# vmd3-dog

VMD3 61 GHz FMCW radar mounted on a robot dog. Records raw radar frames on the dog's onboard Jetson, pulls them to a laptop, and processes them into range-angle maps, background subtracted maps, and phase stability measurements. First steps toward SAR from the dog.

---

## Layout

```
vmd3-dog/
├── README.md         start here
├── .gitignore
├── config.py         shared settings, edit values here
├── initradar.sh      radar network setup        (Pi / Jetson)
├── record.py         record radar frames        (Pi / Jetson)
├── replay.py         frame by frame replay      (laptop)
├── heatmap.py        averaged range-angle map   (laptop)
├── bgsub.py          background subtraction     (laptop)
├── stability.py      phase stability            (laptop)
├── lib/
│   ├── __init__.py
│   ├── vmd3.py       talking to the radar
│   ├── capture.py    files to arrays
│   ├── dsp.py        signal processing
│   └── plots.py      shared figure setup
├── docs/             how-to references
└── data/             captures, never committed
    └── YYYY-MM-DD/
        ├── <name>.json
        ├── <name>_frames.csv
        ├── <name>_radc.bin
        ├── <name>_rfft.bin
        └── plots/
```

### Where things go

- **Top level:** things you run
- **`lib/`:** things you import, one file per job (hardware, files, signal processing, plots)
- **`config.py`:** every shared number. Never import numpy here, `record.py` loads it on the Jetson
- **`docs/`:** step by step references
- A function lives in the script that uses it until a second script needs it, then it moves to `lib/`

---

## What Runs Where

| Machine | Runs | Needs |
|---|---|---|
| Pi 5 / Jetson | `initradar.sh`, `record.py` | `python3` 3.10+, no pip installs |
| Laptop | `replay.py`, `heatmap.py`, `bgsub.py`, `stability.py` | venv with numpy and matplotlib |

The Jetson only needs `config.py`, `initradar.sh`, `record.py`, `lib/__init__.py`, and `lib/vmd3.py`. Keep those compatible with Python 3.10.

---

## Workflow

1. Connect the laptop to the dog's network and SSH into the Jetson
2. Sync the clock from the laptop
3. Push the five recording files with rsync
4. Free the radar's address on `eth1` and run `sudo ./initradar.sh eth1`
5. `python3 record.py --fileName <name>` inside tmux, marking segments with Enter
6. Pull `data/` back with rsync
7. `replay.py` to check the capture and find segment times
8. `heatmap.py`, `bgsub.py`, `stability.py` for results

Exact commands are in the docs below.

---

## Docs

| Doc | Open when |
|---|---|
| `pi-ssh-setup.md` | SSH, keys, tmux, rsync, renaming the Pi |
| `radar-network-setup.md` | Radar link, `initradar.sh`, interface names |
| `pi-clock-setup.md` | Clock sync and the RTC battery |
| `record-capture.md` | Recording, output files, marks, missed frames, `record.py` source |
| `pi-rehearsal.md` | Full dog sequence rehearsed on the Pi |
| `dog-field-runbook.md` | The day with the dog, Jetson specifics, recovery |
| `processing.md` | All laptop scripts, how to read results, 2026-10-15 results |

---

## Conventions

- Positive angle = target on the right, radar right side up (`ANGLE_SIGN = -1`)
- Captures are named by their stem, `data/<date>/<name>`. Names never overwrite
- Frame times come from the frame log, not from assuming 130 ms
- Missed frames come from the radar's DONE counter
- Marks (Enter during recording) label frames in the log and `.json`
- Plots go in `data/<date>/plots/`
- Code comments: one short comment per group of lines, one-line docstrings, side comments three spaces after the code
