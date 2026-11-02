import serial
import pynmea2
import sys
import time

# --- Pin & Port Definitions ---
# Pi 5 PL011 UART mapped to GPIO 14/15 via enable_uart=1
UART_PORT = '/dev/ttyAMA0' 
BAUD_RATE = 9600           # NEO-6M default hardware baud rate
TIMEOUT = 1.5              # Seconds to wait for a serial byte

def parse_gps_stream():
    """Reads and parses NMEA sentences from the UART stream."""
    try:
        ser = serial.Serial(UART_PORT, BAUD_RATE, timeout=TIMEOUT)
        print(f"[INFO] Listening on {UART_PORT} at {BAUD_RATE} baud...")
        
        while True:
            # Read raw bytes, decode to ASCII, ignore non-ASCII garbage
            raw_line = ser.readline().decode('ascii', errors='replace').strip()
            
            # NMEA sentences always start with '$'
            if raw_line.startswith('$'):
                try:
                    msg = pynmea2.parse(raw_line)
                    
                    # GGA contains essential fix data (Lat/Lon/Alt/Satellites)
                    if isinstance(msg, pynmea2.types.talker.GGA):
                        if msg.gps_qual > 0:
                            print(f"[FIX] Quality: {msg.gps_qual} | "
                                  f"Lat: {msg.latitude:0.6f} | "
                                  f"Lon: {msg.longitude:0.6f} | "
                                  f"Sats: {msg.num_sats} | "
                                  f"Alt: {msg.altitude}m")
                        else:
                            print("[SEARCH] Waiting for satellite lock...")
                            
                except pynmea2.ParseError:
                    # Silently ignore sentences with corrupted checksums
                    pass
                    
    except serial.SerialException as e:
        print(f"[HARDWARE ERROR] Failed to open serial port: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INFO] Stream interrupted by user. Closing port.")
        ser.close()
        sys.exit(0)

if __name__ == "__main__":
    parse_gps_stream()