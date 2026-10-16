# Processing Captures

All processing runs on the laptop, from `~/Projects/vmd3/vmd3-dog` with the venv active (numpy, matplotlib). No Pi, Jetson, radar, or network needed.

A capture can be given as its stem or any of its files, e.g. `data/2026-10-15/sitting-real` or `data/2026-10-15/sitting-real.json`.

---

## Quick Reference

| Script | Does | Example |
|---|---|---|
| `replay.py` | Frame by frame map, find segments and times | `python replay.py data/<date>/<name> --maxRange 3` |
| `heatmap.py` | Averaged range-angle map of one window | `python heatmap.py data/<date>/<name> --start 45 --end 220 --maxRange 3` |
| `bgsub.py` | Target, background, and subtracted maps | `python bgsub.py data/<date>/<name> --target 90 210 --background 310 430 --method complex --maxRange 3` |
| `stability.py` | Phase stability of one point, mm of motion | `python stability.py data/<date>/<name> --window 310 430 --maxRange 3` |

All plots save to `data/<date>/plots/`. Add `--show` to also open a window.

### heatmap.py

| Argument | Default | Use |
|---|---|---|
| `stem` | required | Capture path |
| `--start` / `--end` | whole capture | Window in seconds into the capture |
| `--startClock` / `--endClock` | none | Window as `HH:MM:SS`, overrides seconds |
| `--floor` | `-40` | Lowest dB shown |
| `--maxRange` | full range | Top of the range axis in m |
| `--show` | off | Open the plot window too |

### replay.py

| Argument | Default | Use |
|---|---|---|
| `stem` | required | Capture path |
| `--doppler` | `zero` | `zero` = still targets only, `all` = everything |
| `--floor` | `-40` | Lowest dB shown |
| `--maxRange` | full range | Top of the range axis in m |
| `--speed` | `1` | Playback speed, 2 = twice real time |

Controls: Pause/Play button, Frame slider. Pause before dragging the slider. Marks are printed at startup with their frame, seconds, and clock time, and the title shows the current segment.

### bgsub.py

| Argument | Default | Use |
|---|---|---|
| `stem` | required | Capture with the target |
| `--target START END` | required | Target window, seconds |
| `--background START END` | required | Background window, seconds |
| `--bgStem` | same capture | Capture holding the background, if different |
| `--method` | `power` | `power` or `complex` |
| `--floor` | `-40` | Lowest dB shown |
| `--maxRange` | full range | Top of the range axis in m |
| `--show` | off | Open the plot window too |

### stability.py

| Argument | Default | Use |
|---|---|---|
| `stem` | required | Capture path |
| `--window START END` | required | Window, seconds |
| `--range` / `--angle` | strongest return | Point to track |
| `--floor` | `-40` | Lowest dB shown |
| `--maxRange` | full range | Top of the range axis in m |
| `--show` | off | Open the plot window too |

---

## 1. Pipeline

```
load_window            payloads (frames, bytes), log, meta
decode_radc            (frames, samples, chirps, channels)
range_fft              (frames, range, chirps, channels)
zero_doppler           (frames, range, channels)
range_angle            (frames, range, angles)
```

- Range FFT: Hamming window over the 128 samples
- Zero Doppler: Hann-weighted sum over the 64 chirps, same as the zero Doppler bin
- Angle: steering vector beamforming, −70° to +70° at 0.5°, uniform RX weights
- `zero_doppler_profiles` runs decode, range FFT, and zero Doppler 64 frames at a time to keep memory small
- Heatmaps average power over frames, not complex values

---

## 2. Choosing a Time Window

- Marks typed during recording: printed by `replay.py` at startup
- Phone stopwatch laps: convert `M:SS` to seconds, e.g. `3:05.2` = 185.2
- Field notes clock times: `--startClock` / `--endClock` in `heatmap.py`
- Trim a few seconds off each end of a segment

Windows use `elapsed_s` from the frame log, so the startup pause doesn't shift them.

---

## 3. Zero vs All Doppler

| Mode | Shows | Use for |
|---|---|---|
| `zero` | Returns not moving toward or away from the radar | Standing segments, heatmaps, subtraction |
| `all` | Everything, any velocity | Walking segments |

- Doppler only sees radial motion. Moving toward or away vanishes in zero Doppler, moving sideways at constant range mostly stays
- Still target: both modes match

---

## 4. Reading a Range-Angle Map

