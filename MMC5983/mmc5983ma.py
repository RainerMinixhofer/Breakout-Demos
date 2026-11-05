#!/usr/bin/env python3
"""Driver for the MMC5983MA 3-axis magnetometer."""

from __future__ import annotations

import math
import threading
import time
from typing import Iterable, Tuple

try:
    import smbus2 as smbus
except ImportError:  # pragma: no cover - fallback for older Linux boards
    try:
        import smbus  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "This driver requires the 'smbus2' package. Install it with: pip install smbus2"
        ) from exc


class MMC5983MA:
    """Read the MMC5983MA via its default I2C address 0x30."""

    REG_X_OUT_0 = 0x00
    REG_X_OUT_1 = 0x01
    REG_Y_OUT_0 = 0x02
    REG_Y_OUT_1 = 0x03
    REG_Z_OUT_0 = 0x04
    REG_Z_OUT_1 = 0x05
    REG_XYZ_OUT_2 = 0x06
    REG_T_OUT = 0x07
    REG_STATUS = 0x08
    REG_INT_CTRL_0 = 0x09
    REG_INT_CTRL_1 = 0x0A
    REG_INT_CTRL_2 = 0x0B
    REG_INT_CTRL_3 = 0x0C
    REG_PROD_ID = 0x2F

    MEAS_M_DONE = 1 << 0
    MEAS_T_DONE = 1 << 1
    TM_M = 1 << 0
    TM_T = 1 << 1
    SET_OPERATION = 1 << 3
    RESET_OPERATION = 1 << 4
    PROD_ID = 0x30

    FULL_SCALE_BITS = 18
    FULL_SCALE_COUNTS = 1 << (FULL_SCALE_BITS - 1)
    GAUSS_PER_COUNT = 8.0 / FULL_SCALE_COUNTS

    def __init__(self, bus_number: int = 1, address: int = 0x30) -> None:
        self.bus_number = bus_number
        self.address = address
        self.bus = smbus.SMBus(bus_number)

        self.x_offset = float(1 << 17)
        self.y_offset = float(1 << 17)
        self.z_offset = float(1 << 17)

    def __enter__(self) -> "MMC5983MA":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self.bus.close()

    def is_connected(self) -> bool:
        try:
            return self.read_byte(self.REG_PROD_ID) == self.PROD_ID
        except OSError:
            return False

    def read_byte(self, register: int) -> int:
        return int(self.bus.read_byte_data(self.address, register))

    def write_byte(self, register: int, value: int) -> None:
        self.bus.write_byte_data(self.address, register, int(value) & 0xFF)

    def read_block(self, register: int, length: int) -> list[int]:
        return list(self.bus.read_i2c_block_data(self.address, register, length))

    def _trigger_measurement(self) -> None:
        current = self.read_byte(self.REG_INT_CTRL_0)
        self.write_byte(self.REG_INT_CTRL_0, current | self.TM_M)

        deadline = time.monotonic() + 0.250
        while time.monotonic() < deadline:
            if self.read_byte(self.REG_STATUS) & self.MEAS_M_DONE:
                break
            time.sleep(0.001)

        current = self.read_byte(self.REG_INT_CTRL_0)
        self.write_byte(self.REG_INT_CTRL_0, current & ~self.TM_M)

    def read_raw_xyz(self) -> Tuple[int, int, int]:
        """Read the 18-bit raw X/Y/Z counts from the sensor."""
        self._trigger_measurement()
        values = self.read_block(self.REG_X_OUT_0, 7)

        x = values[0]
        x = (x << 8) | values[1]
        x = (x << 2) | (values[6] >> 6)

        y = values[2]
        y = (y << 8) | values[3]
        y = (y << 2) | ((values[6] >> 4) & 0x03)

        z = values[4]
        z = (z << 8) | values[5]
        z = (z << 2) | ((values[6] >> 2) & 0x03)

        return x, y, z

    def read_magnetic(self, gain_gauss: float = 8.0) -> Tuple[float, float, float]:
        """Return magnetic field in gauss for X/Y/Z, using the device's raw 18-bit data."""
        x_raw, y_raw, z_raw = self.read_raw_xyz()
        x = (x_raw - self.x_offset) * gain_gauss / self.FULL_SCALE_COUNTS
        y = (y_raw - self.y_offset) * gain_gauss / self.FULL_SCALE_COUNTS
        z = (z_raw - self.z_offset) * gain_gauss / self.FULL_SCALE_COUNTS
        return x, y, z

    def read_magnetic_microtesla(self, gain_gauss: float = 8.0) -> Tuple[float, float, float]:
        x, y, z = self.read_magnetic(gain_gauss=gain_gauss)
        return (x * 10000.0, y * 10000.0, z * 10000.0)

    def read_orientation(self) -> Tuple[float, float, float, float]:
        """Return the horizontal board heading in degrees and the X/Y/Z magnetic components.

        Assumes the breakout board is lying flat in the X/Y plane. The heading is
        computed around the Z axis using the horizontal magnetic field vector:
        0° aligns with +X, 90° with +Y, 180° with -X, and 270° with -Y.
        """
        x, y, z = self.read_magnetic()
        heading_deg = math.degrees(math.atan2(y, x))
        if heading_deg < 0.0:
            heading_deg += 360.0
        return heading_deg, x, y, z

    def read_temperature_c(self) -> float:
        """Temperature in °C, per the MMC5983MA datasheet."""
        current = self.read_byte(self.REG_INT_CTRL_0)
        self.write_byte(self.REG_INT_CTRL_0, current | self.TM_T)
        deadline = time.monotonic() + 0.050
        while time.monotonic() < deadline:
            if self.read_byte(self.REG_STATUS) & self.MEAS_T_DONE:
                break
            time.sleep(0.001)
        temperature_raw = self.read_byte(self.REG_T_OUT)
        self.write_byte(self.REG_INT_CTRL_0, current & ~self.TM_T)
        return -75.0 + (float(temperature_raw) * (200.0 / 255.0))

    def perform_set_operation(self) -> None:
        current = self.read_byte(self.REG_INT_CTRL_0)
        self.write_byte(self.REG_INT_CTRL_0, current | self.SET_OPERATION)
        time.sleep(0.001)
        self.write_byte(self.REG_INT_CTRL_0, current)

    def perform_reset_operation(self) -> None:
        current = self.read_byte(self.REG_INT_CTRL_0)
        self.write_byte(self.REG_INT_CTRL_0, current | self.RESET_OPERATION)
        time.sleep(0.001)
        self.write_byte(self.REG_INT_CTRL_0, current)

    def calibrate_offsets(self) -> None:
        """Apply a SET then RESET calibration as described in the datasheet."""
        self.perform_set_operation()
        x1, y1, z1 = self.read_raw_xyz()
        self.perform_reset_operation()
        x2, y2, z2 = self.read_raw_xyz()
        self.x_offset = (x1 + x2) / 2.0
        self.y_offset = (y1 + y2) / 2.0
        self.z_offset = (z1 + z2) / 2.0


