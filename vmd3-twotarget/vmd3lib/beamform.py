"""
beamform.py — Digital azimuth beamforming for the 4 RX channels (2D mode).

Steers the 4-channel array to a chosen look angle by applying phase weights,
operating on range-FFT'd data (beamform *within* a range bin). Ported from
Ethan Chee's MATLAB wBF steering loop. Assumes lambda/2 element spacing,
which the datasheet confirms (2.464 mm at 62 GHz ~= 0.51 lambda).

Resolution: 4 elements at lambda/2 gives a 3 dB beamwidth near 25 degrees
and a first broadside null at 30 degrees. Two targets 30 degrees apart are
therefore about one beamwidth apart — too close for beamforming to be the
primary way to tell them apart. Range bins do the actual isolation; this
module corroborates it and gives the angular narrative.

Watch the nulls. Plain channel-averaging IS a broadside beam, so it nulls
anything at +/-30 degrees. Use array_nulls() before choosing a target angle,
and prefer a single RX channel (no array factor, no nulls) when you just
want a clean extraction.

No plotting, no side effects on import.
"""

import numpy as np

from vmd3lib.analysis import range_fft
from vmd3lib.config import N_CHANNELS, RANGE_WINDOW


def steering_weights(angle_deg, n_ch=N_CHANNELS):
    """
    Phase weights that steer the array to `angle_deg` off boresight.

    For element n at angle alpha: exp(-j*pi*n*sin(alpha)), the lambda/2
    steering vector. Returns a length-n_ch complex array.
    """
    alpha = np.deg2rad(angle_deg)
    n = np.arange(n_ch)
    return np.exp(-1j * np.pi * n * np.sin(alpha))


def steering_matrix(angles_deg, n_ch=N_CHANNELS):
    """
    Steering weights for many angles at once. Returns (n_angles, n_ch).
    Vectorized form of steering_weights for sweeps.
    """
    alpha = np.deg2rad(np.asarray(angles_deg, dtype=float))
    n = np.arange(n_ch)
    return np.exp(-1j * np.pi * np.outer(np.sin(alpha), n))


def beamform_at(fft_range, target_bin, angle_deg):
    """
    Form a beam at one steer angle, at one range bin, for one frame.

    fft_range  : range-FFT'd cube, (range_bins, chirps, channels), complex.
    target_bin : range bin to beamform within.
    angle_deg  : steer angle in degrees.

    Applies the steering weights across channels and averages over chirps,
    giving one complex value: the beamformed return at (bin, angle) for
    this frame.
    """
    w = steering_weights(angle_deg, fft_range.shape[2])
    at_bin = fft_range[target_bin, :, :]          # (chirps, channels)
    beamed = at_bin @ np.conj(w)                  # (chirps,) steer across channels
    return np.mean(beamed)                        # average over chirps


def angle_profile(fft_range, target_bin, angle_range=67.0, n_angles=512):
    """
    Sweep steer angle at one range bin and return |beamformed energy| vs angle.

    fft_range   : range-FFT'd cube for ONE frame, (range_bins, chirps, channels).
    target_bin  : range bin to sweep within.
    angle_range : sweep spans [-angle_range, +angle_range] degrees.
    n_angles    : number of steer angles across that span.

    Returns (angles_deg, magnitude), both length n_angles.
    """
    angles = np.linspace(-angle_range, angle_range, n_angles)
    W = steering_matrix(angles, fft_range.shape[2])
    at_bin = fft_range[target_bin, :, :]        # (chirps, channels)
    beamed = at_bin @ np.conj(W).T              # (chirps, n_angles)
    mag = np.abs(np.mean(beamed, axis=0))       # average chirps, then magnitude
    return angles, mag


def steered_slow_time(cubes, target_bin, angle_deg, window=RANGE_WINDOW):
    """
    Extract a slow-time phasor at one range bin, steered to one angle.

    cubes      : (frames, samples, chirps, channels) decoded stack.
    target_bin : range bin to beamform within.
    angle_deg  : steer angle in degrees.

    Range-FFTs every frame, beamforms at (bin, angle) per frame, returns a
    complex 1-D array of length n_frames — a drop-in replacement for
    displacement.slow_time_signal, but angle-steered instead of channel-averaged.
    """
    fft_range = range_fft(cubes, axis=1, window=window)   # (frames, bins, chirps, ch)
    w = steering_weights(angle_deg, cubes.shape[3])
    at_bin = fft_range[:, target_bin, :, :]       # (frames, chirps, channels)
    beamed = at_bin @ np.conj(w)                  # (frames, chirps) steered
    return np.mean(beamed, axis=1)                # (frames,) average over chirps


def array_nulls(steer_deg=0.0, n_ch=N_CHANNELS, d_over_lambda=0.5):
    """
    Angles (deg) where a beam steered to steer_deg has array-factor nulls.

    Nulls fall where (d/lambda)*(sin a - sin a0) = k/n_ch, k not a multiple
    of n_ch. For this 4-element half-wavelength array a broadside beam
    (which is what plain channel-averaging gives you) nulls at +/-30 and
    +/-90 degrees. Check this before choosing a target angle.
    """
    s0 = np.sin(np.deg2rad(steer_deg))
    out = []
    for k in range(1, n_ch):
        for sign in (+1, -1):
            s = s0 + sign * k / (n_ch * d_over_lambda)
            if abs(s) <= 1.0:
                out.append(float(np.rad2deg(np.arcsin(s))))
    return sorted(set(np.round(out, 2)))