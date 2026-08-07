## Step 1 — Boresight target alone (verification)

**Physical:** boresight plate at (0, 6), radar facing it, drive it at your chosen breathing rate (~0.2–0.3 Hz). Nothing else moving in the scene.

**Record.** No code changes — RSET comes from config:
```bash
python record.py --fileName step1_boresight
```
Let it run through enough cycles of your drive frequency (60–90 s for a clean FFT), then Ctrl+C. Watch the frame counter climb steadily — that's your "frames are flowing" check.

**Process — profile first, to see the target land:**
```bash
python process.py --file data/radc/<date>/step1_boresight.bin --mode profile --avg 10
```
Look for a clean single peak near 6 m. **Note its bin and its width** — that's your step-1 deliverable, and the bin number is what you'll feed manual mode later. (You already know from the old file it'll be around bin 79.)

**Process — motion, to confirm you recover the breathing:**
```bash
python process.py --file data/radc/<date>/step1_boresight.bin --mode motion --targets 1 --auto
```
Check the four figures and the printed numbers: peak-to-peak displacement should match whatever amplitude you set the stage to, and dominant frequency should match your drive rate. If both land, step 1 passes.

**Code you changed for step 1:** nothing but the `--fileName` and `--file` strings. That's the point.

## Step 2 — Angled target alone (the go/no-go)

**Physical:** remove the boresight plate. Place the second plate at (1.61, 6) — 15° off — rotated to face the radar, driven at your breathing rate. Radar unchanged, still staring down boresight.

**Record:**
```bash
python record.py --fileName step2_angled15
```

**Process — profile, and this is the critical read:**
```bash
python process.py --file data/radc/<date>/step2_angled15.bin --mode profile --avg 10
```
Two things to check here that decide the whole experiment: **does a peak appear near ~6.2 m** (bin ~79), and **is it strong enough to stand clearly above the noise floor?** This is where you learn target 2's true SNR through the off-boresight beam. Note its bin.

**Process — motion:**
```bash
python process.py --file data/radc/<date>/step2_angled15.bin --mode motion --targets 1 --auto
```
If you cleanly recover its displacement and frequency, 15° works and you proceed. If the peak is buried or the motion won't come out, that's your signal to either move to a different angle or reconsider — better to know now, with one target, than to be confused in step 3.

**Code you changed for step 2:** just the filenames again.

Two possible snags at this step, both handled without code edits: if auto latches onto a leakage artifact instead of the real peak (possible if target 2 is weak), switch to `--manual <bin>` using the bin you saw in the profile. And note the two single-target bins from steps 1 and 2 might be close (both near 6.0–6.2 m) since target 2 at 15° is only ~0.2 m further — that closeness is exactly what step 3 has to resolve, and why you're recording each alone first to get their true bins.

## Step 3 — Both targets (the actual experiment)

**Physical:** both plates in place — boresight at (0,6), angled at (1.61,6). Here's the one setup decision that matters: **drive them at distinctly different frequencies** (e.g. 0.2 and 0.3 Hz, not 0.2 and 0.25). That difference is your proof of isolation, and the further apart they are, the shorter the capture needed to resolve them. Both moving simultaneously.

**Record — longer capture:** because you now need to resolve two close-ish frequencies, record generously — 90+ seconds. Same command:
```bash
python record.py --fileName step3_both
```

**Process — profile, to confirm two distinct peaks:**
```bash
python process.py --file data/radc/<date>/step3_both.bin --mode profile --avg 10
```
You want to *see two separate peaks*. If they're clearly resolved, great. Note both bins.

**Process — motion, two targets.** Here's the one real judgment call on flags. Auto *can* find both:
```bash
python process.py --file data/radc/<date>/step3_both.bin --mode motion --targets 2 --auto
```
But given the two peaks are close and target 2 may be weak, **manual is safer** — feed it the two bins you measured in steps 1 and 2:
```bash
python process.py --file data/radc/<date>/step3_both.bin --mode motion --targets 2 --manual 79 81
```
(using your actual measured bins). Manual is more robust exactly because you already know where each target lives from the single-target steps — you're not trusting auto to disentangle two close peaks.

**The success criterion:** target 1's bin shows target 1's drive frequency, target 2's bin shows target 2's drive frequency, each clean. Two different frequencies from two different bins = isolation proven. If instead both bins show the *same* frequency, that's leakage winning (the 0.201-Hz-everywhere effect you already saw) — which is when windowing becomes worth adding.

**Code you changed for step 3:** filenames, `--targets 2`, and the `--manual` bins. Still no file edits.

## The overall shape

Notice what you *don't* touch across all three steps: no editing `config.py` between runs (RSET is fixed), no editing any library file, no editing `process.py`. Every per-step difference is a command-line flag — filename, mode, target count, auto vs manual. That's the payoff of the structure. The only decisions that need your judgment are physical (drive frequencies, is target 2 strong enough) and which bins to pass in manual mode — and those come from *reading the figures*, which is exactly the incremental confirm-before-advancing loop you wanted.

One practical tip for step 3's comparison: since all the motion figures pop up at once, put target 1's and target 2's displacement-spectrum windows side by side and confirm the peaks sit at different frequencies. That single visual is the whole experiment's result.
