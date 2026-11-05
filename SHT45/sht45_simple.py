#!/usr/bin/env python3
"""
Simple one-shot SHT45 reader example
Useful for testing and integration into other scripts
"""

from sensirion_driver_adapters.i2c_adapter.i2c_channel import I2cChannel
from sensirion_i2c_driver import CrcCalculator, I2cConnection, LinuxI2cTransceiver
from sensirion_i2c_sht4x import Sht4xDevice


def read_sht45_once(i2c_bus: int = 1, i2c_address: int = 0x44) -> dict:
    """
    Read SHT45 sensor once and return measurements.
    
    Args:
        i2c_bus: I2C bus number
        i2c_address: I2C address of sensor (typically 0x44 or 0x45)
    
    Returns:
        Dictionary with temperature_c, humidity_percent, and serial_number
    """
    transceiver = LinuxI2cTransceiver(f'/dev/i2c-{i2c_bus}')
    i2c_connection = I2cConnection(transceiver)
    crc = CrcCalculator(width=8, polynomial=0x31, init_value=0xFF, final_xor=0x00)
    channel = I2cChannel(i2c_connection, slave_address=i2c_address, crc=crc)
    sensor = Sht4xDevice(channel)
    
    temperature, humidity = sensor.measure_high_precision()
    serial = sensor.serial_number()
    
    return {
        'temperature_c': temperature.value,
        'humidity_percent': humidity.value,
        'serial_number': serial
    }


if __name__ == "__main__":
    try:
        data = read_sht45_once()
        print(f"Temperature: {data['temperature_c']:.2f}°C")
        print(f"Humidity:    {data['humidity_percent']:.2f}%")
        print(f"Serial:      {data['serial_number']:016X}")
    except Exception as e:
        print(f"Error: {e}")
