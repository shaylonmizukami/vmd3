"""Find each virtual channel's position and phase calibration from captures of one target at known spots."""

import argparse
import json
from datetime import datetime
import numpy as np

from config import ANGLE_SIGN, CAL_SEARCH_M, HST, LEAKAGE_CUTOFF_M, RANGE_FFT_SIZE, RX_SPACING_M, WAVELENGTH_M
from lib.capture import load_window, to_stem
from lib.dsp import range_axis, zero_doppler_profiles
from radar3d.config3d import GEOMETRY_FILE, N_CHANNELS, N_RX, N_TX, RX_OF_CHANNEL, TX_OF_CHANNEL

K = 2 * np.pi / WAVELENGTH_M

def direction(right, up, forward):
    """Direction cosines (sideways, vertical) to a target and its distance."""
    distance = np.sqrt(right ** 2 + up ** 2 + forward ** 2)
    return np.array([right, up]) / distance, distance

def target_samples(stem, distance):
    """Frame-averaged complex value of each channel at the target's range peak, and that range."""
    payloads, _, meta = load_window(stem)
    if meta["vmd3_setting"]["angle_setting"] != "3D":
        raise SystemExit(f"{to_stem(stem).name} is not a 3D capture")
    profiles = zero_doppler_profiles(payloads, meta, n_fft=RANGE_FFT_SIZE)
    ranges = range_axis(meta, RANGE_FFT_SIZE)

    # Strongest bin near the tape distance, summed over frames and channels
    power = np.sum(np.abs(profiles) ** 2, axis=(0, 2))
    near = np.flatnonzero((np.abs(ranges - distance) <= CAL_SEARCH_M) & (ranges >= LEAKAGE_CUTOFF_M))
    i = near[np.argmax(power[near])]
    return profiles[:, i, :].mean(axis=0), ranges[i]

def wrap(phase):
    """Wrap phase to between -pi and pi."""
    return np.angle(np.exp(1j * phase))

def main(captures, save):
    # Target direction and channel samples for every capture, the first is the reference
    rows, samples, directions = [], [], []
    for stem, right, up, forward in captures:
        u, distance = direction(float(right), float(up), float(forward))
        s, measured = target_samples(stem, distance)
        rows.append((to_stem(stem).name, distance, measured, u))
        samples.append(s)
        directions.append(u)
    samples, directions = np.array(samples), np.array(directions)
    du = directions[1:] - directions[0]
    if len(captures) < 3 or np.linalg.matrix_rank(du, tol=0.02) < 2:
        raise SystemExit("Need a reference capture, plus one moved sideways and one moved up or down")

    # Phase of each channel relative to channel 0, and how it changed from the reference
    phases = np.angle(samples * np.conj(samples[:, :1]))
    dphi = wrap(phases[1:] - phases[0])

    # Channel positions from those changes, then calibration from the reference capture
    positions = np.linalg.lstsq(K * du, dphi, rcond=None)[0].T   # (channels, 2) in m, relative to channel 0
    residual = wrap(dphi - K * du @ positions.T)
    calibration = wrap(phases[0] - K * positions @ directions[0])

    # Where each capture put the target
    for name, distance, measured, u in rows:
        az, el = np.degrees(np.arcsin(u))
        print(f"{name}: tape {distance * 100:.1f} cm, radar {measured * 100:.1f} cm, az {az:+.1f} deg, el {el:+.1f} deg")

    # Per channel position, calibration, and fit residual
    print("\nCh TX RX     x mm     y mm   cal deg   resid deg")
    for c in range(N_CHANNELS):
        rms = np.degrees(np.sqrt(np.mean(residual[:, c] ** 2)))
        print(f"{c:2d}  {TX_OF_CHANNEL[c] + 1}  {RX_OF_CHANNEL[c] + 1}  {positions[c, 0] * 1000:+7.2f}  "
              f"{positions[c, 1] * 1000:+7.2f}  {np.degrees(calibration[c]):+8.1f}  {rms:9.1f}")

    # Checks against the known RX layout
    grid = positions.reshape(N_TX, N_RX, 2)
    spacing = np.diff(grid[:, :, 0], axis=1).mean(axis=1) * 1000
    print(f"\nRX spacing per TX: {np.round(spacing, 2)} mm (expected {-ANGLE_SIGN * RX_SPACING_M * 1000:+.2f})")
    print(f"RX height spread per TX: {np.round(np.ptp(grid[:, :, 1], axis=1) * 1000, 2)} mm (expected near 0)")

    # Each TX's offset from TX1, averaged over its RX
    offsets = (grid - grid[:1]).mean(axis=1)[1:]
    for t, (dx, dy) in enumerate(offsets, start=2):
        print(f"TX{t} from TX1: x {dx * 1000:+.2f} mm ({dx / WAVELENGTH_M:+.2f} λ), "
              f"y {dy * 1000:+.2f} mm ({dy / WAVELENGTH_M:+.2f} λ)")

    # Save for the beamformer
    if save:
        result = {
            "created": datetime.now(HST).isoformat(timespec="seconds"),
            "captures": [{"stem": name, "direction": u.round(5).tolist()} for name, _, _, u in rows],
            "positions_m": positions.round(6).tolist(),
            "calibration_rad": calibration.round(5).tolist(),
            "tx_offsets_m": offsets.round(6).tolist(),
        }
        GEOMETRY_FILE.write_text(json.dumps(result, indent=2))
        print(f"Saved {GEOMETRY_FILE}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find the 3D channel layout from captures of one target at known spots")
    parser.add_argument("--capture", action="append", nargs=4, required=True, metavar=("STEM", "RIGHT", "UP", "FORWARD"),
                        help="Capture and target position in m from the radar center. Give the straight-ahead one first")
    parser.add_argument("--save", action="store_true", help=f"Write the result to radar3d/{GEOMETRY_FILE.name}")
    args = parser.parse_args()

    main(args.capture, args.save)