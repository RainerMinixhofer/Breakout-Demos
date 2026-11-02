#!/usr/bin/env python3
"""
Unified GPS Diagnostic Tool
Combines health check, comprehensive diagnostics, and satellite monitoring
into one tool with menu-driven interface.

Usage: python3 gps_diagnostics.py
"""

import os
import sys
import serial
import time
import subprocess
from typing import Optional, Tuple

try:
    from pyubx2 import UBXReader
except ImportError:
    print("pyubx2 not installed. Run: pip install pyubx2")
    sys.exit(1)

# Configuration
PORTS_TO_TEST = ["/dev/ttyAMA0", "/dev/serial0", "/dev/ttyS0", "/dev/ttyUSB0", "/dev/ttyUSB1"]
BAUD_RATES = [9600, 4800, 19200, 38400, 115200, 230400]
PROBE_TIME = 2.0
PROBE_BYTES = 200


def clear_screen():
    """Clear terminal screen."""
    os.system('clear' if os.name == 'posix' else 'cls')


def print_header(title: str):
    """Print formatted header."""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70 + "\n")


def print_section(title: str):
    """Print formatted section header."""
    print(f"\n{title}:")
    print("-" * 70)


def print_menu():
    """Print main menu."""
    clear_screen()
    print("""
╔════════════════════════════════════════════════════════════════════╗
║                                                                    ║
║             GPS UNIFIED DIAGNOSTIC TOOL                           ║
║             Raspberry Pi 5 + u-blox NEO-6M                        ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝

SELECT A DIAGNOSTIC TEST:

1. Quick Health Check         (2 seconds)
   → Verify system is ready to use
   → Check ports, permissions, services, data

2. Comprehensive Diagnostics (30 seconds)
   → Test all ports and baud rates
   → Detect GPS data and protocol format
   → Detailed troubleshooting info

3. Satellite Monitor          (continuous)
   → Real-time satellite acquisition monitor
   → Shows fix status and coordinates
   → Press Ctrl+C to stop

4. All Tests (Sequential)     (5 minutes)
   → Run all diagnostics in sequence
   → Complete system verification

0. Exit

═══════════════════════════════════════════════════════════════════════
""")


def health_check():
    """Quick 2-second system status check."""
    print_header("QUICK HEALTH CHECK")
    
    checks_passed = 0
    checks_total = 0
    
    # Serial ports
    print_section("Serial Ports")
    ports_available = {}
    for port in PORTS_TO_TEST:
        checks_total += 1
        if os.path.exists(port):
            has_perms = os.access(port, os.R_OK | os.W_OK)
            if has_perms:
                print(f"  ✓ {port:<20} OK")
                ports_available[port] = True
                checks_passed += 1
            else:
                print(f"  ⚠ {port:<20} NO PERMISSIONS")
                ports_available[port] = False
        else:
            print(f"  ✗ {port:<20} NOT FOUND")
    
    # Python modules
    print_section("Python Modules")
    try:
        import serial
        checks_total += 1
        print("  ✓ pyserial installed")
        checks_passed += 1
    except ImportError:
        checks_total += 1
        print("  ✗ pyserial NOT installed")
    
    try:
        from pyubx2 import UBXReader
        checks_total += 1
        print("  ✓ pyubx2 installed")
        checks_passed += 1
    except ImportError:
        checks_total += 1
        print("  ✗ pyubx2 NOT installed")
    
    # Services
    print_section("System Services")
    result = subprocess.run(
        ["systemctl", "is-enabled", "gpsd"],
        capture_output=True,
        text=True
    )
    checks_total += 1
    if result.returncode != 0:
        print("  ✓ gpsd disabled")
        checks_passed += 1
    else:
        print("  ✗ gpsd enabled (may cause conflicts)")
    
    # Hardware
    print_section("Hardware Connection")
    usable_ports = [p for p, ok in ports_available.items() if ok]
    if usable_ports:
        port = usable_ports[0]
        checks_total += 1
        try:
            ser = serial.Serial(port, 9600, timeout=0.5)
            print(f"  ✓ Can open {port}")
            checks_passed += 1
            
            data = ser.read(50)
            checks_total += 1
            if len(data) > 0:
                print(f"  ✓ Data received ({len(data)} bytes)")
                checks_passed += 1
            else:
                print(f"  ⚠ No data received (GPS may need time to acquire)")
            
            ser.close()
        except Exception as e:
            checks_total += 1
            print(f"  ✗ Cannot open port: {e}")
    
    # Summary
    print_section("Summary")
    percentage = (checks_passed / checks_total * 100) if checks_total > 0 else 0
    status = "✓ GPS System READY" if checks_passed == checks_total else f"⚠ {checks_passed}/{checks_total} checks passed"
    print(f"  {status} ({percentage:.0f}%)")
    print()


