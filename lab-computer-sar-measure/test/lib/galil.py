"""Galil control for the CDS-3310 linear mover, positions in mm from the right end."""

import time

import gclib


class Stage:
    """One Galil axis driving the linear mover."""

    def __init__(self, address, axis="A", right_is_positive=True, counts_per_mm=10000, accel=1000000):
        """Open the Galil connection and store the axis settings."""
        self.address = address
        self.axis = axis
        self.sign = 1 if right_is_positive else -1
        self.cpm = counts_per_mm
        self.accel = accel
        self.g = gclib.py()
        self.g.GOpen(address)

    def cmd(self, command):
        """Send one command and return the reply."""
        return self.g.GCommand(command).strip()

    def values(self, *operands):
        """Read numeric operands like _TPA in a single round trip."""
        return [float(v) for v in self.cmd("MG " + ", ".join(operands)).split()]

    def counts(self, mm):
        """Convert mm (or mm/s) to encoder counts (or counts/s)."""
        return int(round(mm * self.cpm))

    def state(self):
        """Return travel in mm from the right end and whether the axis is moving."""
        pos, moving = self.values(f"_TP{self.axis}", f"_BG{self.axis}")
        return -self.sign * pos / self.cpm, moving != 0

    def wait(self):
        """Block until motion finishes and let the stage settle."""
        self.g.GMotionComplete(self.axis)
        time.sleep(0.2)

    def _move(self, command, speed_mm_s):
        """Run one PR or PA move at a speed and wait for it."""
        self.cmd(f"SP{self.axis}={self.counts(speed_mm_s)}")
        self.cmd(command)
        self.cmd(f"BG{self.axis}")
        self.wait()

    def home_right(self, backoff_mm=1.0, speed_mm_s=10.0):
        """Drive into the right end, back off, and zero the position there."""
        # Stop any leftover .dmc program and set up the axis
        self.cmd("HX")
        self.cmd(f"SH{self.axis}")
        self.cmd(f"AC{self.axis}={self.accel}")
        self.cmd(f"DC{self.axis}={self.accel}")

        # Hit the right end, back off, and call that zero
        self._move(f"PR{self.axis}={self.sign * 1100000}", speed_mm_s)   # longer than the rail on purpose, same as the .dmc
        self._move(f"PR{self.axis}={-self.sign * self.counts(backoff_mm)}", speed_mm_s)
        self.cmd(f"DP{self.axis}=0")

    def move_to_zero(self, speed_mm_s=10.0):
        """Return to the homed right-end position if not already there."""
        if abs(self.state()[0]) > 0.005:
            self._move(f"PA{self.axis}=0", speed_mm_s)

    def preload_sweep(self, sweep_mm, speed_mm_s):
        """Load a leftward sweep so start() fires it with a single command."""
        self.cmd(f"SP{self.axis}={self.counts(speed_mm_s)}")
        self.cmd(f"PR{self.axis}={-self.sign * self.counts(sweep_mm)}")

    def start(self):
        """Begin the preloaded move."""
        self.cmd(f"BG{self.axis}")

    def stop(self):
        """Stop the axis and wait for it to come to rest."""
        self.cmd(f"ST{self.axis}")
        self.g.GMotionComplete(self.axis)

    def close(self):
        """Close the Galil connection."""
        try:
            self.g.GClose()
        except Exception as e:
            print(f"   Galil close warning: {e}")