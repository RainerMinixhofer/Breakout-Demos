# Troubleshooting

## `ModuleNotFoundError: mlx90640`

```bash
pip install --upgrade mlx90640-driver mlx90640-driver-devicetree
```

## `Acknowledge issue on I2C bus; data is not valid`

Verify:

1. Device is visible:
   ```bash
   i2cdetect -y 1
   ```
2. Devicetree backend is loaded before creating `MLX90640`:
   - [`ensure_devicetree_backend`](/home/rainer/Projects/MLX90640/mlx90640_backend.py:7)
3. `dump_eeprom()` is called before `extract_parameters()`.

## `extract_parameters()` timeout

Use [`example_threaded_init.py`](/home/rainer/Projects/MLX90640/example_threaded_init.py), which applies a timeout guard.

## Permission denied on `/dev/i2c-1`

```bash
sudo usermod -aG i2c $USER
```

Log out/in, then retry.
