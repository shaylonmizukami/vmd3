"""
sar_a.py — Option A, Step 1: single-station range-angle image.

Decode ONE .bin capture, beamform the 4 RX channels across azimuth,
and plot one range x angle image. This is the piece analyze_scan.py
computes internally but throws away (it only kept the peak).

Usage:
    python sar_a.py --bin data/scan_2026-05-19/bins/scan_0cm.bin --show
"""

import argparse
import csv
import math
import os

import matplotlib.pyplot as plt
import numpy as np
from lib.vmd3 import VMD3

# ─── Constants (RSET 0) ──────────────────────────────────────────
RANGE_BIN_M = 4.69e-2          # m per range bin
N_RANGE_BINS = 128
MAX_RANGE_M = N_RANGE_BINS * RANGE_BIN_M
MAX_ANGLE_DEG = 67             # azimuth FOV
N_ANGLE_BINS = 181            # beamform resolution (-67..+67 in ~0.75 deg steps)

SKIP_FIRST_FRAMES = 5
MAX_FRAMES_USED = 30

# ─── Option A image grid (meters) ────────────────────────────────
GRID_X_HALF = 2.0      # cross-range span: -2.0 .. +2.0 m
GRID_X_STEP = 0.02
GRID_Y_MIN = 0.3       # skip the leakage zone
GRID_Y_MAX = 2.0
GRID_Y_STEP = 0.02
# ─────────────────────────────────────────────────────────────────

def load_bin_frames(filepath):
    """Read a .bin file, return a list of RADC payloads (headers stripped)."""
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

def station_range_angle(payloads):
    """Beamform one capture into a (range, angle) magnitude image.

    Returns (image, angles_deg) where image is shape (N_RANGE_BINS, N_ANGLE_BINS),
    magnitude in linear units. Coherently averages chirps within the capture,
    then beamforms the 4 RX channels across azimuth angles.
    """
    vmd3 = VMD3(standalone=True)

    if len(payloads) > SKIP_FIRST_FRAMES:
        payloads = payloads[SKIP_FIRST_FRAMES:]
    if len(payloads) > MAX_FRAMES_USED:
        payloads = payloads[:MAX_FRAMES_USED]

    angles = np.linspace(-MAX_ANGLE_DEG, MAX_ANGLE_DEG, N_ANGLE_BINS)

    acc = None
    n_used = 0
    for payload in payloads:
        cube = vmd3.decode_radc_2d(payload)          # (128, 64, 4)
        if cube is None:
            continue
        rp = np.fft.fft(cube, axis=0)                # range FFT -> (range, chirps, rx)
        rp = np.mean(rp, axis=1)                      # coherent avg over chirps -> (range, rx)

        # Beamform: for each angle, phase-steer the 4 channels and sum
        nRx = rp.shape[1]
        img = np.zeros((N_RANGE_BINS, N_ANGLE_BINS), dtype=np.complex128)
        for ai, alpha in enumerate(angles):
            steer = np.array([
                np.exp(-1j * np.pi * n * np.sin(np.radians(alpha)))
                for n in range(nRx)
            ])
            img[:, ai] = rp @ steer                   # (range,) beam at this angle

        if acc is None:
            acc = np.abs(img)
        else:
            acc += np.abs(img)
        n_used += 1

    if n_used == 0:
        return None, angles
    return acc / n_used, angles


def load_scan_log(session_dir):
    """Parse scan_log.csv -> sorted list of (x_pos_m, bin_filepath)."""
    csv_path = os.path.join(session_dir, 'scan_log.csv')
    bins_dir = os.path.join(session_dir, 'bins')
    rows = {}
    with open(csv_path, 'r', newline='') as f:
        for row in csv.DictReader(f):
            try:
                pos_cm = int(row['scan_pos_cm'])
            except (ValueError, KeyError):
                continue
            rows[pos_cm] = row['filename']          # last row wins
    stations = []
    for pos_cm in sorted(rows):
        path = os.path.join(bins_dir, rows[pos_cm])
        if os.path.exists(path):
            stations.append((pos_cm / 100.0, path))
        else:
            print(f'[sar_a]   {rows[pos_cm]}: MISSING, skipping')
    return stations


