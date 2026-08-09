"""
analysis.py — Range-profile and target-bin helpers (RADC, 2D).

Fast-time processing only: turn a decoded cube into an amplitude-vs-range
profile, and pick the strongest target bin(s) off that profile. Slow-time
phase/displacement lives separately in displacement.py.

No plotting, no side effects on import.
"""

import numpy as np
from vmd3lib.config import RANGE_WINDOW, MAX_RANGE_M, N_SAMPLES


def range_fft(x, axis, window=RANGE_WINDOW):
    """
    Windowed FFT along one axis. The single entry point for every range FFT
    in the library, so a window choice applies everywhere at once.

    A Hann window trades a slightly wider main lobe for sidelobes that fall
    off at 18 dB/octave instead of 6 — which is what keeps a strong target
    from leaking into a weaker target's bin a dozen bins away.
    """
    n = x.shape[axis]
    if window == 'hann':
        w = np.hanning(n)
    elif window in (None, 'none', 'rect'):
        w = np.ones(n)
    else:
        raise ValueError(f'Unknown window: {window!r}')

    shape = [1] * x.ndim
    shape[axis] = n
    return np.fft.fft(x * w.reshape(shape), axis=axis)


def range_profile(cube, window=RANGE_WINDOW):
    """
    Compute an amplitude-vs-range-bin profile from one decoded cube.

    cube : complex (samples, chirps, channels) = (128, 64, 4)

    Range FFT along fast-time (samples), magnitude, averaged over chirps
    and channels. Returns a real 1-D array of length n_range_bins (128).
    """
    fft_range = range_fft(cube, axis=0, window=window)   # (range_bins, chirps, channels)
    profile = np.mean(np.abs(fft_range), axis=(1, 2))   # (range_bins,)
    return profile


def find_target_bins(profile, n_targets=1, leakage_skip=10, min_separation=4, search_window=None):
    """
    Return the bin indices of the strongest target(s) in a range profile,
    skipping the near-range TX-RX leakage region.

    profile        : real 1-D range profile (from range_profile()).
    n_targets      : how many target bins to return.
    leakage_skip   : ignore bins [0:leakage_skip] (near-range leakage).
    min_separation : minimum bin gap between returned targets, so a single
                     broad peak isn't reported as two adjacent targets.

    Returns a list of bin indices (ints), strongest first.
    """
    search = profile.copy()
    search[:leakage_skip] = 0.0   # kill the leakage region

    if search_window is not None:
        lo, hi = search_window
        keep = np.zeros(len(search), dtype=bool)
        keep[max(0, lo):min(len(search), hi)] = True
        search[~keep] = 0.0

    picked = []
    work = search.copy()
    while len(picked) < n_targets:
        bin_idx = int(np.argmax(work))
        if work[bin_idx] == 0.0:
            break                    # nothing left worth picking
        picked.append(bin_idx)
        # Zero out a guard band around this peak so the next argmax
        # lands on a genuinely different target, not the same peak's shoulder.
        lo = max(0, bin_idx - min_separation)
        hi = min(len(work), bin_idx + min_separation + 1)
        work[lo:hi] = 0.0

    return picked


def bin_to_range(bin_idx, max_range=MAX_RANGE_M, n_bins=N_SAMPLES):
    """Range-bin index -> meters."""
    return bin_idx * max_range / n_bins


def range_to_bin(range_m, max_range=MAX_RANGE_M, n_bins=N_SAMPLES):
    """Meters -> nearest range-bin index."""
    return int(round(range_m * n_bins / max_range))