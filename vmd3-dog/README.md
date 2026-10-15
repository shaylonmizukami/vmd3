# vmd3-dog

VMD3 61 GHz FMCW radar mounted on a robot dog. Records raw radar frames on the dog's onboard computer, pulls them to a laptop, and processes them into range-angle heatmaps. First step toward SAR from the dog.

---

## Layout

```
vmd3-dog/
├── README.md         start here
├── .gitignore
├── config.py         shared settings, edit values here
├── initradar.sh      radar network setup        (Pi / Jetson)
├── record.py         record radar frames        (Pi / Jetson)
├── heatmap.py        averaged range-angle plot  (laptop)
├── replay.py         frame-by-frame replay      (laptop)
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
- **`docs/`:** step-by-step references
- A function lives in the script that uses it until a second script needs it, then it moves to `lib/`

---

## What Runs Where

| Machine | Runs | Needs |
|---|---|---|
| Pi 5 / Jetson | `initradar.sh`, `record.py` | `python3` 3.10+, no pip installs |
| Laptop | `heatmap.py`, `replay.py` | venv with numpy and matplotlib |

Keep `record.py`, `config.py`, and `lib/vmd3.py` compatible with Python 3.10.

---

## Workflow

1. Connect the laptop to the Pi or Jetson WiFi and SSH in
2. Sync the clock from the laptop
3. Push code with rsync
4. `sudo ./initradar.sh` on the Pi or Jetson
5. `python3 record.py --fileName <name>` inside tmux
6. Pull `data/` back with rsync
7. `python replay.py` to look through it, `python heatmap.py` for the averaged plot

Exact commands are in the docs below.

---

## Docs

| Doc | Open when |
|---|---|
| `pi-ssh-setup.md` | SSH, keys, tmux, rsync, renaming the Pi |
| `radar-network-setup.md` | Radar link, `initradar.sh`, Jetson interface names |
| `pi-clock-setup.md` | Clock sync and the RTC battery |
| `record-capture.md` | Recording, output files, missed frames, `record.py` source |
| `pi-rehearsal.md` | Full dog sequence rehearsed on the Pi |
| `dog-field-runbook.md` | The day with the dog |
| `processing.md` | Heatmap, replay, angle convention, library reference |

---

## Conventions

- Positive angle = target on the right, radar right side up (`ANGLE_SIGN = -1`)
- Captures are named by their stem, `data/<date>/<name>`. Names never overwrite
- Frame times come from the frame log, not from assuming 130 ms
- Missed frames come from the radar's DONE counter
- Plots go in `data/<date>/plots/`
- Code comments: one short comment per group of lines, one-line docstrings
