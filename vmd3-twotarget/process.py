"""
process.py — Analyze a VMD3 RADC .bin capture (RSET 1, 2D, RADC-only).

Modes:
  profile       Amplitude vs range. Run first to find the target bins.
  motion        Per bin: I/Q, displacement, spectra, phase-step guard.
                With two targets, also prints an isolation report (each
                bin's own frequency vs the other's, in dB).
  constellation I/Q plane per bin, with arc span and revolution count.
  angle         Beamformed energy vs steer angle. Positive is to the
                right of boresight on this unit (confirmed empirically).

Bins: auto-detected by default; --manual overrides, --search fences the
search. The "expected from geometry" print comes from config.py and will
disagree with captures taken at a different range.

WARNING: omitting --channel averages all four RX channels, which is a
broadside beam — and this array nulls at +/-30 degrees. A target there
would be cancelled, not attenuated. Use --channel 0 for extraction and
--angle only as a corroborating pass. Isolation comes from range bins;
four channels give ~25 deg beamwidth, too coarse to separate 30 deg.

Nothing is saved; plots are shown interactively.

Examples:
  python process.py --file cap.bin --mode profile --avg 20
  python process.py --file cap.bin --mode motion --targets 2 --channel 0 --search 60 110
  python process.py --file cap.bin --mode constellation --targets 2 --channel 0
  python process.py --file cap.bin --mode angle --bin 89 --avg 20
"""

import argparse
import os

import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import CubicSpline
from vmd3lib.analysis import (
    bin_to_range,
    find_target_bins,
    range_fft,
    range_profile,
    range_to_bin,
)
from vmd3lib.beamform import angle_profile, steered_slow_time
from vmd3lib.config import (
    FS_SLOW,
    MAX_RANGE_M,
    RANGE_WINDOW,
    TARGET1_RANGE_M,
    TARGET2_RANGE_M,
)
from vmd3lib.decode import decode_radc_2d, get_frames
from vmd3lib.displacement import (
    bandpass_filter,
    displacement_spectrum,
    dominant_frequency,
    max_phase_step,
    motion_spectrum,
    phase_step_stats,
    phase_to_displacement,
    slow_time_signal,
)
from vmd3lib.iq import arc_span_deg, remove_dc, revolutions


def load_cubes(filepath, trim):
    """Read a .bin, decode every RADC frame, trim startup frames, stack."""
    frames = get_frames(filepath)
    if not frames:
        raise RuntimeError(f'No RADC frames found in {filepath}')
    cubes = np.stack([decode_radc_2d(f) for f in frames], axis=0)
    if trim > 0:
        cubes = cubes[trim:]
        print(f'Trimmed first {trim} frame(s) -> {cubes.shape[0]} remain.')
    print(f'{cubes.shape[0]} frames ready (shape {cubes.shape}).')
    check_timing(filepath, trim, cubes.shape[0])
    return cubes


def check_timing(filepath, trim, n_frames):
    """
    Read the timestamp sidecar record.py writes and report frame gaps.
    A dropped frame doubles the phase step, which silently corrupts the
    unwrap from that point on — so this runs before anything is trusted.
    """
    ts_path = os.path.splitext(filepath)[0] + '_timestamps.npy'
    if not os.path.exists(ts_path):
        print('[timing] No timestamp sidecar — cannot check for gaps.')
        return
    ts_all = np.load(ts_path)
    if ts_all.size != n_frames + trim:
        print(f'[timing] Sidecar has {ts_all.size} timestamps but '
              f'{n_frames + trim} frames decoded — indices below are '
              f'approximate.')
    ts = ts_all[trim:]
    if ts.size < 2:
        return
    diffs = np.diff(ts)
    dt_ref = float(np.median(diffs))
    bad = np.flatnonzero(diffs > 2.0 * dt_ref)
    print(f'[timing] median dt {dt_ref * 1000:.1f} ms, '
          f'max {diffs.max() * 1000:.1f} ms, {bad.size} gap(s).')
    if bad.size:
        print(f'[timing] *** Gaps at frame index {bad[:10].tolist()}'
              f'{" ..." if bad.size > 10 else ""} — displacement after the '
              f'first gap may carry a 2*pi offset. ***')


