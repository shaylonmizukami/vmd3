#!/usr/bin/env zsh
#
# setup_radar.sh — Configure network and firewall for V-MD3 radar testing.
#
# Run with: sudo ./setup_radar.sh
#
# What it does:
#   1. Brings the USB-C ethernet adapter up
#   2. Assigns static IP 192.168.100.1/24 (idempotent — won't error if already set)
#   3. Opens UDP port 4567 in firewalld (for radar's data stream)
#   4. Pings the radar to confirm connectivity
#
# Settings the radar's IP (default 192.168.100.201) and the laptop's
# adapter name are at the top — edit if your hardware changes.

set -e   # exit on any error

# ─── Configuration ────────────────────────────────────────────────
ETH_IFACE="enp0s13f0u1u2c2"
LAPTOP_IP="192.168.100.1/24"
RADAR_IP="192.168.100.201"
UDP_PORT="4567"
# ──────────────────────────────────────────────────────────────────

# Color codes for nicer output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'   # No Color

info()  { echo -e "${YELLOW}[*]${NC} $1"; }
ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
fail()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# Must be root for ip and firewall-cmd
if [[ $EUID -ne 0 ]]; then
    fail "This script must be run with sudo: sudo ./setup_radar.sh"
fi

# ─── Step 1: Check the adapter exists ─────────────────────────────
info "Checking for ethernet adapter $ETH_IFACE..."
if ! ip link show "$ETH_IFACE" &>/dev/null; then
    fail "Adapter $ETH_IFACE not found. Is the USB-C dongle plugged in?"
fi
ok "Adapter $ETH_IFACE found."

# ─── Tell NetworkManager to leave this adapter alone ──────
info "Marking $ETH_IFACE as unmanaged in NetworkManager..."
nmcli device set "$ETH_IFACE" managed no
ok "$ETH_IFACE is unmanaged by NM."

# ─── Step 2: Bring the interface up ───────────────────────────────
info "Bringing $ETH_IFACE up..."
ip link set "$ETH_IFACE" up
ok "$ETH_IFACE is up."

# ─── Step 3: Assign static IP (idempotent) ────────────────────────
info "Assigning $LAPTOP_IP to $ETH_IFACE..."
if ip addr show "$ETH_IFACE" | grep -q "${LAPTOP_IP%/*}/"; then
    ok "IP $LAPTOP_IP already assigned."
else
    ip addr add "$LAPTOP_IP" dev "$ETH_IFACE"
    ok "IP $LAPTOP_IP assigned."
fi

# ─── Step 4: Open UDP port in firewall ────────────────────────────
info "Opening UDP $UDP_PORT in firewalld..."
if firewall-cmd --query-port="${UDP_PORT}/udp" &>/dev/null; then
    ok "UDP $UDP_PORT already open."
else
    firewall-cmd --add-port="${UDP_PORT}/udp" >/dev/null
    ok "UDP $UDP_PORT opened (this session only — not persistent)."
fi

# ─── Step 5: Wait for link to come up ─────────────────────────────
info "Waiting for ethernet link..."
for i in {1..10}; do
    if ip link show "$ETH_IFACE" | grep -q "state UP"; then
        if ! ip link show "$ETH_IFACE" | grep -q "NO-CARRIER"; then
            ok "Ethernet link active."
            break
        fi
    fi
    if [[ $i -eq 10 ]]; then
        fail "No carrier on $ETH_IFACE. Check that the M12-RJ45 cable is connected and the radar is powered on."
    fi
    sleep 1
done

# ─── Step 6: Ping the radar ───────────────────────────────────────
info "Pinging radar at $RADAR_IP..."
if ping -c 3 -W 2 "$RADAR_IP" >/dev/null 2>&1; then
    ok "Radar is responding at $RADAR_IP."
else
    fail "Radar not responding at $RADAR_IP. Is it powered on? (Wait ~10 seconds after power-up for the bootloader to hand off.)"
fi

echo ""
ok "All checks passed. You can now run:"
echo "    cd ~/vmd3_test && source .venv/bin/activate && python record.py --fileName <name>"
echo ""