def build_scene(session_dir):
    """Assemble all stations' range-angle images onto one (x, y) grid.

    For each station at x_stn, every (range R, angle theta) cell is placed at
    world coords  x = x_stn + R*sin(theta),  y = R*cos(theta),  and its
    magnitude added into the grid (incoherent / real-aperture combining).
    """
    stations = load_scan_log(session_dir)
    print(f'[sar_a] Combining {len(stations)} stations.')

    xs = np.arange(-GRID_X_HALF, GRID_X_HALF + 1e-9, GRID_X_STEP)
    ys = np.arange(GRID_Y_MIN, GRID_Y_MAX + 1e-9, GRID_Y_STEP)
    grid = np.zeros((len(ys), len(xs)))
    counts = np.zeros((len(ys), len(xs)))

    range_axis = np.arange(N_RANGE_BINS) * RANGE_BIN_M

    for x_stn, path in stations:
        payloads = load_bin_frames(path)
        img, angles = station_range_angle(payloads)   # (range, angle) magnitude
        if img is None:
            print(f'[sar_a]   {os.path.basename(path)}: no frames, skipping')
            continue

        # Scatter every (range, angle) cell into the (x, y) grid
        ang_rad = np.radians(angles)
        for ai in range(len(angles)):
            sin_a = np.sin(ang_rad[ai])
            cos_a = np.cos(ang_rad[ai])
            wx = x_stn + range_axis * sin_a            # world x for each range bin
            wy = range_axis * cos_a                    # world y for each range bin
            col = np.round((wx - xs[0]) / GRID_X_STEP).astype(int)
            rowi = np.round((wy - ys[0]) / GRID_Y_STEP).astype(int)
            valid = (col >= 0) & (col < len(xs)) & (rowi >= 0) & (rowi < len(ys))
            grid[rowi[valid], col[valid]] += img[valid, ai]
            counts[rowi[valid], col[valid]] += 1

        print(f'[sar_a]   station x={x_stn:+.2f} m  placed')

    # Average where multiple stations overlap (avoids edge brightening)
    grid = np.where(counts > 0, grid / np.maximum(counts, 1), 0)
    return xs, ys, grid


def plot_scene(session_dir, show, save):
    xs, ys, grid = build_scene(session_dir)
    grid_db = 20 * np.log10(np.maximum(grid / grid.max(), 1e-4))

    fig, ax = plt.subplots(figsize=(9, 7))
    im = ax.imshow(
        grid_db, aspect='equal', origin='lower',
        extent=[xs[0], xs[-1], ys[0], ys[-1]],
        cmap='inferno', vmin=-30, vmax=0,
    )
    ax.set_xlabel('Cross-range (m)')
    ax.set_ylabel('Down-range (m)')
    ax.set_title('Option A: real-aperture swept image')
    ax.plot(0, 1.5, 'c+', markersize=12, label='expected plate')
    ax.legend(loc='upper right')
    fig.colorbar(im, ax=ax, label='dB rel. peak')
    fig.tight_layout()

    if save:
        out = os.path.join(session_dir, 'sar_a_scene.png')
        fig.savefig(out, dpi=120)
        print(f'[sar_a] Wrote {out}')
    if show:
        plt.show()


def main(bin_path, show, save):
    payloads = load_bin_frames(bin_path)
    print(f'[sar_a] Loaded {len(payloads)} frames from {bin_path}')

    image, angles = station_range_angle(payloads)
    if image is None:
        print('[sar_a] ERROR: no usable frames')
        return

    # Convert to dB relative to this station's peak
    img_db = 20 * np.log10(np.maximum(image / image.max(), 1e-4))

    # Report the peak
    r_bin, a_bin = np.unravel_index(np.argmax(image), image.shape)
    print(f'[sar_a] Peak at range {r_bin * RANGE_BIN_M:.2f} m, '
          f'angle {angles[a_bin]:+.1f} deg')

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(
        img_db, aspect='auto', origin='lower',
        extent=[angles[0], angles[-1], 0, MAX_RANGE_M],
        cmap='inferno', vmin=-30, vmax=0,
    )
    ax.set_xlabel('Azimuth angle (deg)')
    ax.set_ylabel('Range (m)')
    ax.set_title(f'Single-station range-angle image\n{bin_path}')
    fig.colorbar(im, ax=ax, label='dB rel. peak')
    fig.tight_layout()

    if save:
        out = bin_path.replace('.bin', '_rangeangle.png')
        fig.savefig(out, dpi=120)
        print(f'[sar_a] Wrote {out}')
    if show:
        plt.show()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Option A: real-aperture swept image')
    p.add_argument('--bin', help='Single .bin (Step 1: one range-angle image)')
    p.add_argument('--session', help='Session folder (Step 2: full swept scene)')
    p.add_argument('--show', action='store_true', help='Display the plot')
    p.add_argument('--save', action='store_true', help='Save the plot as PNG')
    args = p.parse_args()

    if args.session:
        plot_scene(args.session, args.show, args.save)
    elif args.bin:
        main(args.bin, args.show, args.save)
    else:
        p.error('give either --bin (Step 1) or --session (Step 2)')