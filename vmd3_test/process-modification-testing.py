"""
vmd3_process_bin.py — Process VMD3 Raw Binary File
Original MATLAB author: Ethan Chee
Python port: maintains identical behavior to vmd3_process_bin_copy.m

Slow-time phase displacement extraction + I/Q diagnostics.

Usage:
    python vmd3_process_bin.py
    (edit the parameters at the top of main() as needed)
"""

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import detrend

plt.style.use('seaborn-v0_8-darkgrid')

# Optional manual tweaks for a more "true dark" look
plt.rcParams.update({
    'figure.facecolor': "#2E2E2E",
    'axes.facecolor': "#151515",
    'axes.edgecolor': '#cccccc',
    'axes.labelcolor': '#e0e0e0',
    'text.color': '#e0e0e0',
    'xtick.color': '#cccccc',
    'ytick.color': '#cccccc',
    'grid.color': "#3B3B3B",
    'grid.alpha': 0.7,
    'legend.frameon': True,              # actually draw the legend box
    'legend.facecolor': "#B6B6B6",     # legend box fill
    'legend.edgecolor': "#ffffff",     # legend box border
    'legend.labelcolor': "#ffffff",    # text color inside the legend
    'legend.framealpha': 0.9,            # transparency of the legend box (0–1)
    'legend.fancybox': True,             # rounded corners (vs. sharp rectangle)
    'legend.shadow': False,              # drop shadow under the legend (usually False in dark mode)
    'legend.fontsize': 10,               # text size in the legend
    'legend.title_fontsize': 11,         # if you ever use a legend title
})

# =====================================================================
# Changeable Parameters
# =====================================================================
BINARY_FILEPATH = (
    "/home/shaylon/repos/ALiSM_Python_copy/vmd3_test/data/radc/2026-05-26/"
    "plate_7p5m_1p6mm_0p2hz_rset1.bin"
)
CONFIG_MODE = "2D"    # "2D" or "3D"
MAX_RANGE = 10        # Meters
TRIM_FRAMES = 0       # Number of startup frames to discard

RAW_PLOT_MODE = 'chirp'   # 'chirp', 'frame', or 'dataset'
RAW_PLOT_FRAME = 0        # used by 'chirp' and 'frame' modes
RAW_PLOT_CHIRP_RANGE = None   # e.g. (0, 8) for chirps 0-7, or None for all
RAW_PLOT_CHIRP = 0        # used by 'chirp' mode only
RAW_PLOT_CHANNEL = 0    # 0..n_ch-1 for one channel, or None for all

# =====================================================================
# CONSTANTS: DO NOT EDIT
# =====================================================================
TIME_STEP = 0.13                  # seconds
SAMPLE_FREQ = 1.0 / TIME_STEP     # Hz
HEADER_TO_PROCESS = b'RADC'


# =====================================================================
# Helper functions
# =====================================================================
def get_frames(filepath, header, config_mode):
    """
    Read a .bin file and extract all valid RADC frame payloads.

    Mirrors the MATLAB get_frames() logic:
      - find every occurrence of the header bytes
      - read the 4-byte little-endian length that follows
      - keep only frames whose length matches the configured mode
      - reject frames whose payload accidentally contains the header
    """
    with open(filepath, 'rb') as f:
        raw_data = f.read()

    expected_len = 131072 if config_mode == "2D" else 196608
    header_len = len(header)
    frames = []

    # Find all header positions in the file
    start = 0
    while True:
        idx = raw_data.find(header, start)
        if idx == -1:
            break

        # Read the 4-byte payload length immediately after the header
        if idx + 8 > len(raw_data):
            break
        payload_length = int.from_bytes(
            raw_data[idx + 4:idx + 8], byteorder='little', signed=False
        )

        # Validate length against the configured mode
        if payload_length == expected_len:
            payload_start = idx + 8
            payload_end = payload_start + payload_length

            if payload_end <= len(raw_data):
                payload = raw_data[payload_start:payload_end]

                # Reject if the header sequence appears inside the payload
                if header not in payload:
                    frames.append(payload)

        # Advance past this header occurrence and continue searching
        start = idx + 1

    return frames


    """
    Decode a 2D-mode RADC payload into a complex cube.
    Output shape: (128 samples, 64 chirps, 4 channels)

    Byte layout (per sweep of 2048 bytes, 64 sweeps total):
      - 4 channel blocks of 512 bytes each
      - Within each block: Q at offsets 0,4,8,... and I at offsets 2,6,10,...
      - Each sample is int16 little-endian
    """
