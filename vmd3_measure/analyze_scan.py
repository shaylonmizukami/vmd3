"""
analyze_scan.py — Post-process a V-MD3 horizontal scan session.

Reads scan_log.csv to find all captures, processes each .bin into a single
range-angle heatmap (averaged across frames), extracts the peak in a window
around the plate's range, and produces summary plots:

    1. Peak magnitude (dB rel. to scan peak) vs. scan position    [the main result]
    2. Peak angle vs. scan position                               [geometry sanity check]
    3. 2D scan-position-vs-range image

Outputs (saved alongside scan_log.csv):
    results.csv              — per-capture numerical results
    plot_pattern.png         — main result plot
    plot_angle.png           — peak angle vs scan position
    plot_2d_image.png        — 2D image

Usage:
    python analyze_scan.py --session data/FolderWithBinaryDataFolder
    python analyze_scan.py --session data/FolderWithBinaryDataFolder --show
"""

from lib.vmd3 import VMD3

import sys
import os
import csv
import argparse
import numpy as np
import math
import matplotlib.pyplot as plt


# ─── Configuration ───────────────────────────────────────────────
RSET_CONFIG = 0          # 2D, 6m max range, 4.69 cm range bin
MAX_ANGLE_RANGE = 67     # Degrees, V-MD3 azimuth FOV
MAX_RANGE_M = 6          # Mode 0 max range

SKIP_FIRST_FRAMES = 5    # Discard initial transient frames
MAX_FRAMES_USED = 60     # Cap on how many frames to average per capture

# Range window around the auto-detected plate range
RANGE_WINDOW_HALF_M = 1   # ±15 cm window

# Where to estimate the noise floor (range bins far from the target)
NOISE_FLOOR_RANGE_M = (4.0, 5.5)
# ─────────────────────────────────────────────────────────────────


def load_bin_frames(filepath):
    """Read a .bin file and return a list of RADC payloads (frames stripped of headers)."""
    with open(filepath, 'rb') as f:
        data = f.read()

    payloads = []
    search_index = 0
    while True:
        idx = data.find(b'RADC', search_index)
        if idx == -1:
            break
        if idx + 8 > len(data):
            break
        payload_len = int.from_bytes(data[idx + 4:idx + 8], byteorder='little')
        if idx + 8 + payload_len > len(data):
            break
        payloads.append(data[idx + 8:idx + 8 + payload_len])
        search_index = idx + 8 + payload_len

    return payloads


def compute_range_angle_heatmap(payloads, vmd3):
    """Average multiple frames into one range-angle heatmap.

    Returns a numpy array shaped (n_range_bins, n_angle_bins), with magnitude
    in linear units. Returns None if no usable frames were found.
    """
    # Drop early transient frames
    if len(payloads) > SKIP_FIRST_FRAMES:
        payloads = payloads[SKIP_FIRST_FRAMES:]
    if len(payloads) > MAX_FRAMES_USED:
        payloads = payloads[:MAX_FRAMES_USED]
    if len(payloads) == 0:
        return None

    accumulator = None
    n_used = 0

    for payload in payloads:
        cube = vmd3.decode_radc_2d(payload)
        if cube is None:
            cube = vmd3.decode_radc_3d(payload)
        if cube is None:
            continue

        fft_range = np.fft.fft(cube, axis=0)
        fft_doppler = np.fft.fftshift(np.fft.fft(fft_range, axis=1), axes=1)
        fft_angle = np.fft.fftshift(np.fft.fft(fft_doppler, n=128, axis=2), axes=2)
        # Sum magnitude across the Doppler axis → range × angle (linear)
        range_angle = np.sum(np.abs(fft_angle), axis=1)
        range_angle = np.squeeze(range_angle)
        # Shape is (range_bins, angle_bins) — keep that orientation

        if accumulator is None:
            accumulator = range_angle.astype(np.float64)
        else:
            accumulator += range_angle
        n_used += 1

    if n_used == 0:
        return None, 0

    accumulator /= n_used
    return accumulator, n_used


def axis_value(idx, n_bins, axis_min, axis_max):
    """Convert a bin index into the physical axis value."""
    if n_bins <= 1:
        return axis_min
    return axis_min + (axis_max - axis_min) * idx / (n_bins - 1)


def value_to_bin(value, n_bins, axis_min, axis_max):
    """Convert a physical axis value into the nearest bin index, clamped."""
    if axis_max == axis_min:
        return 0
    frac = (value - axis_min) / (axis_max - axis_min)
    idx = int(round(frac * (n_bins - 1)))
    return max(0, min(n_bins - 1, idx))