# ---------------------------------------------------------------------
# Profile mode
# ---------------------------------------------------------------------
def run_profile(cubes, avg, window=RANGE_WINDOW):
    """Show amplitude-vs-range profiles, in meters and in range bins."""
    n = min(avg, cubes.shape[0])
    profiles = [range_profile(cubes[i], window=window) for i in range(n)]
    profile = np.mean(profiles, axis=0)
    print(f'Range profile averaged over {n} frame(s).')

    bins = np.arange(len(profile))
    rng = bins * MAX_RANGE_M / len(profile)

    fig, axs = plt.subplots(2, 1, figsize=(10, 8))
    fig.suptitle(f'Range profile ({n} frame(s) averaged)')

    # ---- Top: range in meters ----
    axs[0].plot(rng, profile, linewidth=1.2)
    axs[0].set_xlabel('Range (m)')
    axs[0].set_ylabel('Amplitude')
    axs[0].grid(True, alpha=0.3)

    # ---- Bottom: range bin index ----
    axs[1].plot(bins, profile, linewidth=1.2, color='tab:orange')
    axs[1].set_xlabel('Range bin')
    axs[1].set_ylabel('Amplitude')
    axs[1].grid(True, alpha=0.3)

    peak_bin = int(np.argmax(profile[10:])) + 10   # skip leakage region
    print(f'Peak at bin {peak_bin} (~{peak_bin * MAX_RANGE_M / len(profile):.2f} m)')

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()


# ---------------------------------------------------------------------
# Motion mode
# ---------------------------------------------------------------------
def resolve_bins(cubes, n_targets, manual, avg_for_profile=10, search_window=None):
    """
    Decide which range bins to analyze.
      auto   : find the n_targets strongest peaks from an averaged profile.
      manual : use the bins the user passed.
    Returns a list of bin indices.
    """
    print(f'Expected from geometry: bins '
              f'{range_to_bin(TARGET1_RANGE_M)} and {range_to_bin(TARGET2_RANGE_M)}')
    if manual is not None:
        if len(manual) != n_targets:
            raise ValueError(
                f'--targets {n_targets} but --manual got {len(manual)} '
                f'bin(s): {manual}')
        return list(manual)

    # auto
    n = min(avg_for_profile, cubes.shape[0])
    profile = np.mean([range_profile(cubes[i]) for i in range(n)], axis=0)
    bins = find_target_bins(profile, n_targets=n_targets, search_window=search_window)
    if len(bins) < n_targets:
        raise RuntimeError(
            f'Auto-detection found only {len(bins)} target(s), '
            f'asked for {n_targets}. Try --manual, or check the profile.')
    return bins


def analyze_target(cubes, target_bin, angle_deg=None, channel=None, band=None):
    """
    Full slow-time analysis at one range bin, showing its 4 plots.
    If angle_deg is given, beamform (steer) to that angle instead of
    averaging channels. Returns (peak_to_peak_mm, dominant_freq_hz).
    """
    rng = bin_to_range(target_bin)
    if angle_deg is None:
        sig = slow_time_signal(cubes, target_bin, channel=channel)
        steer_label = f'ch {channel}' if channel is not None else 'broadside'
    else:
        sig = steered_slow_time(cubes, target_bin, angle_deg)
        steer_label = f'{angle_deg:+.0f} deg'

    sig_c = remove_dc(sig)
    step, p99 = phase_step_stats(sig_c)
    print(f'  bin {target_bin} [{steer_label}]: phase step max {step:.2f} rad, '
          f'p99 {p99:.2f} rad, {revolutions(sig_c):.2f} revolutions')
    if p99 >= 0.8 * np.pi:
        print('  *** phase steps near pi — unwrap may be ambiguous ***')
    elif step >= 0.8 * np.pi:
        print('  (note: isolated step near pi)')

    disp = phase_to_displacement(sig)

    if band is not None:
        disp_band = bandpass_filter(disp, band[0], band[1])
        edge = int(10 * FS_SLOW)
        core = disp_band[edge:-edge] if len(disp_band) > 3 * edge else disp_band
        print(f'  band-passed {band[0]}-{band[1]} Hz: '
              f'peak-to-peak {np.ptp(core):.3f} mm')

    n_frames = len(sig)
    frame_idx = np.arange(n_frames)

    # ---- I / Q vs slow-time frame index (two subplots) ----
    fig, axs = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    fig.suptitle(f'Slow-time I/Q — bin {target_bin} (~{rng:.2f} m)')
    axs[0].plot(frame_idx, np.real(sig), linewidth=1.2)
    axs[0].set_ylabel('I amplitude')
    axs[0].grid(True, alpha=0.3)
    axs[1].plot(frame_idx, np.imag(sig), linewidth=1.2, color='tab:orange')
    axs[1].set_xlabel('Slow-time frame index')
    axs[1].set_ylabel('Q amplitude')
    axs[1].grid(True, alpha=0.3)
    plt.tight_layout(rect=[0, 0, 1, 0.96])

    # ---- Displacement vs time ----
    t = frame_idx / FS_SLOW
    plt.figure(figsize=(10, 4))
    plt.plot(t, disp, linewidth=1.2)
    plt.xlabel('Time (s)')
    plt.ylabel('Displacement (mm)')
    plt.title(f'Displacement — bin {target_bin} (~{rng:.2f} m)')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    # ---- FFT of the I/Q signal ----
    f_iq, m_iq = motion_spectrum(sig)
    plt.figure(figsize=(10, 4))
    plt.plot(f_iq, m_iq, linewidth=1.2)
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('Magnitude')
    plt.title(f'FFT of I/Q signal — bin {target_bin} (~{rng:.2f} m)')
    plt.xlim([0, 2])
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    # ---- FFT of the displacement waveform ----
    f_d, m_d = displacement_spectrum(disp)
    plt.figure(figsize=(10, 4))
    plt.plot(f_d, m_d, linewidth=1.2)
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('Magnitude')
    plt.title(f'Displacement spectrum — bin {target_bin} (~{rng:.2f} m)')
    plt.xlim([0, 2])
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    pp = float(np.ptp(disp))
    fpk = dominant_frequency(f_d, m_d)
    return pp, fpk, f_d, m_d


