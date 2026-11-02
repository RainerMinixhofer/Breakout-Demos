#!/usr/bin/env python3
"""Quick GPS health check."""

import subprocess
import os
import serial
import sys

def check(description, condition):
    """Print a check result."""
    symbol = "✓" if condition else "✗"
    print(f"  {symbol} {description}")
    return condition

def main():
    print("\n" + "="*60)
    print("  GPS System Health Check")
    print("="*60 + "\n")
    
    all_ok = True
    
    # 1. Check ports
    print("Serial Ports:")
    all_ok &= check("UART0: /dev/ttyAMA0 exists", os.path.exists("/dev/ttyAMA0"))
    all_ok &= check("Fallback: /dev/serial0 exists", os.path.exists("/dev/serial0"))
    
    # 2. Check permissions
    print("\nPermissions:")
    all_ok &= check("Can read /dev/ttyAMA0", os.access("/dev/ttyAMA0", os.R_OK))
    all_ok &= check("Can write /dev/ttyAMA0", os.access("/dev/ttyAMA0", os.W_OK))
    
    # 3. Check pyserial
    print("\nPython Modules:")
    try:
        import serial
        check("pyserial installed", True)
    except ImportError:
        check("pyserial installed", False)
        all_ok = False
    
    try:
        from pyubx2 import UBXReader
        check("pyubx2 installed", True)
    except ImportError:
        check("pyubx2 installed", False)
        all_ok = False
    
    # 4. Check gpsd
    print("\nServices:")
    result = subprocess.run(
        ["systemctl", "is-enabled", "gpsd"],
        capture_output=True,
        text=True
    )
    gpsd_disabled = result.returncode != 0
    all_ok &= check("gpsd disabled (✓ for GPS use)", gpsd_disabled)
    
    # 5. Try to open port
    print("\nHardware Connection:")
    try:
        ser = serial.Serial("/dev/ttyAMA0", 9600, timeout=0.5)
        check("Can open /dev/ttyAMA0", True)
        data = ser.read(50)
        check(f"Data received ({len(data)} bytes)", len(data) > 0)
        ser.close()
    except Exception as e:
        check(f"Can open /dev/ttyAMA0", False)
        all_ok = False
    
    # Summary
    print("\n" + "="*60)
    if all_ok:
        print("  ✓ GPS System READY")
        print("\n  Run: python3 gpsneo6.py")
    else:
        print("  ✗ GPS System has issues")
        print("\n  Run: python3 gps_diagnostic.py")
        print("  for detailed troubleshooting")
    print("="*60 + "\n")
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
