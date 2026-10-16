# Recording Captures

`[Laptop]` = Konsole on the laptop (`shaylon@x1carbon`)
`[Pi]` = SSH'd into the Pi (`pipi5@pipi5`)
`[Jetson]` = SSH'd into the Jetson (`unitree@ubuntu`)

---

## Quick Reference

### Every session

Sync the clock `[Laptop]`
```
ssh -t pipi5 "sudo date -s @$(date +%s)"
```

Push code `[Laptop]`
```
rsync -av --filter=':- .gitignore' ~/Projects/vmd3/vmd3-dog/ pipi5:~/vmd3-dog/
```

Init radar and record `[Pi]`
```
cd ~/vmd3-dog
sudo ./initradar.sh
tmux new -s radar
python3 record.py --fileName <name>
```

Pull data `[Laptop]`
```
rsync -av pipi5:~/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/
```

On the Jetson, see `dog-field-runbook.md` for the paths and the `eth1` steps.

### record.py arguments

| Argument | Default | Use |
|---|---|---|
| `--rset` | `0` | RSET 0-8 (0 = 2D 6 m, 1 = 2D 10 m) |
| `--outputs` | `radc` | `radc`, `rfft`, or both, e.g. `--outputs radc rfft` |
| `--duration` | none | Stop after N seconds |
| `--filePath` | `data/YYYY-MM-DD/` | Output folder |
| `--fileName` | `HH-MM-SS` | File name stem |

- No `--duration` = runs until `Ctrl-c`
- DONE is always requested behind the scenes, never typed

### While recording

| Key | Does |
|---|---|
| `Enter` | Mark the current frame as `lap1`, `lap2`, ... |
| `stand` then `Enter` | Mark the current frame as `stand` |
| `Ctrl-c` | Stop and save |
| `Ctrl-b` then `d` | Detach tmux, recording continues |

---

## 1. Layout

```
vmd3-dog/
├── config.py
├── initradar.sh
├── record.py
├── lib/
│   ├── __init__.py
│   └── vmd3.py
└── data/
    └── YYYY-MM-DD/
        ├── <name>.json
        ├── <name>_frames.csv
        ├── <name>_radc.bin
        └── <name>_rfft.bin
```

`record.py` only needs `config.py` and `lib/vmd3.py`. No numpy, no pip installs. Runs on Python 3.10 or newer. `data/` and the date folder are created automatically.

`.gitignore`
```
data/
__pycache__/
```

---

## 2. Output Files

One set per capture, all sharing the same stem.

| File | Contents |
|---|---|
| `<name>.json` | Settings, stats, and marks, written once at the end |
| `<name>_frames.csv` | One row per frame |
| `<name>_radc.bin` | Raw RADC frames back to back, 131,080 bytes each (2D) |
| `<name>_rfft.bin` | Raw RFFT frames, only if recorded, 131,080 bytes each (2D) |

Marks never go in the `.bin` files. Those stay pure radar frames.

### Frame log columns

| Column | Meaning |
|---|---|
| `frame` | Frame number, starts at 0, matches array index in processing |
| `time_unix` | Clock time of the frame, seconds since 1970 (for GPS later) |
| `elapsed_s` | Seconds since recording started |
| `radar_counter` | Radar's own frame number from DONE, blank if DONE was lost |
| `mark` | Label typed for this frame, usually blank |
| `radc`, `rfft` | 1 if that output arrived for this frame, 0 if not |

### .json fields

`rset`, `vmd3_setting`, `outputs`, `start_time`, `end_time`, `duration_s`, `frame_count`, `output_counts`, `frame_sizes`, `frames_missed_estimate`, `marks`

Each entry in `marks` has `frame`, `elapsed_s`, and `label`.

### Checks

```
ls -l data/<date>/<name>*
grep -v ',,' data/<date>/<name>_frames.csv | head
cat data/<date>/<name>.json
```

- Size of each `.bin` = `output_counts` × `frame_sizes`
- The `grep` line shows only marked rows
- About 60 MB per minute per output

---

## 3. Marks

- Type while attached to the tmux session, the status line keeps scrolling but input comes through whole
- A mark lands on the next completed frame, within 130 ms
- Several marks in one frame are joined with `|`
- Labels can contain spaces
- Status line `Frame N` = log frame N − 1

Backup when the WiFi drops and you can't type: phone stopwatch started with `record.py`, lap at each event. Lap times are seconds into the capture.

Suggested labels: `stand`, `removed`, `back`, `sit`.

---

## 4. How a Run Ends

| Cause | Output | Saved? |
|---|---|---|
| `--duration` reached | `[VMD3] Disconnected` | Yes |
| `Ctrl-c` | `Stopped by user` | Yes |
| Radar silent 2 s | `No data from radar for 2 s, stopping` | Yes, up to that point |
| Zero frames | `No frames captured, nothing saved` | No, empty files deleted |
| Name already used | `<name> already exists in ...` | Nothing touched, radar never connected |

After an unplug, also expect `Radar did not respond to disconnect`. Rerun `initradar.sh` after replugging.

---

## 5. Expected Output

