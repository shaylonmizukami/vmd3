"""Find the 3D transmitter layout and channel calibration from captures of one target at known spots."""

import argparse
import json
from datetime import datetime
import numpy as np

from config import ANGLE_SIGN, CAL_SEARCH_M, HST, LEAKAGE_CUTOFF_M, RANGE_FFT_SIZE, RX_SPACING_M, WAVELENGTH_M
from lib.capture import load_window, to_stem
from lib.dsp import range_axis, zero_doppler_profiles
from radar3d.config3d import GEOMETRY_FILE, N_RX, N_TX

K = 2 * np.pi / WAVELENGTH_M
RX_STEP_M = -ANGLE_SIGN * RX_SPACING_M   # neighboring RX spacing, same sign convention as lib.dsp

# Search grid for each transmitter's offset from TX1
SEARCH_X_M = np.arange(-0.015, 0.015 + 1e-9, 0.00005)
SEARCH_Y_M = np.arange(-0.008, 0.008 + 1e-9, 0.00005)

# IWR6843 style layouts: TX2 two RX steps across and one up or down, TX3 four RX steps across
CANDIDATES = {
    "TX2": [(sx * 2 * RX_SPACING_M, sy * RX_SPACING_M) for sx in (1, -1) for sy in (1, -1)],
    "TX3": [(sx * 4 * RX_SPACING_M, 0.0) for sx in (1, -1)],
}

def mean_profile(stem):
    """Frame-averaged complex profile (range, 12) and range axis for one 3D capture."""
    payloads, _, meta = load_window(stem)
    if meta["vmd3_setting"]["angle_setting"] != "3D":
        raise SystemExit(f"{to_stem(stem).name} is not a 3D capture")
    profiles = zero_doppler_profiles(payloads, meta, n_fft=RANGE_FFT_SIZE)
    return profiles.mean(axis=0), range_axis(meta, RANGE_FFT_SIZE)

def target_samples(stem, distance, background):
    """Channel values at the target's range peak after background subtraction, its range, and target to clutter in dB."""
    profile, ranges = mean_profile(stem)
    if background is not None:
        profile = profile - background
    power = np.sum(np.abs(profile) ** 2, axis=1)
    near = np.flatnonzero((np.abs(ranges - distance) <= CAL_SEARCH_M) & (ranges >= LEAKAGE_CUTOFF_M))
    i = near[np.argmax(power[near])]
    clutter = np.sum(np.abs(background[i]) ** 2) if background is not None else np.nan
    return profile[i], ranges[i], 10 * np.log10(power[i] / clutter)

def direction(right, up, forward):
    """Direction cosines (sideways, vertical) to a target and its distance."""
    distance = np.sqrt(right ** 2 + up ** 2 + forward ** 2)
    return np.array([right, up]) / distance, distance

def wrap(phase):
    """Wrap phase to between -pi and pi."""
    return np.angle(np.exp(1j * phase))

def sideways_from_rx(samples):
    """Change in sideways direction cosine from the reference capture, from neighboring RX phases in every TX group."""
    grid = samples.reshape(len(samples), N_TX, N_RX)
    pairs = grid[:, :, 1:] * np.conj(grid[:, :, :-1])
    q = np.sum(pairs * np.conj(pairs[:1]), axis=(1, 2))   # relative to the reference, so fixed RX offsets cancel
    return np.angle(q) / (K * RX_STEP_M)

def tx_phases(samples):
    """Phase of TX2 and TX3 relative to TX1 per capture, summed over matching RX, shaped (captures, 2)."""
    grid = samples.reshape(len(samples), N_TX, N_RX)
    return np.angle(np.sum(grid[:, 1:, :] * np.conj(grid[:, :1, :]), axis=2))

def rms_residual(dphase, du, offset):
    """RMS phase residual in deg for one TX offset."""
    return np.degrees(np.sqrt(np.mean(wrap(dphase - K * du @ np.asarray(offset)) ** 2)))

def best_offsets(dphase, du, count=3, spacing_m=0.002):
    """The best few distinct (x, y) offsets on the search grid, best first."""
    X, Y = np.meshgrid(SEARCH_X_M, SEARCH_Y_M)
    predicted = K * (X[..., None] * du[:, 0] + Y[..., None] * du[:, 1])
    cost = 1 - np.mean(np.cos(dphase - predicted), axis=-1)
    found = []
    for _ in range(count):
        i = np.unravel_index(np.argmin(cost), cost.shape)
        found.append((X[i], Y[i]))
        cost[np.hypot(X - X[i], Y - Y[i]) < spacing_m] = np.inf   # block this minimum to find the next
    return found