def run_motion(cubes, n_targets, manual, angle=None, channel=None, search_window=None, band=None):
    bins = resolve_bins(cubes, n_targets, manual, search_window=search_window)
    print(f'Analyzing {len(bins)} target(s) at bin(s): {bins}')

    results, spectra = [], []
    for b in bins:
        pp, fpk, f_d, m_d = analyze_target(cubes, b, angle_deg=angle, channel=channel, band=band)
        results.append((b, pp, fpk))
        spectra.append((f_d, m_d))

    print('\n--- Results ---')
    for b, pp, fpk in results:
        print(f'  bin {b:3d} (~{bin_to_range(b):.2f} m): '
              f'peak-to-peak {pp:.3f} mm, dominant {fpk:.3f} Hz')

    if len(results) == 2:
        report_isolation(results, spectra)

    plt.show()


def report_isolation(results, spectra):
    """
    For each bin, compare the magnitude at its own frequency against the
    magnitude at the OTHER target's frequency. This ratio is the evidence
    that range separation actually isolated the two targets.
    """
    print('\n--- Isolation ---')
    freqs = [r[2] for r in results]
    for i, (b, _, own_f) in enumerate(results):
        other_f = freqs[1 - i]
        f_ax, mag = spectra[i]
        own = mag[np.argmin(np.abs(f_ax - own_f))]
        cross = mag[np.argmin(np.abs(f_ax - other_f))]
        ratio_db = 20 * np.log10(own / cross) if cross > 0 else np.inf
        print(f'  bin {b:3d}: own {own_f:.3f} Hz vs other {other_f:.3f} Hz '
              f'-> {ratio_db:+.1f} dB')


def run_constellation(cubes, bins, channel=None, angle=None, smooth=None):
    """
    I/Q constellation per bin, DC-removed, equal aspect. Closed loops mean
    the phasor swept past 2*pi; a short arc means small stroke.
    """
    fig, axs = plt.subplots(1, len(bins), figsize=(5.5 * len(bins), 5.5),
                            squeeze=False)
    for ax, b in zip(axs[0], bins):
        if angle is None:
            sig = slow_time_signal(cubes, b, channel=channel)
        else:
            sig = steered_slow_time(cubes, b, angle)
        sig = remove_dc(sig, method='mean')
        stats_sig = sig
        if smooth > 1:
            sig = _upsample(sig, smooth)
        ax.plot(np.real(sig), np.imag(sig), '-', linewidth=0.8, alpha=0.7)
        ax.set_aspect('equal', 'datalim')
        ax.set_xlabel('I'); ax.set_ylabel('Q')
        ax.set_title(f'bin {b} (~{bin_to_range(b):.2f} m)\n'
                     f'{arc_span_deg(sig):.0f} deg, {revolutions(sig):.2f} rev')
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()\


def _upsample(sig, factor):
    """Cubic-spline interpolate a complex signal for display only."""
    t = np.arange(len(sig))
    t_fine = np.linspace(0, len(sig) - 1, len(sig) * factor)
    return (CubicSpline(t, np.real(sig))(t_fine)
            + 1j * CubicSpline(t, np.imag(sig))(t_fine))


