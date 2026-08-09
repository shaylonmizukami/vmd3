"""
measure.py — V-MD3 live measurement with discrete captures.

Continuous live GUI showing range-angle heatmap and beamformed time/frequency
plots. Click Start Capture to begin recording frames to a .bin file, click
Stop Capture to end. Each capture appends a row to scan_log.csv.

Usage:
    python measure.py
    python measure.py --sessionName morning
    python measure.py --rsetMode 0

Output structure:
    data/scan_YYYY-MM-DD[_sessionName]/
        scan_log.csv
        bins/
            scan_neg50cm.bin
            scan_neg40cm.bin
            ...

The .bin format is byte-identical to record.py output, so replay.py and
vmd3_process_bin.m can consume the files unchanged.
"""

from lib.vmd3 import VMD3, RdotConfig

import sys
import os
import signal
import argparse
import threading
import csv
from datetime import datetime
from collections import deque

import numpy as np
import math

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QGridLayout, QWidget, QPushButton,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox
)
from PyQt6.QtCore import Qt, QTimer

from lib.QtWidgets.HeatmapWidget import HeatmapWidget
from lib.QtWidgets.XYPlotWidget import XYPlotWidget
from lib.QtWidgets.QDropdown import QDropdown


# ─── Configuration ───────────────────────────────────────────────
RSET_CONFIG = 0         # 2D, 6m max range, 4.69cm range bin
TIME_STEP = 0.13        # Seconds between frames (radar frame rate ~7.7 Hz)
MAX_ANGLE_RANGE = 67    # Degrees, V-MD3 azimuth FOV
MAX_RANGE_M = 6         # Mode 0 max range

# Planned scan positions (cm). Negative = left of plate center, positive = right.
PLANNED_POSITIONS = [
    -50, -40, -30, -20, -15, -10, -8, -6, -4, -2,
      0,
     +2, +4, +6, +8, +10, +15, +20, +30, +40, +50,
]

# Default beamforming angle for the time/freq plots (degrees off boresight)
DEFAULT_BF_ANGLE = 0
# ─────────────────────────────────────────────────────────────────


# ─── Globals for the radar thread ────────────────────────────────
vmd3 = None
vmd3_thread = None
vmd3_thread_running = True
app = None

# Capture state — protected by capture_lock for thread safety
capture_lock = threading.Lock()
capturing = False
capture_file = None
capture_start_time = None
capture_n_frames = 0
capture_bytes_written = 0
capture_filename = None
capture_scan_pos = None
capture_notes = None

# Frame timing for live readout
frame_times = deque(maxlen=100)
total_frames_received = 0

# Slow-time samples for the beamformed time/freq plots
bf_slow_time_samples = []
bf_angle = DEFAULT_BF_ANGLE
# ─────────────────────────────────────────────────────────────────


_sigint_count = 0


def handle_sigint(signum, frame):
    """Ctrl+C handler — stop the radar thread and quit the GUI.

    First Ctrl+C: graceful shutdown.
    Second Ctrl+C: hard exit (in case cleanup is hung).
    """
    global vmd3_thread_running, _sigint_count
    _sigint_count += 1
    if _sigint_count == 1:
        print('\n[measure] Ctrl+C received, shutting down...')
        vmd3_thread_running = False
        if app is not None:
            app.quit()
    else:
        print('\n[measure] Second Ctrl+C, forcing exit.')
        os._exit(1)


signal.signal(signal.SIGINT, handle_sigint)


