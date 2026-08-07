"""
displacement.py — Slow-time phase → displacement helpers (RADC, 2D).

Slow-time processing: given a target range bin, extract the per-frame
complex phasor across all frames, convert its phase to displacement, and
provide FFTs of both the phasor and the displacement waveform.

Returns arrays and numbers only. No plotting — process.py owns matplotlib.
"""

import numpy as np
from scipy.signal import butter, filtfilt
from vmd3lib.config import LAMBDA_M, FS_SLOW, RANGE_WINDOW, SLOW_WINDOW
from vmd3lib.analysis import range_fft
from vmd3lib.iq import remove_dc


def slow_time_signal(cubes, target_bin, channel=None, window=RANGE_WINDOW):
    """
    Extract the slow-time complex phasor at one range bin.

    cubes      : array of decoded cubes, shape (frames, samples, chirps, channels)
    target_bin : range bin index to extract

    For each frame: range FFT along fast-time, take the chosen bin, average
    over chirps and channels -> one complex value per frame. Returns a
    complex 1-D array of length n_frames.
    """
    # Range FFT along the samples axis for every frame at once.
    fft_range = range_fft(cubes, axis=1, window=window)   # (frames, bins, chirps, ch)
    at_bin = fft_range[:, target_bin, :, :]               # (frames, chirps, channels)
    if channel is None:
        sig = np.mean(at_bin, axis=(1, 2))                # broadside sum
    else:
        sig = np.mean(at_bin[:, :, int(channel)], axis=1)  # one RX channel
    return sig


def phase_to_displacement(sig, wavelength=LAMBDA_M, dc='mean'):
    """
    Convert a slow-time complex phasor to displacement in millimeters.

    Phase is unwrapped to remove 2*pi jumps, then converted via the round-trip
    relation d = -phi * lambda / (4*pi). Returns displacement in mm (1-D real).

    No detrending is applied here — the raw unwrapped displacement is returned
    so the caller sees any real drift. Detrend downstream if desired.
    """
    if dc is not None:
        sig = remove_dc(sig, method=dc)
    phase = np.unwrap(np.angle(sig))
    displacement_m = -phase * wavelength / (4.0 * np.pi)
    return displacement_m * 1000.0                 # mm


def max_phase_step(sig):
    """
    Largest frame-to-frame phase jump, in radians. np.unwrap is only
    trustworthy below pi; anything approaching it means the displacement
    output is fiction. Expect ~0.9 rad for target 1, ~2.1 for target 2.
    """
    return float(np.max(np.abs(np.diff(np.angle(sig)))))


def motion_spectrum(sig, fs=FS_SLOW, n_pad=4096, window=SLOW_WINDOW):
    """
    FFT magnitude of a complex slow-time phasor (motion from the time-domain
    signal, before unwrapping). Mean-removed, zero-padded.

    Returns (freqs, magnitude) over the positive-frequency half.
    freqs in Hz, magnitude real.
    """
    centered = sig - np.mean(sig)
    if window == 'hann':
        centered = centered * np.hanning(len(centered))
    mag = np.abs(np.fft.fft(centered, n_pad))
    freqs = np.fft.fftfreq(n_pad, d=1.0 / fs)
    pos = freqs >= 0
    return freqs[pos], mag[pos]


def displacement_spectrum(displacement_mm, fs=FS_SLOW, n_pad=4096):
    """
    FFT magnitude of the real displacement waveform. Mean-removed, zero-padded.

    Returns (freqs, magnitude) over the positive-frequency half (real signal,
    so the spectrum is one-sided).
    """
    centered = displacement_mm - np.mean(displacement_mm)
    mag = np.abs(np.fft.fft(centered, n_pad))
    freqs = np.arange(n_pad) * fs / n_pad
    half = slice(0, n_pad // 2)
    return freqs[half], mag[half]


def dominant_frequency(freqs, mag, skip_dc=True):
    """
    Return the frequency of the largest spectral peak.

    skip_dc drops the zeroth bin so a residual DC offset doesn't win.
    Handy for printing 'measured motion frequency' next to the expected value.
    """
    start = 1 if skip_dc else 0
    peak_idx = int(np.argmax(mag[start:])) + start
    return freqs[peak_idx]


def lowpass_filter(x, fc, fs=FS_SLOW, order=6):
    """
    Zero-phase Butterworth low-pass for slow-time signals. Returns x
    unchanged if it's too short for filtfilt padding.
    """
    x = np.asarray(x, dtype=float)
    nyq = fs / 2.0
    if not (0 < fc < nyq):
        raise ValueError(f'Cutoff fc={fc} must be between 0 and Nyquist={nyq}.')
    b, a = butter(order, fc / nyq, btype='low', analog=False)
    padlen = 3 * (max(len(a), len(b)) - 1)
    if len(x) <= padlen:
        return x.copy()
    return filtfilt(b, a, x, padlen=padlen)
