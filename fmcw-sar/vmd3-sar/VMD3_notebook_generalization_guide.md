# Generalizing the V-MD3 Processing Notebook

## Purpose

This document describes how to convert the current V-MD3 experiment notebook into a reusable processing template for future acquisitions.

The template should support common V-MD3 workflows such as:

- single-position acquisitions;
- repeated-frame measurements at one position;
- rail-SAR acquisitions with an arbitrary number of positions;
- background or subtraction datasets;
- one-dimensional range profiles;
- range–azimuth heatmaps;
- coherent phase analysis;
- SAR image formation;
- future radar modes beyond the current mode-0 configuration.

The immediate priority is to generalize the existing **2-D mode-0** workflow without overcomplicating it. Three-dimensional scanning and 3-D virtual-array processing can be added later as a separate extension.

---

## 1. Design Goals

The generalized notebook should:

1. Use one reusable setup section for all experiments.
2. Separate radar configuration from experiment configuration.
3. Support both single-position and multi-position acquisitions.
4. Permit any number of captures per acquisition file.
5. Support optional background or subtraction datasets.
6. Load large datasets only when needed.
7. Preserve raw complex data and metadata.
8. Avoid assuming that RADC, RFFT, and DONE records always arrive in strict repeating order.
9. Keep binary decoding separate from signal processing.
10. Make the processing path explicit and reproducible.
11. Allow experiment-specific plotting and imaging choices without modifying the low-level loaders.
12. Provide clear validation checks before any interpretation of the radar data.

---

## 2. Recommended Notebook Architecture

A reusable notebook should be organized into the following major sections.

### 2.1 Configuration

This section defines:

- repository and data paths;
- radar mode;
- dataset organization;
- acquisition positions;
- background and target datasets;
- expected target geometry;
- processing parameters;
- plotting limits.

### 2.2 File and Record Indexing

This section:

- discovers binary files;
- builds the file-level manifest;
- parses the records inside each binary file;
- builds the record-level manifest;
- validates file counts, stream counts, payload lengths, and DONE continuity.

### 2.3 Binary Decoding

This section defines reusable functions for:

- RADC decoding;
- RFFT decoding;
- DONE decoding;
- stack construction;
- shape validation.

### 2.4 Common Radar Processing

This section defines reusable functions for:

- range FFT;
- Doppler FFT;
- windowing;
- DC removal;
- complex normalization;
- range-axis construction;
- channel selection;
- frame selection;
- beamforming;
- range–azimuth map construction;
- background subtraction;
- phase extraction;
- SAR backprojection.

### 2.5 Experiment-Specific Analysis

This section contains the actual analysis for the current experiment, such as:

- fixed-position validation;
- target-versus-background comparison;
- centered-target SAR;
- offset-target SAR;
- multi-target imaging;
- repeatability tests.

The experiment-specific section should call reusable functions rather than duplicate processing code.

---

## 3. Separate Radar Configuration from Dataset Configuration

The most important generalization is to distinguish:

1. **Radar-mode properties**
2. **Dataset organization**
3. **Experiment-specific geometry and processing**

These should not be mixed into one large collection of global constants.

---

## 4. Radar-Mode Configuration

The current notebook assumes V-MD3 mode 0:

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
}
```

The generalized notebook should pass this configuration to mode-dependent functions rather than relying on hard-coded values inside every decoder.

For example:

```python
def decode_radc(payload: bytes, radar_config: dict) -> np.ndarray:
    ...
