# MMC5983MA Python Driver and CLI

This project provides a small Python driver and command-line interface for the MMC5983MA 3-axis magnetometer. The sensor is expected to be connected on the I2C bus at address `0x30`.

## Features

- Reads raw X/Y/Z magnetic data from the MMC5983MA
- Converts readings to gauss or microtesla
- Supports simple offset calibration
- Includes a quick CLI test tool for live readings
- Works with Linux I2C devices using `smbus2`

## Hardware setup

The MMC5983MA is connected to the host board via I2C and uses the default address:

- I2C address: `0x30`
- Bus: usually `1` on Raspberry Pi and many Linux SBCs

Confirm the bus and device mapping for your platform before running the sample commands.

## Requirements

- Python 3.9+
- I2C enabled on the host system
- `smbus2` Python package

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Quick start

Run a single measurement sample:

```bash
python3 mmc5983ma.py --bus 1 --address 0x30 --samples 1
```

Run several samples with a delay:

```bash
python3 mmc5983ma.py --bus 1 --address 0x30 --samples 5 --delay 0.25
```

Read in microtesla instead of gauss:

```bash
python3 mmc5983ma.py --bus 1 --address 0x30 --microtesla
```

Read the board heading in degrees assuming the breakout is mounted flat on the X/Y plane:

```bash
python3 mmc5983ma.py --bus 1 --address 0x30 --orientation
```

Calibrate the sensor before reading:

```bash
python3 mmc5983ma.py --bus 1 --address 0x30 --calibrate --samples 3
```

## CLI options

```bash
python3 mmc5983ma.py --help
```

Available options:

- `--bus`: I2C bus number (default: `1`)
- `--address`: sensor address in hex or decimal (default: `0x30`)
- `--samples`: number of readings to collect
- `--delay`: seconds between readings
- `--calibrate`: perform a simple offset calibration
- `--microtesla`: print values in microtesla instead of gauss
- `--orientation`: print the horizontal heading in degrees assuming the breakout is flat on the board plane

## Python API

Example:

```python
from mmc5983ma import MMC5983MA

sensor = MMC5983MA(bus_number=1, address=0x30)

if not sensor.is_connected():
    raise RuntimeError("MMC5983MA not found on I2C bus")

sensor.calibrate_offsets()

x, y, z = sensor.read_magnetic()
print(f"x={x:.6f} G, y={y:.6f} G, z={z:.6f} G")

sensor.close()
```

### Available methods

- `is_connected()` — verify the sensor responds on the configured address
- `read_raw_xyz()` — read raw X/Y/Z counts
- `read_magnetic()` — read X/Y/Z in gauss
- `read_magnetic_microtesla()` — read X/Y/Z in microtesla
- `read_orientation()` — return horizontal heading in degrees plus the magnetic triplet, assuming the board is flat
- `read_temperature_c()` — read sensor temperature in °C
- `calibrate_offsets()` — set offset values using the sensor's calibration cycle

## Calibration behavior

The driver stores per-axis offset values and applies them during magnetic-field conversion. A simple calibration routine performs a SET/RESET operation sequence to reduce bias caused by local magnetic conditions.

If the environment is strongly magnetized or contains nearby ferromagnetic material, recalibrate before taking measurements.

## Troubleshooting

### Sensor not found

- Confirm the board is connected to the correct I2C bus
- Confirm the address is `0x30`
- Check that the I2C interface is enabled on the host
- On Linux, verify the bus with a tool such as:

```bash
i2cdetect -y 1
```

### Noisy or unstable values

- Move the sensor away from magnets, motors, and large metal objects
- Re-run calibration
- Increase the sample count or average multiple readings

### Import errors

If Python reports a missing module error, install the driver dependency:

```bash
python3 -m pip install smbus2
```

## Files

- `mmc5983ma.py` — driver implementation
- `mmc5983ma_cli.py` — CLI entry point
- `requirements.txt` — Python dependencies

## Notes

This driver is intended for direct I2C access and is suitable for quick development, testing, and integration into project code that needs magnetometer data from the MMC5983MA.