- **0 dB** = strongest return past the leakage cutoff
- **Below the dotted 0.3 m line:** antenna leakage, ignore it
- **A target smears across every angle at its range:** four-element array, ~26° beam at boresight, sidelobes ~11 dB down. The peak marker is the real angle
- **Dark notches along a target's band:** array nulls where sin θ differs from the target's by 0.5 and 1.0. Seeing them in the right spots confirms the geometry
- **Bands from about 0.9 to 2.2 m on the dog:** ground return, with the radar tilted ~45° down
- **Range:** within one bin (4.69 cm at RSET 0) of a tape measure is normal

---

## 5. Background Subtraction

| Method | How | Needs |
|---|---|---|
| `power` | Average power maps, subtract, clip negatives | Roughly the same spot |
| `complex` | Average complex profiles, subtract, then beamform | Same spot to a fraction of a millimeter |

Why complex does better when it's allowed:
- Clutter cancels exactly before squaring, so the target and clutter interference term never forms
- Clutter sidelobes vanish too, since clutter is removed before beamforming
- Complex averaging pushes noise toward zero, power averaging holds a noise floor

Printed diagnostics:
- **Background match per channel:** complex correlation away from the target. 0.99 or higher justifies complex
- **Clutter away from target:** how much the scene dropped. More negative is cleaner

Best background: remove the target while still recording, without moving the dog. Target and background then come from the same capture and position.

What subtraction can't remove: the target's own sidelobes, ground it shadows, and target-ground multipath. These only exist with the target present and land at or just beyond its range.

---

## 6. Phase Stability

- Tracks one point (range bin + beamformed angle) frame by frame
- Phase to radial displacement: one full turn = λ/2 ≈ 2.46 mm. Mean removed
- **Frame coherence:** |Σ y| / Σ |y|, near 1 = every frame adds in phase
- **λ/8 band:** 0.61 mm wide, rough SAR budget for unknown path error
- **Spectrum:** sway frequency, amplitude in mm. Frame rate is 7.7 Hz, so anything above 3.85 Hz aliases into the plot

Limits:
- Only motion along the line of sight to the tracked point
- Size of the motion is exact, the toward/away sign is unconfirmed
- Pick strong points (above about −20 dB), weak points are noise dominated
- To isolate the platform's motion, track a ground return in a background window with no target and nobody moving

---

## 7. Angle Convention

- Positive angle = target on the right, radar right side up, RX array horizontal
- Set by `ANGLE_SIGN = -1` in `config.py`
- Radar upside down (like the rail-SAR notebook data): `ANGLE_SIGN = +1`
- Verified with `sign-right-2` and `sign-right-3`: target right of boresight, peak +29.5°

---

## 8. Settings

In `config.py`:

| Setting | Value | Meaning |
|---|---|---|
| `CARRIER_HZ` | `61e9` | Carrier frequency |
| `WAVELENGTH_M` | ~4.914 mm | From carrier |
| `RX_SPACING_M` | `2.464e-3` | RX element spacing, ~λ/2 |
| `ANGLE_SIGN` | `-1` | Flips left and right |
| `ANGLE_LIMIT_DEG` | `70` | Angle grid limit |
| `ANGLE_STEP_DEG` | `0.5` | Angle grid step |
| `LEAKAGE_CUTOFF_M` | `0.3` | Ignored for peaks and dB reference |
| `PLOTS_SUBDIR` | `plots` | Plot folder inside each date folder |

---

## 9. Library Reference

### lib/capture.py (files to arrays)

| Function | Purpose |
|---|---|
| `to_stem(path)` | Any capture file or stem to the stem |
| `read_log(stem)` | Frame log CSV to arrays, lost DONE counter = −1, marks included |
| `load(stem, output)` | `(payloads, log, meta)` for `radc` or `rfft`, checks tags and frame count |
| `load_window(stem, start, end, output)` | Same, trimmed to a time window |
| `decode_radc(payloads, meta)` | `(frames, samples, chirps, channels)`, 2D or 3D |
| `decode_rfft(payloads, meta)` | `(frames, range, chirps, channels)`, 2D only |
| `time_window(log, start, end)` | Slice of frames by seconds into the capture |
| `clock_to_seconds(clock, log, meta)` | `HH:MM:SS` to seconds into the capture |

### lib/dsp.py (signal processing)

