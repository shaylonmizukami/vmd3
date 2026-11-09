# VMD3 3D Mode Test Runbook

Linux laptop wired directly to the radar, radar level and looking toward the horizon, sphere at 1 m. Run everything from `~/Projects/vmd3/vmd3-dog`. Capture names use `2026-11-08`, adjust to the actual date.

## Status

### Done

| Capture | Right (m) | Up (m) | Forward (m) | Notes |
|---|---|---|---|---|
| `3d-bg` | sphere removed | | | stand left at the `3d-ref` spot |
| `3d-ref` | 0 | 0 | 1.00 | |
| `3d-side` | 0.27 | 0 | 1.00 | |
| `3d-up` | 0 | 0.18 | 1.00 | |
| `3d-diag` | 0.27 | 0.18 | 1.00 | |
| `3d-side5` | 0.105 | 0 | 1.00 | aimed for 0.09, placed about 0.10 to 0.11 |
| `3d-up20` | 0 | 0.36 | 1.00 | **excluded**, radar range 17 cm too long, likely locked onto something else |

### Layout so far

- **Horizontal, settled:** TX2 about +4.3 to +4.9 mm from TX1, TX3 about +8.9 to +9.9 mm. Matches the IWR6843 layout (+4.93 and +9.86)
- **Vertical, inconclusive:** best fit puts TX2 near 0, but the IWR6843 value of −2.46 mm fits nearly as well. Needs captures at larger elevation, which Part D provides
- **Not saved yet:** no `geometry.json`

### What depends on the vertical layout

| Task | Needs it? |
|---|---|
| 2D SAR and 3D SAR on the rail | No |
| Section 8 Parts A and B with `--perTx` | No |
| Sections 6 and 7 full maps, Section 8 Parts C and D processing | Yes |

## Session start

```
cd ~/Projects/vmd3/vmd3-dog
sudo ./recording/initradar.sh enp0s13f0u1u2c2
```

Expected: all `[ok]` lines, ending with `Radar responding at 192.168.100.201`.

`Radar did not respond to disconnect` at the end of a capture is harmless. Frames are only saved whole.

## Setup reminders

- Radar must not move between captures that go into the same `channels.py` run
- Right is the radar's right from behind it, up is straight toward the ceiling, forward is along its boresight
- Sphere on a firm non-metal support, measured from the radar's antenna center to the sphere's center
- Wall at least 1 m behind the sphere, surfaces between radar and sphere kept out of the beam or covered with absorber

## Step 1: Part D elevation sweep

Sphere at 1.00 m forward, centered sideways, raised straight up in steps. Hold it firmly so it doesn't drift back as it goes up. Log the measured heights.

| Capture | Elevation | Height above radar |
|---|---|---|
| `3d-el05` | 5° | 8.7 cm |
| `3d-el10` | 10° | 17.6 cm |
| `3d-el15` | 15° | 26.8 cm |
| `3d-el20` | 20° | 36.4 cm |
| `3d-el25` | 25° | 46.6 cm |
| `3d-el30` | 30° | 57.7 cm |

```
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el05
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el10
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el15
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el20
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el25
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el30
```

## Step 2: layout with Part D included

Replace the Part D heights with measured values:

```
python3 -m radar3d.channels --background data/2026-11-08/3d-bg \
  --capture data/2026-11-08/3d-ref 0 0 1.00 \
  --capture data/2026-11-08/3d-side 0.27 0 1.00 \
  --capture data/2026-11-08/3d-up 0 0.18 1.00 \
  --capture data/2026-11-08/3d-diag 0.27 0.18 1.00 \
  --capture data/2026-11-08/3d-side5 0.105 0 1.00 \
  --capture data/2026-11-08/3d-el05 0 0.087 1.00 \
  --capture data/2026-11-08/3d-el10 0 0.176 1.00 \
  --capture data/2026-11-08/3d-el15 0 0.268 1.00 \
  --capture data/2026-11-08/3d-el20 0 0.364 1.00 \
  --capture data/2026-11-08/3d-el25 0 0.466 1.00 \
  --capture data/2026-11-08/3d-el30 0 0.577 1.00
```

Check before trusting the fit:

- Each capture's radar range about 7.5 cm more than its tape distance, within about 3 cm. Drop any capture far outside that and rerun
- Target/clutter well above 0 dB. Drop the top steps if they fall near 0 dB, since they're outside the beam's −3 dB edge

Expected:

- TX2 and TX3 horizontal offsets as before
- TX2 vertical clearly near either 0 or ±2.46 mm, with fit 1 well ahead of fit 2
- Channel residuals mostly under 15°, focusing above about 0.95 for every capture

Send the output for review before saving.

## Step 3: save

Same command with `--save` at the end. Add `--snap` only if every fitted offset is close to a whole number of 2.46 mm steps, since snapping rounds to the nearest step.

