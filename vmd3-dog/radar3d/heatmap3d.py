"""Maps from a VMD3 3D capture: full azimuth and elevation from all 12 channels, or per TX range-azimuth."""

import argparse
import matplotlib.pyplot as plt
import numpy as np

from config import ANGLE_LIMIT_DEG, ANGLE_STEP_DEG, FLOOR_DB, LEAKAGE_CUTOFF_M, PLOTS_SUBDIR
from lib.capture import load_window, to_stem
from lib.dsp import range_angle, range_axis, to_db, zero_doppler_profiles
from lib.plots import draw_range_angle
from radar3d.config3d import BEAM_AZ_DEG, BEAM_EL_DEG, ELEVATION_LIMIT_DEG, ELEVATION_STEP_DEG
from radar3d.mimo import combined_power, direction_power, load_geometry, per_tx_power

def window_profiles(stem, start, end, mode):
    """Zero Doppler profiles and meta for one time window, refusing the wrong angle mode."""
    payloads, _, meta = load_window(stem, start, end)
    found = meta["vmd3_setting"]["angle_setting"]
    if found != mode:
        raise SystemExit(f"{to_stem(stem).name} is a {found} capture, expected {mode}")
    return zero_doppler_profiles(payloads, meta), meta

def mark_peak(ax, db, x, y, rows=None):
    """Mark the strongest pixel, only in the given rows if set, and return its (x, y, dB)."""
    masked = db if rows is None else np.where(rows[:, None], db, -np.inf)
    i, j = np.unravel_index(np.argmax(masked), db.shape)
    ax.plot(x[j], y[i], "c+", markersize=12, markeredgewidth=2)
    return x[j], y[i], db[i, j]

def per_tx_figure(profiles, compare_power, ranges, angles, floor, maxRange):
    """Each TX's range-azimuth map, their average, and an optional 2D map."""
    per_tx = per_tx_power(profiles, angles)
    maps = {f"TX{tx + 1}": power for tx, power in enumerate(per_tx)}
    maps["3D combined"] = combined_power(per_tx)
    if compare_power is not None:
        maps["2D"] = compare_power
    past = ranges >= LEAKAGE_CUTOFF_M
    ref = max(power[past].max() for power in maps.values())

    # One panel per map on one dB scale
    fig, axes = plt.subplots(1, len(maps), figsize=(4.5 * len(maps), 5.5), sharey=True, layout="constrained")
    for ax, (name, power) in zip(axes, maps.items()):
        db = to_db(power, floor, ref)
        mesh = draw_range_angle(ax, db, ranges, angles, floor, maxRange)
        a, r, level = mark_peak(ax, db, angles, ranges, past)
        ax.set_title(f"{name}\npeak {r:.2f} m, {a:+.1f} deg, {level:.1f} dB")
        print(f"{name:12s} peak {r:.2f} m, {a:+.1f} deg, {level:.1f} dB")
    for ax in axes[1:]:
        ax.set_ylabel("")
    fig.colorbar(mesh, ax=axes, label="dB rel. strongest return past leakage")
    return fig