```

or, preferably, select the appropriate decoder through a registry:

```python
RADC_DECODERS = {
    "vmd3_2d_mode_0": decode_radc_2d_mode_0,
}
```

Then:

```python
decoder = RADC_DECODERS[RADAR_CONFIG["name"]]
cube = decoder(payload)
```

This makes it easier to add another V-MD3 mode without rewriting the manifest or file-handling logic.

---

## 5. Future Radar Modes

The binary-record parser should remain mode independent.

The following parts are likely to change by radar mode:

- number of ADC samples;
- number of chirps;
- number of physical or virtual channels;
- payload length;
- RADC memory layout;
- RFFT memory layout;
- range-bin spacing;
- speed-bin spacing;
- frame period;
- transmit sequencing;
- antenna-array geometry.

For example, the existing V-MD3 3-D RADC decoder indicates a shape of:

```text
(128 samples, 32 chirps, 12 virtual channels)
```

with payload size:

```text
196,608 bytes
```

However, 3-D mode should be added only after the 2-D mode-0 RFFT convention is understood.

The future 3-D extension will require more than a shape change. It will also require:

- virtual-channel ordering;
- transmitter–receiver mapping;
- azimuth and elevation element positions;
- TDM-MIMO phase compensation;
- channel calibration;
- 3-D beamforming;
- confirmation of the 3-D FPGA RFFT layout.

---

## 6. Dataset Configuration

The dataset configuration should describe how the experiment is organized without embedding that information in the binary decoder.

A recommended structure is:

```python
DATASET_CONFIG = {
    "dataset_name": "20260709_vmd3_sar",
    "runs": {
        "A": {
            "role": "fixed_target",
            "directory": RUN_DIRS["a"],
            "uses_positions": False,
        },
        "B": {
            "role": "background",
            "directory": RUN_DIRS["b"],
            "uses_positions": True,
        },
        "C": {
            "role": "target_centered",
            "directory": RUN_DIRS["c"],
            "uses_positions": True,
        },
        "D": {
            "role": "target_offset",
            "directory": RUN_DIRS["d"],
            "uses_positions": True,
        },
    },
}
```

The notebook should not assume that the run names must always be `A`, `B`, `C`, and `D`.

A future experiment could instead use:

```python
DATASET_CONFIG = {
    "runs": {
        "single": {...},
        "background": {...},
        "target": {...},
    }
}
```

---

## 7. Supporting Single-Position and N-Position Acquisitions

The generalized notebook should support two broad acquisition types.

### 7.1 Single-position acquisition

Examples:

- repeated-frame phase stability;
- static target range profile;
- range–azimuth heatmap;
- human motion or respiration measurement;
- calibration target measurement.

Representation:

```python
position_coordinates_m = np.array([0.0])
```

The loader should still return stacks with a consistent frame-first layout:

```text
RADC: (frame, sample, chirp, channel)
RFFT: (frame, range_bin, slow_time_index, channel)
```

### 7.2 Multi-position acquisition

Examples:

- SAR;
- synthetic-aperture calibration;
- target localization;
- background scan;
- repeat scans.

Representation:

```python
position_indices = np.arange(N)
position_coordinates_m = ...
```

Do not hard-code:

```python
N = 17
center_position_index = 8
```

Instead derive them from the dataset:

```python
N_POSITIONS = len(position_coordinates_m)
CENTER_POSITION_INDEX = np.argmin(
    np.abs(position_coordinates_m)
)
```

The SAR processing should operate on arbitrary position coordinates:

```python
x_positions_m
```

rather than on filename labels or assumed one-centimeter increments.

---

## 8. Position Metadata

Each acquisition file should carry or be associated with:

- position index;
- commanded encoder count;
- measured encoder count, when available;
- physical position in meters;
- center reference;
- acquisition direction;
- timestamp, when available.

A useful position table is:

```text
run
position_index
encoder_count
position_m
filename
```

Physical positions should be computed once and stored in the file manifest.

For example:

```python
position_m = (
    encoder_count - center_encoder_count
) * meters_per_encoder_count
```

The SAR algorithm should use `position_m`, not the filename.

---

## 9. Background and Subtraction Data

Many future experiments may include background or subtraction datasets.

The notebook should distinguish between:

- no background data;
- noncoherent magnitude subtraction;
- power subtraction;
- complex subtraction;
- background normalization.

A recommended dataset-role configuration is:

```python
PROCESSING_CONFIG = {
    "background_run": "B",
    "target_run": "C",
    "background_method": "none",
}
```

Possible values:

```text
none
magnitude
power
complex
```

Complex subtraction should not be used automatically. It is valid only when phase is sufficiently repeatable between the background and target acquisitions.

Recommended workflow:

1. Compare background and target magnitude profiles.
2. Check DONE continuity and acquisition timing.
3. Evaluate phase stability at representative range bins.
4. Use noncoherent subtraction first.
5. Use complex subtraction only if repeatability is demonstrated.

Background subtraction should be implemented as a reusable function:

```python
def subtract_background(
    target,
    background,
    method="none",
):
    ...
```

---

## 10. File-Level Manifest

The file-level manifest should remain generic.

Recommended columns:

```text
dataset_name
run
role
acquisition_type
position_index
encoder_count
position_m
filename
path
file_size_bytes
```

The manifest should not assume a specific run count or position count.

Validation should verify:

- all configured directories exist;
- all expected files were found;
- no duplicate position indices exist within a position-based run;
- position indices are consistent with configured metadata;
- file sizes are nonzero;
- naming patterns were parsed successfully.

Expected file counts should come from configuration rather than from hard-coded values.

---

## 11. Record-Level Manifest

The record-level manifest should continue to contain:

```text
run
role
position_index
position_m
filename
path
record_index
stream
stream_frame_index
header_offset
payload_offset
payload_length
frame_length
done_value
```

The record parser should remain independent of radar mode whenever possible.

It should read:

```text
4-byte stream code
4-byte payload length
payload
```

The validator should:

- verify known stream identifiers;
- verify that payloads remain inside file boundaries;
- count each stream independently;
- verify stream-frame indices;
- verify payload lengths against the active radar configuration;
- verify DONE continuity when possible.

It should not require strict repeated:

```text
RADC → RFFT → DONE
```

ordering because UDP arrival order may vary.

---

## 12. Stream Pairing

Do not assume that equal `stream_frame_index` values always represent perfectly hardware-synchronized RADC and RFFT frames.

Pairing confidence can be classified as:

```text
high confidence:
RADC, RFFT, and DONE are stored in a clear repeated pattern

