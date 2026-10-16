"""Phase stability of one point in a VMD3 capture, shown as radial displacement over time."""

import argparse
import matplotlib.pyplot as plt
import numpy as np

from config import ANGLE_LIMIT_DEG, ANGLE_STEP_DEG, LEAKAGE_CUTOFF_M, PLOTS_SUBDIR, WAVELENGTH_M
from lib.capture import load_window, to_stem
from lib.dsp import find_peak, range_angle, range_axis, steering_matrix, to_db, zero_doppler_profiles
from lib.plots import draw_range_angle

def main(stem, window, point_range, point_angle, floor, maxRange, show):
    stem = to_stem(stem)
    payloads, log, meta = load_window(stem, *window)
    profiles = zero_doppler_profiles(payloads, meta)
    times = log["elapsed_s"]

    # Averaged map, and the point to track (strongest return unless given)
    angles = np.arange(-ANGLE_LIMIT_DEG, ANGLE_LIMIT_DEG + ANGLE_STEP_DEG, ANGLE_STEP_DEG)
    power = np.mean(np.abs(range_angle(profiles, angles)) ** 2, axis=0)
    ranges = range_axis(meta, power.shape[0])
    db = to_db(power, floor, power[ranges >= LEAKAGE_CUTOFF_M].max())
    peak_r, peak_a = find_peak(db, ranges, angles)
    a = peak_a if point_angle is None else point_angle
    i = int(np.argmin(np.abs(ranges - (peak_r if point_range is None else point_range))))
    j = int(np.argmin(np.abs(angles - a)))

    # Complex value at that point for every frame
    steer = steering_matrix([a], profiles.shape[-1])[:, 0] / profiles.shape[-1]
    y = profiles[:, i, :] @ steer

    # Phase to radial displacement about its mean, and magnitude over time
    phase = np.unwrap(np.angle(y))
    disp_mm = (phase - phase.mean()) * WAVELENGTH_M / (4 * np.pi) * 1000
    mag_db = 20 * np.log10(np.abs(y) / np.abs(y).max())

    # Stability numbers
    rms = disp_mm.std()
    p2p = disp_mm.max() - disp_mm.min()
    coherence = np.abs(y.sum()) / np.abs(y).sum()
    limit = WAVELENGTH_M / 8 * 1000

    # Displacement spectrum, assuming even frame spacing
    fs = 1 / np.median(np.diff(times))
    taper = np.hanning(len(disp_mm))
    spectrum = 2 * np.abs(np.fft.rfft(disp_mm * taper)) / taper.sum()   # amplitude in mm
    freqs = np.fft.rfftfreq(len(disp_mm), 1 / fs)
    sway_hz = freqs[1:][np.argmax(spectrum[1:])]   # skip the zero frequency bin

    # Plot map, displacement, magnitude, and spectrum
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), layout="constrained")
    mesh = draw_range_angle(axes[0, 0], db, ranges, angles, floor, maxRange)
    axes[0, 0].plot(a, ranges[i], "c+", markersize=14, markeredgewidth=2)
    axes[0, 0].set_title(f"Tracked point {ranges[i]:.2f} m, {a:+.1f} deg ({db[i, j]:.1f} dB)")
    fig.colorbar(mesh, ax=axes[0, 0], label="dB")

    axes[0, 1].plot(times, disp_mm)
    axes[0, 1].axhspan(-limit / 2, limit / 2, color="r", alpha=0.1, label="λ/8 band")
    axes[0, 1].set(xlabel="Time (s)", ylabel="Radial displacement (mm)",
                   title=f"RMS {rms:.3f} mm, peak to peak {p2p:.3f} mm")
    axes[0, 1].legend()

    axes[1, 0].plot(times, mag_db)
    axes[1, 0].set(xlabel="Time (s)", ylabel="Magnitude (dB rel. max)", title=f"Frame coherence {coherence:.4f}")

    axes[1, 1].plot(freqs, spectrum)
    axes[1, 1].set(xlabel="Frequency (Hz)", ylabel="Amplitude (mm)", title=f"Displacement spectrum, strongest {sway_hz:.2f} Hz")
    fig.suptitle(f"{stem.name} | {times[0]:.1f} to {times[-1]:.1f} s, {len(times)} frames")

    # Save to the plots folder and report
    out = stem.parent / PLOTS_SUBDIR / f"{stem.name}_stability_{window[0]:g}-{window[1]:g}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"Tracked {ranges[i]:.2f} m, {a:+.1f} deg at {db[i, j]:.1f} dB, {len(times)} frames")
    if db[i, j] < -20:
        print("Warning: weak point, phase may be mostly noise")
    print(f"Displacement RMS {rms:.3f} mm, peak to peak {p2p:.3f} mm (λ/8 = {limit:.2f} mm)")
    print(f"Frame coherence {coherence:.4f}")
    print(f"Strongest sway {sway_hz:.2f} Hz")
    print(f"Saved {out}")
    if show:
        plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase stability of one point in a VMD3 capture")
    parser.add_argument("stem", help="Capture path, e.g. data/2026-10-15/sitting-real")
    parser.add_argument("--window", nargs=2, type=float, required=True, metavar=("START", "END"), help="Time window, seconds into the capture")
    parser.add_argument("--range", type=float, default=None, help="Range of the point to track in m. Default: strongest return")
    parser.add_argument("--angle", type=float, default=None, help="Angle of the point to track in deg. Default: strongest return")
    parser.add_argument("--floor", type=float, default=-40, help="Lowest dB shown. Default: -40")
    parser.add_argument("--maxRange", type=float, default=None, help="Top of the range axis in m. Default: full range")
    parser.add_argument("--show", action="store_true", help="Open the plot window as well as saving it")
    args = parser.parse_args()

    main(args.stem, args.window, args.range, args.angle, args.floor, args.maxRange, args.show)