def estimate_plate_range(heatmap):
    """Auto-detect the plate's range from the boresight capture.

    Find the strongest peak in the heatmap, excluding the near-range
    leakage zone (first ~30 cm), and return its range in meters.
    """
    n_range_bins, n_angle_bins = heatmap.shape

    # Mask out near-range leakage zone
    leakage_cutoff_bin = value_to_bin(0.3, n_range_bins, 0, MAX_RANGE_M)
    masked = heatmap.copy()
    masked[:leakage_cutoff_bin, :] = 0

    # Find the strongest bin
    r_bin, a_bin = np.unravel_index(np.argmax(masked), masked.shape)
    plate_range_m = axis_value(r_bin, n_range_bins, 0, MAX_RANGE_M)
    return plate_range_m


def extract_peak_in_window(heatmap, range_center_m, range_half_m):
    """Return (peak_magnitude, peak_range_m, peak_angle_deg) within a range window."""
    n_range_bins, n_angle_bins = heatmap.shape

    r_min_bin = value_to_bin(
        max(0, range_center_m - range_half_m), n_range_bins, 0, MAX_RANGE_M
    )
    r_max_bin = value_to_bin(
        min(MAX_RANGE_M, range_center_m + range_half_m), n_range_bins, 0, MAX_RANGE_M
    )

    window = heatmap[r_min_bin:r_max_bin + 1, :]
    if window.size == 0:
        return 0.0, range_center_m, 0.0

    local_r, local_a = np.unravel_index(np.argmax(window), window.shape)
    peak_mag = window[local_r, local_a]

    peak_range_m = axis_value(
        r_min_bin + local_r, n_range_bins, 0, MAX_RANGE_M
    )
    peak_angle_deg = axis_value(
        local_a, n_angle_bins, -MAX_ANGLE_RANGE, MAX_ANGLE_RANGE
    )
    return peak_mag, peak_range_m, peak_angle_deg


def estimate_noise_floor(heatmap):
    """Mean magnitude in a far-range strip — used as noise reference."""
    n_range_bins, n_angle_bins = heatmap.shape
    r_min = value_to_bin(NOISE_FLOOR_RANGE_M[0], n_range_bins, 0, MAX_RANGE_M)
    r_max = value_to_bin(NOISE_FLOOR_RANGE_M[1], n_range_bins, 0, MAX_RANGE_M)
    strip = heatmap[r_min:r_max + 1, :]
    if strip.size == 0:
        return 1e-9
    return float(np.mean(strip))


