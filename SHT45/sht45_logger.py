#!/usr/bin/env python3
"""
SHT45 Sensor Reader with Data Logging
Logs measurements to CSV file for analysis
"""

import csv
import time
import sys
from datetime import datetime
from pathlib import Path
from sensirion_driver_adapters.i2c_adapter.i2c_channel import I2cChannel
from sensirion_i2c_driver import CrcCalculator, I2cConnection, LinuxI2cTransceiver
from sensirion_i2c_sht4x import Sht4xDevice


class SHT45Logger:
    """Data logger for SHT45 sensor measurements."""
    
    def __init__(self, log_file: str = "sht45_data.csv", i2c_bus: int = 1, i2c_address: int = 0x44):
        """
        Initialize sensor and logger.
        
        Args:
            log_file: CSV file to log measurements to
            i2c_bus: I2C bus number
            i2c_address: I2C address of sensor (typically 0x44 or 0x45)
        """
        self.log_file = Path(log_file)
        self.i2c_bus = i2c_bus
        self.i2c_address = i2c_address
        self.sensor = None
        self.measurement_count = 0
        
        # Initialize sensor
        self._init_sensor()
        
        # Initialize CSV file if it doesn't exist
        self._init_csv()
    
    def _init_sensor(self) -> None:
        """Initialize the SHT45 sensor."""
        try:
            transceiver = LinuxI2cTransceiver(f'/dev/i2c-{self.i2c_bus}')
            i2c_connection = I2cConnection(transceiver)
            crc = CrcCalculator(width=8, polynomial=0x31, init_value=0xFF, final_xor=0x00)
            channel = I2cChannel(i2c_connection, slave_address=self.i2c_address, crc=crc)
            self.sensor = Sht4xDevice(channel)
            serial = self.sensor.serial_number()
            print(f"✓ SHT45 sensor found (Serial: {serial:016X})")
        except Exception as e:
            print(f"✗ Failed to initialize sensor: {e}", file=sys.stderr)
            raise RuntimeError("Sensor initialization failed") from e
    
    def _init_csv(self) -> None:
        """Initialize CSV file with headers."""
        if not self.log_file.exists():
            try:
                with open(self.log_file, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Timestamp', 'Temperature (°C)', 'Humidity (%)', 'Measurement #'])
                print(f"✓ Log file created: {self.log_file}")
            except Exception as e:
                print(f"✗ Failed to create log file: {e}", file=sys.stderr)
                raise
    
    def log_measurement(self) -> None:
        """Read sensor and log measurement to CSV."""
        try:
            temperature, humidity = self.sensor.measure_high_precision()
            self.measurement_count += 1
            
            timestamp = datetime.now().isoformat()
            
            with open(self.log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, f"{temperature.value:.2f}", f"{humidity.value:.2f}", self.measurement_count])
            
            print(f"[{timestamp}] T: {temperature.value:6.2f}°C | H: {humidity.value:6.2f}% | Count: {self.measurement_count}")
            
        except Exception as e:
            print(f"✗ Failed to log measurement: {e}", file=sys.stderr)
    
    def run(self, interval: float = 1.0, duration: int = None) -> None:
        """
        Continuously log measurements.
        
        Args:
            interval: Time between measurements in seconds
            duration: Stop after N seconds (None = run indefinitely)
        """
        print(f"Logging to: {self.log_file.absolute()}")
        print(f"Interval: {interval}s")
        if duration:
            print(f"Duration: {duration}s ({duration // 60}m {duration % 60}s)")
        print("\nPress Ctrl+C to stop\n")
        
        start_time = time.time()
        
        try:
            while True:
                self.log_measurement()
                time.sleep(interval)
                
                if duration and (time.time() - start_time) > duration:
                    print(f"\nLogging duration complete. Logged {self.measurement_count} measurements.")
                    break
                    
        except KeyboardInterrupt:
            print(f"\n\nStopped by user. Logged {self.measurement_count} measurements to {self.log_file}")
            sys.exit(0)
        except Exception as e:
            print(f"\n✗ Fatal error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="SHT45 Sensor Data Logger")
    parser.add_argument("--output", default="sht45_data.csv", help="Output CSV file (default: sht45_data.csv)")
    parser.add_argument("--interval", type=float, default=1.0, help="Time between measurements in seconds (default: 1.0)")
    parser.add_argument("--duration", type=int, help="Stop after N seconds (optional)")
    parser.add_argument("--bus", type=int, default=1, help="I2C bus number (default: 1)")
    parser.add_argument("--address", type=lambda x: int(x, 16), default=0x44, help="I2C address in hex (default: 0x44)")
    
    args = parser.parse_args()
    
    logger = SHT45Logger(args.output, args.bus, args.address)
    logger.run(args.interval, args.duration)
