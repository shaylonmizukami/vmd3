# V-MD3 FMCW Rail-SAR: Complete Working Reference

*A consolidated guide to the four source documents, written so you can replicate the measurements, understand the processing, and continue the work.*

---

## Table of Contents

**Part 0 — Orientation**
- 0.1 What the four source files are and which one to trust
- 0.2 How to read this document

**Part I — Concepts**
- 1.1 What SAR actually is
- 1.2 Why FMCW is the right radar for it
- 1.3 Four pictures people constantly confuse
- 1.4 The resolution math that governs everything
- 1.5 Why your magnitude plot will look boring

**Part II — The Hardware and the Data Format**
- 2.1 V-MD3 mode 0 specifications
- 2.2 Where those numbers come from
- 2.3 The binary record format
- 2.4 RADC decoding
- 2.5 RFFT decoding
- 2.6 DONE decoding
- 2.7 Canonical array shapes
- 2.8 File sizes and memory budget

**Part III — Taking the Measurements**
- 3.1 Physical setup
- 3.2 The rail and encoder
- 3.3 The four runs and what each one proves
- 3.4 Acquisition protocol
- 3.5 Rules you must not break
- 3.6 How to save and organize the data
- 3.7 Sampling constraints to respect

**Part IV — The Processing Pipeline Explained**
- 4.1 Overview and the processing fork
- 4.2 Stage 1: decode and validate
- 4.3 Stage 2: range FFT
- 4.4 Stage 3: Doppler FFT and zero-Doppler extraction
- 4.5 Stage 4: coherent frame averaging
- 4.6 Stage 5: complex background subtraction
- 4.7 Path A: four-RX range-azimuth beamforming
- 4.8 Path B: aperture phase history
- 4.9 Path B continued: backprojection
- 4.10 Range oversampling
- 4.11 Window selection, both dimensions

**Part V — What the Data Actually Showed**
- 5.1 FPGA versus Python agreement
- 5.2 Coherence results
- 5.3 Background subtraction performance
- 5.4 Phase sign determination
- 5.5 The q=22 anomaly
- 5.6 Final Run C image measurements

**Part VI — The Frozen Pipeline (Runnable Reference)**
- 6.1 Acquisition checklist
- 6.2 Processing steps
- 6.3 Validation gates

**Part VII — Function Reference**

**Part VIII — Traps, Lessons, and Debugging**

**Part IX — Open Items and Next Steps**
- 9.1 Run D, the validation that has not happened yet
- 9.2 Resolving the range offset
- 9.3 Multi-RX SAR
- 9.4 Other open items

**Part X — Corrections Table**

**Part XI — Refactor and Template Roadmap**

**Appendix A — Quick Number Reference**
**Appendix B — Formula Sheet**

---

# Part 0 — Orientation

## 0.1 What the four source files are and which one to trust

You gave me four documents that were written at different times and at different levels of maturity. They do not fully agree with each other, so knowing the lineage matters.

**`vmd3_fmcw_to_sar_basics.ipynb`** is a teaching scaffold. It lays out ten milestones from raw I/Q to a focused image, with a loader deliberately left as `NotImplementedError`. Its concepts are sound but several of its numbers and its assumed data layout are wrong. Treat it as a syllabus, not a specification.

**`VMD3_notebook_generalization_guide.md`** is a software architecture document. It describes how to turn a working experiment notebook into a reusable template, and it contains the first correct statement of the hardware configuration. Its advice on manifests, configuration separation, and staged refactoring is all still good.

**`vmd3_synthetic_sar_first_principles_v2.ipynb`** is the physics, demonstrated on a synthetic dataset where nothing is hidden. It is the clearest explanation of why any of this works, and it is where the correct axis convention, carrier frequency, and RX element spacing first appear together.

**`vmd3_sar_basics.ipynb`** is the real thing. It decodes the actual binary format, processes the actual Runs A through C, cross-validates against the FPGA, and produces a focused image. **When any document conflicts with this one, this one wins.**

## 0.2 How to read this document

Parts I through III are what you need before you touch a keyboard. Part IV is the explanation of every processing step and why it is there. Part V is what the data actually said. Part VI is a terse runnable checklist for when you already understand everything and just need the sequence. Parts VIII through XI are for picking the project back up.

---

# Part I — Concepts

## 1.1 What SAR actually is

You already know how a range profile works. You transmit, you listen, and the round-trip delay tells you how far away something is. What range alone cannot tell you is where across the beam a target sits. Everything at 0.84 m lands in the same bin whether it is dead ahead or off to one side.

The usual fix is an antenna array, but angular resolution scales with aperture size, and the V-MD3's physical array spans about 7.4 mm. Synthetic aperture radar cheats. You slide the radar along a rail, take a complex measurement at each stop, and then treat those stops as elements of one enormous array that you built out of time instead of hardware.

The focusing step is conceptually simple. For every candidate pixel in your image you know the geometry, so you can predict the exact round-trip range from each rail position to that pixel. You interpolate the measured complex range profile at that predicted range, multiply by a phase term that undoes the predicted propagation phase, and sum over all positions. If a real scatterer sits at that pixel, all seventeen contributions line up in phase and add constructively. If not, they scatter around the unit circle and cancel.

That is the entire algorithm.

$$I(x,z)=\sum_m w_m\,\widetilde G_m\!\left(R_m(x,z)\right)e^{-j4\pi R_m(x,z)/\lambda},\qquad R_m=\sqrt{(x-x_m)^2+z^2}$$

The payoff in your setup is large. The physical four-channel array gives about 26 degrees of beamwidth, which at 0.84 m is roughly 40 cm of cross-range blur. A 10 cm synthetic aperture measured 1.7 cm.

## 1.2 Why FMCW is the right radar for it

FMCW hands you two separate pieces of information out of the same measurement, and SAR needs both.

The **magnitude** of the range FFT gives coarse range. Beat frequency maps to range through $R=cf_b/2S$, and resolution is $c/2B$.

The **phase** of that same complex bin gives sub-wavelength range. A target's round-trip phase is $4\pi R/\lambda$, and at 61 GHz the wavelength is 4.914 mm, so a 1 mm change in range swings the phase by roughly 147 degrees.

The synthetic notebook states the signal model explicitly, and it is worth internalizing:

$$x=\alpha\exp\!\left(j2\pi f_b \tfrac{n}{f_s}\right)\exp\!\left(-j\tfrac{2\pi}{\lambda}L\right),\qquad f_b=\frac{KL}{c_0}$$

Two exponentials, two jobs. The first puts the target in a range bin. The second is the carrier phase, and for a monostatic channel where $L=2R$ it reduces to $-4\pi R/\lambda$. That second term is the entire basis of SAR.

## 1.3 Four pictures people constantly confuse

The source notebooks are pedantic about this and they are right to be.

1. **Range profile.** One position, one FFT, magnitude versus range. One dimensional.
2. **Range-azimuth heatmap.** One position, digital beamforming across the four RX channels, stacked per angle. The horizontal axis is *arrival angle*. This is what you have already done with the V-MD3.
3. **Range-aperture B-scan.** Many mechanical positions, magnitude range profile at each, stacked. The horizontal axis is *where the radar was*, not where the target is. Unfocused.
4. **Focused SAR image.** Same data as number 3, but coherently processed. The horizontal axis is *estimated target cross-range*.

Number 3 to number 4 is the whole jump, and it is entirely a phase operation. The magnitude data is identical.

## 1.4 The resolution math that governs everything

Everything in this project falls out of four expressions.

**Range resolution** depends only on bandwidth.

$$\delta_R=\frac{c}{2B}=\frac{3\times10^8}{2\times 3.2\times10^9}=4.69\text{ cm}$$

No amount of SAR processing, zero-padding, or windowing changes this. Only more transmitted bandwidth does.

**Cross-range resolution** depends on aperture length.

$$\delta_x\approx\frac{\lambda R}{2L}=\frac{4.914\text{ mm}\times0.84\text{ m}}{2\times0.10\text{ m}}=2.06\text{ cm}$$

For an ideal uniformly weighted aperture, the full −3 dB width is a slightly different convention:

$$\Delta x_{-3\text{dB}}\approx0.443\frac{\lambda R}{L}=1.83\text{ cm}$$

**Grating lobe limit** depends on position spacing.

$$|x|_{\max}\approx\frac{\lambda R}{4\Delta x}=\frac{4.914\text{ mm}\times0.84\text{ m}}{4\times6.25\text{ mm}}=16.5\text{ cm}$$

Aperture *length* controls resolution. Aperture *sample spacing* controls aliasing. A long but sparsely sampled rail can have a narrow main lobe and still produce false repeated targets.

**Unfocused coherent limit** is the longest stretch you could coherently add with no phase correction at all.

$$L_u\approx\sqrt{\frac{R\lambda}{2}}=\sqrt{\frac{0.84\times4.914\text{ mm}}{2}}=4.54\text{ cm}$$

Your 10 cm aperture is about 2.2 times this, so focusing buys you real improvement but the aperture is not enormously long. If you ever get to design the next acquisition, a longer rail is the single biggest lever on image quality.

## 1.5 Why your magnitude plot will look boring

Run the geometry for a centered sphere at 0.84 m with a ±5 cm aperture.

$$\Delta R_\text{edge}=\sqrt{0.84^2+0.05^2}-0.84\approx1.49\text{ mm}$$

