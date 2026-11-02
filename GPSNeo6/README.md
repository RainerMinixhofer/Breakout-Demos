# GPS System - Documentation Index

## 📖 Documentation Files

### [QUICKSTART.md](QUICKSTART.md) — START HERE
**Best for:** Getting started, everyday use, quick reference

✓ Common commands (health check, GPS read, monitoring, diagnostics)  
✓ System configuration overview (config.txt, cmdline.txt)  
✓ Service management (gpsd, getty status and control)  
✓ Hardware wiring diagram  
✓ GPS acquisition timeline and expectations  
✓ Troubleshooting common problems  
✓ Reference documentation links  

**Read this first when:**
- You want to get started immediately
- You need a command to run
- You're troubleshooting a simple issue
- You need hardware wiring information

---

### [SYSTEM_CONFIGURATION.md](SYSTEM_CONFIGURATION.md) — DEEP DIVE
**Best for:** System administration, detailed reference, recovery

✓ Complete `/boot/firmware/config.txt` documentation  
✓ Kernel command line (`cmdline.txt`) analysis  
✓ GPIO pin allocation and verification  
✓ Systemd service management (gpsd, getty)  
✓ Device tree overlay details  
✓ Comprehensive troubleshooting procedures  
✓ Recovery and reset procedures  
✓ Verification checklists  
✓ References to official documentation  

**Read this when:**
- You need to understand system configuration deeply
- You're debugging a configuration issue
- You need to make changes to boot parameters
- You're recovering from a broken configuration
- You want to know exactly what was configured and why

---

### [GPS_SETUP_COMPLETE.md](GPS_SETUP_COMPLETE.md) — BACKGROUND
**Best for:** Understanding what was done, setup summary

✓ Issues that were fixed  
✓ How each issue was resolved  
✓ Current hardware status  
✓ System information  
✓ Quick health check commands  
✓ File descriptions  

**Read this when:**
- You want to understand the setup history
- You're checking what issues were solved
- You want a summary of everything that's installed

---

## 🛠️ Utility Scripts

### ⭐ [gps_diagnostics.py](gps_diagnostics.py) — UNIFIED DIAGNOSTIC TOOL
**Runtime:** 2-30 seconds (menu-selectable)  
**Best for:** All diagnostics in one tool

Menu-driven interface with options:
1. **Quick Health Check** (2 sec) — System status verification
2. **Comprehensive Diagnostics** (30 sec) — Port/baud/protocol testing
3. **Satellite Monitor** (continuous) — Real-time satellite acquisition
4. **All Tests** (5 min) — Sequential complete verification

```bash
python3 gps_diagnostics.py
```

Then select option 1-4 from the menu.

**Use this:** For all diagnostic and testing purposes (replaces old individual scripts)

---

### Legacy Diagnostic Scripts (Deprecated)

The following scripts still work but functionality is now in `gps_diagnostics.py`:
- `gps_healthcheck.py` — Now option 1 in unified tool
- `gps_diagnostic.py` — Now option 2 in unified tool
- `gps_monitor.py` — Now option 3 in unified tool

See [DIAGNOSTIC_MIGRATION.md](DIAGNOSTIC_MIGRATION.md) for details.

---

### [gpsneo6.py](gpsneo6.py)
**Runtime:** Varies by timeout  
**Best for:** Production GPS reading

Reads:
- UBX NAV-PVT messages
- Position (latitude, longitude)
- Altitude
- Fix quality
- Time

```bash
python3 gpsneo6.py                    # Default 15-second timeout
python3 gpsneo6.py --timeout=60       # Custom timeout
python3 gpsneo6.py --port=/dev/ttyAMA0  # Specific port
```

**Use this:** In your actual GPS-reading application

---

## 🎯 Quick Decision Tree

**What do you want to do?**

### 1. "Get started right now"
→ Read [QUICKSTART.md](QUICKSTART.md)  
→ Run `python3 gps_healthcheck.py`  
→ Run `python3 gpsneo6.py`

### 2. "Verify my system is working"
→ Run `python3 gps_healthcheck.py`  
→ Run `python3 gps_diagnostic.py`  
→ Check [SYSTEM_CONFIGURATION.md](SYSTEM_CONFIGURATION.md) if any issues

### 3. "I got an error, help!"
→ Check "[Troubleshooting](QUICKSTART.md#-troubleshooting)" in [QUICKSTART.md](QUICKSTART.md)  
→ If not solved, check "[Troubleshooting Configuration](SYSTEM_CONFIGURATION.md#7-troubleshooting-configuration)" in [SYSTEM_CONFIGURATION.md](SYSTEM_CONFIGURATION.md)  
→ Run `python3 gps_diagnostic.py` for detailed info

