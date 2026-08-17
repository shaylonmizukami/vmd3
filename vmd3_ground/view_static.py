"""
view_static.py — V-MD3 live viewer for a STATIC down-looking scene.

No recording. Just connects to the radar and shows a live GUI:
    - range-angle heatmap (the main display)
    - beamformed time-domain plot
    - beamformed frequency-domain plot
    - BF angle selector + peak angle/range readout

Point the radar (mounted high, tilted toward the floor) at your objects and
watch whether they show up as distinct bright spots above the floor return.

Usage:
    python view_static.py
    python view_static.py --rsetMode 0
"""

import argparse
import math
import os
import signal
import sys
import threading
from collections import deque
from datetime import datetime

import numpy as np
from lib.QtWidgets.HeatmapWidget import HeatmapWidget
from lib.QtWidgets.QDropdown import QDropdown
from lib.QtWidgets.XYPlotWidget import XYPlotWidget
from lib.vmd3 import VMD3, RdotConfig
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# ─── Configuration ───────────────────────────────────────────────
RSET_CONFIG = 0         # 2D, 6m max range, 4.69cm range bin
TIME_STEP = 0.13        # Seconds between frames (~7.7 Hz)
MAX_ANGLE_RANGE = 67    # Degrees, V-MD3 azimuth FOV
MAX_RANGE_M = 6         # Mode 0 max range
DEFAULT_BF_ANGLE = 0    # Degrees off boresight for time/freq plots
# ─────────────────────────────────────────────────────────────────


# ─── Globals ─────────────────────────────────────────────────────
vmd3 = None
vmd3_thread = None
vmd3_thread_running = True
app = None

frame_times = deque(maxlen=100)
bf_slow_time_samples = []
bf_angle = DEFAULT_BF_ANGLE
# ─────────────────────────────────────────────────────────────────


_sigint_count = 0


def handle_sigint(signum, frame):
    global vmd3_thread_running, _sigint_count
    _sigint_count += 1
    if _sigint_count == 1:
        print('\n[view] Ctrl+C received, shutting down...')
        vmd3_thread_running = False
        if app is not None:
            app.quit()
    else:
        print('\n[view] Second Ctrl+C, forcing exit.')
        os._exit(1)


signal.signal(signal.SIGINT, handle_sigint)


def process_time_domain(slow_time_samples):
    """Complex slow-time samples → magnitude with DC removal."""
    data_complex = np.array([np.mean(row) for row in slow_time_samples])
    data = [np.abs(x) for x in data_complex]
    if len(data) > 0:
        data_mean = sum(data) / len(data)
        data = [x - data_mean for x in data]
    time_length = len(data) * TIME_STEP
    time_interval = np.arange(TIME_STEP, time_length + TIME_STEP, TIME_STEP)
    if len(time_interval) != len(data):
        time_interval = time_interval[:len(data)]
    return time_interval, data


