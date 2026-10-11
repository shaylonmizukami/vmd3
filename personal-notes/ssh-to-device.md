# Pi / Jetson SSH Setup

`[Laptop]` = Konsole on the laptop (`shaylon@x1carbon`)
`[Pi]` = SSH'd into the Pi (`pipi5@pipi5`)

---

## Quick Reference

| | Pi 5 | Jetson |
|---|---|---|
| WiFi network | `pipi5` | |
| WiFi password | `<fill in>` | |
| Hostname | `pipi5` | |
| Username | `pipi5` | |
| User password | `<fill in>` | |
| IP | `192.168.50.1` | |
| SSH alias | `pipi5` | `jetson` |
| AP profile (on Pi) | `pipi5ap` | |

### Daily use

Power on the Pi, wait ~1 min.

`[Laptop]`
```
nmcli device wifi rescan
nmcli connection up pipi5
ssh pipi5
```

Start a session `[Pi]`
```
tmux new -s radar
```

Detach: `Ctrl-b` then `d`

Reattach `[Pi]`
```
tmux attach -t radar
```

Code to Pi `[Laptop]`
```
rsync -av --filter=':- .gitignore' ~/Projects/vmd3/vmd3-dog/ pipi5:~/vmd3-dog/
```

Data to laptop `[Laptop]`
```
rsync -av pipi5:~/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/
```

Shut down `[Laptop]`
```
ssh -t pipi5 'sudo shutdown now'
```

Back to campus WiFi `[Laptop]`
```
nmcli connection up UHM
```

---

## 1. Connect Laptop to the Pi's Network

`[Laptop]`
```
nmcli device wifi connect pipi5 --ask
```

If "No network found":
```
nmcli device wifi rescan
sleep 5
nmcli device wifi list
```

If still missing: Pi is off or still booting (red LED = off, flickering green = booting).

After the first time:
```
nmcli connection up pipi5
```

---

## 2. Find a Device's IP

`[Laptop]`, try in order:
```
ip route | grep default
ping pipi5.local
ip neigh
nmap -sn 192.168.50.0/24
```

On the device itself `[Pi]`:
```
hostname -I
```

---

## 3. First Login

`[Laptop]`
```
ssh pipi5@192.168.50.1
```

Type `yes` at the fingerprint prompt.

Check the device `[Pi]`
```
whoami
hostname
ip a
python3 --version
tmux -V
exit
```

---

## 4. Change Hostname

`[Pi]`
```
sudo hostnamectl set-hostname NEWHOST
sudo sed -i '/127.0.1.1/d' /etc/hosts
echo -e '127.0.1.1\tNEWHOST' | sudo tee -a /etc/hosts
```

"unable to resolve host" during these commands is normal. Confirm it's gone:
```
sudo true
```

---

## 5. Change Login Password

`[Pi]`
```
passwd
```

---

## 6. Change Username

Can't rename the logged in user. Make a new one, delete the old.

`[Pi]` as old user
```
groups
sudo adduser NEWUSER
sudo usermod -aG adm,dialout,cdrom,sudo,audio,video,plugdev,games,users,netdev,lpadmin,gpio,i2c,spi,render,input NEWUSER
groups NEWUSER
exit
```

Use the list from `groups`, minus the old username, comma separated.

`[Laptop]`
```
ssh NEWUSER@192.168.50.1
```

`[Pi]` as new user
```
sudo whoami
sudo pkill -u OLDUSER
sudo deluser --remove-home OLDUSER
sudo rm -f /etc/sudoers.d/010_pi-nopasswd
```

If "user is currently used by process":
```
sudo loginctl terminate-user OLDUSER
sudo pkill -KILL -u OLDUSER
sudo deluser --remove-home OLDUSER
```

If still failing (console autologin):
```
sudo raspi-config nonint do_boot_behaviour B1
sudo systemctl restart getty@tty1
sudo pkill -KILL -u OLDUSER
sudo deluser --remove-home OLDUSER
```

Confirm `[Pi]`
```
id OLDUSER
```
Should say no such user.

---

## 7. Change WiFi Name and Password

Do this last. It disconnects you.