```
Recording radc to /home/pipi5/vmd3-dog/data/2026-10-14/mark-test_*
Press Enter to mark a frame, or type a label then Enter
Frame 1 | 117.8 ms | Missed 0 | 0.1 s | radc | Counter 1
Frame 2 | 733.3 ms | Missed 0 | 0.9 s | radc | Counter 2
Frame 3 | 130.0 ms | Missed 0 | 1.0 s | radc | Counter 3
...
>>> stand at 3.0 s (log frame 18)
```

- 128 to 131 ms per frame after frame 2
- `Counter` up by exactly 1 each frame
- `Missed` stays 0

---

## 6. Missed Frames

Counted from the radar's frame counter, not timing.

- Counter up by 1: nothing lost, however long the gap
- Counter jumps: `Missed` goes up by the jump minus the frames actually saved

Example of a real drop:
```
Frame 40 | 130.1 ms | Missed 0 | ... | Counter 40
Frame 41 | 390.4 ms | Missed 2 | ... | Counter 43
```

Walking out of WiFi range never causes missed frames. Frames come over the Ethernet cable, WiFi only carries your SSH view.

---

## 7. Known Quirks

### Startup pause

~730 ms gap between frame 1 and frame 2, but the counter goes 1 then 2. The radar pauses after `RDOT`, nothing is lost. Use `elapsed_s` for timing.

### Clock

The recording computer's clock goes stale without internet. Wrong date = wrong folder, names, and `time_unix`. Sync from the laptop every session.

---

## 8. Common Errors

| Output | Fix |
|---|---|
| `<name> already exists in ...` | Pick another `--fileName` |
| `[VMD3] Error while connecting with TCP/IP socket` | Run `initradar.sh` first. On the Jetson, check `.201` isn't local, see the runbook |
| `[VMD3] Error while connecting with UDP socket` | Another `record.py` already running, close it |
| `ModuleNotFoundError: No module named 'numpy'` | numpy import still at top of `vmd3.py`, see section 9 |
| `ModuleNotFoundError: No module named 'config'` | Run from the `vmd3-dog` folder |
| `invalid choice` on `--rset` or `--outputs` | `--rset` 0 to 8, `--outputs` radc or rfft |
| `Missed` climbing | Real drops, check cable and computer load |
| Folder date is wrong | Clock not synced |

---

## 9. vmd3.py Edits

### numpy only where it's used

- Delete `import numpy as np` from the top
- Add `import numpy as np` as the first line inside `decode_radc_2d`
- Add `import numpy as np` as the first line inside `decode_radc_3d`

### read_any_frame

Inside the `VMD3` class, right after `read_frame` and before `send_tcp`:
```python
    def read_any_frame(self, headers):
        """Return the next complete frame whose tag is in headers."""
        while True:
            data = self.recv_udp()
            if data[0:4] not in headers:
                continue

            # Collect packets until the full frame is in
            respLength = int.from_bytes(data[4:8], byteorder='little')
            while len(data) < respLength + 8:
                data += self.recv_udp()

            if len(data) == respLength + 8:   # drop frames that picked up stray packets
                return data
```

Measured order every frame: RADC (131,080), RFFT (131,080), DONE (12).

---

## 10. Source

`config.py`
```python
"""Shared settings for VMD3 capture and processing."""

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
HEADER_SIZE = 8   # 4 byte tag + 4 byte payload length
FRAME_PERIOD_S = 0.13   # same for every RSET config

# Time
HST = timezone(timedelta(hours=-10), "HST")   # Hawaii has no DST

# Radar hardware
CARRIER_HZ = 61e9
WAVELENGTH_M = 299_792_458 / CARRIER_HZ   # about 4.914 mm
RX_SPACING_M = 2.464e-3
ANGLE_SIGN = -1   # -1 puts a target on the right at a positive angle, radar right side up

# Range-angle heatmap
ANGLE_LIMIT_DEG = 70
ANGLE_STEP_DEG = 0.5
LEAKAGE_CUTOFF_M = 0.3   # ignore the coupling blob right in front of the radar
```

`record.py`
```python
"""Record VMD3 radar outputs to disk, one .bin per output type."""

import argparse
import csv
import json
import queue
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from config import DATA_DIR, DONE_HEADER, HEADER_SIZE, HST, RADC_HEADER, RFFT_HEADER
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

    # Radar setup, DONE is always requested to mark the end of each frame
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

    # Lookups and counters
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
            # Collect outputs until something closes the frame
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
        print("\nNo data from radar for 2 s, stopping")
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
    parser.add_argument("--rset", type=int, default=0, choices=range(9), help="RSET config 0-8 (0 = 2D 6 m, 1 = 2D 10 m)")
    parser.add_argument("--outputs", nargs="+", default=["radc"], choices=list(OUTPUTS), help="Outputs to save: radc, rfft, or both. Default: radc")
    parser.add_argument("--duration", type=float, default=None, help="Stop after this many seconds")
    parser.add_argument("--filePath", type=str, default=None, help="Output folder. Default: data/YYYY-MM-DD/")
    parser.add_argument("--fileName", type=str, default=None, help="File name stem. Default: HH-MM-SS")
    args = parser.parse_args()

    outputs = list(dict.fromkeys(args.outputs))   # drop repeats, keep order
    main(args.rset, outputs, args.duration, args.filePath, args.fileName)
```
