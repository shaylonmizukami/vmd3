# Galil Rail Continuous SAR Runbook

Continuous-motion SAR sweeps with the VMD3 on the Galil rail, 2D mode, RADC only. Collection runs on the lab's Windows laptop with `galil/galil_sweep.ipynb`. Conversion and processing run on the Linux laptop from `~/Projects/vmd3/vmd3-dog`. Images are formed on the ground plane.

## Before the first run

- [ ] `lib/sar.py`, `load_sweep`: default track file is `f"{stem}_track.csv"`
- [ ] `sar/simulate_sweep.py`, `main`: writes `f"{stem}_track.csv"`
- [ ] `sar/sar_image.py`: `--track` and `--bgTrack` help text say `_track.csv`
- [ ] `lib/sar.py` and `sar/sar_image.py`: ground-plane edits in, `--height` option available
- [ ] `sar/sar_image.py`: plot file name includes `_slant` or `_ground`
- [ ] `sar/galil_convert.py` exists

## Setup

- Target at about 0.6 to 0.8 m slant range from the radar, centered on the sweep center
- Radar and target fixed, nothing moving in the scene
- Measure with the stage at sweep center:
  - **Slant range:** straight-line distance from the radar's antenna center to the target's center
  - **Height:** vertical distance from the radar's antenna center down to the target's center
- Height must be less than slant range. Ground range is then `sqrt(slant² − height²)`

## Windows: collection

### Session start

1. Close GDK
2. Run the imports cell
3. Run **1a** only if the radar was plugged in or power cycled
4. Run **1b** with:

```python
RADAR_MODE = 0
RADAR_STREAMS = ["radc"]
```

Expected: `[radar] Ready. Mode 0, streams ['radc']`, then a frame period near 130 ms.

5. Run **2** to connect and home the stage

Expected: `[stage] Homed. Position 0 counts = start of scan.`

### Sweeps

In **Section 3**, set `SESSION_FOLDER` once, then change only `FILE_NAME` for each sweep:

```python
SWEEP_LENGTH_MM = 100.0
N_FRAMES = 101
```

| `FILE_NAME` | Scene |
|---|---|
| `bg` | Target removed |
| `center` | Target at sweep center |
| `offset` | Target moved about 3 cm toward the radar's right, measured |

Expected per sweep:

- Frame spacing about 1.0 mm, under λ/4 = 1.23 mm
- About 101 RADC frames, center position +50 to −50 mm
- No dropped-frame warning. If one appears, re-run that sweep

### Session end

Run **Section 4**.

## Transfer

Copy the whole session folder, `data/<SESSION_FOLDER>/` including `bins/` and `scan_log.csv`, to the Linux laptop at:

```
~/Projects/vmd3/vmd3-dog/galil/data/<SESSION_FOLDER>/
```

## Linux: convert

```
cd ~/Projects/vmd3/vmd3-dog
python3 -m sar.galil_convert galil/data/<SESSION_FOLDER>/bins/bg.bin
python3 -m sar.galil_convert galil/data/<SESSION_FOLDER>/bins/center.bin
python3 -m sar.galil_convert galil/data/<SESSION_FOLDER>/bins/offset.bin
```

Expected per sweep:

```
101 RADC frames, RSET 0 (2D), x +5.0 to -5.0 cm
Missed frames: not recorded
Saved data/<date>/galil-<name>_*
```

## Linux: SAR images

```
python3 -m sar.sar_image data/<date>/galil-center --targetRange <slant m> --height <height m> --background data/<date>/galil-bg --calibrate --show
python3 -m sar.sar_image data/<date>/galil-offset --targetRange <slant m> --height <height m> --background data/<date>/galil-bg --calibrate --show
```

Expected:

- Background match per RX near 1
- `galil-center`: peak x near 0, offset by a few mm at most from position read lag, ground range near `sqrt(slant² − height²)`
- `galil-offset`: peak x near +3 cm, same ground range
- Cross-range and ground range widths close to the printed ideal. Ground range width is larger than slant range width by slant over ground range
- Phase sign check: +1 near 1 for every RX, −1 clearly lower

Images save to `data/<date>/plots/` as `galil-<name>_sar_ground_bgsub.png`. Leaving out `--height` gives the slant-plane image instead, saved as `_sar_slant_bgsub.png`.

## If something is off

| Symptom | Fix |
|---|---|
| `galil-offset` peak at −3 cm instead of +3 cm | Stage's right is the radar's left. Delete the converted `galil-*` files and rerun all three conversions with `--flipX` |
| Ground range far from expected but slant image looks right | Recheck the height measurement, from antenna center to target center |
| `--height must be less than --targetRange` | Height or slant range swapped or mismeasured |
| 1b hangs after "Connected to UDP" | Power cycle the radar, wait about 10 s, run 1a and 1b again |
| Converter says rows and records don't match | `.bin` and `_positions.csv` are from different sweeps or one was cut short. Re-run the sweep |
| Converter says frames don't match RSET | `scan_log.csv` missing or wrong. Pass `--rset 0` |
| Converter says the stem already exists | Delete the old `galil-<name>_*` files or pass `--out` |
| Peak far from the expected range | Check `--targetRange` against the tape, and that the background sweep is the same scene without the target |

## Field log

| Sweep | Target | Slant range (m) | Height (m) | Sideways offset (m) | Notes |
|---|---|---|---|---|---|
| `bg` | none | | | | |
| `center` | | | | 0 | |
| `offset` | | | | | |
