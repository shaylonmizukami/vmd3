# VMD3 3D Mode Test Runbook

Sections 4, 6, 7, and 8. Run everything from `~/Projects/vmd3/vmd3-dog`. Capture names use `2026-11-08`, adjust to the actual date.

## Session start

```
cd ~/Projects/vmd3/vmd3-dog
sudo ./recording/initradar.sh enp0s13f0u1u2c2
```

Expected: all `[ok]` lines, ending with `Radar responding at 192.168.100.201`.

If no frames arrive after a reboot:

```
sudo firewall-cmd --zone=trusted --change-interface=enp0s13f0u1u2c2
```

## Section 4: channel layout

### Captures

Sphere at about 0.5 m. Log the measured right, up, and forward offsets from the radar's center to the sphere's center. Right is the radar's right when standing behind it, up is toward the radar's top.

```
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-ref
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-side
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-up
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-diag
```

| Capture | Right | Up | Forward |
|---|---|---|---|
| `3d-ref` | 0 | 0 | 0.5 m |
| `3d-side` | about 0.13 m | 0 | 0.5 m |
| `3d-up` | 0 | about 0.09 m | 0.5 m |
| `3d-diag` | about 0.13 m | about 0.09 m | 0.5 m |

### Solve

Use the measured values, not the targets in the table.

```
python3 -m radar3d.channels \
  --capture data/2026-11-08/3d-ref 0 0 0.5 \
  --capture data/2026-11-08/3d-side 0.13 0 0.5 \
  --capture data/2026-11-08/3d-up 0 0.09 0.5 \
  --capture data/2026-11-08/3d-diag 0.13 0.09 0.5
```

Expected:

- Radar range within a few cm of tape distance for each capture
- `RX spacing per TX` near `+2.46` for all three
- `RX height spread per TX` near 0
- Residuals under about 20°
- TX offsets near round multiples of 0.5 λ

### Save

Only if the above looks right. Same command with `--save` at the end.

Expected: `Saved .../radar3d/geometry.json`

## Section 6: beamforming check

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
for name in ['3d-ref', '3d-side', '3d-up', '3d-diag']:
    p, l, m = load(f'data/2026-11-08/{name}')
    pw = direction_power(zero_doppler_profiles(p, m), pos, cal, az, el)
    r = range_axis(m, pw.shape[0])
    pw[r < LEAKAGE_CUTOFF_M] = 0
    i, j, k = np.unravel_index(pw.argmax(), pw.shape)
    print(f'{name}: {r[i]:.2f} m, az {az[k]:+.1f}, el {el[j]:+.1f}')
"
```

Expected: az and el for each capture match the angles `channels.py` printed, within about 1° to 2°. The diagonal one is the real test.

## Section 7: maps

### Per-TX view

```
python3 -m radar3d.heatmap3d data/2026-11-07/3d-reflector --compare data/2026-11-07/2d-reflector --perTx --maxRange 3 --show
```

Expected: all panels at 1.55 m and about −2°, same as before.

### Full view

```
python3 -m radar3d.heatmap3d data/2026-11-08/3d-ref --maxRange 1 --show
python3 -m radar3d.heatmap3d data/2026-11-08/3d-diag --maxRange 1 --show
```

Expected:

- `3d-ref`: peak near az 0, el 0
- `3d-diag`: peak at the diagonal's tape angles
- One blob on the az-el map, likely taller than wide. Repeated copies stacked in one direction mean ghost peaks from wide transmitter spacing

## Section 8: comparisons

Radar fixed and level, nothing moving, every target at least 0.5 m away.

### Part A: empty scene

```
python3 -m recording.record --duration 10 --fileName 2d-empty
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-empty
python3 -m radar3d.heatmap3d data/2026-11-08/3d-empty --compare data/2026-11-08/2d-empty --maxRange 2 --show
```

Expected: only room clutter, same spots in both modes.

### Part B: diagonal pair

Two targets about 25 cm apart diagonally, for example about 0.6 m forward slightly left and about 0.8 m forward slightly right, both at radar height. For each placement N:

```
python3 -m recording.record --duration 10 --fileName 2d-diag-N
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-diag-N
python3 -m radar3d.heatmap3d data/2026-11-08/3d-diag-N --compare data/2026-11-08/2d-diag-N --maxRange 2 --show
```

Expected: both targets in both modes, same ranges and azimuths.

### Part C: different heights

Two targets at the same sideways position, one at radar height and one raised. Offset their forward distances by about 5 to 10 cm so they land in different range bins.

| Placement | Forward | Upper target raised by |
|---|---|---|
| `h-1` | 0.8 m | about 0.25 m (17°) |
| `h-2` | 0.8 m | about 0.15 m (11°) |
| `h-3` | 0.8 m | about 0.08 m (6°) |

For N = 1, 2, 3:

```
python3 -m recording.record --duration 10 --fileName 2d-h-N
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-h-N
python3 -m radar3d.heatmap3d data/2026-11-08/3d-h-N --compare data/2026-11-08/2d-h-N --maxRange 2 --show
python3 -m radar3d.heatmap3d data/2026-11-08/3d-h-N --sliceRange <upper target range> --maxRange 2 --show
```

Expected: 2D shows no height difference. 3D range-elevation separates them, until the gap drops below the vertical resolution.

### Part D: elevation sweep

One target at 0.8 m forward, centered sideways, raised in steps.

| Capture | Elevation | Height above radar |
|---|---|---|
| `3d-el00` | 0° | 0 |
| `3d-el05` | 5° | 7.0 cm |
| `3d-el10` | 10° | 14.1 cm |
| `3d-el15` | 15° | 21.4 cm |
| `3d-el20` | 20° | 29.1 cm |
| `3d-el25` | 25° | 37.3 cm |
| `3d-el30` | 30° | 46.2 cm |

```
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el00
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el05
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el10
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el15
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el20
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el25
python3 -m recording.record --rset 6 --duration 10 --fileName 3d-el30
```

```
for e in 00 05 10 15 20 25 30; do echo "el $e"; python3 -m radar3d.heatmap3d data/2026-11-08/3d-el$e --maxRange 1.5; done
```

Expected: measured elevation tracks the true one, peak level dropping by about 3 dB near 18°.

## Field log

| Capture | Target | Right (m) | Up (m) | Forward (m) | Notes |
|---|---|---|---|---|---|
| | | | | | |