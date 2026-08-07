"""
config.py — VMD3 radar configuration and experiment geometry.

Single source of truth for RSET settings, frame constants, and the
two-target scene geometry. No logic here, just constants that the
decode, range-profile, and displacement code import.
"""

import math

# --- Frame / decode constants (2D RADC mode) ---
RADC_2D_FRAME_LEN = 131072   # bytes, payload length for a 2D RADC frame
N_SAMPLES  = 128             # fast-time samples per chirp
N_CHIRPS   = 64              # chirps per frame (2D mode)
N_CHANNELS = 4               # RX channels (2D mode, azimuth)

HEADER_RADC = b'RADC'

# --- RSET table ---
# Only the 2D settings are listed; this experiment uses RSET 1.
RSET_TABLE = {
    0: {"max_range": 6,   "range_res_cm": 4.69,  "n_chirps": 64, "mode": "2D"},
    1: {"max_range": 10,  "range_res_cm": 7.82,  "n_chirps": 64, "mode": "2D"},
    2: {"max_range": 30,  "range_res_cm": 23.43, "n_chirps": 64, "mode": "2D"},
    3: {"max_range": 30,  "range_res_cm": 23.43, "n_chirps": 64, "mode": "2D"},
    4: {"max_range": 50,  "range_res_cm": 39.12, "n_chirps": 64, "mode": "2D"},
    5: {"max_range": 100, "range_res_cm": 78.18, "n_chirps": 64, "mode": "2D"},
}

# --- RSET to use ---
ACTIVE_RSET = 1

# --- Slow-time (frame-rate) parameters ---
FRAME_PERIOD_S = 0.13            # s, frame repetition time
FS_SLOW = 1.0 / FRAME_PERIOD_S   # ~7.7 Hz, slow-time sample rate

# --- RF / wavelength (RSET 1 center frequency) ---
F_CENTER_HZ = 61.06e9
C = 3e8
LAMBDA_M = C / F_CENTER_HZ  # ~4.91 mm

# Hard ceiling on phase unwrapping: the slow-time phase must move less than
# pi between frames. Collapses to (peak-to-peak mm) * (motion Hz) < this.
UNWRAP_LIMIT_MM_HZ = LAMBDA_M * FS_SLOW / (4.0 * math.pi) * 1000.0   # ~3.0

# --- Convenience derived from the active RSET ---
MAX_RANGE_M = RSET_TABLE[ACTIVE_RSET]["max_range"]
RANGE_RES_M = RSET_TABLE[ACTIVE_RSET]["range_res_cm"] / 100.0

# --- Processing defaults ---
RANGE_WINDOW = 'hann'   # applied along fast-time before the range FFT
SLOW_WINDOW  = 'hann'   # applied to slow-time signals before their FFT

# Scene geometry (radar at origin, boresight target on +y axis).
# Kept here for reference / expected-bin sanity checks in process.py.
TARGET1_RANGE_M = 6.0            # boresight target, (0, 6)
TARGET2_ANGLE_DEG = 30           # off-boresight angle (leaning 15)
# Target 2 sits at (R*tan(theta), R); its radial range is R/cos(theta).
TARGET2_RANGE_M = TARGET1_RANGE_M / math.cos(math.radians(TARGET2_ANGLE_DEG))

# --- Expected motion (for margin checks and result sanity) ---
TARGET1_DISP_MM = 5.0
TARGET1_FREQ_HZ = 0.17
TARGET2_DISP_MM = 8.0
TARGET2_FREQ_HZ = 0.25
