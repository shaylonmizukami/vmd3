"""Continuous-motion SAR sweep recording, logging, and .bin file export."""

import os
import csv
import time
import socket
from datetime import datetime
import numpy as np
import pandas as pd
from .radar_link import STREAM_HEADERS

# Constants
WAVELENGTH_MM = 299_792_458 / 61.0e9 * 1e3
LOG_HEADER = ["file", "start", "stop", "duration_s", "n_frames",
              "radar_mode", "streams", "sweep_mm", "speed_mm_s"]
POSITION_HEADER = ["record", "stream", "stream_frame", "t_s", "galil_counts",
                   "x_mm", "x_center_mm", "moving"]


# Sweep planning
def _sweep_speed(frame_period, sweep_counts, n_frames):
    """Stage speed in counts/s that spreads n_frames frames over the sweep."""
    return int(round(sweep_counts / ((n_frames - 1) * frame_period)))


def print_sweep_plan(frame_period, sweep_length_mm, n_frames, counts_per_mm):
    """Print the frame rate, sweep speed, and frame spacing for a planned sweep."""
    sweep_counts = int(round(sweep_length_mm * counts_per_mm))
    speed = _sweep_speed(frame_period, sweep_counts, n_frames)
    spacing = sweep_length_mm / (n_frames - 1)
    print(f"[sweep] Frame period  : {frame_period * 1e3:.1f} ms ({1 / frame_period:.2f} Hz)")
    print(f"[sweep] Sweep speed   : {speed} counts/s ({speed / counts_per_mm:.2f} mm/s)")
    print(f"[sweep] Sweep time    : {sweep_counts / speed:.1f} s for {n_frames} frames")
    print(f"[sweep] Frame spacing : {spacing:.3f} mm (λ/4 = {WAVELENGTH_MM / 4:.3f} mm)")
    if spacing > WAVELENGTH_MM / 4:
        min_frames = int(np.ceil(sweep_length_mm / (WAVELENGTH_MM / 4))) + 1
        print(f"[sweep] Warning: spacing exceeds λ/4. Use n_frames ≥ {min_frames} to avoid grating lobes.")


# Output files
def _next_file_path(bin_dir, file_name):
    """Path for file_name in bin_dir, adding _2, _3... instead of overwriting."""
    path = os.path.join(bin_dir, f"{file_name}.bin")
    i = 2
    while os.path.exists(path):
        path = os.path.join(bin_dir, f"{file_name}_{i}.bin")
        i += 1
    return path


def _ensure_session_files(bin_dir, log_path):
    """Create the session folders and the session log with its header if missing."""
    os.makedirs(bin_dir, exist_ok=True)
    if not os.path.exists(log_path):
        with open(log_path, "w", newline="") as f:
            csv.writer(f).writerow(LOG_HEADER)


