# Processing Captures

All processing runs on the laptop, from `~/Projects/vmd3/vmd3-dog` with the venv active (numpy, matplotlib). No Pi, radar, or network needed.

---

## Quick Reference

Averaged heatmap
```
python heatmap.py data/<date>/<name> --maxRange 3
```

Replay
```
python replay.py data/<date>/<name> --maxRange 3
python replay.py data/<date>/<name> --maxRange 3 --doppler all
```

A capture can be given as its stem or any of its files, e.g. `data/2026-10-14/sign-right-3` or `data/2026-10-14/sign-right-3.json`.

### heatmap.py arguments

| Argument | Default | Use |
|---|---|---|
| `stem` | required | Capture path |
| `--start` / `--end` | whole capture | Window in seconds into the capture |
| `--startClock` / `--endClock` | none | Window as `HH:MM:SS` from field notes, overrides seconds |
| `--floor` | `-40` | Lowest dB shown |
| `--maxRange` | full range | Top of the range axis in m |
| `--show` | off | Open the plot window too |

Saves `data/<date>/plots/<name>_heatmap.png`, rebuilt every run.

### replay.py arguments

| Argument | Default | Use |
|---|---|---|
| `stem` | required | Capture path |
| `--doppler` | `zero` | `zero` = still targets only, `all` = everything |
| `--floor` | `-40` | Lowest dB shown |
| `--maxRange` | full range | Top of the range axis in m |
| `--speed` | `1` | Playback speed, 2 = twice real time |

Controls: Pause/Play button, Frame slider. Pause before dragging the slider.

---

## 1. Pipeline

```
load            payloads (frames, bytes), log, meta
decode_radc     (frames, samples, chirps, channels)
range_fft       (frames, range, chirps, channels)
zero_doppler    (frames, range, channels)
range_angle     (frames, range, angles)
power           |.|², averaged over frames for heatmap.py
```

- Range FFT: Hamming window over the 128 samples
- Zero Doppler: Hann-weighted sum over the 64 chirps, same as the zero Doppler bin
- Angle: steering vector beamforming, −70° to +70° at 0.5°, uniform RX weights
- Frames: power averaged, not complex. Dog sway rotates phase between frames, complex averaging could cancel the target

---

## 2. Choosing a Time Window

- Test runs: `--start 2 --end 60`
- Dog runs: `--startClock` and `--endClock` from the field notes
- Unsure of the times: open `replay.py`, the title shows each frame's clock time

Windows use `elapsed_s` from the frame log, so the startup pause doesn't shift them.

---

## 3. Zero vs All Doppler

| Mode | Shows | Use for |
|---|---|---|
| `zero` | Returns not moving toward or away from the radar | Standing segment, heatmaps |
| `all` | Everything, any velocity | Walking segments, seeing the whole capture |

- Doppler only sees radial motion. Moving toward or away vanishes in zero Doppler, moving sideways at constant range mostly stays
- Still target: both modes look the same, scaled to match

---

## 4. Reading the Heatmap

- **0 dB** = strongest return past the leakage cutoff. Everything else is relative to it
- **Leakage blob** below the dotted 0.3 m line, saturated, ignore it
- **Target smeared across every angle at its range:** four-element array, ~26° beam at boresight, wider off-axis, sidelobes only ~11 dB down. The peak marker is the real angle
- **Dark notches along the target's band:** array nulls, where sin θ differs from the target's by 0.5 and 1.0. Target at +29.5° gives nulls near −0.4° and −30.5°. Seeing them in the right spots confirms the geometry
- **Faint bands further out:** room clutter, 25 to 35 dB down
- **Range:** within one bin (4.69 cm at RSET 0) of a tape measure is normal

This angular smearing is the limit SAR exists to beat.

---

## 5. Angle Convention

- Positive angle = target on the right, radar right side up, RX array horizontal
- Set by `ANGLE_SIGN = -1` in `config.py`
- Radar upside down (like the rail-SAR notebook data): set `ANGLE_SIGN = +1`
- Verified with `sign-right-2` and `sign-right-3`: target right of boresight at 1.41 m, peak +29.5°

Check after any hardware change: target ~30° to one side at ~1.5 m, record 10 s, confirm the sign.

---

## 6. Settings

In `config.py`:

