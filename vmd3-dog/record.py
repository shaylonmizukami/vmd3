"""Record raw VMD3 RADC frames to disk."""

import argparse
import json
import socket
import time
from datetime import datetime
from pathlib import Path

from config import DATA_DIR, FRAME_PERIOD_S, HST, RADC_HEADER
from lib.vmd3 import VMD3, VMD3_SETTING, RdotConfig

def capture_paths(started, filePath=None, fileName=None):
    """Return (bin_path, json_path) for a capture."""
    directory = Path(filePath) if filePath else DATA_DIR / started.strftime("%Y-%m-%d")
    stem = fileName if fileName else started.strftime("%H-%M-%S")
    return directory / f"{stem}.bin", directory / f"{stem}.json"

def write_metadata(json_path, rset, started, ended, frames, frame_size, missed):
    """Save capture settings and stats next to the .bin."""
    meta = {
        "rset": rset,
        "vmd3_setting": VMD3_SETTING[rset],
        "start_time": started.isoformat(timespec="seconds"),
        "end_time": ended.isoformat(timespec="seconds"),
        "duration_s": round((ended - started).total_seconds(), 3),
        "frame_count": frames,
        "frame_size": frame_size,
        "frames_missed_estimate": missed,
    }
    with open(json_path, "w") as f:
        json.dump(meta, f, indent=2)

def main(rset, duration, filePath, fileName):
    started = datetime.now(HST)
    bin_path, json_path = capture_paths(started, filePath, fileName)
    bin_path.parent.mkdir(parents=True, exist_ok=True)

    # Radar setup
    vmd3 = VMD3()
    vmd3.connect()
    vmd3.set_rset_config(rset)
    vmd3.set_output_config([RdotConfig.RADC])
    vmd3.sockUDP.settimeout(2)   # give up if the radar goes quiet
    vmd3.sockTCP.settimeout(2)

    # Counters
    frames = 0
    missed = 0
    frame_size = 0
    start = time.monotonic()
    previous = start

    print(f"Recording to {bin_path}")
    try:
        with open(bin_path, "wb") as f:
            while True:
                # Read one frame and time it
                raw = vmd3.read_frame(RADC_HEADER)
                now = time.monotonic()
                dt = now - previous
                previous = now

                # Save and count gaps
                f.write(raw)
                frame_size = len(raw)
                if frames > 0:
                    missed += max(0, round(dt / FRAME_PERIOD_S) - 1)
                frames += 1

                # Status line
                print(f"Frame {frames} | {dt * 1000:.1f} ms | Missed {missed} | {now - start:.1f} s")

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

        # Keep the capture only if something was recorded
        if frames:
            write_metadata(json_path, rset, started, datetime.now(HST), frames, frame_size, missed)
            print(f"Saved {frames} frames to {bin_path}")
        else:
            bin_path.unlink(missing_ok=True)
            print("No frames captured, nothing saved")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record raw VMD3 RADC frames")
    parser.add_argument("--rset", type=int, default=0, choices=range(9), help="RSET config 0-8 (0 = 2D 6m, 1 = 2D 10m)")
    parser.add_argument("--duration", type=float, default=None, help="Stop after this many seconds")
    parser.add_argument("--filePath", type=str, default=None, help="Output folder. Default: data/YYYY-MM-DD/")
    parser.add_argument("--fileName", type=str, default=None, help="File name stem. Default: HH-MM-SS")
    args = parser.parse_args()

    main(args.rset, args.duration, args.filePath, args.fileName)