def decode_radc_2d(frame):
    if len(frame) != 131072:
        raise ValueError(f'INVALID FRAME LENGTH FOR 2D MODE: {len(frame)}')

    raw = np.frombuffer(frame, dtype='<i2')  # 65536 int16 values

    # Layout: 64 sweeps × 4 channels × 256 int16 per channel (Q,I interleaved)
    raw = raw.reshape(64, 4, 256)

    q_values = raw[:, :, 0::2]   # Q at even positions (offsets 0, 4, 8, ...)
    i_values = raw[:, :, 1::2]   # I at odd positions  (offsets 2, 6, 10, ...)

    complex_data = i_values.astype(np.float64) + 1j * q_values.astype(np.float64)
    # shape: (sweeps=64, channels=4, samples=128)

    cube = np.transpose(complex_data, (2, 0, 1))  # → (samples, chirps, channels)
    return cube


def decode_radc_3d(frame):
    """
    Decode a 3D-mode RADC payload into a complex cube.
    Output shape: (128 samples, 32 chirps, 12 channels)
    """
    if len(frame) != 196608:
        raise ValueError(f'INVALID FRAME LENGTH FOR 3D MODE: {len(frame)}')

    raw = np.frombuffer(frame, dtype='<i2')   # shape: (98304,)
    # 32 sweeps × 12 channels × 128 samples × 2 (I and Q)

    raw = raw.reshape(32, 12, 128, 2)
    q_values = raw[:, :, :, 0]
    i_values = raw[:, :, :, 1]

    complex_data = i_values.astype(np.float64) + 1j * q_values.astype(np.float64)
    cube = np.transpose(complex_data, (2, 0, 1))
    return cube