def main(session_dir, show_plots):
    session_dir = os.path.abspath(session_dir)
    csv_path = os.path.join(session_dir, 'scan_log.csv')
    bins_dir = os.path.join(session_dir, 'bins')

    if not os.path.exists(csv_path):
        print(f'[analyze] ERROR: scan_log.csv not found at {csv_path}')
        sys.exit(1)
    if not os.path.isdir(bins_dir):
        print(f'[analyze] ERROR: bins/ directory not found at {bins_dir}')
        sys.exit(1)

    # ─── Load scan log ──────────────────────────────────────
    captures = []   # list of dicts: filename, scan_pos_cm, n_frames
    with open(csv_path, 'r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            try:
                scan_pos = int(row['scan_pos_cm'])
            except (ValueError, KeyError):
                continue
            captures.append({
                'filename': row['filename'],
                'scan_pos_cm': scan_pos,
                'n_frames_logged': int(row.get('n_frames', 0) or 0),
            })

    if len(captures) == 0:
        print('[analyze] ERROR: no captures found in scan_log.csv')
        sys.exit(1)

    # If a position was recaptured, keep the last one (most recent row wins)
    seen = {}
    for c in captures:
        seen[c['scan_pos_cm']] = c
    captures = sorted(seen.values(), key=lambda c: c['scan_pos_cm'])

    print(f'[analyze] Found {len(captures)} unique scan positions in CSV.')

    # ─── Decoder helper (we don't actually connect over network) ───
    vmd3 = VMD3(standalone=True)

    # ─── Pass 1: process every capture, store heatmaps ──────
    heatmaps = []      # parallel to captures
    for c in captures:
        path = os.path.join(bins_dir, c['filename'])
        if not os.path.exists(path):
            print(f'[analyze]   {c["filename"]}: FILE MISSING, skipping')
            heatmaps.append(None)
            continue

        payloads = load_bin_frames(path)
        result = compute_range_angle_heatmap(payloads, vmd3)
        if result is None or result[0] is None:
            print(f'[analyze]   {c["filename"]}: no usable frames')
            heatmaps.append(None)
            continue
        heatmap, n_used = result
        heatmaps.append((heatmap, n_used))
        print(f'[analyze]   {c["filename"]:<24}  pos={c["scan_pos_cm"]:+4d} cm  '
              f'frames_used={n_used}')

    # ─── Auto-detect plate range from the boresight capture ──
    # Find capture closest to 0 cm
    sorted_by_dist_to_zero = sorted(
        range(len(captures)),
        key=lambda i: abs(captures[i]['scan_pos_cm'])
    )
    plate_range_m = None
    for i in sorted_by_dist_to_zero:
        if heatmaps[i] is not None:
            plate_range_m = estimate_plate_range(heatmaps[i][0])
            print(f'[analyze] Auto-detected plate range from '
                  f'{captures[i]["filename"]} ({captures[i]["scan_pos_cm"]:+d} cm): '
                  f'{plate_range_m:.3f} m')
            break

    if plate_range_m is None:
        print('[analyze] ERROR: could not auto-detect plate range '
              '(no usable boresight capture)')
        sys.exit(1)

    # ─── Pass 2: extract peak in range window for each capture ──
    results = []
    for c, hm in zip(captures, heatmaps):
        if hm is None:
            results.append(None)
            continue
        heatmap, n_used = hm
        peak_mag, peak_range, peak_angle = extract_peak_in_window(
            heatmap, plate_range_m, RANGE_WINDOW_HALF_M
        )
        noise_floor = estimate_noise_floor(heatmap)
        results.append({
            'scan_pos_cm': c['scan_pos_cm'],
            'filename': c['filename'],
            'peak_magnitude_linear': float(peak_mag),
            'peak_range_m': float(peak_range),
            'peak_angle_deg': float(peak_angle),
            'noise_floor_linear': float(noise_floor),
            'n_frames_averaged': int(n_used),
        })

    valid_results = [r for r in results if r is not None]
    if len(valid_results) == 0:
        print('[analyze] ERROR: no valid results to plot')
        sys.exit(1)

    # ─── Normalize: dB relative to scan peak ────────────────
    scan_peak_linear = max(r['peak_magnitude_linear'] for r in valid_results)
    if scan_peak_linear <= 0:
        print('[analyze] ERROR: scan peak magnitude is zero')
        sys.exit(1)

    for r in valid_results:
        r['peak_magnitude_db'] = (
            20 * math.log10(max(r['peak_magnitude_linear'], 1e-12) / scan_peak_linear)
        )
        r['noise_floor_db'] = (
            20 * math.log10(max(r['noise_floor_linear'], 1e-12) / scan_peak_linear)
        )

    # ─── Write results.csv ──────────────────────────────────
    results_path = os.path.join(session_dir, 'results.csv')
    with open(results_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            'scan_pos_cm', 'filename', 'peak_magnitude_linear',
            'peak_magnitude_db', 'peak_range_m', 'peak_angle_deg',
            'noise_floor_linear', 'noise_floor_db', 'n_frames_averaged',
        ])
        for r in valid_results:
            writer.writerow([
                r['scan_pos_cm'], r['filename'],
                f'{r["peak_magnitude_linear"]:.4f}',
                f'{r["peak_magnitude_db"]:.2f}',
                f'{r["peak_range_m"]:.3f}',
                f'{r["peak_angle_deg"]:+.2f}',
                f'{r["noise_floor_linear"]:.4f}',
                f'{r["noise_floor_db"]:.2f}',
                r['n_frames_averaged'],
            ])
    print(f'[analyze] Wrote {results_path}')

    # ─── Plot 1: peak magnitude (dB) vs. scan position ──────
    positions = [r['scan_pos_cm'] for r in valid_results]
    peaks_db = [r['peak_magnitude_db'] for r in valid_results]
    noise_db_avg = np.mean([r['noise_floor_db'] for r in valid_results])

    fig1, ax1 = plt.subplots(figsize=(9, 5))
    ax1.plot(positions, peaks_db, 'o-', color='#1f77b4', linewidth=1.5,
             markersize=6, label='Measured peak')
    ax1.axhline(noise_db_avg, color='gray', linestyle='--', linewidth=1,
                label=f'Mean noise floor ({noise_db_avg:.1f} dB)')
    ax1.set_xlabel('Scan position (cm)')
    ax1.set_ylabel('Peak magnitude (dB relative to scan max)')
    ax1.set_title(
        f'Plate specular pattern  —  range {plate_range_m:.2f} m, '
        f'18×20 cm plate'
    )
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='lower center')
    fig1.tight_layout()
    plot1_path = os.path.join(session_dir, 'plot_pattern.png')
    fig1.savefig(plot1_path, dpi=120)
    print(f'[analyze] Wrote {plot1_path}')

    # ─── Plot 2: peak angle vs. scan position ───────────────
    angles = [r['peak_angle_deg'] for r in valid_results]
    # Predicted angle: arctan(scan_pos / plate_range)
    predicted = [
        math.degrees(math.atan(p / 100.0 / plate_range_m)) for p in positions
    ]

    fig2, ax2 = plt.subplots(figsize=(9, 5))
    ax2.plot(positions, angles, 'o-', color='#2ca02c', linewidth=1.5,
             markersize=6, label='Measured peak angle')
    ax2.plot(positions, predicted, '--', color='black', linewidth=1,
             alpha=0.6, label='Predicted geometry')
    ax2.set_xlabel('Scan position (cm)')
    ax2.set_ylabel('Peak angle in heatmap (deg)')
    ax2.set_title('Peak angle vs. scan position (geometry sanity check)')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='best')
    fig2.tight_layout()
    plot2_path = os.path.join(session_dir, 'plot_angle.png')
    fig2.savefig(plot2_path, dpi=120)
    print(f'[analyze] Wrote {plot2_path}')

    # ─── Plot 3: 2D image — scan position × range ───────────
    # For each capture, take the angle slice at the peak's angle (or sum across angles)
    # and stack into a 2D image. Using sum-across-angles to be robust.
    image_rows = []
    n_range_bins = None
    for c, hm in zip(captures, heatmaps):
        if hm is None:
            if n_range_bins is not None:
                image_rows.append(np.zeros(n_range_bins))
            continue
        heatmap, _ = hm
        if n_range_bins is None:
            n_range_bins = heatmap.shape[0]
        # Sum magnitude across angles → 1D range profile
        range_profile = np.sum(heatmap, axis=1)
        image_rows.append(range_profile)

    if len(image_rows) > 0 and n_range_bins is not None:
        # Pad any missing rows
        image_rows = [
            r if len(r) == n_range_bins else np.zeros(n_range_bins)
            for r in image_rows
        ]
        image = np.array(image_rows).T   # shape: (range_bins, n_captures)
        # Normalize to scan peak then convert to dB
        image_max = np.max(image)
        if image_max > 0:
            image_db = 20 * np.log10(
                np.maximum(image / image_max, 1e-5)
            )
        else:
            image_db = image

        fig3, ax3 = plt.subplots(figsize=(10, 5))
        all_positions = [c['scan_pos_cm'] for c in captures]
        im = ax3.imshow(
            image_db,
            aspect='auto',
            origin='lower',
            extent=[
                min(all_positions) - 1, max(all_positions) + 1,
                0, MAX_RANGE_M
            ],
            cmap='inferno',
            vmin=-40, vmax=0,
        )
        ax3.set_xlabel('Scan position (cm)')
        ax3.set_ylabel('Range (m)')
        ax3.set_title('Range profile across scan')
        ax3.axhline(plate_range_m, color='cyan', linestyle=':', linewidth=1,
                    alpha=0.7, label=f'Plate range ({plate_range_m:.2f} m)')
        ax3.legend(loc='upper right')
        fig3.colorbar(im, ax=ax3, label='dB')
        fig3.tight_layout()
        plot3_path = os.path.join(session_dir, 'plot_2d_image.png')
        fig3.savefig(plot3_path, dpi=120)
        print(f'[analyze] Wrote {plot3_path}')

    # ─── Print summary ──────────────────────────────────────
    print()
    print('─── Summary ────────────────────────────────────────────')
    print(f'Auto-detected plate range:   {plate_range_m:.3f} m')
    print(f'Range window for peak:       ±{RANGE_WINDOW_HALF_M*100:.0f} cm')
    print(f'Scan peak position:          '
          f'{positions[int(np.argmax(peaks_db))]:+d} cm')
    print(f'Mean noise floor:            {noise_db_avg:.1f} dB rel. to peak')
    print(f'Number of captures plotted:  {len(valid_results)}')
    print()

    if show_plots:
        plt.show()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Post-process a V-MD3 horizontal scan session'
    )
    parser.add_argument(
        '--session', type=str, required=True,
        help='Path to the session folder '
             '(e.g. data/scan_2026-05-18). Must contain scan_log.csv and bins/'
    )
    parser.add_argument(
        '--show', action='store_true',
        help='Display plots interactively (in addition to saving PNGs)'
    )
    args = parser.parse_args()
    main(args.session, args.show)