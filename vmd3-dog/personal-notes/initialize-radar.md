# Radar Network Setup

`[Laptop]` = Konsole on the laptop (`shaylon@x1carbon`)
`[Pi]` = SSH'd into the Pi (`pipi5@pipi5`)

---

## Quick Reference

| | Address | Interface |
|---|---|---|
| VMD3 radar | `192.168.100.201` (fixed) | |
| Pi radar side | `192.168.100.1/24` | `eth0` |
| Pi WiFi side | `192.168.50.1/24` | `wlan0` |
| Laptop | `192.168.50.x` (auto) | `wlp0s20f3` |
| Laptop USB Ethernet | `192.168.100.1/24` | `enp0s13f0u3u2c2` |

| Port | Use |
|---|---|
| TCP 6172 | Radar control |
| UDP 4567 | Radar frame data |
| TCP 39123 | Optional stream to laptop |

### Every boot

`[Pi]`
```
sudo ~/vmd3-dog/initradar.sh
```

Nothing persists across reboots. Rerun after every boot.

---

## 1. The Two Links

- **Radar link:** VMD3 ↔ Pi `eth0`, `192.168.100.x`, never leaves the platform
- **WiFi link:** Pi `wlan0` ↔ laptop, `192.168.50.x`, carries SSH, rsync, stream
- Laptop never talks to the radar directly

---

## 2. Check Interfaces

`[Pi]` or `[Laptop]`
```
ip -br a
ip route
```

Expected on the Pi with radar up:
```
eth0     UP    192.168.100.1/24
wlan0    UP    192.168.50.1/24

192.168.50.0/24 dev wlan0 ...
192.168.100.0/24 dev eth0 ...
```

`eth0 DOWN` with no address = radar unplugged or script not run yet.

No `default` route = no internet. Expected.

---

## 3. Install the Script

`[Laptop]`
```
chmod +x ~/Projects/vmd3/vmd3-dog/initradar.sh
rsync -av --filter=':- .gitignore' ~/Projects/vmd3/vmd3-dog/ pipi5:~/vmd3-dog/
```

---

## 4. Run the Script

Pi `[Pi]`
```
sudo ~/vmd3-dog/initradar.sh
```

Laptop with USB Ethernet adapter `[Laptop]`
```
sudo ./initradar.sh enp0s13f0u3u2c2
```

Jetson: find the radar's interface first, then pass it in.
```
ip -br a
sudo ./initradar.sh <interface>
```
Don't run it on the interface the dog uses internally.

Expected:
```
[ok] Found eth0
[ok] NetworkManager released eth0
[ok] eth0 at 192.168.100.1/24
[ok] Link up
[ok] Radar responding at 192.168.100.201
```

---

## 5. Common Errors

| Output | Fix |
|---|---|
| `Run with sudo` | Add `sudo` |
| `eth0 not found` | Wrong interface name, check `ip -br a` |
| `No link on eth0` | Cable unplugged or radar off |
| `No reply from 192.168.100.201` | Wait ~10 s after radar power up, rerun |
| `[!] ufw is active` | `sudo ufw allow 4567/udp` (ask owner first on Jetson) |
| `env: 'zsh': No such file or directory` | Shebang must be `bash`, Pi and Jetson have no zsh |
| `Permission denied` running the script | `chmod +x initradar.sh` |

---

## 6. Script Source

`initradar.sh`
```bash
#!/usr/bin/env bash
# Bring up the radar ethernet link and confirm the VMD3 responds.
# Usage: sudo ./initradar.sh [interface] (default: eth0)

set -e

# Network settings
IFACE="${1:-eth0}"
HOST_IP="192.168.100.1/24"
RADAR_IP="192.168.100.201"
UDP_PORT="4567"

# Output helpers
ok() { echo "[ok] $1"; }
fail() { echo "[x] $1"; exit 1; }

# Pre-checks
[[ $EUID -eq 0 ]] || fail "Run with sudo"
ip link show "$IFACE" &>/dev/null || fail "$IFACE not found"
ok "Found $IFACE"

# Stop NetworkManager from fighting over the port
if command -v nmcli &>/dev/null; then
    nmcli device set "$IFACE" managed no
    ok "NetworkManager released $IFACE"
fi

# Bring port up with a static IP (skips if already set)
ip link set "$IFACE" up
if ! ip -br addr show dev "$IFACE" | grep -q "${HOST_IP%/*}/"; then
    ip addr add "$HOST_IP" dev "$IFACE"
fi
ok "$IFACE at $HOST_IP"

# Open the radar data port if a firewall is running
if command -v firewall-cmd &>/dev/null && firewall-cmd --state &>/dev/null; then
    firewall-cmd --add-port="$UDP_PORT/udp" &>/dev/null
    ok "Opened UDP $UDP_PORT (until reboot)"
fi
if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    echo "[!] ufw is active, may need: sudo ufw allow $UDP_PORT/udp"
fi

# Wait up to 10s for a live cable
for i in {1..10}; do
    [[ $(cat /sys/class/net/"$IFACE"/carrier 2>/dev/null) == 1 ]] && break
    [[ $i -eq 10 ]] && fail "No link on $IFACE, check cable and radar power"
    sleep 1
done
ok "Link up"

# Confirm the radar answers
ping -c 3 -W 2 "$RADAR_IP" &>/dev/null || fail "No reply from $RADAR_IP, wait ~10s after radar power up"
ok "Radar responding at $RADAR_IP"
```

---

## 7. Jetson Differences

### Interface name

May not be `eth0`. Common: `eth0`, `enP8p1s0`, `enx...` (USB adapter).

Find it `[Jetson]`
```
ip -br a   # radar unplugged
ip -br a   # radar plugged in, the one that went UP is the radar port
```

Pass it in, no edit needed:
```
sudo ./initradar.sh <interface>
```

To make it the default, edit this line in `initradar.sh`:
```
IFACE="${1:-eth0}"
```
to
```
IFACE="${1:-<interface>}"
```

### Subnet clash

Run before the script `[Jetson]`
```
ip route | grep 192.168.100
```
Anything shows up = the dog already uses that range. Stop and ask the owner.

### Other checks `[Jetson]`

| Check | Command | If different |
|---|---|---|
| sudo access | `sudo -v` | Ask owner |
| Python | `python3 --version` | Code targets 3.10 |
| Firewall | `sudo ufw status` | `sudo ufw allow 4567/udp` with owner's OK |
| Free space | `df -h ~` | ~60 MB per minute of RADC |