Expected: `Saved .../radar3d/geometry.json`

## Step 4: beamforming check

```
python3 -c "
import numpy as np
from config import LEAKAGE_CUTOFF_M
from lib.capture import load
from lib.dsp import range_axis, zero_doppler_profiles
from radar3d.mimo import direction_power, load_geometry
pos, cal = load_geometry()
az = np.arange(-70, 70.5, 0.5)
el = np.arange(-45, 45.5, 0.5)
for name in ['3d-ref', '3d-side', '3d-up', '3d-diag', '3d-side5', '3d-el05', '3d-el10', '3d-el15', '3d-el20', '3d-el25', '3d-el30']:
    p, l, m = load(f'data/2026-11-08/{name}')
    pw = direction_power(zero_doppler_profiles(p, m), pos, cal, az, el)
    r = range_axis(m, pw.shape[0])
    pw[r < LEAKAGE_CUTOFF_M] = 0
    i, j, k = np.unravel_index(pw.argmax(), pw.shape)
    print(f'{name}: {r[i]:.2f} m, az {az[k]:+.1f}, el {el[j]:+.1f}')
"
```

Expected: az and el match each capture's tape angles within a few degrees, with el climbing through the Part D steps. If el stays near 0 for every step, the 3D mode has no vertical aperture.

## Step 5: full maps

```
python3 -m radar3d.heatmap3d data/2026-11-08/3d-ref --maxRange 1.6 --show
python3 -m radar3d.heatmap3d data/2026-11-08/3d-diag --maxRange 1.6 --show
for e in 05 10 15 20 25 30; do echo "el $e"; python3 -m radar3d.heatmap3d data/2026-11-08/3d-el$e --maxRange 2; done
```

Expected:

- `3d-ref`: peak near az 0, el 0, range about 1.07 m
- Part D: measured elevation tracks the true one, peak level dropping about 3 dB near 18°
- One blob on the az-el map, likely taller than wide. Repeated copies in one direction mean ghost peaks

## Step 6: Section 8 comparisons

Same level setup, nothing moving, targets around 1 m away. Capture all of these now. The layout is a property of the radar, so it applies to these later.

### Part A: empty scene

```
python3 -m recording.record --duration 10 --fileName 2d-empty
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-empty
```

Process now:

```
python3 -m radar3d.heatmap3d data/2026-11-08/3d-empty --compare data/2026-11-08/2d-empty --perTx --maxRange 2.5 --show
```

Expected: only room clutter, same spots in both modes.

### Part B: diagonal pair

Two targets about 25 cm apart diagonally, for example one at about 1.00 m forward and 0.09 m left, the other at about 1.18 m forward and 0.09 m right, both at radar height. For each placement N:

```
python3 -m recording.record --duration 10 --fileName 2d-diag-N
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-diag-N
```

Process now:

```
python3 -m radar3d.heatmap3d data/2026-11-08/3d-diag-N --compare data/2026-11-08/2d-diag-N --perTx --maxRange 2.5 --show
```

Expected: both targets in both modes, same ranges and azimuths.

### Part C: different heights

Two targets at the same sideways position, one at radar height and one raised. Offset their forward distances by about 5 to 10 cm so they land in different range bins.

| Placement | Forward | Upper target raised by |
|---|---|---|
| `h-1` | 1.0 m | about 0.31 m (17°) |
| `h-2` | 1.0 m | about 0.19 m (11°) |
| `h-3` | 1.0 m | about 0.11 m (6°) |

For N = 1, 2, 3:

```
python3 -m recording.record --duration 10 --fileName 2d-h-N
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-h-N
```

Process after `geometry.json` exists:

```
python3 -m radar3d.heatmap3d data/2026-11-08/3d-h-N --compare data/2026-11-08/2d-h-N --maxRange 2.5 --show
python3 -m radar3d.heatmap3d data/2026-11-08/3d-h-N --sliceRange <upper target range + 0.075> --maxRange 2.5 --show
```

For `--sliceRange`, add the 7.5 cm range offset to the tape range, since the maps show the radar's raw range.

Expected: 2D shows no height difference. 3D range-elevation separates them, until the gap drops below the vertical resolution.

## Field log

| Capture | Target | Right (m) | Up (m) | Forward (m) | Notes |
|---|---|---|---|---|---|
| `3d-el05` | PEC sphere | 0 | | 1.00 | |
| `3d-el10` | PEC sphere | 0 | | 1.00 | |
| `3d-el15` | PEC sphere | 0 | | 1.00 | |
| `3d-el20` | PEC sphere | 0 | | 1.00 | |
| `3d-el25` | PEC sphere | 0 | | 1.00 | |
| `3d-el30` | PEC sphere | 0 | | 1.00 | |
| | | | | | |