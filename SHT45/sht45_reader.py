#!/usr/bin/env python3
"""
SHT45 Temperature and Humidity Sensor Reader
Uses the official Sensirion I2C SHT4X library
"""

import sys
import time
from sensirion_driver_adapters.i2c_adapter.i2c_channel import I2cChannel
from sensirion_i2c_driver import CrcCalculator, I2cConnection, LinuxI2cTransceiver
from sensirion_i2c_sht4x import Sht4xDevice


def initialize_sensor(i2c_bus: int = 1, i2c_address: int = 0x44) -> Sht4xDevice:
    """
    Initialize the SHT45 sensor on the specified I2C bus.
    
    Args:
        i2c_bus: I2C bus number (default: 1 for Raspberry Pi)
        i2c_address: I2C address of the sensor (typically 0x44 or 0x45)
    
    Returns:
        Sht4xDevice: Initialized sensor object
    
    Raises:
        RuntimeError: If sensor initialization fails
    """
    try:
        transceiver = LinuxI2cTransceiver(f'/dev/i2c-{i2c_bus}')
        i2c_connection = I2cConnection(transceiver)
        crc = CrcCalculator(width=8, polynomial=0x31, init_value=0xFF, final_xor=0x00)
        channel = I2cChannel(i2c_connection, slave_address=i2c_address, crc=crc)
        sensor = Sht4xDevice(channel)
        
        # Read serial number to verify sensor is responding
        serial = sensor.serial_number()
        print(f"✓ SHT45 sensor found (Serial: {serial:016X})")
        
        return sensor
    except Exception as e:
        print(f"✗ Failed to initialize sensor: {e}", file=sys.stderr)
        raise RuntimeError("Sensor initialization failed") from e


def read_measurements(sensor: Sht4xDevice) -> tuple[float, float]:
    """
    Read temperature and humidity from the sensor.
    
    Args:
        sensor: Sht4xDevice object
    
    Returns:
        Tuple of (temperature_celsius, relative_humidity_percent)
    
    Raises:
        RuntimeError: If reading fails
    """
    try:
        temperature, humidity = sensor.measure_high_precision()
        return temperature.value, humidity.value
    except Exception as e:
        print(f"✗ Failed to read measurements: {e}", file=sys.stderr)
        raise RuntimeError("Sensor measurement failed") from e


def print_measurements(temperature: float, humidity: float) -> None:
    """Print formatted measurements."""
    print(f"Temperature: {temperature:6.2f}°C")
    print(f"Humidity:    {humidity:6.2f}%")
    print()


def main():
    """Main function to continuously read sensor data."""
    print("=" * 40)
    print("SHT45 Sensor Reader")
    print("=" * 40)
    print()
    
    try:
        # Initialize sensor
        sensor = initialize_sensor()
        print()
        
        # Read measurements continuously
        print("Reading sensor data (press Ctrl+C to stop):")
        print("-" * 40)
        
        iteration = 0
        while True:
            iteration += 1
            print(f"Reading #{iteration} ({time.strftime('%H:%M:%S')})")
            
            temperature, humidity = read_measurements(sensor)
            print_measurements(temperature, humidity)
            
            # Wait before next reading (SHT45 measurement time is ~10ms)
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopped by user")
        sys.exit(0)
    except RuntimeError as e:
        print(f"\n✗ Fatal error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
