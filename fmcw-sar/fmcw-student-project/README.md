# Radar Final Project Package

This package contains two balanced project options.

## Project A: Dual-Frequency CW Displacement Calibration

- Uses the original measured 2.4 GHz and 24 GHz mover CSV files without modification.
- Emphasizes real I/Q imbalance, ellipse-based calibration, circle fitting, DC-offset removal, arctangent phase demodulation, displacement recovery, and frequency sensitivity.
- The heavy calibration functions are supplied in the student notebook; students must apply them correctly and interpret each result.

## Project B: FMCW Range-Gated Physiological Sensing

- Uses a synthetic complex dechirped FMCW array with shape `(6000 chirps, 128 fast-time samples)`.
- Emphasizes fast versus slow time, fast-time windowing, range FFT processing, target-bin selection, preservation of complex phase, physiological displacement, spectral estimates, and filtering.
- The filter helper is supplied; students implement and explain the central FMCW processing chain.

## Folder structure

- `data/`: student data files.
- `student/`: guided notebooks with TODO code cells and required Markdown analysis prompts.
- `instructor/`: complete executable solution notebooks.
- `project_briefs/`: traditional LaTeX source and compiled one-page PDFs.

## Submission and presentation balance

The completed notebook is the full technical submission and should contain code, figures, tables, and written analysis. The presentation should emphasize the processing chain, quantitative results, comparison, and limitations rather than repeat every notebook response.

## Phase terminology used in both projects

1. `atan2(Q, I)` or `angle(z)` produces wrapped phase in radians.
2. `unwrap(...)` produces continuous phase in radians.
3. Multiplication by `lambda/(4*pi)` converts monostatic phase change to displacement.
