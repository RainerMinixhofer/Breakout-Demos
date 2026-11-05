# SHT45 Quick Start Guide

## Files Created

| File | Purpose |
|------|---------|
| `sht45_reader.py` | Full-featured continuous sensor reader |
| `sht45_simple.py` | Simple one-shot reader for quick tests |
| `requirements.txt` | Python dependencies |
| `README.md` | Complete documentation |

## 1-Minute Setup

### On Raspberry Pi:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Make scripts executable (already done)
chmod +x sht45_reader.py sht45_simple.py

# 3. Run the reader
python3 sht45_reader.py
```

## Hardware Checklist

- [ ] SHT45 sensor connected to I2C bus (SCL/SDA)
- [ ] Power supply connected (VDD to 3.3V, GND to ground)
- [ ] Pull-up resistors installed (4.7kΩ typical)
- [ ] I2C enabled in raspi-config (if on Raspberry Pi)

## Verify I2C Connection

```bash
# List all I2C devices
i2cdetect -y 1

# Should show sensor at 0x44 or 0x45
```

## Script Usage

### Continuous Reading (sht45_reader.py)
```bash
python3 sht45_reader.py
```
- Reads sensor every 1 second
- Shows timestamp and measurements
- Press Ctrl+C to stop

### One-Shot Reading (sht45_simple.py)
```bash
python3 sht45_simple.py
```
- Single measurement
- Useful for integration with other scripts

## Example Output

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
```

## Common Issues

| Issue | Solution |
|-------|----------|
| "No such file or directory: '/dev/i2c-1'" | Enable I2C: `sudo raspi-config` |
| "Remote I/O error" | Check wiring and pull-up resistors |
| Permission denied | Add to i2c group: `sudo usermod -a -G i2c $USER` |
| No data appearing | Verify with `i2cdetect -y 1` |

## Next Steps

- Modify sensor address in script (if using 0x45 instead of 0x44)
- Add data logging to file
- Integrate with Home Assistant or other systems
- See `README.md` for full API reference