def main(captures, background_stem, snap, save):
    # Background profile to subtract, if given
    background = mean_profile(background_stem)[0] if background_stem else None

    # Channel samples and tape directions per capture, the first is the straight-ahead reference
    names, tape, samples, rows = [], [], [], []
    for stem, right, up, forward in captures:
        u, distance = direction(float(right), float(up), float(forward))
        s, measured, tcr = target_samples(stem, distance, background)
        names.append(to_stem(stem).name)
        tape.append(u)
        samples.append(s)
        rows.append((distance, measured, tcr))
    tape, samples = np.array(tape), np.array(samples)
    if len(captures) < 3 or np.linalg.matrix_rank(tape[1:] - tape[0], tol=0.02) < 2:
        raise SystemExit("Need a reference capture, plus captures moved sideways and moved up or down")

    # Sideways from the RX themselves, vertical from the tape
    directions = tape.copy()
    directions[:, 0] = tape[0, 0] + sideways_from_rx(samples)
    du = directions[1:] - directions[0]

    print("Capture         tape cm  radar cm  target/clutter  tape az  radar az  tape el")
    for name, (distance, measured, tcr), ut, ud in zip(names, rows, tape, directions):
        print(f"{name:14s}  {distance * 100:7.1f}  {measured * 100:8.1f}  {tcr:11.1f} dB  "
              f"{np.degrees(np.arcsin(ut[0])):+6.1f}   {np.degrees(np.arcsin(ud[0])):+6.1f}   "
              f"{np.degrees(np.arcsin(ut[1])):+6.1f}")

    # Each transmitter's offset from TX1: best grid fits and the IWR6843 candidates
    dphase = wrap(tx_phases(samples)[1:] - tx_phases(samples)[0])
    chosen = []
    for t, name in enumerate(("TX2", "TX3")):
        print(f"\n{name} from TX1 (x mm, y mm, rms residual deg)")
        fits = best_offsets(dphase[:, t], du)
        for rank, (x, y) in enumerate(fits, start=1):
            print(f"  fit {rank}:       {x * 1000:+6.2f}  {y * 1000:+6.2f}  {rms_residual(dphase[:, t], du, (x, y)):5.1f}")
        for x, y in CANDIDATES[name]:
            print(f"  IWR6843:     {x * 1000:+6.2f}  {y * 1000:+6.2f}  {rms_residual(dphase[:, t], du, (x, y)):5.1f}")
        x, y = fits[0]
        if snap:
            x, y = np.round(x / RX_SPACING_M) * RX_SPACING_M, np.round(y / RX_SPACING_M) * RX_SPACING_M
        chosen.append((x, y))
    chosen = np.array(chosen)
    print(f"\nUsing{' snapped' if snap else ''} TX2 {np.round(chosen[0] * 1000, 2)} mm, TX3 {np.round(chosen[1] * 1000, 2)} mm")

    # Every channel's position from the TX offsets and the known RX spacing
    offsets = np.vstack([[0.0, 0.0], chosen])
    rx = np.column_stack([np.arange(N_RX) * RX_STEP_M, np.zeros(N_RX)])
    positions = (offsets[:, None, :] + rx[None, :, :]).reshape(-1, 2)

    # Calibration averaged over every capture, then the residuals it leaves
    unit = samples / np.abs(samples)
    rel = unit * np.conj(unit[:, :1])
    model = np.exp(1j * K * directions @ positions.T)
    calibration = np.angle(np.sum(rel * np.conj(model), axis=0))
    residual = np.degrees(wrap(np.angle(rel) - np.angle(model) - calibration))
    print(f"Channel rms residual deg: {np.round(np.sqrt(np.mean(residual ** 2, axis=0)), 1)}")

    # How well each capture focuses with this layout, 1 is perfect
    steer = np.exp(1j * (K * directions @ positions.T + calibration))
    eta = np.abs(np.sum(samples * np.conj(steer), axis=1)) / np.sum(np.abs(samples), axis=1)
    print("Focusing per capture: " + ", ".join(f"{n} {e:.3f}" for n, e in zip(names, eta)))

    # Save for the beamformer
    if save:
        result = {
            "created": datetime.now(HST).isoformat(timespec="seconds"),
            "captures": [{"stem": n, "direction": u.round(5).tolist()} for n, u in zip(names, directions)],
            "background": to_stem(background_stem).name if background_stem else None,
            "snapped": snap,
            "tx_offsets_m": chosen.round(6).tolist(),
            "positions_m": positions.round(6).tolist(),
            "calibration_rad": calibration.round(5).tolist(),
        }
        GEOMETRY_FILE.write_text(json.dumps(result, indent=2))
        print(f"Saved {GEOMETRY_FILE}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find the 3D transmitter layout from captures of one target at known spots")
    parser.add_argument("--capture", action="append", nargs=4, required=True, metavar=("STEM", "RIGHT", "UP", "FORWARD"),
                        help="Capture and target position in m from the radar center. Give the straight-ahead one first")
    parser.add_argument("--background", default=None, help="Same scene without the target, subtracted before measuring")
    parser.add_argument("--snap", action="store_true", help="Round TX offsets to whole RX spacings before saving")
    parser.add_argument("--save", action="store_true", help=f"Write the result to radar3d/{GEOMETRY_FILE.name}")
    args = parser.parse_args()

    main(args.capture, args.background, args.snap, args.save)