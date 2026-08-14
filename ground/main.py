from lib.vmd3 import VMD3, VMD3_SETTING

import sys
import argparse
import socket
import time
import signal
import threading
from datetime import datetime
from collections import deque

import numpy as np
import math

from PyQt6.QtWidgets import QApplication, QMainWindow, QGridLayout, QWidget, QPushButton, QComboBox, QVBoxLayout, QLabel
from lib.QtWidgets.HeatmapWidget import HeatmapWidget
from lib.QtWidgets.XYPlotWidget import XYPlotWidget
from lib.QtWidgets.XYZPlotWidget import XYZPlotWidget
from lib.QtWidgets.BarGraphWidget import BarChartWidget
from lib.QtWidgets.QDropdown import QDropdown

### GLOBALS
RSET_CONFIG = 1
TIME_STEP = 0.13
MAX_ANGLE_RANGE = 67
slow_time_samples = []
bf1_slow_time_samples = []
bf2_slow_time_samples = []
bf1_angle = 0
bf2_angle = 0

KILL_COUNTER = 0
KILL_IT = 5
app = None
vmd3_td = None
vmd3_thread_running = True

sock = None
programStartTime = datetime.now()
frameTimes = deque(maxlen=1000)
frameDrops = 0
framesMissed = 0
###

def cleanup_threads():
    global vmd3_thread_running
    global vmd3_td
    vmd3_thread_running = False
    vmd3_td.join()

# Handle CTRL-C
def handle_sigint(signal_number, frame):
    print("\nCtrl+C pressed! JOINING THREADS.")

    # sigint force kill safety
    global KILL_COUNTER
    global KILL_IT
    KILL_COUNTER += 1
    if KILL_COUNTER >= KILL_IT: exit

    # Quit the window if exists
    global app
    if app is not None and app.instance(): app.quit()

    # Close and join threads
    cleanup_threads()
# Register the SIGINT handler to join threads
signal.signal(signal.SIGINT, handle_sigint)

