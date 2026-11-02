# Quick Start

## 1) Install

```bash
pip install mlx90640-driver mlx90640-driver-devicetree
pip install numpy
pip install Flask
```

## 2) Verify device

```bash
i2cdetect -y 1
```

Expected: `0x33`.

## 3) Minimal working script

```python
from mlx90640_backend import ensure_devicetree_backend
from mlx90640.mlx90640 import MLX90640

ensure_devicetree_backend()

cam = MLX90640(slave_address=0x33)
cam.i2c_init("/dev/i2c-1")
cam.set_refresh_rate(4)  # register code 4 = 8 Hz
cam.dump_eeprom()
cam.extract_parameters()

_ = cam.get_frame_data()
ta = cam.get_ta()
to = cam.calculate_to(1.0, ta - 8)  # 768 temperatures in °C

print(f"pixels={len(to)}, min={min(to):.2f}, max={max(to):.2f}")
cam.i2c_tear_down()
```

## 4) Run repository examples

```bash
python3 example_threaded_init.py
python3 example_thermal_camera.py
python3 example_visualization.py
python3 web_frontend.py
```

Open in browser:

```text
http://<raspberry-pi-ip>:5000
```

Web controls:
- One-click stripe-mitigation preset (avg=16, stripe correction=0.85, median=5x5)
- Refresh-rate code (0..7)
- Averaging count (number of frames averaged per output frame)
- Stripe correction (enable + strength)
- Median filter (enable + kernel size)
- Emissivity
- Reflected-temperature offset (Tr offset)
- Color palette
- Interpolation
- Auto/manual temperature scaling

## 5) Performance tuning on Raspberry Pi (optional)

To improve maximum frame readout speed, increase I2C bus baudrate in
[`/boot/firmware/config.txt`](/boot/firmware/config.txt):

```ini
dtparam=i2c_arm_baudrate=1000000
```

Then reboot and benchmark:

```bash
python3 example_frame_rate_test.py
```

Expected effect on this setup: throughput increased from ~25 fps (default 100kHz)
to ~54 fps at refresh-rate code 7 (64Hz target).