That is about 1/31 of a range bin. The B-scan will show a flat horizontal ridge. There will be no visible hyperbola, no range migration, nothing.

Now the same distance in phase:

$$\Delta\phi=\frac{4\pi\Delta R}{\lambda}=\frac{4\pi\times1.49\text{ mm}}{4.914\text{ mm}}\approx218^\circ$$

More than half a cycle. The entire SAR signal lives in a phase curve you cannot see unless you deliberately go and plot it.

This is the single most important expectation to set before you look at real data. A flat B-scan is not broken data. It is exactly what the geometry predicts. The notebooks call this a **sub-bin range change observed through phase**, which is a good name for it.

---

# Part II — The Hardware and the Data Format

## 2.1 V-MD3 mode 0 specifications

| Property | Value |
|---|---|
| Carrier frequency | 61 GHz |
| Wavelength | 4.914 mm |
| ADC sample rate | 2 MHz |
| Samples per chirp | 128 |
| Chirp duration | 64 µs |
| Chirp slope | about 5.0 × 10¹³ Hz/s |
| Chirp bandwidth | about 3.2 GHz |
| Chirps per frame | 64 |
| RX channels | 4 |
| RX element spacing | 2.464 mm (about λ/2) |
| Range bin spacing | 0.046875 m |
| Range bins | 128 |
| Unambiguous range | 6.0 m |
| Range resolution | 4.69 cm |
| RADC frame shape | (128, 64, 4) |
| RADC payload | 131,072 bytes |
| RFFT frame shape | (128, 64, 4) |
| RFFT payload | 131,072 bytes |

The 3-D mode, which is not implemented anywhere yet, uses (128, 32, 12) with a 196,608 byte payload. That shape is consistent with three TX by four RX in TDM-MIMO, which suggests mode 0 is one TX by four RX. Do not treat that as confirmed.

## 2.2 Where those numbers come from

Some of these are given by the vendor and some fall out of arithmetic, and it helps to know which.

128 × 64 × 4 = 32,768 samples per frame, and 131,072 / 32,768 = **4 bytes per sample**, which is int16 I plus int16 Q. The data is complex on arrival. This matters because complex sampling keeps positive and negative beat frequencies distinct, whereas real sampling would fold them together.

Bin spacing of 6 m / 128 = 4.6875 cm implies the chirp slope through $R = cf_b/2S$, which works out to about 5.0 × 10¹³ Hz/s, and multiplying by the 64 µs chirp duration gives 3.2 GHz of bandwidth. Range resolution $c/2B$ is then 4.69 cm, which equals the bin spacing. That equality is not a coincidence. It means the range sampling is Nyquist-matched to the resolution, with no oversampling and no gaps.

## 2.3 The binary record format

Every `.bin` file is a flat sequence of records. Each record has an 8-byte header.

```
bytes 0:4   ASCII stream code: RADC, RFFT, or DONE
bytes 4:8   payload length, little-endian unsigned int
bytes 8:    payload
```

Three stream types exist. `RADC` is the raw complex ADC data, `RFFT` is the FPGA's own range-Doppler output, and `DONE` is a four-byte frame counter.

The parser walks the file record by record and raises an error if it does not land exactly on the file size at the end. That is a good integrity check and you should keep it.

**Record ordering is not assumed.** The records are saved in UDP arrival order, so the validator does not require repeating RADC-RFFT-DONE triplets. Instead it counts each stream independently and checks that the per-stream frame indices run 0 through N−1 within each file. DONE continuity across a file is your dropped-frame detector.

## 2.4 RADC decoding

The on-disk layout is chirp-major, then channel, then interleaved samples, and the interleaving is **Q first, then I**.

```
raw = np.frombuffer(payload, dtype="<i2").reshape(64, 4, 256)
q   = raw[:, :, 0::2]      # even indices are Q
i   = raw[:, :, 1::2]      # odd indices are I
cube = np.transpose(i + 1j*q, (2, 0, 1))   # -> (128, 64, 4)
```

The Q-before-I ordering is the kind of thing you would never guess and that would silently hand you a conjugated signal. If you ever port this code, write that down first.

The final cube is `(sample, chirp, channel)`.

## 2.5 RFFT decoding

The FPGA output has a different memory layout, channel-major.

```
raw = np.frombuffer(payload, dtype="<i2").reshape(4, 128, 64, 2)
q   = raw[:, :, :, 0]
i   = raw[:, :, :, 1]
cube = np.transpose(i + 1j*q, (1, 2, 0))   # -> (128, 64, 4)
```

The final cube is `(range_bin, doppler_bin, channel)`.

**Axis 1 is Doppler, confirmed.** Earlier documents called it a provisional `slow_time_index` because nobody knew whether the FPGA had applied only a range FFT or both transforms. Section 2.4 of the real notebook settles it by computing both products in Python and comparing. The FPGA does the range FFT *and* the Doppler FFT, with zero Doppler centered at bin 32. Rename that axis everywhere.

## 2.6 DONE decoding

Four bytes, little-endian unsigned integer, behaving as a radar-side frame counter.

```
value = int.from_bytes(payload, byteorder="little", signed=False)
```

Consecutive values within a file mean no frames were dropped. A jump means you lost one.

## 2.7 Canonical array shapes

Use these consistently. The whole pipeline assumes frame-first, then physical dimensions.

| Product | Shape |
|---|---|
| One RADC frame | (sample, chirp, channel) = (128, 64, 4) |
| RADC stack, one position | (frame, sample, chirp, channel) |
| RADC stack, all positions | (position, frame, sample, chirp, channel) |
| One RFFT frame | (range_bin, doppler_bin, channel) |
| RFFT stack | (frame, range_bin, doppler_bin, channel) |
| Zero-Doppler product | (position, frame, range_bin, channel) |
| After frame averaging | (position, range_bin, channel) |
| Single-RX aperture data | (position, range_bin) |
| Focused image | (downrange, cross_range) |

**There is no beam axis anywhere.** The hardware does not steer beams. You get four raw RX channels and you form angles digitally. The first teaching notebook assumed `[frame, beam, rx, chirp, sample]` and that assumption is simply wrong. Where it says "beam," read "angle bin you synthesized."

## 2.8 File sizes and memory budget

Per frame, on disk: 131,080 bytes RADC plus 131,080 bytes RFFT plus 12 bytes DONE, so 262,172 bytes.

- Run A, 5 frames, one file: about 1.31 MB
- Runs B, C, D, 20 frames per file, 17 files each: about 5.24 MB per file, 89 MB per run

In memory as complex128, one full run's RADC is 17 × 20 × 128 × 64 × 4 = 11.1 million complex values, which is about 178 MB. Holding Run B and Run C simultaneously is roughly 356 MB. That is fine on a workstation but it is why the generalization guide recommends lazy per-position loading for anything larger.

---

# Part III — Taking the Measurements

## 3.1 Physical setup

- Radar height: 0.315 m
- Target: metal sphere, diameter flagged as provisional (see 9.4)
- Target slant range: approximately 0.84 m
- Target near boresight for Runs A and C
- Absorber, mounting structure, floor, and cables all present and treated as static clutter

The radar is mounted on a Galil-driven linear rail. The imaging plane is two dimensional, with $x$ parallel to the rail and $z$ the slant-range direction. Note that $z$ is not ground range and not vertical height.

## 3.2 The rail and encoder

Seventeen positions, encoder counts from 0 to 800,000 in steps of 50,000. Center is position index 8 at count 400,000.

$$x_m=\left(\text{count}_m-400{,}000\right)\times\frac{0.10\text{ m}}{800{,}000}$$

This gives positions from −5 cm to +5 cm in steps of **6.25 mm**, since there are 16 intervals across the 10 cm span.

**Important caveat.** The 0.10 m aperture length is passed in as an assumption, not measured. The code divides it by the encoder span to derive meters per count. If the true travel over 800,000 counts is not exactly 10 cm, your entire cross-range axis scales proportionally and every cross-range number you quote is off by the same factor. Verify this against the Galil specification or a tape measure before publishing anything.

## 3.3 The four runs and what each one proves

**Run A, fixed position.** Radar parked at the center, sphere present near boresight, 5 repeated frames. One file. This is your decoding sandbox and your coherence gate. It validates binary decoding, offline range processing, FPGA RFFT interpretation, range-azimuth processing, and frame-to-frame phase stability. Run A contains no synthetic aperture.

**Run B, background.** Sphere removed, all 17 positions, 20 frames each. Characterizes static clutter from rail, mount, absorber, floor, cables, and the surrounding room. Also serves as the matched background at position 8 for Run A.

**Run C, centered sphere.** Sphere near $x=0$, all 17 positions, 20 frames each. The primary SAR dataset.

**Run D, offset sphere.** Sphere displaced in cross-range, same 17 positions. The validation dataset.

Run D is the one that matters scientifically and it has not been processed yet. A bright blob in a Run C image proves nothing, because you can get a bright blob from a bug. A blob that moves by the right amount when you physically move the target is real evidence.

## 3.4 Acquisition protocol

