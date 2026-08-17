"""
record.py — Capture VMD3 RADC frames to a .bin file.

Pure recorder: connect, pull RADC frames, write raw bytes to disk, log
per-frame timestamps, disconnect. No decoding, no processing — all
interpretation of the data lives in process.py.

Usage:
    python record.py --fileName plate_t1_alone
    (Ctrl+C to stop.)

The .bin is a concatenation of raw frames (8-byte header + payload each),
readable by vmd3lib.decode.get_frames.
"""

import argparse
import os
import signal
import socket
import time
from datetime import datetime

import numpy as np
from vmd3lib.config import (
    ACTIVE_RSET,
    FRAME_PERIOD_S,
    HEADER_RADC,
    TARGET1_DISP_MM,
    TARGET1_FREQ_HZ,
    TARGET2_DISP_MM,
    TARGET2_FREQ_HZ,
    UNWRAP_LIMIT_MM_HZ,
)
from vmd3lib.iq import predicted_phase_step
from vmd3lib.vmd3 import VMD3, RdotConfig

running = True


def sigint_handler(sig, frame):
    global running
    print('\n[record] Ctrl+C received, stopping after current frame...')
    running = False


signal.signal(signal.SIGINT, sigint_handler)


def print_margins():
    """
    Predicted unwrap margin for both targets, from the config constants.
    Printed before connecting so a doomed capture is obvious in advance.
    """
    for name, d, f in (('target 1', TARGET1_DISP_MM, TARGET1_FREQ_HZ),
                       ('target 2', TARGET2_DISP_MM, TARGET2_FREQ_HZ)):
        step = predicted_phase_step(d, f)
        if step >= np.pi:
            verdict = 'WILL FAIL — over pi'
        elif step >= np.pi / 2:
            verdict = 'ok, but one dropped frame breaks it'
        else:
            verdict = 'robust to a dropped frame'
        print(f'[record] {name}: {d:.1f} mm @ {f:.2f} Hz -> D*f={d * f:.2f} '
              f'(limit {UNWRAP_LIMIT_MM_HZ:.2f}), step={step:.2f} rad — {verdict}')


def connect_with_interrupt(ip='192.168.100.201', tcp_port=6172,
                           udp_port=4567, tcp_timeout=3.0):
    """
    Connect to the V-MD3 with a short TCP timeout so Ctrl+C stays responsive
    during connection setup. Returns a connected VMD3, or None if interrupted
    or the connection failed.
    """
    print(f'[record] Connecting to V-MD3 at {ip}... (Ctrl+C to abort)')
    try:
        sock_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock_tcp.settimeout(tcp_timeout)

        for attempt in range(3):
            if not running:
                sock_tcp.close()
                return None
            try:
                sock_tcp.connect((ip, tcp_port))
                break
            except socket.timeout:
                print(f'[record] TCP connect timed out '
                      f'(attempt {attempt + 1}/3), retrying...')
            except ConnectionRefusedError:
                print(f'[record] Connection refused '
                      f'(attempt {attempt + 1}/3), retrying...')
            except OSError as e:
                print(f'[record] Network error: {e}')
                sock_tcp.close()
                return None
        else:
            sock_tcp.close()
            print('[record] Failed to connect after 3 attempts.')
            return None

        # TCP handshake worked. Build the VMD3 around the existing socket and
        # switch back to blocking mode for the (fast) protocol setup.
        sock_tcp.settimeout(None)
        print('[VMD3] Connected to TCP/IP')

        vmd3 = VMD3(standalone=True)   # don't let it open its own sockets
        vmd3.sockTCP = sock_tcp
        vmd3.tcp_ip = ip
        vmd3.tcp_port = tcp_port

        sock_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock_udp.bind(('0.0.0.0', udp_port))
        vmd3.sockUDP = sock_udp
        vmd3.udp_ip = '0.0.0.0'
        vmd3.udp_port = udp_port
        print('[VMD3] Connected to UDP')

        vmd3.connect()   # send INIT
        return vmd3

    except KeyboardInterrupt:
        print('\n[record] Connection aborted by user.')
        return None


