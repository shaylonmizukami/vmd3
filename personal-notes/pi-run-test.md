# Pi Rehearsal

`[Laptop]` = Konsole on the laptop (`shaylon@x1carbon`)
`[Pi]` = SSH'd into the Pi (`pipi5@pipi5`)

Full dog sequence on the Pi. Rerun whenever the code changes.

---

## Quick Reference

| Step | Command |
|---|---|
| Connect | `nmcli connection up pipi5` |
| Clock | `ssh -t pipi5 "sudo date -s @$(date +%s)"` |
| Push code | `rsync -av --filter=':- .gitignore' ~/Projects/vmd3/vmd3-dog/ pipi5:~/vmd3-dog/` |
| Init radar | `sudo ~/vmd3-dog/initradar.sh` |
| Record | `tmux new -s radar` then `python3 ~/vmd3-dog/record.py --fileName <name>` |
| Detach | `Ctrl-b` then `d` |
| Reattach | `tmux attach -t radar` |
| Pull data | `rsync -av pipi5:~/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/` |

Target at boresight, 1 to 2 m out, so the capture is usable for processing.

---

## 1. Connect and Sync Clock

`[Laptop]`
```
nmcli connection up pipi5
ssh -t pipi5 "sudo date -s @$(date +%s)"
```

---

## 2. Fresh Device

Pull old captures first, then wipe.

`[Laptop]`
```
rsync -av pipi5:~/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/
ssh pipi5 'rm -rf ~/vmd3-dog'
```

Skip this section for a normal retest.

---

## 3. Push Code

`[Laptop]`
```
rsync -av --filter=':- .gitignore' ~/Projects/vmd3/vmd3-dog/ pipi5:~/vmd3-dog/
```

Keep the trailing `/` on the source. Without it you get `~/vmd3-dog/vmd3-dog/`.

Fix if nested `[Pi]`
```
rm -rf ~/vmd3-dog/vmd3-dog
```

---

## 4. Pre-checks

`[Laptop]`
```
ssh pipi5
```

`[Pi]`
```
ls ~/vmd3-dog
date
python3 --version
tmux -V
df -h ~
ip -br a
tmux ls
```

- `ls`: `config.py`, `initradar.sh`, `lib`, `record.py`, no nested `vmd3-dog`
- `date`: matches the laptop
- `df`: ~60 MB free per minute of recording
- `tmux ls`: no sessions. Leftover: `tmux kill-session -t radar`

---

## 5. Init Radar

`[Pi]`
```
sudo ~/vmd3-dog/initradar.sh
```

---

## 6. Record

### Fixed duration

`[Pi]`
```
tmux new -s radar
python3 ~/vmd3-dog/record.py --duration 120 --fileName <name>
```

### Manual stop

`[Pi]`
```
tmux new -s radar
python3 ~/vmd3-dog/record.py --fileName <name>
```

Detach: `Ctrl-b` then `d`

---

## 7. Drop the Connection

Close Konsole, then `[Laptop]`
```
nmcli connection down pipi5
```

Or walk the laptop out of range. Wait at least 30 s.

---

## 8. Reattach

`[Laptop]`
```
nmcli connection up pipi5
ssh pipi5
```

`[Pi]`
```
tmux attach -t radar
```

- Fixed duration: should show `Saved ... frames`
- Manual stop: still running, press `Ctrl-c`, expect `Stopped by user`

Close the session:
```
exit
```

---

## 9. Pull and Check

`[Laptop]`
```
rsync -av pipi5:~/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/
ls -l ~/Projects/vmd3/vmd3-dog/data/*/<name>.*
cat ~/Projects/vmd3/vmd3-dog/data/*/<name>.json
```

| Check | Expected |
|---|---|
| `frame_count` + `frames_missed_estimate` | ≈ `duration_s` ÷ 0.13 |
| `frames_missed_estimate` | 5 (startup gap only) |
| `.bin` size | `frame_count` × 131080 |

Size math `[Laptop]`
```
echo $(( <frame_count> * 131080 ))
```

---

## 10. Results So Far

| Run | Stop | Duration | Frames | Missed | Notes |
|---|---|---|---|---|---|
| `test-run-1` | `--duration 120` | 120.1 s | 919 | 5 | SSH dropped, reattached, saved |
| `test-run-2` | `Ctrl-c` | 116.7 s | 893 | 5 | SSH dropped, reattached, stopped |

---

## 11. Common Errors

| Output | Fix |
|---|---|
| `duplicate session: radar` | `tmux attach -t radar` or `tmux kill-session -t radar` |
| `no sessions` on attach | Recording already ended and `exit` was run, or never started in tmux |
| `No such file or directory` on `record.py` | Nested folder, section 3 |
| Folder date wrong | Clock not synced, section 1 |
| `Missed` climbing past 5 | Disk or CPU busy, check `df -h ~` and other running jobs |
| `No data from radar for 2 s` | Cable or radar power, rerun `initradar.sh` |
| SSH hangs on reconnect | Pi still booting or laptop not on `pipi5`, `nmcli connection up pipi5` |
