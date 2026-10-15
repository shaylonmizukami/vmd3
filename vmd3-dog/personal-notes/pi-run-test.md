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
| Init radar | `cd ~/vmd3-dog && sudo ./initradar.sh` |
| Record | `tmux new -s radar` then `python3 record.py --fileName <name>` |
| Detach | `Ctrl-b` then `d` |
| Reattach | `tmux attach -t radar` |
| Pull data | `rsync -av pipi5:~/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/` |
| Check | `python heatmap.py data/<date>/<name> --maxRange 3` |

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
- `df`: ~60 MB free per minute per output
- `tmux ls`: no sessions. Leftover: `tmux kill-session -t radar`

---

## 5. Init Radar

`[Pi]`
```
cd ~/vmd3-dog
sudo ./initradar.sh
```

---

## 6. Record

### Fixed duration

`[Pi]`
```
tmux new -s radar
python3 record.py --duration 120 --fileName <name>
```

### Manual stop

`[Pi]`
```
tmux new -s radar
python3 record.py --fileName <name>
```

### With RFFT

Add `--outputs radc rfft` to either.

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

Scroll back through output while attached: `Ctrl-b` then `[`, arrows or Page Up, `q` to leave.

---

## 9. Pull and Check

`[Laptop]`
```
rsync -av pipi5:~/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/
cd ~/Projects/vmd3/vmd3-dog
ls -l data/*/<name>*
cat data/*/<name>.json
```

| Check | Expected |
|---|---|
| `frames_missed_estimate` | 0 |
| `frame_count` | ≈ (`duration_s` − 0.7) ÷ 0.13 + 1 |
| Each `.bin` size | `output_counts` × 131080 |
| Counter | Consecutive, no gaps |

Size math `[Laptop]`
```
echo $(( <frame_count> * 131080 ))
```

Counter gaps `[Laptop]` (venv active, from `vmd3-dog/`)
```
python -c "
import numpy as np
from lib.capture import read_log
c = read_log('data/<date>/<name>')['radar_counter']
print('gaps:', int(np.sum(np.diff(c) != 1)))
"
```

Heatmap `[Laptop]`
```
python heatmap.py data/<date>/<name> --maxRange 3
```
Peak should land on the target's measured range and angle.

---

## 10. Results So Far

| Run | Format | Stop | Duration | Frames | Missed | Notes |
|---|---|---|---|---|---|---|
| `test-run-1` | old single `.bin` | `--duration 120` | 120.1 s | 919 | 5* | SSH dropped, reattached, saved |
| `test-run-2` | old single `.bin` | `Ctrl-c` | 116.7 s | 893 | 5* | SSH dropped, reattached, stopped |
| `both-test-2` | radc + rfft | `--duration 10` | 10.2 s | 73 | 0 | Counter 1 to 73, no gaps |
| `sign-right-3` | radc | `--duration 10` | 10.1 s | 73 | 0 | Target right, peak 1.41 m +29.5° |

\* Old timing-based estimate, fooled by the startup pause. No frames were actually lost.

Old single `.bin` captures don't load with the current `capture.py`.

---

## 11. Common Errors

| Output | Fix |
|---|---|
| `<name> already exists in ...` | Pick another `--fileName` |
| `duplicate session: radar` | `tmux attach -t radar` or `tmux kill-session -t radar` |
| `no sessions` on attach | Recording ended and `exit` was run, or never started in tmux |
| `No such file or directory` on `record.py` | Nested folder, section 3, or not in `~/vmd3-dog` |
| Folder date wrong | Clock not synced, section 1 |
| `Missed` climbing | Real drops, check cable and Pi load |
| `No data from radar for 2 s` | Cable or radar power, rerun `initradar.sh` |
| SSH hangs on reconnect | Pi still booting or laptop not on `pipi5`, `nmcli connection up pipi5` |
