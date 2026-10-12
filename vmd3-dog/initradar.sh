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