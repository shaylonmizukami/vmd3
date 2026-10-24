"""Shared setting for VMD3 capture and processing."""

from datetime import timedelta, timezone
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PLOTS_SUBDIR = "plots"   # plots go in data/<date>/plots/

# Radar protocol
RADC_HEADER = b"RADC"
RFFT_HEADER = b"RFFT"
DONE_HEADER = b"DONE"
HEADER_SIZE = 8   # 4 byte tage + 4 byte payload length
FRAME_PERIOD_S = 0.13   # same for every RSET config

# Radar hardware
CARRIER_HZ = 61e9
WAVELENGTH_M = 299_792_458 / CARRIER_HZ   # about 4.914 mm
RX_SPACING_M = 2.464e-3
ANGLE_SIGN = -1   # -1 puts a target on the right at a positive angle, radar right side up

# Range-angle heatmap
ANGLE_LIMIT_DEG = 70
ANGLE_STEP_DEG = 0.5
LEAKAGE_CUTOFF_M = 0.3   # ignore the coupling blob right in front of the radar
FLOOR_DB = -25   # lowest dB shown on maps

# SAR
RANGE_FFT_SIZE = 1024   # zero padded, a giner grid for interpolation, not more resolution
PHASE_SIGN = +1   # measured on the rail data
APERTURE_WINDOW = "hamming"
SAR_CROSS_RANGE_M = 0.10   # image spans +/- this sideways
SAR_CROSS_STEP_M = 0.001
SAR_DOWNRANGE_HALF_M = 0.15   # image spans target range +/- this
SAR_DOWNRANGE_STEP_M = 0.002

# Time
HST = timezone(timedelta(hours=-10), "HST")   # Hawaii has no DST
