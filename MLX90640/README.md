# MLX90640 Python Examples

This repository contains working Python examples for MLX90640 on Linux SBCs
using the official Melexis driver stack.

## Required packages

```bash
pip install mlx90640-driver mlx90640-driver-devicetree
pip install numpy matplotlib scipy opencv-python pillow Flask
```

## Hardware check

```bash
i2cdetect -y 1
```

Expected: device at `0x33`.

## Run examples

```bash
python3 example_threaded_init.py
python3 example_thermal_camera.py
python3 example_visualization.py
python3 example_basic_test.py
python3 web_frontend.py
```

Open web UI: `http://<raspberry-pi-ip>:5000`

Web UI controls include refresh-rate code, frame averaging, stripe correction,
median filtering, emissivity, reflected-temperature offset, palette, and
auto/manual temperature scaling.

## Performance tuning (Raspberry Pi)

For higher frame throughput, set the kernel I2C bus speed to 1MHz:

1. Edit [`/boot/firmware/config.txt`](/boot/firmware/config.txt) and add:

```ini
dtparam=i2c_arm_baudrate=1000000
```

2. Reboot.
3. Re-run:

```bash
python3 example_frame_rate_test.py
```

On this setup, increasing from default 100kHz to 1MHz raised measured throughput
from ~25 fps ceiling to ~54 fps at refresh-rate code 7 (64Hz target).

## Important implementation detail

All scripts call [`ensure_devicetree_backend`](/home/rainer/Projects/MLX90640/mlx90640_backend.py:7)
before creating `MLX90640(...)`.

## Repository layout

- [`mlx90640_backend.py`](/home/rainer/Projects/MLX90640/mlx90640_backend.py) - devicetree backend loader
- [`example_threaded_init.py`](/home/rainer/Projects/MLX90640/example_threaded_init.py) - official driver init with timeout guard
- [`example_thermal_camera.py`](/home/rainer/Projects/MLX90640/example_thermal_camera.py) - basic capture/statistics flow
- [`example_visualization.py`](/home/rainer/Projects/MLX90640/example_visualization.py) - visualization example
- [`example_basic_test.py`](/home/rainer/Projects/MLX90640/example_basic_test.py) - simple end-to-end checks
- [`web_frontend.py`](/home/rainer/Projects/MLX90640/web_frontend.py) - Flask MJPEG stream + camera controls
- [`QUICK_START_GUIDE.md`](/home/rainer/Projects/MLX90640/QUICK_START_GUIDE.md) - concise setup and API usage
- [`TROUBLESHOOTING.md`](/home/rainer/Projects/MLX90640/TROUBLESHOOTING.md) - common failures and fixes
