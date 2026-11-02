# RP2040 Zero Blink Test (PlatformIO + Arduino)

This project lets you verify that a Raspberry Pi 4 can detect and program an RP2040 Zero.

## Files

- `platformio.ini`: PlatformIO environment for **RP2040 Zero** using the **Arduino** framework.
- `src/main.cpp`: Slow RGB cross-fade with breathing brightness overlay for onboard WS2812 LED.
- `scripts/check_rp2040zero.py`: Python helper to detect the board and optionally upload firmware.

## Prerequisites on Raspberry Pi 4

1. Install Python 3.
2. Install PlatformIO CLI:
   - `sudo apt install -y pipx python3-venv`
   - `pipx ensurepath`
   - `pipx install platformio`
3. Connect the RP2040 Zero over USB.

If you're using VS Code Remote SSH on the Pi, this workspace includes
[.vscode/settings.json](/home/rainer/Projects/RP2040Zero/.vscode/settings.json)
so PlatformIO uses `~/.local/bin/pio` and binds PIO Home in a remote-friendly mode.

## Usage

From this project folder:

```bash
python3 scripts/check_rp2040zero.py
```

This prints detected serial devices and a likely RP2040 port.

To build and upload:

```bash
python3 scripts/check_rp2040zero.py --upload
```

If needed, force a specific port:

```bash
python3 scripts/check_rp2040zero.py --upload --port /dev/ttyACM0
```

## Optional serial monitor

After upload:

```bash
pio device monitor -b 115200
```

The firmware starts with the LED off. Press the BOOTSEL button to toggle the
animation on or off. When enabled, you should see a slow continuous red → green
→ blue fade with a breathing brightness overlay (heartbeat) on the onboard RGB
LED.

> Note: RP2040 Zero's onboard LED is a WS2812 RGB LED (GPIO16), not a simple
> `LED_BUILTIN` pin like Raspberry Pi Pico. This project drives that LED with a
> direct RP2040 PIO WS2812 routine in [main.cpp](/home/rainer/Projects/RP2040Zero/src/main.cpp),
> avoiding core-specific NeoPixel compatibility issues.
>
> BOOTSEL is not a normal GPIO input pin; it is read via the RP2040 QSPI CS
> line, so treating it as GPIO0 does not work reliably.
