"""Continuous and stepped SAR recording, logging, and .bin file export."""

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
STEPPED_LOG_HEADER = ["scan", "start", "stop", "duration_s", "n_positions",
                      "frames_per_position", "step_mm", "sweep_mm", "radar_mode", "streams"]
STEP_POSITION_HEADER = ["position", "file", "target_mm", "galil_counts", "galil_counts_after",
                        "x_mm", "x_center_mm", "n_frames", "time"]


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


def _next_dir(parent, name):
    """Path for a new folder called name in parent, adding _2, _3... instead of overwriting."""
    path = os.path.join(parent, name)
    i = 2
    while os.path.exists(path):
        path = os.path.join(parent, f"{name}_{i}")
        i += 1
    return path


def _ensure_session_files(bin_dir, log_path, header=LOG_HEADER):
    """Create the session folders and a log file with its header if missing."""
    os.makedirs(bin_dir, exist_ok=True)
    if not os.path.exists(log_path):
        with open(log_path, "w", newline="") as f:
            csv.writer(f).writerow(header)


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


# Continuous recording
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


# Stepped planning
def plan_steps(sweep_length_mm, counts_per_mm, frames_per_position, settle_s, step_speed,
               n_positions=None, step_mm=None, frame_period=None):
    """Build the target positions for a stepped scan, print the plan, and return it."""
    if (n_positions is None) == (step_mm is None):
        raise ValueError("Set exactly one of n_positions or step_mm (the other must be None).")
    length_counts = int(round(sweep_length_mm * counts_per_mm))

    # Targets in counts from the start edge
    if n_positions is not None:
        if n_positions < 2:
            raise ValueError("n_positions must be at least 2")
        targets = [int(round(k * length_counts / (n_positions - 1))) for k in range(n_positions)]
    else:
        step_counts = int(round(step_mm * counts_per_mm))
        if step_counts <= 0:
            raise ValueError("step_mm must be positive")
        targets = list(range(0, length_counts + 1, step_counts))
        if targets[-1] < length_counts:
            targets.append(length_counts)   # short last step so the scan still ends at sweep_length_mm

    # Step sizes and the center position
    n = len(targets)
    steps = np.diff(targets)
    main_step = int(np.median(steps))
    odd_steps = [k for k, s in enumerate(steps) if abs(s - main_step) > 1]
    center = [k for k, t in enumerate(targets) if abs(t - length_counts / 2) <= 1]

    print(f"[plan] Positions       : {n} over {sweep_length_mm:g} mm (index 0 to {n - 1})")
    print(f"[plan] Step            : {main_step / counts_per_mm:.4f} mm ({main_step} counts)")
    print(f"[plan] Frames/position : {frames_per_position}, settle {settle_s:g} s")
    if center:
        print(f"[plan] Center          : position {center[0]} sits at x_center = 0")

    # Time estimate
    if frame_period:
        per_position = main_step / step_speed + 0.2 + settle_s + (frames_per_position + 1.5) * frame_period
        print(f"[plan] Estimated time  : {n * per_position / 60:.1f} min, plus the return to the start edge")

    # Warnings
    if odd_steps:
        for k in odd_steps:
            print(f"[plan] Warning: step {k} → {k + 1} is {steps[k] / counts_per_mm:.4f} mm, "
                  f"all others are {main_step / counts_per_mm:.4f} mm.")
        if odd_steps == [n - 2]:
            print(f"[plan] To drop it, use n_positions = {n - 1} with sweep_length_mm = "
                  f"{(n - 2) * main_step / counts_per_mm:g}, or a step that divides {sweep_length_mm:g} mm evenly.")
    elif steps.max() != steps.min():
        print("[plan] Steps differ by at most 1 count (0.125 µm) from rounding, so they are effectively equal.")
    if not center:
        i = int(np.searchsorted(targets, length_counts / 2)) - 1
        left_mm = (length_counts / 2 - targets[i]) / counts_per_mm
        right_mm = (targets[i + 1] - length_counts / 2) / counts_per_mm
        print(f"[plan] Note: no position sits at exactly the center. Positions {i} and {i + 1} straddle it, "
              f"{left_mm:.4f} mm and {right_mm:.4f} mm away. Use an odd number of equal steps to land on it.")
    if steps.max() / counts_per_mm > WAVELENGTH_MM / 4:
        print(f"[plan] Warning: steps exceed λ/4 ({WAVELENGTH_MM / 4:.3f} mm), which causes grating lobes.")

    return {
        "targets": targets, "sweep_length_mm": sweep_length_mm, "counts_per_mm": counts_per_mm,
        "frames_per_position": frames_per_position, "settle_s": settle_s, "step_speed": step_speed,
        "step_mm": main_step / counts_per_mm,
    }


def _append_stepped_log(log_path, scan_name, start, stop, plan, n_positions, radar_mode, streams):
    """Add one summary row for a stepped scan to the stepped session log."""
    with open(log_path, "a", newline="") as f:
        csv.writer(f).writerow([
            scan_name, start.isoformat(timespec="seconds"), stop.isoformat(timespec="seconds"),
            f"{(stop - start).total_seconds():.2f}", n_positions, plan["frames_per_position"],
            f"{plan['step_mm']:.4f}", f"{plan['sweep_length_mm']:g}", radar_mode, "+".join(streams),
        ])


