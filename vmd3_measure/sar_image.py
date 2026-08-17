"""
sar_image.py — Backprojection SAR imaging from a V-MD3 lateral sweep.

Forms a 2D down-range x cross-range image from a 1D synthetic aperture
(the 21-position wall sweep). Reuses the decode path from analyze_scan.py.

Pipeline layers (enable via flags):
    Layer 1 (default):  raw backprojection — the actual capability test
    Layer 2 (--ref-fix): per-station phase correction using the plate bin
                         as a reference reflector (use if layer 1 is noise)
    Layer 3 (--pga):     phase-gradient autofocus to sharpen residual blur

Usage:
    python sar_image.py --session data/scan_2026-05-18
    python sar_image.py --session data/scan_2026-05-18 --ref-fix
    python sar_image.py --session data/scan_2026-05-18 --ref-fix --pga --show
"""

import argparse
import csv
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
from analyze_scan import load_bin_frames  # reuse your exact .bin parser
from lib.vmd3 import VMD3

# ─── Radar / geometry constants ──────────────────────────────────
C = 300000000.0          # m/s
F_C = 61.0e9               # Hz, V-MD3 center frequency (RSET 0/1 band)
LAMBDA = C / F_C           # ~4.91 mm
RANGE_BIN_M = 4.69e-2      # m per range bin (RSET 0)
N_RANGE_BINS = 128
MAX_RANGE_M = N_RANGE_BINS * RANGE_BIN_M

SKIP_FIRST_FRAMES = 5      # discard transient frames (matches analyze_scan)
MAX_FRAMES_USED = 80

# Scene geometry: radar sweeps along x at y=0; plate is downrange at +y.
PLATE_STANDOFF_M = 1.50    # nominal; refined per-session from the data
PLATE_CROSSRANGE_M = 0.0   # plate assumed centered on the scan line

# Image grid (meters). x = cross-range, y = down-range.
GRID_X_HALF = 1.20         # sweep is ±1.0 m, pad a little past the aperture
GRID_X_STEP = 0.01
GRID_Y_MIN = 1.00
GRID_Y_MAX = 2.20          # off-center stations see the plate at longer slant range
GRID_Y_STEP = 0.01
# ─────────────────────────────────────────────────────────────────


def station_range_profile(payloads):
    """Coherently average frames+chirps into one complex range profile.

    Returns a complex array of shape (N_RANGE_BINS,) — the per-station
    range profile, phase preserved. Averages Rx channels coherently too
    (treats the 4-element array as a single phase center for 1D SAR).
    Returns None if no usable frames.
    """
    vmd3 = VMD3(standalone=True)

    if len(payloads) > SKIP_FIRST_FRAMES:
        payloads = payloads[SKIP_FIRST_FRAMES:]
    if len(payloads) > MAX_FRAMES_USED:
        payloads = payloads[:MAX_FRAMES_USED]
    if len(payloads) == 0:
        return None

    acc = None
    n_used = 0
    for payload in payloads:
        cube = vmd3.decode_radc_2d(payload)
        if cube is None:
            cube = vmd3.decode_radc_3d(payload)
        if cube is None:
            continue
        # Range FFT (complex), then coherent average over chirps and Rx.
        rp = np.fft.fft(cube, axis=0)        # (range, chirps, rx)
        rp = np.mean(rp, axis=1)             # coherent avg over chirps -> (range, rx)
        rp = np.mean(rp, axis=1)             # coherent avg over rx     -> (range,)
        if acc is None:
            acc = rp.astype(np.complex128)
        else:
            acc += rp
        n_used += 1

    if n_used == 0:
        return None
    return acc / n_used


