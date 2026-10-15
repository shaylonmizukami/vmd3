# Dog Field Runbook

`[Laptop]` = Konsole on the laptop (`shaylon@x1carbon`)
`[Jetson]` = SSH'd into the Jetson

Follow in order. Fill in the blanks with the owner before starting.

---

## Fill In

| Item | Value |
|---|---|
| Dog WiFi network | |
| Dog WiFi password | |
| Jetson IP | |
| Jetson username | |
| Jetson password | |
| Radar interface | |
| Python version | |
| Dog power port voltage | |
| Dog power port pinout matches VMD3 | yes / no |

---

## Pack List

- VMD3
- M12 D-coded to RJ45 cable (data)
- M12 A-coded power cable
- Mount and hardware
- USB Ethernet adapter (if the Jetson's port is taken)
- Target and tape measure
- Phone level or angle gauge
- Laptop, charged
- This runbook, saved offline

---

## Before Leaving

- Pi rehearsal passed with the current code (`pi-rehearsal.md`)
- Code on the laptop is the final version
- `jetson` block in `~/.ssh/config` filled in where known

---

## 1. Hardware

1. Confirm dog port voltage and pinout match the VMD3 input. If unsure, stop
2. Mount the radar right side up, RX array horizontal, ~45° down, boresight forward
3. Data cable to the Jetson (not plugged in yet, needed for step 4)
4. Power cable to the dog

Radar upside down = left and right swap. Flip `ANGLE_SIGN` in `config.py` for processing.

---

## 2. Connect

`[Laptop]`
```
nmcli device wifi rescan
sleep 5
nmcli device wifi connect "<dog wifi>" --ask
ssh <user>@<jetson ip>
```

Type `yes` at the fingerprint prompt. Then `exit` and update `~/.ssh/config`:
```
Host jetson
    HostName <jetson ip>
    User <user>
    HostKeyAlias jetson
    ServerAliveInterval 10
    ServerAliveCountMax 3
```

Unknown IP `[Laptop]`
```
ip route | grep default
ip neigh
```

---

## 3. Clock

`[Laptop]`
```
ssh -t jetson "sudo date -s @$(date +%s)"
```

---

## 4. Pre-checks

`[Laptop]`
```
ssh jetson
```

`[Jetson]`
```
date
python3 --version
tmux -V
rsync --version
df -h ~
ip route | grep 192.168.100
```

- `date`: matches the laptop
- `python3`: 3.8 or newer
- `tmux` missing: use the `nohup` fallback in section 8
- `rsync` missing: use `scp -r` in sections 5 and 10
- `df`: ~60 MB free per minute per output
- `ip route | grep 192.168.100`: must print nothing. Anything = subnet clash, stop and ask the owner

Find the radar interface `[Jetson]`
```
ip -br a
```
Plug the radar data cable in, then
```
ip -br a
```
The one that changed to `UP` is the radar port. Never use the dog's internal interface.

---

## 5. Push Code

`[Laptop]`
```
rsync -av --filter=':- .gitignore' ~/Projects/vmd3/vmd3-dog/ jetson:~/vmd3-dog/
```

No rsync `[Laptop]`
```
scp -r ~/Projects/vmd3/vmd3-dog jetson:~/
```

---

## 6. Init Radar

`[Jetson]`
```
cd ~/vmd3-dog
sudo ./initradar.sh <interface>
```

`[!] ufw is active`: ask the owner before `sudo ufw allow 4567/udp`.

---

## 7. Test Capture

At the start position `[Jetson]`
```
python3 record.py --duration 10 --fileName test
```

Expect ~130 ms per frame after frame 2, `Counter` climbing by 1, `Missed 0`.

---

## 8. Record

`[Jetson]`
```
tmux new -s radar
python3 record.py --fileName dog-run-1
```

Add `--outputs radc rfft` to also save RFFT.

Detach: `Ctrl-b` then `d`

No tmux `[Jetson]`
```
cd ~/vmd3-dog
nohup python3 record.py --fileName dog-run-1 > run.log 2>&1 &
tail -f run.log
```
`Ctrl-c` stops `tail` only. Stop the recording later with `pkill -INT -f record.py`.

---

## 9. Walk

1. Note start time: `[Laptop]` `date`
2. Walk the dog to the target
3. Stop with the target at boresight
4. Note arrival time
5. Hold still ~60 s
6. Note departure time
7. Walk back to start

Link may drop. Recording keeps going.

---

## 10. Stop and Pull

`[Laptop]`
```
ssh jetson
```

`[Jetson]`
```
tmux attach -t radar
```
`Ctrl-c`, expect `Stopped by user`, then `exit`.

`[Laptop]`
```
rsync -av jetson:~/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/
cat ~/Projects/vmd3/vmd3-dog/data/*/dog-run-1.json
```

No rsync `[Laptop]`
```
scp -r jetson:~/vmd3-dog/data ~/Projects/vmd3/vmd3-dog/
```

Check:
- `frames_missed_estimate` is 0
- `output_counts` matches `frame_count`

---

## 11. Process

`[Laptop]` from `~/Projects/vmd3/vmd3-dog` with the venv active

Find the standing segment
```
python replay.py data/<date>/dog-run-1 --maxRange 3
python replay.py data/<date>/dog-run-1 --maxRange 3 --doppler all
```
Title shows each frame's clock time. Zero Doppler hides the walk, all Doppler shows it.

Heatmap of the standing segment
```
python heatmap.py data/<date>/dog-run-1 --startClock <arrive> --endClock <depart> --maxRange 3
```

Plot lands in `data/<date>/plots/`.

---

## 12. Field Notes

| Run | Start | Arrive | Depart | Range to target | Angle | Target | Notes |
|---|---|---|---|---|---|---|---|
| dog-run-1 | | | | | | | |
| dog-run-2 | | | | | | | |

Arrive and depart times feed `--startClock` and `--endClock`.

---

## 13. Wrap Up

1. Data on the laptop and checked
2. Unplug radar power, then data
3. Remove code only if the owner wants `[Jetson]` `rm -rf ~/vmd3-dog`
4. Don't shut down the Jetson unless the owner says to

---

## 14. Common Errors

| Output | Fix |
|---|---|
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | `ssh-keygen -R jetson` |
| `Permission denied` on SSH | Wrong user or password |
| `<interface> not found` | Recheck `ip -br a`, section 4 |
| `No link on <interface>` | Cable or radar power |
| `No reply from 192.168.100.201` | Wait ~10 s after radar power up, rerun |
| `<name> already exists in ...` | Use the next run number |
| `ModuleNotFoundError` | Code not pushed, nested folder, or not in `~/vmd3-dog` |
| Folder date wrong | Section 3 |
| `no sessions` on attach | Recording ended or never started in tmux |
| `No data from radar for 2 s` | Cable knocked loose on the walk, check mount |
| `Missed` climbing | Real drops, check data cable |
