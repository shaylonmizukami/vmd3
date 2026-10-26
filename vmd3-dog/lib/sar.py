"""Synthetic aperture radar helpers: radar positions, profiles, and backprojection."""

import csv
import numpy as np

from config import (ANGLE_SIGN, APERTURE_WINDOW, PHASE_SIGN, RX_SPACING_M, SAR_CROSS_RANGE_M, SAR_CROSS_STEP_M,
                    SAR_DOWNRANGE_HALF_M, SAR_DOWNRANGE_STEP_M, WAVELENGTH_M, LEAKAGE_CUTOFF_M, BG_REFERENCE_M,
                    BG_EXCLUDE_M, RANGE_FFT_SIZE, CAL_SEARCH_M)
from lib.capture import load, to_stem
from lib.dsp import range_axis, zero_doppler_profiles

def load_track(path):
    """Return (time_unix, x_m) arrays from an arm track CSV, sorted by time."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    t = np.array([float(r["time_unix"]) for r in rows])
    x = np.array([float(r["x_m"]) for r in rows])
    order = np.argsort(t)
    return t[order], x[order]

def positions_at(times, track_t, track_x, clock_offset=0.0):
    """Radar x at each frame time. clock_offset is the arm clock minus the radar clock."""
    return np.interp(times + clock_offset, track_t, track_x)

def moving_frames(positions, track_x, trim_m=0.002):
    """Mask of frames taken while the arm was moving, dropping trim_m at each end."""
    lo, hi = sorted((track_x[0], track_x[-1]))
    return (positions > lo + trim_m) & (positions < hi - trim_m)

def phase_track(profiles, ranges):
    """Cumulative phase of everything past the leakage, power weighted, one value per frame in rad."""
    flat = profiles[:, ranges >= LEAKAGE_CUTOFF_M, :].reshape(len(profiles), -1)
    steps = np.angle(np.sum(flat[1:] * np.conj(flat[:-1]), axis=1))
    return np.concatenate([[0.0], np.cumsum(steps)])

def motion_edges(track_t, track_x, moved_m=0.0005):
    """Arm clock times when the sweep starts and stops."""
    start = track_t[np.argmax(np.abs(track_x - track_x[0]) > moved_m)]
    stop = track_t[len(track_t) - 1 - np.argmax(np.abs(track_x[::-1] - track_x[-1]) > moved_m)]
    return start, stop

def estimate_clock_offset(times, phase, track_t, track_x, window_s=1.5, search_s=1.5, step_s=0.005):
    """Arm clock minus radar clock that lines up the radar's phase changes with the arm's start and stop."""
    edges = motion_edges(track_t, track_x)
    candidates = np.arange(-search_s, search_s + step_s / 2, step_s)
    costs = np.full(len(candidates), np.inf)

    for k, offset in enumerate(candidates):
        x = positions_at(times, track_t, track_x, offset)
        cost = 0.0
        for edge in edges:
            # Frames within the window on both sides of this edge
            near = np.abs(times + offset - edge) < window_s
            before = np.sum(near & (times + offset < edge))
            after = np.sum(near & (times + offset > edge))
            if before < 3 or after < 3:
                break

            # Phase should be a smooth function of position across the edge
            A = np.column_stack([np.ones(near.sum()), x[near], x[near] ** 2])
            fit = np.linalg.lstsq(A, phase[near], rcond=None)[0]
            cost += np.mean((phase[near] - A @ fit) ** 2)
        else:
            costs[k] = cost
    return candidates[int(np.argmin(costs))]

def rx_phase_centers(positions):
    """(frames, 4) effective x of each RX, halfway between the TX and that RX."""
    offsets = ANGLE_SIGN * (np.arange(4) - 1.5) * RX_SPACING_M / 2
    return positions[:, None] + offsets[None, :]

def load_sweep(stem, track=None, clock_offset=0.0, auto_clock=False):
    """Return (positions, profiles, meta, clock_offset) for the moving frames of one sweep."""
    stem = to_stem(stem)
    payloads, log, meta = load(stem, "radc")
    track_t, track_x = load_track(track or f"{stem}_arm.csv")
    profiles = zero_doppler_profiles(payloads, meta, n_fft=RANGE_FFT_SIZE)

    # Line the arm clock up with the radar from the data itself, if asked
    if auto_clock:
        phase = phase_track(profiles, range_axis(meta, RANGE_FFT_SIZE))
        clock_offset = estimate_clock_offset(log["time_unix"], phase, track_t, track_x)

    # Radar position at every frame, keeping only the sweep
    positions = positions_at(log["time_unix"], track_t, track_x, clock_offset)
    moving = moving_frames(positions, track_x)
    return positions[moving], profiles[moving], meta, clock_offset

def interpolate_profiles(profiles, positions, new_positions):
    """Complex profiles resampled from positions to new_positions, linear in position."""
    order = np.argsort(positions)
    x, p = positions[order], profiles[order]
    k = np.clip(np.searchsorted(x, new_positions), 1, len(x) - 1)
    f = np.clip((new_positions - x[k - 1]) / (x[k] - x[k - 1]), 0, 1)[:, None, None]
    return (1 - f) * p[k - 1] + f * p[k]

def subtract_background(target, background, ranges, target_range):
    """Scale the background per RX to match the target away from it, then subtract. Returns (residual, rho, reduction_db)."""
    ref = ((ranges >= BG_REFERENCE_M[0]) & (ranges <= BG_REFERENCE_M[1])
           & (np.abs(ranges - target_range) > BG_EXCLUDE_M))
    t, b = target[:, ref, :], background[:, ref, :]

    # Best complex scale per RX, and how well the two match
    num = np.sum(t * np.conj(b), axis=(0, 1))
    t_pow = np.sum(np.abs(t) ** 2, axis=(0, 1))
    b_pow = np.sum(np.abs(b) ** 2, axis=(0, 1))
    alpha = num / b_pow
    rho = np.abs(num) / np.sqrt(t_pow * b_pow)

    # Subtract and measure how much of the reference region was removed
    residual = target - alpha * background
    reduction_db = 10 * np.log10(t_pow / np.sum(np.abs(residual[:, ref, :]) ** 2, axis=(0, 1)))
    return residual, rho, reduction_db

def peak_bin(power, k):
    """Fractional peak location from a parabola through the log power at bin k and its neighbors."""
    y = 10 * np.log10(np.maximum(power[k - 1:k + 2], 1e-30))
    denom = y[0] - 2 * y[1] + y[2]
    return k + (0.5 * (y[0] - y[2]) / denom if denom != 0 else 0.0)

def estimate_range_offset(profiles, ranges, target_range):
    """Per RX (offset_m, measured_m), where offset is the tape range minus where the radar puts the target."""
    power = np.sum(np.abs(profiles) ** 2, axis=0)   # (bins, rx), summed over the sweep
    search = np.flatnonzero(np.abs(ranges - target_range) <= CAL_SEARCH_M)
    bin_m = ranges[1] - ranges[0]
    measured = np.array([peak_bin(power[:, rx], search[np.argmax(power[search, rx])]) * bin_m
                         for rx in range(power.shape[1])])
    return target_range - measured, measured

def phase_sign_check(profiles, positions, x_t, z_t, bin_m, offset_m=0.0):
    """Focusing coherence at one point for phase sign +1 and -1, per RX. The right sign scores near 1."""
    centers = rx_phase_centers(positions)
    frames = np.arange(len(positions))
    scores = {}
    for sign in (+1, -1):
        eta = []
        for rx in range(profiles.shape[2]):
            # Complex sample at the predicted range from every frame
            r = np.hypot(x_t - centers[:, rx], z_t)
            q = (r - offset_m) / bin_m
            lo = np.floor(q).astype(int)
            f = q - lo
            s = (1 - f) * profiles[frames, lo, rx] + f * profiles[frames, lo + 1, rx]

            # Remove the predicted phase and see how well the frames add up
            aligned = s * np.exp(-1j * sign * 4 * np.pi * (r - r[len(r) // 2]) / WAVELENGTH_M)
            eta.append(np.abs(aligned.sum()) / np.abs(s).sum())
        scores[sign] = np.array(eta)
    return scores

def image_grid(target_range):
    """Return (cross_m, down_m) pixel axes centered on the target's slant range."""
    cross = np.arange(-SAR_CROSS_RANGE_M, SAR_CROSS_RANGE_M + SAR_CROSS_STEP_M / 2, SAR_CROSS_STEP_M)
    down = np.arange(target_range - SAR_DOWNRANGE_HALF_M, target_range + SAR_DOWNRANGE_HALF_M + SAR_DOWNRANGE_STEP_M / 2, SAR_DOWNRANGE_STEP_M)
    return cross, down