`[Pi]`
```
nmcli connection show
sudo nmcli connection modify pipi5ap 802-11-wireless.ssid NEWSSID wifi-sec.psk 'NEWWIFIPASS' wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp
sudo reboot
```

Password must be 8 to 63 characters, or you get "psk: property is invalid".

Rename the profile itself (internal label only, doesn't disconnect) `[Pi]`
```
sudo nmcli connection modify OLDPROFILE connection.id NEWPROFILE
```

`[Laptop]`
```
nmcli connection delete OLDSSID
nmcli device wifi rescan
sleep 5
nmcli device wifi connect NEWSSID --ask
```

---

## 8. SSH Key

`[Laptop]`
```
ls ~/.ssh
```

If no `id_ed25519`:
```
ssh-keygen -t ed25519 -C "shaylon-laptop"
```

Copy to device (redo after any username change):
```
ssh-copy-id pipi5@192.168.50.1
```

---

## 9. SSH Alias

`[Laptop]` edit `~/.ssh/config`
```
Host pipi5
    HostName 192.168.50.1
    User pipi5
    HostKeyAlias pipi5
    ServerAliveInterval 10
    ServerAliveCountMax 3

# Host jetson
#     HostName <fill in>
#     User <fill in>
#     HostKeyAlias jetson
#     ServerAliveInterval 10
#     ServerAliveCountMax 3
```

```
chmod 600 ~/.ssh/config
ssh pipi5
```

Run one command without logging in:
```
ssh pipi5 'hostname -I'
```

Commands needing sudo:
```
ssh -t pipi5 'sudo <command>'
```

---

## 10. tmux

`[Pi]`
| Action | Command |
|---|---|
| New session | `tmux new -s radar` |
| Detach | `Ctrl-b` then `d` |
| List | `tmux ls` |
| Reattach | `tmux attach -t radar` |
| Close | `exit` inside the session |
| Kill from outside | `tmux kill-session -t radar` |

Survival test `[Pi]`
```
tmux new -s radar
for i in $(seq 1 600); do echo $i; sleep 1; done
```
Detach, close Konsole, `ssh pipi5`, `tmux attach -t radar`. Counter should still be running.

If tmux isn't installed and there's no internet:
```
nohup python3 flight/main.py --saveBin > run.log 2>&1 &
tail -f run.log
```
`Ctrl-c` stops `tail`, not the recording.

---

## 11. Moving Files

`[Laptop]`

Folder to device:
```
rsync -av --filter=':- .gitignore' ~/Projects/vmd3/vmd3-dog/ pipi5:~/vmd3-dog/
```

Folder from device:
```
rsync -av pipi5:~/vmd3-dog/data/ ~/Projects/vmd3/vmd3-dog/data/
```

Single file:
```
scp pipi5:~/somefile.txt .
scp somefile.txt pipi5:~/
```

Keep the trailing `/` on folders, or you get a folder inside a folder.

"change_dir failed: No such file or directory" = folder doesn't exist on that end yet.

---

## 12. Power

Off `[Laptop]`
```
ssh -t pipi5 'sudo shutdown now'
```

Red LED = off but powered. Never pull power while green is flickering.

On: press the Pi 5 power button or replug power. Wait ~1 min for the WiFi network.

---

## 13. Jetson Differences

- Same commands, different `HostName` and `User` in `~/.ssh/config`
- Ask the owner before `ssh-copy-id`, password login works otherwise
- May not have tmux or internet, use the `nohup` fallback in section 10
- Check Python first: `python3 --version`

---

## 14. Common Errors

| Error | Fix |
|---|---|
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | `[Laptop]` `ssh-keygen -R <ip or alias>` |
| `No network with SSID found` | `nmcli device wifi rescan`, wait, retry |
| `unable to resolve host` | Section 4 |
| `psk: property is invalid` | WiFi password under 8 characters |
| `user is currently used by process` | Section 6 |
| `Permission denied (publickey,password)` | Wrong user, or key not copied (section 8) |
| `sudo: a terminal is required` | Add `-t` to the ssh command |
| `Connection timed out` | Not on the Pi's WiFi, or Pi still booting |
