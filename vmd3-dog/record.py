"""Record VMD3 radar outputs to disk, one .bin per output type."""

import argparse
import csv
import json
import socket
import time
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path

from config import DATA_DIR, RADC_HEADER, RFFT_HEADER, DONE_HEADER, HEADER_SIZE, HST
from lib.vmd3 import VMD3, VMD3_SETTING, RdotConfig

# Outputs the user can pick, with their radar setting and frame tag
OUTPUTS = {
    "radc": (RdotConfig.RADC, RADC_HEADER),
    "rfft": (RdotConfig.RFFT, RFFT_HEADER),
}

def capture_stem(started, filePath=None, fileName=None):
    """Return the shared path stem for all files of a capture."""
    directory = Path(filePath) if filePath else DATA_DIR / started.strftime("%Y-%m-%d")
    name = fileName if fileName else started.strftime("%H-%M-%S")
    return directory / name

def save_frame(parts, files, log, frame, elapsed, counter, mark, counts, sizes):
    """Write one frame's outputs to their files and add its row to the log."""
    for name, raw in parts.items():
        files[name].write(raw)
        counts[name] += 1
        sizes[name] = len(raw)
    present = [int(name in parts) for name in files]
    log.writerow([frame, f"{time.time():.3f}", f"{elapsed:.3f}", counter, mark] + present)

def write_metadata(json_path, rset, outputs, started, ended, frames, counts, sizes, missed, marks):
    """Save capture settings and stats next to the data files."""
    meta = {
        "rset": rset,
        "vmd3_setting": VMD3_SETTING[rset],
        "outputs": outputs,
        "start_time": started.isoformat(timespec="seconds"),
        "end_time": ended.isoformat(timespec="seconds"),
        "duration_s": round((ended - started).total_seconds(), 3),
        "frame_count": frames,
        "output_counts": counts,
        "frame_sizes": sizes,
        "frames_missed_estimate": missed,
        "marks": marks,
    }
    with open(json_path, "w") as f:
        json.dump(meta, f, indent=2)

def read_marks(marks):
    """Queue a label each time Enter is pressed, blank lines become lap numbers."""
    lap = 0
    for line in sys.stdin:
        lap += 1
        marks.put(line.strip() or f"lap{lap}")

def main(rset, outputs, duration, filePath, fileName):
    started = datetime.now(HST)
    stem = capture_stem(started, filePath, fileName)
    stem.parent.mkdir(parents=True, exist_ok=True)

    # Refuse to overwrite an earlier capture
    names = [f"{stem}.json", f"{stem}_frames.csv"] + [f"{stem}_{o}.bin" for o in OUTPUTS]
    if any(Path(n).exists() for n in names):
        raise SystemExit(f"{stem.name} already exists in {stem.parent}, pick another --fileName")

    # Radar setup, DONE is always requested to mark end of each frame
    vmd3 = VMD3()
    vmd3.connect()
    vmd3.set_rset_config(rset)
    vmd3.set_output_config([OUTPUTS[o][0] for o in outputs] + [RdotConfig.DONE])
    vmd3.sockUDP.settimeout(2)   # give up if the radar goes quiet
    vmd3.sockTCP.settimeout(2)

    # One .bin per output plus the frame log
    files = {o: open(f"{stem}_{o}.bin", "wb") for o in outputs}
    log_file = open(f"{stem}_frames.csv", "w", newline="")
    log = csv.writer(log_file)
    log.writerow(["frame", "time_unix", "elapsed_s", "radar_counter", "mark"] + outputs)

    # Lookups & counters
    tag_to_name = {OUTPUTS[o][1]: o for o in outputs}
    tags = tuple(tag_to_name) + (DONE_HEADER,)
    counts = {o: 0 for o in outputs}
    sizes = {o: 0 for o in outputs}
    parts = {}
    frames = 0
    missed = 0
    last_counter = None
    last_frame = 0
    start = time.monotonic()
    previous = start
    
    # Enter (optionally with a label) marks the current frame
    marks = queue.Queue()
    threading.Thread(target=read_marks, args=(marks,), daemon=True).start()
    mark_list = []

    print(f"Recording {', '.join(outputs)} to {stem}_*")
    print("Press Enter to mark a frame, or type a label then Enter")
    try:
        while True:
            # collect outputs until something closes the frame
            raw = vmd3.read_any_frame(tags)
            tag = raw[:4]
            if tag != DONE_HEADER and tag_to_name[tag] not in parts:
                parts[tag_to_name[tag]] = raw
                continue
            if not parts:
                continue   # DONE with nothing before it, started mid-frame

            # DONE closes the frame, a repeated tag means DONE was lost
            now = time.monotonic()
            counter = int.from_bytes(raw[HEADER_SIZE:], "little") if tag == DONE_HEADER else ""
            saved = "+".join(parts)

            # Attach any marks typed since the last frame
            mark = "|".join(marks.get_nowait() for _ in range(marks.qsize()))
            if mark:
                mark_list.append({"frame": frames, "elapsed_s": round(now - start, 3), "label": mark})
                print(f">>> {mark} at {now - start:.1f} s (log frame {frames})")

            save_frame(parts, files, log, frames, now - start, counter, mark, counts, sizes)
            parts = {} if tag == DONE_HEADER else {tag_to_name[tag]: raw}

            # Count gaps from the radar's own frame counter
            dt = now - previous
            previous = now
            if counter != "":
                if last_counter is not None:
                    missed += max(0, (counter - last_counter) - (frames - last_frame))
                last_counter, last_frame = counter, frames
            frames += 1

            # Status line
            print(f"Frame {frames} | {dt * 1000:.1f} ms | Missed {missed} | {now - start:.1f} s | {saved} | Counter {counter}")

            if duration and now - start >= duration:
                break

    except KeyboardInterrupt:
        print("\nStopped by user")
    except socket.timeout:
        print("\nNo data from radar for 2s, stopping")
    finally:
        # Disconnect even if the radar is unreachable
        try:
            vmd3.disconnect()
        except OSError:
            print("Radar did not respond to disconnect")

        # Close files, keep the capture only if something was recorded
        for f in files.values():
            f.close()
        log_file.close()
        if frames:
            write_metadata(f"{stem}.json", rset, outputs, started, datetime.now(HST), frames, counts, sizes, missed, mark_list)
            print(f"Saved {frames} frames to {stem}_*")
        else:
            for o in outputs:
                Path(f"{stem}_{o}.bin").unlink(missing_ok=True)
            Path(f"{stem}_frames.csv").unlink(missing_ok=True)
            print("No frames captured, nothing saved")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record VMD3 radar outputs")
    parser.add_argument("--rset", type=int, default=0, choices=range(9), help="RSET config 0-8 (0 = 2D 6m, 1 = 2D 10m)")
    parser.add_argument("--outputs", nargs="+", default=["radc"], choices=list(OUTPUTS), help="Outputs to save: radc, rfft, or both. Default: radc")
    parser.add_argument("--duration", type=float, default=None, help="Stop after this many seconds")
    parser.add_argument("--filePath", type=str, default=None, help="Output folder. Default: data/YYYY-MM-DD/")
    parser.add_argument("--fileName", type=str, default=None, help="File name stem. Default: HH-MM-SS")
    args = parser.parse_args()

    outputs = list(dict.fromkeys(args.outputs))   # drop repeats, keep order
    main(args.rset, outputs, args.duration, args.filePath, args.fileName)