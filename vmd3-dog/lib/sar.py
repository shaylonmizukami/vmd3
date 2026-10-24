"""Synthetic aperture radar helpers: radar positions, profiles, and backprojection."""

import csv
import numpy as np

from config import ANGLE_SIGN, RX_SPACING_M

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

def rx_phase_centers(positions):
    """(frames, 4) effective x of each RX, halfway between the TX and that RX."""
    offsets = ANGLE_SIGN * (np.arange(4) - 1.5) * RX_SPACING_M / 2
    return positions[:, None] + offsets[None, :]
