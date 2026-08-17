"""
record.py — Record V-MD3 RADC frames to a binary file.

Usage:
    python record.py --mode 0 --fileName test_3m_18cm_run1

Stops on Ctrl+C. Output file is processable by vmd3_process_bin.m
or by replay.py.
"""

import argparse
import os
import signal
import socket
import sys
import time
from datetime import datetime

import numpy as np
from lib.vmd3 import VMD3, RdotConfig

running = True

def sigint_handler(sig, frame):
    global running
    print('\n[record] Ctrl+C received, stopping after current frame...')
    running = False

signal.signal(signal.SIGINT, sigint_handler)


# Range axes for the live readout — depends on RSET mode.
# Index = RSET value, value = (max_range_m, max_speed_kmh, n_chirps)
_RSET_INFO = {
    0: (6,   10,  64),  # 2D, 6m,   10kmh
    1: (10,  10,  64),  # 2D, 10m,  10kmh
    2: (30,  30,  64),  # 2D, 30m,  30kmh
    3: (30,  50,  64),  # 2D, 30m,  50kmh
    4: (50,  50,  64),  # 2D, 50m,  50kmh
    5: (100, 100, 64),  # 2D, 100m, 100kmh
    6: (6,   10,  32),  # 3D, 6m,   10kmh
    7: (10,  10,  32),  # 3D, 10m,  10kmh
    8: (30,  30,  32),  # 3D, 30m,  30kmh
}


def read_any_frame(vmd3, headers=(b'RADC', b'RFFT')):
    """Read the next UDP frame whose header is in `headers`. Returns full frame."""
    while True:
        data = vmd3.recv_udp()
        if data[0:4] not in headers:
            continue
        resp_len = int.from_bytes(data[4:8], byteorder='little')
        while len(data) < resp_len + 8:
            data += vmd3.recv_udp()
        if resp_len != len(data[8:]):
            continue
        return data
    

def quick_target_readout(vmd3, payload, rset_config):
    """Return (range_m, speed_kmh, magnitude) of the strongest target."""
    max_range, max_speed, _ = _RSET_INFO[rset_config]

    cube = vmd3.decode_radc_2d(payload)
    if cube is None:
        cube = vmd3.decode_radc_3d(payload)
    if cube is None:
        return None

    # Range FFT across samples, Doppler FFT across chirps
    fft_range = np.fft.fft(cube, axis=0)
    fft_dopp = np.fft.fftshift(np.fft.fft(fft_range, axis=1), axes=1)

    # Average magnitude across RX channels → 2D range-Doppler map
    rd = np.mean(np.abs(fft_dopp), axis=2)

    # Mask out near-range TX-RX leakage (first ~20 bins = ~94 cm)
    rd_masked = rd.copy()
    rd_masked[:20, :] = 0
    r_bin, d_bin = np.unravel_index(np.argmax(rd_masked), rd_masked.shape)
    n_range, n_dopp = rd.shape
    target_range = r_bin * (max_range / n_range)
    target_speed = (d_bin - n_dopp / 2) * (2 * max_speed / n_dopp)
    return target_range, target_speed, rd[r_bin, d_bin]


def connect_with_interrupt(tcp_timeout=3.0):
    """
    Try to connect to the V-MD3 with a short timeout so Ctrl+C is
    responsive during connection setup. Returns the VMD3 object on
    success, or None if interrupted.
    """
    print(f'[record] Connecting to V-MD3 at 192.168.100.201... '
          f'(Ctrl+C to abort)')
    try:
        # Pre-create the sockets manually so we can set timeouts
        # before any blocking calls happen.
        sock_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock_tcp.settimeout(tcp_timeout)

        # Try a few times in case the radar is still booting
        for attempt in range(3):
            if not running:
                sock_tcp.close()
                return None
            try:
                sock_tcp.connect(('192.168.100.201', 6172))
                break
            except socket.timeout:
                print(f'[record] TCP connect timed out '
                      f'(attempt {attempt+1}/3), retrying...')
            except ConnectionRefusedError:
                print(f'[record] Connection refused '
                      f'(attempt {attempt+1}/3), retrying...')
            except OSError as e:
                print(f'[record] Network error: {e}')
                sock_tcp.close()
                return None
        else:
            sock_tcp.close()
            print('[record] Failed to connect after 3 attempts.')
            return None

        # We have a working TCP connection. Now construct VMD3 around it.
        # Reset to blocking mode for the rest of the protocol setup
        # (which is fast once the TCP handshake worked).
        sock_tcp.settimeout(None)
        print('[VMD3] Connected to TCP/IP')

        vmd3 = VMD3(standalone=True)  # don't have it open its own sockets
        vmd3.sockTCP = sock_tcp
        vmd3.tcp_ip = '192.168.100.201'
        vmd3.tcp_port = 6172

        # Open UDP socket
        sock_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock_udp.bind(('0.0.0.0', 4567))
        vmd3.sockUDP = sock_udp
        vmd3.udp_ip = '0.0.0.0'
        vmd3.udp_port = 4567
        print('[VMD3] Connected to UDP')

        # Send INIT
        vmd3.connect()
        return vmd3

    except KeyboardInterrupt:
        print('\n[record] Connection aborted by user.')
        return None


