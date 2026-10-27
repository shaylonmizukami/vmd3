"""V-MD3 radar connection, frame reading, and network setup for continuous-motion SAR sweeps."""

import os
import time
import socket
import base64
import ctypes
import subprocess
from pathlib import Path
import numpy as np
from .vmd3 import VMD3, RdotConfig

# Stream definitions
STREAM_FLAGS = {"radc": RdotConfig.RADC, "rfft": RdotConfig.RFFT, "done": RdotConfig.DONE}
STREAM_HEADERS = {"radc": b"RADC", "rfft": b"RFFT", "done": b"DONE"}
CYCLE_ORDER = ["radc", "rfft", "done"]   # order streams arrive within one radar cycle

# Socket settings
UDP_TIMEOUT_S = 1.0
RCVBUF_BYTES = 8 * 1024 * 1024   # room to buffer frames while Python talks to the stage


def run_network_setup(script_path):
    """Run the radar network setup script as administrator and print its output."""
    script = Path(script_path).resolve()
    log = Path(os.environ["TEMP"]) / "vmd3_setup_log.txt"
    if not script.is_file():
        raise FileNotFoundError(f"Setup script not found: {script}")
    log.unlink(missing_ok=True)

    # Run the script and capture everything it prints into the log
    script_q = str(script).replace("'", "''")
    log_q = str(log).replace("'", "''")
    inner = f"& '{script_q}' *>&1 | Out-File -FilePath '{log_q}' -Encoding utf8"
    encoded = base64.b64encode(inner.encode("utf-16-le")).decode()
    ps_args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]

    # Run directly if already elevated, otherwise go through a UAC prompt
    if ctypes.windll.shell32.IsUserAnAdmin():
        subprocess.run(["powershell", *ps_args])
    else:
        print("[radar] Approve the UAC prompt to run the network setup...")
        launcher = f"Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '{' '.join(ps_args)}'"
        subprocess.run(["powershell", "-NoProfile", "-Command", launcher])

    # Show the output and confirm it passed
    if not log.is_file():
        raise RuntimeError("No setup output. The UAC prompt may have been declined.")
    text = log.read_text(encoding="utf-8-sig")
    print(text)
    if "All checks passed" not in text:
        raise RuntimeError("Radar network setup did not pass. See the messages above.")
    print("[radar] Network ready.")


class Radar:
    """One V-MD3 radar connection with retrying setup and frame-level UDP reading."""

    def __init__(self, ip):
        """Store connection settings without opening the radar yet."""
        self.ip = ip
        self.dev = None
        self.mode = None
        self.streams = None
        self.frame_period = None

    # Connection
    def connect(self, mode, streams, attempts=3):
        """Open and configure the radar, retrying if the handshake stalls."""
        streams = list(dict.fromkeys(s.strip().lower() for s in streams))
        if not streams or any(s not in STREAM_FLAGS for s in streams):
            raise ValueError(f"streams must use only {list(STREAM_FLAGS)}")
        if not 0 <= mode <= 8:
            raise ValueError("mode must be 0 to 8")
        if self.dev is not None:
            self.close()
            time.sleep(2)   # let the radar release the old session

        for i in range(attempts):
            dev = VMD3(tcp_ip=self.ip)
            try:
                dev.connect()
                dev.sockTCP.settimeout(5.0)
                dev.set_rset_config(mode)
                dev.set_output_config([STREAM_FLAGS[s] for s in streams])
            except OSError as e:
                print(f"[radar] Handshake stalled ({e or 'timeout'}), retry {i + 1}/{attempts}...")
                self._close_sockets(dev)
                time.sleep(2)
                continue
            dev.sockUDP.settimeout(UDP_TIMEOUT_S)
            dev.sockUDP.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RCVBUF_BYTES)
            self.dev, self.mode, self.streams = dev, mode, streams
            print(f"[radar] Ready. Mode {mode}, streams {streams}")
            return
        raise RuntimeError("Radar did not respond. Power cycle it, wait about 10 s, then rerun the network setup and connect.")

    def close(self):
        """Close the radar connection if one is open."""
        if self.dev is None:
            return
        try:
            self.dev.sockTCP.settimeout(2.0)
            self.dev.disconnect()
            print("[radar] Disconnected.")
        except Exception as e:
            print(f"[radar] Close warning: {e}. Sockets force-closed.")
            self._close_sockets(self.dev)
        self.dev = None

    @staticmethod
    def _close_sockets(dev):
        """Force-close a device's TCP and UDP sockets, ignoring errors."""
        for s in (getattr(dev, "sockTCP", None), getattr(dev, "sockUDP", None)):
            try:
                s.close()
            except Exception:
                pass

    def _require_connected(self):
        """Raise a clear error if connect() has not been run."""
        if self.dev is None:
            raise RuntimeError("Radar is not connected. Run radar.connect(...) first.")

    # Streams
    def cycle_streams(self):
        """Selected streams in the order they arrive within one radar cycle."""
        self._require_connected()
        return [s for s in CYCLE_ORDER if s in self.streams]

    def sync_stream(self):
        """Last selected stream in each radar cycle, used to mark cycle boundaries."""
        return self.cycle_streams()[-1]

    # Frames
    def read_frame(self, headers):
        """Read the next complete frame whose header is in headers."""
        self._require_connected()
        while True:
            data = self.dev.recv_udp()
            if data[:4] not in headers:
                continue
            length = int.from_bytes(data[4:8], "little")
            while len(data) < length + 8:
                data += self.dev.recv_udp()
            if len(data) == length + 8:
                return data

    def drain(self):
        """Discard everything already waiting in the UDP buffer."""
        self._require_connected()
        self.dev.sockUDP.settimeout(0.05)
        try:
            while True:
                self.dev.recv_udp()
        except socket.timeout:
            pass
        finally:
            self.dev.sockUDP.settimeout(UDP_TIMEOUT_S)

    def wait_for_frame(self, header):
        """Block until the next complete frame with this header arrives."""
        while True:
            try:
                return self.read_frame((header,))
            except socket.timeout:
                pass

    def measure_frame_period(self, n_cycles=30):
        """Time n radar cycles, store the median period, and return it in seconds."""
        header = STREAM_HEADERS[self.sync_stream()]
        self.drain()
        stamps = []
        while len(stamps) < n_cycles + 1:
            self.wait_for_frame(header)
            stamps.append(time.perf_counter())
        self.frame_period = float(np.median(np.diff(stamps)))
        print(f"[radar] Frame period: {self.frame_period * 1e3:.1f} ms ({1 / self.frame_period:.2f} Hz)")
        return self.frame_period