"""Simulated VMD3 sweep and arm track in the same file format as record.py."""

import argparse
import csv
import json
import time
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

from config import (ANGLE_SIGN, DATA_DIR, FRAME_PERIOD_S, HST, PHASE_SIGN, RADC_HEADER, RX_SPACING_M, WAVELENGTH_M)
from lib.vmd3 import VMD3_SETTING

RSET = 0
ARM_LOG_PERIOD_S = 0.02   # arm track written at 50 Hz
AMPLITUDE = 1000   # ADC counts for a scatterer with gain 1

def arm_position(t, start_x, end_x, speed, hold_s):
    """Radar x position at time t for a hold, constant speed move, hold sweep."""
    move_s = abs(end_x - start_x) / speed
    progress = np.clip((t - hold_s) / move_s, 0.0, 1.0)
    return start_x + (end_x - start_x) * progress

def frame_payload(x_radar, scatterers, setting, noise, rng):
    """Return one RADC payload for the radar at x_radar seeing the given scatterers."""
    samples, chirps = setting["num_samples"], setting["num_chirps"]
    bin_m = setting["max_range"] / samples
    n = np.arange(samples)[:, None]
    tx_x = x_radar   # TX assumed at the array center
    rx_x = x_radar + ANGLE_SIGN * (np.arange(4) - 1.5) * RX_SPACING_M

    # Path out to the scatterer and back to each RX sets the beat frequency and carrier phase
    signal = np.zeros((samples, 4), dtype=complex)
    for x_t, z_t, gain in scatterers:
        path = np.hypot(x_t - tx_x, z_t) + np.hypot(x_t - rx_x, z_t)
        beat = 2 * np.pi * n * (path / 2 / bin_m) / samples
        carrier = PHASE_SIGN * 2 * np.pi * path / WAVELENGTH_M
        signal += gain * np.exp(1j * (beat + carrier))

    # Same return on every chirp plus fresh noise, in ADC counts
    shape = (samples, chirps, 4)
    cube = AMPLITUDE * signal[:, None, :] + noise * (rng.normal(size=shape) + 1j * rng.normal(size=shape))

    # Pack as chirp, channel, sample with Q before I, like the radar
    ordered = cube.transpose(1, 2, 0)
    packed = np.empty((chirps, 4, samples, 2), dtype="<i2")
    packed[..., 0] = np.clip(np.round(ordered.imag), -32768, 32767)
    packed[..., 1] = np.clip(np.round(ordered.real), -32768, 32767)
    return packed.tobytes()

def main(fileName, targetRange, targetCross, start, end, speed, hold, clutter, noTarget, clockOffset, noise, seed):
    rng = np.random.default_rng(seed)
    setting = VMD3_SETTING[RSET]
    started = datetime.now(HST)
    stem = DATA_DIR / started.strftime("%Y-%m-%d") / fileName
    stem.parent.mkdir(parents=True, exist_ok=True)
    if Path(f"{stem}.json").exists():
        raise SystemExit(f"{stem.name} already exists in {stem.parent}, pick another --fileName")

    # Scene: optional target plug optional fixed clutter around it
    scatterers = [] if noTarget else [(targetCross, targetRange, 1.0)]
    if clutter:
        scatterers += [(-0.06, targetRange + 0.10, 0.6), (0.04, targetRange - 0.08, 0.5), (0.08, targetRange + 0.20, 0.8)]

    # Timeline: hold at start, sweep, hold at end
    total_s = 2 * hold + abs(end - start) / speed
    frame_t = np.arange(0, total_s, FRAME_PERIOD_S)
    start_unix = time.time()

    # Radar frames and frame log
    with open(f"{stem}_radc.bin", "wb") as f, open(f"{stem}_frames.csv", "w", newline="") as lf:
        log = csv.writer(lf)
        log.writerow(["frame", "time_unix", "elapsed_s", "radar_counter", "mark", "radc"])
        for k, t in enumerate(frame_t):
            payload = frame_payload(arm_position(t, start, end, speed, hold), scatterers, setting, noise, rng)
            f.write(RADC_HEADER + len(payload).to_bytes(4, "little") + payload)
            log.writerow([k, f"{start_unix + t:.3f}", f"{t:.3f}", k + 1, "", 1])
    frame_size = len(RADC_HEADER) + 4 + len(payload)

    # Arm track, shifted by clockOffset to mimic unsynced clocks
    with open(f"{stem}_arm.csv", "w", newline="") as af:
        arm = csv.writer(af)
        arm.writerow(["time_unix", "x_m"])
        for t in np.arange(0, total_s, ARM_LOG_PERIOD_S):
            arm.writerow([f"{start_unix + t + clockOffset:.3f}", f"{arm_position(t, start, end, speed, hold):.6f}"])

    # Metadata, plug the true scene for checking results
    meta = {
        "rset": RSET,
        "vmd3_setting": setting,
        "outputs": ["radc"],
        "start_time": started.isoformat(timespec="seconds"),
        "end_time": (started + timedelta(seconds=total_s)).isoformat(timespec="seconds"),
        "duration_s": round(total_s, 3),
        "frame_count": len(frame_t),
        "output_counts": {"radc": len(frame_t)},
        "frame_sizes": {"radc": frame_size},
        "frames_missed_estimate": 0,
        "marks": [],
        "simulated": {
            "scatterers": scatterers,
            "start_x_m": start,
            "end_x_m": end,
            "speed_m_s": speed,
            "move_start_s": hold,
            "move_end_s": total_s - hold,
            "clock_offset_s": clockOffset,
        },
    }
    with open(f"{stem}.json", "w") as jf:
        json.dump(meta, jf, indent=2)

    print(f"Wrote {len(frame_t)} frames over {total_s:.1f} s to {stem}_*")
    print(f"Sweep {start * 100:+.1f} to {end * 100:+.1f} cm at {speed * 1000:.1f} mm/s, {speed * FRAME_PERIOD_S * 1000:.2f} mm per frame")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate a VMD3 SAR sweep and arm track")
    parser.add_argument("--fileName", required=True, help="Capture name, saved under data/<today>/")
    parser.add_argument("--targetRange", type=float, default=0.78, help="Target slant range at sweep center in m. Default: 0.78")
    parser.add_argument("--targetCross", type=float, default=0.0, help="Target cross-range in m, + is right. Default: 0")
    parser.add_argument("--start", type=float, default=0.05, help="Sweep start x in m. Default: 0.05 (right)")
    parser.add_argument("--end", type=float, default=-0.05, help="Sweep end x in m. Default: -0.05 (left)")
    parser.add_argument("--speed", type=float, default=0.0077, help="Arm speed in m/s. Default: 0.0077")
    parser.add_argument("--hold", type=float, default=5.0, help="Still time at each end in s. Default: 5")
    parser.add_argument("--clutter", action="store_true", help="Add three fixed clutter scatterers around the target")
    parser.add_argument("--noTarget", action="store_true", help="Leave the target out, for a background sweep")
    parser.add_argument("--clockOffset", type=float, default=0.0, help="Seconds added to arm timestamps. Default: 0")
    parser.add_argument("--noise", type=float, default=100.0, help="Noise level in ADC counts. Default: 100")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for the noise. Default: 0")
    args = parser.parse_args()

    main(args.fileName, args.targetRange, args.targetCross, args.start, args.end, args.speed, args.hold, args.clutter, args.noTarget, args.clockOffset, args.noise, args.seed)    
