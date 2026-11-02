# GPS Setup - Quick Start Guide for Raspberry Pi 5

## ✓ Status: WORKING

Your GPS module is fully functional and communicating with the Raspberry Pi!

---

## 🚀 Quick Commands

### Check System Status (2 seconds)
```bash
python3 gps_healthcheck.py
```
Verifies all components are ready

### Get GPS Position (real-time)
```bash
python3 gpsneo6.py
```
Displays current position, altitude, and fix quality

### Watch Satellite Acquisition
```bash
python3 gps_monitor.py
```
Real-time monitor showing fix status and satellite count

### Run Full Diagnostics (30 seconds)
```bash
python3 gps_diagnostic.py
```
Tests all ports, baud rates, and data formats

---

## ⚙️ System Configuration

### Boot Configuration: `/boot/firmware/config.txt`

Your system has the following GPS-related settings applied:

```ini
[all]
dtparam=pciex1              # PCIe configuration
PCIE_PROBE=1                # Enable PCIe probing
dtoverlay=uart0             # ⭐ Enable UART0 (GPIO 14/15)
dtparam=uart0=on            # Alternative UART0 enable
enable_uart=1               # Ensure UART is powered
dtoverlay=w1-gpio           # 1-wire support (optional)
```

**Key lines for GPS:**
- `dtoverlay=uart0` — Allocates GPIO14 (TX) and GPIO15 (RX) to UART0
- `enable_uart=1` — Powers the UART hardware
- `dtparam=uart0=on` — Legacy parameter (kept for compatibility)

**To apply changes:**
```bash
# Edit if needed
sudo nano /boot/firmware/config.txt

# Always reboot after changes
sudo reboot
```

### Kernel Command Line: `/boot/firmware/cmdline.txt`

```
console=tty1 root=PARTUUID=d73ba30c-02 rootfstype=ext4 fsck.repair=yes enable_uart=1 rootwait quiet splash plymouth.ignore-serial-consoles cfg80211.ieee80211_regdom=
```

**Important notes:**
- ✓ `console=tty1` — Serial console on HDMI (not UART), which is correct
- ✓ No `console=serial0` or `console=ttyAMA0` — GPS has exclusive access
- ✓ `enable_uart=1` — Powers UART hardware
- ✓ `plymouth.ignore-serial-consoles` — Prevents serial console interference

### System Services

#### gpsd (GPS Daemon) - DISABLED ✓

```bash
# Check status
sudo systemctl status gpsd

# Stop if running
sudo systemctl stop gpsd
sudo systemctl stop gpsd.socket

# Disable permanently
sudo systemctl disable gpsd
sudo systemctl mask gpsd.socket
```

**Why disabled?** The `gpsd` daemon claims exclusive access to GPS serial ports. Since we're reading directly with Python, it must be disabled.

**If you need gpsd later:**
```bash
sudo systemctl unmask gpsd.socket
sudo systemctl enable gpsd
sudo reboot
```

#### Serial Console - DISABLED ✓

```bash
# Check status
sudo systemctl status serial-getty@ttyAMA0.service

# Should show: disabled and inactive ✓
```

The serial console doesn't interfere (console is on tty1/HDMI), but it's disabled to be safe.

---

## 📊 Current Setup Summary

| Component | Status | Details |
|-----------|--------|---------|
| UART Hardware | ✓ Enabled | Via `dtoverlay=uart0` |
| GPIO Pins | ✓ Allocated | GPIO14 (TX), GPIO15 (RX) |
| Serial Port | ✓ Available | `/dev/ttyAMA0` |
| Baud Rate | ✓ 9600 baud | NEO-6M default |
| Protocol | ✓ UBX binary | u-blox proprietary |
| Data Flow | ✓ Confirmed | Real-time updates |
| gpsd Daemon | ✓ Disabled | No conflicts |
| Serial Console | ✓ Disabled | On HDMI (tty1) instead |

---

## 🔌 Hardware Wiring

Connect your NEO-6M GPS module as follows:

| GPS Pin | Pi Pin | Details |
|---------|--------|---------|
| TX | GPIO 15 / Pin 10 | GPS data output → Pi RX |
| RX | GPIO 14 / Pin 8 | Pi TX output → GPS data input |
| GND | GND | Ground reference |
| VCC | 3.3V | Power supply |

**Voltage Levels:**
- NEO-6M requires 3.3V power
- GPIO 14/15 accept 3.3V logic levels
- 5V GPS modules need voltage dividers on RX line

---

## ⏱️ First-Time GPS Acquisition

### What to Expect