def main(rset_config, file_path, file_name, on_exists):
    # Auto-create a date-based subdirectory: data/radc/2026-05-22/
    date_folder = datetime.now().strftime('%Y-%m-%d')
    full_path = os.path.join(file_path, date_folder)
    os.makedirs(full_path, exist_ok=True)
    out_path = os.path.join(full_path, f'{file_name}.bin')

    # Handle the case where the target file already exists
    if os.path.exists(out_path):
        if on_exists == 'overwrite':
            print(f'[record] File exists, will overwrite: {out_path}')
        elif on_exists == 'append':
            base_path = out_path
            counter = 1
            while os.path.exists(out_path):
                out_path = os.path.join(
                    full_path, f'{file_name}_{counter}.bin')
                counter += 1
            print(f'[record] File exists, using: {out_path}')
        elif on_exists == 'fail':
            print(f'[record] File already exists: {out_path}')
            print(f'[record] Use --onExists overwrite or append, '
                  f'or pick a different --fileName.')
            return

    vmd3 = connect_with_interrupt()
    if vmd3 is None:
        print('[record] Exiting without recording.')
        return

    try:
        vmd3.set_rset_config(rset_config)
        vmd3.set_output_config([RdotConfig.RADC, RdotConfig.RFFT])
        vmd3.sockUDP.settimeout(1.0)
    except Exception as e:
        print(f'[record] Setup failed: {e}')
        try:
            vmd3.disconnect()
        except Exception:
            pass
        return

    out = open(out_path, 'wb')

    print(f'[record] RSET={rset_config}, recording to {out_path}')
    print(f'[record] Press Ctrl+C to stop.')

    start = datetime.now()
    n_frames = 0
    bytes_written = 0
    frame_timestamps = []   # perf_counter() at each frame arrival
    try:
        while running:
            try:
                frame = read_any_frame(vmd3, (b'RADC', b'RFFT'))
            except socket.timeout:
                continue
            frame_timestamps.append(time.perf_counter())
            out.write(frame)
            n_frames += 1
            bytes_written += len(frame)
            frame_type = frame[0:4].decode('ascii', errors='replace')

            if frame_type == 'RADC':
                elapsed = datetime.now() - start
                payload = frame[8:]
                tgt = quick_target_readout(vmd3, payload, rset_config)
                if tgt is not None:
                    r, v, mag = tgt
                    print(f'  frame {n_frames:5d}  {elapsed}  '
                          f'{bytes_written/1e6:.1f} MB  '
                          f'target: {r:5.2f} m  {v:+6.2f} km/h')
                else:
                    print(f'  frame {n_frames:5d}  {elapsed}  '
                          f'{bytes_written/1e6:.1f} MB')

    finally:
        out.close()
        if frame_timestamps:
            ts_path = out_path.replace('.bin', '_timestamps.txt')
            t0 = frame_timestamps[0]
            rel = [t - t0 for t in frame_timestamps]
            with open(ts_path, 'w') as tf:
                tf.write('\n'.join(f'{t:.6f}' for t in rel))
            # quick on-the-spot jitter readout
            if len(rel) > 1:
                diffs = np.diff(rel)
                print(f'[record] frame rate: {1.0/np.mean(diffs):.3f} Hz '
                      f'(mean dt={np.mean(diffs)*1000:.2f} ms, '
                      f'jitter std={np.std(diffs)*1000:.2f} ms, '
                      f'max dt={np.max(diffs)*1000:.2f} ms)')
            print(f'[record] timestamps saved to {ts_path}')
        try:
            vmd3.disconnect()
        except Exception as e:
            print(f'[record] disconnect warning: {e}')
        print(f'[record] Saved {n_frames} frames ({bytes_written} bytes) '
              f'to {out_path}')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='V-MD3 RADC recorder')
    p.add_argument('--mode', type=int, default=0,
                   help='RSET value 0-8. '
                        '0=2D/6m/10kmh/128x64 (recommended for 3m bench), '
                        '6=3D/6m/10kmh/128x32. See datasheet Table 3.')
    p.add_argument('--filePath', type=str, default='data/radc-rfft',
                   help='Directory to save .bin files (default: data/radc-rfft)')
    p.add_argument('--fileName', type=str,
                   default=datetime.now().strftime('%Y-%m-%d_%H-%M-%S'),
                   help='Filename without extension '
                        '(default: timestamp YYYY-MM-DD_H-M-S)')
    p.add_argument('--onExists', type=str, default='append',
                   choices=['overwrite', 'append', 'fail'],
                   help='What to do if the target file already exists. '
                        'overwrite = replace existing file silently; '
                        'append = auto-append _1, _2, ... to the filename; '
                        'fail = abort without recording. '
                        '(default: append)')
    args = p.parse_args()
    main(args.mode, args.filePath, args.fileName, args.onExists)