def _save_positions(path, rows):
    """Write the per-record position log for one sweep."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(POSITION_HEADER)
        writer.writerows(rows)


def _append_log(log_path, name, start, stop, n_frames, radar_mode, streams, sweep_length_mm, speed_mm_s):
    """Add one summary row for a sweep to the session log."""
    with open(log_path, "a", newline="") as f:
        csv.writer(f).writerow([
            name, start.isoformat(timespec="seconds"), stop.isoformat(timespec="seconds"),
            f"{(stop - start).total_seconds():.2f}", n_frames, radar_mode,
            "+".join(streams), f"{sweep_length_mm:g}", f"{speed_mm_s:.3f}",
        ])


def _print_summary(bin_path, pos_path, rows, first_stream, n_frames, sweep_length_mm, duration_s):
    """Print the frame count, aperture span, and any dropped-frame gaps."""
    xc = np.array([float(r[6]) for r in rows if r[1] == first_stream])
    gaps = np.abs(np.diff(xc))
    mean_spacing = gaps.mean() if gaps.size else float("nan")
    print(f"[sweep] Saved {os.path.basename(bin_path)}: {len(rows)} records, "
          f"{os.path.getsize(bin_path) / 1e6:.2f} MB, {duration_s:.1f} s")
    print(f"[sweep] {len(xc)} {first_stream.upper()} frames (target {n_frames}), center position "
          f"{xc[0]:+.2f} to {xc[-1]:+.2f} mm, mean spacing {mean_spacing:.3f} mm")
    big = np.where(gaps > 1.5 * sweep_length_mm / (n_frames - 1))[0]
    if big.size:
        print(f"[sweep] Warning: {big.size} dropped frame gap(s), largest {gaps.max():.2f} mm "
              f"near center {xc[big[0]]:+.2f} mm. Consider re-running this sweep.")
    print(f"[sweep] Positions → {os.path.basename(pos_path)}")


# Recording
def record_sweep(radar, stage, data_dir, session_folder, file_name,
                 sweep_length_mm, n_frames, accel, frame_period=None):
    """Run one sweep, record every frame while the stage moves, save the results, and return the .bin path."""
    frame_period = frame_period or radar.frame_period
    if frame_period is None:
        raise RuntimeError("No frame period. Run radar.measure_frame_period() or pass frame_period.")
    if n_frames < 2:
        raise ValueError("n_frames must be at least 2")
    sweep_counts = int(round(sweep_length_mm * stage.counts_per_mm))
    speed = _sweep_speed(frame_period, sweep_counts, n_frames)
    timeout_s = sweep_counts / speed + 10
    half_mm = sweep_length_mm / 2
    print_sweep_plan(frame_period, sweep_length_mm, n_frames, stage.counts_per_mm)

    # Output files
    session_dir = os.path.join(data_dir, session_folder)
    bin_dir = os.path.join(session_dir, "bins")
    log_path = os.path.join(session_dir, "scan_log.csv")
    _ensure_session_files(bin_dir, log_path)
    bin_path = _next_file_path(bin_dir, file_name)
    pos_path = bin_path[:-4] + "_positions.csv"

    # Stream bookkeeping
    streams = radar.cycle_streams()
    accepted = tuple(STREAM_HEADERS[s] for s in streams)
    header_to_stream = {STREAM_HEADERS[s]: s for s in streams}
    sync = streams[-1]
    counts = {s: 0 for s in streams}
    rows = []

    # Park at the start and load the sweep move without starting it
    print("[sweep] Moving to start...")
    stage.go_to_start()
    stage.prepare_move(-stage.home_direction * sweep_counts, speed, accel)

    # Start the move right after a radar cycle ends
    radar.drain()
    radar.wait_for_frame(STREAM_HEADERS[sync])
    stage.begin()
    t0 = time.perf_counter()
    start = datetime.now()
    print(f"[sweep] {sweep_length_mm:g} mm at {speed / stage.counts_per_mm:.2f} mm/s, "
          f"target {n_frames} frames → {os.path.basename(bin_path)}")

    # Record until the stage stops and the current cycle is complete
    with open(bin_path, "wb") as out:
        try:
            while True:
                if time.perf_counter() - t0 > timeout_s:
                    raise TimeoutError("Sweep took too long. Check the radar stream and the stage.")
                try:
                    frame = radar.read_frame(accepted)
                except socket.timeout:
                    continue
                t = time.perf_counter() - t0
                pos, moving = stage.state()
                stream = header_to_stream[frame[:4]]
                x_mm = stage.distance_mm(pos)

                out.write(frame)
                rows.append([len(rows), stream, counts[stream], f"{t:.4f}", pos,
                             f"{x_mm:.4f}", f"{half_mm - x_mm:.4f}", int(moving)])
                counts[stream] += 1

                if stream == sync:
                    print(f"   cycle {counts[stream]:3d}   x = {x_mm:7.2f} mm   "
                          f"center {half_mm - x_mm:+7.2f} mm   {'moving' if moving else 'stopped'}")
                    if not moving:
                        break
        except BaseException:
            stage.stop()
            raise
    stop = datetime.now()

    # Save logs and report
    _save_positions(pos_path, rows)
    _append_log(log_path, os.path.basename(bin_path), start, stop, counts[sync], radar.mode,
                streams, sweep_length_mm, speed / stage.counts_per_mm)
    _print_summary(bin_path, pos_path, rows, streams[0], n_frames, sweep_length_mm,
                   (stop - start).total_seconds())
    return bin_path


# Reading and export
def read_records(bin_path):
    """Yield (stream, payload) for each record in a .bin file, in file order."""
    names = {v: k for k, v in STREAM_HEADERS.items()}
    with open(bin_path, "rb") as f:
        while header := f.read(8):
            length = int.from_bytes(header[4:8], "little")
            yield names.get(header[:4], "unknown"), f.read(length)


def decode_radc(payload):
    """Decode a 2D RADC payload to (sample, chirp, rx) complex samples."""
    raw = np.frombuffer(payload, dtype="<i2").reshape(64, 4, 256)
    iq = raw[:, :, 1::2] + 1j * raw[:, :, 0::2]
    return np.transpose(iq, (2, 0, 1))


def decode_rfft(payload):
    """Decode a 2D RFFT payload to (range_bin, chirp, rx) complex samples."""
    raw = np.frombuffer(payload, dtype="<i2").reshape(4, 128, 64, 2)
    iq = raw[..., 1] + 1j * raw[..., 0]
    return np.transpose(iq, (1, 2, 0))


def export_long_csv(bin_path, streams=("radc",)):
    """Write one row per (frame, bin, chirp, channel) I/Q value to a CSV next to the .bin."""
    decoders = {"radc": decode_radc, "rfft": decode_rfft}
    counts = {s: 0 for s in streams}
    parts = []
    for stream, payload in read_records(bin_path):
        if stream not in streams or stream not in decoders:
            continue
        cube = decoders[stream](payload)
        b, c, h = np.meshgrid(*map(np.arange, cube.shape), indexing="ij")
        parts.append(pd.DataFrame({
            "stream": stream, "frame": counts[stream], "bin": b.ravel(), "chirp": c.ravel(),
            "channel": h.ravel(), "I": cube.real.ravel(), "Q": cube.imag.ravel(),
        }))
        counts[stream] += 1
    if not parts:
        print(f"[export] No {list(streams)} frames found in {os.path.basename(bin_path)}")
        return None
    out_path = os.path.splitext(bin_path)[0] + "_long.csv"
    df = pd.concat(parts, ignore_index=True)
    df.to_csv(out_path, index=False)
    print(f"[export] Wrote {os.path.basename(out_path)}: {len(df):,} rows {counts}")
    return out_path