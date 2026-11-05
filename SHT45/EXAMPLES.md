# SHT45 Script Usage Examples

## 1. Basic Continuous Reading (sht45_reader.py)

### Simple usage with defaults (I2C bus 1, address 0x44):
```bash
python3 sht45_reader.py
```

### Expected output:
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

---

## 2. One-Shot Reading (sht45_simple.py)

### Single measurement:
```bash
python3 sht45_simple.py
```

### Use in a shell script or cron job:
```bash
#!/bin/bash
# Take measurement every 5 minutes
python3 sht45_simple.py | grep "Temperature"
```

### Parse in Python:
```python
from sht45_simple import read_sht45_once

data = read_sht45_once()
print(f"Temp: {data['temperature_c']:.1f}°C")
print(f"Humidity: {data['humidity_percent']:.1f}%")
```

---

## 3. Data Logging (sht45_logger.py)

### Basic logging with 1-second interval:
```bash
python3 sht45_logger.py
```

### Log to custom file:
```bash
python3 sht45_logger.py --output my_measurements.csv
```

### Log for 1 hour with 10-second interval:
```bash
python3 sht45_logger.py --interval 10 --duration 3600
```

### Log with different I2C address:
```bash
python3 sht45_logger.py --address 0x45
```

### Log with different I2C bus:
```bash
python3 sht45_logger.py --bus 0
```

### Combine options:
```bash
python3 sht45_logger.py \
    --output data/temp_humidity_$(date +%Y%m%d).csv \
    --interval 5 \
    --duration 86400 \
    --bus 1 \
    --address 0x44
```

### CSV output format:
```csv
Timestamp,Temperature (°C),Humidity (%),Measurement #
2024-11-05T14:23:45.123456,23.45,55.32,1
2024-11-05T14:23:46.234567,23.46,55.31,2
2024-11-05T14:23:47.345678,23.47,55.30,3
```

---

## 4. Advanced Usage

### Continuous background logging with systemd

Create `/etc/systemd/system/sht45-logger.service`:
```ini
[Unit]
Description=SHT45 Sensor Data Logger
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/sht45
ExecStart=/usr/bin/python3 sht45_logger.py --output /var/log/sht45/data.csv --interval 60
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable sht45-logger.service
sudo systemctl start sht45-logger.service
sudo systemctl status sht45-logger.service
```

### Data analysis with Python:
```python
import pandas as pd

# Read logged data
df = pd.read_csv('sht45_data.csv')
df['Timestamp'] = pd.to_datetime(df['Timestamp'])

# Statistics
print(f"Average temperature: {df['Temperature (°C)'].mean():.2f}°C")
print(f"Average humidity: {df['Humidity (%)'].mean():.2f}%")
print(f"Min/Max temp: {df['Temperature (°C)'].min():.2f}°C / {df['Temperature (°C)'].max():.2f}°C")

# Plot with matplotlib
import matplotlib.pyplot as plt

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6))

ax1.plot(df['Timestamp'], df['Temperature (°C)'])
ax1.set_ylabel('Temperature (°C)')
ax1.set_title('SHT45 Measurements')

ax2.plot(df['Timestamp'], df['Humidity (%)'], color='orange')
ax2.set_ylabel('Humidity (%)')
ax2.set_xlabel('Time')

plt.tight_layout()
plt.savefig('sht45_plot.png')
plt.show()
```

### Integration with Home Assistant

Example MQTT publisher:
```python
import paho.mqtt.client as mqtt
from sht45_simple import read_sht45_once

client = mqtt.Client()
client.connect("localhost", 1883, 60)

data = read_sht45_once()
client.publish("home/sensors/sht45/temperature", data['temperature_c'])
client.publish("home/sensors/sht45/humidity", data['humidity_percent'])

client.disconnect()
```

---

## 5. Troubleshooting Commands

### Check I2C connection:
```bash
i2cdetect -y 1
```

### Check for I2C errors:
```bash
dmesg | grep -i i2c
```

### Monitor in real-time:
```bash
watch -n 1 'python3 sht45_simple.py'
```

### Run with debugging:
```bash
python3 -u sht45_reader.py  # Unbuffered output
```

### Check Python version:
```bash
python3 --version
```

### Verify dependencies:
```bash
pip list | grep sensirion
```

---

## 6. Cron Job Examples

### Read sensor every hour, log to file:
```cron
0 * * * * cd /home/pi/sht45 && python3 sht45_simple.py >> sensor_log.txt 2>&1
```

### Read sensor every 15 minutes during working hours:
```cron
*/15 8-18 * * 1-5 cd /home/pi/sht45 && python3 sht45_simple.py >> workday.txt 2>&1
```

### Start continuous logging at boot:
```cron
@reboot cd /home/pi/sht45 && python3 sht45_logger.py --output /home/pi/logs/sht45_$(date +\%Y\%m\%d).csv &
```

---

## 7. Error Handling Examples

### Python script with retry logic:
```python
from sht45_simple import read_sht45_once
import time

max_retries = 3
retry_delay = 1

for attempt in range(max_retries):
    try:
        data = read_sht45_once()
        print(f"Success: {data}")
        break
    except Exception as e:
        print(f"Attempt {attempt + 1} failed: {e}")
        if attempt < max_retries - 1:
            time.sleep(retry_delay)
        else:
            print("All attempts failed")
```

### Check I2C before running:
```bash
#!/bin/bash
if ! i2cdetect -y 1 | grep -q "44"; then
    echo "Sensor not found at 0x44"
    exit 1
fi

python3 sht45_reader.py
```

---

## 8. Performance Tips

- **Faster readings**: Reduce `interval` parameter (minimum ~10ms)
- **Lower power**: Increase `interval` (e.g., 60 seconds for logging)
- **Accurate averages**: Log for extended periods and calculate mean
- **Multiple sensors**: Use different I2C addresses (0x44 and 0x45)
- **Data buffering**: Use logger script for better I/O performance

---

For more information, see README.md and QUICKSTART.md
