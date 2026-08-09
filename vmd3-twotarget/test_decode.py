from vmd3lib.decode import get_frames, decode_radc_2d
from vmd3lib.analysis import range_profile, find_target_bins
import numpy as np

PATH = "data/radc/2026-06-02/plate_6m_1p6mm_0p2hz_rset1.bin"  # <-- your file

frames = get_frames(PATH)
print(f"{len(frames)} frames found")

cube = decode_radc_2d(frames[0])
print(f"cube shape: {cube.shape}, dtype: {cube.dtype}")
print(f"finite values: {np.isfinite(cube).all()}")
print(f"sample magnitude range: {np.abs(cube).min():.1f} to {np.abs(cube).max():.1f}")

prof = range_profile(decode_radc_2d(frames[1]))   # frame 1, skipping startup
bins = find_target_bins(prof, n_targets=1)
print(f"strongest bin: {bins}, range ~{bins[0] * 10/128:.2f} m")

# ---
from vmd3lib.displacement import (
    slow_time_signal, phase_to_displacement,
    displacement_spectrum, dominant_frequency,
)

cubes = np.stack([decode_radc_2d(f) for f in frames], axis=0)[1:]  # drop startup frame
sig = slow_time_signal(cubes, target_bin=79)
disp = phase_to_displacement(sig)
print(f"peak-to-peak displacement: {np.ptp(disp):.3f} mm  (expected ~1.6 mm)")

f, m = displacement_spectrum(disp)
print(f"dominant motion frequency: {dominant_frequency(f, m):.3f} Hz  (expected ~0.2 Hz)")