class MainWindow(QMainWindow):
    def __init__(self, windowWidth=1800, windowHeight=1200, rset_config=RSET_CONFIG):
        super().__init__()            

        self.setWindowTitle("ALiSM")
        self.setGeometry(100, 100, int(windowWidth*0.75), int(windowHeight*0.75))

        # Buttons
        self.resetDataButton = QPushButton('Reset Data')
        self.resetDataButton.clicked.connect(self.resetDataButtonClicked)

        # Plots
        self.range_doppler = HeatmapWidget(
            title='Range-Doppler', 
            xLabel='Velocity', 
            yLabel='Range', 
            yUnit='m', 
            yTickLimits=[0, VMD3_SETTING[rset_config]['max_range']], 
            xTickLimits=[-VMD3_SETTING[rset_config]['max_speed'], VMD3_SETTING[rset_config]['max_speed']]
        )
        self.range_angle = HeatmapWidget(
            title='Range-Angle', 
            xLabel='Angle', 
            yLabel='Range', 
            yUnit='m', 
            yTickLimits=[0, VMD3_SETTING[rset_config]['max_range']], 
            xTickLimits=[-MAX_ANGLE_RANGE, MAX_ANGLE_RANGE]
        )
        self.time_domain = XYPlotWidget(title='Time Domain', xLabel='Time', xUnit='s', yLabel='Amplitude')
        self.freq_domain = XYPlotWidget(title='Frequency Domain', xLabel='Frequency', xUnit='Hz', yLabel='Magnitude')
        self.xyz_range = XYZPlotWidget()
        self.bar_graph = BarChartWidget(title='Beamforming', xLabel='Angles', yLabel='Amplitude')

        # Beamforming related plots
        self.bf1_time_domain = XYPlotWidget(title='Time Domain BF1', xLabel='Time', xUnit='s', yLabel='Amplitude')
        self.bf1_freq_domain = XYPlotWidget(title='Frequency Domain BF1', xLabel='Frequency', xUnit='Hz', yLabel='Magnitude')
        self.bf2_time_domain = XYPlotWidget(title='Time Domain BF2', xLabel='Time', xUnit='s', yLabel='Amplitude')
        self.bf2_freq_domain = XYPlotWidget(title='Frequency Domain BF2', xLabel='Frequency', xUnit='Hz', yLabel='Magnitude')

        # Beamform angle selection
        self.peakAngleLabel = QLabel('Peak Angle: 0 degrees')
        self.minAngleLabel = QLabel('Min Angle: 0 degrees')
        global bf1_angle
        global bf2_angle
        self.bf1_angle_selection = QDropdown(label='Angle 1:', defaultIndex=(bf1_angle+MAX_ANGLE_RANGE), onChange=self.bf1AngleChanged)
        self.bf2_angle_selection = QDropdown(label='Angle 2:', defaultIndex=(bf2_angle+MAX_ANGLE_RANGE), onChange=self.bf2AngleChanged)
        for i in range(-MAX_ANGLE_RANGE, MAX_ANGLE_RANGE + 1):
            self.bf1_angle_selection.addItem(f'{i}')
            self.bf2_angle_selection.addItem(f'{i}')
        beamformSelectionLayout = QVBoxLayout()
        beamformSelectionLayout.addStretch()
        beamformSelectionLayout.addWidget(self.peakAngleLabel)
        beamformSelectionLayout.addWidget(self.minAngleLabel)
        beamformSelectionLayout.addStretch()
        beamformSelectionLayout.addWidget(self.bf1_angle_selection)
        beamformSelectionLayout.addWidget(self.bf2_angle_selection)
        beamformSelectionLayout.addStretch()
        beamformSelectionLayout.addWidget(self.resetDataButton)
        beamformSelectionLayout.addStretch()

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        layout = QGridLayout(central_widget)
        # layout.addWidget(self.range_doppler, 0, 0)
        layout.addWidget(self.range_angle, 0, 1)
        layout.addWidget(self.time_domain, 1, 0)
        layout.addWidget(self.freq_domain, 1, 1)
        layout.addLayout(beamformSelectionLayout, 1, 2)
        # layout.addWidget(self.xyz_range, 0, 2)
        # layout.addWidget(self.bar_graph, 2, 2, 2, 1)
        layout.addWidget(self.bf1_time_domain, 2, 0)
        layout.addWidget(self.bf1_freq_domain, 2, 1)
        layout.addWidget(self.bf2_time_domain, 3, 0)
        layout.addWidget(self.bf2_freq_domain, 3, 1)
        
    def setRangeDopplerHeatmap(self, data):
        self.range_doppler.setData(data)
        
    def setRangeAngleHeatmap(self, data):
        self.range_angle.setData(data)
        
    def setTimeDomain(self, x, y):
        self.time_domain.set_plot(x, y)
        
    def setFreqDomain(self, x, y):
        self.freq_domain.set_plot(x, y)

    def setBFTimeDomain(self, x1, y1, x2, y2):
        self.bf1_time_domain.set_plot(x1, y1)
        self.bf2_time_domain.set_plot(x2, y2)

    def setBFFreqDomain(self, x1, y1, x2, y2):
        self.bf1_freq_domain.set_plot(x1, y1)
        self.bf2_freq_domain.set_plot(x2, y2)
        
    def setXYZRangePlot(self, data):
        self.xyz_range.setData(data)

    def setBarGraph(self, data):
        self.bar_graph.update_data(data)
        
    def resetDataButtonClicked(self):
        global slow_time_samples
        global bf1_slow_time_samples
        global bf2_slow_time_samples
        slow_time_samples = []
        bf1_slow_time_samples = []
        bf2_slow_time_samples = []

    def bf1AngleChanged(self, index):
        global bf1_angle
        bf1_angle = -(index - MAX_ANGLE_RANGE)

    def bf2AngleChanged(self, index):
        global bf2_angle
        bf2_angle = -(index - MAX_ANGLE_RANGE)

    def setPeakAngleLabel(self, val):
        self.peakAngleLabel.setText(f'Peak Angle: {val} degrees')

    def setMinAngleLabel(self, val):
        self.minAngleLabel.setText(f'Min Angle: {val} degrees')