def run_web_server(sensor: MMC5983MA, port: int = 5000, host: str = "0.0.0.0") -> None:
    """Run a Flask web server showing real-time sensor orientation."""
    from flask import Flask, jsonify, render_template

    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = True
    
    sensor_data = {"heading": 0.0, "x": 0.0, "y": 0.0, "z": 0.0}
    lock = threading.Lock()

    def update_sensor():
        """Background thread that continuously updates sensor readings."""
        while True:
            try:
                heading_deg, x, y, z = sensor.read_orientation()
                with lock:
                    sensor_data["heading"] = round(heading_deg, 2)
                    sensor_data["x"] = round(x, 6)
                    sensor_data["y"] = round(y, 6)
                    sensor_data["z"] = round(z, 6)
                time.sleep(0.5)
            except Exception:
                time.sleep(1)

    @app.route("/")
    def index():
        return render_template("mmc5983ma.html")

    @app.route("/api/orientation")
    def get_orientation():
        with lock:
            return jsonify(sensor_data)

    thread = threading.Thread(target=update_sensor, daemon=True)
    thread.start()

    print(f"Starting MMC5983MA web server on http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MMC5983MA magnetometer readout")
    parser.add_argument("--bus", type=int, default=1, help="I2C bus number (default: 1)")
    parser.add_argument("--address", type=lambda value: int(value, 0), default=0x30,
                        help="I2C address in decimal or hex (default: 0x30)")
    parser.add_argument("--samples", type=int, default=1, help="Number of readings to take")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay in seconds between samples")
    parser.add_argument("--calibrate", action="store_true", help="Calibrate the magnetic offsets")
    parser.add_argument("--microtesla", action="store_true", help="Print values in microtesla instead of gauss")
    parser.add_argument("--orientation", action="store_true",
                        help="Print the horizontal heading in degrees assuming the board lies flat")
    parser.add_argument("--web", action="store_true", help="Launch a Flask web server showing orientation")
    parser.add_argument("--port", type=int, default=5000, help="Port for web server (default: 5000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host for web server (default: 0.0.0.0)")
    args = parser.parse_args()

    with MMC5983MA(bus_number=args.bus, address=args.address) as sensor:
        if not sensor.is_connected():
            raise SystemExit(f"MMC5983MA not found at 0x{args.address:02x} on bus {args.bus}.")

        if args.calibrate:
            sensor.calibrate_offsets()

        if args.web:
            run_web_server(sensor, port=args.port, host=args.host)
        else:
            for index in range(args.samples):
                if args.microtesla:
                    x, y, z = sensor.read_magnetic_microtesla()
                    unit = "uT"
                else:
                    x, y, z = sensor.read_magnetic()
                    unit = "G"

                if args.orientation:
                    heading_deg, x_axis, y_axis, z_axis = sensor.read_orientation()
                    print(
                        f"sample {index}: heading={heading_deg: .2f} deg  "
                        f"x={x_axis: .6f} {unit}  y={y_axis: .6f} {unit}  z={z_axis: .6f} {unit}"
                    )
                else:
                    print(f"sample {index}: x={x: .6f} {unit}  y={y: .6f} {unit}  z={z: .6f} {unit}")
                if index + 1 < args.samples:
                    time.sleep(args.delay)


if __name__ == "__main__":
    main()