def detect_data_type(data: bytes) -> str:
    """Identify GPS data type."""
    if not data:
        return "No data"
    
    if data[:2] == b'\xb5\x62':
        return "UBX binary protocol (u-blox)"
    
    if b'$' in data[:50]:
        sentences = []
        for chunk in data[:50].split(b'\n'):
            if chunk.startswith(b'$'):
                try:
                    sentence = chunk.decode('ascii', errors='ignore').strip()
                    if ',' in sentence:
                        talker = sentence[1:3]
                        msg_type = sentence[3:6]
                        sentences.append(f"{talker}.{msg_type}")
                except:
                    pass
        if sentences:
            return f"NMEA protocol: {', '.join(set(sentences))}"
        return "NMEA protocol (unidentified)"
    
    printable = sum(1 for b in data[:50] if 32 <= b < 127)
    if printable / len(data[:50]) > 0.7:
        return "Likely NMEA or text data"
    else:
        return "Binary data (possibly UBX)"


def format_hex_preview(data: bytes, width: int = 32) -> str:
    """Format binary data as hex with ASCII preview."""
    hex_str = ' '.join(f'{b:02x}' for b in data[:width])
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:width])
    return f"{hex_str:<{width*3}} │ {ascii_str}"


def probe_port(port: str, baud_rate: int, timeout: float = 0.5) -> Optional[bytes]:
    """Attempt to read data from port at specific baud rate."""
    try:
        ser = serial.Serial(
            port,
            baudrate=baud_rate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            rtscts=False,
            dsrdtr=False,
            xonxoff=False,
        )
        ser.reset_input_buffer()
        time.sleep(0.1)
        
        data = b''
        deadline = time.time() + PROBE_TIME
        while time.time() < deadline:
            chunk = ser.read(PROBE_BYTES - len(data))
            if chunk:
                data += chunk
                if len(data) >= PROBE_BYTES:
                    break
        
        ser.close()
        return data if data else None
    except (serial.SerialException, OSError, PermissionError):
        return None


def comprehensive_diagnostics():
    """Run comprehensive 30-second hardware diagnostic."""
    print_header("COMPREHENSIVE DIAGNOSTICS")
    
    # System checks
    print_section("System Checks")
    print("1.1 Checking serial port availability:")
    
    ports_available = {}
    for port in PORTS_TO_TEST:
        exists = os.path.exists(port)
        if exists:
            has_perms = os.access(port, os.R_OK | os.W_OK)
            status = "✓ OK" if has_perms else "⚠ NO PERMISSIONS"
            print(f"  {port:<20} {status}")
            ports_available[port] = has_perms
        else:
            print(f"  {port:<20} ✗ NOT FOUND")
    
    usable_ports = [p for p, ok in ports_available.items() if ok]
    if not usable_ports:
        print("\n✗ ERROR: No usable serial ports found!")
        return False
    
    print(f"\n✓ Found {len(usable_ports)} usable port(s)")
    
    # GPIO status
    print_section("GPIO Status (GPIO14=TX, GPIO15=RX)")
    try:
        result = subprocess.run(
            ["gpioinfo", "GPIO14", "GPIO15"],
            capture_output=True,
            text=True,
            timeout=5
        )
        for line in result.stdout.split('\n'):
            if 'GPIO14' in line or 'GPIO15' in line:
                print(f"  {line.strip()}")
    except Exception as e:
        print(f"  ⚠ Could not check GPIO status: {e}")
    
    # Port probing
    print_section("Probing Serial Ports")
    
    results = {}
    for port in usable_ports:
        print(f"\nTesting {port}:")
        port_results = {}
        
        for baud_rate in BAUD_RATES:
            sys.stdout.write(f"    {baud_rate:>6} baud: ")
            sys.stdout.flush()
            
            data = probe_port(port, baud_rate)
            
            if data:
                port_results[baud_rate] = data
                print(f"✓ {len(data):>3} bytes")
                print(f"             {format_hex_preview(data)}")
                data_type = detect_data_type(data)
                print(f"             Type: {data_type}")
            else:
                print("✗ No data")
        
        results[port] = port_results
    
    # Analysis
    print_section("Analysis & Recommendations")
    
    total_data_found = sum(len(d) for r in results.values() for d in r.values())
    
    if total_data_found > 0:
        print("\n✓ SUCCESS! GPS data detected!")
        print("\nPorts receiving data:")
        for port, port_results in results.items():
            if port_results:
                print(f"\n  {port}:")
                for baud, data in port_results.items():
                    data_type = detect_data_type(data)
                    print(f"    • {baud} baud: {data_type}")
        return True
    else:
        print("\n✗ No GPS data detected on any port/baud rate combination.")
        print("\nTROUBLESHOOTING CHECKLIST:")
        print("  ☐ GPS Module Powered? (check red LED)")
        print("  ☐ Wiring Correct? (TX→RX, RX→TX)")
        print("  ☐ Voltage Levels? (3.3V or 5V as per module spec)")
        print("  ☐ Module Initialized? (may need 30+ seconds)")
        print("  ☐ Try Alternate Port? (USB-to-serial adapter)")
        return False