1. Mount the radar on the rail at 0.315 m height. Level the rail.
2. Record the encoder count at rail center. Confirm the count range and step size.
3. Place the sphere at boresight. Measure slant range with a tape. Record the sphere diameter from the actual object, not from a prior note.
4. **Run A.** Park at center position. Capture 5 frames. Save.
5. Remove the sphere without touching the rail, mount, or anything else in the room.
6. **Run B.** Step the rail through all 17 positions, 20 frames at each, logging the encoder count at every stop. Save one file per position.
7. Replace the sphere at $x=0$. Measure it, do not eyeball it.
8. **Run C.** Repeat the same sweep, 20 frames per position. Save.
9. Move the sphere to the offset position. **Measure the displacement precisely.** Record it.
10. **Run D.** Repeat the sweep again. Save.

## 3.5 Rules you must not break

- Do not change any radar setting between runs. Not gain, not chirp config, not frame rate.
- Do not move the rail, the mount, the absorber, or anything else in the room between B, C, and D.
- Do not move the radar between Run A and Run B position 8.

These exist because complex background subtraction is only valid if the runs are mutually phase coherent and geometrically repeatable. Bump the rail between runs and you have thrown that away permanently, with no way to recover it in post-processing. The measured Run A to Run B alignment coefficients came out at 1.025 to 1.036 in magnitude and about −1 degree in phase, which is how you know this discipline was actually maintained.

## 3.6 How to save and organize the data

Current naming is `scan_0cm.bin` or `scan_posNcm.bin`, with position metadata supplied separately from the binaries. That works but it is fragile. The number in the filename is treated as a **position index, not a trustworthy physical distance in centimeters**, which is the right call.

Build two manifests before you process anything.

**File manifest**, one row per acquisition file:

```
dataset_name, run, role, acquisition_type, position_index,
encoder_count, position_m, filename, path, file_size_bytes
```

**Record manifest**, one row per stored record inside every file:

```
run, role, position_index, position_m, filename, path,
record_index, stream, stream_frame_index,
header_offset, payload_offset, payload_length,
frame_length, done_value
```

Then validate. All configured directories exist. Expected file counts match configuration, not hard-coded numbers. No duplicate position indices within a run. Position indices consistent with the metadata. Positions monotonic and uniformly spaced. File sizes nonzero. Payload lengths match the active radar configuration. Known stream identifiers only. Payloads inside file boundaries. DONE counters consecutive.

Validators should raise informative errors rather than silently returning malformed arrays. You want to find a decode problem at load time, not three milestones later when an image looks strange.

**The SAR algorithm must consume `position_m`, never the filename.**

## 3.7 Sampling constraints to respect

At 6.25 mm spacing the alias-free half-extent is 16.5 cm at 0.84 m, comfortably wider than the ±10 cm image grid used. No grating lobes.

This is worth knowing because the earlier teaching notebook assumed 1 cm spacing, which would have given only ±10.4 cm and put you right at the edge. The finer real spacing is a meaningful improvement. If you design a future acquisition with coarser steps, recompute this before choosing an image grid.

---

# Part IV — The Processing Pipeline Explained

## 4.1 Overview and the processing fork

Both products, the conventional heatmap and the SAR image, come from the same reduction. The split happens late.

```
raw complex I/Q                     (position, frame, sample, chirp, channel)
    -> range FFT over sample        (position, frame, range, chirp, channel)
    -> Doppler FFT over chirp       (position, frame, range, doppler, channel)
    -> extract zero Doppler         (position, frame, range, channel)
    -> coherent frame average       (position, range, channel)
    -> complex background subtract  (position, range, channel)
         |
         +-- PATH A: pick one position, sum across RX channels -> range-azimuth map
         +-- PATH B: pick one channel, sum across positions    -> focused SAR image
```

Nothing about the range processing decides which one you get. The distinction is purely which spatial aperture you coherently combine after the complex range profiles exist.

| | Conventional heatmap | SAR |
|---|---|---|
| Positions used | One | All 17 |
| Sum across | Physical RX channels | Mechanical rail positions |
| Hypothesis tested | Candidate angle $\theta$ | Candidate pixel $(x,z)$ |
| Model used | Far-field steering vector | Predicted range and propagation phase |

## 4.2 Stage 1: decode and validate

Read the record manifest, seek to each payload offset, decode, and stack. The validator checks four dimensions, correct per-frame shape, expected frame count, all values finite, and reports I/Q min and max plus the exact-zero fraction.

That exact-zero fraction is a useful early warning. A decode with the wrong reshape often produces suspiciously many exact zeros or an implausible dynamic range.

Also confirm that RADC, RFFT, and DONE streams have matching frame counts and that the DONE values are consecutive.

## 4.3 Stage 2: range FFT

```
compute_radc_range_fft(radc_frame, range_window, remove_fast_time_mean)
    input:  (sample, chirp, channel)
    output: (range_bin, chirp, channel)
```

Optionally remove the fast-time mean, apply a window across fast time, then FFT along axis 0.

**On the DC removal question.** The two earlier documents disagreed on whether `remove_fast_time_mean` should default to True or False. The real notebook defaults it to False and never enables it. The reason is that complex background subtraction removes the near-range coupling far more effectively than mean removal does, and the q≈0 response essentially vanishes after subtraction. Leave it False.

**Beat frequency sign.** With complex sampling, positive and negative beat frequencies are distinct, and which side your targets land on depends on the dechirp convention. In this data the targets appear on the positive side and no unwrapping or flipping is needed. If you ever process a new mode and the positive half looks empty, check the negative half before changing anything else.

## 4.4 Stage 3: Doppler FFT and zero-Doppler extraction

```
compute_radc_range_doppler(radc_frame, range_window, doppler_window, center_doppler=True)
    output: (range_bin, doppler_bin, channel)
```

Window across chirp index, FFT along axis 1, then `fftshift` so zero Doppler lands at bin 32.

The scene is stationary, so you keep only the zero-Doppler slice. `extract_zero_doppler` takes index `shape//2` along the Doppler axis and works on either a single cube or a stacked array.

**A useful shortcut.** The unshifted Doppler bin $p=0$ is mathematically identical to the windowed complex sum over chirp index. The oversampled processing in section 3.5 exploits this and sums directly instead of computing all 64 Doppler bins and discarding 63. Over 17 positions times 20 frames that saves real time.

## 4.5 Stage 4: coherent frame averaging

$$\overline{C}_m[q,\ell]=\frac{1}{F}\sum_{f=0}^{F-1}C^{(0)}_{m,f}[q,\ell]$$

This is a **complex** average. Real and imaginary parts are averaged before any magnitude is taken. Stable returns reinforce, uncorrelated noise reduces, and the phase survives.

Frames are averaged **only within a rail position**. The 17 positions are never averaged together, because their position-dependent phase differences are the entire SAR signal.

Before averaging, check the frame-coherence factor:

$$\gamma_m[q,\ell]=\frac{\left|\sum_f x_f\right|}{\sum_f\left|x_f\right|}$$

The denominator is the magnitude you would get if every frame added perfectly in phase. A value near 1 means coherent averaging is justified. A low value means the phases partially cancel. Note that frame magnitudes need not be equal for $\gamma=1$, since samples of magnitude 1, 2, and 5 all pointing the same direction still give $\gamma=1$. It is primarily a phase-consistency measure.

## 4.6 Stage 5: complex background subtraction

This is where the real notebook goes well beyond what the earlier documents suggested.

Rather than subtracting Run B directly, estimate a least-squares complex coefficient that maps background to target, independently for every rail position and every RX channel:

$$\alpha_{m,\ell}=\frac{\sum_{q\in\mathcal{Q}_\text{ref}}\overline{C}_m[q,\ell]\,\overline{B}_m^*[q,\ell]}{\sum_{q\in\mathcal{Q}_\text{ref}}\left|\overline{B}_m[q,\ell]\right|^2}$$

$$G_m[q,\ell]=\overline{C}_m[q,\ell]-\alpha_{m,\ell}\overline{B}_m[q,\ell]$$

The reference bins $\mathcal{Q}_\text{ref}$ are equivalent original bins 1 through 50, excluding 15 through 26. Bin 0 is excluded because it is dominated by direct coupling and DC. Bins 15 through 26 are excluded because they contain both the geometrically expected sphere region and the observed response at q=22, and you must not let the target influence its own background estimate.

There is also a magnitude threshold. Only bins at least 35 dB below the reference-region peak in *both* runs contribute, so weak noise-dominated samples cannot steer the alignment.

Two diagnostics come out of this. The **complex correlation** $\rho$ tells you whether Run B is a good template for Run C apart from one overall complex scale. The **residual reduction** tells you how much reference-region power the subtraction actually removed.

**The coefficient is applied only to the background.** It never rotates or corrects the Run C target data, so the position-dependent target phase that SAR needs is preserved exactly.

**Subtraction happens while the data is complex, before any magnitude is taken.** Magnitude subtraction would destroy the phase and make SAR impossible.

### Coherence versus correlation

These are both normalized 0 to 1 and they answer different questions. Worth keeping straight.

| Metric | Compares | Varies over | Question |
|---|---|---|---|
| Frame coherence $\gamma$ | Repeated frames, one run | Frame index $f$ | Will frames reinforce under coherent averaging? |
| Complex correlation $\rho$ | Run C profile vs Run B profile | Range bin $q$ | Is Run B a good complex template for Run C? |
| Focusing coherence $\eta$ | Measurements from different rail positions | Position index $m$ | Do they reinforce after geometric phase compensation? |

You could have excellent frame coherence and poor correlation, meaning Run C is internally stable but the background scene changed. You could have similar average profiles and poor frame coherence, meaning the averaged profiles look correlated but coherent integration would fail.