def full_figure(profiles, compare_power, ranges, angles, floor, maxRange, slice_range):
    """Range-azimuth, range-elevation, and azimuth-elevation maps from all 12 channels, plus an optional 2D map."""
    positions, calibration = load_geometry()
    elevations = np.arange(-ELEVATION_LIMIT_DEG, ELEVATION_LIMIT_DEG + ELEVATION_STEP_DEG / 2, ELEVATION_STEP_DEG)
    cube = direction_power(profiles, positions, calibration, angles, elevations)
    past = ranges >= LEAKAGE_CUTOFF_M

    # One dB scale for everything, 0 dB = strongest return past leakage
    ref = cube[past].max()
    if compare_power is not None:
        ref = max(ref, compare_power[past].max())

    # Range for the azimuth-elevation slice, the strongest return unless chosen
    if slice_range is None:
        i = np.unravel_index(np.argmax(np.where(past[:, None, None], cube, 0)), cube.shape)[0]
    else:
        i = int(np.argmin(np.abs(ranges - slice_range)))

    n = 3 if compare_power is None else 4
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5.5), layout="constrained")

    # Top-down view, every elevation folded in
    db = to_db(cube.max(axis=1), floor, ref)
    mesh = draw_range_angle(axes[0], db, ranges, angles, floor, maxRange)
    a, r, level = mark_peak(axes[0], db, angles, ranges, past)
    axes[0].set_title(f"3D range-azimuth, max over elevation\npeak {r:.2f} m, az {a:+.1f} deg, {level:.1f} dB")
    print(f"Range-azimuth     peak {r:.2f} m, az {a:+.1f} deg, {level:.1f} dB")

    # Side view, every azimuth folded in
    db = to_db(cube.max(axis=2), floor, ref)
    draw_range_angle(axes[1], db, ranges, elevations, floor, maxRange)
    e, r, level = mark_peak(axes[1], db, elevations, ranges, past)
    axes[1].set(xlabel="Elevation (deg, + is up)",
                title=f"3D range-elevation, max over azimuth\npeak {r:.2f} m, el {e:+.1f} deg, {level:.1f} dB")
    print(f"Range-elevation   peak {r:.2f} m, el {e:+.1f} deg, {level:.1f} dB")

    # Both angles at one range, with the antenna's -3 dB beam edges
    db = to_db(cube[i], floor, ref)
    axes[2].pcolormesh(angles, elevations, db, shading="nearest", cmap="inferno", vmin=floor, vmax=0)
    a, e, level = mark_peak(axes[2], db, angles, elevations)
    axes[2].add_patch(plt.Rectangle((-BEAM_AZ_DEG, -BEAM_EL_DEG), 2 * BEAM_AZ_DEG, 2 * BEAM_EL_DEG,
                                    fill=False, edgecolor="white", linestyle="--", linewidth=1))
    axes[2].set(xlabel="Azimuth (deg, + is right)", ylabel="Elevation (deg, + is up)", aspect="equal",
                title=f"Azimuth-elevation at {ranges[i]:.2f} m\npeak az {a:+.1f}, el {e:+.1f} deg, {level:.1f} dB")
    print(f"Az-el at {ranges[i]:.2f} m  peak az {a:+.1f} deg, el {e:+.1f} deg, {level:.1f} dB")

    # 2D capture of the same scene
    if compare_power is not None:
        db = to_db(compare_power, floor, ref)
        draw_range_angle(axes[3], db, ranges, angles, floor, maxRange)
        a, r, level = mark_peak(axes[3], db, angles, ranges, past)
        axes[3].set_title(f"2D range-azimuth\npeak {r:.2f} m, az {a:+.1f} deg, {level:.1f} dB")
        print(f"2D range-azimuth  peak {r:.2f} m, az {a:+.1f} deg, {level:.1f} dB")

    fig.colorbar(mesh, ax=axes, label="dB rel. strongest return past leakage")
    return fig

def main(stem, compare, perTx, sliceRange, start, end, floor, maxRange, show):
    stem = to_stem(stem)
    angles = np.arange(-ANGLE_LIMIT_DEG, ANGLE_LIMIT_DEG + ANGLE_STEP_DEG, ANGLE_STEP_DEG)
    profiles, meta = window_profiles(stem, start, end, "3D")
    ranges = range_axis(meta, profiles.shape[1])

    # Range-azimuth power from a 2D capture of the same scene, if given
    compare_power = None
    if compare:
        profiles_2d, meta_2d = window_profiles(compare, start, end, "2D")
        if not np.allclose(range_axis(meta_2d, profiles_2d.shape[1]), ranges):
            raise SystemExit("The 2D and 3D captures use different range settings")
        compare_power = np.mean(np.abs(range_angle(profiles_2d, angles)) ** 2, axis=0)

    # Per TX maps, or the full 12-channel maps
    if perTx:
        fig = per_tx_figure(profiles, compare_power, ranges, angles, floor, maxRange)
        suffix = "pertx"
    else:
        fig = full_figure(profiles, compare_power, ranges, angles, floor, maxRange, sliceRange)
        suffix = "full"
    fig.suptitle(f"{stem.name}" + (f" vs {to_stem(compare).name}" if compare else ""))

    # Save to the plots folder
    out = stem.parent / PLOTS_SUBDIR / f"{stem.name}_heatmap3d_{suffix}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"Saved {out}")
    if show:
        plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Maps from a VMD3 3D capture")
    parser.add_argument("stem", help="3D capture path, e.g. data/2026-11-08/3d-ref")
    parser.add_argument("--compare", default=None, help="2D capture of the same scene to show alongside")
    parser.add_argument("--perTx", action="store_true", help="Show each TX's range-azimuth map instead of the full 12-channel maps")
    parser.add_argument("--sliceRange", type=float, default=None, help="Range in m for the azimuth-elevation map. Default: strongest return")
    parser.add_argument("--start", type=float, default=None, help="Window start, seconds into each capture")
    parser.add_argument("--end", type=float, default=None, help="Window end, seconds into each capture")
    parser.add_argument("--floor", type=float, default=FLOOR_DB, help=f"Lowest dB shown. Default: {FLOOR_DB}")
    parser.add_argument("--maxRange", type=float, default=None, help="Top of the range axis in m. Default: full range")
    parser.add_argument("--show", action="store_true", help="Open the plot window as well as saving it")
    args = parser.parse_args()

    main(args.stem, args.compare, args.perTx, args.sliceRange, args.start, args.end, args.floor, args.maxRange, args.show)