# GPS Setup Complete ✓

## Summary

Your Raspberry Pi 5 GPS module is **fully configured and working**!

### What Was Fixed

1. **UART Configuration** ✓
   - Enabled UART0 on Pi 5 via `/boot/firmware/config.txt`
   - Changed `dtparam=uart0=on` → `dtoverlay=uart0`
   - Rebooted to apply changes

2. **Port Access Issues** ✓
   - Stopped `gpsd` daemon that was blocking `/dev/ttyAMA0`
   - Disabled it permanently: `sudo systemctl disable gpsd`

3. **Script Port Detection** ✓
   - Updated `gpsneo6.py` to prioritize `/dev/ttyAMA0`
   - Changed port candidate order in `DEFAULT_PORT_CANDIDATES`

### Diagnostic Results

**GPS Hardware Status:**
```
✓ GPS Module: DETECTED and COMMUNICATING
✓ Port: /dev/ttyAMA0 (Raspberry Pi UART0)
✓ Baud Rate: 9600 baud (NEO-6M default)
✓ Protocol: UBX binary (u-blox proprietary)
✓ Data Flow: CONFIRMED (receiving NAV-SVINFO messages)
```

**System Info:**
- Model: Raspberry Pi 5 Model B Rev 1.1
- OS: Debian 12 (Bookworm)
- UART Status: Enabled and accessible

### Current Status

The GPS module is:
- ✓ Powered and operating
- ✓ Transmitting data correctly
- ✓ Being read by the Pi without errors
- ⏳ Acquiring satellite signal (normal first-time startup)

**Note:** GPS first-time acquisition can take 30-120 seconds from cold start, especially indoors. For faster acquisition:
- Place the antenna near a window
- Ensure clear sky view
- Let it run for several minutes

## How to Use

### Run the Main GPS Script

```bash
cd ~/Projects/Breakout-Demos/GPSNeo6
source .venv/bin/activate
python3 gpsneo6.py
```

This will:
- Automatically detect the GPS on `/dev/ttyAMA0`
- Read UBX NAV-PVT data
- Display latitude, longitude, altitude, and fix quality
- Output JSON format

### Monitor GPS Fix Acquisition (Real-Time)

```bash
python3 gps_monitor.py
```

Shows:
- Current fix status (No Fix → 2D → 3D)
- Number of satellites acquired
- Coordinates when lock is achieved

### Run Diagnostics (if needed)

```bash
python3 gps_diagnostic.py
```

Tests:
- All serial ports
- Multiple baud rates
- GPS data presence and format

### Test with NMEA Parser

```bash
python3 test.py
```

Reads NMEA sentences directly (if GPS is in NMEA mode)

## Hardware Wiring

Verify your connections:

| GPS Pin | Pi Pin | Description |
|---------|--------|------------|
| TX | GPIO 15 / Pin 10 | GPS data output → Pi RX |
| RX | GPIO 14 / Pin 8 | Pi TX output → GPS data input |
| GND | GND | Ground reference |
| VCC | 3.3V | Power (check module spec) |

## Files Created

1. **`gps_diagnostic.py`** — Comprehensive hardware diagnostics
2. **`gps_monitor.py`** — Real-time satellite acquisition monitor
3. **Updated `gpsneo6.py`** — Fixed port detection
4. **`GPS_SETUP_COMPLETE.md`** — This file

## Next Steps

1. **Verify Satellite Lock**
   - Run `gps_monitor.py` and wait for 🟢 3D FIX
   - Should appear within 1-2 minutes near a window
   
2. **Use GPS Data in Your Application**
   - The scripts automatically parse UBX messages
   - `read_snapshot()` gets position, altitude, time
   - Data is returned as structured JSON

3. **Optional: Switch to NMEA Mode**
   - Most NEO-6M modules support both UBX and NMEA
   - Use u-blox u-center to configure if needed

## Troubleshooting

**"No data received"** after running diagnostics?
- Check GPS antenna is connected
- Verify power LED on GPS module (red/green)
- Try near a window for better signal

**"Device busy" error**?
- Ensure `gpsd` is stopped: `systemctl status gpsd`
- No other GPS application should be running

**Wrong coordinates or time?**
- GPS is not a time-of-day source initially
- It will be accurate after satellite acquisition
- Check antenna orientation

## Commands Reference

```bash
# Stop any running GPS service
sudo systemctl stop gpsd

# Check if UART is enabled
grep uart /boot/firmware/config.txt

# Monitor GPS data in raw hex
python3 gps_diagnostic.py

# List all serial devices
ls -la /dev/ttyAMA* /dev/ttyS* /dev/serial*

# Check system uptime
uptime

# Reboot if config was changed
sudo reboot
```

## Support

For u-blox NEO-6M documentation:
- https://www.u-blox.com/en/product/neo-6-series

For Raspberry Pi UART setup:
- https://www.raspberrypi.com/documentation/computers/configuration.html

---

**Status: ✓ OPERATIONAL**  
**Last Updated:** 2026-11-02  
**GPS Hardware:** u-blox NEO-6M  
**Platform:** Raspberry Pi 5  
