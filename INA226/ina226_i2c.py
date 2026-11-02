#!/usr/bin/env python3
"""Read the most important INA226 values over the Raspberry Pi I2C bus."""

from __future__ import annotations

import atexit
import argparse
import json
import threading
import time
from typing import Any

try:
    from flask import Flask, jsonify, render_template_string, request
except ImportError as exc:  # pragma: no cover - dependency installation guidance
    raise SystemExit(
        "Flask is not installed. Activate the project .venv and run:\n"
        "  python -m pip install -r requirements.txt"
    ) from exc

try:
    from ina226 import INA226
except ImportError as exc:  # pragma: no cover - dependency installation guidance
    raise SystemExit(
        "INA226 library not installed. Activate the project .venv and run:\n"
        "  python -m pip install -r requirements.txt"
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read INA226 bus voltage, shunt voltage, current and power over I2C."
    )
    parser.add_argument("--bus", type=int, default=1, help="I2C bus number (default: 1)")
    parser.add_argument(
        "--address",
        type=lambda value: int(value, 0),
        default=0x40,
        help="INA226 I2C address in hex or decimal (default: 0x40)",
    )
    parser.add_argument(
        "--max-amps",
        type=float,
        default=3.0,
        help="Estimated maximum current in amps for calibration (default: 3.0)",
    )
    parser.add_argument(
        "--shunt-ohms",
        type=float,
        default=0.002,
        help="Shunt resistor value in ohms (default: 0.002 = 2 mΩ)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=1,
        help="Number of readings to capture (default: 1)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Delay in seconds between samples (default: 1.0)",
    )
    parser.add_argument(
        "--serve",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Serve the INA226 values in a small Flask dashboard instead of printing a one-off sample. Default: enabled.",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Flask host to bind when serving (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Flask port to bind when serving (default: 5000)")
    return parser.parse_args()


AVERAGING_LABELS = {
    0: "1",
    1: "4",
    2: "16",
    3: "64",
    4: "128",
    5: "256",
    6: "512",
    7: "1024",
}

CONVERSION_TIME_LABELS = {
    0: "140us",
    1: "204us",
    2: "332us",
    3: "588us",
    4: "1.1ms",
    5: "2.116ms",
    6: "4.156ms",
    7: "8.244ms",
}

MODE_LABELS = {
    0: "Power down",
    1: "Triggered shunt",
    2: "Triggered bus",
    3: "Triggered shunt+bus",
    4: "Power down (reserved)",
    5: "Continuous shunt",
    6: "Continuous bus",
    7: "Continuous shunt+bus",
}


def apply_configuration(sensor: INA226, *, avg_mode: int, bus_ct: int, shunt_ct: int, mode: int) -> None:
    sensor.configure(avg_mode=int(avg_mode), bus_ct=int(bus_ct), shunt_ct=int(shunt_ct))
    sensor.wake(mode=int(mode))


def read_config(sensor: INA226) -> dict[str, Any]:
    config_register = sensor._read_configuration()
    mask_register = sensor._read_mask_register()
    avg_shift = INA226._INA226__AVG0
    bus_shift = INA226._INA226__VBUSCT0
    shunt_shift = INA226._INA226__VSHCT0
    avg_mode = (config_register >> avg_shift) & 0x7
    bus_conversion_time = (config_register >> bus_shift) & 0x7
    shunt_conversion_time = (config_register >> shunt_shift) & 0x7
    mode_value = config_register & 0x7
    return {
        "avg_mode": avg_mode,
        "avg_mode_samples": AVERAGING_LABELS.get(avg_mode, str(avg_mode)),
        "bus_conversion_time": bus_conversion_time,
        "bus_conversion_time_value": CONVERSION_TIME_LABELS.get(bus_conversion_time, str(bus_conversion_time)),
        "shunt_conversion_time": shunt_conversion_time,
        "shunt_conversion_time_value": CONVERSION_TIME_LABELS.get(shunt_conversion_time, str(shunt_conversion_time)),
        "mode": mode_value,
        "mode_value": MODE_LABELS.get(mode_value, str(mode_value)),
        "current_overflow": bool(sensor.current_overflow()),
        "conversion_ready": bool(sensor.is_conversion_ready()),
        "low_battery": bool(sensor.is_low_battery()),
        "config_register": config_register,
        "mask_register": mask_register,
        "limit_register": sensor._read_limit_register(),
        "manufacturer_id": sensor._manufacture_id(),
    }


def read_snapshot(sensor: INA226) -> dict[str, float | bool | int | str]:
    values = {
        "bus_voltage_V": sensor.voltage(),
        "shunt_voltage_mV": sensor.shunt_voltage(),
        "current_mA": sensor.current(),
        "power_mW": sensor.power(),
        "supply_voltage_V": sensor.supply_voltage(),
    }
    values.update(read_config(sensor))
    return values