| Function | Purpose |
|---|---|
| `range_axis(meta, n_bins)` | Range in m of each bin |
| `range_fft(cube, n_fft)` | Hamming window and FFT over samples |
| `zero_doppler(range_cube)` | Hann-weighted chirp sum |
| `zero_doppler_profiles(payloads, meta, block)` | Payloads to zero Doppler profiles, a block at a time |
| `steering_matrix(angles, n_channels)` | `(channels, angles)` phasors |
| `range_angle(profiles, angles)` | Beamform channels to angles |
| `all_doppler_power(range_cube, angles)` | Beamformed power summed over all Doppler |
| `range_angle_power(cube, angles, doppler)` | Cube to power per frame, `zero` or `all` |
| `to_db(power, floor_db, ref)` | dB relative to `ref`, clipped at floor |
| `find_peak(db, ranges, angles)` | Strongest pixel past the leakage cutoff |
| `complex_correlation(a, b)` | Per channel match of two complex profiles |

### lib/plots.py (shared figures)

| Function | Purpose |
|---|---|
| `draw_range_angle(ax, db, ranges, angles, floor, max_range)` | Map on an existing axis |
| `range_angle_axes(db, ranges, angles, floor, max_range)` | Map in a new figure with colorbar |

---

## 10. Results, 2026-10-15

ISO target (UXO surrogate), radar on the dog, RSET 0, ~45° down.

### Background subtraction

| Capture | ISO at | Match per channel | Power | Complex |
|---|---|---|---|---|
| Sitting, separate captures | 0.75 m, +0.5° | 0.988 to 0.995 | −13.6 dB | −18.1 dB |
| Standing, same capture | 1.22 m, −6.5° | 0.988 to 0.994 | −12.8 dB | −13.8 dB |

- ISO range matches the tape measure within a bin
- Standing: the ISO is buried in ground clutter until subtracted

### Stability

| Setup | Point | RMS | Peak to peak | Coherence |
|---|---|---|---|---|
| Bench, radar on a stand | Plate | 0.002 mm | 0.009 mm | 1.0000 |
| Dog sitting | Ground, no ISO | 0.004 mm | 0.018 mm | 1.0000 |
| Dog sitting | ISO | 0.009 mm | 0.051 mm | 0.9998 |
| Dog standing | ISO | 0.027 mm | 0.172 mm | 0.9976 |
| Dog standing | Ground, no ISO | 0.040 mm | 0.216 mm | 0.9947 |

- Standing moves the radar 10 to 20× the bench, sitting 2 to 4×
- Worst case 0.22 mm peak to peak, about a third of the 0.61 mm SAR budget
- Sharp line at 3.34 Hz on the dog, sitting and standing. Absent on the bench (floor below 0.001 mm), so it comes from the dog. True frequency may be higher and aliased

| Capture | Point | 3.34 Hz amplitude | Total RMS |
|---|---|---|---|
| Standing | Ground | 0.045 mm | 0.040 mm |
| Sitting | Ground | 0.004 mm | 0.004 mm |
| Standing | ISO | 0.025 mm | 0.027 mm |
| Sitting | ISO | ~0.006 mm, several peaks 3.2 to 3.35 Hz | 0.009 mm |

- 4 to 12× stronger standing, depending on the line of sight to the tracked point
- The line is most of the motion. A sine's RMS is 0.71 × its amplitude, so it accounts for ~0.032 of 0.040 mm (standing ground) and ~0.018 of 0.027 mm (standing ISO)
- Sitting shows several close lines that beat against each other, standing one dominant line
- Sitting is the better pose for stepped SAR

---

## 11. Checks Run

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

## 12. Common Errors

| Output | Fix |
|---|---|
| `No frames in <name> between ...` | Window outside the capture, check times in `replay.py` |
| `<name> has no rfft, it has [...]` | Capture recorded without `--outputs rfft` |
| `frames are misaligned or corrupted` | File damaged or truncated |
| `log lists N frames, file has M` | `.bin` and `_frames.csv` don't match |
| `RFFT decoding is only written for 2D captures` | 3D RFFT layout not implemented |
| `FileNotFoundError ..._frames.csv` | Old single `.bin` format, can't load |
| `module 'matplotlib' has no attribute 'subplots'` | Import must be `matplotlib.pyplot as plt` |
| `Warning: weak point, phase may be mostly noise` | Track a stronger point |
| Heatmap left and right swapped | `ANGLE_SIGN` wrong for the radar's orientation |

---

## 13. Open Items

- Source of the 3.34 Hz vibration on the dog, and whether it can be paused during SAR
- Displacement sign (toward vs away) on this radar
- Longer bench baseline (2 min) for slow drift
- Complex alignment coefficient per channel before subtraction, as in the rail-SAR notebook
- RFFT middle axis: rail-SAR notebook found it's Doppler, zero at bin 32. Confirm before using RFFT
- RX gain imbalance (~4 dB in the notebook) can make sidelobes lopsided
- Range offset seen in the notebook (bin 22 vs expected 18) not yet checked on this setup
