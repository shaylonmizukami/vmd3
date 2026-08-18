"""VMD3 ground station — receives RADC frames over the wireless link and reports link health.

No decoding, no plotting. Post-processing runs offline from the flight-side .bin.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import socket
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    FLIGHT_IP,
    FRAME_PERIOD_MS,
    HEADER_SIZE,
    RADC_HEADER,
    TCP_PORT,
    resolve_capture_paths,
)

### GLOBALS
sock = None
frameTimes = deque(maxlen=1000)
frameNum = 0
framesMissed = 0
frameDrops = 0
bytesWritten = 0

HST = ZoneInfo("Pacific/Honolulu")
###


def recv_exact(n):
    """Read exactly n bytes, never past the frame boundary."""
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
        header = recv_exact(HEADER_SIZE)
        if header[0:4] != header_requested:
            frameDrops += 1
            continue
        respLength = int.from_bytes(header[4:8], byteorder='little')
        payload = recv_exact(respLength)
        return header + payload


def connect(ip, port, timeout):
    """Block until the flight relay accepts, retrying on failure."""
    global sock
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((ip, port))
            print(f'Connected to flight computer at {ip}:{port}')
            return
        except (TimeoutError, ConnectionRefusedError, OSError) as e:
            print(f'Connect failed ({e}) — retrying in 2 s')
            sock.close()
            time.sleep(2)


def write_metadata(json_path, ip, started, ended, frame_size):
    meta = {
        'source': f'{ip}:{TCP_PORT}',
        'frame_size': frame_size,
        'frame_count': frameNum,
        'bytes_written': bytesWritten,
        'frames_missed_estimate': framesMissed,
        'header_mismatches': frameDrops,
        'start_time': started.isoformat(timespec='seconds'),
        'end_time': ended.isoformat(timespec='seconds'),
        'duration_s': round((ended - started).total_seconds(), 3),
        'frame_period_ms': FRAME_PERIOD_MS,
        'note': 'Ground copy — incomplete if frames_missed_estimate > 0. Flight .bin is authoritative.',
    }
    with open(json_path, 'w') as f:
        json.dump(meta, f, indent=2, default=str)
    print(f'Metadata saved at {json_path}')


def main(ip, port, saveBin, filePath, fileName, duration, timeout):
    global frameNum, framesMissed, bytesWritten

    started = datetime.now(HST)

    file = None
    bin_path, json_path = resolve_capture_paths(started, filePath, fileName)
    if saveBin:
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        file = open(bin_path, 'wb')
        print(f'Recording to {bin_path}')

    if duration:
        print(f'Capturing for {duration} s')

    connect(ip, port, timeout)

    frameSize = 0
    startClock = time.time()
    previous_time = startClock

    try:
        while True:
            try:
                frame = read_frame(RADC_HEADER)
            except (TimeoutError, ConnectionResetError, OSError) as e:
                print(f'Link lost ({e}) — reconnecting')
                sock.close()
                connect(ip, port, timeout)
                previous_time = time.time()
                continue

            frameSize = len(frame)

            current_time = time.time()
            dt_ms = (current_time - previous_time) * 1000
            previous_time = current_time

            if frameNum > 0:
                framesMissed += max(0, round(dt_ms / FRAME_PERIOD_MS) - 1)

            frameTimes.append(dt_ms)

            if saveBin:
                file.write(frame)
                bytesWritten += frameSize

            received = (1 - framesMissed / (frameNum + framesMissed + 1)) * 100
            print(f'Frame Number: {frameNum} | Frame Size: {frameSize} | Frame Time: {dt_ms:.02f} ms | '
                  f'Average Time: {sum(frameTimes) / len(frameTimes):.02f} ms | '
                  f'Total Time: {str(datetime.now(HST) - started)[:-3]} | '
                  f'Frames Missed: {framesMissed} | Frames Received: {received:.02f}%')
            frameNum += 1

            if duration and (current_time - startClock) >= duration:
                print(f'Duration of {duration} s reached')
                break
    except KeyboardInterrupt:
        print('\nStopping')
    finally:
        if sock is not None:
            sock.close()
        if saveBin:
            file.close()
            ended = datetime.now(HST)
            print(f'Binary file saved at {bin_path} with {bytesWritten} bytes ({frameNum} frames)')
            write_metadata(json_path, ip, started, ended, frameSize)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='VMD3 ground station — receive RADC frames from the flight computer')

    parser.add_argument('--ip', type=str, default=FLIGHT_IP, help=f'IP address of the flight computer. Default: {FLIGHT_IP}')
    parser.add_argument('--port', type=int, default=TCP_PORT, help=f'Port of the flight computer. Default: {TCP_PORT}')
    parser.add_argument('--saveBin', action='store_true', help='Save received frames into a binary file')
    parser.add_argument('--filePath', type=str, default=None, help='Directory for the raw binary data. Default: <wifi_data>/data/radc/YYYY-MM-DD/')
    parser.add_argument('--fileName', type=str, default=None, help='Filename stem for the raw binary data. Default: HH-MM-SS')
    parser.add_argument('--duration', type=float, default=None, help='Stop after this many seconds. Default: no limit')
    parser.add_argument('--timeout', type=float, default=5.0, help='Socket timeout in seconds before assuming the link is dead. Default: 5')

    args = parser.parse_args()

    main(
        ip=args.ip,
        port=args.port,
        saveBin=args.saveBin,
        filePath=args.filePath,
        fileName=args.fileName,
        duration=args.duration,
        timeout=args.timeout,
    )