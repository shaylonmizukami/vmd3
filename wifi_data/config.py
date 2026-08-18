"""
Shared constants and helpers for wireless data capture
"""

from datetime import datetime
from pathlib import Path

# --- Paths ---
""" BASE_DIR is wifi_data/ """
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "radc"


# --- Network ---
FLIGHT_IP = "192.168.50.1"  # Pi5 address set as default. Can change with --ip arg
# Beryl7 IP & PW: 192.168.100.1 | WirelessRadar
# FLIGHT_IP = "192.168.100.1"
TCP_PORT = 39123


# --- Protocol ---
RADC_HEADER = b"RADC"
HEADER_SIZE = 8  # 4-byte RDOT tag + 4-byte payload little-endian length
FRAME_PERIOD_S = 0.13  # 130 ms for every RSET config
FRAME_PERIOD_MS = FRAME_PERIOD_S * 1000


# --- Capture layout ---
METADATA_SUFFIX = ".json"
DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H-%M-%S"


def default_capture_dir(started: datetime) -> Path:
    """data/radc/<YYYY-MM-DD>/ runtime start date"""
    return DATA_DIR / started.strftime(DATE_FMT)


def default_capture_name(started: datetime) -> str:
    """<HH-MM-SS> runtime start time"""
    return started.strftime(TIME_FMT)


def resolve_capture_paths(started: datetime, filePath=None, fileName=None):
    """Fill in unset --filePath & --fileName, return (bin_path, json_path)"""
    directory = Path(filePath) if filePath else default_capture_dir(started)
    name = fileName if fileName else default_capture_name(started)
    return directory / f"{name}.bin", directory / f"{name}{METADATA_SUFFIX}"
