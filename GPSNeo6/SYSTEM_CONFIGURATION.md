# Raspberry Pi 5 GPS System Configuration Reference

## Overview

This document details all system-level configuration required for GPS on Raspberry Pi 5 with NEO-6M module, including boot parameters, device tree overlays, and systemd services.

**Platform:** Raspberry Pi 5 Model B (8GB)  
**OS:** Raspberry Pi OS Bookworm (Debian 12)  
**GPS Module:** u-blox NEO-6M  
**Status:** ✓ Fully Configured and Operational

---

## 1. Boot Configuration: `/boot/firmware/config.txt`

### GPS-Essential Settings

```ini
[all]
# ⭐ PRIMARY: Enable UART0 on GPIO14/15
dtoverlay=uart0

# ALTERNATIVE/LEGACY: Older format for UART enable
# (Note: dtoverlay=uart0 is preferred on Pi 5)
enable_uart=1

# Ensure UART hardware is powered
dtparam=uart0=on
```

### Your Current Configuration (COMPLETE)

```ini
# For more options and information see
# http://rptl.io/configtxt
# Some settings may impact device functionality. See link above for details

# Uncomment some or all of these to enable the optional hardware interfaces
dtparam=i2c_arm=on
#dtparam=i2s=on
dtparam=spi=on

# Enable audio (loads snd_bcm2835)
dtparam=audio=on

# Additional overlays and parameters are documented
# /boot/firmware/overlays/README

dtoverlay=disable-wifi
dtoverlay=disable-bt

# Automatically load overlays for detected cameras
camera_auto_detect=1

# Automatically load overlays for detected DSI displays
display_auto_detect=1

# Automatically load initramfs files, if found
auto_initramfs=1

# Enable DRM VC4 V3D driver
dtoverlay=vc4-kms-v3d
max_framebuffers=2

# Don't have the firmware create an initial video= setting in cmdline.txt.
# Use the kernel's default instead.
disable_fw_kms_setup=1

# Run in 64-bit mode
arm_64bit=1

# Disable compensation for displays with overscan
disable_overscan=1
otg_mode=1

# Run as fast as firmware / board allows
arm_boost=1

[cm4]
# Enable host mode on the 2711 built-in XHCI USB controller.
# This line should be removed if the legacy DWC2 controller is required
# (e.g. for USB device mode) or if USB support is not required.
otg_mode=1

[cm5]
dtoverlay=dwc2,dr_mode=host

[all]
dtparam=pciex1
PCIE_PROBE=1
dtoverlay=uart0              # ✓ GPS UART0 allocation
dtoverlay=w1-gpio            # 1-wire temperature sensors
dtparam=uart0=on             # ✓ GPS UART0 power enable
enable_uart=1                # ✓ GPS UART hardware enable
```

### Configuration Explanation

| Parameter | Value | Purpose | GPS? |
|-----------|-------|---------|------|
| `dtoverlay=uart0` | (present) | Enables UART0 on GPIO14/15 | ⭐ YES |
| `dtparam=uart0=on` | (present) | Powers UART0 hardware | ⭐ YES |
| `enable_uart=1` | (present) | Ensures UART stays powered | ⭐ YES |
| `dtoverlay=vc4-kms-v3d` | (present) | Graphics driver | No |
| `dtoverlay=disable-wifi` | (present) | Disables WiFi | No |
| `dtoverlay=disable-bt` | (present) | Disables Bluetooth | No |

### To Modify

```bash
# Edit the config file
sudo nano /boot/firmware/config.txt

# After changes, ALWAYS reboot
sudo reboot

# Verify changes took effect
grep uart /boot/firmware/config.txt
gpioinfo | grep -E "GPIO14|GPIO15"
```

---

## 2. Kernel Command Line: `/boot/firmware/cmdline.txt`

### Current Configuration (CORRECT)

```
console=tty1 root=PARTUUID=d73ba30c-02 rootfstype=ext4 fsck.repair=yes enable_uart=1 rootwait quiet splash plymouth.ignore-serial-consoles cfg80211.ieee80211_regdom=
```

### Parameter Analysis

