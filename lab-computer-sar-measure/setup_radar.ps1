#Requires -RunAsAdministrator
# setup_radar.ps1 — Configure network + firewall for V-MD3 on Windows 11.
# Run in an *elevated* PowerShell:  .\setup_radar.ps1

# ─── Configuration ────────────────────────────────────────────────
$AdapterName = "Ethernet"          # <-- find yours with: Get-NetAdapter
$LaptopIP    = "192.168.100.1"
$PrefixLen   = 24
$RadarIP     = "192.168.100.201"
$UdpPort     = 4567
# ──────────────────────────────────────────────────────────────────

function Info($m) { Write-Host "[*] $m" -ForegroundColor Yellow }
function Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Fail($m) { Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# ─── Step 1: Check the adapter exists ─────────────────────────────
Info "Checking for adapter '$AdapterName'..."
$adapter = Get-NetAdapter -Name $AdapterName -ErrorAction SilentlyContinue
if (-not $adapter) {
    Fail "Adapter '$AdapterName' not found. Run Get-NetAdapter to list names; is the USB-C dongle plugged in?"
}
Ok "Adapter '$AdapterName' found."

# ─── Step 2: Bring the interface up ───────────────────────────────
Info "Enabling '$AdapterName'..."
Enable-NetAdapter -Name $AdapterName -Confirm:$false -ErrorAction SilentlyContinue
Ok "'$AdapterName' enabled."

# ─── Step 3: Assign static IP (idempotent) ────────────────────────
Info "Assigning $LaptopIP/$PrefixLen to '$AdapterName'..."
$existing = Get-NetIPAddress -InterfaceAlias $AdapterName -AddressFamily IPv4 `
    -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -eq $LaptopIP }
if ($existing) {
    Ok "IP $LaptopIP already assigned."
} else {
    # Clear any stale IPs/DHCP on this adapter first, then set static
    Remove-NetIPAddress -InterfaceAlias $AdapterName -AddressFamily IPv4 `
        -Confirm:$false -ErrorAction SilentlyContinue
    New-NetIPAddress -InterfaceAlias $AdapterName -IPAddress $LaptopIP `
        -PrefixLength $PrefixLen -ErrorAction Stop | Out-Null
    Ok "IP $LaptopIP assigned."
}

# ─── Step 4: Open UDP port in Windows Firewall ────────────────────
Info "Opening UDP $UdpPort in Windows Firewall..."
$ruleName = "VMD3 Radar UDP $UdpPort"
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Ok "Firewall rule '$ruleName' already exists."
} else {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound `
        -Protocol UDP -LocalPort $UdpPort -Action Allow | Out-Null
    Ok "UDP $UdpPort opened (persistent rule)."
}

# ─── Step 5: Wait for link ────────────────────────────────────────
Info "Waiting for ethernet link..."
$up = $false
for ($i = 1; $i -le 10; $i++) {
    $status = (Get-NetAdapter -Name $AdapterName).Status
    if ($status -eq "Up") { $up = $true; Ok "Ethernet link active."; break }
    Start-Sleep -Seconds 1
}
if (-not $up) {
    Fail "No link on '$AdapterName'. Check the M12-RJ45 cable and that the radar is powered on."
}

# ─── Step 6: Ping the radar ───────────────────────────────────────
Info "Pinging radar at $RadarIP..."
if (Test-Connection -ComputerName $RadarIP -Count 3 -Quiet) {
    Ok "Radar is responding at $RadarIP."
} else {
    Fail "Radar not responding at $RadarIP. Powered on? (Wait ~10 s after power-up for the bootloader.)"
}

Write-Host ""
Ok "All checks passed."
Write-Host ""