## 4.7 Path A: four-RX range-azimuth beamforming

The steering vector uses RX positions centered on the array midpoint:

$$x_\ell=\left(\ell-\tfrac{M-1}{2}\right)d,\qquad d=2.464\text{ mm}$$

$$v_\ell(\theta)=e^{-jkx_\ell\sin\theta},\qquad Y[q,\theta]=\sum_\ell X[q,\ell]\,v_\ell^*(\theta)$$

In NumPy this is one matrix multiply. The conjugate is the matched filter in space. It removes the phase progression predicted for a trial angle, and if the trial is right the four channel phasors point the same direction in the complex plane and add.

A point worth internalizing. **The steering vector entries are not antenna coordinates.** The coordinates go into the phase model and what comes out is a set of dimensionless phasors. At broadside every entry is 1, which is a good sanity check when you build yours.

The angle grid used is `np.linspace(-70, 70, 281)`. That is a display choice, not a hardware property.

**Never coherently average RX channels before beamforming.** For a magnitude-only diagnostic you may noncoherently sum power across channels, but combining complex channels without understanding relative phase will steer your beam to the wrong place and you will not notice.

### Aperture weighting on four elements

Section 2.10 tests this and the answer is clear.

| Window | Normalized weights | Ideal −3 dB | Measured −3 dB | Noise penalty |
|---|---|---|---|---|
| Uniform | [0.25, 0.25, 0.25, 0.25] | 26.2° | 25.5° | 0.00 dB |
| Hamming | [0.047, 0.453, 0.453, 0.047] | 46.6° | 45.0° | 2.20 dB |
| Hann | [0, 0.5, 0.5, 0] | 59.6° | 60.0° | 3.01 dB |

Hann zeroes the outer two elements entirely, reducing a four-element array to two. Uniform wins decisively here. Note that this conclusion reverses for the 17-position synthetic aperture, where tapering becomes affordable.

The close agreement between ideal and measured widths is strong evidence that the element spacing, steering convention, and channel ordering are all correct. The broad angular response is a physical aperture limit, not a calibration failure.

## 4.8 Path B: aperture phase history

Before forming any image, test whether the measured phase across the rail matches what geometry predicts. This is the gate that decides whether SAR will work.

Extract the complex sample at the target range bin from all 17 positions. Compute the predicted range from each position:

$$R_{m,\ell}=\sqrt{\left(x_t-x_m-x_\ell\right)^2+z_t^2}$$

Reference everything to the center position so that constant absolute range and system phase terms cancel:

$$\Delta\psi_m=\pm\frac{4\pi}{\lambda}\left(R_m-R_\text{center}\right)$$

Remove the predicted phase, sum across positions, and compute the **aperture focusing coherence**:

$$\eta_\ell=\frac{\left|\sum_m g_{m,\ell}e^{-j\psi_{m,\ell}}\right|}{\sum_m\left|g_{m,\ell}\right|}$$

Try both signs. Whichever produces substantially higher coherence is your convention.

Each complex rail sample can be pictured as an arrow whose length is magnitude and whose direction is phase. Before focusing the arrows point in different directions. Phase compensation rotates them into alignment. $\eta$ measures how efficiently they add.

Two pieces of spatial information live in the phase-history shape. The horizontal location of the phase minimum contains cross-range information about $x_t$, and the curvature contains downrange information about $z_t$. In Run C the minimum sits toward the negative side of the rail, which is the first hint that the dominant scattering center is not exactly at $x=0$.

## 4.9 Path B continued: backprojection

Treat every candidate image pixel as a hypothesis. *If a scatterer were here, what complex measurement should it have produced at every rail position?*

For each rail position $m$:

1. **Predict distance.** $R_m(x,z)=\sqrt{(x-x_m)^2+z^2}$ for the whole pixel grid at once.
2. **Convert to fractional bin.** $\hat q_m=q_\text{ref}+\dfrac{R_m-R_\text{reg}}{\Delta R_\text{bin}}$
3. **Interpolate the complex profile.** For $\hat q=22.35$, that is $0.65\,G[22]+0.35\,G[23]$. Interpolation must be on the complex values, never on magnitude.
4. **Compute relative range.** $R_m-R_\text{center}$, which removes a phase common to all positions for that pixel and does not change the final magnitude.
5. **Remove predicted phase.** Multiply by $\exp\!\left(-j\,s\,4\pi(R_m-R_\text{center})/\lambda\right)$ with $s$ the measured sign.
6. **Weight and accumulate.**

$$I_\text{BP}(x,z)=\sum_m a_m\,G_m\!\left[\hat q_m(x,z)\right]\exp\!\left[-j\frac{4\pi}{\lambda}\left(R_m-R_\text{center}\right)\right]$$

Magnitude or power is taken only after the coherent sum.

Two companion products come free:

**Noncoherent accumulation.** Same predicted ranges and same interpolation, but magnitude is taken before summing. This uses the range geometry but discards aperture phase, so it cannot produce cross-range focusing. Comparing it to the coherent image shows exactly how much spatial concentration phase compensation bought you.

$$I_\text{NC}(x,z)=\sum_m a_m\left|G_m\!\left[\hat q_m(x,z)\right]\right|$$

**Per-pixel focusing coherence.** $\eta(x,z)=\left|I_\text{BP}\right|/I_\text{NC}$. High values mean the phase model for that pixel aligns the measurements efficiently. A weak noise-dominated pixel can score high by chance, so the coherence map is masked wherever the focused image is more than 25 dB below its peak. Masked pixels render black, which means "not interpreted," not "zero."

**Support counting.** The function counts how many rail positions supplied a valid interpolated sample to each pixel, and the code asserts that every displayed pixel used all 17. Uneven support across the image would introduce artificial brightness variation.

**Implementation note.** The first teaching notebook's `backproject` loops over every pixel and every position in Python, roughly 800,000 scalar interpolation calls. The real notebook vectorizes with `np.meshgrid` and processes the entire image grid per position, looping only over the 17 rail positions. Use the vectorized version.

### Local range registration

Because the measured target sits at q=22 rather than the geometrically expected q≈18, the image formation needs an anchor. The registration assigns the observed bin to the independently measured distance:

$$q_\text{ref}=22\quad\longleftrightarrow\quad R_\text{reg}\approx0.84\text{ m}$$

This is a one-point mapping for image formation only. It is not a radar range calibration, it does not explain the offset, and it does not validate the absolute range scale.

**The practical consequence: the focused downrange result of 0.84 m proves nothing, because it was forced by the registration.** Only the cross-range result is an independent measurement.

## 4.10 Range oversampling

The first backprojection reported a downrange −3 dB width of 1.85 cm, which is narrower than a single 4.69 cm range bin and therefore not physically credible.

The cause is linear interpolation between sparsely sampled complex FFT bins. Neighboring complex bins can have substantially different phases, and a linear combination of two phasors pointing in different directions can pass near zero. That carves artificial nulls immediately above and below the peak and makes the central response look falsely sharp.

The fix is zero-padding the range FFT from 128 to 1024 points.

$$X_K[q']=\sum_{i=0}^{N-1}w_R[i]x[i]e^{-j2\pi q'i/K},\qquad K=1024$$

Grid spacing drops from 46.875 mm to 5.859 mm. **This adds no bandwidth and no physical resolution.** It samples the existing range response more densely so that interpolation is faithful.

The distinction is worth stating plainly. Physical resolution describes whether two nearby targets can be separated. FFT grid spacing describes how densely the existing response is represented numerically. Only more transmitted bandwidth changes the former.

After oversampling, the downrange width became 7.05 cm, about 1.5 original bins, which is physically sensible for a Hann-windowed response. Everything else stayed put. Target at equivalent bin 22.000, cross-range peak within 1 mm, focusing coherence 0.9607 to 0.9521.

To keep the range grids matched, **Run B must be reprocessed with the same FFT size as Run C** before subtraction.

## 4.11 Window selection, both dimensions

Two windows act on two different data axes with two different effects.

| Weighting | Axis | Controls |
|---|---|---|
| Range window | Fast-time sample $i$ | Downrange main lobe and range sidelobes |
| Doppler window | Chirp index $n$ | Doppler point-spread function |
| Aperture window | Rail position $m$ | Cross-range main lobe and cross-range sidelobes |

### Range window comparison

Ideal properties, computed from the window coefficients alone:

| Window | Ideal −3 dB (bins) | Null-to-null | Peak sidelobe | ENBW (bins) |
|---|---|---|---|---|
| Rectangular | 0.873 | 2 | −13.4 dB | 1.000 |
| Hamming | 1.303 | 4 | −42.6 dB | 1.371 |
| Hann | 1.445 | 4 | −31.5 dB | 1.512 |
| Blackman | 1.649 | 6 | −58.3 dB | 1.740 |

Measured on the SAR image:

| Window | Unfocused range width | Focused downrange width | Cross-range width |
|---|---|---|---|
| Rectangular | 4.54 cm | 4.48 cm | 1.7245 cm |
| Hamming | 6.69 cm | 6.53 cm | 1.7204 cm |
| Hann | 7.30 cm | 7.05 cm | 1.7195 cm |
| Blackman | 8.36 cm | 8.04 cm | 1.7213 cm |

**Hamming is selected.** It is 0.52 cm narrower than Hann with a lower ideal first sidelobe, lower equivalent noise bandwidth, and essentially identical focusing coherence and background correlation.