def process_time_domain(slow_time_samples):
    """Convert complex slow-time samples to magnitude with DC removal."""
    data_complex = np.array([np.mean(row) for row in slow_time_samples])
    data = [np.abs(x) for x in data_complex]

    # Remove DC offset
    if len(data) > 0:
        data_mean = sum(data) / len(data)
        data = [x - data_mean for x in data]

    # Time axis
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
        data = data[1:]   # First sample is often a transient

    # Zero pad for better frequency resolution
    data = data + [0] * 256

    num_samples = len(data)
    if num_samples == 0:
        return np.array([0]), np.array([0])
    fft = abs(np.fft.fft(data))
    y_fft = fft[:num_samples // 2 + 1]
    x_fft = sample_freq * np.arange(0, num_samples // 2 + 1) / num_samples
    return x_fft, y_fft


class MainWindow(QMainWindow):
    def __init__(self, output_dir, csv_path):
        super().__init__()
        self.output_dir = output_dir
        self.csv_path = csv_path

        self.setWindowTitle('V-MD3 Measurement')
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
            xLabel='Time', xUnit='s',
            yLabel='Amplitude',
        )
        self.bf_freq_domain = XYPlotWidget(
            title='Beamformed Frequency Domain',
            xLabel='Frequency', xUnit='Hz',
            yLabel='Magnitude',
        )

        # ─── Right-side control panel ─────────────────────────
        # Status labels
        self.frameRateLabel = QLabel('Frame rate: -- Hz')
        self.peakAngleLabel = QLabel('Peak angle: -- deg')
        self.peakRangeLabel = QLabel('Peak range: -- m')
        self.captureStatusLabel = QLabel('Status: idle')
        self.captureStatusLabel.setStyleSheet('font-weight: bold; color: gray;')

        # Beamforming angle selector (single, for time/freq plots)
        global bf_angle
        self.bf_angle_selection = QDropdown(
            label='BF Angle:',
            defaultIndex=(bf_angle + MAX_ANGLE_RANGE),
            onChange=self.bfAngleChanged,
        )
        for i in range(-MAX_ANGLE_RANGE, MAX_ANGLE_RANGE + 1):
            self.bf_angle_selection.addItem(f'{i}')

        # Position selector (dropdown + free-text override)
        self.posDropdown = QComboBox()
        self.posDropdown.addItem('-- pick planned position --')
        for p in PLANNED_POSITIONS:
            sign = '+' if p > 0 else ''
            self.posDropdown.addItem(f'{sign}{p} cm')
        self.posDropdown.currentIndexChanged.connect(self.posDropdownChanged)

        self.posTextField = QLineEdit()
        self.posTextField.setPlaceholderText('or type e.g. -12')

        posLayout = QHBoxLayout()
        posLayout.addWidget(QLabel('Position:'))
        posLayout.addWidget(self.posDropdown)
        posLayout.addWidget(self.posTextField)

        # Notes field
        self.notesField = QLineEdit()
        self.notesField.setPlaceholderText('Notes (optional)')

        # Start/Stop buttons
        self.startButton = QPushButton('Start Capture')
        self.startButton.setStyleSheet(
            'background-color: #2d6a4f; color: white; font-weight: bold; padding: 8px;'
        )
        self.startButton.clicked.connect(self.startCapture)

        self.stopButton = QPushButton('Stop Capture')
        self.stopButton.setStyleSheet(
            'background-color: #6c757d; color: white; font-weight: bold; padding: 8px;'
        )
        self.stopButton.clicked.connect(self.stopCapture)
        self.stopButton.setEnabled(False)

        # Reset BF data button
        self.resetBfButton = QPushButton('Reset BF Plots')
        self.resetBfButton.clicked.connect(self.resetBfPlots)

        # Output directory label
        self.outputDirLabel = QLabel(f'Output: {self.output_dir}')
        self.outputDirLabel.setWordWrap(True)
        self.outputDirLabel.setStyleSheet('color: #555; font-size: 10px;')

        # Assemble control panel
        controlLayout = QVBoxLayout()
        controlLayout.addWidget(self.frameRateLabel)
        controlLayout.addWidget(self.peakAngleLabel)
        controlLayout.addWidget(self.peakRangeLabel)
        controlLayout.addSpacing(10)
        controlLayout.addWidget(self.bf_angle_selection)
        controlLayout.addWidget(self.resetBfButton)
        controlLayout.addSpacing(20)
        controlLayout.addLayout(posLayout)
        controlLayout.addWidget(self.notesField)
        controlLayout.addWidget(self.startButton)
        controlLayout.addWidget(self.stopButton)
        controlLayout.addWidget(self.captureStatusLabel)
        controlLayout.addStretch()
        controlLayout.addWidget(self.outputDirLabel)

        controlWidget = QWidget()
        controlWidget.setLayout(controlLayout)
        controlWidget.setFixedWidth(320)

        # ─── Main grid layout ─────────────────────────────────
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        layout = QGridLayout(central_widget)
        layout.addWidget(self.range_angle,   0, 0, 2, 1)   # Big heatmap, left
        layout.addWidget(self.bf_time_domain, 0, 1)
        layout.addWidget(self.bf_freq_domain, 1, 1)
        layout.addWidget(controlWidget,       0, 2, 2, 1)

        # Status update timer (refresh status labels at 5 Hz)
        self.statusTimer = QTimer()
        self.statusTimer.timeout.connect(self.updateStatusLabels)
        self.statusTimer.start(200)

    # ─── GUI callbacks ────────────────────────────────────────
    def posDropdownChanged(self, index):
        """When user picks a planned position, fill the text field with it."""
        if index == 0:
            return
        pos = PLANNED_POSITIONS[index - 1]
        self.posTextField.setText(str(pos))

    def bfAngleChanged(self, index):
        global bf_angle
        bf_angle = index - MAX_ANGLE_RANGE

    def resetBfPlots(self):
        global bf_slow_time_samples
        bf_slow_time_samples = []

    def getCurrentScanPos(self):
        """Parse the position text field, returning int cm or None if invalid."""
        text = self.posTextField.text().strip()
        if not text:
            return None
        # Strip 'cm' if user typed it, allow leading + or -
        text = text.replace('cm', '').replace('+', '').strip()
        try:
            return int(text)
        except ValueError:
            try:
                return int(round(float(text)))
            except ValueError:
                return None

    def startCapture(self):
        global capturing, capture_file, capture_start_time
        global capture_n_frames, capture_bytes_written
        global capture_filename, capture_scan_pos, capture_notes

        scan_pos = self.getCurrentScanPos()
        if scan_pos is None:
            self.captureStatusLabel.setText(
                'Status: ERROR — invalid position'
            )
            self.captureStatusLabel.setStyleSheet(
                'font-weight: bold; color: red;'
            )
            return

        # Build filename: scan_neg40cm.bin, scan_0cm.bin, scan_pos15cm.bin
        if scan_pos < 0:
            pos_str = f'neg{abs(scan_pos)}cm'
        elif scan_pos > 0:
            pos_str = f'pos{scan_pos}cm'
        else:
            pos_str = '0cm'
        filename = f'scan_{pos_str}.bin'
        filepath = os.path.join(self.output_dir, 'bins', filename)

        # Warn if overwriting
        if os.path.exists(filepath):
            self.captureStatusLabel.setText(
                f'Status: overwriting {filename}...'
            )

        # Open the file and flip the capture flag atomically
        with capture_lock:
            capture_file = open(filepath, 'wb')
            capture_start_time = datetime.now()
            capture_n_frames = 0
            capture_bytes_written = 0
            capture_filename = filename
            capture_scan_pos = scan_pos
            capture_notes = self.notesField.text().strip()
            capturing = True

        self.startButton.setEnabled(False)
        self.stopButton.setEnabled(True)
        self.captureStatusLabel.setText(
            f'Status: RECORDING {filename} @ {scan_pos} cm'
        )
        self.captureStatusLabel.setStyleSheet(
            'font-weight: bold; color: #c0392b;'
        )

    def stopCapture(self):
        global capturing, capture_file

        # Flip the flag and grab the snapshot under the lock
        with capture_lock:
            if not capturing:
                return
            capturing = False
            f = capture_file
            capture_file = None
            n_frames = capture_n_frames
            bytes_written = capture_bytes_written
            filename = capture_filename
            scan_pos = capture_scan_pos
            start_time = capture_start_time
            notes = capture_notes

        if f is not None:
            f.close()
        stop_time = datetime.now()
        duration = (stop_time - start_time).total_seconds()

        # Append CSV row
        with open(self.csv_path, 'a', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([
                filename,
                scan_pos,
                start_time.isoformat(timespec='seconds'),
                stop_time.isoformat(timespec='seconds'),
                f'{duration:.2f}',
                n_frames,
                RSET_CONFIG,
                notes or '',
            ])

        self.startButton.setEnabled(True)
        self.stopButton.setEnabled(False)
        self.captureStatusLabel.setText(
            f'Status: saved {filename} ({n_frames} frames, '
            f'{bytes_written/1e6:.1f} MB, {duration:.1f} s)'
        )
        self.captureStatusLabel.setStyleSheet(
            'font-weight: bold; color: #2d6a4f;'
        )
        # Clear notes for next capture, leave position alone
        self.notesField.clear()

    def updateStatusLabels(self):
        """Called by QTimer at 5 Hz — refresh frame rate and capture stats."""
        if len(frame_times) > 1:
            avg_dt_ms = np.mean(frame_times)
            if avg_dt_ms > 0:
                fps = 1000.0 / avg_dt_ms
                self.frameRateLabel.setText(f'Frame rate: {fps:.1f} Hz')

        if capturing:
            with capture_lock:
                n = capture_n_frames
                mb = capture_bytes_written / 1e6
            elapsed = (datetime.now() - capture_start_time).total_seconds()
            self.captureStatusLabel.setText(
                f'Status: RECORDING {capture_filename} @ {capture_scan_pos} cm  '
                f'({n} frames, {mb:.1f} MB, {elapsed:.1f} s)'
            )

    # ─── Plot setters called from the radar thread ────────────
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
        """Clean shutdown when user closes the window."""
        global vmd3_thread_running
        vmd3_thread_running = False
        # If a capture is in progress, close it cleanly
        if capturing:
            self.stopCapture()
        event.accept()


def radar_thread_fn(window):
    """Pull frames from the V-MD3 UDP socket and update the GUI."""
    global total_frames_received, bf_slow_time_samples

    previous_time = datetime.now()

    while vmd3_thread_running:
        try:
            frame = vmd3.read_frame(b'RADC')
        except Exception as e:
            # During shutdown, swallow the timeout exception silently
            if not vmd3_thread_running:
                break
            # If a real error happens mid-run, print it but keep going
            err_str = str(e).lower()
            if 'timed out' not in err_str and 'timeout' not in err_str:
                print(f'[radar_thread] read_frame error: {e}')
            continue

        # Frame timing
        current_time = datetime.now()
        dt_ms = (current_time - previous_time).total_seconds() * 1000
        previous_time = current_time
        frame_times.append(dt_ms)
        total_frames_received += 1

        # Save raw frame if capturing
        with capture_lock:
            if capturing and capture_file is not None:
                try:
                    capture_file.write(frame)
                    globals()['capture_n_frames'] += 1
                    globals()['capture_bytes_written'] += len(frame)
                except Exception as e:
                    print(f'[radar_thread] write error: {e}')

        # Decode and process
        payload = frame[8:]
        cube = vmd3.decode_radc_2d(payload)
        if cube is None:
            cube = vmd3.decode_radc_3d(payload)
        if cube is None:
            continue

        # Range FFT, Doppler FFT, Angle FFT
        fft_range = np.fft.fft(cube, axis=0)
        fft_doppler = np.fft.fftshift(
            np.fft.fft(fft_range, axis=1), axes=1
        )
        fft_angle = np.fft.fftshift(
            np.fft.fft(fft_doppler, n=128, axis=2), axes=2
        )

        # Range-angle heatmap (sum |·| across Doppler axis)
        range_angle = np.sum(np.abs(fft_angle), axis=1)
        range_angle = np.squeeze(range_angle)
        max_val = np.max(range_angle)
        if max_val > 0:
            range_angle = range_angle / max_val
        range_angle = range_angle.T   # Heatmap expects angle×range
        window.setRangeAngleHeatmap(range_angle)

        # Peak target location
        peak_idx = np.unravel_index(np.argmax(range_angle), range_angle.shape)
        # range_angle is [angle_bins, range_bins] after the .T
        n_angle_bins, n_range_bins = range_angle.shape
        peak_angle_deg = (
            -MAX_ANGLE_RANGE
            + 2 * MAX_ANGLE_RANGE * peak_idx[0] / max(n_angle_bins - 1, 1)
        )
        peak_range_m = MAX_RANGE_M * peak_idx[1] / max(n_range_bins - 1, 1)
        window.setPeakLabels(peak_angle_deg, peak_range_m)

        # Beamform at the selected single angle for time/freq plots
        nRx = cube.shape[2]
        alpha = bf_angle
        wBF = np.array([
            complex(
                math.cos(-math.pi * n * math.sin(math.radians(alpha))),
                math.sin(-math.pi * n * math.sin(math.radians(alpha))),
            )
            for n in range(nRx)
        ])
        bf_result = np.matmul(fft_range, wBF)   # samples × chirps
        bf_chirp_avg = np.mean(bf_result, axis=1)
        bf_slow_time_samples.append(bf_chirp_avg)

        # Trim history to avoid unbounded growth (keep ~30 s)
        if len(bf_slow_time_samples) > 256:
            bf_slow_time_samples = bf_slow_time_samples[-256:]

        x_td, y_td = process_time_domain(bf_slow_time_samples)
        window.setBfTimeDomain(x_td, y_td[:len(x_td)])

        x_fd, y_fd = process_freq_domain(y_td)
        window.setBfFreqDomain(x_fd, y_fd)


def main(rset_config, session_name):
    global vmd3, vmd3_thread, app

    # ─── Set up output directory ────────────────────────────
    date_str = datetime.now().strftime('%Y-%m-%d')
    folder_name = f'scan_{date_str}'
    if session_name:
        folder_name += f'_{session_name}'

    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, 'data', folder_name)
    bins_dir = os.path.join(output_dir, 'bins')
    csv_path = os.path.join(output_dir, 'scan_log.csv')

    os.makedirs(bins_dir, exist_ok=True)

    # Write CSV header if file is new
    if not os.path.exists(csv_path):
        with open(csv_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([
                'filename', 'scan_pos_cm', 'timestamp_start',
                'timestamp_stop', 'duration_s', 'n_frames',
                'rset_mode', 'notes',
            ])
        print(f'[measure] Created {csv_path}')
    else:
        print(f'[measure] Appending to existing {csv_path}')

    # ─── Connect to V-MD3 ───────────────────────────────────
    print(f'[measure] Connecting to V-MD3 at 192.168.100.201...')
    vmd3 = VMD3()
    vmd3.connect()
    vmd3.set_rset_config(rset_config)
    vmd3.set_output_config([RdotConfig.RADC])
    vmd3.sockUDP.settimeout(1.0)
    print(f'[measure] RSET={rset_config}, ready')

    # ─── Launch GUI ─────────────────────────────────────────
    app = QApplication(sys.argv)
    window = MainWindow(output_dir, csv_path)
    window.show()

    # ─── Start radar thread ─────────────────────────────────
    vmd3_thread = threading.Thread(
        target=radar_thread_fn, args=(window,), daemon=True
    )
    vmd3_thread.start()

    # ─── Run Qt event loop ──────────────────────────────────
    exit_code = app.exec()

    # ─── Cleanup ────────────────────────────────────────────
    print('[measure] Shutting down...')
    global vmd3_thread_running
    vmd3_thread_running = False

    # Give the radar thread a chance to exit on its own.
    # It may be mid-recv with a 1s timeout, so wait up to ~1.5s.
    vmd3_thread.join(timeout=1.5)
    if vmd3_thread.is_alive():
        print('[measure] Radar thread did not exit cleanly (continuing anyway).')

    # If a capture was open at shutdown, close the file
    if capture_file is not None:
        try:
            capture_file.close()
        except Exception:
            pass

    # Disconnect from radar. The disconnect() call sends a TCP "GBYE" and
    # waits for a response — wrap in a timeout-aware attempt so we don't
    # hang forever if the radar is unresponsive.
    try:
        vmd3.sockTCP.settimeout(2.0)
        vmd3.disconnect()
    except Exception as e:
        print(f'[measure] disconnect warning: {e}')
        # Force-close the sockets so the OS releases the ports
        try:
            vmd3.sockTCP.close()
        except Exception:
            pass
        try:
            vmd3.sockUDP.close()
        except Exception:
            pass

    print('[measure] Done.')
    # os._exit instead of sys.exit so any remaining non-daemon threads
    # don't keep the process alive
    os._exit(exit_code)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='V-MD3 live measurement with discrete captures'
    )
    parser.add_argument(
        '--rsetMode', type=int, default=RSET_CONFIG,
        help=f'RSET value 0-8 (default: {RSET_CONFIG} — 2D, 6m, 4.69cm bin)'
    )
    parser.add_argument(
        '--sessionName', type=str, default='',
        help='Optional suffix for the session folder '
             '(e.g. "morning" -> scan_2026-05-18_morning/)'
    )
    args = parser.parse_args()
    main(args.rsetMode, args.sessionName)