"""Range-angle heatmaps of target, background, and target minus background."""

import argparse
import matplotlib.pyplot as plt
import numpy as np

from config import ANGLE_LIMIT_DEG, ANGLE_STEP_DEG, LEAKAGE_CUTOFF_M, PLOTS_SUBDIR, FLOOR_DB
from lib.capture import load_window, to_stem
from lib.dsp import complex_correlation, find_peak, range_angle, range_axis, to_db, zero_doppler_profiles
from lib.plots import draw_range_angle

BLOCK = 64   # frames decoded at a time, keeps memory small on long windows

def window_profiles(stem, start, end):
    """Return zero Doppler profiles (frames, range, channels) and meta for one time window."""
    payloads, _, meta = load_window(stem, start, end)
    return zero_doppler_profiles(payloads, meta), meta

def main(stem, target, background, bgStem, method, floor, maxRange, show):
    stem = to_stem(stem)
    bg_stem = to_stem(bgStem) if bgStem else stem

    # Zero Doppler profiles for each window
    tgt, meta = window_profiles(stem, *target)
    bkg, _ = window_profiles(bg_stem, *background)
    angles = np.arange(-ANGLE_LIMIT_DEG, ANGLE_LIMIT_DEG + ANGLE_STEP_DEG, ANGLE_STEP_DEG)
    ranges = range_axis(meta, tgt.shape[1])
    past = ranges >= LEAKAGE_CUTOFF_M

    # Power maps averaged over frames
    tgt_power = np.mean(np.abs(range_angle(tgt, angles)) ** 2, axis=0)
    bkg_power = np.mean(np.abs(range_angle(bkg, angles)) ** 2, axis=0)

    # Subtract by power, or by complex average before beamforming
    if method == "power":
        sub_power = np.maximum(tgt_power - bkg_power, 0)
    else:
        diff = tgt.mean(axis=0) - bkg.mean(axis=0)
        sub_power = np.abs(range_angle(diff[None], angles)[0]) ** 2

    # All three on one dB scale, 0 dB = the target maps strongest return past leakage
    ref = tgt_power[past].max()
    sub_title = f"Target minus background ({method})"
    maps = {
        "Target": to_db(tgt_power, floor, ref),
        "Background": to_db(bkg_power, floor, ref),
        sub_title: to_db(sub_power, floor, ref),
    }

    # How well the background matches away from the target, near 1 justifies complex
    peak_r, peak_a = find_peak(maps[sub_title], ranges, angles)
    away = past & (np.abs(ranges - peak_r) > 0.2)
    rho = complex_correlation(tgt.mean(axis=0)[away], bkg.mean(axis=0)[away])
    clutter_db = 10 * np.log10(sub_power[away].sum() / tgt_power[away].sum())

    # Plot the three maps side by side
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.5), sharey=True, layout="constrained")
    for ax, (title, db) in zip(axes, maps.items()):
        mesh = draw_range_angle(ax, db, ranges, angles, floor, maxRange)
        r, a = find_peak(db, ranges, angles)
        ax.plot(a, r, "c+", markersize=12, markeredgewidth=2)
        ax.set_title(f"{title}\npeak {r:.2f} m, {a:+.1f} deg")
    for ax in axes[1:]:
        ax.set_ylabel("")
    fig.colorbar(mesh, ax=axes, label="dB rel. target's strongest return past leakage")
    fig.suptitle(f"{stem.name} target {target[0]:g} to {target[1]:g} s | "
                 f"{bg_stem.name} background {background[0]:g} to {background[1]:g} s")

    # Save to the plots folder and report
    out = stem.parent / PLOTS_SUBDIR / f"{stem.name}_bgsub_{method}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"Target {len(tgt)} frames, background {len(bkg)} frames")
    print(f"Subtracted peak {peak_r:.2f} m, {peak_a:+.1f} deg")
    print(f"Background match per channel: {np.round(rho, 4)}")
    print(f"Clutter away from target: {clutter_db:+.1f} dB after subtraction")
    print(f"Saved {out}")
    if show:
        plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Background subtracted range-angle heatmap")
    parser.add_argument("stem", help="Capture with the target, e.g. data/2026-10-15/dog-run-1")
    parser.add_argument("--target", nargs=2, type=float, required=True, metavar=("START", "END"), help="Target window, seconds into the capture")
    parser.add_argument("--background", nargs=2, type=float, required=True, metavar=("START", "END"), help="Background window, seconds into its capture")
    parser.add_argument("--bgStem", default=None, help="Capture holding the background, if different from the target's")
    parser.add_argument("--method", choices=["power", "complex"], default="power", help="Subtract power maps or complex profiles. Default: power")
    parser.add_argument("--floor", type=float, default=FLOOR_DB, help=f"Lowest dB shown. Default: {FLOOR_DB}")
    parser.add_argument("--maxRange", type=float, default=None, help="Top of the range axis in m. Default: full range")
    parser.add_argument("--show", action="store_true", help="Open the plot window as well as saving it")
    args = parser.parse_args()

    main(args.stem, args.target, args.background, args.bgStem, args.method, args.floor, args.maxRange, args.show)