def _print_step_summary(scan_dir, pos_path, xs, half_mm, duration_s):
    """Print the position count, aperture span, step spacing, and the position nearest center."""
    xs = np.array(xs)
    steps = np.diff(xs)
    print(f"[scan] Saved {len(xs)} positions to {os.path.basename(scan_dir)}/ in {duration_s / 60:.1f} min")
    if steps.size:
        print(f"[scan] Aperture {xs[0]:.3f} to {xs[-1]:.3f} mm, steps {steps.min():.4f} to "
              f"{steps.max():.4f} mm (mean {steps.mean():.4f})")
    center = int(np.argmin(np.abs(half_mm - xs)))
    print(f"[scan] Nearest center: position {center} at x_center = {half_mm - xs[center]:+.4f} mm")
    print(f"[scan] Positions → {os.path.basename(pos_path)}")


# Stepped recording
def record_stepped(radar, stage, plan, data_dir, session_folder, scan_name):
    """Run a stepped scan, saving each position's frames to its own .bin, and return the scan folder."""
    if stage.counts_per_mm != plan["counts_per_mm"]:
        raise ValueError("The plan was made with a different counts_per_mm than the stage. Re-run the plan.")
    targets = plan["targets"]
    n_frames = plan["frames_per_position"]
    half_mm = plan["sweep_length_mm"] / 2
    capture_timeout_s = (n_frames + 2) * (radar.frame_period or 0.13) * 3 + 5

    # Output folders and logs
    session_dir = os.path.join(data_dir, session_folder)
    bin_dir = os.path.join(session_dir, "bins")
    log_path = os.path.join(session_dir, "stepped_log.csv")
    _ensure_session_files(bin_dir, log_path, STEPPED_LOG_HEADER)
    scan_dir = _next_dir(bin_dir, scan_name)
    os.makedirs(scan_dir)
    scan_name = os.path.basename(scan_dir)
    pos_path = os.path.join(scan_dir, f"{scan_name}_positions.csv")
    with open(pos_path, "w", newline="") as f:
        csv.writer(f).writerow(STEP_POSITION_HEADER)

    # Stream bookkeeping
    streams = radar.cycle_streams()
    accepted = tuple(STREAM_HEADERS[s] for s in streams)
    header_to_stream = {STREAM_HEADERS[s]: s for s in streams}
    sync = streams[-1]

    print(f"[scan] {len(targets)} positions, {n_frames} frames each → {scan_name}/")
    start = datetime.now()
    xs = []
    try:
        for k, target in enumerate(targets):
            # Move to the position and let it settle
            if k == 0:
                stage.go_to_start()
            else:
                stage.move(-stage.home_direction * target, plan["step_speed"], absolute=True)
            time.sleep(plan["settle_s"])
            pos = stage.state()[0]
            t_pos = datetime.now()

            # Record frames starting at the next radar cycle boundary
            bin_name = f"pos_{k:03d}.bin"
            radar.drain()
            radar.wait_for_frame(STREAM_HEADERS[sync])
            counts = {s: 0 for s in streams}
            t_end = time.perf_counter() + capture_timeout_s
            with open(os.path.join(scan_dir, bin_name), "wb") as out:
                while counts[sync] < n_frames:
                    if time.perf_counter() > t_end:
                        raise TimeoutError(f"Position {k} did not get {n_frames} frames. Check the radar stream.")
                    try:
                        frame = radar.read_frame(accepted)
                    except socket.timeout:
                        continue
                    out.write(frame)
                    counts[header_to_stream[frame[:4]]] += 1
            pos_after = stage.state()[0]

            # Log this position right away so an interrupted scan keeps its log
            x_mm = stage.distance_mm(pos)
            with open(pos_path, "a", newline="") as f:
                csv.writer(f).writerow([
                    k, bin_name, f"{target / stage.counts_per_mm:.4f}", pos, pos_after,
                    f"{x_mm:.4f}", f"{half_mm - x_mm:.4f}", counts[sync], t_pos.isoformat(timespec="seconds"),
                ])
            xs.append(x_mm)
            print(f"   pos {k:3d}/{len(targets) - 1}   x = {x_mm:7.3f} mm   "
                  f"center {half_mm - x_mm:+8.3f} mm   {counts[sync]} frames")
    except BaseException:
        stage.stop()
        partial = os.path.join(scan_dir, f"pos_{len(xs):03d}.bin")
        if os.path.exists(partial):
            os.remove(partial)   # drop the half-recorded position so only complete positions remain
        if xs:
            print(f"[scan] Stopped. Positions 0 to {len(xs) - 1} are saved in {scan_name}/.")
        else:
            print("[scan] Stopped before any position was saved.")
        raise
    stop = datetime.now()

    # Save the scan summary and report
    _append_stepped_log(log_path, scan_name, start, stop, plan, len(xs), radar.mode, streams)
    _print_step_summary(scan_dir, pos_path, xs, half_mm, (stop - start).total_seconds())
    return scan_dir


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