| Setting | Value | Meaning |
|---|---|---|
| `CARRIER_HZ` | `61e9` | Carrier frequency |
| `WAVELENGTH_M` | ~4.914 mm | From carrier |
| `RX_SPACING_M` | `2.464e-3` | RX element spacing, ~λ/2 |
| `ANGLE_SIGN` | `-1` | Flips left and right |
| `ANGLE_LIMIT_DEG` | `70` | Angle grid limit |
| `ANGLE_STEP_DEG` | `0.5` | Angle grid step |
| `LEAKAGE_CUTOFF_M` | `0.3` | Ignored for peak and dB reference |
| `PLOTS_SUBDIR` | `plots` | Plot folder inside each date folder |

---

## 7. Library Reference

### lib/capture.py (files to arrays)

| Function | Purpose |
|---|---|
| `to_stem(path)` | Any capture file or stem to the stem |
| `read_log(stem)` | Frame log CSV to numpy arrays, lost DONE counter = −1 |
| `load(stem, output)` | `(payloads, log, meta)` for `radc` or `rfft`, checks tags and frame count |
| `decode_radc(payloads, meta)` | `(frames, samples, chirps, channels)`, 2D or 3D |
| `decode_rfft(payloads, meta)` | `(frames, range, chirps, channels)`, 2D only |
| `time_window(log, start, end)` | Slice of frames by seconds into the capture |
| `clock_to_seconds(clock, log, meta)` | `HH:MM:SS` to seconds into the capture |

### lib/dsp.py (signal processing)

| Function | Purpose |
|---|---|
| `range_axis(meta, n_bins)` | Range in m of each bin, works with zero padding |
| `range_fft(cube, n_fft)` | Hamming window and FFT over samples |
| `zero_doppler(range_cube)` | Hann-weighted chirp sum |
| `steering_matrix(angles, n_channels)` | `(channels, angles)` phasors |
| `range_angle(profiles, angles)` | Beamform channels to angles |
| `all_doppler_power(range_cube, angles)` | Beamformed power summed over all Doppler |
| `range_angle_power(cube, angles, doppler)` | Cube to power per frame, `zero` or `all` |
| `to_db(power, floor_db, ref)` | dB relative to `ref`, clipped at floor |
| `find_peak(db, ranges, angles)` | Strongest pixel past the leakage cutoff |

### lib/plots.py (shared figures)

| Function | Purpose |
|---|---|
| `range_angle_axes(db, ranges, angles, floor, max_range)` | Map, leakage line, labels, colorbar |

---

## 8. Checks Run

| Check | Result |
|---|---|
| Fast `decode_radc` vs old `decode_radc_2d` | Identical |
| RADC and RFFT logs line up | Same counters |
| Steering vector at 0° | All ones |
| Target right of boresight | Positive angle after `ANGLE_SIGN = -1` |
| Null positions on `sign-right-3` | Match four-element prediction |
| `heatmap.py` after moving plot code to `lib/plots.py` | Same image |

Recheck the decoder after touching `capture.py` `[Laptop]`
```
python -c "
from lib.capture import load, decode_radc
from lib.vmd3 import VMD3
import numpy as np
p, log, m = load('data/2026-10-11/both-test-2', 'radc')
old = VMD3(standalone=True).decode_radc_2d(p[0].tobytes())
print('matches old decoder:', np.allclose(decode_radc(p, m)[0], old))
"
```

---

## 9. Common Errors

| Output | Fix |
|---|---|
| `No frames in that time window` | Window outside the capture, check times in `replay.py` |
| `<name> has no rfft, it has [...]` | Capture recorded without `--outputs rfft` |
| `frames are misaligned or corrupted` | File damaged or truncated mid-write |
| `log lists N frames, file has M` | `.bin` and `_frames.csv` don't match, file damaged |
| `RFFT decoding is only written for 2D captures` | 3D RFFT layout not implemented |
| `FileNotFoundError ..._frames.csv` | Old single `.bin` format, can't load |
| `module 'matplotlib' has no attribute 'subplots'` | Import must be `matplotlib.pyplot as plt` |
| Heatmap left and right swapped | `ANGLE_SIGN` wrong for the radar's orientation |

---

## 10. Open Items

- RFFT middle axis: named `chirps`, but the rail-SAR notebook found it's Doppler with zero at bin 32. Confirm by comparing to a Doppler FFT of RADC before using RFFT
- RX gain imbalance (~4 dB across channels in the notebook) can make sidelobes lopsided
- Measurement 2: phase stability at the target's range bin while the dog stands, its own script
- Range offset seen in the notebook (bin 22 vs expected 18) not yet checked on this setup
