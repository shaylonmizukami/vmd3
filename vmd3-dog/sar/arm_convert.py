"""Turn a robot arm log into a SAR track CSV in the radar's frame."""

import argparse
import csv
from pathlib import Path

import numpy as np

from config import WAVELENGTH_M
from lib.capture import read_log, to_stem

MOVED_M = 0.001   # how far from a hold counts as moving
SPEED_WINDOW_S = 0.25   # smoothing window for the speed estimate

def load_arm_log(path):
    """Return (time_unix, positions (n, 3), rotation vectors (n, 3) or None) from an arm log, sorted by time."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    t = np.array([float(r["time_unix"]) for r in rows])
    pos = np.array([[float(r[k]) for k in ("x", "y", "z")] for r in rows])
    rot = np.array([[float(r[k]) for k in ("rx", "ry", "rz")] for r in rows]) if "rx" in rows[0] else None
    order = np.argsort(t)
    return t[order], pos[order], None if rot is None else rot[order]

def rotate(rotvecs, v):
    """Rotate vector v by each rotation vector, Rodrigues formula."""
    angle = np.linalg.norm(rotvecs, axis=1, keepdims=True)
    k = np.divide(rotvecs, angle, out=np.zeros_like(rotvecs), where=angle > 0)
    cos, sin = np.cos(angle), np.sin(angle)
    return v * cos + np.cross(k, v) * sin + k * (k @ v)[:, None] * (1 - cos)

def to_radar_frame(pos, flip):
    """Arm base frame (x forward, y left, z up) to radar frame (x right, y forward, z up)."""
    sign = 1 if flip else -1
    return np.column_stack([sign * pos[:, 1], pos[:, 0], pos[:, 2]])

def motion_window(t, x):
    """Arm times when the sweep starts and stops moving."""
    start = t[np.argmax(np.abs(x - x[0]) > MOVED_M)]
    stop = t[len(t) - 1 - np.argmax(np.abs(x[::-1] - x[-1]) > MOVED_M)]
    return start, stop

def center_on_sweep(track):
    """Shift so x is 0 at the sweep middle and y, z are 0 where the radar passes it."""
    mid = (track[:, 0].min() + track[:, 0].max()) / 2
    near = np.abs(track[:, 0] - mid) < 0.002
    return track - np.array([mid, np.median(track[near, 1]), np.median(track[near, 2])])

def smoothed_speed(t, x):
    """Sweep speed in m/s after a moving average over SPEED_WINDOW_S."""
    n = max(1, int(round(SPEED_WINDOW_S / np.median(np.diff(t)))))
    x_s = np.convolve(x, np.ones(n) / n, mode="same")
    return np.abs(np.gradient(x_s, t))[n:-n]

def report(t, track, start, stop, stem):
    """Print sweep checks, and frame coverage if the radar capture is already there."""
    moving = (t >= start) & (t <= stop)
    x, y, z = track[moving].T
    speed = smoothed_speed(t[moving], x)
    print(f"Arm log {np.median(np.diff(t)) * 1000:.1f} ms per sample, {len(t)} samples, {t[-1] - t[0]:.1f} s")
    print(f"Sweep x {x[0] * 100:+.1f} to {x[-1] * 100:+.1f} cm in {stop - start:.1f} s")
    print(f"Speed median {np.median(speed) * 1000:.1f} mm/s, peak {speed.max() * 1000:.1f} mm/s")
    print(f"Wobble while moving: forward {np.ptp(y) * 1000:.2f} mm, up {np.ptp(z) * 1000:.2f} mm")

    # Radar frames inside the log and during the sweep, with their worst spacing
    if not Path(f"{stem}_frames.csv").exists():
        print("No radar capture at this stem yet, skipping frame checks")
        return
    ft = read_log(stem)["time_unix"]
    inside = (ft >= t[0]) & (ft <= t[-1])
    during = (ft >= start) & (ft <= stop)
    print(f"Radar frames: {len(ft)} total, {inside.sum()} inside the arm log, {during.sum()} during the sweep")
    if not inside.any():
        print("[!] No radar frames overlap the arm log, check both computers' clocks")
    elif during.sum() > 1:
        gaps = np.abs(np.diff(np.interp(ft[during], t, track[:, 0])))
        flag = "  [!] over λ/4, slow the sweep" if gaps.max() > WAVELENGTH_M / 4 else ""
        print(f"Frame spacing median {np.median(gaps) * 1000:.2f} mm, worst {gaps.max() * 1000:.2f} mm "
              f"(λ/4 = {WAVELENGTH_M / 4 * 1000:.2f}){flag}")

def main(armLog, stem, flipX, wristOffset, force):
    stem = to_stem(stem)
    out = Path(f"{stem}_track.csv")
    if out.exists() and not force:
        raise SystemExit(f"{out} already exists, pass --force to replace it")
    t, pos, rot = load_arm_log(armLog)

    # Add the wrist tilt back if the radar offset was a fixed shift in the base frame
    if wristOffset:
        if rot is None:
            raise SystemExit("--wristOffset needs rx, ry, rz columns in the arm log")
        offset = np.array([wristOffset[0], 0.0, wristOffset[1]])
        pos = pos + rotate(rot, offset) - offset

    # Radar frame, centered on the sweep
    track = center_on_sweep(to_radar_frame(pos, flipX))
    start, stop = motion_window(t, track[:, 0])

    # Same track format as the Galil converter, plus forward and up
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_unix", "x_m", "y_m", "z_m"])
        writer.writerows([f"{ti:.4f}", f"{xi:.6f}", f"{yi:.6f}", f"{zi:.6f}"] for ti, (xi, yi, zi) in zip(t, track))

    report(t, track, start, stop, stem)
    print(f"Saved {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert a robot arm log to a SAR track CSV")
    parser.add_argument("armLog", help="Arm log CSV with time_unix, x, y, z (and rx, ry, rz)")
    parser.add_argument("stem", help="Radar capture stem the track belongs to, e.g. data/2026-11-28/arm/bg")
    parser.add_argument("--flipX", action="store_true", help="Use if the image comes out mirrored, arm +y taken as the radar's right")
    parser.add_argument("--wristOffset", type=float, nargs=2, default=None, metavar=("FORWARD", "UP"),
                        help="Only if the log's radar-face offset was a fixed base-frame shift, e.g. 0.06 0.03")
    parser.add_argument("--force", action="store_true", help="Replace an existing track CSV")
    args = parser.parse_args()

    main(args.armLog, args.stem, args.flipX, args.wristOffset, args.force)
    