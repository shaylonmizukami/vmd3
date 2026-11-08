"""Convert a Galil rail sweep (.bin plus _positions.csv) into a capture and track that sar_image.py reads."""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from config import DATA_DIR, DONE_HEADER, HEADER_SIZE, HST, RADC_HEADER
from lib.vmd3 import VMD3_SETTING

PAYLOAD_BYTES = {"2D": 131072, "3D": 196608}

def read_records(bin_path):
    """Yield (tag, full record bytes) for each record in a Galil .bin, in file order."""
    with open(bin_path, "rb") as f:
        while header := f.read(HEADER_SIZE):
            payload = f.read(int.from_bytes(header[4:8], "little"))
            yield header[:4], header + payload

def sweep_info(bin_path):
    """(radar mode, start time) from the session's scan_log.csv, or None if the sweep isn't listed."""
    log = bin_path.parent.parent / "scan_log.csv"
    if not log.exists():
        return None
    with open(log, newline="") as f:
        for row in csv.DictReader(f):
            if row["file"] == bin_path.name:
                return int(row["radar_mode"]), datetime.fromisoformat(row["start"]).replace(tzinfo=HST)
    return None

def main(bin_path, rset, out, flipX):
    bin_path = Path(bin_path)
    pos_path = bin_path.with_name(f"{bin_path.stem}_positions.csv")

    # Radar mode and start time from the session log, falling back to --rset and the file time
    info = sweep_info(bin_path)
    if info:
        rset, started = info
    else:
        started = datetime.fromtimestamp(bin_path.stat().st_mtime, HST)
        print(f"No scan_log.csv entry for {bin_path.name}, using --rset {rset} and the file time")
    setting = VMD3_SETTING[rset]

    # Every record must have a position row
    with open(pos_path, newline="") as f:
        rows = list(csv.DictReader(f))
    records = list(read_records(bin_path))
    if len(rows) != len(records):
        raise SystemExit(f"{pos_path.name} has {len(rows)} rows but {bin_path.name} has {len(records)} records")

    # RADC frames with their time and position, plus the DONE counter that follows each one
    sign = -1 if flipX else 1
    frames = []
    for (tag, record), row in zip(records, rows):
        if tag == RADC_HEADER:
            frames.append([record, float(row["t_s"]), sign * float(row["x_center_mm"]) / 1000, ""])
        elif tag == DONE_HEADER and frames and frames[-1][3] == "":
            frames[-1][3] = int.from_bytes(record[HEADER_SIZE:], "little")
    if not frames:
        raise SystemExit(f"No RADC frames in {bin_path.name}")

    # Frame size must match the radar mode
    size = HEADER_SIZE + PAYLOAD_BYTES[setting["angle_setting"]]
    if any(len(record) != size for record, *_ in frames):
        raise SystemExit(f"RADC frames don't match RSET {rset} ({setting['angle_setting']}), check --rset")

    # Output stem, refusing to overwrite
    stem = Path(out) if out else DATA_DIR / started.strftime("%Y-%m-%d") / f"galil-{bin_path.stem}"
    stem.parent.mkdir(parents=True, exist_ok=True)
    if Path(f"{stem}.json").exists():
        raise SystemExit(f"{stem.name} already exists in {stem.parent}, pick another --out")

    # Radar frames, frame log, and track, all on the sweep's own clock
    t0 = started.timestamp()
    with open(f"{stem}_radc.bin", "wb") as fb, open(f"{stem}_frames.csv", "w", newline="") as fl, \
         open(f"{stem}_track.csv", "w", newline="") as ft:
        log, track = csv.writer(fl), csv.writer(ft)
        log.writerow(["frame", "time_unix", "elapsed_s", "radar_counter", "mark", "radc"])
        track.writerow(["time_unix", "x_m"])
        for k, (record, t, x, counter) in enumerate(frames):
            fb.write(record)
            log.writerow([k, f"{t0 + t:.4f}", f"{t:.4f}", counter, "", 1])
            track.writerow([f"{t0 + t:.4f}", f"{x:.6f}"])

    # Missed frames from the DONE counter, if it was recorded
    counters = [c for *_, c in frames if c != ""]
    missed = sum(max(0, b - a - 1) for a, b in zip(counters, counters[1:])) if counters else None

    # Metadata in the same layout record.py writes
    meta = {
        "rset": rset,
        "vmd3_setting": setting,
        "outputs": ["radc"],
        "start_time": started.isoformat(timespec="seconds"),
        "end_time": datetime.fromtimestamp(t0 + frames[-1][1], HST).isoformat(timespec="seconds"),
        "duration_s": round(frames[-1][1], 3),
        "frame_count": len(frames),
        "output_counts": {"radc": len(frames)},
        "frame_sizes": {"radc": size},
        "frames_missed_estimate": missed,
        "marks": [],
        "source": {"galil_bin": bin_path.name, "flip_x": flipX},
    }
    with open(f"{stem}.json", "w") as f:
        json.dump(meta, f, indent=2)

    xs = [x for _, _, x, _ in frames]
    print(f"{len(frames)} RADC frames, RSET {rset} ({setting['angle_setting']}), x {xs[0] * 100:+.1f} to {xs[-1] * 100:+.1f} cm")
    print(f"Missed frames: {'not recorded' if missed is None else missed}")
    print(f"Saved {stem}_*")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert a Galil rail sweep for sar_image.py")
    parser.add_argument("bin", help="Galil sweep .bin, with its _positions.csv beside it")
    parser.add_argument("--rset", type=int, default=0, help="Radar mode if scan_log.csv is missing. Default: 0")
    parser.add_argument("--out", default=None, help="Output stem. Default: data/<date>/galil-<name>")
    parser.add_argument("--flipX", action="store_true", help="Mirror positions if the stage's right is the radar's left")
    args = parser.parse_args()

    main(args.bin, args.rset, args.out, args.flipX)