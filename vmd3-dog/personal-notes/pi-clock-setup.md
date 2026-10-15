# Pi Clock Setup

`[Laptop]` = Konsole on the laptop (`shaylon@x1carbon`)
`[Pi]` = SSH'd into the Pi (`pipi5@pipi5`)

---

## Quick Reference

Sync from the laptop (works without the RTC) `[Laptop]`
```
ssh -t pipi5 "sudo date -s @$(date +%s)"
```

Check `[Pi]`
```
date
```

Wrong date = wrong folder and file names on captures. Sync every session until the RTC is set up.

---

## 1. Why the Clock Drifts

- Pi's own network has no internet, so no automatic time sync
- Without the RTC battery, the Pi restores the time it had at shutdown
- With the battery connected, the RTC keeps counting while unplugged

---

## 2. Connect the RTC Battery

- Two pin `BAT` connector on the Pi 5 board, near the USB-C power port
- Plug the official RTC battery cable in, power off first

---

## 3. Enable Battery Charging

Only for the official rechargeable battery. Never for a regular CR2032 coin cell.

`[Pi]`
```
echo "dtparam=rtc_bbat_vchg=3000000" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

Check after reboot `[Pi]`
```
cat /sys/devices/platform/soc/soc:rpi_rtc/rtc/rtc0/battery_voltage
cat /sys/devices/platform/soc/soc:rpi_rtc/rtc/rtc0/charging_voltage
```

- `battery_voltage` near `3000000` = healthy, near `0` = flat or unplugged
- `charging_voltage` = `3000000` means charging is on

Leave the Pi powered for about a day to charge a flat battery.

---

## 4. Get Internet on the Pi

Phone hotspot on (iPhone: keep the Personal Hotspot screen open).

Save the phone network `[Pi]`
```
sudo nmcli connection add type wifi con-name phone ssid "PHONE_SSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "PHONE_PASS" connection.autoconnect no
```

Switch `[Pi]`
```
sudo nmcli connection down pipi5ap && sudo nmcli connection up phone
```
SSH freezes. Close Konsole.

`[Laptop]`
```
nmcli device wifi rescan
sleep 5
nmcli device wifi connect "PHONE_SSID" --ask
ssh pipi5@pipi5.local
```

If unreachable: power cycle the Pi, it boots back as `pipi5`.

---

## 5. Sync and Save to the RTC

`[Pi]`
```
timedatectl
```
Wait for `System clock synchronized: yes`, recheck every 30 s.

`[Pi]`
```
sudo apt update
sudo apt install -y util-linux-extra
sudo hwclock -w
sudo hwclock -r
```

`hwclock -r` should match `date`.

Optional, while online `[Pi]`
```
sudo apt upgrade
```
Shows download size before confirming. Reboot after.

---

## 6. Switch Back

`[Pi]`
```
sudo nmcli connection down phone && sudo nmcli connection up pipi5ap
```

`[Laptop]`
```
nmcli connection up pipi5
ssh pipi5
```

---

## 7. Confirm It Holds

`[Laptop]`
```
ssh -t pipi5 'sudo shutdown now'
```

Unplug for a few minutes, plug back in, wait ~1 min.

`[Laptop]`
```
ssh pipi5 date
date
```

Match = RTC working. Pi shows its shutdown time = battery flat or unplugged (section 2 and 3).

---

## 8. Jetson

- Has its own RTC, but don't assume it's set
- Check before recording `[Jetson]`
```
date
```
- Fix from the laptop `[Laptop]`
```
ssh -t jetson "sudo date -s @$(date +%s)"
```
- Don't edit its boot config or install packages without the owner's OK

---

## 9. Common Errors

| Output | Fix |
|---|---|
| `sudo: hwclock: command not found` | Section 5, install `util-linux-extra` |
| `battery_voltage` near `0` | Battery unplugged or flat, sections 2 and 3 |
| `No such file or directory` on `battery_voltage` | Not a Pi 5, or RTC not detected |
| `System clock synchronized: no` | No internet yet, wait or check hotspot |
| `hwclock: Cannot access the Hardware Clock` | Run with `sudo` |
| Date correct, then wrong after unplugging | RTC not holding, section 7 |