Two observations. First, the cross-range widths are identical to within 0.005 cm across all four windows, which confirms the two dimensions are independently controlled. Second, beyond about q=24 the three tapered-window curves converge, which means the residual energy out there is *not* dominated by window sidelobes. If it were, it would drop substantially going from Hamming to Hann to Blackman. It is more likely multipath, extended-target scattering, or background residual.

### Aperture window comparison

Ideal, for the actual 17-position near-field geometry:

| Window | Ideal −3 dB | Ideal peak sidelobe | Noise penalty |
|---|---|---|---|
| Uniform | 1.723 cm | −13.13 dB | 0.00 dB |
| Hamming | 2.630 cm | −39.71 dB | 1.53 dB |
| Hann | 2.971 cm | −31.36 dB | 2.02 dB |

Measured:

| Window | Peak $x$ | Peak $z$ | Coherence | Cross-range | Max outside main lobe | Downrange |
|---|---|---|---|---|---|---|
| Uniform | −0.6 cm | 84.0 cm | 0.9520 | 1.720 cm | −10.89 dB | 6.528 cm |
| Hamming | −0.6 cm | 83.4 cm | 0.9752 | 2.559 cm | −20.60 dB | 6.504 cm |
| Hann | −0.6 cm | 83.4 cm | 0.9832 | 2.825 cm | −19.50 dB | 6.499 cm |

**Hamming is selected.** It buys 9.7 dB of sidelobe suppression for 0.84 cm of main-lobe broadening and 1.53 dB of noise penalty.

The noise penalty for unit-sum weights is $G_\text{noise}=M\sum_m a_m^2$, with uniform weighting minimizing it.

Three notes. The downrange width is unchanged across all three, confirming that aperture weighting acts only along cross-range. The peak position is stable at −0.6 cm, confirming tapering changes the point-spread shape without moving the target. And the rising focusing coherence does **not** mean tapering adds information, it means the retained weighted samples align more efficiently because the edge samples with greater model mismatch have been down-weighted. Coherence alone should not pick the window.

The measured 9.7 dB improvement is smaller than the ideal prediction, again because the out-of-main-lobe response is not purely window sidelobes.

---

# Part V — What the Data Actually Showed

## 5.1 FPGA versus Python agreement

The Python RADC path and the FPGA RFFT path place stationary energy at the same Doppler bin, $p=32$, and show corresponding responses at range bins $q\approx1, 22, 27, 31, 41$.

That single comparison validates a remarkable number of things at once: the RADC fast-time axis is decoded correctly, the range FFT is on the right axis, the RFFT payload reshape is correct, RFFT axis 0 is range, RFFT axis 1 is Doppler, the FPGA Doppler spectrum is centered, and the frame pairing by stream index is reasonable.

The FPGA responses are broader with smoother sidelobes than rectangular-window Python, which means the FPGA applies a taper. Hann matched best of the three tested. Remaining differences are attributable to fixed-point arithmetic, scaling, quantization, and zero suppression inside the FPGA.

The range-azimuth maps from both paths also agree in main lobes, nulls, and sidelobe pattern, which additionally confirms the RFFT channel ordering matches RADC.

## 5.2 Coherence results

Everything passed, and comfortably.

**Run A frames, q=22.** Magnitude varies by about 0.01 dB across five frames. Phase stays within about 0.3 degrees of the first frame. Both processing paths agree.

**Run A frames, q=18.** Noticeably less stable, with a −0.4 dB and −5 degree excursion at frame 2 in the Python path and a corresponding −0.2 dB and −3.5 degree change in the FPGA path. Because the same excursion appears in both paths, it is in the measured data rather than the processing. The greater stability at q=22 is consistent with its stronger signal.

**Run B background, all positions.** Median frame coherence above 0.9997 per channel. Reduced coherence around bins 12 to 16 occurs in a weak part of the spectrum and is a signal-to-noise effect, not instability.

**Runs B and C across the aperture.** Median frame coherence above 0.99999 for both runs and every channel.

**Run A to Run B cross-run.** Complex correlations 0.996 to 0.9999. Alignment magnitudes 1.025 to 1.036, phases −0.9 to −1.4 degrees.

**Run B to Run C cross-run.** Alignment magnitudes within about ±0.1 dB across the rail, worst case −0.32 dB. Unwrapped alignment phase spans across the whole aperture of 1.37, 1.19, 0.61, and 0.58 degrees for RX 0 through 3. Minimum complex correlation 0.988, medians 0.993 to 0.9995.

All of this means the radar held a highly consistent complex reference across runs, and coherent averaging plus matched complex subtraction are fully justified.

## 5.3 Background subtraction performance

Reference-region power reduction:

| RX | Run A vs Run B (pos 8) | Runs B/C across rail (median) |
|---|---|---|
| 0 | 19.5 dB | 18.6 dB |
| 1 | 23.9 dB | 24.3 dB |
| 2 | 27.3 dB | 27.8 dB |
| 3 | 28.0 dB | 29.8 dB |

The strong near-range coupling at $q\approx0$ is almost entirely removed, which is the clearest confirmation that the alignment and subtraction work. RX 2 and RX 3 give the best suppression, which is part of why RX 3 was eventually selected.

## 5.4 Phase sign determination

Aperture focusing coherence at $x_t=0$, $z_t=0.84$ m, tested at q=22:

| RX | Sign −1 | Sign +1 |
|---|---|---|
| 0 | 0.356 | 0.604 |
| 1 | 0.340 | 0.653 |
| 2 | 0.316 | 0.764 |
| 3 | 0.277 | 0.792 |

Median 0.328 versus 0.709. The +1 model wins on every channel.

So the measured propagation phase follows $\psi_m=+\dfrac{4\pi}{\lambda}\Delta R_m$, and the focusing correction is the conjugate, $\exp\!\left(-j\dfrac{4\pi}{\lambda}\Delta R_m\right)$.

The consistent preference across all four channels is itself evidence that the q=22 residual contains a real position-dependent phase history rather than random subtraction residue.

RX 3 was selected on the basis of the best focusing coherence (0.792), the lowest RMS phase error (50.2 degrees), and the highest target-to-reference level (14.96 dB).

The roughly 50 degree residual phase error is the signal that $x=0$ is not quite the right target location, which is exactly what backprojection then goes and searches for.

Also worth noting: the largest predicted phase excursion was about 250 degrees rather than the 218 degrees you get from the rail alone, because the individual RX element offsets extend the outer phase centers slightly beyond ±5 cm.

## 5.5 The q=22 anomaly

This is the one genuinely unresolved result and you will inherit it.

The sphere was measured at approximately 0.84 m slant range. Under the nominal 6 m over 128 bins mapping, that corresponds to

$$q_\text{expected}=\frac{0.84}{6/128}\approx18$$

The dominant sphere-associated response sits at **q = 22**, which nominally reads as

$$R_\text{nominal}=22\times0.046875=1.031\text{ m}$$

A discrepancy of about 19 cm, or four range bins.

**What has been ruled out:**

- Not the Python FFT, because the FPGA independently places it at the same bin
- Not the window choice, because it survives rectangular, Hamming, Hann, and Blackman unchanged
- Not the beamformer, because beamforming combines RX channels independently at each range bin and never mixes range bins
- Not ordinary stationary clutter, because it survives matched complex background subtraction in both Run A and Run C
- Not SAR processing, because it is present in the unfocused data before any focusing
- Not range interpolation, because the 1024-point oversampled processing puts it at equivalent bin 22.000

**What remains possible:**

- A fixed internal delay or range-bin offset in the radar
- An inaccurate range-scale assumption
- Sphere-induced multipath
- A stronger delayed scattering path

A single-point measurement cannot separate these, which is why the notebook correctly refuses to apply a one-point correction and uses local registration instead.

Given that the response survives subtraction of the matched no-target background and appears in two independent target-present runs, it is associated with the sphere or with multipath introduced by the sphere, not with ordinary room clutter.

## 5.6 Final Run C image measurements

Using the frozen pipeline:

| Measurement | Value |
|---|---|
| RX channel | 3 |
| Phase sign | +1 measured, conjugate applied |
| Peak cross-range | −0.6 cm |
| Peak downrange | 83.4 cm |
| Center-aperture range bin | 22.001 |
| Peak focusing coherence | 0.9752 |
| Cross-range −3 dB width | 2.559 cm |
| Downrange −3 dB width | 6.504 cm |
| Max response outside cross-range main lobe | −20.60 dB |
| Ideal $\lambda R/2L$ | 2.06 cm |
| Ideal uniform $0.443\lambda R/L$ | 1.83 cm |

The evidence that focusing actually worked, in order of strength:

1. Focusing coherence rose from 0.792 at the assumed point to 0.961 at the searched peak. Backprojection *found* a better location, it was not told one.
2. The measured uniform-weight cross-range width of 1.72 cm matches the ideal 1.83 cm closely.
3. The focused peak remains tied to q=22, so it is the same physical response seen in Run A and in the unfocused data.
4. The coherent image is dramatically more localized than the noncoherent accumulation of the same data.
5. The cross-range peak at −0.6 cm matches the asymmetry independently visible in the phase-history plots.

The downrange peak shifting from 84.0 to 83.4 cm between uniform and tapered weighting is about 6 mm, one 1024-point grid interval, inside a 6.5 cm wide response, on an axis anchored by a one-point registration. Not significant.

