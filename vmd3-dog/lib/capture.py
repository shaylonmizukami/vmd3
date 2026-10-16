"""Load VMD3 captures from disk and decode them into data cubes."""

import csv
import json
from datetime import datetime
from pathlib import Path
import numpy as np

from config import HEADER_SIZE, RADC_HEADER, RFFT_HEADER

TAGS = {"radc": RADC_HEADER, "rfft": RFFT_HEADER}

def read_log(stem):
    """Return the frame log as a dict of numpy arrays."""
    with open(f"{stem}_frames.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    log = {
        "frame": np.array([int(r["frame"]) for r in rows]),
        "time_unix": np.array([float(r["time_unix"]) for r in rows]),
        "elapsed_s": np.array([float(r["elapsed_s"]) for r in rows]),
        "radar_counter": np.array([int(r["radar_counter"] or -1) for r in rows]),
        "mark": np.array([r.get("mark", "") for r in rows]),
    }
    for name in TAGS:
        if name in rows[0]:
            log[name] = np.array([r[name] == "1" for r in rows])
    return log

def to_stem(path):
    """Accept any file of a capture, or its stem, and return the stem."""
    path = Path(path)
    for suffix in [".json", "_frames.csv"] + [f"_{o}.bin" for o in TAGS]:
        if path.name.endswith(suffix):
            return path.with_name(path.name[:-len(suffix)])
    return path

def load(stem, output="radc"):
    """Return (payloads, log, meta) for one output of a capture."""
    stem = Path(stem)
    with open(f"{stem}.json") as f:
        meta = json.load(f)
    if output not in meta["outputs"]:
        raise ValueError(f"{stem.name} has no {output}, is has {meta['outputs']}")

    # Keep only the log rows where this output arrived
    log = read_log(stem)
    keep = log[output]
    log = {key: value[keep] for key, value in log.items()}

    # Split the file into equal sized frames
    frame_size = meta["frame_sizes"][output]
    raw = np.fromfile(f"{stem}_{output}.bin", dtype=np.uint8)
    n_frames = raw.size // frame_size
    frames = raw[:n_frames * frame_size].reshape(n_frames, frame_size)

    # Every frame must carry the right tag and match the log
    tag = np.frombuffer(TAGS[output], dtype=np.uint8)
    if not np.all(frames[:, :4] == tag):
        raise ValueError(f"{stem.name}_{output}.bin: frames are misaligned or corrupted")
    if n_frames != len(log["frame"]):
        raise ValueError(f"{stem.name}: log lists {len(log['frame'])} {output} frames, file has {n_frames}")

    return frames[:, HEADER_SIZE:], log, meta

def decode_radc(payloads, meta):
    """Return a complex cube shaped (frames, samples, chirps, channels)."""
    setting = meta["vmd3_setting"]
    samples = setting["num_samples"]
    chirps = setting["num_chirps"]
    channels = 4 if setting["angle_setting"] == "2D" else 12

    # Chirp major, then channel, then sample, stored Q first then I
    data = np.ascontiguousarray(payloads).view("<i2")
    data = data.reshape(len(payloads), chirps, channels, samples, 2)
    iq = data[..., 1].astype(np.float32) + 1j * data[..., 0].astype(np.float32)

    return iq.transpose(0, 3, 1, 2)

def decode_rfft(payloads, meta):
    """Return a complex cube shaped (frames, range_bins, chirps, channels)."""
    setting = meta["vmd3_setting"]
    if setting["angle_setting"] != "2D":
        raise NotImplementedError("RFFT decoding is only written for 2D captures")
    bins = setting["num_samples"]
    chirps = setting["num_chirps"]
    channels = 4

    # Channel major, then range bin, then chirp, stored Q first then I
    data = np.ascontiguousarray(payloads).view("<i2")
    data = data.reshape(len(payloads), channels, bins, chirps, 2)
    iq = data[..., 1].astype(np.float32) + 1j * data[..., 0].astype(np.float32)

    return iq.transpose(0, 2, 3, 1)

def time_window(log, start=None, end=None):
    """Return a slice of frames from start to end, in seconds into the capture."""
    t = log["elapsed_s"]
    first = 0 if start is None else np.searchsorted(t, start)
    last = len(t) if end is None else np.searchsorted(t, end, side="right")
    return slice(first, last)

def load_window(stem, start=None, end=None, output="radc"):
    """Return (payloads, log, meta) trimmed to start through end seconds into the capture."""
    payloads, log, meta = load(stem, output)
    window = time_window(log, start, end)
    log = {key: value[window] for key, value in log.items()}
    payloads = payloads[window]
    if len(payloads) == 0:
        raise SystemExit(f"No frames in {to_stem(stem).name} between {start} and {end} s")
    return payloads, log, meta

def clock_to_seconds(clock, log, meta):
    """Convert a field notes time like '16:22:30' to seconds into the capture."""
    started = datetime.fromisoformat(meta["start_time"])
    t = datetime.strptime(clock, "%H:%M:%S").time()
    target = datetime.combine(started.date(), t, tzinfo=started.tzinfo).timestamp()
    capture_start = log["time_unix"][0] - log["elapsed_s"][0]
    return target - capture_start