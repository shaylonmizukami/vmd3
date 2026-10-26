"""Galil DMC-30012 linear stage control for continuous-motion SAR sweeps."""

import time
import gclib


class Stage:
    """One Galil axis driving a linear stage, with timeout recovery and limit switch homing."""

    def __init__(self, port, counts_per_mm, axis="A"):
        """Store connection settings without opening the controller yet."""
        self.port = port
        self.counts_per_mm = counts_per_mm
        self.axis = axis
        self.g = None
        self.home_direction = None
        self.home_backoff = None
        self.home_speed = None

    # Connection

    def connect(self):
        """Open the controller and stop any leftover motion or GDK program."""
        self.close()
        self.g = gclib.py()
        self.g.GOpen(self.port)
        print(f"[stage] Connected: {self.g.GInfo()}")
        self.stop()
        self.wait()
        try:
            self.cmd("HX")   # halt any program left running from GDK
        except RuntimeError:
            pass

    def close(self):
        """Stop the stage and close the controller connection if one is open."""
        if self.g is None:
            return
        try:
            self.stop()
            self.g.GClose()
            print("[stage] Disconnected.")
        except Exception as e:
            print(f"[stage] Close warning: {e}")
        self.g = None

    def _reconnect(self, attempts=3):
        """Close and reopen the connection to clear out-of-sync replies."""
        try:
            self.g.GClose()
        except gclib.GclibError:
            pass
        for i in range(attempts):
            time.sleep(0.5)
            try:
                self.g.GOpen(self.port)
                return
            except gclib.GclibError:
                if i == attempts - 1:
                    raise

    def cmd(self, command):
        """Send one command, reconnecting once after a timeout, and return the reply."""
        if self.g is None:
            raise RuntimeError("Stage is not connected. Run stage.connect() first.")
        try:
            return self.g.GCommand(command).strip()
        except gclib.GclibError as e:
            if "timed out" not in str(e):
                raise RuntimeError(f"Stage rejected '{command}': {self.g.GCommand('TC1').strip()}") from e
            print(f"[stage] '{command}' timed out, reconnecting...")
            self._reconnect()
            return self.g.GCommand(command).strip()

    # Motion

    def state(self):
        """Return (position in counts, True if the axis is moving)."""
        pos = float(self.cmd(f"MG _TP{self.axis}"))
        moving = float(self.cmd(f"MG _BG{self.axis}")) > 0.5
        return int(pos), moving

    def stop(self):
        """Stop motion on the axis."""
        self.cmd(f"ST{self.axis}")

    def wait(self, timeout_s=60):
        """Poll until the axis stops, stopping it if it takes too long."""
        t_end = time.perf_counter() + timeout_s
        while self.state()[1]:
            if time.perf_counter() > t_end:
                self.stop()
                raise TimeoutError("Stage move did not finish in time.")
            time.sleep(0.05)

    def move(self, counts, speed, absolute=False, timeout_s=60):
        """Move at the given speed and block until the move finishes."""
        self.cmd(f"SP{self.axis}={int(speed)}")
        self.cmd(f"{'PA' if absolute else 'PR'}{self.axis}={int(counts)}")
        self.cmd(f"BG{self.axis}")
        try:
            self.wait(timeout_s)
        except BaseException:
            self.stop()
            raise

    def prepare_move(self, counts, speed, accel):
        """Load a relative move with its speed and acceleration without starting it."""
        self.cmd(f"AC{self.axis}={int(accel)}")
        self.cmd(f"DC{self.axis}={int(accel)}")
        self.cmd(f"SP{self.axis}={int(speed)}")
        self.cmd(f"PR{self.axis}={int(counts)}")

    def begin(self):
        """Start the loaded move."""
        self.cmd(f"BG{self.axis}")

    def seek_end(self, direction, speed, timeout_s=60):
        """Jog toward an end until a limit switch or stall stops it."""
        self.cmd(f"JG{self.axis}={int(direction * speed)}")
        try:
            self.begin()
        except RuntimeError as e:
            if "limit switch" in str(e):
                return   # already sitting on that limit switch
            raise
        t_end = time.perf_counter() + timeout_s
        last_pos, last_t = self.state()[0], time.perf_counter()
        try:
            while True:
                time.sleep(0.05)
                pos, moving = self.state()
                if not moving:
                    break   # the limit switch stopped it
                if abs(pos - last_pos) > 100:
                    last_pos, last_t = pos, time.perf_counter()
                elif time.perf_counter() - last_t > 0.3:
                    break   # pressed against the end stop
                if time.perf_counter() > t_end:
                    raise TimeoutError("Stage never reached the end.")
        finally:
            self.stop()
            self.wait(10)

    # Homing

    def home(self, direction, backoff_counts, speed, accel):
        """Seek the home-side limit switch, back off, and set that position as zero."""
        print("[stage] Homing...")
        self.cmd(f"SH{self.axis}")
        self.cmd(f"AC{self.axis}={int(accel)}")
        self.cmd(f"DC{self.axis}={int(accel)}")
        self.seek_end(direction, speed)
        self.cmd(f"SH{self.axis}")   # re-enable in case the end tripped the error limit
        self.move(-direction * backoff_counts, speed)
        time.sleep(0.2)
        self.cmd(f"DP{self.axis}=0")
        self.home_direction = direction
        self.home_backoff = backoff_counts
        self.home_speed = speed
        print(f"[stage] Homed. Position {self.state()[0]} counts = start of sweep.")

    def _require_homed(self):
        """Raise a clear error if home() has not been run on this connection."""
        if self.home_direction is None:
            raise RuntimeError("Stage is not homed. Run stage.home(...) first.")

    def go_to_start(self):
        """Return to the zero position set by homing and let it settle."""
        self._require_homed()
        self.move(0, self.home_speed, absolute=True)
        time.sleep(0.2)

    def distance_mm(self, pos):
        """Distance in mm from the start toward the far end for a position in counts."""
        self._require_homed()
        return -self.home_direction * pos / self.counts_per_mm

    # Calibration

    def measure_switch_release(self, step=100, max_counts=20_000):
        """Drive onto the home-side switch and return how many counts it takes to release."""
        self._require_homed()
        switch_var = "_LF" if self.home_direction > 0 else "_LR"
        self.seek_end(self.home_direction, self.home_speed)
        on_state = self.cmd(f"MG {switch_var}{self.axis}")
        moved = 0
        while self.cmd(f"MG {switch_var}{self.axis}") == on_state and moved < max_counts:
            self.move(-self.home_direction * step, 5_000)
            moved += step
        print(f"[calibration] Switch reads {on_state} when active, released after {moved} counts "
              f"({moved / self.counts_per_mm:.3f} mm)")
        self.go_to_start()
        return moved

    def measure_full_travel(self):
        """Drive to the far switch and return the travel in counts between both switches."""
        self._require_homed()
        self.seek_end(-self.home_direction, self.home_speed)
        travel = abs(self.state()[0]) + self.home_backoff
        print(f"[calibration] Full travel: {travel} counts "
              f"({travel / self.counts_per_mm:.2f} mm at {self.counts_per_mm} counts/mm)")
        self.go_to_start()
        return travel