# =====================================================================
# Main processing
# =====================================================================
def main():
    # ---- Get all frames from binary with the matching header ----
    frames = get_frames(BINARY_FILEPATH, HEADER_TO_PROCESS, CONFIG_MODE)
    # frames = frames[99:101]  # Temporary... uncomment if you are impatient :)

    if not frames:
        raise RuntimeError('NO FRAMES FOUND')
    
    frames = frames[TRIM_FRAMES:]
    print(f'Trimmed first {TRIM_FRAMES} frames to skip startup transient.')

    n_frames = len(frames)
    slow_time_signal = np.zeros((n_frames, 4), dtype=np.complex128)  # was (n_frames,)
    target_range_bin = None  # picked from the first frame

    decode_fn = decode_radc_2d if CONFIG_MODE == "2D" else decode_radc_3d

    raw_cube_for_plot = None   # for 'chirp' / 'frame' modes
    raw_dataset = []           # for 'dataset' mode
    for i, frame in enumerate(frames):
        print(f'Processing Frame #{i+1}/{n_frames} ...', end='')

        cube = decode_fn(frame)

        if RAW_PLOT_MODE in ('chirp', 'frame') and i == RAW_PLOT_FRAME:
            raw_cube_for_plot = cube.copy()
        elif RAW_PLOT_MODE == 'dataset':
            raw_dataset.append(cube)

        # Range FFT along the samples (fast-time) axis
        # cube: (samples, chirps, channels) -> (range_bins, chirps, channels)
        fft_range = np.fft.fft(cube, axis=0)

        # Average magnitude across chirps and channels for a clean range profile
        range_profile = np.mean(np.abs(fft_range), axis=(1, 2))  # (range_bins,)

        # On the first frame, lock onto the target's range bin
        if target_range_bin is None:
            leakage_bins_to_skip = 10
            search_region = range_profile[leakage_bins_to_skip:]
            idx = int(np.argmax(search_region))
            target_range_bin = idx + leakage_bins_to_skip + 1  # +1 to match MATLAB's offset
            target_distance = (target_range_bin - 1) * MAX_RANGE / fft_range.shape[0]
            print(
                f'\n>> Target locked at range bin {target_range_bin} '
                f'({target_distance:.2f} m)'
            )

        # average over chirps only, keep channels
        complex_at_target = np.mean(
            fft_range[target_range_bin - 1, :, :], axis=0   # → shape (4,)
        )
        slow_time_signal[i, :] = complex_at_target

        print('Done!')

    # ---- Convert phase to displacement ----
    LAMBDA = 3e8 / 61.6e9   # wavelength at center frequency, ~4.87 mm
    phase_raw = np.angle(slow_time_signal)
    phase_unwrapped = np.unwrap(phase_raw)
    # Remove linear trend (residual range bin offset / slow drift)
    # phase_detrended = detrend(phase_unwrapped)
    displacement_mm = -phase_unwrapped * LAMBDA / (4 * np.pi) * 1000  # mm

    # ---- Time axis ----
    t = np.arange(n_frames) * TIME_STEP

    # # ---- Plot 1: Displacement vs time ----
    # plt.figure()
    # plt.plot(t, displacement_mm, linewidth=1.2)
    # plt.xlabel('Time (s)')
    # plt.ylabel('Displacement (mm)')
    # plt.title('Target displacement (from slow-time phase)')
    # plt.grid(True)

    # # ---- Plot 2: Magnitude vs time ----
    # plt.figure()
    # plt.plot(t, np.abs(slow_time_signal), linewidth=1.2)
    # plt.xlabel('Time (s)')
    # plt.ylabel('|s[n]|')
    # plt.title('Target reflection magnitude over time')
    # plt.grid(True)

    # ---- Plot 3: I and Q components vs time ----
    I_component = np.real(slow_time_signal)
    Q_component = np.imag(slow_time_signal)

    plt.figure()
    for ch in range(4):
        plt.plot(t, np.real(slow_time_signal[:, ch]),
                linewidth=1.0, label=f'I ch{ch}')
        plt.plot(t, np.imag(slow_time_signal[:, ch]),
                linewidth=1.0, linestyle='--', label=f'Q ch{ch}')
    plt.xlabel('Time (s)')
    plt.ylabel('Amplitude')
    plt.title('Slow-time I/Q per channel at target range bin')
    plt.legend(ncol=4, fontsize=8)
    plt.grid(True)

    # # ---- Plot 4: I/Q constellation ----
    # plt.figure()
    # plt.plot(I_component, Q_component, '-', linewidth=0.5, alpha=0.6)
    # plt.axis('equal')
    # plt.xlabel('I (real)')
    # plt.ylabel('Q (imag)')
    # plt.title('I/Q constellation at target range bin')
    # plt.grid(True)

    # # ---- Plot 5: FFT of displacement signal ----
    # N_pad = 4096
    # disp_fft = np.abs(
    #     np.fft.fft(displacement_mm - np.mean(displacement_mm), N_pad)
    # )
    # freqs = np.arange(N_pad) * SAMPLE_FREQ / N_pad
    # half = slice(0, N_pad // 2)

    # plt.figure()
    # plt.plot(freqs[half], disp_fft[half], linewidth=1.2)
    # plt.xlabel('Frequency (Hz)')
    # plt.ylabel('Magnitude')
    # plt.title('Displacement spectrum')
    # plt.xlim([0, 2])
    # plt.grid(True)

    # print(slow_time_signal[0])

    # ---- Plot 6: Raw I/Q (chirp / frame / dataset) ----
    n_ch = (raw_cube_for_plot.shape[2] if raw_cube_for_plot is not None
            else raw_dataset[0].shape[2])
    channels = range(n_ch) if RAW_PLOT_CHANNEL is None else [RAW_PLOT_CHANNEL]

    data = {}
    if RAW_PLOT_MODE == 'chirp':
        for ch in channels:
            data[ch] = raw_cube_for_plot[:, RAW_PLOT_CHIRP, ch]
        xlabel = 'Sample index (fast time)'
        title = f'Raw I/Q — frame {RAW_PLOT_FRAME}, chirp {RAW_PLOT_CHIRP}'

    elif RAW_PLOT_MODE == 'frame':
        if RAW_PLOT_CHIRP_RANGE is None:
            c0, c1 = 0, raw_cube_for_plot.shape[1]
        else:
            c0, c1 = RAW_PLOT_CHIRP_RANGE
        n_c = c1 - c0
        for ch in channels:
            data[ch] = raw_cube_for_plot[:, c0:c1, ch].T.reshape(-1)
        xlabel = 'Sample index (chirps concatenated)'
        title = f'Raw I/Q — frame {RAW_PLOT_FRAME}, chirps {c0}-{c1-1}'

    else:  # 'dataset'
        for ch in channels:
            per_frame = [c[:, :, ch].T.reshape(-1) for c in raw_dataset]
            data[ch] = np.concatenate(per_frame)
        xlabel = 'Sample index (entire dataset concatenated)'
        title = f'Raw I/Q — entire dataset ({len(raw_dataset)} frames)'

    plt.figure()
    for ch in channels:
        x = np.arange(data[ch].size)
        plt.plot(x, np.real(data[ch]), linewidth=1.0, label=f'I ch{ch}')
        plt.plot(x, np.imag(data[ch]), linewidth=1.0,
                 linestyle='--', label=f'Q ch{ch}')
    plt.xlabel(xlabel)
    plt.ylabel('ADC value')
    plt.title(title)
    plt.legend(ncol=2, fontsize=8)
    plt.grid(True)
    
    plt.show()


if __name__ == '__main__':
    main()