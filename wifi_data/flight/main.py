"""
VMD3 flight relay (reads RADC frames, records, optionally streams to ground)
Frames are read/written whether or not client is connected, independent of the ground station
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import queue
import signal
import socket
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from config import FRAME_PERIOD_MS, RADC_HEADER, TCP_PORT, resolve_capture_paths
from lib.vmd3 import VMD3, VMD3_SETTING, RdotConfig

### GLOBALS
running = threading.Event()
running.set()

send_queue = queue.Queue(maxsize=8)  # preview stream (drops when link is behind)
write_queue = queue.Queue()  # disk (never drops)
client_connected = threading.Event()

framesSkipped = 0
framesWritten = 0
bytesWritten = 0

HST = ZoneInfo("Pacific/Honolulu")
###


def handle_sigint(signal_number, frame):
    running.clear()


signal.signal(signal.SIGINT, handle_sigint)


def drain(q):
    while not q.empty():
        try:
            q.get_nowait()
        except queue.Empty:
            break


def acceptor_thread(server):
    """Accept one client at a time and forward preview frames to it"""
    while running.is_set():
        try:
            client_socket, addr = server.accept()
        except TimeoutError:
            continue
        except OSError:
            break

        print(f"Client connected from {addr}")
        drain(send_queue)
        client_connected.set()

        try:
            while running.is_set():
                try:
                    frame = send_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                client_socket.sendall(frame)
        except (BrokenPipeError, ConnectionResetError, OSError):
            print(f"Client {addr} disconnected")
        finally:
            client_connected.clear()
            drain(send_queue)
            client_socket.close()


def writer_thread(bin_path):
    """Drain write queue to disk, off radar read loop"""
    global framesWritten, bytesWritten
    with open(bin_path, "wb") as file:
        while True:
            chunk = write_queue.get()
            if chunk is None:
                break
            file.write(chunk)
            framesWritten += 1
            bytesWritten += len(chunk)


def write_metadata(json_path, rset_config, started, ended, frame_size):
    meta = {
        "rset_config": rset_config,
        "frame_size": frame_size,
        "frame_count": framesWritten,
        "bytes_written": bytesWritten,
        "frames_skipped": framesSkipped,
        "start_time": started.isoformat(timespec="seconds"),
        "end_time": ended.isoformat(timespec="seconds"),
        "duration_s": round((ended - started).total_seconds(), 3),
        "frame_period_ms": FRAME_PERIOD_MS,
        "vmd3_setting": VMD3_SETTING.get(rset_config),
    }
    with open(json_path, "w") as f:
        json.dump(meta, f, indent=2, default=str)
    print(f"Metadata saved at {json_path}")


def main(rset_config, saveBin, filePath, fileName, duration, noStream):
    global framesSkipped
    started = datetime.now(HST)

    # --- Save to file ---
    writer = None
    bin_path, json_path = resolve_capture_paths(started, filePath, fileName)
    if saveBin:
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        writer = threading.Thread(target=writer_thread, args=(bin_path,), daemon=True)
        writer.start()
        print(f"Recording to {bin_path}")

    # --- TCP server ---
    server = None
    acceptor = None
    if not noStream:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", TCP_PORT))
        server.listen(1)
        server.settimeout(1)
        acceptor = threading.Thread(target=acceptor_thread, args=(server,), daemon=True)
        acceptor.start()
        print(f"TCP server listening on {TCP_PORT}")

    # --- Radar ---
    print("Connecting to VMD3...")
    vmd3 = VMD3()
    vmd3.connect()
    vmd3.set_rset_config(rset_config)
    vmd3.set_output_config([RdotConfig.RADC])
    print(f"VMD3 connected (rset {rset_config})")

    if duration:
        print(f"Capture Duration: {duration} s")

    # --- Read loop ---
    frameNum = 0
    frameSize = 0
    startClock = time.time()
    previous_time = startClock

    try:
        while running.is_set():
            raw = vmd3.read_frame(RADC_HEADER)
            frameSize = len(raw)

            current_time = time.time()
            dt_ms = (current_time - previous_time) * 1000
            previous_time = current_time

            if saveBin:
                write_queue.put(raw)

            if client_connected.is_set():
                try:
                    send_queue.put_nowait(raw)
                except queue.Full:
                    framesSkipped += 1

            elapsed = current_time - startClock
            print(
                f"Frame Number: {frameNum} | Frame Size: {frameSize} | Frame Time: {dt_ms:.02f} ms | "
                f"Skipped: {framesSkipped} | Written: {framesWritten} | "
                f"Total Time: {str(datetime.now(HST) - started)[:-3]}"
            )
            frameNum += 1

            if duration and elapsed >= duration:
                print(f"Duration of {duration} s reached")
                break
    except KeyboardInterrupt:
        pass
    finally:
        running.clear()

        print("Disconnecting VMD3")
        vmd3.disconnect()

        if server is not None:
            server.close()
            acceptor.join(timeout=2)
            print("TCP server closed")

        if saveBin:
            write_queue.put(None)
            writer.join(timeout=10)
            ended = datetime.now(HST)
            print(
                f"Binary file saved at {bin_path} with {bytesWritten} bytes ({framesWritten} frames)"
            )
            write_metadata(json_path, rset_config, started, ended, frameSize)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VMD3 flight relay: record RADC frames & stream to ground station"
    )

    parser.add_argument(
        "--rset", type=int, default=1, 
        help="RSET configuration of the VMD3 radar (0-8)"
    )
    parser.add_argument(
        "--saveBin", action="store_true", 
        help="Save frames into a binary file"
    )
    parser.add_argument(
        "--filePath", type=str, default=None,
        help="Directory for the raw binary data. Default: <wifi_data>/data/radc/YYYY-MM-DD/",
    )
    parser.add_argument(
        "--fileName", type=str, default=None,
        help="Filename stem for the raw binary data. Default: HH-MM-SS",
    )
    parser.add_argument(
        "--duration", type=float, default=None, 
        help="Stop after this many seconds"
    )
    parser.add_argument(
        "--noStream", action="store_true", 
        help="Record only (don't open TCP server)"
    )

    args = parser.parse_args()

    main(
        rset_config=args.rset,
        saveBin=args.saveBin,
        filePath=args.filePath,
        fileName=args.fileName,
        duration=args.duration,
        noStream=args.noStream,
    )