**Interpretation caveat.** The bright region is the point-spread response of the sphere's dominant scattering center, not an optical outline of the sphere. Its size is set by bandwidth, aperture length, windowing, geometry, and the target's own scattering behavior. A radar image is scattering strength convolved with the point-spread function.

---

# Part VI — The Frozen Pipeline (Runnable Reference)

## 6.1 Acquisition checklist

1. Mount radar at 0.315 m. Level rail.
2. Record center encoder count and full count range.
3. Place sphere at boresight. Measure slant range. Record diameter.
4. Capture Run A at center position, 5 frames.
5. Remove sphere.
6. Capture Run B, 17 positions, 20 frames each, logging encoder counts.
7. Replace sphere at $x=0$. Measure.
8. Capture Run C, same 17 positions, 20 frames each.
9. Displace sphere in cross-range. Measure displacement.
10. Capture Run D, same 17 positions, 20 frames each.
11. Change nothing between steps 5 and 10.

## 6.2 Processing steps

1. Build `FILE_MANIFEST` from directory scan and filename position parsing.
2. Build `RECORD_MANIFEST` by scanning every `.bin` for records.
3. Validate both manifests. Fail loudly.
4. Build rail position table from encoder counts.
5. Load RADC stacks for the runs needed.
6. Select RX channel 3.
7. Apply Hamming window across fast time.
8. Compute 1024-point zero-padded range FFT.
9. Apply Hann window across chirps.
10. Extract zero-Doppler bin.
11. Compute frame coherence. Confirm near 1.
12. Coherently average frames within each position.
13. Estimate complex alignment coefficient per position, reference bins 1–50 excluding 15–26, minimum level −35 dB.
14. Subtract aligned background while complex.
15. Locate target peak in residual, search window equivalent bins 19–26.
16. Register target peak to 0.84 m reference range.
17. Build image grid, $x$ from −10 to +10 cm at 1 mm, $z$ from 70 to 105 cm at 2 mm.
18. Apply Hamming aperture weights across 17 positions, normalized to unit sum.
19. For each position: predict $R_m$ per pixel, convert to fractional bin, interpolate complex, phase-correct with $\exp(-j4\pi\Delta R/\lambda)$, weight, accumulate.
20. Assert full 17-position support on every pixel.
21. Convert to normalized power in dB.
22. Locate peak, measure −3 dB widths, report focusing coherence.

## 6.3 Validation gates

Do not proceed past a failed gate.

| Gate | Where | Pass criterion |
|---|---|---|
| Parser lands on file size | Record scan | Exact match |
| Stream frame indices consecutive | Manifest validation | 0 through N−1 |
| DONE counters consecutive | Manifest validation | All diffs equal 1 |
| Array shapes and finiteness | Stack validation | Shape matches, all finite |
| Python vs FPGA range-Doppler | Run A section 2.4 | Same peak locations, zero Doppler at 32 |
| Frame coherence | Before averaging | Near 1.0 |
| Cross-run correlation | Before subtraction | Above ~0.99 |
| Background suppression | After subtraction | Near-range coupling gone, ~20 dB reference reduction |
| Phase sign preference | Section 3.3 | One sign clearly dominant across all channels |
| Aperture support | After backprojection | All pixels use all 17 positions |
| Downrange width plausible | After backprojection | Not narrower than one range bin |

---

# Part VII — Function Reference

Grouped by what they do, with the file they came from.

### Binary parsing and loading

| Function | Purpose |
|---|---|
| `parse_sar_position_index` | Extract position index from `scan_[pos]Ncm.bin` |
| `scan_vmd3_bin` | Walk one file, return one row per record |
| `read_record_payload` | Seek and read one payload |
| `decode_radc_2d` | Payload to (128, 64, 4) complex, Q-then-I |
| `decode_rfft_2d` | Payload to (128, 64, 4) complex |
| `decode_done` | Payload to frame counter int |
| `_select_stream_records` | Filter and order manifest rows by run, stream, position |
| `load_radc_stack` | Frames to (frame, sample, chirp, channel) |
| `load_rfft_stack` | Frames to (frame, range, doppler, channel) |
| `load_done_values` | Frames to counter array |
| `load_sar_radc_run` | All positions to (position, frame, sample, chirp, channel) |
| `build_sar_position_table` | Encoder counts to physical rail coordinates |

### Validation

| Function | Purpose |
|---|---|
| `validate_complex_stack` | Shape, dtype, finiteness, zero fraction |
| `validate_record_manifest` | Counts, consecutiveness, payload lengths, DONE continuity |
| `validate_sar_radc_run` | Multi-position shapes, DONE, per-position summary table |

### Core signal processing

| Function | Purpose |
|---|---|
| `create_window` | Rectangular, Hann, Hamming, Blackman |
| `compute_radc_range_fft` | Windowed range FFT along fast time |
| `compute_radc_range_doppler` | Range FFT then Doppler FFT with fftshift |
| `extract_zero_doppler` | Take centered Doppler bin |
| `normalized_magnitude_db` | Normalize to peak, convert to dB, apply floor |
| `normalized_power_db` | Same in power |
| `process_sar_radc_to_zero_doppler` | Multi-position, all channels |
| `process_single_rx_sar_with_oversampled_range_fft` | One channel, zero-padded, direct chirp sum |
| `calculate_sar_frame_coherence` | Per position, range, channel |
| `calculate_single_rx_frame_coherence` | Single-channel version |
| `coherently_average_sar_frames` | Complex mean over frames |

### Background subtraction

| Function | Purpose |
|---|---|
| `align_and_subtract_sar_background` | Per position and channel alignment and subtraction |
| `align_and_subtract_single_rx_background` | Single-channel version for oversampled data |

### Beamforming

| Function | Purpose |
|---|---|
| `conventional_range_azimuth` | Steering matrix and RX sum |
| `weighted_conventional_range_azimuth` | With real aperture amplitude weights |
| `create_normalized_aperture_weights` | Unit-sum RX weights |
| `calculate_aperture_noise_penalty` | $M\sum a_m^2$ in dB |
| `form_ideal_array_power_profile` | Theoretical array factor |
| `analyze_rx_phase_progression` | Linear fit across elements, angle estimate, spatial coherence |
| `form_angular_power_profile` | Noncoherent power over selected range bins |
| `measure_angular_mainlobe` | Peak angle and contiguous −3 dB width |

### SAR

| Function | Purpose |
|---|---|
| `evaluate_sar_aperture_phase_history` | Measured vs predicted phase, both signs, coherence |
| `backproject_single_rx` | Coherent image, noncoherent image, coherence map, support count |
| `create_synthetic_aperture_weights` | Uniform, Hamming, Hann over positions |
| `simulate_ideal_near_field_aperture_response` | Ideal point-target response for actual geometry |
| `characterize_ideal_range_window` | Ideal spectrum, widths, sidelobe, ENBW, coherent gain |
| `characterize_mainlobe_and_outside_response` | Width plus max outside main lobe |
| `measure_contiguous_minus_3db_width` | Interpolated crossings around the peak |
| `measure_range_mainlobe` | Range-domain version |
| `calculate_map_peak_to_background_contrast` | Peak vs 95th-percentile background |

### Plotting and comparison

`plot_run_c_processing_evolution`, `form_minimal_center_position_range_azimuth`, `extract_sar_image_db`, `get_existing_notebook_variable`.

---

# Part VIII — Traps, Lessons, and Debugging

**A suspiciously good number is a bug signal.** The 1.85 cm downrange width was better than the theoretical range resolution, which is impossible. Chasing it down produced the single most useful diagnostic result in the project. When a measurement beats physics, you have an artifact.

**Magnitude will not show you the hyperbola.** At 1.5 mm of range migration inside a 4.7 cm bin, there is nothing to see. Do not conclude the data is bad from a flat B-scan.

**Keep the complex data.** Every time you take `abs()` you have thrown away the thing SAR runs on. Subtraction, averaging, and interpolation all happen while complex. Magnitude is the very last operation.

**Q comes before I in the payload.** Get this backwards and you get a conjugated signal that will decode, validate, plot, and be wrong.

**Interpolate complex, never magnitude.** Linear interpolation of magnitude discards the phase you need. Linear interpolation of sparse complex bins introduces artificial nulls, which is why you zero-pad first.

**Never coherently combine RX channels before understanding their relative phase.** Noncoherent power summing is safe for diagnostics.

**Complex background subtraction must be earned.** It requires phase coherence between two separate acquisitions. Check the alignment coefficients and correlations first. The workflow is: compare magnitude profiles, check DONE continuity and timing, evaluate phase stability, try noncoherent first, use complex only once repeatability is demonstrated.

**Exclude the target from its own background estimate.** The reference mask exists for this reason.

**The phase sign is a coin flip on real data.** It is unambiguous in theory and determined by the mixer and FFT conventions in practice. Test both and keep the parameter in your production code.

**Distinguish "the image put it there" from "the image found it there."** Downrange 0.84 m was forced by registration. Cross-range −0.6 cm was discovered by search. Only the second is a measurement.

**A visually smoother image is not a better-resolved image.** Tapering redistributes energy into a broader main lobe. Hann on four elements looks cleanest and throws away half the array.

**Display scaling changes nothing about the data.** Section 2.11.4 shows the same image at 50 dB log, 25 dB log, and linear. The linear version looks cleanest and conveys the least. Use log for analysis.