def main(file_path, file_name, rset_config, on_exists, duration=None):
    print_margins()
    # Date-based subfolder: data/radc/2026-07-16/
    date_folder = datetime.now().strftime('%Y-%m-%d')
    full_path = os.path.join(file_path, date_folder)
    os.makedirs(full_path, exist_ok=True)
    out_path = os.path.join(full_path, f'{file_name}.bin')

    # Resolve a name collision before touching the radar.
    if os.path.exists(out_path):
        if on_exists == 'overwrite':
            print(f'[record] File exists, will overwrite: {out_path}')
        elif on_exists == 'append':
            counter = 1
            while os.path.exists(out_path):
                out_path = os.path.join(
                    full_path, f'{file_name}_{counter}.bin')
                counter += 1
            print(f'[record] File exists, using: {out_path}')
        elif on_exists == 'fail':
            print(f'[record] File already exists: {out_path}')
            print('[record] Use --onExists overwrite or append, '
                  'or pick a different --fileName.')
            return

    vmd3 = connect_with_interrupt()
    if vmd3 is None:
        print('[record] Exiting without recording.')
        return

    try:
        vmd3.set_rset_config(rset_config)
        vmd3.set_output_config([RdotConfig.RADC])   # RADC only
        vmd3.sockUDP.settimeout(1.0)   # wake the loop each second to check Ctrl+C
    except Exception as e:
        print(f'[record] Setup failed: {e}')
        try:
            vmd3.disconnect()
        except Exception:
            pass
        return

    # Open the file only after a confirmed connection, so a failed connect
    # never leaves a 0-byte junk file behind.
    out = open(out_path, 'wb')
    print(f'[record] RSET={rset_config}, recording to {out_path}')
    print('[record] Press Ctrl+C to stop.')

    if duration is not None:
        expected = int(duration / FRAME_PERIOD_S)
        print(f'[record] Timed capture: {duration:.0f} s '
              f'(~{expected} frames, ~{expected * 131080 / 1e6:.0f} MB)')

    start = datetime.now()
    n_frames = 0
    bytes_written = 0
    frame_timestamps = []

    try:
        while running:
            if duration is not None and \
                    (datetime.now() - start).total_seconds() >= duration:
                print(f'[record] Reached {duration:.0f} s.')
                break
            try:
                frame = vmd3.read_frame(HEADER_RADC)
            except socket.timeout:
                continue
            frame_timestamps.append(time.perf_counter())
            out.write(frame)
            n_frames += 1
            bytes_written += len(frame)

            if n_frames == 1 or n_frames % 10 == 0:
                print(f'  frame {n_frames:5d}  '
                      f'{(datetime.now() - start).total_seconds():6.1f} s  '
                      f'{bytes_written / 1e6:.1f} MB')

    finally:
        out.close()
        if len(frame_timestamps) > 1:
            ts = np.asarray(frame_timestamps) - frame_timestamps[0]
            ts_path = os.path.splitext(out_path)[0] + '_timestamps.npy'
            np.save(ts_path, ts)
            print(f'[record] Timestamps -> {ts_path}')

            diffs = np.diff(ts)
            mean_dt = float(np.median(diffs))
            max_dt = float(np.max(diffs))
            print(f'[record] frame rate: {1.0 / mean_dt:.3f} Hz '
                  f'(jitter std={np.std(diffs) * 1000:.2f} ms, '
                  f'max dt={max_dt * 1000:.2f} ms)')

            n_gaps = int(np.sum(diffs > 1.5 * mean_dt))
            if max_dt > 2.0 * mean_dt:
                print(f'[record] *** WARNING: {n_gaps} gap(s) detected. '
                      f'A dropped frame doubles the phase step, which pushes '
                      f'target 2 past pi. Its unwrap is likely corrupted — '
                      f're-record before processing. ***')
            elif n_gaps:
                print(f'[record] Note: {n_gaps} mild timing outlier(s), '
                      f'below the 2x drop threshold.')
        try:
            vmd3.disconnect()
        except Exception as e:
            print(f'[record] disconnect warning: {e}')
        print(f'[record] Saved {n_frames} frames ({bytes_written} bytes) '
              f'to {out_path}')
        
        if n_frames == 0:
            os.remove(out_path)
            print('[record] No frames captured, removed empty file.')
        else:
            print(f'[record] Saved {n_frames} frames ({bytes_written} bytes) '
                  f'to {out_path}')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='VMD3 RADC recorder (pure capture)')
    p.add_argument('--filePath', type=str, default='data/radc',
                   help='Directory for .bin files (default: data/radc)')
    p.add_argument('--fileName', type=str,
                   default=datetime.now().strftime('%Y-%m-%d_%H-%M-%S'),
                   help='Filename without extension (default: timestamp)')
    p.add_argument('--rset', type=int, default=ACTIVE_RSET,
                   help=f'RSET config (default: {ACTIVE_RSET} from config.py)')
    p.add_argument('--onExists', type=str, default='append',
                   choices=['overwrite', 'append', 'fail'],
                   help='Behavior if the target file exists (default: append)')
    p.add_argument('--duration', type=float, default=None,
                   help='Capture length in seconds (default: run until Ctrl+C). Use 120 for the two-target measurement.')
    args = p.parse_args()
    main(args.filePath, args.fileName, args.rset, args.onExists, args.duration)