def processTimeDomain(raw):
    # Process slow-time samples
    data_complex = np.array([np.mean(row) for row in raw])
    data = [np.abs(x) for x in data_complex]
    
    # Remove DC offset
    data_mean = sum(data) / len(data)
    data = [x - data_mean for x in data]
    
    # Calculate time domain interval
    time_length = len(data) * TIME_STEP
    time_interval = np.arange(TIME_STEP, time_length + TIME_STEP, TIME_STEP)
    if len(time_interval) != len(data):
        time_interval = time_interval[:len(data)]

    return time_interval, data

def processFreqDomain(data):
    # Calculate FFT of Time Domain
    sample_freq = 1 / TIME_STEP
    data.extend([0] * 256)
    data = data[1:] # First index always bad data?
    num_samples = len(data)
    fft = abs(np.fft.fft(data))
    y_fft = fft[:num_samples // 2 + 1]
    x_fft = sample_freq * np.arange(0, num_samples // 2 + 1) / num_samples

    return x_fft, y_fft

def recv_exact(n):
    global sock
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError('socket closed by peer')
        buf += chunk
    return bytes(buf)

def read_frame(header_requested):
    global frameDrops
    while True:
        header = recv_exact(8)
        if header[0:4] != header_requested:
            frameDrops += 1
            continue
        respLength = int.from_bytes(header[4:8], byteorder='little')
        payload = recv_exact(respLength)
        return header + payload

def main(ip, port):
    global sock
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ip, port))

    vmd3 = VMD3(standalone=True)

    # Setup PyQt6
    global app
    app = QApplication(sys.argv)
    primary_screen = app.primaryScreen()
    available_geometry: QRect = primary_screen.availableGeometry()
    window = MainWindow(available_geometry.width(), available_geometry.height())
    window.show()

    def vmd3_thread():
        global vmd3_thread_running
        global framesMissed

        frameNum = 0
        previous_time = time.time()

        while vmd3_thread_running:
            frame = read_frame(b'RADC')
            payload = frame[8:]

            # Calculate time difference between read times
            current_time = time.time()
            dt_ms = (current_time - previous_time) * 1000
            previous_time = time.time()
            if frameNum > 0:
                framesMissed += max(0, round(dt_ms / (TIME_STEP * 1000)) - 1)

            # Decode 2D or 3D. Cube is in Samples x Chirps x Channels
            mode = '2d'
            cube = vmd3.decode_radc_2d(payload)
            if cube is None:
                mode = '3d'
                cube = vmd3.decode_radc_3d(payload)
            if cube is None: continue

            frameTimes.append(dt_ms)

            print(f'Frame Number: {frameNum} | Frame Size: {len(frame)} | Frame Time: {dt_ms:.02f} ms | ',
                    'Average Time: {np.mean(frameTimes):.02f} ms | Total Time: {datetime.now() - programStartTime} | ',
                    'Frames Missed: {framesMissed} | Frames Received: {(1 - framesMissed / (frameNum + framesMissed + 1)) * 100:.02f}%')
            frameNum += 1

            # RANGE FFT: Perform FFT across samples dimension.
            # INPUT: Samples x Chirps x Channels
            # OUTPUT: Range x Chirps x Channels
            fft_range = np.fft.fft(cube, axis=0)
            
            # DOPPLER FFT: Perform FFT across chirps dimension.
            # INPUT: Range x Chirps x Channels
            # OUTPUT: Range x Velocity x Channels
            fft_doppler = np.fft.fft(fft_range, axis=1)
            fft_doppler = np.fft.fftshift(fft_doppler, axes=1)
            
            # ANGLE FFT: Perform FFT across channels dimension.
            # INPUT: Range x Velocity x Channels
            # OUTPUT: Range x Velocity x Angle
            fft_angle = np.fft.fft(fft_doppler, n=128, axis=2)
            fft_angle = np.fft.fftshift(fft_angle, axes=2)

            # BEAMFORMING
            nRx = cube.shape[2]
            angles = np.linspace(-MAX_ANGLE_RANGE, MAX_ANGLE_RANGE, 64)
            subbeam = []
            for alpha in angles:
                wBF = []
                for n in range(nRx):
                    x = -math.pi * n * math.sin(math.radians(alpha))
                    real = math.cos(x)
                    imag = math.sin(x)
                    wBF.append(complex(real, imag))
                ret = np.matmul(fft_range, wBF) # Dot product between 3D cube and weight vector. Results in a Samples x Chirps matrix.
                ret = np.mean(ret, axis=1) # Average Chirps
                subbeam.append(ret) # This is for one angle. Store it, and repeat for the remaining angles.
            subbeam_max = []
            for arr in subbeam:
                t2 = np.abs(arr) # Contents of the sub-beams are in complex form. Take the magnitude of all.
                subbeam_max.append(np.max(t2)) # Find the max value for that respective angle. This will indicate the highest reflection at that angle.
            window.setPeakAngleLabel(angles[subbeam_max.index(max(subbeam_max))])
            window.setMinAngleLabel(angles[subbeam_max.index(min(subbeam_max))])
            # window.setBarGraph(subbeam_max)

            # PLOT TIME/FREQ DOMAIN OF BEAMFORMED DATA
            global bf1_angle
            global bf2_angle
            Delta = (angles[-1] - angles[0]) / (len(angles) - 1)
            index0 = int(round((bf1_angle - angles[0]) / Delta))
            index1 = int(round((bf2_angle - angles[0]) / Delta))
            bf1_slow_time_samples.append(subbeam[index0])
            bf2_slow_time_samples.append(subbeam[index1])

            time_interval1, data1 = processTimeDomain(bf1_slow_time_samples)
            time_interval2, data2 = processTimeDomain(bf2_slow_time_samples)
            window.setBFTimeDomain(time_interval1, data1[:len(time_interval1)], time_interval2, data2[:len(time_interval2)])
            
            x_fft1, y_fft1 = processFreqDomain(data1)
            x_fft2, y_fft2 = processFreqDomain(data2)
            window.setBFFreqDomain(x_fft1, y_fft1, x_fft2, y_fft2)

            # Filter out BF1 - BF2
            filtered_data = []
            for i in range(len(data1)):
                filtered_data.append(data1[i] - data2[i])
            x_fft, y_fft = processFreqDomain(filtered_data)
            window.setTimeDomain(time_interval1, filtered_data[:len(time_interval1)])
            window.setFreqDomain(x_fft, y_fft)

            # RANGE ANGLE HEATMAP
            range_angle_data = np.sum(np.abs(fft_angle), axis=1)
            range_angle_data = np.squeeze(range_angle_data)
            range_angle_data = range_angle_data / np.max(range_angle_data) # Normalize
            range_angle_data = range_angle_data.T
            window.setRangeAngleHeatmap(range_angle_data)
            
            # RANGE RANGE 3D
            # range_targets_x = []
            # range_targets_y = []
            # range_targets_z = []
            # targets = np.argwhere(range_angle_data > 0.9)
            # for target in targets:
            #     angles = np.radians(np.linspace(-MAX_ANGLE_RANGE, MAX_ANGLE_RANGE, len(range_angle_data)))
            #     rangebin = np.linspace(0, VMD3_SETTING[RSET_CONFIG]['max_range'], len(range_angle_data[0]))
            #     x = rangebin[target[1]] * np.sin(angles[target[0]])
            #     y = rangebin[target[1]] * np.cos(angles[target[0]])
            #     range_targets_x.append(x)
            #     range_targets_y.append(y)
            #     range_targets_z.append(0)
            # window.setXYZRangePlot([range_targets_x, range_targets_y, range_targets_z])
            
            # RANGE DOPPLER HEATMAP
            range_doppler_avg = np.mean(fft_doppler, axis=2)
            range_doppler_avg = np.abs(range_doppler_avg)
            range_doppler_avg = range_doppler_avg.T
            # window.setRangeDopplerHeatmap(range_doppler_avg)

        sock.close()

    # Start threads
    global vmd3_td
    vmd3_td = threading.Thread(target=vmd3_thread)
    vmd3_td.start()

    app.exec()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="ALiSM Ground to Interface with Flight Hardware")

    parser.add_argument('--ip', type=str, default='192.168.100.201', help='IP Address of the Flight Computer. Default: 192.168.100.201')
    parser.add_argument('--port', type=int, default=39123, help='Port of the Flight Computer. Default: 39123')

    args = parser.parse_args()

    main(ip=args.ip, port=args.port)
