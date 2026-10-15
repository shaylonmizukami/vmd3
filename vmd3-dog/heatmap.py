"""Plot an averaged range-angle heatmap from a VMD3 capture."""

import argparse
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

from config import ANGLE_LIMIT_DEG, ANGLE_STEP_DEG, LEAKAGE_CUTOFF_M, PLOTS_SUBDIR
from lib.capture import clock_to_seconds, decode_radc, load, time_window, to_stem
from lib.dsp import find_peak, range_angle_power, range_axis, to_db
from lib.plots import range_angle_axes

def main(stem, start, end, startClock, endClock, floor, maxRange, show):
    stem = to_stem(stem)
    payloads, log, meta = load(stem, "radc")

    # Pick the time window, clock times win over seconds
    if startClock:
        start = clock_to_seconds(startClock, log, meta)
    if endClock:
        end = clock_to_seconds(endClock, log, meta)
    window = time_window(log, start, end)
    payloads = payloads[window]
    times = log["elapsed_s"][window]
    if len(payloads) == 0:
        raise SystemExit("No frames in that time window")

    # Range-angle power, averaged over frames
    angles = np.arange(-ANGLE_LIMIT_DEG, ANGLE_LIMIT_DEG + ANGLE_STEP_DEG, ANGLE_STEP_DEG)
    power = range_angle_power(decode_radc(payloads, meta), angles).mean(axis=0)
    ranges = range_axis(meta, power.shape[0])

    # dB relative to the strongest return past the leakage zone
    ref = power[ranges >= LEAKAGE_CUTOFF_M].max()
    db = to_db(power, floor, ref)
    peak_r, peak_a = find_peak(db, ranges, angles)

    # Plot
    fig, ax, mesh = range_angle_axes(db, ranges, angles, floor, maxRange)
    ax.plot(peak_a, peak_r, "c+", markersize=14, markeredgewidth=2)
    ax.set_title(f"{stem.name} | {times[0]:.1f} to {times[-1]:.1f} s, {len(times)} frames\n"
                 f"peak {peak_r:.2f} m, {peak_a:+.1f} deg")
    fig.tight_layout()

    # Save next to the capture and report
    out = stem.parent / PLOTS_SUBDIR / f"{stem.name}_heatmap.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"Frames {len(times)} ({times[0]:.1f} to {times[-1]:.1f} s)")
    print(f"Peak {peak_r:.2f} m, {peak_a:+.1f} deg")
    print(f"Saved {out}")
    if show:
        plt.show()

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description="Range-angle heatmap from a VMD3 capture")
    parser.add_argument("stem", help="Capture path, e.g. data/2026-10-14/sign-right-3")
    parser.add_argument("--start", type=float, default=None, help="Window start, seconds into the capture")
    parser.add_argument("--end", type=float, default=None, help="Window end, seconds into the capture")
    parser.add_argument("--startClock", default=None, help="Window start as HH:MM:SS from field notes")
    parser.add_argument("--endClock", default=None, help="Window end as HH:MM:SS from field notes")
    parser.add_argument("--floor", type=float, default=-40, help="Lowest dB shown. Default: -40")
    parser.add_argument("--maxRange", type=float, default=None, help="Tope of the range axis in m. Default: full range")
    parser.add_argument("--show", action="store_true", help="Open the plot window as well as saving it")
    args = parser.parse_args()

    main(args.stem, args.start, args.end, args.startClock, args.endClock, args.floor, args.maxRange, args.show)