1. **Seconds 0-30**: Module powers up, starts satellite search
   - LED on module blinks (acquisition mode)
   - Shows "NO FIX" status

2. **Seconds 30-120**: Satellites being acquired
   - Signal continues
   - Satellite count increases
   - Still shows "NO FIX" or "2D FIX"

3. **After 2-5 minutes**: 3D fix acquired
   - Shows "3D FIX" status
   - Coordinates and altitude available
   - Accuracy typically ±10-20m

### Improve Acquisition Speed

1. **Place antenna outdoors or near window**
   - Indoor reception is poor
   - Direct sky view is best

2. **Wait longer on first power-up**
   - Cold start can take 2-5 minutes
   - Hot start (after power cycle) is faster
   - Warm start (saved almanac) is fastest

3. **Run multiple times**
   - GPS saves almanac data
   - Each subsequent start is faster

---

## 🛠️ Troubleshooting

### "No data received" Error
```bash
# 1. Check GPS power LED
ls -la /dev/ttyAMA0

# 2. Run full diagnostics
python3 gps_diagnostic.py

# 3. Test raw connection
python3 << 'EOF'
import serial
ser = serial.Serial('/dev/ttyAMA0', 9600, timeout=1)
data = ser.read(100)
print(f"Received {len(data)} bytes: {data.hex()}")
ser.close()
EOF
```

### "Device Busy" Error
```bash
# gpsd or another process is using the port
sudo systemctl stop gpsd
sudo systemctl stop gpsd.socket

# Find what's using the port
fuser /dev/ttyAMA0

# Kill the process (replace PID)
sudo kill <PID>
```

### "Permission Denied" Error
```bash
# Add user to dialout group
sudo usermod -a -G dialout $USER

# Apply changes (logout and login, or:)
newgrp dialout

# Verify
id | grep dialout
```

### No Satellites Despite Outdoor Placement
```bash
# Check GPS module LEDs
# - Red LED: Power indicator (should be steady)
# - Green LED: Fix indicator (should blink)

# If no LEDs:
# 1. Check 3.3V power connection
# 2. Verify power is at least 50mA capable
# 3. Try powering from USB hub instead

# If only power LED:
# 1. GPS has no fix yet (normal first time)
# 2. Wait 2-5 minutes
# 3. Move to clear sky area
# 4. Try different location/orientation
```

---

## 📁 Files Included

| File | Purpose | Usage |
|------|---------|-------|
| `gpsneo6.py` | Main GPS reader | `python3 gpsneo6.py` |
| `test.py` | NMEA parser test | `python3 test.py` |
| `gps_diagnostic.py` | Hardware testing | `python3 gps_diagnostic.py` |
| `gps_monitor.py` | Satellite monitor | `python3 gps_monitor.py` |
| `gps_healthcheck.py` | System status | `python3 gps_healthcheck.py` |
| `GPS_SETUP_COMPLETE.md` | Detailed guide | Reference docs |
| `QUICKSTART.md` | This file | Quick reference |

---

## ✅ Verification Checklist

Before using the GPS in production:

- [ ] Run `gps_healthcheck.py` and see all ✓
- [ ] Run `gpsneo6.py` and receive UBX messages
- [ ] Run `gps_monitor.py` and see satellite acquisition
- [ ] Verify `/dev/ttyAMA0` data flow
- [ ] Confirm `gpsd` is disabled
- [ ] Check `/boot/firmware/config.txt` has `dtoverlay=uart0`
- [ ] Antenna is outdoors or near window
- [ ] Power LED on GPS module is lit

---

## 💡 Additional Resources

- **u-blox NEO-6M Datasheet**: https://www.u-blox.com/sites/default/files/NEO-6_DataSheet_%28GPS.G6-HW-09005%29.pdf
- **Raspberry Pi UART Setup**: https://www.raspberrypi.com/documentation/computers/configuration.html
- **UBX Protocol Reference**: https://www.u-blox.com/en/product/neo-6-series

---

## 🎯 Next Steps

1. **Verify System Ready**
   ```bash
   python3 gps_healthcheck.py
   ```

2. **Get First Position**
   ```bash
   python3 gpsneo6.py --timeout=120
   ```
   (Use longer timeout for first acquisition)

3. **Monitor Satellites**
   ```bash
   python3 gps_monitor.py
   ```

4. **Use in Production**
   - Integrate `gpsneo6.py` module into your application
   - Call `GPSNeo6()` class for GPS data
   - See `GPS_SETUP_COMPLETE.md` for API details

---

**✨ GPS system fully configured and operational!**
