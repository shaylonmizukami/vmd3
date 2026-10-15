"""Replay a VMD3 capture as an animated range-angle map."""

import argparse
from datetime import datetime
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button, Slider

from config import ANGLE_LIMIT_DEG, ANGLE_STEP_DEG, FRAME_PERIOD_S, HST, LEAKAGE_CUTOFF_M
from lib.capture import decode_radc, load, to_stem
from lib.dsp import find_peak, range_angle_power, range_axis, to_db
from lib.plots import range_angle_axes

BLOCK = 64

def compute_maps(payloads, meta, angles, doppler):
    """Return range-angle power for every frame, (frames, range, angles)."""
    blocks = []
    for i in range(0, len(payloads), BLOCK):
        cube = decode_radc(payloads[i:i + BLOCK], meta)
        blocks.append(range_angle_power(cube, angles, doppler).astype(np.float32))
        print(f"Processed {min(i + BLOCK, len(payloads))}/{len(payloads)} frames", end="\r")
    print()
    return np.concatenate(blocks)

def main(stem, doppler, floor, maxRange, speed):
    stem = to_stem(stem)
    payloads, log, meta = load(stem, "radc")
    times = log["elapsed_s"]
    clocks = [datetime.fromtimestamp(t, HST).strftime("%H:%M:%S") for t in log["time_unix"]]

    # List marks and track which segment each frame is in
    marks = log["mark"]
    segments, last = [], ""
    for i, m in enumerate(marks):
        if m:
            print(f"{m}: frame {i}, {times[i]:.1f} s, {clocks[i]}")
        last = m or last
        segments.append(last)

    # Every frame's map on one fixed dB scale
    angles = np.arange(-ANGLE_LIMIT_DEG, ANGLE_LIMIT_DEG + ANGLE_STEP_DEG, ANGLE_STEP_DEG)
    power = compute_maps(payloads, meta, angles, doppler)
    ranges = range_axis(meta, power.shape[1])
    ref = power[:, ranges >= LEAKAGE_CUTOFF_M].max()
    db = to_db(power, floor, ref)

    # Figure with room for the controls
    fig, ax, mesh = range_angle_axes(db[0], ranges, angles, floor, maxRange)
    fig.subplots_adjust(bottom=0.22)
    marker, = ax.plot([], [], "c+", markersize=14, markeredgewidth=2)
    slider = Slider(fig.add_axes([0.15, 0.08, 0.6, 0.03]), "Frame", 0, len(db) - 1, valinit=0, valstep=1)
    button = Button(fig.add_axes([0.8, 0.07, 0.1, 0.05]), "Pause")
    state = {"playing": True}

    def show(i):
        """Draw frame i."""
        mesh.set_array(db[i])
        peak_r, peak_a = find_peak(db[i], ranges, angles)
        marker.set_data([peak_a], [peak_r])
        ax.set_title(f"{stem.name} | {doppler} Doppler | frame {i} | {times[i]:.1f} s | {clocks[i]}\n"
                     f"peak {peak_r:.2f} m, {peak_a:+.1f} deg | {segments[i] or 'start'}")
        fig.canvas.draw_idle()

    def step(_):
        """Advance one frame while playing."""
        if state["playing"]:
            slider.set_val((slider.val + 1) % len(db))

    def toggle(_):
        """Pause or resume playback."""
        state["playing"] = not state["playing"]
        button.label.set_text("Pause" if state["playing"] else "Play")

    # Wire up controls and start
    slider.on_changed(lambda val: show (int(val)))
    button.on_clicked(toggle)
    show(0)
    anim = FuncAnimation(fig, step, interval=FRAME_PERIOD_S * 1000 / speed, cache_frame_data=False)   # keep a referece or it stops
    plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay a VMD3 capture as a range-angle map")
    parser.add_argument("stem", help="Capture path, e.g. data/2026-10-14/sign-right-3")
    parser.add_argument("--doppler", choices=["zero", "all"], default="zero", help="Keep only still targets (zero) or everything (all). Default: zero")
    parser.add_argument("--floor", type=float, default=-40, help="Lowest dB shown. Default: -40")
    parser.add_argument("--maxRange", type=float, default=None, help="Top of the range axis in m. Default: full range")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed, 2 = twice real time. Default: 1")
    args = parser.parse_args()

    main(args.stem, args.doppler, args.floor, args.maxRange, args.speed)