**Equal stream frame indices are not proof of hardware synchronization.** The guide grades pairing confidence as high, moderate, or low. You are at moderate. Do not assume exact hardware pairing across Runs B through D.

**Do not hard-code position counts, step sizes, or a centered aperture.** Derive from the manifest. The correct values changed from 11 positions at 1 cm to 17 at 6.25 mm between documents, and the code that derived them survived.

**Separate ideal from measured.** The notebooks consistently compute the theoretical window or array response alongside the measured one. When they agree, your geometry model is right. When they disagree, the difference is physics you have not modeled, such as multipath or extended-target scattering.

---

# Part IX — Open Items and Next Steps

## 9.1 Run D, the validation that has not happened yet

The notebook stops at section 3.8. Section 4.0 does not exist, and it is the whole point of the experiment.

Run C alone proves that a coherent sum concentrates energy somewhere. Run D proves the reconstruction tracks a physically moved target. That is the difference between a demo and a result.

**The rule, stated in 3.8.3 and worth following exactly: apply the frozen configuration to Run D without retuning anything.** Same RX channel, same windows, same FFT size, same phase sign, same aperture weights, same image grid, same registration approach. If you tune on Run D, you have nothing.

**Procedure:**

1. Load Run D RADC across all 17 positions. Validate shapes and DONE continuity.
2. Confirm Run B and Run D encoder counts match Run C exactly.
3. Process with the frozen pipeline, estimating Run B to Run D alignment coefficients fresh per position.
4. Locate the Run D residual target range bin. Expect it at or very near q=22.
5. Register to the same 0.84 m reference, since the sphere was moved in cross-range and not in range.
6. Backproject with identical settings.
7. Compare the Run C and Run D focused peak positions.

**Two things to expect.** First, the Run C peak is at −0.6 cm, not zero, so the Run D peak should land near −0.6 cm plus the displacement, not at the displacement itself. The *difference* between the two peaks is the measurement. Second, at 2.56 cm cross-range width, a displacement of a few centimeters is resolvable but not by an enormous margin. Expect distinguishable rather than dramatic.

**Before running it,** confirm the actual Run D displacement from the lab notes. The earliest notebook says approximately +3 cm but nothing in the real notebook confirms it.

If Run D validates, you have a working rail-SAR system and a result worth writing up.

## 9.2 Resolving the range offset

This is the highest-value short experiment available.

Measure the sphere at two or more known slant ranges and observe how the offset behaves.

- Constant offset in meters across ranges implies a fixed internal delay or timing error
- Offset scaling with range implies a range-scale error
- Erratic behavior implies multipath or a target-dependent effect

That distinction determines whether a general correction is even possible. Until then the local registration stands, and any downrange number in an image should be labeled nominal and uncalibrated.

## 9.3 Multi-RX SAR

The current reconstruction uses one RX channel treated as a translated monostatic element. Using all four requires the exact bistatic path:

$$L_{m,\ell}(x,z)=R_{\text{TX},m}(x,z)+R_{\text{RX},m,\ell}(x,z)$$

That needs the transmitter's coordinate inside the module, which is not currently available. Request the antenna phase-center geometry from the vendor or measure it.

There are three viable approaches, in increasing sophistication: model each RX phase center separately, model the full bistatic geometry, or reconstruct each channel independently and combine the images coherently afterward.

Expected gain is roughly 6 dB of SNR from four channels plus a slight effective aperture extension from the element offsets. Do it only after Run D validates the single-channel result.

## 9.4 Other open items

**Verify the 10 cm aperture length** against the Galil encoder specification. This scales your entire cross-range axis.

**Sphere diameter** is still flagged provisional across all four documents. You need it for any RCS or resolution argument. Go measure the actual sphere.

**Absolute angle sign** is unverified. The Run A target sat about 2 degrees off boresight, which is far too close to determine left from right. Place a reflector deliberately off to one side and confirm the peak lands on the correct side of the map.

**RX amplitude imbalance.** Channel magnitudes at q=22 were −4.27, −3.58, −3.44, and 0.00 dB relative to RX 3. Spread of about 4.3 dB. This changes the effective aperture weighting and makes sidelobes asymmetric. The notebook correctly declines to derive a correction from the sphere measurement, since that would fit the calibration to one target and its multipath. Use an independent reference target at known range and angle.

**RX phase calibration** was judged unjustified. Spatial coherence was already 0.9966 and the phase-fit RMS error only 5 degrees. A phase-only correction derived from this target would risk fitting the target rather than a general channel error.

**Run A frame count discrepancy.** The narrative says approximately 20 frames but the validator expects 5 and section 2.7 processes 5. Confirm against your lab notes and fix the prose.

**3-D mode** is not implemented. Adding it needs more than a shape change. It requires virtual-channel ordering, TX to RX mapping, azimuth and elevation element positions, TDM-MIMO phase compensation, channel calibration, 3-D beamforming, and confirmation of the 3-D FPGA RFFT layout.

---

# Part X — Corrections Table

The earlier documents are stale in specific places. When building the template, trust the real notebook.

| Item | Stale value | Correct value |
|---|---|---|
| Positions | 11 at 1 cm spacing | 17 at 6.25 mm spacing |
| Center position index | 5 | 8 |
| Carrier frequency | 60 GHz | 61 GHz |
| Wavelength | 5.00 mm | 4.914 mm |
| Data layout | Includes a beam axis | No beam axis, angles formed in software |
| `BEAM_ANGLES_DEG` | Hardware steering angles | A software angle grid you choose |
| RFFT axis 1 | Provisional `slow_time_index` | Doppler bin, zero at 32 |
| Run A frames | About 20 | 5, verify against notes |
| Range FFT size | 128 | 1024 zero-padded |
| Phase sign | Free parameter, try both | Measured +1, conjugate applied |
| Range window | Hann | Hamming |
| Aperture weighting | Uniform (conclusion from 4-element case) | Hamming for 17 positions |
| Fast-time mean removal | Default True | Default False |
| Grating lobe limit | ±10.4 cm (at 1 cm spacing) | ±16.5 cm (at 6.25 mm) |
| Unfocused limit $L_u$ | 4.5 cm (at 60 GHz) | 4.54 cm (at 61 GHz) |
| Background subtraction | Start with power difference | Complex with per-position alignment, validated |
| Backprojection loop | Triple Python loop | Vectorized over pixel grid |
| I/Q ordering | Unspecified | Q first, then I |

---

# Part XI — Refactor and Template Roadmap

The generalization guide advised not refactoring until the RFFT layout, range-FFT convention, angle convention, and SAR processing were understood. **That condition is now satisfied for mode 0.** The refactor is appropriate after Run D validates.

## Stage 1 — Complete mode 0

Resolved: FPGA RFFT memory layout, RFFT second axis meaning, range FFT convention, angle processing convention, SAR processing. Remaining: range-axis calibration, absolute angle sign, Run D validation.

## Stage 2 — Move hard-coded values into configuration

```python
RADAR_CONFIG = {
    "name": "vmd3_2d_mode_0",
    "rset": 0,
    "dimensionality": "2d",
    "num_samples": 128,
    "num_chirps": 64,
    "num_channels": 4,
    "radc_frame_shape": (128, 64, 4),
    "radc_payload_bytes": 131_072,
    "rfft_frame_shape": (128, 64, 4),
    "rfft_payload_bytes": 131_072,
    "range_bin_spacing_m": 0.046875,
    "carrier_frequency_hz": 61.0e9,
    "rx_element_spacing_m": 2.464e-3,
}

DATASET_CONFIG = {
    "dataset_name": "20260709_vmd3_sar",
    "runs": {
        "A": {"role": "fixed_target",    "uses_positions": False, "frames": 5},
        "B": {"role": "background",      "uses_positions": True,  "frames": 20},
        "C": {"role": "target_centered", "uses_positions": True,  "frames": 20},
        "D": {"role": "target_offset",   "uses_positions": True,  "frames": 20},
    },
}

PROCESSING_CONFIG = {
    "range_window": "hamming",
    "doppler_window": "hann",
    "range_fft_size": 1024,
    "remove_fast_time_mean": False,
    "apply_fftshift_doppler": True,
    "angle_grid_deg": np.linspace(-70, 70, 281),
    "background_method": "complex",
    "aperture_window": "hamming",
    "sar_rx_channel": 3,
    "measured_phase_sign": +1,
}

GEOMETRY_CONFIG = {
    "target_slant_range_m": 0.84,
    "target_cross_range_m": 0.0,
    "radar_height_m": 0.315,
    "center_encoder_count": 400_000,
    "aperture_length_m": 0.10,
}
```

Run names must not be assumed to be A, B, C, D. A future experiment might use `single`, `background`, `target`.

Derive counts from the data, never hard-code:

```python
N_POSITIONS = len(position_coordinates_m)
CENTER_POSITION_INDEX = np.argmin(np.abs(position_coordinates_m))
```

## Stage 3 — Make loaders mode aware

Keep the record parser mode-independent. It reads stream code, payload length, payload, and nothing else. Only the decoders vary by mode.

```python
RADC_DECODERS = {"vmd3_2d_mode_0": decode_radc_2d}
RFFT_DECODERS = {"vmd3_2d_mode_0": decode_rfft_2d}

decoder = RADC_DECODERS[RADAR_CONFIG["name"]]
cube = decoder(payload)
```

