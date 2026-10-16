# Dog Field Runbook

`[Laptop]` = Konsole on the laptop (`shaylon@x1carbon`)
`[Jetson]` = SSH'd into the Jetson (`unitree@ubuntu`)

Follow in order.

---

## Known Setup

| Item | Value |
|---|---|
| Dog network | Wired, `192.168.123.x` |
| Laptop wired address | `192.168.123.10/24`, gateway `192.168.123.1` (`Wired connection 1`) |
| Jetson IP | `192.168.123.18` |
| Jetson username | `unitree` |
| Jetson password | |
| Dog main controller | `192.168.123.161` (answers ping) |
| Jetson `eth0` | Dog's internal network. Never touch |
| Jetson `eth1` | Radar port |
| Code folder on Jetson | `~/radar_scripts/vmd3-dog` |
| Python version | |
| Dog power port voltage | |

---

## Pack List

- VMD3, data cable (M12 D-coded to RJ45), power cable (M12 A-coded)
- Mount and hardware
- ISO target, tape measure, phone level or angle gauge
- Laptop charged, venv working offline, this runbook saved offline
- Phone for the stopwatch backup

---

## Before Leaving

- Pi rehearsal passed with the current code (`pi-rehearsal.md`)
- Laptop clock synced to the internet
- `jetson` block in `~/.ssh/config`:
```
Host jetson
    HostName 192.168.123.18
    User unitree
    HostKeyAlias jetson
    ServerAliveInterval 10
    ServerAliveCountMax 3
```

---

## 1. Hardware

1. Confirm the dog port voltage and pinout match the VMD3 input. If unsure, stop
2. Mount the radar right side up, RX array horizontal, ~45° down, boresight forward
3. Radar data cable into the Jetson's `eth1` port
4. Radar power from the dog

Radar upside down = left and right swap. Flip `ANGLE_SIGN` in `config.py` for processing.

---

## 2. Connect

Laptop wired to the dog `[Laptop]`
```
nmcli connection up "Wired connection 1"
ping -c 3 192.168.123.161
ssh jetson
```

First time on a laptop with firewalld `[Laptop]`
```
sudo firewall-cmd --permanent --zone=trusted --add-source=192.168.123.18
sudo firewall-cmd --reload
```

---

## 3. Clock

`[Laptop]`
```
ssh -t jetson "sudo date -s @$(date +%s)"
```

---

## 4. Pre-checks

`[Jetson]`
```
date
python3 --version
tmux -V
df -h ~
ip -br a
```

- `date`: matches the laptop
- `tmux` missing: use the `nohup` fallback in section 9
- `df`: ~60 MB free per minute of RADC
- `ip -br a`: `eth0` holds `192.168.123.18`, `eth1` is the radar port

---

## 5. Push Code

Only the five recording files `[Laptop]`
```
rsync -av --include='config.py' --include='initradar.sh' --include='record.py' --include='lib/' --include='lib/__init__.py' --include='lib/vmd3.py' --exclude='*' ~/Projects/vmd3/vmd3-dog/ jetson:~/radar_scripts/vmd3-dog/
```

Add `-n` first to preview without copying.

---

## 6. Init Radar

`eth1` comes preconfigured with `192.168.100.201`, the radar's own address. The Jetson then answers its own pings and refuses the radar connection. Free it every boot.

`[Jetson]`
```
cd ~/radar_scripts/vmd3-dog
sudo ip addr del 192.168.100.201/16 dev eth1
sudo ./initradar.sh eth1
ip route get 192.168.100.201
python3 -c "import socket; s = socket.create_connection(('192.168.100.201', 6172), timeout=3); print('TCP ok')"
```

- `Cannot assign requested address` on the `del` line: already gone, fine
- `ip route get` must name `eth1`, never `local ... dev lo`
- `TCP ok` before moving on

Never run `initradar.sh` without `eth1`. The default `eth0` is the dog's network.