def load_session(session_dir):
    """Read scan_log.csv, return sorted list of (x_pos_m, complex_profile)."""
    csv_path = os.path.join(session_dir, 'scan_log.csv')
    bins_dir = os.path.join(session_dir, 'bins')
    if not os.path.exists(csv_path):
        print(f'[sar] ERROR: scan_log.csv not found at {csv_path}')
        sys.exit(1)

    rows = {}
    with open(csv_path, 'r', newline='') as f:
        for row in csv.DictReader(f):
            try:
                pos_cm = int(row['scan_pos_cm'])
            except (ValueError, KeyError):
                continue
            rows[pos_cm] = row['filename']   # last row wins for a position

    stations = []
    for pos_cm in sorted(rows):
        path = os.path.join(bins_dir, rows[pos_cm])
        if not os.path.exists(path):
            print(f'[sar]   {rows[pos_cm]}: MISSING, skipping')
            continue
        profile = station_range_profile(load_bin_frames(path))
        if profile is None:
            print(f'[sar]   {rows[pos_cm]}: no usable frames, skipping')
            continue
        stations.append((pos_cm / 100.0, profile))   # cm -> m
        print(f'[sar]   pos {pos_cm:+4d} cm  loaded  '
              f'(plate-bin mag {np.abs(profile[32]):.1f})')

    if len(stations) < 3:
        print('[sar] ERROR: need at least 3 usable stations')
        sys.exit(1)
    return stations


def detect_plate_bin(stations):
    """Find the range bin of the plate from the most central station."""
    x_abs = [abs(x) for x, _ in stations]
    cx = int(np.argmin(x_abs))
    prof = np.abs(stations[cx][1])
    # ignore near-range leakage (first ~30 cm)
    lo = int(0.30 / RANGE_BIN_M)
    bin_idx = lo + int(np.argmax(prof[lo:]))
    print(f'[sar] Plate detected at bin {bin_idx} '
          f'({bin_idx * RANGE_BIN_M:.3f} m) from station x={stations[cx][0]:+.2f} m')
    return bin_idx


def reference_phase_fix(stations, plate_bin):
    """Layer 2: tie stations to a common phase reference.

    Removes the measured phase at the plate bin from each station's whole
    profile, then re-adds the *geometric* phase that station should have
    for a scatterer at (PLATE_CROSSRANGE_M, plate_range). This forces
    inter-capture phase consistency using the plate as a known anchor.
    """
    plate_range = plate_bin * RANGE_BIN_M
    fixed = []
    for x, prof in stations:
        measured_phase = np.angle(prof[plate_bin])
        R = np.hypot(x - PLATE_CROSSRANGE_M, plate_range)   # one-way
        geom_phase = -2.0 * (2 * np.pi / LAMBDA) * R        # round-trip
        correction = np.exp(-1j * measured_phase) * np.exp(1j * geom_phase)
        fixed.append((x, prof * correction))
    print('[sar] Applied reference-based per-station phase correction.')
    return fixed


def backproject(stations, plate_bin):
    """Layer 1: coherent backprojection onto the (x, y) grid."""
    xs = np.arange(-GRID_X_HALF, GRID_X_HALF + 1e-9, GRID_X_STEP)
    ys = np.arange(GRID_Y_MIN, GRID_Y_MAX + 1e-9, GRID_Y_STEP)
    image = np.zeros((len(ys), len(xs)), dtype=np.complex128)

    range_axis = np.arange(N_RANGE_BINS) * RANGE_BIN_M
    k = 2 * np.pi / LAMBDA

    for x_rdr, prof in stations:
        # interpolate complex profile (real & imag separately) vs range
        for iy, y in enumerate(ys):
            R = np.hypot(xs - x_rdr, y)                 # one-way range to each pixel
            re = np.interp(R, range_axis, prof.real, left=0, right=0)
            im = np.interp(R, range_axis, prof.imag, left=0, right=0)
            s = re + 1j * im
            phase = np.exp(1j * 2 * k * R)              # round-trip phase comp
            image[iy, :] += s * phase
    print(f'[sar] Backprojected {len(stations)} stations onto '
          f'{len(ys)}x{len(xs)} grid.')
    return xs, ys, image