def satellite_monitor():
    """Real-time satellite acquisition monitor."""
    print_header("SATELLITE ACQUISITION MONITOR")
    print("Waiting for satellite acquisition...")
    print("(This may take 30-120 seconds on first power-up)")
    print("Press Ctrl+C to stop.\n")
    
    try:
        # Find working port
        port_to_use = None
        for port in PORTS_TO_TEST:
            if os.path.exists(port) and os.access(port, os.R_OK | os.W_OK):
                try:
                    test_ser = serial.Serial(port, 9600, timeout=0.5)
                    data = test_ser.read(50)
                    test_ser.close()
                    if len(data) > 0:
                        port_to_use = port
                        break
                except:
                    pass
        
        if not port_to_use:
            print("✗ Could not find GPS port with data")
            return
        
        ser = serial.Serial(
            port_to_use,
            9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=2.0,
            rtscts=False,
            dsrdtr=False,
            xonxoff=False,
        )
        
        reader = UBXReader(ser, quitonerror=False)
        
        print(f"Connected to: {port_to_use}\n")
        
        last_status = None
        start_time = time.time()
        
        while True:
            try:
                msg = reader.read()
                
                if msg is None:
                    continue
                
                # Check for NAV-PVT messages
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
            
            except Exception:
                # Silently skip parsing errors
                pass
        
        ser.close()
        
    except KeyboardInterrupt:
        print("\n\n✓ Monitor stopped by user")
        return
    except Exception as e:
        print(f"✗ Error: {e}")
        return


def run_all_tests():
    """Run all diagnostics sequentially."""
    print_header("RUNNING ALL DIAGNOSTICS")
    print("This will run through all tests sequentially.\n")
    
    input("Press Enter to start...")
    
    # Quick health check
    print("\n[1/3] Quick Health Check...")
    input("Press Enter to continue...")
    health_check()
    input("Press Enter for next test...")
    
    # Comprehensive diagnostics
    print("\n[2/3] Comprehensive Diagnostics...")
    input("Press Enter to continue...")
    comprehensive_diagnostics()
    input("Press Enter for next test...")
    
    # Satellite monitor
    print("\n[3/3] Satellite Monitor...")
    print("Note: This will run continuously. Press Ctrl+C to stop.\n")
    input("Press Enter to start satellite monitoring...")
    satellite_monitor()
    
    print_section("All Tests Complete")
    print("Diagnostic suite finished.")


def main():
    """Main menu loop."""
    while True:
        print_menu()
        
        try:
            choice = input("Enter your choice (0-4): ").strip()
            
            if choice == "1":
                health_check()
                input("\nPress Enter to return to menu...")
            
            elif choice == "2":
                comprehensive_diagnostics()
                input("\nPress Enter to return to menu...")
            
            elif choice == "3":
                satellite_monitor()
                input("\nPress Enter to return to menu...")
            
            elif choice == "4":
                run_all_tests()
                input("\nPress Enter to return to menu...")
            
            elif choice == "0":
                print("\nExiting GPS Diagnostic Tool.\n")
                sys.exit(0)
            
            else:
                print("\n✗ Invalid choice. Please try again.")
                time.sleep(1)
        
        except KeyboardInterrupt:
            print("\n\nExiting GPS Diagnostic Tool.\n")
            sys.exit(0)
        except Exception as e:
            print(f"\n✗ Error: {e}")
            input("Press Enter to return to menu...")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