# ---------------------------------------------------------------------
# Angle mode
# ---------------------------------------------------------------------
def run_angle(cubes, target_bin, angle_range, avg):
    """
    Sweep steer angle at one range bin and show energy-vs-angle.
    Averages the angle profile over the first `avg` frames.
    This is the beamforming analog of profile mode: it shows WHERE in
    angle the energy sits at a chosen range bin.
    """
    n = min(avg, cubes.shape[0])
    profiles = []
    for i in range(n):
        fft_range = range_fft(cubes[i], axis=0)   # (range_bins, chirps, channels)
        angles, mag = angle_profile(fft_range, target_bin, angle_range)
        profiles.append(mag)
    mag = np.mean(profiles, axis=0)
    print(f'Angle profile at bin {target_bin} (~{bin_to_range(target_bin):.2f} m), '
          f'averaged over {n} frame(s).')

    peak_angle = angles[int(np.argmax(mag))]
    print(f'Peak energy at steer angle: {peak_angle:+.1f} deg')

    plt.figure(figsize=(10, 4.5))
    plt.plot(angles, mag, linewidth=1.2)
    plt.axvline(peak_angle, color='tab:red', linestyle=':', alpha=0.7,
                label=f'peak {peak_angle:+.1f} deg')
    plt.xlabel('Steer angle (deg)')
    plt.ylabel('Beamformed magnitude')
    plt.title(f'Angle profile at bin {target_bin} '
              f'(~{bin_to_range(target_bin):.2f} m), {n} frame(s) avg')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


# ---------------------------------------------------------------------
if __name__ == '__main__':
    DEFAULT_FILE = '/home/shaylon/x1-vmd3/vmd3-twotarget/data/radc/2026-08-04/twotarget-30right-5mmhuman.bin'

    p = argparse.ArgumentParser(description='Analyze a VMD3 RADC capture.')
    p.add_argument('--file', default=DEFAULT_FILE, 
                   help=f'Path to the .bin file (default: {DEFAULT_FILE}).')
    p.add_argument('--mode', choices=['profile', 'motion', 'angle', 'circle'], required=True)
    p.add_argument('--trim', type=int, default=1, 
                   help='Startup frames to drop (default: 1).')
    p.add_argument('--channel', type=int, default=None, choices=[0, 1, 2, 3],
                   help='Single RX channel (no array factor, no nulls). Omit for a broadside sum — which nulls +/-30 deg.')
    p.add_argument('--window', type=str, default=None, choices=['hann', 'rect'],
                   help='Override the config range window (A/B testing).')
    p.add_argument('--search', type=int, nargs=2, metavar=('LO', 'HI'), default=None, 
                   help='Fence auto-detect to a bin range.')
    # profile
    p.add_argument('--avg', type=int, default=1, 
                   help='Frames to average for the profile (default: 1).')
    # motion
    p.add_argument('--targets', type=int, default=1, choices=[1, 2], 
                   help='Number of targets to analyze (motion mode).')   # Use for circle mode too
    p.add_argument('--band', type=float, nargs=2, metavar=('LO', 'HI'), default=None,
                   help='Band-pass the displacement before measuring peak-to-peak, e.g. --band 0.1 0.6 to strip postural drift from a human target.')
    # angle
    p.add_argument('--bin', type=int, default=None,
                   help='Range bin for angle mode / steered motion. Angle mode requires it; motion uses it with --angle.')
    p.add_argument('--angle-range', type=float, default=67.0,
                   help='Angle sweep half-range in degrees (default: 67).')
    p.add_argument('--angle', type=float, default=None,
                   help='Steer angle for motion mode (deg). Omit = channel-average.')
    # circle
    p.add_argument('--smooth', type=int, default=0)
    sel = p.add_mutually_exclusive_group()
    sel.add_argument('--auto', action='store_true', 
                     help='Auto-detect the strongest target bin(s).')
    sel.add_argument('--manual', type=int, nargs='+', metavar='BIN', 
                     help='Manually specify target bin(s), e.g. --manual 79 82.')
    args = p.parse_args()

    cubes = load_cubes(args.file, args.trim)
    if args.mode == 'profile':
        run_profile(cubes, args.avg, args.window or RANGE_WINDOW)
    elif args.mode == 'angle':
        if args.bin is None:
            p.error('--mode angle requires --bin (which range bin to sweep).')
        run_angle(cubes, args.bin, args.angle_range, args.avg)
    elif args.mode == 'circle':
        bins = resolve_bins(cubes, args.targets, args.manual, search_window=args.search)
        run_constellation(cubes, bins, channel=args.channel, angle=args.angle, smooth=args.smooth)
    else: # motion
        run_motion(cubes, args.targets, args.manual, angle=args.angle, channel=args.channel, search_window=args.search, band=args.band)
        