### 4. "I need to change configuration"
→ Read [SYSTEM_CONFIGURATION.md](SYSTEM_CONFIGURATION.md) section 1-3  
→ Make changes to `/boot/firmware/config.txt` or `/boot/firmware/cmdline.txt`  
→ Reboot  
→ Run `python3 gps_healthcheck.py` to verify

### 5. "System is broken, I need recovery"
→ Read "[Recovery Procedures](SYSTEM_CONFIGURATION.md#9-recovery-procedures)" in [SYSTEM_CONFIGURATION.md](SYSTEM_CONFIGURATION.md)  
→ Follow step-by-step recovery instructions

### 6. "I want to understand everything"
→ Read [GPS_SETUP_COMPLETE.md](GPS_SETUP_COMPLETE.md) for background  
→ Read [QUICKSTART.md](QUICKSTART.md) for practical commands  
→ Read [SYSTEM_CONFIGURATION.md](SYSTEM_CONFIGURATION.md) for technical details  
→ Review script source code for implementation details

### 7. "I'm integrating GPS into my application"
→ Study [gpsneo6.py](gpsneo6.py) class interface  
→ Review API in [GPS_SETUP_COMPLETE.md](GPS_SETUP_COMPLETE.md)  
→ Use `GPSNeo6()` class from your Python code  
→ Call `read_snapshot()` to get current position

---

## 📋 System Status Summary

### ✓ Configuration Applied

| Item | Status | Details |
|------|--------|---------|
| UART Hardware | ✓ Enabled | `dtoverlay=uart0` in config.txt |
| GPIO Pins | ✓ Allocated | GPIO14 (TX), GPIO15 (RX) |
| Serial Device | ✓ Available | `/dev/ttyAMA0` active |
| Boot Console | ✓ HDMI | `console=tty1` in cmdline.txt |
| Serial Console | ✓ Disabled | getty@ttyAMA0 not running |
| gpsd Daemon | ✓ Disabled | No port conflicts |
| GPS Module | ✓ Connected | Communicating at 9600 baud |
| Data Format | ✓ UBX Binary | u-blox protocol active |

### ✓ Scripts Tested

- `gps_healthcheck.py` — ✓ PASS
- `gps_diagnostic.py` — ✓ PASS (data detected)
- `gps_monitor.py` — ✓ PASS (listening for satellites)
- `gpsneo6.py` — ✓ PASS (receiving UBX messages)

---

## 🔍 File Locations

All files are in: `/home/rainer/Projects/Breakout-Demos/GPSNeo6/`

```
GPSNeo6/
├── README (this file)
│
├── Documentation/
│   ├── QUICKSTART.md                    ← Start here
│   ├── SYSTEM_CONFIGURATION.md          ← Technical details
│   └── GPS_SETUP_COMPLETE.md            ← Setup summary
│
├── Scripts/
│   ├── gpsneo6.py                       ← Main GPS reader
│   ├── gps_healthcheck.py               ← 2-second check
│   ├── gps_diagnostic.py                ← 30-second test
│   ├── gps_monitor.py                   ← Real-time monitor
│   └── test.py                          ← NMEA parser test
│
└── Configuration (on Pi filesystem)/
    ├── /boot/firmware/config.txt        ← Boot parameters
    └── /boot/firmware/cmdline.txt       ← Kernel command line
```

---

## 📞 Reference Documentation

| Resource | Link |
|----------|------|
| Raspberry Pi Config | https://www.raspberrypi.com/documentation/computers/config_txt.html |
| Raspberry Pi UART Setup | https://www.raspberrypi.com/documentation/computers/configuration.html#uart |
| Device Tree Overlays | https://www.raspberrypi.com/documentation/computers/device-tree.html |
| u-blox NEO-6M Datasheet | https://www.u-blox.com/sites/default/files/NEO-6_DataSheet.pdf |
| GPIO Pinout | https://www.raspberrypi.com/documentation/computers/io_pin_documentation.html |
| ElectricalFlux Article | https://electricalflux.com/mcu-projects/gps-on-raspberry-pi-5-neo6m-wiring-debug |

---

## ✨ Summary

Your Raspberry Pi 5 GPS system is:

✅ **Fully Configured** — All boot parameters set correctly  
✅ **Verified Working** — Hardware tested and operational  
✅ **Well Documented** — Multiple guides for different needs  
✅ **Ready to Use** — Utility scripts tested and working  
✅ **Easy to Troubleshoot** — Diagnostic tools available  
✅ **Production Ready** — Can integrate into applications  

**Get started with:** `python3 gps_healthcheck.py`

---

**Last Updated:** 2026-11-02  
**Platform:** Raspberry Pi 5 Model B, Bookworm OS  
**GPS Module:** u-blox NEO-6M
