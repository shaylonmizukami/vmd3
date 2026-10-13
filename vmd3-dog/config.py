"""Shared setting for VMD3 capture and processing."""

from datetime import timedelta, timezone
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Radar protocol
RADC_HEADER = b"RADC"
RFFT_HEADER = b"RFFT"
DONE_HEADER = b"DONE"
HEADER_SIZE = 8   # 4 byte tage + 4 byte payload length
FRAME_PERIOD_S = 0.13   # same for every RSET config

# Time
HST = timezone(timedelta(hours=-10), "HST")   # Hawaii has no DST
