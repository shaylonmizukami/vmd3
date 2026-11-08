"""MIMO helpers for VMD3 3D mode: channel groups, beamforming, and calibration."""

import json
import numpy as np

from config import WAVELENGTH_M
from lib.dsp import range_angle
from radar3d.config3d import GEOMETRY_FILE, N_RX, N_TX

K = 2 * np.pi / WAVELENGTH_M

def split_tx(profiles):
    """Reshape (frames, range, 12) profiles to (frames, range, TX, RX)."""
    return profiles.reshape(*profiles.shape[:-1], N_TX, N_RX)

def per_tx_power(profiles, angles_deg):
    """Frame-averaged range-azimuth power from each TX's four RX, shaped (TX, range, angles)."""
    groups = split_tx(profiles)
    return np.stack([np.mean(np.abs(range_angle(groups[..., tx, :], angles_deg)) ** 2, axis=0)
                     for tx in range(N_TX)])

def combined_power(per_tx):
    """Average the per-TX power maps into one range-azimuth map."""
    return per_tx.mean(axis=0)

def load_geometry(path=GEOMETRY_FILE):
    """Channel positions (12, 2) in m and calibration phases (12,) in rad, saved by channels.py."""
    if not path.exists():
        raise SystemExit(f"No {path.name} yet, run radar3d.channels with --save first")
    geometry = json.loads(path.read_text())
    return np.array(geometry["positions_m"]), np.array(geometry["calibration_rad"])

def steering_3d(positions, calibration, az_deg, el_deg):
    """(channels, directions) phasors that undo each direction's phase, for paired az and el values."""
    az, el = np.radians(az_deg), np.radians(el_deg)
    u = np.stack([np.sin(az) * np.cos(el), np.sin(el)])   # direction cosines, sideways and up
    return np.exp(-1j * (K * positions @ u + calibration[:, None])).astype(np.complex64)

def direction_power(profiles, positions, calibration, az_deg, el_deg):
    """Frame-averaged power over every range, elevation, and azimuth, shaped (range, el, az)."""
    AZ, EL = np.meshgrid(az_deg, el_deg)
    steer = steering_3d(positions, calibration, AZ.ravel(), EL.ravel())
    power = np.zeros((profiles.shape[1], steer.shape[1]), dtype=np.float32)
    for frame in profiles:   # one frame at a time keeps memory small
        power += np.abs(frame @ steer) ** 2
    power /= len(profiles) * steer.shape[0] ** 2   # same scale as the 2D range_angle
    return power.reshape(profiles.shape[1], len(el_deg), len(az_deg))