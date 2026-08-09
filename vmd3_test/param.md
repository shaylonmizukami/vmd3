
| Parameter | RSET 0 | RSET 1 | How it's calculated |
|---|---|---|---|
| **Max Range** | 6 m | 10 m | $d_\text{max} = F_s \cdot c / (2S)$ — set by ADC speed and chirp slope |
| **Max Speed** | 10 km/h | 10 km/h | $v_\text{max} = \lambda / (4 \cdot T_\text{PRI})$ — set by chirp spacing |
| **Angle Setting** | 2D | 2D | Datasheet preset (chooses TX antenna configuration) |
| **Samples per Chirp** | 128 | 128 | Datasheet preset (firmware-fixed for these RSETs) |
| **Chirps per Frame** | 64 | 64 | 2D mode uses 1 TX → 64 chirps; 3D uses 3 TX → 32 chirps each |
| **Range Resolution** | 4.69 cm | 7.82 cm | $\Delta R = c / (2 \cdot \text{BW})$ — finer with wider bandwidth |
| **Speed Resolution** | 0.31 km/h | 0.31 km/h | $\Delta v = v_\text{max} / (N_\text{chirps}/2)$ — set by chirp count |
| **Sweep Start Frequency** | 60.095 GHz | 60.095 GHz | Datasheet default (configurable 57–64 GHz on hardware) |
| **Sweep Bandwidth** | 3.2 GHz | 1.92 GHz | $\text{BW} = S \cdot T_\text{chirp}$ — or $c / (2 \cdot \Delta R)$ from resolution |
| **Sweep End Frequency** | 63.3 GHz | 62.0 GHz | $f_\text{start} + \text{BW}$ |
| **Center Frequency** | 61.7 GHz | 61.06 GHz | $(f_\text{start} + f_\text{end}) / 2$ |
| **Wavelength (λ)** | 4.86 mm | 4.91 mm | $\lambda = c / f_c$ — used for converting phase to displacement |
| **Sweep Slope** | ~50 GHz/ms | ~30 GHz/ms | $S = \text{BW} / T_\text{chirp}$ — how fast the chirp ramps |
| **Chirp Duration** | 64 μs | 64 μs | $T_\text{chirp} = N_\text{samples} / F_s$ — time to fill the ADC buffer |
| **Sample Rate** | 2 MHz | 2 MHz | Datasheet default (controls beat-frequency Nyquist limit) |
| **Sweep Repetition Time** | 147 μs | 147 μs | Datasheet preset (chirp duration + dead time between chirps) |
| **Frame Repetition Time** | 130 ms | 130 ms | Datasheet preset (TIME_STEP in the processing script) |



- $c$ = speed of light (3 × 10⁸ m/s)
- $F_s$ = ADC sample rate (Hz)
- $S$ = chirp slope (Hz/sec)
- $T_\text{chirp}$ = duration of one chirp (s)
- $T_\text{PRI}$ = sweep repetition time, also called pulse/chirp repetition interval (s)
- $N_\text{samples}$ = samples per chirp (128)
- $N_\text{chirps}$ = chirps per frame
- BW = chirp bandwidth (Hz)
- $f_c$ = center frequency of the chirp (Hz)
- $\lambda$ = wavelength at center frequency (m)
- $\Delta R$ = range resolution (m)
- $\Delta v$ = speed resolution (m/s or km/h)



# Binary Data File Structure
```
Sweep 0:  [Ch0: 256 int16] [Ch1: 256] [Ch2: 256] [Ch3: 256]   ← 2048 bytes
Sweep 1:  [Ch0: 256 int16] [Ch1: 256] [Ch2: 256] [Ch3: 256]
...
Sweep 63: [Ch0: 256 int16] [Ch1: 256] [Ch2: 256] [Ch3: 256]
```
