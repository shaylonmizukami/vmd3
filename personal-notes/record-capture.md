# Recording Captures

`[Laptop]` = Konsole on the laptop (`shaylon@x1carbon`)
`[Pi]` = SSH'd into the Pi (`pipi5@pipi5`)

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
sudo ~/vmd3-dog/initradar.sh
python3 ~/vmd3-dog/record.py --duration 60
```

Pull data `[Laptop]`
```
rsync -av pipi5:~/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/
```

### record.py arguments

| Argument | Default | Use |
|---|---|---|
| `--rset` | `0` | RSET 0-8 (0 = 2D 6 m, 1 = 2D 10 m) |
| `--duration` | none | Stop after N seconds |
| `--filePath` | `data/YYYY-MM-DD/` | Output folder |
| `--fileName` | `HH-MM-SS` | File name stem |

No `--duration` = runs until `Ctrl-c`.

---

## 1. Layout

```
vmd3-dog/
├── initradar.sh
├── config.py
├── record.py
├── .gitignore
├── lib/
│   ├── __init__.py
│   └── vmd3.py
└── data/
    └── YYYY-MM-DD/
        ├── HH-MM-SS.bin
        └── HH-MM-SS.json
```

- `config.py`: constants shared by more than one script
- `lib/vmd3.py`: radar driver
- Everything else stays in the script that uses it until a second script needs it

`.gitignore`
```
data/
__pycache__/
```

---

## 2. Output Files

One `.bin` and one `.json` per capture, same name.

- `.bin`: raw RADC frames back to back, 131,080 bytes each (8 byte header + 131,072 payload, 2D)
- `.json`: written once at the end of the capture from values held in memory

`.json` fields: `rset`, `vmd3_setting`, `start_time`, `end_time`, `duration_s`, `frame_count`, `frame_size`, `frames_missed_estimate`

Check a capture `[Pi]`
```
ls -l ~/vmd3-dog/data/*/
cat ~/vmd3-dog/data/<date>/<time>.json
```

Size check: `.bin` bytes = `frame_count` × `frame_size`

Delete a day `[Pi]`
```
rm -r ~/vmd3-dog/data/<date>
```

---

## 3. How a Run Ends

| Cause | Output | Saved? |
|---|---|---|
| `--duration` reached | `[VMD3] Disconnected` | Yes |
| `Ctrl-c` | `Stopped by user` | Yes |
| Radar silent 2 s | `No data from radar for 2 s, stopping` | Yes, up to that point |
| Zero frames | `No frames captured, nothing saved` | No, empty `.bin` deleted |

After an unplug, also expect `Radar did not respond to disconnect`. Rerun `initradar.sh` after replugging.

---

## 4. Expected Output

```
Recording to /home/pipi5/vmd3-dog/data/2026-10-11/16-22-18.bin
Frame 1 | 61.9 ms | Missed 0 | 0.1 s
Frame 2 | 737.0 ms | Missed 5 | 0.8 s
Frame 3 | 130.2 ms | Missed 5 | 0.9 s
...
```

Steady state: 128 to 131 ms per frame, `Missed` stops climbing.

---

## 5. Known Quirks

### Frame 2 gap

Every run has a ~725 ms gap at frame 2, counting as `Missed 5`. Radar startup after `RDOT`, not data loss. Steady after that. Drop the first ~1 s of every capture in processing.

### Clock

Pi has no internet on its own network, so its clock drifts or goes stale. Wrong date = wrong folder and file names. Sync from the laptop every session.

Permanent fix (needs internet, e.g. phone hotspot) `[Pi]`
```
sudo apt install util-linux-extra
sudo hwclock -w
sudo hwclock -r
```

Jetson: check `date` before recording, same sync command with `jetson`.

---

## 6. Common Errors

| Output | Fix |
|---|---|
| `[VMD3] Error while connecting with TCP/IP socket` | Run `initradar.sh` first, check radar power |
| `[VMD3] Error while connecting with UDP socket` | Another `record.py` already running, close it |
| `ModuleNotFoundError: No module named 'numpy'` | numpy import still at top of `vmd3.py`, see section 7 |
| `ModuleNotFoundError: No module named 'config'` | Run `record.py` from its own path, keep it next to `config.py` |
| `invalid choice` on `--rset` | Must be 0 to 8 |
| `sudo: hwclock: command not found` | Not installed, sync from laptop instead |
| Folder date is wrong | Clock not synced |

---

## 7. vmd3.py Edit

numpy only needed for decoding, not recording. Moved so `record.py` runs on plain `python3` with no installs.

- Delete `import numpy as np` from the top
- Add `import numpy as np` as the first line inside `decode_radc_2d`
- Add `import numpy as np` as the first line inside `decode_radc_3d`

---

## 8. Source

`config.py`
```python
"""Shared settings for VMD3 capture and processing."""

from datetime import timedelta, timezone
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Radar protocol
RADC_HEADER = b"RADC"
FRAME_PERIOD_S = 0.13   # same for every RSET config

# Time
HST = timezone(timedelta(hours=-10), "HST")   # Hawaii has no DST
```

`record.py`
```python
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
        print("\nNo data from radar for 2 s, stopping")
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
    parser.add_argument("--rset", type=int, default=0, choices=range(9), help="RSET config 0-8 (0 = 2D 6 m, 1 = 2D 10 m)")
    parser.add_argument("--duration", type=float, default=None, help="Stop after this many seconds")
    parser.add_argument("--filePath", type=str, default=None, help="Output folder. Default: data/YYYY-MM-DD/")
    parser.add_argument("--fileName", type=str, default=None, help="File name stem. Default: HH-MM-SS")
    args = parser.parse_args()

    main(args.rset, args.duration, args.filePath, args.fileName)
```