def process_freq_domain(data):
    """FFT of the slow-time magnitude data."""
    sample_freq = 1 / TIME_STEP
    data = list(data)
    if len(data) > 1:
        data = data[1:]
    data = data + [0] * 256
    num_samples = len(data)
    if num_samples == 0:
        return np.array([0]), np.array([0])
    fft = abs(np.fft.fft(data))
    y_fft = fft[:num_samples // 2 + 1]
    x_fft = sample_freq * np.arange(0, num_samples // 2 + 1) / num_samples
    return x_fft, y_fft


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('V-MD3 Static Viewer')
        self.setGeometry(100, 100, 1400, 900)

        # ─── Plots ────────────────────────────────────────────
        self.range_angle = HeatmapWidget(
            title='Range-Angle Heatmap',
            xLabel='Angle', xUnit='deg',
            yLabel='Range', yUnit='m',
            yTickLimits=[0, MAX_RANGE_M],
            xTickLimits=[-MAX_ANGLE_RANGE, MAX_ANGLE_RANGE],
        )
        self.bf_time_domain = XYPlotWidget(
            title='Beamformed Time Domain',
            xLabel='Time', xUnit='s', yLabel='Amplitude',
        )
        self.bf_freq_domain = XYPlotWidget(
            title='Beamformed Frequency Domain',
            xLabel='Frequency', xUnit='Hz', yLabel='Magnitude',
        )

        # ─── Control panel ────────────────────────────────────
        self.frameRateLabel = QLabel('Frame rate: -- Hz')
        self.peakAngleLabel = QLabel('Peak angle: -- deg')
        self.peakRangeLabel = QLabel('Peak range: -- m')

        global bf_angle
        self.bf_angle_selection = QDropdown(
            label='BF Angle:',
            defaultIndex=(bf_angle + MAX_ANGLE_RANGE),
            onChange=self.bfAngleChanged,
        )
        for i in range(-MAX_ANGLE_RANGE, MAX_ANGLE_RANGE + 1):
            self.bf_angle_selection.addItem(f'{i}')

        self.resetBfButton = QPushButton('Reset BF Plots')
        self.resetBfButton.clicked.connect(self.resetBfPlots)

        controlLayout = QVBoxLayout()
        controlLayout.addWidget(self.frameRateLabel)
        controlLayout.addWidget(self.peakAngleLabel)
        controlLayout.addWidget(self.peakRangeLabel)
        controlLayout.addSpacing(10)
        controlLayout.addWidget(self.bf_angle_selection)
        controlLayout.addWidget(self.resetBfButton)
        controlLayout.addStretch()

        controlWidget = QWidget()
        controlWidget.setLayout(controlLayout)
        controlWidget.setFixedWidth(280)

        # ─── Layout ───────────────────────────────────────────
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        layout = QGridLayout(central_widget)
        layout.addWidget(self.range_angle,    0, 0, 2, 1)
        layout.addWidget(self.bf_time_domain,  0, 1)
        layout.addWidget(self.bf_freq_domain,  1, 1)
        layout.addWidget(controlWidget,        0, 2, 2, 1)

        self.statusTimer = QTimer()
        self.statusTimer.timeout.connect(self.updateStatusLabels)
        self.statusTimer.start(200)

    def bfAngleChanged(self, index):
        global bf_angle
        bf_angle = index - MAX_ANGLE_RANGE

    def resetBfPlots(self):
        global bf_slow_time_samples
        bf_slow_time_samples = []

    def updateStatusLabels(self):
        if len(frame_times) > 1:
            avg_dt_ms = np.mean(frame_times)
            if avg_dt_ms > 0:
                self.frameRateLabel.setText(
                    f'Frame rate: {1000.0 / avg_dt_ms:.1f} Hz'
                )

    def setRangeAngleHeatmap(self, data):
        self.range_angle.setData(data)

    def setBfTimeDomain(self, x, y):
        self.bf_time_domain.set_plot(x, y)

    def setBfFreqDomain(self, x, y):
        self.bf_freq_domain.set_plot(x, y)

    def setPeakLabels(self, angle_deg, range_m):
        self.peakAngleLabel.setText(f'Peak angle: {angle_deg:+.1f} deg')
        self.peakRangeLabel.setText(f'Peak range: {range_m:.2f} m')

    def closeEvent(self, event):
        global vmd3_thread_running
        vmd3_thread_running = False
        event.accept()


def radar_thread_fn(window):
    global bf_slow_time_samples
    previous_time = datetime.now()

    while vmd3_thread_running:
        try:
            frame = vmd3.read_frame(b'RADC')
        except Exception as e:
            if not vmd3_thread_running:
                break
            err_str = str(e).lower()
            if 'timed out' not in err_str and 'timeout' not in err_str:
                print(f'[radar_thread] read_frame error: {e}')
            continue

        current_time = datetime.now()
        dt_ms = (current_time - previous_time).total_seconds() * 1000
        previous_time = current_time
        frame_times.append(dt_ms)

        # Decode
        payload = frame[8:]
        cube = vmd3.decode_radc_2d(payload)
        if cube is None:
            cube = vmd3.decode_radc_3d(payload)
        if cube is None:
            continue

        # Range / Doppler / Angle FFT
        fft_range = np.fft.fft(cube, axis=0)
        fft_doppler = np.fft.fftshift(np.fft.fft(fft_range, axis=1), axes=1)
        fft_angle = np.fft.fftshift(
            np.fft.fft(fft_doppler, n=128, axis=2), axes=2
        )

        # Range-angle heatmap
        range_angle = np.sum(np.abs(fft_angle), axis=1)
        range_angle = np.squeeze(range_angle)
        max_val = np.max(range_angle)
        if max_val > 0:
            range_angle = range_angle / max_val
        range_angle = range_angle.T   # angle × range for the widget
        window.setRangeAngleHeatmap(range_angle)

        # Peak readout
        peak_idx = np.unravel_index(np.argmax(range_angle), range_angle.shape)
        n_angle_bins, n_range_bins = range_angle.shape
        peak_angle_deg = (
            -MAX_ANGLE_RANGE
            + 2 * MAX_ANGLE_RANGE * peak_idx[0] / max(n_angle_bins - 1, 1)
        )
        peak_range_m = MAX_RANGE_M * peak_idx[1] / max(n_range_bins - 1, 1)
        window.setPeakLabels(peak_angle_deg, peak_range_m)

        # Beamform at the selected angle for time/freq plots
        nRx = cube.shape[2]
        alpha = bf_angle
        wBF = np.array([
            complex(
                math.cos(-math.pi * n * math.sin(math.radians(alpha))),
                math.sin(-math.pi * n * math.sin(math.radians(alpha))),
            )
            for n in range(nRx)
        ])
        bf_result = np.matmul(fft_range, wBF)
        bf_chirp_avg = np.mean(bf_result, axis=1)
        bf_slow_time_samples.append(bf_chirp_avg)
        if len(bf_slow_time_samples) > 256:
            bf_slow_time_samples = bf_slow_time_samples[-256:]

        x_td, y_td = process_time_domain(bf_slow_time_samples)
        window.setBfTimeDomain(x_td, y_td[:len(x_td)])
        x_fd, y_fd = process_freq_domain(y_td)
        window.setBfFreqDomain(x_fd, y_fd)


def main(rset_config):
    global vmd3, vmd3_thread, app

    print('[view] Connecting to V-MD3 at 192.168.100.201...')
    vmd3 = VMD3()
    vmd3.connect()
    vmd3.set_rset_config(rset_config)
    vmd3.set_output_config([RdotConfig.RADC])
    vmd3.sockUDP.settimeout(1.0)
    print(f'[view] RSET={rset_config}, ready')

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    vmd3_thread = threading.Thread(
        target=radar_thread_fn, args=(window,), daemon=True
    )
    vmd3_thread.start()

    exit_code = app.exec()

    print('[view] Shutting down...')
    global vmd3_thread_running
    vmd3_thread_running = False
    vmd3_thread.join(timeout=1.5)

    try:
        vmd3.sockTCP.settimeout(2.0)
        vmd3.disconnect()
    except Exception as e:
        print(f'[view] disconnect warning: {e}')
        try:
            vmd3.sockTCP.close()
        except Exception:
            pass
        try:
            vmd3.sockUDP.close()
        except Exception:
            pass

    print('[view] Done.')
    os._exit(exit_code)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='V-MD3 live viewer for a static down-looking scene'
    )
    parser.add_argument(
        '--rsetMode', type=int, default=RSET_CONFIG,
        help=f'RSET value 0-8 (default: {RSET_CONFIG} — 2D, 6m, 4.69cm bin)'
    )
    args = parser.parse_args()
    main(args.rsetMode)