| Parameter | Value | Purpose | Correct? |
|-----------|-------|---------|----------|
| `console=tty1` | tty1 (HDMI) | Kernel/boot messages to HDMI | ✓ YES |
| `root=PARTUUID=...` | Partition ID | Root filesystem location | ✓ YES |
| `rootfstype=ext4` | ext4 | Filesystem type | ✓ YES |
| `enable_uart=1` | 1 | UART hardware enabled | ✓ YES |
| `fsck.repair=yes` | yes | Auto-fix filesystem | ✓ YES |
| `plymouth.ignore-serial-consoles` | (flag) | Prevents serial console conflicts | ✓ YES |
| `quiet splash` | (flags) | Suppresses verbose boot output | ✓ YES |

### ⚠️ CRITICAL: What NOT to Have

```bash
# ❌ WRONG - These would conflict with GPS:
console=serial0,115200      # Would use /dev/serial0
console=ttyAMA0,115200      # Would use /dev/ttyAMA0
console=ttyS0,115200        # Would use /dev/ttyS0
```

### To Verify/Modify

```bash
# View current configuration
cat /boot/firmware/cmdline.txt

# Edit if needed (all on ONE line, no newlines)
sudo nano /boot/firmware/cmdline.txt

# Reboot to apply
sudo reboot
```

---

## 3. GPIO Pin Allocation

### UART0 GPIO Mapping

| GPIO | Pin # | Function | Direction |
|------|-------|----------|-----------|
| GPIO14 | 8 | TX (Transmit) | Pi → GPS |
| GPIO15 | 10 | RX (Receive) | GPS → Pi |
| GND | 6,9,14,20,25,30,34,39 | Ground | Both |

### Verification

```bash
# Show GPIO status for UART pins
gpioinfo | grep -E "GPIO14|GPIO15"

# Expected output (when UART enabled):
#   line  14: "GPIO14"  kernel input  active-high
#   line  15: "GPIO15"  kernel input  active-high

# If showing "unused input", UART overlay not loaded
```

### GPIO Pin Layout Reference

```
Pi 5 GPIO Header (40-pin):

3.3V [1]  [2]  5V
GPIO2 [3] [4]  5V
GPIO3 [5] [6]  GND
GPIO4 [7] [8]  GPIO14 ← RX (GPS TX input)
GND   [9] [10] GPIO15 ← TX (GPS RX output)
GPIO17 [11] [12] GPIO18
GPIO27 [13] [14] GND
GPIO22 [15] [16] GPIO23
3.3V [17] [18] GPIO24
GPIO10 [19] [20] GND
GPIO9  [21] [22] GPIO25
GPIO11 [23] [24] GPIO8
GND   [25] [26] GPIO7
GPIO0  [27] [28] GPIO1
GPIO5  [29] [30] GND
GPIO6  [31] [32] GPIO12
GPIO13 [33] [34] GND
GPIO19 [35] [36] GPIO16
GPIO26 [37] [38] GPIO20
GND   [39] [40] GPIO21
```

---

## 4. System Services

### 4.1 gpsd (GPS Daemon)

**Status:** ✓ DISABLED

The `gpsd` daemon must be disabled because it claims exclusive access to GPS serial ports.

#### Check Status

```bash
sudo systemctl status gpsd
sudo systemctl status gpsd.socket
```

Expected output:
```
○ gpsd.service - GPS (Global Positioning System) Daemon
     Loaded: loaded (.../gpsd.service; disabled; ...)
     Active: inactive (dead)
```

#### Disable gpsd (if not already done)

```bash
# Stop the service
sudo systemctl stop gpsd
sudo systemctl stop gpsd.socket

# Disable it permanently
sudo systemctl disable gpsd
sudo systemctl disable gpsd.socket

# Also mask it to prevent socket activation
sudo systemctl mask gpsd.socket

# Verify
sudo systemctl status gpsd
```

#### Re-enable gpsd (if needed later)

```bash
# If you need to use gpsd instead of direct Python GPS reading:
sudo systemctl unmask gpsd.socket
sudo systemctl enable gpsd
sudo systemctl start gpsd

# Then your Python scripts should use gpsd's interface
```