def read_config_payload(sensor: INA226) -> dict[str, Any]:
    config = read_config(sensor)
    config["mode_label"] = MODE_LABELS.get(config["mode"], str(config["mode"]))
    return config


class Ina226Monitor:
    def __init__(self, sensor: INA226, interval_seconds: float = 2.0) -> None:
        self.sensor = sensor
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._latest: dict[str, Any] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                snapshot = read_snapshot(self.sensor)
                with self._lock:
                    self._latest = snapshot
            except OSError:
                with self._lock:
                    self._latest = {"error": "sensor read failed"}
            time.sleep(self.interval_seconds)

    def refresh_now(self) -> dict[str, Any]:
        try:
            snapshot = read_snapshot(self.sensor)
        except OSError:
            snapshot = {"error": "sensor read failed"}
        with self._lock:
            self._latest = snapshot
        return dict(snapshot)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest)


def build_flask_app(sensor: INA226, *, refresh_interval: int = 2000) -> Flask:
    app = Flask(__name__)
    monitor = Ina226Monitor(sensor, interval_seconds=2.0)
    monitor.start()

    @app.route("/")
    def index() -> str:
        current = read_config_payload(sensor)
        return render_template_string(
            """
            <!doctype html>
            <html lang="en">
            <head>
                <meta charset="utf-8">
                <title>INA226 Dashboard</title>
                <style>
                    body { font-family: sans-serif; background: #111827; color: #f9fafb; padding: 2rem; }
                    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; }
                    .card { background: #1f2937; border-radius: 12px; padding: 1rem 1.2rem; box-shadow: 0 6px 18px rgba(0,0,0,0.2); }
                    .label { color: #9ca3af; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em; }
                    .value { font-size: clamp(1.5rem, 3vw, 2.4rem); font-weight: bold; margin-top: 0.35rem; }
                    .panel { margin-top: 2rem; background: #1f2937; padding: 1rem; border-radius: 12px; }
                    .controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; }
                    label { display: block; margin-bottom: 0.5rem; color: #d1d5db; }
                    select, button { width: 100%; padding: 0.6rem 0.75rem; border-radius: 8px; border: 1px solid #374151; background: #111827; color: #f9fafb; }
                    button { background: #2563eb; border: none; cursor: pointer; font-weight: bold; }
                    .status { margin-top: 0.8rem; color: #93c5fd; min-height: 1.2em; }
                </style>
            </head>
            <body>
                <h1>INA226 dashboard</h1>
                <div class="grid" id="stats">
                    <div class="card"><div class="label">Bus voltage</div><div class="value" id="bus_voltage_V">--</div></div>
                    <div class="card"><div class="label">Shunt voltage</div><div class="value" id="shunt_voltage_mV">--</div></div>
                    <div class="card"><div class="label">Current</div><div class="value" id="current_mA">--</div></div>
                    <div class="card"><div class="label">Power</div><div class="value" id="power_mW">--</div></div>
                    <div class="card"><div class="label">Supply voltage</div><div class="value" id="supply_voltage_V">--</div></div>
                    <div class="card"><div class="label">Avg mode</div><div class="value" id="avg_mode_samples">--</div></div>
                    <div class="card"><div class="label">Bus CT</div><div class="value" id="bus_conversion_time_value">--</div></div>
                    <div class="card"><div class="label">Shunt CT</div><div class="value" id="shunt_conversion_time_value">--</div></div>
                    <div class="card"><div class="label">Current overflow</div><div class="value" id="current_overflow">--</div></div>
                    <div class="card"><div class="label">Conversion ready</div><div class="value" id="conversion_ready">--</div></div>
                    <div class="card"><div class="label">Low battery</div><div class="value" id="low_battery">--</div></div>
                    <div class="card"><div class="label">Mode</div><div class="value" id="mode_value">--</div></div>
                </div>

                <div class="panel">
                    <h2>Configure INA226</h2>
                    <form id="config-form">
                        <div class="controls">
                            <div>
                                <label for="avg_mode">Averaging</label>
                                <select id="avg_mode" name="avg_mode">
                                    {% for value, label in avg_modes %}
                                        <option value="{{ value }}" {% if value == current['avg_mode'] %}selected{% endif %}>{{ label }}</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div>
                                <label for="bus_ct">Bus conversion time</label>
                                <select id="bus_ct" name="bus_ct">
                                    {% for value, label in bus_times %}
                                        <option value="{{ value }}" {% if value == current['bus_conversion_time'] %}selected{% endif %}>{{ label }}</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div>
                                <label for="shunt_ct">Shunt conversion time</label>
                                <select id="shunt_ct" name="shunt_ct">
                                    {% for value, label in shunt_times %}
                                        <option value="{{ value }}" {% if value == current['shunt_conversion_time'] %}selected{% endif %}>{{ label }}</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div>
                                <label for="mode">Operating mode</label>
                                <select id="mode" name="mode">
                                    {% for value, label in modes %}
                                        <option value="{{ value }}" {% if value == current['mode'] %}selected{% endif %}>{{ label }}</option>
                                    {% endfor %}
                                </select>
                            </div>
                        </div>
                        <div style="margin-top: 1rem;">
                            <button type="submit">Apply configuration</button>
                        </div>
                        <div id="config-status" class="status"></div>
                    </form>
                </div>

                <script>
                    function formatMetric(key, value) {
                        if (typeof value === 'boolean') {
                            return value ? 'true' : 'false';
                        }
                        if (typeof value === 'number') {
                            if (key === 'current_mA') {
                                return value.toPrecision(4) + ' mA';
                            }
                            if (key === 'power_mW') {
                                return value.toFixed(3) + ' mW';
                            }
                            if (key === 'bus_voltage_V' || key === 'supply_voltage_V') {
                                return value.toFixed(3) + ' V';
                            }
                            if (key === 'shunt_voltage_mV') {
                                return value.toFixed(3) + ' mV';
                            }
                            return String(value);
                        }
                        return String(value);
                    }

                    async function refresh() {
                        const response = await fetch('/api/metrics');
                        const data = await response.json();
                        for (const [key, value] of Object.entries(data)) {
                            const element = document.getElementById(key);
                            if (element) {
                                element.textContent = formatMetric(key, value);
                            }
                        }
                    }

                    document.getElementById('config-form').addEventListener('submit', async function(event) {
                        event.preventDefault();
                        const status = document.getElementById('config-status');
                        const payload = {
                            avg_mode: Number(document.getElementById('avg_mode').value),
                            bus_ct: Number(document.getElementById('bus_ct').value),
                            shunt_ct: Number(document.getElementById('shunt_ct').value),
                            mode: Number(document.getElementById('mode').value),
                        };
                        status.textContent = 'Applying...';
                        const response = await fetch('/api/config', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify(payload),
                        });
                        const result = await response.json();
                        if (response.ok) {
                            status.textContent = result.message || 'Configuration updated.';
                            await refresh();
                        } else {
                            status.textContent = result.error || 'Update failed.';
                        }
                    });

                    setInterval(refresh, {{ refresh_interval }});
                    refresh();
                </script>
            </body>
            </html>
            """,
            refresh_interval=refresh_interval,
            avg_modes=sorted(AVERAGING_LABELS.items()),
            bus_times=sorted(CONVERSION_TIME_LABELS.items()),
            shunt_times=sorted(CONVERSION_TIME_LABELS.items()),
            modes=sorted(MODE_LABELS.items()),
            current=current,
        )

    @app.route("/api/metrics")
    def api_metrics():
        payload = monitor.snapshot()
        return jsonify(payload)

    @app.route("/api/config", methods=["GET", "POST"])
    def api_config():
        if request.method == "GET":
            return jsonify(read_config_payload(sensor))

        data = request.get_json(silent=True) or {}
        try:
            avg_mode = int(data.get("avg_mode", read_config(sensor)["avg_mode"]))
            bus_ct = int(data.get("bus_ct", read_config(sensor)["bus_conversion_time"]))
            shunt_ct = int(data.get("shunt_ct", read_config(sensor)["shunt_conversion_time"]))
            mode = int(data.get("mode", read_config(sensor)["mode"]))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid configuration values."}), 400

        try:
            apply_configuration(sensor, avg_mode=avg_mode, bus_ct=bus_ct, shunt_ct=shunt_ct, mode=mode)
            monitor.refresh_now()
        except OSError as exc:
            return jsonify({"error": f"Could not update INA226 configuration: {exc}"}), 500

        return jsonify({"message": f"Applied avg={avg_mode}, bus_ct={bus_ct}, shunt_ct={shunt_ct}, mode={MODE_LABELS.get(mode, mode)}"})

    atexit.register(monitor.stop)
    return app


def run_cli(args: argparse.Namespace) -> None:
    sensor = INA226(
        busnum=args.bus,
        address=args.address,
        max_expected_amps=args.max_amps,
        shunt_ohms=args.shunt_ohms,
    )
    sensor.configure()

    if args.serve:
        app = build_flask_app(sensor, refresh_interval=2000)
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
        return

    print(
        json.dumps(
            {
                "bus": args.bus,
                "address": hex(args.address),
                "max_expected_amps_A": args.max_amps,
                "shunt_ohms": args.shunt_ohms,
            },
            separators=(",", ":"),
        )
    )

    for index in range(1, args.samples + 1):
        snapshot = read_snapshot(sensor)
        payload = {"sample": index, **snapshot}
        print(json.dumps(payload, separators=(",", ":")))
        if args.samples > 1 and index < args.samples:
            time.sleep(args.interval)


def main() -> None:
    args = parse_args()
    try:
        run_cli(args)
    except OSError as exc:
        raise SystemExit(
            "Could not read INA226 over I2C. Check the I2C bus number, address, and wiring. "
            f"Details: {exc}"
        ) from exc


if __name__ == "__main__":
    main()