moderate confidence:
stream counts match and DONE counters are continuous, but arrival order varies

low confidence:
records are missing, counters jump, or stream counts differ
```

For future acquisition code, improve pairing by recording a shared frame identifier or timestamp for each stream if the V-MD3 interface exposes one.

Until then:

- use stream-frame pairing only when supported by stored order;
- compare robust features before requiring exact complex equality;
- do not assume Run B–D stream-frame indices are exact hardware pairs.

---

## 13. Standard Data Shapes

Use consistent frame-first stack conventions.

### RADC

One frame:

```text
(sample, chirp, channel)
```

Stack:

```text
(frame, sample, chirp, channel)
```

### FPGA RFFT

One frame:

```text
(range_bin, slow_time_index, channel)
```

Stack:

```text
(frame, range_bin, slow_time_index, channel)
```

The term `slow_time_index` remains provisional until the FPGA RFFT convention is fully confirmed.

### Multi-position data

Avoid automatically loading all positions into one large array.

Preferred access:

```python
stack = load_radc_stack(
    record_manifest,
    run="C",
    position_index=8,
)
```

For SAR, iterate through positions or load a selected frame from each position.

A future lazy-access interface could use:

```python
dataset.load(
    run="C",
    stream="radc",
    position_index=8,
)
```

---

## 14. Common Processing Functions

The reusable template should eventually include the following function groups.

### Range processing

```python
make_range_window(...)
remove_fast_time_mean(...)
compute_range_fft(...)
make_range_axis(...)
extract_range_profile(...)
```

### Slow-time and Doppler processing

```python
make_slow_time_window(...)
compute_doppler_fft(...)
make_velocity_axis(...)
select_zero_doppler(...)
```

### Channel and angle processing

```python
apply_channel_calibration(...)
form_rx_vector(...)
beamform_azimuth(...)
make_angle_axis(...)
make_range_azimuth_map(...)
```

### Background processing

```python
estimate_background(...)
subtract_background(...)
compare_background_target(...)
```

### Phase analysis

```python
extract_complex_range_bin(...)
unwrap_phase_history(...)
evaluate_phase_stability(...)
apply_propagation_phase_correction(...)
```

### SAR processing

```python
make_image_grid(...)
interpolate_complex_range_profile(...)
backproject_single_rx(...)
backproject_multi_rx(...)
```

### Plotting

```python
plot_iq_samples(...)
plot_range_profile(...)
plot_range_azimuth_map(...)
plot_phase_history(...)
plot_sar_image(...)
```

Processing functions should accept data and configuration values as arguments. They should not silently depend on experiment-specific global variables.

---

## 15. Processing Configuration

A reusable processing configuration may look like:

```python
PROCESSING_CONFIG = {
    "range_window": "hann",
    "remove_fast_time_mean": False,
    "doppler_window": "hann",
    "apply_fftshift_doppler": True,
    "angle_grid_deg": np.linspace(-70, 70, 281),
    "background_method": "none",
    "initial_rx_channel": 0,
}
```

The notebook should print the active configuration near the beginning of each analysis section.

---

## 16. Experiment Geometry Configuration

Experiment-specific geometry should be isolated:

```python
GEOMETRY_CONFIG = {
    "target_slant_range_m": 0.84,
    "target_cross_range_m": 0.0,
    "target_height_m": 0.0,
    "radar_height_m": 0.315,
    "center_encoder_count": 400_000,
    "meters_per_encoder_count": ...,
}
```

Future experiments can update this section without touching the binary parser.

---

## 17. Range Profiles

The range-profile workflow should support:

- one frame;
- one chirp;
- one channel;
- averaging over chirps;
- noncoherent integration;
- coherent integration;
- averaging over frames;
- background comparison.

Functions should clearly distinguish:

```text
single-chirp range FFT
chirp-averaged magnitude profile
coherently averaged complex profile
Doppler-selected range profile
```

These are not interchangeable.

---

## 18. Range–Azimuth Heatmaps

The template should support range–azimuth maps from:

1. RADC-derived range data;
2. FPGA RFFT data;
3. selected slow-time or Doppler indices;
4. one frame or averaged frames;
5. one target dataset or background-subtracted data.

The angle-processing implementation must document:

- RX element spacing;
- wavelength;
- channel order;
- sign convention;
- steering-vector convention;
- beamforming normalization;
- angle grid.

Do not average complex channels before beamforming.

---

## 19. SAR Processing

The SAR interface should support arbitrary position counts:

```python
sar_image = backproject(
    range_data=...,
    radar_positions_m=...,
    image_x_m=...,
    image_z_m=...,
    wavelength_m=...,
)
```

It should not assume:

- 17 positions;
- one-centimeter steps;
- a centered aperture;
- one specific target range;
- one background run.

Recommended initial SAR workflow:

1. One RX channel.
2. One selected frame per position.
3. Complex range profile.
4. Exact rail-position coordinates.
5. Interpolation in range.
6. Round-trip phase correction.
7. Coherent summation.
8. Background comparison.
9. Multi-RX extension after calibration.

---

## 20. Validation Philosophy

Every processing section should begin with a compact validation cell.

Recommended checks:

- array shape;
- frame count;
- finite values;
- exact-zero fraction;
- peak magnitude;
- expected index ranges;
- position count;
- position monotonicity;
- DONE continuity;
- selected frame and channel validity.

Validation functions should raise informative errors rather than silently returning malformed arrays.

---

## 21. Template versus Experiment Notebook

A useful long-term organization is:

```text
vmd3_template.ipynb
    reusable setup
    configuration examples
    reusable processing functions
    blank analysis sections