def pga(stations, plate_bin, n_iter=3):
    """Layer 3: minimal phase-gradient autofocus.

    Estimates one phase error per station from the dominant scatterer and
    removes it. Crude 1D-aperture version; sharpens residual position blur.
    """
    profiles = np.array([p for _, p in stations])      # (n_stn, n_range)
    xs = np.array([x for x, _ in stations])
    for _ in range(n_iter):
        # dominant scatterer = plate bin; phase history across stations
        ph = profiles[:, plate_bin]
        # center (remove the geometric trend by referencing to magnitude-weighted mean)
        est = np.angle(ph)
        est -= np.mean(est)
        corr = np.exp(-1j * est)
        profiles = profiles * corr[:, None]
    fixed = [(xs[i], profiles[i]) for i in range(len(xs))]
    print(f'[sar] PGA applied ({n_iter} iterations).')
    return fixed


def main(session_dir, use_ref_fix, use_pga, show):
    session_dir = os.path.abspath(session_dir)
    stations = load_session(session_dir)
    plate_bin = detect_plate_bin(stations)

    if use_ref_fix:
        stations = reference_phase_fix(stations, plate_bin)
    if use_pga:
        stations = pga(stations, plate_bin)

    xs, ys, image = backproject(stations, plate_bin)
    mag = np.abs(image)
    mag_db = 20 * np.log10(np.maximum(mag / mag.max(), 1e-4))

    # ─── 2D focused image ───────────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 7))
    im = ax.imshow(
        mag_db, aspect='equal', origin='lower',
        extent=[xs[0], xs[-1], ys[0], ys[-1]],
        cmap='inferno', vmin=-30, vmax=0,
    )
    ax.set_xlabel('Cross-range (m)')
    ax.set_ylabel('Down-range (m)')
    ax.set_title('V-MD3 backprojection SAR image'
                 + ('  [ref-fix]' if use_ref_fix else '')
                 + ('  [pga]' if use_pga else ''))
    ax.plot(PLATE_CROSSRANGE_M, plate_bin * RANGE_BIN_M, 'c+',
            markersize=12, label='expected plate')
    ax.legend(loc='upper right')
    fig.colorbar(im, ax=ax, label='dB')
    fig.tight_layout()
    out2d = os.path.join(session_dir, 'sar_image_2d.png')
    fig.savefig(out2d, dpi=120)
    print(f'[sar] Wrote {out2d}')

    # ─── 1D cross-range cut at the plate's down-range ───────
    iy_plate = int(np.argmin(np.abs(ys - plate_bin * RANGE_BIN_M)))
    cut = mag_db[iy_plate, :]
    fig2, ax2 = plt.subplots(figsize=(9, 4))
    ax2.plot(xs, cut, color='#1f77b4')
    ax2.axvline(PLATE_CROSSRANGE_M, color='gray', linestyle='--',
                label='expected plate cross-range')
    ax2.set_xlabel('Cross-range (m)')
    ax2.set_ylabel('Magnitude (dB rel. peak)')
    ax2.set_title(f'Cross-range cut at down-range {ys[iy_plate]:.2f} m')
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    fig2.tight_layout()
    out1d = os.path.join(session_dir, 'sar_crossrange_cut.png')
    fig2.savefig(out1d, dpi=120)
    print(f'[sar] Wrote {out1d}')

    print()
    print('─── Interpreting the result ─────────────────────────────')
    print('  If energy concentrates near the cyan + (cross-range 0,')
    print(f'  down-range {plate_bin*RANGE_BIN_M:.2f} m): the radar supports SAR.')
    print('  If it smears across cross-range but sits at the right')
    print('  down-range: inter-capture phase is the issue -> try --ref-fix.')
    print('  If --ref-fix sharpens it: phase WAS the problem (expected).')
    print('  Then --pga to clean up residual position blur.')
    print()

    if show:
        plt.show()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='V-MD3 backprojection SAR imaging')
    p.add_argument('--session', required=True,
                   help='Session folder with scan_log.csv and bins/')
    p.add_argument('--ref-fix', action='store_true',
                   help='Layer 2: reference-based per-station phase correction')
    p.add_argument('--pga', action='store_true',
                   help='Layer 3: phase-gradient autofocus')
    p.add_argument('--show', action='store_true', help='Display plots')
    args = p.parse_args()
    main(args.session, args.ref_fix, args.pga, args.show)