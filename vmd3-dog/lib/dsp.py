"""Signal processing for VMD3 datat cubes."""

import numpy as np

from config import ANGLE_SIGN, LEAKAGE_CUTOFF_M, RX_SPACING_M, WAVELENGTH_M
from lib.capture import decode_radc

def range_axis(meta, n_bins):
    """Return the range in meters of each range bin."""
    return np.arange(n_bins) * meta["vmd3_setting"]["max_range"] / n_bins

def range_fft(cube, n_fft=None):
    """Range FFT over samples with a Hamming window."""
    window = np.hamming(cube.shape[1]).astype(np.float32)
    return np.fft.fft(cube * window[:, None, None], n=n_fft, axis=1)

def zero_doppler(range_cube):
    """Keep only the stationary part by summing chirps with a Hann window."""
    window = np.hanning(range_cube.shape[2]).astype(np.float32)
    window /= window.sum()
    return (range_cube * window[:, None]).sum(axis=2)

def zero_doppler_profiles(payloads, meta, block=64, n_fft=None):
    """Decode payloads to zero Doppler profiles (frames, range, channels), a block at a time."""
    blocks = [zero_doppler(range_fft(decode_radc(payloads[i:i + block], meta), n_fft))
              for i in range(0, len(payloads), block)]
    return np.concatenate(blocks)

def steering_matrix(angles_deg, n_channels):
    """Return the (channels, angles) phasors that undo each angle's phase across the RX array."""
    k = 2 * np.pi / WAVELENGTH_M
    x = (np.arange(n_channels) - (n_channels - 1) / 2) * RX_SPACING_M   # RX positions about the array center
    sin_theta = np.sin(np.radians(angles_deg))
    return np.exp(1j * ANGLE_SIGN * k * np.outer(x, sin_theta)).astype(np.complex64)

def range_angle(profiles, angles_deg):
    """Beamform (frames, range, channels) into (frames, range, angles) with uniform weights."""
    steer = steering_matrix(angles_deg, profiles.shape[-1])
    return profiles @ steer / profiles.shape[-1]

def to_db(power, floor_db=-60, ref=None):
    """Convert power to dB relative to ref (default its peak), clipped at floor_db."""
    ref = power.max() if ref is None else ref
    ratio = np.maximum(power / ref, 10 ** (floor_db / 10))
    return 10 * np.log10(ratio)

def all_doppler_power(range_cube, angles_deg):
    """Beamformed power summed over every Doppler bin, (frames, range, angles)."""
    steer = steering_matrix(angles_deg, range_cube.shape[-1]) / range_cube.shape[-1]
    window = np.hanning(range_cube.shape[2]).astype(np.float32)
    weights = window ** 2 / (window **2).sum()   # same scale as zero_doppler for a still target
    power = np.empty((range_cube.shape[0], range_cube.shape[1], len(angles_deg)), dtype=np.float32)
    for f in range(len(range_cube)):   # one frame at a time keeps memory small
        beams = range_cube[f] @ steer
        power[f] = (np.abs(beams) ** 2 * weights[:, None]).sum(axis=1)
    return power

def range_angle_power(cube, angles_deg, doppler="zero"):
    """Range-angle power per frame from a RADC cube, keeping zero Doppler or all of it."""
    range_cube = range_fft(cube)
    if doppler == "zero":
        return np.abs(range_angle(zero_doppler(range_cube), angles_deg)) ** 2
    return all_doppler_power(range_cube, angles_deg)

def find_peak(db, ranges, angles):
    """Return (range_m, angle_deg) of the strongest pixel past the leakage zone."""
    masked = np.where(ranges[:, None] >= LEAKAGE_CUTOFF_M, db, -np.inf)
    i, j = np.unravel_index(np.argmax(masked), masked.shape)
    return ranges[i], angles[j]

def complex_correlation(a, b):
    """Per channel match between two (range, channels) complex profiles, 1 is identical."""
    num = np.abs(np.sum(a * np.conj(b), axis =0))
    den = np.sqrt(np.sum(np.abs(a) ** 2, axis=0) * np.sum(np.abs(b) ** 2, axis=0))
    return num / den
