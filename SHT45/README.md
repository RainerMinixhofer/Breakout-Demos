# SHT45 Sensor Reader

A Python script to read temperature and humidity data from a Sensirion SHT45 sensor using the official `sensirion-i2c-sht4x` library.

## Hardware Requirements

- **SHT45 Sensor** (Sensirion SHT45)
- **Raspberry Pi** or other Linux system with I2C support
- **I2C Pull-up Resistors** (typically 4.7kΩ to VDD)

### Wiring (Raspberry Pi)

| SHT45 Pin | RPi Pin | Cable Color |
|-----------|---------|-------------|
| SDA (1)   | GPIO 2  | Green       |
| GND (2)   | GND     | Black       |
| SCL (3)   | GPIO 3  | Yellow      |
| VDD (4)   | 3.3V    | Red         |

## Installation

### 1. Enable I2C on Raspberry Pi

```bash
sudo raspi-config
```

- Select "Interface Options" → "I2C" → Enable

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

Or install individually:

```bash
pip install sensirion-i2c-sht4x
pip install sensirion-i2c-driver
```

### 3. Verify I2C Connection

List connected I2C devices:

```bash
i2cdetect -y 1
```

The SHT45 should appear at address 0x44 (or 0x45 depending on ADDR pin configuration).

## Usage

### Basic Reading

Run the script to continuously read sensor data:

```bash
python3 sht45_reader.py
```

Output example:
```
========================================
SHT45 Sensor Reader
========================================

✓ SHT45 sensor found (Serial: 1234567890ABCDEF)

Reading sensor data (press Ctrl+C to stop):
----------------------------------------
Reading #1 (14:23:45)
Temperature:  23.45°C
Humidity:     55.32%

Reading #2 (14:23:46)
Temperature:  23.46°C
Humidity:     55.31%
```

### Custom I2C Configuration

To use a different I2C bus or address, modify the `initialize_sensor()` call:

```python
sensor = initialize_sensor(i2c_bus=1, i2c_address=0x45)
```

## API Reference

### `initialize_sensor(i2c_bus=1, i2c_address=0x44)`

Initialize and verify the SHT45 sensor connection.

**Parameters:**
- `i2c_bus` (int): I2C bus number (default: 1)
- `i2c_address` (int): Hex address of sensor (default: 0x44)

**Returns:** `Sht4xDevice` object

**Raises:** `RuntimeError` if initialization fails

### `read_measurements(sensor)`

Read temperature and humidity from the sensor.

**Parameters:**
- `sensor` (Sht4xDevice): Sensor object from `initialize_sensor()`

**Returns:** Tuple of `(temperature_celsius, relative_humidity_percent)`

**Raises:** `RuntimeError` if reading fails

## Troubleshooting

### "No such file or directory: '/dev/i2c-1'"

- I2C interface not enabled on Raspberry Pi
- Solution: Run `sudo raspi-config` and enable I2C

### "Remote I/O error" or sensor not found

- Wiring issue or sensor at wrong I2C address
- Verify wiring and check with `i2cdetect -y 1`
- Check if pull-up resistors are installed (4.7kΩ typical)

### Permission Denied

Add user to i2c group:

```bash
sudo usermod -a -G i2c $USER
newgrp i2c
```

Then log out and back in for changes to take effect.

## Performance

- **Measurement Time**: ~10ms per reading
- **I2C Speed**: 100-400 kHz supported
- **Temperature Range**: -40°C to +125°C
- **Humidity Range**: 0% to 100% RH

## License

This script uses the official Sensirion SHT4X library. See the library documentation for license details.

## References

- [Sensirion SHT45 Datasheet](https://sensirion.com/products/catalog/SHT45/)
- [sensirion-i2c-sht4x PyPI](https://pypi.org/project/sensirion-i2c-sht4x/)
- [GitHub - Sensirion Python I2C SHT4X](https://github.com/Sensirion/python-i2c-sht4x)
