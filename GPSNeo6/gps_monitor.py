#!/usr/bin/env python3
"""Simple GPS fix monitor - shows fix status in real-time."""

import serial
import time
import json

try:
    from pyubx2 import UBXMessage, UBXReader
except ImportError:
    print("pyubx2 not installed. Run: pip install pyubx2")
    exit(1)

def monitor_gps(port="/dev/ttyAMA0", baudrate=9600, timeout=2.0):
    """Monitor GPS for fix acquisition."""
    
    try:
        ser = serial.Serial(
            port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            rtscts=False,
            dsrdtr=False,
            xonxoff=False,
        )
        
        reader = UBXReader(ser, quitonerror=False)
        
        print(f"\n{'='*70}")
        print(f"  GPS Fix Monitor - {port} @ {baudrate} baud")
        print(f"{'='*70}\n")
        print("Waiting for satellite acquisition...")
        print("(This may take 30-120 seconds on first power-up)\n")
        
        last_status = None
        start_time = time.time()
        
        while True:
            try:
                msg = reader.read()
                
                if msg is None:
                    continue
                
                # Check for NAV-PVT messages (contain fix status)
                if msg.msg_type == "NAV-PVT":
                    fix_type = msg.fixType
                    num_sv = msg.numSV
                    lat = msg.lat
                    lon = msg.lon
                    alt = msg.hMSL
                    
                    # Determine fix status
                    if fix_type == 0:
                        status = "🔴 NO FIX"
                    elif fix_type == 2:
                        status = "🟡 2D FIX"
                    elif fix_type == 3:
                        status = "🟢 3D FIX"
                    else:
                        status = f"⚪ FIX TYPE {fix_type}"
                    
                    elapsed = int(time.time() - start_time)
                    
                    if status != last_status:
                        last_status = status
                        print(f"[{elapsed:>3}s] {status} | Satellites: {num_sv}")
                        
                        if fix_type >= 2:
                            print(f"\n  ✓ SUCCESS! GPS acquired {num_sv} satellites")
                            print(f"    Latitude:  {lat:.6f}°")
                            print(f"    Longitude: {lon:.6f}°")
                            print(f"    Altitude:  {alt/1000:.2f}m\n")
                            break
                
                # Also show NAV-STATUS for monitoring
                elif msg.msg_type == "NAV-STATUS":
                    fix_status = msg.gpsFix
                    if fix_status == 0x00:
                        print(f"  Still searching for satellites...")
                
            except Exception as e:
                # Silently skip parsing errors
                pass
        
        ser.close()
        return True
        
    except serial.SerialException as e:
        print(f"✗ Serial error: {e}")
        return False
    except KeyboardInterrupt:
        print("\n\n✓ Monitor stopped by user")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


if __name__ == "__main__":
    import sys
    
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyAMA0"
    monitor_gps(port)