vmd3_experiment_<date>.ipynb
    imports or copies template functions
    defines one experiment
    contains experiment results
```

A more maintainable future option is:

```text
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

Do not refactor into a Python module until the current Run A RFFT format and processing conventions are understood. Prematurely moving uncertain logic into a shared module can make mistakes harder to identify.

---

## 22. Recommended Generalization Sequence

Generalize in stages.

### Stage 1 — Complete the current mode-0 notebook

Resolve:

- FPGA RFFT memory layout;
- FPGA RFFT second-axis meaning;
- range FFT convention;
- range-axis mapping;
- angle-processing convention;
- SAR processing.

### Stage 2 — Replace hard-coded experiment values

Move into configuration:

- run names;
- run roles;
- frame counts;
- number of positions;
- center index;
- encoder positions;
- target range;
- image limits.

### Stage 3 — Make loaders mode aware

Add:

```python
RADAR_CONFIG
decoder registry
payload-size registry
shape registry
```

### Stage 4 — Create a clean template notebook

Remove current experimental results while preserving:

- setup;
- configuration examples;
- validation;
- reusable functions;
- empty analysis sections.

### Stage 5 — Move stable functions to a Python module

Only after the functions have been tested across more than one acquisition.

### Stage 6 — Add 3-D mode

Add separate:

- 3-D RADC decoder;
- 3-D RFFT decoder;
- virtual-array description;
- TDM-MIMO compensation;
- azimuth/elevation beamforming;
- 3-D visualization.

---

## 23. Current Known Limitations

The current notebook still contains the following unresolved or experiment-specific points:

1. FPGA RFFT axis 1 is provisionally called `slow_time_index`.
2. The RFFT decoder is based on a candidate layout and still requires confirmation.
3. Exact cross-stream frame pairing is not guaranteed for all files.
4. Range-axis calibration still needs validation.
5. Angle-array geometry and sign convention still need validation.
6. The present radar configuration is mode 0 only.
7. Current file naming assumes `scan_0cm.bin` or `scan_posNcm.bin`.
8. Current position metadata use encoder counts supplied separately from the binary files.
9. 3-D mode is not yet implemented.
10. The current SAR processing is specific to a one-dimensional rail.

These limitations should be resolved or documented before treating the notebook as a finalized general-purpose tool.

---

## 24. Practical Recommendation

Save the current notebook as:

```text
vmd3_mode0_processing_WIP.ipynb
```

After the current experiment is complete, create a copy such as:

```text
vmd3_processing_template.ipynb
```

In the template copy:

- retain the reusable setup and processing functions;
- replace experiment-specific paths with placeholders;
- replace fixed run names with configuration examples;
- replace fixed position counts with arbitrary arrays;
- remove plots and conclusions from the current experiment;
- include one example single-position workflow;
- include one example N-position SAR workflow;
- include one optional background-subtraction workflow;
- leave 3-D mode marked as a future extension.

The existing notebook is a strong foundation for that template, but the RFFT and angle-processing conventions should be resolved before it is considered stable.
