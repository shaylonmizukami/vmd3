# Robot Arm SAR Runbook

2D mode, RADC only. Record on the arm computer, process on the laptop from `~/Projects/vmd3/vmd3-dog`.

## Measure once, before any sweep

- Point **C**: floor point straight in front of the sweep center, where the radar aims
- Tape line through C, parallel to the sweep
- Positions are (x, g) in cm from C. x is + toward the radar's right, g is + away from the radar
- With the arm at sweep center and the sphere at C:
  - **S**: slant range, radar antenna center to the sphere's near surface
  - **H**: height, radar antenna center straight down to the sphere's center
- Pipes lie flat with the long axis pointing at the radar
- Positions are center to center. If two targets don't fit that close, use the closest spacing that fits and log it

## Arm settings

| Setup | Sweep | Speed | Hold at each end |
|---|---|---|---|
| A, 10 cm | ±5 cm | 6 mm/s | ≥ 5 s |
| B, 20 cm | ±10 cm | 6 mm/s | ≥ 5 s |
| C, 30 cm | ±15 cm | 6 mm/s | ≥ 5 s |

## Recording, arm computer

Session start:

```
cd <vmd3-dog>
sudo recording/initradar.sh <interface>
```

Each sweep:

1. Arm to sweep start, holding
2. `python3 -m recording.record --filePath data/2026-11-27/arm --fileName <name>`
3. Wait 5 s, start the sweep
4. End hold 5 s, then Ctrl+C
5. Arm to rest
6. Rename the arm log to `<name>_arm.csv`, move it into `data/2026-11-27/arm/`
7. Retake if `Missed` went above 0

Session end: copy `data/2026-11-27/arm/` to the Google Drive folder.

## Setup A: 10 cm

| `<name>` | Targets (x, g) |
|---|---|
| `a10-bg` | none |
| `a10-sphere-c` | sphere (0, 0) |
| `a10-sphere-r5` | sphere (+5, 0) |
| `a10-spipe-c` | small pipe (0, 0) |
| `a10-bpipe-c` | big pipe (0, 0) |
| `a10-two-10` | sphere (−5, 0), small pipe (+5, 0) |
| `a10-two-5` | sphere (−2.5, 0), small pipe (+2.5, 0) |
| `a10-diag` | sphere (−2.5, −5), small pipe (+2.5, +5) |
| `a10-bg2` | none, optional |

## Setup B: 20 cm

| `<name>` | Targets (x, g) |
|---|---|
| `a20-bg` | none |
| `a20-sphere-c` | sphere (0, 0) |
| `a20-two-5` | sphere (−2.5, 0), small pipe (+2.5, 0) |
| `a20-two-3` | sphere (−1.5, 0), small pipe (+1.5, 0) |
| `a20-diag` | sphere (−1.5, −5), small pipe (+1.5, +5) |

## Setup C: 30 cm

| `<name>` | Targets (x, g) |
|---|---|
| `a30-bg` | none |
| `a30-sphere-c` | sphere (0, 0) |
| `a30-two-3` | sphere (−1.5, 0), small pipe (+1.5, 0) |
| `a30-two-2` | sphere (−1, 0), small pipe (+1, 0) |
| `a30-diag` | sphere (−1, −5), small pipe (+1, +5) |

## Processing, laptop

Save the Drive folder to:

```
~/Projects/vmd3/vmd3-dog/data/2026-11-27/arm/
```

Convert every sweep:

```
cd ~/Projects/vmd3/vmd3-dog
for f in data/2026-11-27/arm/*_arm.csv; do python3 -m sar.arm_convert "$f" "${f%_arm.csv}"; done
```

Check each: `inside the arm log` near the total, `during the sweep` about 130 / 260 / 385 for A / B / C, no `[!]` on spacing.

Range offset from the sphere at C, note the printed `Range offset` as OFF:

```
python3 -m sar.sar_image data/2026-11-27/arm/a10-sphere-c --targetRange S --height H --background data/2026-11-27/arm/a10-bg --calibrate --show
```

Every other sweep, with the background of its own setup (`a10-bg`, `a20-bg` or `a30-bg`):

```
python3 -m sar.sar_image data/2026-11-27/arm/<name> --targetRange S --height H --background data/2026-11-27/arm/<setup>-bg --rangeOffset OFF --show
```

Images: `data/2026-11-27/arm/plots/<name>_sar_ground_bgsub.png`

## Fixes

| Symptom | Fix |
|---|---|
| `a10-sphere-r5` peak at −5 cm | Reconvert all with `--flipX --force` |
| Sphere +1 phase sign well under 0.9 | Reconvert all with `--wristOffset 0.06 0.03 --force`, keep if sharper |
| `inside the arm log` is 0 | Add `--autoClock` to `sar_image` |
| Spacing `[!]` | Slow to 5 mm/s |
| Background match well under 0.99 | Try `a10-bg2`, or drop `--background` |
| Pipe doesn't show in a two-target sweep | Turn it broadside, long axis along the tape line, widen the gap |

## Field log

| `<name>` | Original arm log | S (m) | H (m) | Actual positions | Notes |
|---|---|---|---|---|---|
| | | | | | |