---

## 7. Test Capture

`[Jetson]`
```
python3 record.py --duration 10 --fileName test
```

Expect ~130 ms per frame after frame 2, `Counter` climbing by 1, `Missed 0`.

---

## 8. Capture Plan

| Run | Procedure | Purpose |
|---|---|---|
| Walk | Start at the mark, walk out, stand 3 min with target, remove target, 1 min empty, walk back | Heatmap, background subtraction, standing stability |
| Sitting | Dog sits facing the target, 2 min with target, stop. Remove target, 1 min empty | Sitting stability and subtraction |

- Tape-mark where the dog stands and sits
- Note range, angle, radar height, and tilt to the target
- RADC only unless checking RFFT

---

## 9. Record

`[Jetson]`
```
tmux new -s radar
python3 record.py --fileName walk-1
```

- Start the phone stopwatch at the same moment
- Type a label and Enter at each event: `stand`, `removed`, `back`
- Lap the stopwatch at each event as backup
- Detach: `Ctrl-b` then `d`

No tmux `[Jetson]`
```
nohup python3 record.py --fileName walk-1 > run.log 2>&1 &
tail -f run.log
```
Stop later with `pkill -INT -f record.py`. Marks can't be typed with `nohup`, use the stopwatch.

---

## 10. Stop and Pull

`[Jetson]`
```
tmux attach -t radar
```
`Ctrl-c`, expect `Stopped by user`, then `exit`.

`[Laptop]`
```
rsync -av jetson:~/radar_scripts/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/
cat ~/Projects/vmd3/vmd3-dog/data/*/walk-1.json
```

- `frames_missed_estimate` is 0
- `marks` lists your labels

---

## 11. Check On Site

`[Laptop]` from `~/Projects/vmd3/vmd3-dog` with the venv active
```
python replay.py data/<date>/walk-1 --maxRange 3
```

- Target visible where you measured it: move on
- Missing or wrong spot: fix the mount or target and retake

---

## 12. Field Notes

| Run | Start | Stand / sit | Target removed | Back | Range | Angle | Height / tilt | Notes |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
| | | | | | | | | |

---

## 13. Wrap Up

1. Data on the laptop and checked
2. Unplug radar power, then data
3. Remove code only if the owner wants: `rm -rf ~/radar_scripts/vmd3-dog`
4. Don't shut down the Jetson unless the owner says to
5. Tell the owner `eth1` had `.201` removed for the session, it returns on reboot

---

## 14. Recovery

### Jetson unreachable at `.18`

Happens if `eth0` was handed to NetworkManager (`nmcli device set eth0 managed yes`). Never run that.

From the Jetson's own screen and keyboard:
```
sudo reboot
```
Or from the laptop, find it another way first:
```
nmap -sn 192.168.123.0/24
ssh unitree@ubuntu.local
```
Last resort: power cycle the dog with the owner's OK. Everything changed for a session resets on reboot.

### TCP refused but ping works

`.201` is local on the Jetson. Check with `ip route get 192.168.100.201`, then section 6.

---

## 15. Common Errors

| Output | Fix |
|---|---|
| `[VMD3] Error while connecting with TCP/IP socket` | Section 6, `.201` still on `eth1` |
| `ConnectionRefusedError` on the TCP test | Same as above |
| `local 192.168.100.201 dev lo` | `sudo ip addr del 192.168.100.201/16 dev eth1` |
| `Destination Host Unreachable` to `.18` | Section 14 |
| `No link on eth1` | Radar data cable or radar power |
| `<name> already exists in ...` | Use the next run number |
| `ModuleNotFoundError` | Not in `~/radar_scripts/vmd3-dog`, or files not pushed |
| Folder date wrong | Section 3 |
| `no sessions` on attach | Recording ended or never started in tmux |
| `No data from radar for 2 s` | Cable knocked loose, check mount |
| `Missed` climbing | Real drops, check data cable |