Likely to change by mode: sample count, chirp count, physical or virtual channels, payload length, RADC memory layout, RFFT memory layout, range-bin spacing, speed-bin spacing, frame period, transmit sequencing, antenna geometry.

## Stage 4 — Create the template notebook

```
vmd3_processing_template.ipynb
    reusable setup
    configuration examples with placeholders
    validation cells
    reusable processing functions
    one single-position example workflow
    one N-position SAR example workflow
    one optional background-subtraction workflow
    3-D mode marked as future extension
    empty analysis sections
```

Replace experiment-specific paths, run names, and position counts with placeholders. Remove plots and conclusions from the current experiment.

## Stage 5 — Move stable functions to a module

Only after testing across more than one acquisition.

```
vmd3_processing.py
    binary parsing
    manifests
    decoders
    common processing functions

vmd3_experiment_<date>.ipynb
    configuration
    analysis
    plots
    interpretation
```

## Stage 6 — Add 3-D mode

Separate 3-D RADC decoder, 3-D RFFT decoder, virtual-array description, TDM-MIMO compensation, azimuth and elevation beamforming, 3-D visualization.

## Practical naming

Save the current working notebook as `vmd3_mode0_processing_WIP.ipynb` and fork the template from a copy once the experiment closes out.

## Function groups for the module

```
Range:      make_range_window, compute_range_fft, make_range_axis,
            extract_range_profile
Doppler:    make_slow_time_window, compute_doppler_fft, select_zero_doppler
Channels:   apply_channel_calibration, form_rx_vector, beamform_azimuth,
            make_angle_axis, make_range_azimuth_map
Background: estimate_background, subtract_background, compare_background_target
Phase:      extract_complex_range_bin, unwrap_phase_history,
            evaluate_phase_stability, apply_propagation_phase_correction
SAR:        make_image_grid, interpolate_complex_range_profile,
            backproject_single_rx, backproject_multi_rx
Plotting:   plot_iq_samples, plot_range_profile, plot_range_azimuth_map,
            plot_phase_history, plot_sar_image
```

Processing functions accept data and configuration as arguments. They must not silently depend on experiment-specific globals.

---

# Appendix A — Quick Number Reference

**Radar**

| Quantity | Value |
|---|---|
| Carrier | 61 GHz |
| Wavelength | 4.914 mm |
| Sample rate | 2 MHz |
| Samples per chirp | 128 |
| Chirp duration | 64 µs |
| Slope | ~5.0 × 10¹³ Hz/s |
| Bandwidth | ~3.2 GHz |
| Chirps per frame | 64 |
| RX channels | 4 |
| RX spacing | 2.464 mm |
| Range bin spacing | 46.875 mm |
| Range resolution | 46.9 mm |
| Unambiguous range | 6.0 m |

**Geometry**

| Quantity | Value |
|---|---|
| Rail positions | 17 |
| Position spacing | 6.25 mm |
| Aperture length | 10 cm (assumed) |
| Encoder range | 0 to 800,000, step 50,000 |
| Center index / count | 8 / 400,000 |
| Radar height | 0.315 m |
| Target slant range | 0.84 m |

**Derived**

| Quantity | Value |
|---|---|
| Cross-range resolution $\lambda R/2L$ | 2.06 cm |
| Uniform −3 dB $0.443\lambda R/L$ | 1.83 cm |
| Range migration, center to edge | 1.49 mm |
| Phase change over same | 218° |
| Phase change including RX offsets | ~250° |
| Alias-free half-extent | 16.5 cm |
| Unfocused aperture limit $L_u$ | 4.54 cm |
| Expected target bin from geometry | ~18 |
| Observed target bin | 22 |

**Results**

| Quantity | Value |
|---|---|
| Frame coherence, Runs B/C | > 0.99999 |
| Background suppression, RX 3 | 29.8 dB |
| Phase sign | +1 measured |
| Selected RX | 3 |
| Peak focusing coherence | 0.9752 |
| Focused peak | x = −0.6 cm, z = 83.4 cm |
| Cross-range width | 2.56 cm |
| Downrange width | 6.50 cm |
| Sidelobe suppression vs uniform | 9.7 dB |

**Data volumes**

| Quantity | Value |
|---|---|
| Bytes per RADC/RFFT record | 131,080 |
| Bytes per frame, all streams | 262,172 |
| Run A file | ~1.31 MB |
| Run B/C/D file | ~5.24 MB |
| One full run in memory (complex128) | ~178 MB |

---

# Appendix B — Formula Sheet

**FMCW range**

$$f_b=\frac{2SR}{c}=\frac{KL}{c_0},\qquad R=\frac{cf_b}{2S},\qquad \delta_R=\frac{c}{2B}$$

**Signal model**

$$x[n]=\alpha\exp\!\left(j2\pi f_b\frac{n}{f_s}\right)\exp\!\left(-j\frac{2\pi}{\lambda}L\right)$$

**Range FFT**

$$S[q,n]=\sum_{i=0}^{N-1}w_R[i]\,x[i,n]\,e^{-j2\pi qi/N}$$

**Zero-padded range FFT**

$$X_K[q']=\sum_{i=0}^{N-1}w_R[i]x[i]e^{-j2\pi q'i/K},\qquad K>N$$

**Doppler FFT**

$$D[q,p]=\sum_{n=0}^{M-1}w_D[n]\,S[q,n]\,e^{-j2\pi pn/M}$$

**Coherent frame average**

$$\overline{C}_m[q,\ell]=\frac{1}{F}\sum_{f=0}^{F-1}C^{(0)}_{m,f}[q,\ell]$$

**Frame coherence**

$$\gamma=\frac{\left|\sum_f x_f\right|}{\sum_f\left|x_f\right|}$$

**Complex correlation**

$$\rho=\frac{\left|\sum_q\overline C[q]\overline B^*[q]\right|}{\sqrt{\sum_q|\overline C[q]|^2\sum_q|\overline B[q]|^2}}$$

**Background alignment and subtraction**

$$\alpha_{m,\ell}=\frac{\sum_q\overline C_m[q,\ell]\overline B_m^*[q,\ell]}{\sum_q\left|\overline B_m[q,\ell]\right|^2},\qquad G_m=\overline C_m-\alpha_{m,\ell}\overline B_m$$

**Steering vector and beamforming**

$$v_\ell(\theta)=e^{-jkx_\ell\sin\theta},\qquad Y[q,\theta]=\sum_\ell X[q,\ell]v_\ell^*(\theta)$$

**Angle from phase slope**

$$\theta\approx\sin^{-1}\!\left(-\frac{1}{k}\frac{d\phi}{dx}\right)$$

**Spatial coherence**

$$C=\frac{\left|\sum_\ell X_\ell v_\ell^*(\hat\theta)\right|}{\sum_\ell|X_\ell|}$$

**Rail position from encoder**

$$x_m=\left(\text{count}_m-\text{count}_\text{center}\right)\times\frac{L}{\text{count span}}$$

**Range history**

$$R_m=\sqrt{(x_t-x_m)^2+z_t^2}\approx R_0+\frac{(x_m-x_t)^2}{2R_0}$$

**Aperture phase**

$$\psi_m=+\frac{4\pi}{\lambda}\left(R_m-R_\text{center}\right)$$

**Aperture focusing coherence**

$$\eta=\frac{\left|\sum_m g_m e^{-j\psi_m}\right|}{\sum_m|g_m|}$$

**Fractional range bin**

$$\hat q_m(x,z)=q_\text{ref}+\frac{R_m(x,z)-R_\text{reg}}{\Delta R_\text{bin}}$$

**Complex interpolation**

$$G(\hat q)=(1-f)G[\lfloor \hat q\rfloor]+fG[\lfloor \hat q\rfloor+1],\qquad f=\hat q-\lfloor \hat q\rfloor$$

**Backprojection**

$$I_\text{BP}(x,z)=\sum_m a_m\,G_m\!\left[\hat q_m(x,z)\right]\exp\!\left[-j\frac{4\pi}{\lambda}\left(R_m-R_\text{center}\right)\right]$$

**Noncoherent comparison**

$$I_\text{NC}(x,z)=\sum_m a_m\left|G_m\!\left[\hat q_m(x,z)\right]\right|$$

**Per-pixel focusing coherence**

$$\eta(x,z)=\frac{\left|I_\text{BP}(x,z)\right|}{I_\text{NC}(x,z)}$$

**Resolutions and limits**

$$\delta_x\approx\frac{\lambda R}{2L},\qquad \Delta x_{-3\text{dB}}\approx0.443\frac{\lambda R}{L}$$

$$|x|_{\max}\approx\frac{\lambda R}{4\Delta x},\qquad L_u\approx\sqrt{\frac{R\lambda}{2}}$$

**Window metrics**

$$\text{coherent gain}=\frac{1}{N}\sum_i w[i],\qquad \text{ENBW}=\frac{N\sum_i w[i]^2}{\left(\sum_i w[i]\right)^2}$$

**Aperture noise penalty (unit-sum weights)**

$$G_\text{noise}=M\sum_m a_m^2,\qquad L_\text{noise}=10\log_{10}G_\text{noise}$$

**Normalized display**

$$P_\text{dB}=10\log_{10}\!\left(\frac{P}{\max P}\right)$$

---

If you want, the natural next artifact is a Run D section written against the frozen configuration so you can drop it into the notebook and run it. Just say the word and tell me the actual displacement from your notes.
