"""Settings for VMD3 3D mode, 3 TX and 4 RX making 12 virtual channels."""

from pathlib import Path

# Radar setting for 3D at 6 m max range
RSET_3D = 6

# Channel layout, the radar sends TX1 RX1-4, then TX2 RX1-4, then TX3 RX1-4
N_TX = 3
N_RX = 4
N_CHANNELS = N_TX * N_RX
TX_OF_CHANNEL = [k // N_RX for k in range(N_CHANNELS)]   # 0,0,0,0,1,1,1,1,2,2,2,2
RX_OF_CHANNEL = [k % N_RX for k in range(N_CHANNELS)]

# Elevation grid, wider than the 36 deg beam to see where returns fade
ELEVATION_LIMIT_DEG = 45
ELEVATION_STEP_DEG = 1.0

# Transmitter layout and per-channel calibration, written later by channels.py
GEOMETRY_FILE = Path(__file__).resolve().parent / "geometry.json"

# Antenna -3 dB beam half widths from the datasheet, 60 by 36 deg
BEAM_AZ_DEG = 30
BEAM_EL_DEG = 18