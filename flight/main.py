import argparse
import math
import os
import queue
import signal
import socket
import sys
import threading
import time
from datetime import datetime

import numpy as np
from lib.vmd3 import VMD3, VMD3_SETTING, RdotConfig

### GLOBALS
MAX_ANGLE_RANGE = 67
slow_time_samples = []
bf1_slow_time_samples = []
bf2_slow_time_samples = []
bf1_angle = 0
bf2_angle = 0

vmd3_running = True
programStartTime = datetime.now()
### 

# Handle CTRL-C
def handle_sigint(signal_number, frame):
    global vmd3_running
    vmd3_running = False

# Register the SIGINT handler to join threads
signal.signal(signal.SIGINT, handle_sigint)

send_queue = queue.Queue(maxsize=8)
client_lost = threading.Event()
framesSkipped = 0

def sender_thread(sock):
    while True:
        frame = send_queue.get()
        if frame is None:
            break
        try:
            sock.sendall(frame)
        except (BrokenPipeError, ConnectionResetError, OSError):
            client_lost.set()
            break

def main(rset_config, saveBin, filePath, fileName):
    global vmd3_running

    # Start TCP Server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('0.0.0.0', 39123))
    server.listen(1)
    server.settimeout(5)
    print('TCP Server started!')

    # Create file
    bytesWritten = 0
    if saveBin:
        os.makedirs(filePath, exist_ok=True)
        file = open(f'{filePath}/{fileName}.bin', "wb")

    # Connect to VMD3
    print('Connecting to VMD3...')
    vmd3 = VMD3()
    vmd3.connect()
    vmd3.set_rset_config(rset_config)
    rdot_configs = [RdotConfig.RADC]
    vmd3.set_output_config(rdot_configs)
    print('VMD3 Connected!')

    while True:
        if not vmd3_running:
            break

        try:
            # Accept incoming connection
            print('Waiting for new connection...')
            client_socket, addr = server.accept()
            print(f'Client connected from {addr}')
            client_lost.clear()
            while not send_queue.empty():
                send_queue.get_nowait()
            sender = threading.Thread(target=sender_thread, args=(client_socket,), daemon=True)
            sender.start()
        except socket.timeout:
            continue

        try:
            frameNum = 0
            previous_time = time.time()
            while not client_lost.is_set():
                if not vmd3_running:
                    break

                # Read frame from VMD3
                raw = vmd3.read_frame(b'RADC')
                frameSize = len(raw)

                # Calculate time difference between read times
                current_time = time.time()
                dt_ms = (current_time - previous_time) * 1000
                previous_time = time.time()

                # Hand frame to sender thread; drop preview frames if the link is behind
                global framesSkipped
                try:
                    send_queue.put_nowait(raw)
                except queue.Full:
                    framesSkipped += 1

                # # Decode 2D or 3D. Cube is in Samples x Chirps x Channels
                # mode = '2d'
                # cube = vmd3.decode_radc_2d(payload)
                # if cube is None:
                #     mode = '3d'
                #     cube = vmd3.decode_radc_3d(payload)
                # if cube is None:
                #     continue

                print(f'Frame Number: {frameNum}, Frame Size: {frameSize}, Frame Time: {dt_ms} ms, Skipped: {framesSkipped}, '
                      f'Total Time: {str(datetime.now() - programStartTime)[:-3]}')
                frameNum += 1

                # Save to binary file
                if saveBin:
                    file.write(raw)
                    bytesWritten += len(raw)

                # # RANGE FFT: Perform FFT across samples dimension.
                # # INPUT: Samples x Chirps x Channels
                # # OUTPUT: Range x Chirps x Channels
                # fft_range = np.fft.fft(cube, axis=0)
                
                # # DOPPLER FFT: Perform FFT across chirps dimension.
                # # INPUT: Range x Chirps x Channels
                # # OUTPUT: Range x Velocity x Channels
                # fft_doppler = np.fft.fft(fft_range, axis=1)
                # fft_doppler = np.fft.fftshift(fft_doppler, axes=1)
                
                # # ANGLE FFT: Perform FFT across channels dimension.
                # # INPUT: Range x Velocity x Channels
                # # OUTPUT: Range x Velocity x Angle
                # fft_angle = np.fft.fft(fft_doppler, n=512, axis=2)
                # fft_angle = np.fft.fftshift(fft_angle, axes=2)

                # # BEAMFORMING
                # nRx = cube.shape[2]
                # angles = np.linspace(-MAX_ANGLE_RANGE, MAX_ANGLE_RANGE, 512)
                # subbeam = []
                # for alpha in angles:
                #     wBF = []
                #     for n in range(nRx):
                #         x = -math.pi * n * math.sin(math.radians(alpha))
                #         real = math.cos(x)
                #         imag = math.sin(x)
                #         wBF.append(complex(real, imag))
                #     ret = np.matmul(fft_range, wBF) # Dot product between 3D cube and weight vector. Results in a Samples x Chirps matrix.
                #     ret = np.mean(ret, axis=1) # Average Chirps
                #     subbeam.append(ret) # This is for one angle. Store it, and repeat for the remaining angles.
                # subbeam_max = []
                # for arr in subbeam:
                #     t2 = np.abs(arr) # Contents of the sub-beams are in complex form. Take the magnitude of all.
                #     subbeam_max.append(np.max(t2)) # Find the max value for that respective angle. This will indicate the highest reflection at that angle.

        except ConnectionResetError:
            print(f'Client {addr} disconnected')
            client_lost.set()
        finally:
            while not send_queue.empty():
                try:
                    send_queue.get_nowait()
                except queue.Empty:
                    break
            send_queue.put(None)
            sender.join(timeout=2)
            client_socket.close()

    print('Disconnecting VMD3')
    vmd3.disconnect()
    print('VMD3 Disconnected')

    server.close()
    print('TCP Server closed')

    if saveBin:
        file.close()
        print(f'Binary file saved at {filePath}/{fileName}.bin with {bytesWritten} bytes')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="VMD3 python to read live VMD3 data and process it")

    parser.add_argument("--saveBin", action='store_true', help="Save frames into binary file")
    parser.add_argument("--filePath", type=str, default='data/radc', help="Filepath to save raw binary data into. Only enabled when --saveBin=True. Default: data/radc/")
    parser.add_argument("--fileName", type=str, default=datetime.now().strftime("%Y-%m-%d_%H-%M-%S"), help="Filename to save raw binary data into. Only enabled when --saveBin=True. Default: YYYY-MM-DD_H-M-S")
    parser.add_argument("--mode", type=int, default=1, help="Mode of the VMD3 radar (0-8). Default: 6")

    args = parser.parse_args()

    main(rset_config=args.mode, saveBin=args.saveBin, filePath=args.filePath, fileName=args.fileName)