#### Why Disable gpsd?

- `gpsd` opens `/dev/ttyAMA0` in exclusive mode
- Our Python scripts also need exclusive access
- Only one process can read the serial port at a time
- Python scripts provide better control and data parsing

---

### 4.2 Serial Console (getty@ttyAMA0)

**Status:** ✓ DISABLED

The serial console login service on UART is disabled (kernel console is on HDMI instead).

#### Check Status

```bash
sudo systemctl status serial-getty@ttyAMA0.service
```

Expected output:
```
○ serial-getty@ttyAMA0.service - Serial Getty on ttyAMA0
     Loaded: loaded (.../serial-getty@.service; disabled; ...)
     Active: inactive (dead)
```

#### Why It's Disabled

- `console=tty1` in cmdline.txt sends output to HDMI
- No serial console process is running
- GPIO14/15 are free for GPS use
- Can re-enable if debug serial console needed (not recommended for GPS)

---

## 5. Systemd Configuration Files

### Create GPS Service (Optional)

If you want GPS to start automatically on boot, create a systemd service:

```bash
sudo nano /etc/systemd/system/gps-logger.service
```

```ini
[Unit]
Description=GPS Data Logger
After=multi-user.target

[Service]
Type=simple
User=rainer
WorkingDirectory=/home/rainer/Projects/Breakout-Demos/GPSNeo6
ExecStart=/usr/bin/python3 /home/rainer/Projects/Breakout-Demos/GPSNeo6/gpsneo6.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable it:
```bash
sudo systemctl daemon-reload
sudo systemctl enable gps-logger
sudo systemctl start gps-logger
```

---

## 6. Device Tree Overlays

### Available UART Overlays

```bash
# List all uart-related overlays
ls /boot/firmware/overlays/uart* 2>/dev/null

# Show details about uart0 overlay
dtoverlay --help uart0
```

### uart0 Overlay Details

```
Name: uart0
Info: Change the pin for UART0
Load: dtoverlay=uart0,pins_<pin_set>
Params: pins_4_17 = 4,17 (default, GPIO4-5)
        pins_14_15 = 14,15 (Raspberry Pi 5 default, GPIO14-15)
```

**Our Configuration:** Uses default pins 14,15 on Pi 5

```bash
# Verify overlay loaded
dtoverlay -l | grep uart

# Output on Pi 5: 
# 1 uart0
```

---

## 7. Troubleshooting Configuration

### Issue: UART Not Enabled

**Symptoms:**
- `/dev/ttyAMA0` doesn't exist
- `gpioinfo` shows GPIO14/15 as "unused"

**Solution:**
```bash
# 1. Check config.txt
grep "dtoverlay=uart0\|enable_uart\|dtparam=uart0" /boot/firmware/config.txt

# Should see:
# dtoverlay=uart0
# dtparam=uart0=on
# enable_uart=1

# 2. If missing, add to [all] section:
sudo bash -c 'echo "dtoverlay=uart0" >> /boot/firmware/config.txt'
sudo bash -c 'echo "enable_uart=1" >> /boot/firmware/config.txt'

# 3. Reboot
sudo reboot

# 4. Verify
gpioinfo | grep -E "GPIO14|GPIO15"
```

### Issue: Serial Console Interfering

**Symptoms:**
- GPS data corrupted
- Can't open /dev/ttyAMA0

**Solution:**
```bash
# 1. Disable serial console service
sudo systemctl disable serial-getty@ttyAMA0.service
sudo systemctl stop serial-getty@ttyAMA0.service

# 2. Check cmdline.txt has no ttyAMA0 console
cat /boot/firmware/cmdline.txt | grep -o "console=[^ ]*"

# Should output: console=tty1

# 3. If you see console=serial0 or console=ttyAMA0:
sudo nano /boot/firmware/cmdline.txt
# Remove those parameters, keep console=tty1

# 4. Reboot
sudo reboot
```

### Issue: gpsd Blocking Port

**Symptoms:**
- "Device or resource busy" error
- Permission denied on /dev/ttyAMA0

**Solution:**
```bash
# 1. Check if gpsd is running
ps aux | grep gpsd | grep -v grep

