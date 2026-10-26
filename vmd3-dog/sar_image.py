"""Form a SAR image from a VMD3 sweep and its arm track, optionally background subtracted."""

import argparse

import matplotlib.pyplot as plt
import numpy as np

from config import FLOOR_DB, PLOTS_SUBDIR, RANGE_FFT_SIZE
from lib.capture import to_stem
from lib.dsp import range_axis, to_db
from lib.sar import (backproject, expected_widths, fuse_power, image_grid, image_metrics, interpolate_profiles,
                     load_sweep, rx_phase_centers, subtract_background, estimate_range_offset, phase_sign_check)


def main(stem, track, targetRange, clockOffset, autoClock, background, bgTrack, bgClockOffset, rangeOffset, calibrate, floor, show):
    stem = to_stem(stem)
    positions, profiles, meta, clockOffset = load_sweep(stem, track, clockOffset, autoClock)
    ranges = range_axis(meta, RANGE_FFT_SIZE)
    aperture = positions.max() - positions.min()
    spacing = np.median(np.abs(np.diff(positions)))
    if autoClock:
        print(f"Clock offset {clockOffset * 1000:+.0f} ms")

    # Subtract a background sweep resampled to this sweep's positions, if given
    if background:
        bg_pos, bg_prof, _, bg_offset = load_sweep(background, bgTrack, bgClockOffset, autoClock)
        bg_prof = interpolate_profiles(bg_prof, bg_pos, positions)
        profiles, rho, reduction = subtract_background(profiles, bg_prof, ranges, targetRange)
        if autoClock:
            print(f"Background clock offset {bg_offset * 1000:+.0f} ms")
        print(f"Background match per RX: {np.round(rho, 4)}")
        print(f"Clutter removed per RX: {np.round(reduction, 1)} dB")

    # Range calibration: shift the range axis so the target lands at the tape range
    if calibrate:
        offsets, measured = estimate_range_offset(profiles, ranges, targetRange)
        rangeOffset = float(np.mean(offsets))
        print(f"Radar puts the target at {np.round(measured * 100, 1)} cm per RX, tape {targetRange * 100:.1f} cm")
        print(f"Range offset {rangeOffset * 100:+.1f} cm")

    # Focus each RX on the image grid, then add their powers
    bin_m = meta["vmd3_setting"]["max_range"] / RANGE_FFT_SIZE
    centers = rx_phase_centers(positions)
    cross, down = image_grid(targetRange)
    images = np.stack([backproject(profiles[:, :, rx], centers[:, rx], cross, down, bin_m, rangeOffset)
                       for rx in range(profiles.shape[2])])
    power = fuse_power(images)
    db = to_db(power, floor)

    # Peak and -3 dB widths, against the ideal for this geometry
    m = image_metrics(power, cross, down)
    ideal_cross, ideal_range = expected_widths(targetRange, aperture, meta)

    # Which phase sign focuses the peak better, per RX
    signs = phase_sign_check(profiles, positions, m["x"], m["range"], bin_m, rangeOffset)

    # Plot in cm, positive cross-range to the right
    fig, ax = plt.subplots(figsize=(7, 6), layout="constrained")
    extent = [cross[0] * 100, cross[-1] * 100, down[0] * 100, down[-1] * 100]
    mesh = ax.imshow(db, origin="lower", extent=extent, aspect="equal", cmap="inferno", vmin=floor, vmax=0)
    ax.plot(m["x"] * 100, m["range"] * 100, "c+", markersize=14, markeredgewidth=2)
    ax.set(xlabel="Cross-range (cm, + is right)", ylabel="Slant range (cm)",
           title=f"{stem.name}{' minus background' if background else ''} | {len(positions)} frames, "
                 f"{aperture * 100:.1f} cm aperture\npeak x {m['x'] * 100:+.1f} cm, range {m['range'] * 100:.1f} cm")
    fig.colorbar(mesh, ax=ax, label="dB")

    # Save to the plots folder and report
    out = stem.parent / PLOTS_SUBDIR / f"{stem.name}_sar{'_bgsub' if background else ''}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"{len(positions)} frames, {aperture * 100:.1f} cm aperture, {spacing * 1000:.2f} mm spacing")
    print(f"Peak x {m['x'] * 100:+.1f} cm, range {m['range'] * 100:.1f} cm")
    print(f"Cross-range width {m['cross_width'] * 100:.2f} cm (ideal {ideal_cross * 100:.2f})")
    print(f"Range width {m['range_width'] * 100:.2f} cm (ideal {ideal_range * 100:.2f})")
    print(f"Phase sign check at the peak: +1 {np.round(signs[1], 3)}, -1 {np.round(signs[-1], 3)}")
    print(f"Saved {out}")
    if show:
        plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAR image from a VMD3 sweep and arm track")
    parser.add_argument("stem", help="Capture path, e.g. data/2026-10-23/sim-point")
    parser.add_argument("--track", default=None, help="Arm track CSV. Default: <stem>_arm.csv")
    parser.add_argument("--targetRange", type=float, required=True, help="Target slant range at sweep center in m")
    parser.add_argument("--clockOffset", type=float, default=0.0, help="Arm clock minus radar clock in s. Default: 0")
    parser.add_argument("--autoClock", action="store_true", help="Estimate clock offsets from the data")
    parser.add_argument("--background", default=None, help="Background sweep to subtract, same setup without the target")
    parser.add_argument("--bgTrack", default=None, help="Background arm track CSV. Default: <background>_arm.csv")
    parser.add_argument("--bgClockOffset", type=float, default=0.0, help="Background arm clock minus radar clock in s. Default: 0")
    parser.add_argument("--rangeOffset", type=float, default=0.0, help="Range calibration offset in m. Default: 0")
    parser.add_argument("--calibrate", action="store_true", help="Estimate the range offset from the target and tape range")
    parser.add_argument("--floor", type=float, default=FLOOR_DB, help=f"Lowest dB shown. Default: {FLOOR_DB}")
    parser.add_argument("--show", action="store_true", help="Open the plot window as well as saving it")
    args = parser.parse_args()

    main(args.stem, args.track, args.targetRange, args.clockOffset, args.autoClock, args.background,
         args.bgTrack, args.bgClockOffset, args.rangeOffset, args.calibrate, args.floor, args.show)