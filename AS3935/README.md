# Modern AS3935 Driver

This project modernizes the classic RaspberryPi-AS3935 library from `pcfens` by using:

- Linux I2C access via `smbus2`
- IRQ handling via `gpiod`
- a small Python CLI for quick validation

The original project was focused on Raspberry Pi GPIO and `smbus`; this version keeps the same basic AS3935 register semantics while adopting current Linux practices.

## Features

- Read and write AS3935 registers over I2C
- Noise floor, indoor/outdoor selection, min strikes, disturber masking
- Lightning distance and energy reporting
- Interrupt pin monitoring using `gpiod`
- Optional mock mode for testing without hardware

## Quick start

If you do not want to install the package, run it directly from the repository root:

```bash
PYTHONPATH=src python -m as3935.cli --help
```

This uses the source tree directly without `pip install`.

You can also run the helper script in the repo root without installation:

```bash
python as3935_cli.py --help
```

If you prefer installing the package, use:

```bash
python -m pip install -e .
```

Then run the CLI:

```bash
as3935 --help
```

Example with a real sensor connected to bus 1 and IRQ line 17:

```bash
as3935 status --bus 1 --address 0x03 --irq-line 17
as3935 calibrate --bus 1 --address 0x03 --irq-line 17 --tune-cap 0
as3935 listen --bus 1 --address 0x03 --irq-line 17 --timeout 30
```

If the IRQ pin is not connected or you prefer polling, leave out `--irq-line` or pass `--polling`:

```bash
as3935 listen --bus 1 --address 0x03 --polling --poll-interval 0.25 --timeout 30
```

To test the software without hardware:

```bash
as3935 status --mock
as3935 listen --mock --timeout 5
```

## Wiring example

Typical AS3935 wiring:

- GND -> GND
- VDD -> 3.3V
- SDA -> GPIO 2 (I2C1 SDA)
- SCL -> GPIO 3 (I2C1 SCL)
- IRQ -> GPIO 17 (or the line configured in the CLI)

## Notes

- Some breakout boards default to address `0x03`; others may use `0x00`.
- The AS3935 needs a proper calibration sequence before it will produce reliable readings.
- `gpiod` support requires Linux with `/dev/gpiochipN` available.