# 2. Stop it
sudo systemctl stop gpsd
sudo systemctl stop gpsd.socket

# 3. Disable permanently
sudo systemctl disable gpsd
sudo systemctl mask gpsd.socket

# 4. Verify
ps aux | grep gpsd | grep -v grep  # Should show nothing
```

---

## 8. Verification Checklist

### After Each Configuration Change

- [ ] Edits made to `/boot/firmware/config.txt` or `/boot/firmware/cmdline.txt`
- [ ] System rebooted: `sudo reboot`
- [ ] Changes verified with appropriate commands
- [ ] GPS scripts tested: `python3 gps_healthcheck.py`

### Full Verification Procedure

```bash
# 1. Check boot config
echo "=== config.txt ===" && grep -E "uart0|enable_uart" /boot/firmware/config.txt

# 2. Check kernel command line
echo "=== cmdline.txt ===" && grep "console=" /boot/firmware/cmdline.txt

# 3. Check GPIO allocation
echo "=== GPIO Status ===" && gpioinfo | grep -E "GPIO14|GPIO15"

# 4. Check device exists
echo "=== Device ===" && ls -la /dev/ttyAMA0

# 5. Check services
echo "=== Services ===" && \
sudo systemctl is-enabled gpsd && echo "gpsd: ENABLED" || echo "gpsd: DISABLED" && \
sudo systemctl is-enabled serial-getty@ttyAMA0 && echo "getty: ENABLED" || echo "getty: DISABLED"

# 6. Test port access
echo "=== Port Access ===" && \
python3 << 'EOF'
import serial
try:
    ser = serial.Serial('/dev/ttyAMA0', 9600, timeout=0.5)
    data = ser.read(50)
    print(f"✓ Port opened, {len(data)} bytes received")
    ser.close()
except Exception as e:
    print(f"✗ Error: {e}")
EOF
```

---

## 9. Recovery Procedures

### Reset to Known Good State

If configuration is broken:

```bash
# 1. Boot into recovery (if system won't boot)
# Insert Pi 5 SD card into Linux machine

# 2. Mount the boot partition
mkdir /tmp/pi5-boot
sudo mount /dev/sdX2 /tmp/pi5-boot

# 3. Fix config.txt
sudo nano /tmp/pi5-boot/firmware/config.txt
# Ensure [all] section has:
# dtoverlay=uart0
# enable_uart=1

# 4. Fix cmdline.txt
sudo nano /tmp/pi5-boot/firmware/cmdline.txt
# Ensure it has: console=tty1 (not console=serial0)

# 5. Unmount and reboot
sudo umount /tmp/pi5-boot
```

### Restore From Backup

```bash
# If you have a backup of working config:
sudo cp /boot/firmware/config.txt.backup /boot/firmware/config.txt
sudo reboot
```

---

## 10. Reference Documentation

| Resource | URL |
|----------|-----|
| Raspberry Pi Config Reference | https://www.raspberrypi.com/documentation/computers/config_txt.html |
| Raspberry Pi UART Setup | https://www.raspberrypi.com/documentation/computers/configuration.html#uart |
| Device Tree Overlays | https://www.raspberrypi.com/documentation/computers/device-tree.html |
| u-blox NEO-6M Datasheet | https://www.u-blox.com/sites/default/files/NEO-6_DataSheet.pdf |
| GPIO Pinout | https://www.raspberrypi.com/documentation/computers/io_pin_documentation.html |

---

## Summary

✅ **Your System is Fully Configured**

- **Boot Config:** UART0 enabled via `dtoverlay=uart0`
- **Command Line:** Console on HDMI (tty1), no UART console
- **GPIO Pins:** GPIO14/15 allocated to UART0
- **Services:** gpsd disabled, getty disabled
- **Device:** `/dev/ttyAMA0` active and accessible
- **Status:** Ready for GPS use

**Last Updated:** 2026-11-02  
**Verified On:** Raspberry Pi 5 Model B, OS Bookworm
