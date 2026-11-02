#!/usr/bin/env python3
"""Comprehensive GPS module diagnostic script for Raspberry Pi."""

import serial
import sys
import time
import os
from typing import Optional, Tuple

# Test configuration
PORTS_TO_TEST = ["/dev/ttyAMA0", "/dev/serial0", "/dev/ttyS0", "/dev/ttyUSB0", "/dev/ttyUSB1"]
BAUD_RATES = [9600, 4800, 19200, 38400, 115200, 230400]
PROBE_TIME = 2.0  # Seconds to listen per baud rate
PROBE_BYTES = 200  # Max bytes to read per probe


def check_port_exists(port: str) -> bool:
    """Check if a serial port device exists."""
    return os.path.exists(port)


def check_port_permissions(port: str) -> bool:
    """Check if we have read/write permissions on a port."""
    return os.access(port, os.R_OK | os.W_OK)


def probe_port(port: str, baud_rate: int, timeout: float = 0.5) -> Optional[bytes]:
    """Attempt to read data from a port at a specific baud rate."""
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
    except (serial.SerialException, OSError, PermissionError) as e:
        return None


def format_hex_preview(data: bytes, width: int = 32) -> str:
    """Format binary data as hex with printable ASCII preview."""
    hex_str = ' '.join(f'{b:02x}' for b in data[:width])
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:width])
    return f"{hex_str:<{width*3}} │ {ascii_str}"


def detect_data_type(data: bytes) -> str:
    """Try to identify what type of GPS data this is."""
    if not data:
        return "No data"
    
    # Check for UBX protocol (starts with 0xB5 0x62)
    if data[:2] == b'\xb5\x62':
        return "UBX binary protocol (u-blox)"
    
    # Check for NMEA sentences (start with '$')
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
        return "NMEA protocol (unidentified sentences)"
    
    # Check for raw binary patterns
    printable = sum(1 for b in data[:50] if 32 <= b < 127)
    if printable / len(data[:50]) > 0.7:
        return "Likely NMEA or text data"
    else:
        return "Binary data (possibly UBX)"


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def main():
    """Run comprehensive GPS diagnostics."""
    print("\n" + "█" * 70)
    print("█" + " " * 68 + "█")
    print("█  GPS Module Diagnostic Tool for Raspberry Pi NEO-6M/u-blox" + " " * 11 + "█")
    print("█" + " " * 68 + "█")
    print("█" * 70)
    
    # Step 1: System checks
    print_section("STEP 1: System Checks")
    
    print("\n1.1 Checking serial port availability:")
    ports_available = {}
    for port in PORTS_TO_TEST:
        exists = check_port_exists(port)
        if exists:
            has_perms = check_port_permissions(port)
            status = "✓ OK" if has_perms else "⚠ NO PERMISSIONS"
            print(f"  {port:<20} {status}")
            ports_available[port] = has_perms
        else:
            print(f"  {port:<20} ✗ NOT FOUND")
    
    usable_ports = [p for p, ok in ports_available.items() if ok]
    if not usable_ports:
        print("\n✗ ERROR: No usable serial ports found!")
        print("  Solutions:")
        print("    - Enable UART in /boot/firmware/config.txt (Pi 5) or /boot/config.txt")
        print("    - Check permissions: sudo usermod -a -G dialout $USER")
        print("    - Reboot if changes were made")
        return False
    
    print(f"\n✓ Found {len(usable_ports)} usable port(s)")
    
    # Step 2: GPIO status
    print_section("STEP 2: GPIO Status (GPIO14=TX, GPIO15=RX)")
    try:
        import subprocess
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
    
    # Step 3: Probe each port
    print_section("STEP 3: Probing Serial Ports")
    
    results = {}
    for port in usable_ports:
        print(f"\n3.{usable_ports.index(port)+1} Testing {port}:")
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
    
    # Step 4: Analysis
    print_section("STEP 4: Analysis & Recommendations")
    
    total_data_found = sum(len(d) for r in results.values() for d in r.values())
    
    if total_data_found > 0:
        print("\n✓ SUCCESS! GPS data detected!")
        print("\nPortions receiving data:")
        for port, port_results in results.items():
            if port_results:
                print(f"\n  {port}:")
                for baud, data in port_results.items():
                    data_type = detect_data_type(data)
                    print(f"    • {baud} baud: {data_type}")
        
        print("\n" + "─" * 70)
        print("NEXT STEPS:")
        print("  1. Update your GPS script to use the working port and baud rate")
        print("  2. For NEO-6M sending NMEA: use pynmea2 library for parsing")
        print("  3. For UBX protocol: use pyubx2 library for parsing")
    
    else:
        print("\n✗ No GPS data detected on any port/baud rate combination.")
        print("\nTROUBLESHOOTING CHECKLIST:")
        print("  ☐ GPS Module Powered?")
        print("      - Check for red LED on GPS module (power indicator)")
        print("      - Verify 3.3V or 5V is connected to correct pins")
        print("      - If LED is off, module is not powered")
        print()
        print("  ☐ Wiring Connections?")
        print("      - GPS TX (output) → Pi RX/GPIO15/Pin 10")
        print("      - GPS RX (input)  → Pi TX/GPIO14/Pin 8")
        print("      - GPS GND → Pi GND")
        print("      - Verify no crossed or loose wires")
        print()
        print("  ☐ Voltage Levels?")
        print("      - Some modules need voltage dividers (5V GPS → 3.3V Pi RX)")
        print("      - Check module datasheet for correct voltage")
        print()
        print("  ☐ Module Initialization?")
        print("      - Some modules need 30+ seconds on first power-up")
        print("      - Try powering off, waiting 10s, then powering back on")
        print()
        print("  ☐ Alternate Connection?")
        print("      - Try a USB-to-serial adapter if one is available")
        print("      - Helps isolate if Pi UART is the issue")
    
    # Step 5: Hardware info
    print_section("STEP 5: System Information")
    try:
        with open("/proc/device-tree/model") as f:
            print(f"  Model: {f.read().strip()}")
    except:
        print("  Model: Unknown")
    
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith(("VERSION_CODENAME", "VERSION_ID")):
                    print(f"  {line.strip()}")
    except:
        pass
    
    print(f"\n  UART Overlay: dtparam=uart0=on")
    print(f"  Ports Tested: {', '.join(usable_ports)}")
    print(f"  Baud Rates: {', '.join(map(str, BAUD_RATES))}")
    
    print("\n" + "█" * 70 + "\n")
    
    return total_data_found > 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