def aperture_weights(n):
    """Unit-sum taper across n aperture positions."""
    w = np.hamming(n) if APERTURE_WINDOW == "hamming" else np.ones(n)
    return w / w.sum()

def backproject(profiles, positions, cross, down, bin_m, offset_m=0.0):
    """Focus one RX. profiles (frames, range bins), positions (frames,) to a complex image (down, cross)."""
    X, Z = np.meshgrid(cross, down)
    weights = aperture_weights(len(positions))
    r_ref = np.hypot(X - positions[len(positions) // 2], Z)
    image = np.zeros(X.shape, dtype=complex)
    n_bins = profiles.shape[1]

    for profile, x_m, w in zip(profiles, positions, weights):
        # Predicted range from this position to every pixel, as a fractional bin
        r = np.hypot(X - x_m, Z)
        q = (r - offset_m) / bin_m
        lo = np.clip(np.floor(q).astype(int), 0, n_bins - 2)
        f = q - lo

        # Interpolate the complex profile there, undo the predicted phase, and add in
        sample = (1 - f) * profile[lo] + f * profile[lo + 1]
        image += w * sample * np.exp(-1j * PHASE_SIGN * 4 * np.pi * (r - r_ref) / WAVELENGTH_M)
    return image

def fuse_power(images):
    """Equal-weight power sum of per-RX complex images."""
    return np.mean(np.abs(images) ** 2, axis=0)

def minus3db_width(coord, profile):
    """Width of the region around the peak that stays within 3 dB of it, interpolated."""
    db = 10 * np.log10(np.maximum(profile / profile.max(), 1e-30))
    k = int(np.argmax(profile))
    lo, hi = k, k
    while lo > 0 and db[lo - 1] >= -3:
        lo -= 1
    while hi < len(db) - 1 and db[hi + 1] >= -3:
        hi += 1
    if lo == 0 or hi == len(db) - 1:
        return np.nan   # peak runs off the edge of the image

    # Interpolate where each side crosses -3 dB
    left = np.interp(-3, [db[lo - 1], db[lo]], [coord[lo - 1], coord[lo]])
    right = np.interp(-3, [db[hi + 1], db[hi]], [coord[hi + 1], coord[hi]])
    return right - left

def image_metrics(power, cross, down):
    """Peak position and -3 dB widths through the peak, in m."""
    i, j = np.unravel_index(np.argmax(power), power.shape)
    return {
        "x": cross[j],
        "range": down[i],
        "cross_width": minus3db_width(cross, power[i, :]),
        "range_width": minus3db_width(down, power[:, j]),
    }

def expected_widths(target_range, aperture, meta):
    """Ideal Hamming-weighted -3 dB widths, (cross-range, range) in m."""
    cross = 0.66 * WAVELENGTH_M * target_range / aperture   # 0.443 for uniform, wider for Hamming
    rng = 1.30 * meta["vmd3_setting"]["max_range"] / meta["vmd3_setting"]["num_samples"]   # Hamming widens one bin by 1.3
    return cross, rng
