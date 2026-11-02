# GPS Setup - Quick Start Guide

## ✓ Status: WORKING

Your GPS module is fully functional and communicating with the Raspberry Pi!

## Quick Commands

### Check System Status
```bash
python3 gps_healthcheck.py
```
Shows if GPS hardware is ready (takes 2 seconds)

### Get GPS Position
```bash
python3 gpsneo6.py
```
Reads current GPS data (position, altitude, fix quality)

### Watch Satellite Acquisition
```bash
python3 gps_monitor.py
```
Watches in real-time as GPS acquires satellites (first-time startup)

### Run Full Diagnostics
```bash
python3 gps_diagnostic.py
```
Tests all ports and baud rates (takes ~30 seconds)

## Setup Summary

| Item | Status |
|------|--------|
| UART Enabled | ✓ Yes |
| Port | ✓ `/dev/ttyAMA0` |
| Baud Rate | ✓ 9600 |
| GPS Module | ✓ Connected |
| Data Flow | ✓ Confirmed |
| gpsd Blocking | ✓ Fixed (disabled) |

## What Happens Next?

1. **First Run** (~30-120 seconds):
   - GPS starts searching for satellites
   - LED on module may blink (acquisition mode)
   - Shows "No Fix" status

2. **After Satellites Acquired** (~1-5 minutes):
   - GPS has 2D or 3D fix
   - Shows coordinates & altitude
   - Accuracy improves with more satellites

3. **Subsequent Runs** (faster):
   - "Hot start" - GPS has almanac data
   - Fix usually within 10-30 seconds

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No data received | Place antenna near window or outside |
| GPS LED off | Check power connections |
| "Device busy" error | Stop gpsd: `sudo systemctl stop gpsd` |
| Wrong coordinates | Wait longer (acquisition in progress) |

## Files Included

| File | Purpose |
|------|---------|
| `gpsneo6.py` | Main GPS reader script |
| `test.py` | NMEA sentence parser test |
| `gps_diagnostic.py` | Comprehensive hardware test |
| `gps_monitor.py` | Real-time satellite monitor |
| `gps_healthcheck.py` | Quick system status check |
| `GPS_SETUP_COMPLETE.md` | Detailed setup documentation |

## All Done! 🎉

Your Raspberry Pi 5 is now set up to read GPS data. The scripts are ready to use.

Start with: `python3 gps_healthcheck.py`
