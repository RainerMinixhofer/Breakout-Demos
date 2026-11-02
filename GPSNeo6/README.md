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

## 🛠️ Production Scripts

### ⭐ [gps_diagnostics.py](gps_diagnostics.py) — UNIFIED DIAGNOSTIC TOOL
**Runtime:** 2-30 seconds (menu-selectable)  
**Purpose:** All diagnostics in one menu-driven tool

**Interactive menu with options:**
1. **Quick Health Check** (2 sec) — System status verification
2. **Comprehensive Diagnostics** (30 sec) — Port/baud/protocol testing
3. **Satellite Monitor** (continuous) — Real-time satellite acquisition
4. **All Tests** (5 min) — Sequential complete verification
0. Exit

```bash
python3 gps_diagnostics.py
```

Then select option 1-4 from the menu.

---

### [gpsneo6.py](gpsneo6.py)
**Runtime:** Varies by timeout  
**Purpose:** Production GPS data reader

Provides:
- UBX NAV-PVT message parsing
- Position (latitude, longitude)
- Altitude and fix quality
- Timestamp data
- Class-based API for integration

**Usage:**
```bash
python3 gpsneo6.py                    # Default 15-second timeout
python3 gpsneo6.py --timeout=60       # Custom timeout
python3 gpsneo6.py --port=/dev/ttyAMA0  # Specific port
```

**Integration example:**
```python
from gpsneo6 import GPSNeo6

gps = GPSNeo6()
snapshot = gps.read_snapshot()
print(f"Position: {snapshot['latitude']}, {snapshot['longitude']}")
gps.close()
```

---

## 🎯 Quick Decision Tree

**What do you want to do?**

### 1. "Get started right now"
```bash
python3 gps_diagnostics.py  # Select option 1 (Quick Health Check)
python3 gpsneo6.py          # Read GPS data
```

### 2. "Verify my system is working"
```bash
python3 gps_diagnostics.py  # Select option 2 (Comprehensive Diagnostics)
```

### 3. "I got an error, help!"
1. Check "[Troubleshooting](QUICKSTART.md#-troubleshooting)" in [QUICKSTART.md](QUICKSTART.md)
2. Run comprehensive diagnostics:
   ```bash
   python3 gps_diagnostics.py  # Select option 2
   ```
3. For deep technical details, see [SYSTEM_CONFIGURATION.md](SYSTEM_CONFIGURATION.md)

### 4. "I need to change configuration"
1. Read [SYSTEM_CONFIGURATION.md](SYSTEM_CONFIGURATION.md) sections 1-3
2. Edit `/boot/firmware/config.txt` or `/boot/firmware/cmdline.txt`
3. Reboot your Pi
4. Verify:
   ```bash
   python3 gps_diagnostics.py  # Select option 1
   ```

### 5. "Watch satellites being acquired"
```bash
python3 gps_diagnostics.py  # Select option 3 (Satellite Monitor)
```

### 6. "Run all tests sequentially"
```bash
python3 gps_diagnostics.py  # Select option 4 (All Tests)
```


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

### ✓ Active Scripts

- `gps_diagnostics.py` — Unified menu tool (all diagnostics)
- `gpsneo6.py` — Main GPS reader

---

## 📁 File Structure

All files are in: `/home/rainer/Projects/Breakout-Demos/GPSNeo6/`

```
GPSNeo6/
├── README.md                          ← You are here
├── QUICKSTART.md                      ← Quick start guide
├── SYSTEM_CONFIGURATION.md            ← Technical reference
│
├── gpsneo6.py                         ← Main GPS reader (production)
├── gps_diagnostics.py                 ← Unified diagnostic tool
│
└── Configuration (on Pi filesystem)/
    ├── /boot/firmware/config.txt      ← Boot parameters

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
