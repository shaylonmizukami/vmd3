# V-MD3 Code Walkthrough

This document walks through the three files that make up the V-MD3 recording and analysis pipeline:

1. **`record-revise.py`** — the recorder that streams RADC frames from the radar over Ethernet and writes them to disk
2. **`vmd3_process_bin_copy.m`** — the MATLAB post-processing script that extracts target displacement from a saved `.bin` file
3. **`vmd3.py`** — the underlying library that handles the V-MD3's network protocol and frame decoding

---

## 'record-revise.py' — what happens, step by step

### Setup and imports

- Imports `VMD3` (the radar driver class) and `RdotConfig` (an enum listing the radar's possible output types like RADC, RFFT, PDAT, etc.) from `lib/vmd3.py`
- Imports `socket`, `numpy`, `signal`, `os`, `sys`, `argparse`, and `datetime` for networking, math, Ctrl+C handling, file I/O, command-line args, and timestamps
- Defines a global `running = True` flag that will be flipped to `False` when you press Ctrl+C

### Ctrl+C handler

- Registers a handler function so that pressing Ctrl+C in the terminal flips `running` to `False` instead of crashing the program
- The handler prints a message saying it received the interrupt and is about to stop after the current frame
- This is what lets you cleanly stop a recording without losing the last frame

### The '_RSET_INFO' lookup table

- A dictionary mapping each RSET mode number (0–8) to a tuple of (max range in meters, max speed in km/h, number of chirps per frame)
- Used by the live readout to convert range bin index into meters and Doppler bin index into km/h
- Just a hardcoded copy of the relevant parts of the datasheet's Table 3

### The quick_target_readout() function

- Takes a single radar frame's payload and figures out where the strongest target is in range and velocity
- Decodes the raw I/Q bytes into a complex 3D cube (samples × chirps × channels) using `decode_radc_2d` or `decode_radc_3d`
- Runs a range FFT (across samples) and a Doppler FFT (across chirps) to build a 2D range-Doppler map of the scene
- Averages magnitude across all RX channels to clean up the map
- **Applies the leakage mask** — zeroes out the first ~20 range bins (which are dominated by TX→RX leakage out to about 94 cm at RSET 0), so the argmax doesn't lock onto that artifact
- Finds the brightest pixel in the masked map, converts bin indices to physical units, and returns `(range_m, speed_kmh, magnitude)`
- This whole function is just for the live terminal readout — it has nothing to do with what gets saved to disk

### The 'connect_with_interrupt()' function

This is the connection-setup wrapper that makes the entire startup phase Ctrl+C-responsive. It's needed because the stock `VMD3()` constructor blocks indefinitely on `socket.connect()` — if the radar isn't powered, isn't on the right subnet, or is still booting, the program would hang and Ctrl+C wouldn't get through.

What it does:

- Manually creates the TCP socket with a **3-second timeout** so individual `connect()` attempts can't hang forever
- Tries up to **3 attempts** to reach `192.168.100.201:6172`, with retry messages on `socket.timeout` or `ConnectionRefusedError`
- After every attempt, checks the `running` flag — if you pressed Ctrl+C during the retry loop, it bails cleanly
- On success, switches the socket back to blocking mode (the rest of the protocol setup is fast and doesn't need a timeout)
- Constructs the `VMD3` object in `standalone=True` mode so its constructor *doesn't* try to open its own sockets, then attaches the pre-built TCP socket
- Opens the UDP socket on port 4567 and attaches that too
- Calls `vmd3.connect()` to send the `INIT` handshake
- Returns the fully-prepared `VMD3` object, or `None` if the user aborted or all retries failed

If you see "Failed to connect after 3 attempts" or "TCP connect timed out (attempt N/3), retrying...", this function is where those messages come from.

### The 'main()' function — recording loop setup

- **Date-based subfolder:** auto-creates a subdirectory inside `--filePath` named after today's date, e.g. `data/radc/2026-05-25/`. Every recording made today goes into the same dated folder.
- Builds the full output path: `data/radc/YYYY-MM-DD/{fileName}.bin`
- **File-collision handling** — checks if that path already exists and acts according to the `--onExists` flag:
  - `overwrite` — replaces the existing file silently, just prints a notice
  - `append` (default) — auto-appends `_1`, `_2`, `_3`, … to the filename until it finds an unused name, then uses that. So if `plate_3m_run1.bin` exists, it'll save to `plate_3m_run1_1.bin`. If that also exists, `plate_3m_run1_2.bin`, etc.
  - `fail` — prints an error and aborts without recording, telling you to pick a different `--fileName` or change the flag
- Calls `connect_with_interrupt()` to set up the radar connection — if it returns `None`, exits without recording
- Sends `RSET` with the chosen mode (0–8) to configure the radar's chirp parameters
- Sends `RDOT` with the `RADC` flag, telling the radar to start streaming raw ADC frames
- Sets a 1-second timeout on the UDP socket — this is what makes Ctrl+C actually responsive during recording (without it, the UDP recv would block forever and Ctrl+C wouldn't be checked)
- Opens the output `.bin` file for binary write
- Prints "Press Ctrl+C to stop" and starts the recording loop

### The main loop — what runs continuously during recording

- Calls `vmd3.read_frame(b'RADC')` to read one complete RADC frame from the radar via UDP. This may take up to ~130 ms (one frame interval) and internally reassembles ~90 small UDP packets into one full frame.
- If the recv times out (1 second of no data), the loop just continues — gives Ctrl+C a chance to be processed
- Writes the full frame (8-byte header + 131072 or 196608 byte payload) directly to the `.bin` file — this is the actual recording
- Increments the frame counter and byte count
- Every frame (because `n_frames % 1 == 0`), runs the live readout: passes the payload to `quick_target_readout`, gets the target's range and speed back, prints a status line like `frame 142  0:00:18.5  18.6 MB  target: 1.92 m  -0.31 km/h`
- Repeats until Ctrl+C flips the `running` flag

### Cleanup at exit

- The `finally` block runs no matter how the loop exits (Ctrl+C or error)
- Closes the output file (flushes any buffered data to disk)
- Sends `GBYE` to the radar to cleanly disconnect (closes the TCP and UDP sockets)
- Prints a summary of how many frames and bytes were saved

### Command-line argument parsing

- `--mode N` (default `0`): the RSET preset to use. `0` = 2D/6m/10kmh/128×64 (recommended for short-range bench work), `6` = 3D/6m/10kmh/128×32. See datasheet Table 3 for the full list.
- `--filePath` (default `data/radc`): the parent directory to save `.bin` files into. The script automatically appends a `YYYY-MM-DD/` subfolder under this.
- `--fileName` (default current timestamp like `2026-05-25_14-30-22`): the name of the `.bin` file, without extension
- `--onExists` (default `append`): how to handle a name collision — `overwrite`, `append`, or `fail`. See "File-collision handling" above.

---

## 'vmd3_process_bin_copy.m' — what happens, step by step

### Setup and parameters at the top

- `BINARY_FILEPATH`: path to the `.bin` file you want to process — change this for each recording
- `CONFIG_MODE`: `"2D"` or `"3D"` — must match what the recording used (mismatch causes the decoders to reject frames)
- `MAX_RANGE`: the radar's max range in meters for the recorded mode (6 for RSET 0/6, 10 for RSET 1/7, etc.)
- `MAX_ANGLE_RANGE`, `BF1_ANGLE`, `BF2_ANGLE`: declared at the top but **not actually used** anywhere in the current script. Carry-overs from a beamforming-aware version. Safe to delete or ignore.
- `TIME_STEP`: 0.13 seconds, the radar's frame period (one frame every 130 ms)
- `SAMPLE_FREQ`: 1/TIME_STEP ≈ 7.69 Hz, the slow-time sampling rate (how often you see the target)
- `HEADER_TO_PROCESS`: `'RADC'` — the 4-byte string that marks the start of each frame in the `.bin` file
- `SLOW_TIME_SAMPLES`, `BF1_SLOW_TIME_SAMPLES`, `BF2_SLOW_TIME_SAMPLES`, `FAST_TIME_PLOTS_INITIALIZED`: also unused leftovers from an older version. Can be removed.

### Frame extraction — 'get_frames()' function

- Reads the entire `.bin` file as raw bytes
- Searches for every occurrence of the bytes `'RADC'` in the file
- For each candidate position, reads the 4-byte length field that follows the header and checks if it matches the expected size for the configured mode (131072 bytes for 2D, 196608 for 3D)
- If the length matches and the payload doesn't accidentally contain another `'RADC'` substring, accepts the frame as valid
- Returns a cell array of all valid frame payloads (just the data, headers stripped)

### Frame decoding — 'decode_radc_2d()' and 'decode_radc_3d()'

- Takes one frame's raw byte payload and unpacks it into a complex-valued 3D array
- For 2D: shape (128 samples × 64 chirps × 4 RX channels)
- For 3D: shape (128 samples × 32 chirps × 12 virtual channels)
- The unpacking knows the V-MD3's specific byte interleave: I/Q values per sample, 4 RX channels per sweep, multiple sweeps per frame
- Output is a complex MATLAB array ready for FFT processing

### The main processing loop

For each frame in the recording, the script does the following:

- Decodes the frame's bytes into a complex cube
- Runs a **range FFT** across the samples axis. This converts the 128 fast-time ADC samples per chirp into 128 range bins. After this, the cube is (range × chirps × channels), still complex.
- Computes the **range profile** by averaging the magnitude of the range FFT across chirps and channels. This gives one number per range bin representing how strong the reflection is from each distance.
- **On the first frame only**, finds where the target is by looking for the strongest range bin (excluding the first 10 bins to skip the TX→RX leakage). Locks this bin index for all subsequent frames so that the same physical target is tracked throughout.
- Extracts the **complex value at that target range bin**, averaged across all chirps and all RX channels. Each frame contributes one complex number — the I/Q value representing the target's reflection at that frame.
- Stores it in `slow_time_signal(i)`

After this loop, `slow_time_signal` is a 1D complex array — one value per frame — that encodes everything the radar saw at the target's range bin throughout the entire recording.

### Phase-to-displacement conversion

- `LAMBDA = 3e8 / 61.7e9` computes the wavelength at the radar's center frequency, about 4.86 mm
- `phase_raw = angle(slow_time_signal)` extracts the phase of each complex sample, wrapped to the range -π to +π
- `phase_unwrapped = unwrap(phase_raw)` corrects 2π jumps so the phase becomes a continuous smooth signal
- `phase_detrended = detrend(phase_unwrapped)` subtracts a best-fit straight line from the phase, removing slow drift and the constant offset corresponding to the target's nominal range
- `displacement_mm = -phase_detrended * LAMBDA / (4*pi) * 1000` converts radians to millimeters using the FMCW round-trip phase relationship. The result is the target's displacement from its starting position over time, in mm.

### Plot 1 — Displacement vs time

- Plots the calculated `displacement_mm` against time
- This is the "money plot" showing the target's actual motion in physical units
- For a sinusoidally-moving target, this should be a clean sine wave at the drive frequency

### Plot 2 — Magnitude vs time |s[n]|

- Plots `abs(slow_time_signal)` against time
- Shows how strong the radar reflection is at each frame
- For a steady target, should be nearly flat with some small modulation from speckle/multipath effects
- A useful sanity check that the radar is consistently seeing the target

### Plot 3 — I and Q vs time

- Computes I = real part of `slow_time_signal`, Q = imag part
- Plots both on the same axes with a legend
- Shows the "raw" rectangular form of the complex signal
- For sinusoidal target motion, I and Q oscillate at varying rates depending on instantaneous velocity — they don't oscillate at the drive frequency directly because each cycle of the drive produces many cycles of phase rotation

### Plot 4 — I/Q constellation

- Plots Q against I as a scatter plot (no time axis)
- Each frame is one dot
- For a clean recording, the dots trace a circular arc (or full circle, if motion exceeds half a wavelength)
- The radius of the circle = signal magnitude
- "Fuzz" in the line = phase noise. A tight, well-defined circle means low noise; a fuzzy scatter means more noise
- This is the most diagnostic plot for coherence quality

### Plot 5 — Displacement spectrum

- Takes the `displacement_mm` signal, subtracts its mean (removes any DC residual)
- Zero-pads to 4096 samples for finer frequency-bin spacing
- Computes the FFT and plots its magnitude against frequency
- Zooms the X-axis to 0–2 Hz where the motion frequency lives
- For sinusoidal motion at 0.3 Hz, should show a sharp clean peak at 0.3 Hz with no significant peaks elsewhere

### Unused helper functions at the bottom

The file also defines `plot_time_domain()` and `plot_freq_domain()` at the bottom, but neither is called by the main script. They're carry-overs from an earlier version of the pipeline and can be deleted without affecting anything.

---

## `vmd3.py` — the underlying library

This is the file that both `record-revise.py` and (conceptually) the MATLAB script depend on. It defines the network protocol for talking to the V-MD3 over Ethernet and the byte-level decoders for unpacking RADC frames into usable complex arrays.

### The 'RdotConfig' enum

A bit-flag enum listing every kind of output the V-MD3 can be configured to stream. Each value is a single bit, so you can OR them together to request multiple outputs simultaneously.

- `DISABLED = 0`
- `RADC = 0x01` — raw ADC samples (what we use)
- `RFFT = 0x02` — radar's own range-Doppler FFT output
- `RMRD = 0x04` — mean range-Doppler map in dB
- `PDAT = 0x08` — detected target list
- `TDAT = 0x10` — tracked target list
- `DONE = 0x20` — end-of-frame marker

You pass a list of these to `set_output_config()`, e.g. `set_output_config([RdotConfig.RADC])` to request only raw ADC.

### The 'VMD3' class — constructor

Takes optional arguments for the IP addresses and port numbers (defaulting to the V-MD3's standard `192.168.100.201:6172` for TCP and `0.0.0.0:4567` for UDP).

Has two modes:

- **Normal mode** (`standalone=False`, the default): immediately opens both the TCP socket (with `connect()`) and the UDP socket (with `bind()`) inside the constructor. If either fails, prints an error and exits. This is the simple, one-line way to use the class.
- **Standalone mode** (`standalone=True`): the constructor returns immediately without opening any sockets. You're expected to attach pre-built `sockTCP` and `sockUDP` attributes manually. This is what `record-revise.py`'s `connect_with_interrupt()` uses so it can give the TCP socket a timeout *before* trying to connect, making the startup phase Ctrl+C-friendly.

### 'connect()' — the INIT handshake

- Builds a command frame: 4-byte header `"INIT"` + 4-byte little-endian payload length (zero, since INIT has no payload)
- Sends it over TCP
- Reads the 9-byte response back
- Byte 8 of the response is the ack code — 0 means success, anything else means the radar didn't accept the command (and the script exits)

### 'disconnect()' — the GBYE handshake

- Sends a `"GBYE"` command frame (same structure as INIT, zero payload)
- Reads the ack response
- Closes both the TCP and UDP sockets
- Returns `True` on clean disconnect, `False` if the radar didn't ack

### 'set_rset_config(rset_config)'

Configures the radar's range/speed/dimensionality preset (the RSET mode, 0–8). Builds a command frame: header `"RSET"` + 4-byte payload length (4) + 4-byte little-endian RSET value. Sends over TCP, checks the ack byte, exits on error.

### 'set_output_config(rdot_configs)'

Tells the radar which data types to stream. Takes a list of `RdotConfig` values and ORs their numeric values together into a single bitmask. Builds a `"RDOT"` command frame with that bitmask as the 4-byte payload. Sends over TCP and waits for the ack.

After this call, the radar starts streaming the requested data types over UDP, and `read_frame()` can be called repeatedly to receive them.

### 'read_frame(header_requested)'

This is the core data-receive function. It reassembles a complete radar frame from multiple UDP packets.

What it does:

- Reads one UDP packet (up to 1500 bytes, the MTU size)
- Checks the first 4 bytes — if they don't match the requested header (e.g. `b'RADC'`), discards the packet and reads again. This skips over frame types you didn't ask for.
- Reads bytes 4–7 to get the total payload length (little-endian uint32)
- Keeps reading more UDP packets and appending them until the accumulated buffer is at least as long as the declared payload length
- Sanity-checks that the header still matches and the length matches what was promised
- Returns the complete reassembled frame (header + payload)

A single RADC frame in 2D mode is 131,072 bytes of payload + 8 bytes of header = 131,080 bytes total, which requires roughly ~90 UDP packets to be stitched together.

### 'send_tcp()' / 'recv_tcp()' / 'recv_udp()'

The low-level socket helpers:

- `send_tcp(frame)`: just sends bytes on the TCP socket
- `recv_tcp()`: receives a 9-byte command response from the radar in 8-byte chunks (because the firmware's response size is 9 bytes — header ack + status byte)
- `recv_udp()`: receives a single UDP packet up to 1500 bytes from the radar's data stream

### 'decode_radc_2d(frame)'

Unpacks a 131,072-byte 2D-mode RADC payload into a complex NumPy cube of shape `(128 samples × 64 chirps × 4 channels)`.

The V-MD3's byte layout is interleaved in a specific way:

- The frame is divided into 64 "sweeps" of 2048 bytes each
- Each sweep contains 4 RX channels' worth of data
- Within each channel block (512 bytes), I and Q samples are interleaved, both stored as signed little-endian int16
- The Q samples sit at byte offsets `0, 4, 8, …` within the channel block; the I samples sit at offsets `2, 6, 10, …`

The function:

1. Loops over all 64 sweeps × 4 channels and extracts the I and Q int16 values into per-channel Python lists
2. Combines I and Q into Python complex numbers, one per fast-time sample
3. Reshapes each channel's flat list into a (64 chirps × 128 samples) array, then transposes to (128 samples × 64 chirps)
4. Stacks the 4 channels into a final cube of shape (128 × 64 × 4)

Returns `None` if the frame isn't exactly 131,072 bytes long.

### 'decode_radc_3d(frame)'

Same idea as the 2D decoder, but for 3D mode. Frame size is 196,608 bytes, divided into 32 sweeps × 12 virtual channels. The output cube is shape `(128 samples × 32 chirps × 12 channels)`. The 12 channels are the virtual MIMO channels formed by the 3 TX × 4 RX antenna configuration.

Returns `None` if the frame isn't exactly 196,608 bytes long.

### The 'VMD3_SETTING' table

A list of dictionaries documenting all 9 RSET presets (numbered 1–9 here, but corresponding to RSET values 0–8 in the protocol). Each entry records:

- `max_range` (meters)
- `max_speed` (km/h)
- `num_samples` (always 128)
- `num_chirps` (64 for 2D modes, 32 for 3D modes)
- `angle_setting` (`'2D'` or `'3D'`)
- `frame_rate` (always 130 ms)
- `range_resolution` (cm) — depends on max_range
- `speed_resolution` (km/h) — depends on max_speed and num_chirps

This table isn't used directly by `record-revise.py` (which has its own simpler `_RSET_INFO` lookup) but is useful as a reference for picking a mode or for downstream analysis scripts that need to know the resolution.

---

## A high-level mental model

If you take a step back, all three files together implement this pipeline:

1. **`vmd3.py`** provides the building blocks: protocol commands (INIT/RSET/RDOT/GBYE), UDP frame reassembly, and byte-level I/Q decoding
2. **`record-revise.py`** uses those building blocks to capture raw I/Q data from the radar and write it to disk as fast as possible, while showing a live target-range readout for situational awareness. It adds robustness features around connection (timeouts, retries, Ctrl+C-responsiveness) and file management (dated subfolders, collision handling).
3. **MATLAB script** loads that saved I/Q data, does a range FFT to figure out which range bin the target is in, then watches how the complex value in that one specific range bin evolves over time
4. The phase of that complex value tells you displacement (with sub-millimeter precision derived from the radar's wavelength, not from range bin width)
5. The magnitude tells you reflection strength
6. The FFT of the displacement gives you the motion frequency content

The whole reason this works for sub-mm displacement is that I/Q data preserves phase, and phase encodes sub-bin position. If `record-revise.py` were saving only magnitudes (just `|s|` rather than `I + jQ`), none of the displacement extraction in MATLAB would work. The chain from ADC to displacement plot is entirely dependent on preserving complex-valued data through every step.

---

## What does RADC mean?

RADC stands for **Raw ADC** — the raw analog-to-digital converter samples from the radar's RX antennas (4 in 2D mode, 12 virtual channels in 3D mode), before any processing. It's the lowest-level data the V-MD3 will give you over the network.

It's one of five output types the radar can stream, listed in datasheet Table 11:

- **RADC** — Raw ADC samples (what you record)
- **RFFT** — Raw range-Doppler FFT (radar has already done the FFTs for you)
- **RMRD** — Mean range-Doppler map (averaged across channels, in dB)
- **PDAT** — Detected raw target list (range, speed, angle of each target)
- **TDAT** — Tracked target list (filtered, with track IDs)

By selecting RADC in `record-revise.py`, you're saying "give me the raw I/Q samples and I'll do all the processing myself." That's why your `.bin` files are large and contain all the underlying complex data, rather than just a list of target detections.
