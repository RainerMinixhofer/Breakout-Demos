#!/usr/bin/env python3
"""Read temperature values and diagnostics from a DS18B20 on Raspberry Pi.

The sensor is typically connected to the Raspberry Pi GPIO 4 (BCM) data pin,
with the 1-Wire interface enabled in /boot/config.txt or via dtoverlay.
Supports:
- single temperature reads (CLI),
- detailed diagnostics output (CLI JSON),
- a Flask web dashboard with a live card and six-hour history plot.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from flask import Flask, jsonify, render_template_string, request
except ImportError:  # pragma: no cover - optional dependency in CLI-only mode
    Flask = None
    jsonify = None
    render_template_string = None
    request = None

try:
    import pyownet.protocol as pyownet_protocol
except ImportError:  # pragma: no cover - optional dependency in read-only mode
    pyownet_protocol = None

DEFAULT_W1_ROOT = Path("/sys/bus/w1/devices")
DEFAULT_SENSOR_PREFIXES = ("28-", "10-")
SIX_HOURS_SECONDS = 6 * 60 * 60
DEFAULT_SAMPLE_INTERVAL = 30.0
DEFAULT_OWSERVER_HOST = "localhost"
DEFAULT_OWSERVER_PORT = 4304


def iter_sensor_paths(root: Path, prefixes: tuple[str, ...] = DEFAULT_SENSOR_PREFIXES):
    """Yield DS18B20 device directories under the 1-Wire sysfs tree."""
    if not root.exists():
        return

    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        if path.name.startswith(prefixes):
            slave_file = path / "w1_slave"
            if slave_file.exists():
                yield path


def find_sensor_paths(root: Path = DEFAULT_W1_ROOT) -> list[Path]:
    """Return every detected DS18B20 device path under the 1-Wire sysfs tree."""
    return list(iter_sensor_paths(root))


def find_sensor_path(sensor_id: str | None = None, root: Path = DEFAULT_W1_ROOT) -> Path:
    """Return the sensor directory, auto-detecting the first DS18B20 if no ID is given."""
    sensor_paths = find_sensor_paths(root)
    if not sensor_paths:
        raise FileNotFoundError(
            f"No DS18B20 sensor found under {root}. "
            "Ensure 1-Wire is enabled and the sensor is connected to the default Pi data pin."
        )

    if sensor_id is None:
        return sensor_paths[0]

    for path in sensor_paths:
        if path.name == sensor_id:
            return path
    raise FileNotFoundError(f"Sensor {sensor_id!r} was not found under {root}.")


def _read_sensor_lines(sensor_path: Path | str) -> tuple[str, str]:
    sensor_path = Path(sensor_path)
    slave_file = sensor_path / "w1_slave"

    try:
        lines = slave_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise OSError(f"Unable to read sensor data from {slave_file}: {exc}") from exc

    if len(lines) < 2:
        raise ValueError(f"Unexpected sensor output from {slave_file}: {lines!r}")
    return lines[0], lines[1]


def _parse_temperature_from_line(data_line: str, raw_lines: tuple[str, str]) -> float:
    match = re.search(r"t=(-?\d+)", data_line)
    if match is None:
        raise ValueError(f"Temperature value not found in sensor output: {raw_lines!r}")

    return float(match.group(1)) / 1000.0


def _dallas_crc8(data: list[int]) -> int:
    crc = 0
    for value in data:
        in_byte = value & 0xFF
        for _ in range(8):
            mix = (crc ^ in_byte) & 0x01
            crc >>= 1
            if mix:
                crc ^= 0x8C
            in_byte >>= 1
    return crc & 0xFF


def _to_signed_8(value: int) -> int:
    return value - 256 if value >= 128 else value


def _to_signed_16(value: int) -> int:
    return value - 65536 if value >= 32768 else value


def _config_byte_to_resolution_bits(config_byte: int) -> int | None:
    resolution_field = (config_byte >> 5) & 0b11
    resolution_by_cfg = {0b00: 9, 0b01: 10, 0b10: 11, 0b11: 12}
    return resolution_by_cfg.get(resolution_field)


def _resolution_bits_to_config_byte(resolution_bits: int) -> int:
    resolution_by_cfg = {9: 0b00, 10: 0b01, 11: 0b10, 12: 0b11}
    if resolution_bits not in resolution_by_cfg:
        raise ValueError(f"Unsupported resolution bits: {resolution_bits}. Supported values are 9, 10, 11, and 12.")
    return resolution_by_cfg[resolution_bits] << 5


def _determine_alarm_state(temp_c: float, alarm_high_celsius: float | None, alarm_low_celsius: float | None) -> tuple[bool, str]:
    if alarm_high_celsius is None and alarm_low_celsius is None:
        return False, "unconfigured"
    if alarm_high_celsius is not None and temp_c > float(alarm_high_celsius):
        return True, "high"
    if alarm_low_celsius is not None and temp_c < float(alarm_low_celsius):
        return True, "low"
    return False, "normal"


def read_diagnostics(sensor_path: Path | str) -> dict[str, Any]:
    """Read and parse DS18B20 diagnostic information from w1_slave."""
    sensor_path = Path(sensor_path)
    line1, line2 = _read_sensor_lines(sensor_path)

    row_match = re.match(
        r"^\s*([0-9a-f]{2}(?:\s+[0-9a-f]{2}){8})\s*:\s*crc=([0-9a-f]{2})\s+(YES|NO)\s*$",
        line1,
        flags=re.IGNORECASE,
    )
    if row_match is None:
        raise ValueError(f"Unexpected first line format in sensor output: {line1!r}")

    raw_bytes = [int(part, 16) for part in row_match.group(1).split()]
    if len(raw_bytes) != 9:
        raise ValueError(f"Expected 9 scratchpad bytes, got {len(raw_bytes)} from {line1!r}")

    crc_reported = int(row_match.group(2), 16)
    crc_calculated = _dallas_crc8(raw_bytes[:-1])
    crc_ok = row_match.group(3).upper() == "YES" and crc_reported == crc_calculated

    temp_c = _parse_temperature_from_line(line2, (line1, line2))
    temp_f = temp_c * 9.0 / 5.0 + 32.0

    raw_temp = _to_signed_16((raw_bytes[1] << 8) | raw_bytes[0])
    raw_temp_c = raw_temp / 16.0
    family_code = sensor_path.name.split("-", maxsplit=1)[0].lower()

    config_byte = raw_bytes[4]
    alarm_high_celsius = _to_signed_8(raw_bytes[2])
    alarm_low_celsius = _to_signed_8(raw_bytes[3])
    resolution_bits = _config_byte_to_resolution_bits(config_byte) if family_code == "28" else None
    alarm_triggered, alarm_state = _determine_alarm_state(temp_c, alarm_high_celsius, alarm_low_celsius)

    diagnostics = {
        "sensor_id": sensor_path.name,
        "sensor_path": str(sensor_path),
        "family_code": family_code,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "crc_kernel_ok": row_match.group(3).upper() == "YES",
        "crc_reported_hex": f"0x{crc_reported:02X}",
        "crc_calculated_hex": f"0x{crc_calculated:02X}",
        "crc_match": crc_reported == crc_calculated,
        "crc_ok": crc_ok,
        "raw_scratchpad_bytes_hex": [f"{byte:02X}" for byte in raw_bytes],
        "raw_temperature_lsb_msb_hex": [f"{raw_bytes[0]:02X}", f"{raw_bytes[1]:02X}"],
        "raw_temperature_register": raw_temp,
        "raw_temperature_celsius": raw_temp_c,
        "temperature_celsius": temp_c,
        "temperature_fahrenheit": temp_f,
        "alarm_high_celsius": alarm_high_celsius,
        "alarm_low_celsius": alarm_low_celsius,
        "alarm_triggered": alarm_triggered,
        "alarm_state": alarm_state,
        "config_register_hex": f"0x{config_byte:02X}",
        "config_register_binary": format(config_byte, "08b"),
        "resolution_bits": resolution_bits,
        "raw_lines": [line1, line2],
    }
    return diagnostics


def read_temperature_celsius(sensor_path: Path | str) -> float:
    """Read the current temperature from a DS18B20 sensor in degrees Celsius."""
    line1, line2 = _read_sensor_lines(sensor_path)
    return _parse_temperature_from_line(line2, (line1, line2))


def read_temperature(sensor_id: str | None = None, root: Path = DEFAULT_W1_ROOT) -> float:
    """Return the temperature in Celsius for the default Raspberry Pi DS18B20 device."""
    path = find_sensor_path(sensor_id=sensor_id, root=root)
    return read_temperature_celsius(path)


def _build_sensor_settings_response(sensor_path: Path, *, resolution_bits: int | None = None, alarm_high_celsius: float | None = None, alarm_low_celsius: float | None = None) -> dict[str, Any]:
    current = read_diagnostics(sensor_path)
    settings = {
        "sensor_id": current["sensor_id"],
        "resolution_bits": int(current["resolution_bits"]) if current["resolution_bits"] is not None else None,
        "alarm_high_celsius": current["alarm_high_celsius"],
        "alarm_low_celsius": current["alarm_low_celsius"],
        "config_register_hex": current["config_register_hex"],
        "alarm_triggered": current["alarm_triggered"],
        "alarm_state": current["alarm_state"],
    }
    if resolution_bits is not None:
        settings["requested_resolution_bits"] = resolution_bits
    if alarm_high_celsius is not None:
        settings["requested_alarm_high_celsius"] = alarm_high_celsius
    if alarm_low_celsius is not None:
        settings["requested_alarm_low_celsius"] = alarm_low_celsius
    return settings


def _parse_owserver_backend_spec(raw_backend_spec: str | None) -> tuple[str, int]:
    if raw_backend_spec is None or not raw_backend_spec.strip():
        return DEFAULT_OWSERVER_HOST, DEFAULT_OWSERVER_PORT

    parsed = urlparse(raw_backend_spec)
    if parsed.scheme.lower() != "owserver":
        raise ValueError(
            "DS18B20_RAW_WRITE_BACKEND must use the format owserver://host:port "
            "(for example owserver://localhost:4304)."
        )
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError(
            "DS18B20_RAW_WRITE_BACKEND only accepts owserver://host:port and must not include a path."
        )
    host = parsed.hostname or DEFAULT_OWSERVER_HOST
    port = parsed.port or DEFAULT_OWSERVER_PORT
    return host, port


def _iter_owserver_sensor_entries(proxy: Any) -> list[str]:
    entries = proxy.dir("/")
    return [entry for entry in entries if re.match(r"^/[0-9A-Fa-f]{2}\.[0-9A-Fa-f]+/$", entry)]


def _sysfs_id_from_owserver_entry(entry: str) -> str | None:
    match = re.match(r"^/([0-9A-Fa-f]{2})\.([0-9A-Fa-f]+)/$", entry)
    if match is None:
        return None
    family = match.group(1).lower()
    serial = match.group(2).lower()
    return f"{family}-{serial}"


def _reverse_id_serial_bytes(serial: str) -> str:
    if len(serial) % 2 != 0:
        return serial
    serial_bytes = [serial[i:i + 2] for i in range(0, len(serial), 2)]
    return "".join(reversed(serial_bytes))


def _resolve_owserver_device_path(proxy: Any, sensor_id: str) -> str:
    sensor_id_lower = sensor_id.lower()
    parts = sensor_id_lower.split("-", maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"Invalid sensor ID {sensor_id!r}. Expected format family-serial, for example 28-0123456789ab.")

    family, serial = parts
    candidates = {
        sensor_id_lower,
        f"{family}-{_reverse_id_serial_bytes(serial)}",
    }

    device_by_sysfs_id: dict[str, str] = {}
    for entry in _iter_owserver_sensor_entries(proxy):
        sysfs_id = _sysfs_id_from_owserver_entry(entry)
        if sysfs_id is None:
            continue
        device_by_sysfs_id.setdefault(sysfs_id, entry)

    for candidate in candidates:
        entry = device_by_sysfs_id.get(candidate)
        if entry is not None:
            return entry

    available_ids = sorted(device_by_sysfs_id.keys())
    available = ", ".join(available_ids) or "(none)"
    available_families = {item.split("-", maxsplit=1)[0] for item in available_ids if "-" in item}
    expected_family = family
    hint = ""
    if expected_family == "28" and "28" not in available_families and available_ids:
        if available_families.issubset({"10", "05"}):
            hint = (
                " owserver appears to be serving FAKE devices (default Debian config). "
                "Update /etc/owfs.conf to use real hardware (for example 'server: usb = all'), then restart owserver."
            )
        else:
            hint = (
                " owserver and Linux sysfs appear to point to different 1-Wire buses/adapters. "
                "Configure owserver to the same hardware source as /sys/bus/w1/devices."
            )

    raise OSError(f"Sensor {sensor_id} was not found on owserver. Available devices: {available}.{hint}")


def _write_owserver_text(proxy: Any, path: str, value: str) -> None:
    proxy.write(path, value.encode("ascii"))


def configure_sensor(sensor_path: Path | str, *, resolution_bits: int | None = None, alarm_high_celsius: float | None = None, alarm_low_celsius: float | None = None) -> dict[str, Any]:
    """Write DS18B20 alarm/resolution settings through owserver when available."""
    sensor_path = Path(sensor_path)
    diagnostics = read_diagnostics(sensor_path)

    if resolution_bits is not None:
        if resolution_bits not in {9, 10, 11, 12}:
            raise ValueError("Resolution must be one of 9, 10, 11, or 12 bits.")

    if alarm_high_celsius is not None:
        if not -128.0 <= float(alarm_high_celsius) <= 127.0:
            raise ValueError("Alarm high temperature must be between -128 and 127 °C.")
    if alarm_low_celsius is not None:
        if not -128.0 <= float(alarm_low_celsius) <= 127.0:
            raise ValueError("Alarm low temperature must be between -128 and 127 °C.")
    if alarm_high_celsius is not None and alarm_low_celsius is not None and float(alarm_low_celsius) > float(alarm_high_celsius):
        raise ValueError("Alarm low temperature must be less than or equal to alarm high temperature.")

    slave_file = sensor_path / "w1_slave"
    if not slave_file.exists():
        raise OSError(f"No sensor interface exists at {slave_file}.")

    if pyownet_protocol is None:
        return {
            "sensor_id": diagnostics["sensor_id"],
            "ok": False,
            "supported": False,
            "reason": "pyownet is not installed in the active Python environment. Install it with: pip install pyownet",
            "settings": _build_sensor_settings_response(
                sensor_path,
                resolution_bits=resolution_bits,
                alarm_high_celsius=alarm_high_celsius,
                alarm_low_celsius=alarm_low_celsius,
            ),
        }

    backend_spec = os.environ.get("DS18B20_RAW_WRITE_BACKEND")
    try:
        ow_host, ow_port = _parse_owserver_backend_spec(backend_spec)
    except ValueError as exc:
        return {
            "sensor_id": diagnostics["sensor_id"],
            "ok": False,
            "supported": False,
            "reason": str(exc),
            "settings": _build_sensor_settings_response(
                sensor_path,
                resolution_bits=resolution_bits,
                alarm_high_celsius=alarm_high_celsius,
                alarm_low_celsius=alarm_low_celsius,
            ),
        }

    try:
        proxy = pyownet_protocol.proxy(host=ow_host, port=ow_port, persistent=False)
        device_path = _resolve_owserver_device_path(proxy, diagnostics["sensor_id"])
        if alarm_high_celsius is not None:
            _write_owserver_text(proxy, f"{device_path}temphigh", str(float(alarm_high_celsius)))
        if alarm_low_celsius is not None:
            _write_owserver_text(proxy, f"{device_path}templow", str(float(alarm_low_celsius)))

        if resolution_bits is not None:
            if diagnostics["family_code"] != "28":
                return {
                    "sensor_id": diagnostics["sensor_id"],
                    "ok": False,
                    "supported": False,
                    "reason": "Resolution changes are only supported for DS18B20 (family code 28).",
                    "settings": _build_sensor_settings_response(
                        sensor_path,
                        resolution_bits=resolution_bits,
                        alarm_high_celsius=alarm_high_celsius,
                        alarm_low_celsius=alarm_low_celsius,
                    ),
                }
            resolution_path = None
            for candidate_name in ("resolution", "tempres"):
                candidate_path = f"{device_path}{candidate_name}"
                if proxy.present(candidate_path):
                    resolution_path = candidate_path
                    break
            if resolution_path is None:
                return {
                    "sensor_id": diagnostics["sensor_id"],
                    "ok": False,
                    "supported": False,
                    "reason": (
                        f"The owserver device {device_path} does not expose a writable resolution register "
                        "(tried resolution and tempres)."
                    ),
                    "settings": _build_sensor_settings_response(
                        sensor_path,
                        resolution_bits=resolution_bits,
                        alarm_high_celsius=alarm_high_celsius,
                        alarm_low_celsius=alarm_low_celsius,
                    ),
                }
            _write_owserver_text(proxy, resolution_path, str(resolution_bits))
    except (OSError, pyownet_protocol.Error, pyownet_protocol.ConnError, pyownet_protocol.ProtocolError, pyownet_protocol.OwnetError) as exc:
        return {
            "sensor_id": diagnostics["sensor_id"],
            "ok": False,
            "supported": False,
            "reason": f"Failed to write settings through owserver at {ow_host}:{ow_port}: {exc}",
            "settings": _build_sensor_settings_response(
                sensor_path,
                resolution_bits=resolution_bits,
                alarm_high_celsius=alarm_high_celsius,
                alarm_low_celsius=alarm_low_celsius,
            ),
        }

    return {
        "sensor_id": diagnostics["sensor_id"],
        "ok": True,
        "supported": True,
        "backend": f"owserver://{ow_host}:{ow_port}",
        "settings": _build_sensor_settings_response(
            sensor_path,
            resolution_bits=resolution_bits,
            alarm_high_celsius=alarm_high_celsius,
            alarm_low_celsius=alarm_low_celsius,
        ),
    }


class TemperatureHistory:
    """Maintain a rolling six-hour history of sensor samples."""

    def __init__(self, sensor_path: Path, sample_interval: float = DEFAULT_SAMPLE_INTERVAL) -> None:
        self.sensor_path = sensor_path
        self.sample_interval = sample_interval
        self._history: deque[dict[str, Any]] = deque()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._sampling_loop, daemon=True)
        self.last_error: str | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def _sampling_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now(timezone.utc)
            try:
                temp_c = read_temperature_celsius(self.sensor_path)
                sample = {
                    "timestamp_utc": now.isoformat(),
                    "unix_time": now.timestamp(),
                    "temperature_celsius": temp_c,
                    "temperature_fahrenheit": temp_c * 9.0 / 5.0 + 32.0,
                }
                with self._lock:
                    self._history.append(sample)
                    self._prune(now.timestamp())
                    self.last_error = None
            except (OSError, ValueError) as exc:
                self.last_error = str(exc)

            self._stop_event.wait(self.sample_interval)

    def _prune(self, now_unix_time: float) -> None:
        cutoff = now_unix_time - SIX_HOURS_SECONDS
        while self._history and self._history[0]["unix_time"] < cutoff:
            self._history.popleft()

    def get_history(self) -> list[dict[str, Any]]:
        with self._lock:
            history = list(self._history)
        now_unix_time = datetime.now(timezone.utc).timestamp()
        cutoff = now_unix_time - SIX_HOURS_SECONDS
        return [sample for sample in history if sample["unix_time"] >= cutoff]

    def get_latest(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._history:
                return None
            return dict(self._history[-1])


def create_web_app(sensor_paths: Path | list[Path] | None = None, sample_interval: float = DEFAULT_SAMPLE_INTERVAL):
    if Flask is None or jsonify is None or render_template_string is None:
        raise RuntimeError("Flask is not installed. Install it with: python3 -m pip install flask")

    if sensor_paths is None:
        sensor_paths = find_sensor_paths()
    elif isinstance(sensor_paths, (str, Path)):
        sensor_paths = [Path(sensor_paths)]
    else:
        sensor_paths = [Path(path) for path in sensor_paths]

    if not sensor_paths:
        raise FileNotFoundError(
            "No DS18B20 sensors were found under the default 1-Wire sysfs root. "
            "Ensure the device is connected and 1-Wire is enabled."
        )

    app = Flask(__name__)
    histories: dict[str, TemperatureHistory] = {}
    for sensor_path in sensor_paths:
        history = TemperatureHistory(sensor_path=sensor_path, sample_interval=sample_interval)
        history.start()
        atexit.register(history.stop)
        histories[sensor_path.name] = history

    page_template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DS18B20 Monitor</title>
  <style>
    html, body { height: 100%; }
    body { font-family: Arial, sans-serif; margin: 0; background: #f3f6fb; color: #1b2430; }
    .container { width: 100%; max-width: 100vw; min-height: 100vh; margin: 0 auto; padding: 16px 16px 24px; box-sizing: border-box; }
    h1 { margin: 0 0 8px; font-size: 1.5rem; }
    .sensor-grid { display: flex; flex-direction: column; gap: 20px; }
    .card { width: 100%; min-height: calc(100vh - 120px); background: #ffffff; border-radius: 12px; padding: 18px 22px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); box-sizing: border-box; display: flex; flex-direction: column; }
    .temp-value { font-size: clamp(2.2rem, 4vw, 4rem); font-weight: 700; margin: 10px 0 6px; }
    .meta { color: #5a6778; font-size: 0.95rem; }
    .plot-wrap { margin-top: auto; }
    svg { width: 100%; height: min(28vh, 260px); display: block; background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
    .axis-label { fill: #6a7686; font-size: 11px; }
    .line { fill: none; stroke: #0079d3; stroke-width: 2.25; }
    .grid { stroke: #d7dde6; stroke-width: 1; }
    .details { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px 14px; margin-top: 12px; }
    .detail-box { background: #f6f8fc; border: 1px solid #e1e7ef; border-radius: 8px; padding: 8px 10px; }
    .settings { margin-top: 16px; border-top: 1px solid #e6ebf3; padding-top: 14px; }
    .settings-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px 12px; align-items: end; }
    label { display: flex; flex-direction: column; gap: 6px; color: #445267; font-size: 0.82rem; }
    input, select, button { font: inherit; border-radius: 8px; border: 1px solid #d5dce7; padding: 8px 10px; }
    button { background: #0079d3; color: white; cursor: pointer; border: none; }
    button:hover { background: #0067b4; }
    .settings-status { min-height: 20px; margin-top: 10px; font-size: 0.8rem; color: #3f536d; }
    .settings-status.error { color: #b22222; }
    .settings-status.success { color: #0b7c3d; }
  </style>
</head>
<body>
  <div class="container">
    <h1>DS18B20 Sensor Dashboard</h1>
    <div class="meta">Detected sensors: {{ sensor_count }}</div>
    <div id="sensor-list" class="sensor-grid"></div>
  </div>
  <script>
    const sensorList = document.getElementById("sensor-list");
    const pendingConfigBySensor = new Map();
    const formatAlarmInput = (value, fallback) => {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        return parsed.toFixed(1);
      }
      return fallback;
    };

    function getPendingConfig(sensorId) {
      return pendingConfigBySensor.get(sensorId) || {};
    }

    function ensureCard(sensorId) {
      let card = sensorList.querySelector(`[data-sensor-id="${sensorId}"]`);
      if (card) {
        return card;
      }

      card = document.createElement("div");
      card.className = "card";
      card.dataset.sensorId = sensorId;
      card.innerHTML = `
        <div class="meta">Sensor ID: <span class="sensor-id">-</span></div>
        <div class="temp-value"><span class="temp-c">--.--</span> °C</div>
        <div class="meta"><span class="temp-f">--.--</span> °F · Updated: <span class="updated">-</span></div>
        <div class="meta">CRC OK: <span class="crc-ok">-</span> · Resolution: <span class="resolution">-</span> · Alarm: <span class="alarm-state">-</span></div>
        <div class="details">
          <div class="detail-box"><strong>Family:</strong> <span class="family">-</span></div>
          <div class="detail-box"><strong>Alarm High:</strong> <span class="alarm-high">-</span> °C</div>
          <div class="detail-box"><strong>Alarm Low:</strong> <span class="alarm-low">-</span> °C</div>
          <div class="detail-box"><strong>Raw Temp:</strong> <span class="raw-temp">-</span> °C</div>
          <div class="detail-box"><strong>Config:</strong> <span class="config">-</span></div>
          <div class="detail-box"><strong>CRC:</strong> <span class="crc-full">-</span></div>
        </div>
        <div class="settings">
          <form class="settings-form">
            <label>Resolution
              <select class="set-resolution">
                <option value="9">9-bit</option>
                <option value="10">10-bit</option>
                <option value="11">11-bit</option>
                <option value="12">12-bit</option>
              </select>
            </label>
            <label>Alarm high (°C)
              <input class="set-alarm-high" type="number" step="0.5" min="-128" max="127" value="75">
            </label>
            <label>Alarm low (°C)
              <input class="set-alarm-low" type="number" step="0.5" min="-128" max="127" value="-10">
            </label>
            <button type="submit" class="apply-settings">Apply settings</button>
          </form>
          <div class="settings-status"></div>
        </div>
        <div class="plot-wrap">
          <svg class="sensor-plot" viewBox="0 0 920 180" preserveAspectRatio="none">
            <g class="grid"></g>
            <polyline class="line temp-line" points=""></polyline>
            <text class="axis-label" x="8" y="14">°C</text>
            <text class="axis-label" x="760" y="170">6h</text>
          </svg>
        </div>
      `;
      const settingsForm = card.querySelector(".settings-form");
      const resolutionInput = card.querySelector(".set-resolution");
      const alarmHighInput = card.querySelector(".set-alarm-high");
      const alarmLowInput = card.querySelector(".set-alarm-low");

      const updatePendingFromInputs = () => {
        const previous = getPendingConfig(sensorId);
        pendingConfigBySensor.set(sensorId, {
          ...previous,
          resolution_bits_input: resolutionInput.value,
          alarm_high_input: alarmHighInput.value,
          alarm_low_input: alarmLowInput.value,
          is_dirty: true,
        });
      };

      [resolutionInput, alarmHighInput, alarmLowInput].forEach((input) => {
        input.addEventListener("input", updatePendingFromInputs);
        input.addEventListener("change", updatePendingFromInputs);
        input.addEventListener("keydown", (event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            settingsForm.requestSubmit();
          }
        });
      });

      settingsForm.addEventListener("submit", (event) => {
        event.preventDefault();
        submitSensorSettings(card);
      });

      sensorList.appendChild(card);
      return card;
    }

    async function submitSensorSettings(card) {
      const sensorId = card.dataset.sensorId;
      const resolutionInput = card.querySelector(".set-resolution");
      const alarmHighInput = card.querySelector(".set-alarm-high");
      const alarmLowInput = card.querySelector(".set-alarm-low");
      const status = card.querySelector(".settings-status");

      const resolutionBitsValue = Number(resolutionInput.value);
      const alarmHighValue = Number(alarmHighInput.value);
      const alarmLowValue = Number(alarmLowInput.value);
      if (!Number.isFinite(resolutionBitsValue) || !Number.isFinite(alarmHighValue) || !Number.isFinite(alarmLowValue)) {
        status.className = "settings-status error";
        status.textContent = "Please enter valid numeric values.";
        return;
      }

      pendingConfigBySensor.set(sensorId, {
        resolution_bits_input: resolutionInput.value,
        alarm_high_input: alarmHighInput.value,
        alarm_low_input: alarmLowInput.value,
        is_dirty: false,
        is_applying: true,
      });

      try {
        status.className = "settings-status";
        status.textContent = "Applying...";
        const response = await fetch("/api/configure", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sensor_id: sensorId,
            resolution_bits: resolutionBitsValue,
            alarm_high_celsius: alarmHighValue,
            alarm_low_celsius: alarmLowValue,
          }),
        });
        const payload = await response.json();
        if (!payload.ok) {
          throw new Error(payload.error || payload.reason || "Unable to apply settings.");
        }

        status.classList.add("success");
        status.textContent = payload.supported ? "Settings submitted successfully." : payload.reason;
        const committed = payload.settings || {};
        pendingConfigBySensor.set(sensorId, {
          resolution_bits_input: String(committed.resolution_bits ?? resolutionBitsValue),
          alarm_high_input: formatAlarmInput(committed.alarm_high_celsius, String(alarmHighValue)),
          alarm_low_input: formatAlarmInput(committed.alarm_low_celsius, String(alarmLowValue)),
          is_dirty: false,
          is_applying: false,
        });
        await refreshCurrent();
      } catch (error) {
        const previous = getPendingConfig(sensorId);
        pendingConfigBySensor.set(sensorId, {
          ...previous,
          is_dirty: true,
          is_applying: false,
        });
        status.classList.add("error");
        status.textContent = error.message;
      }
    }

    function drawGrid(gridEl, yMin, yMax) {
      gridEl.innerHTML = "";
      const top = 18;
      const bottom = 155;
      const left = 52;
      const right = 900;
      const rows = 5;
      for (let i = 0; i <= rows; i += 1) {
        const y = top + (bottom - top) * (i / rows);
        const value = yMax - (yMax - yMin) * (i / rows);
        const lineNode = document.createElementNS("http://www.w3.org/2000/svg", "line");
        lineNode.setAttribute("x1", left);
        lineNode.setAttribute("x2", right);
        lineNode.setAttribute("y1", y);
        lineNode.setAttribute("y2", y);
        lineNode.setAttribute("class", "grid");
        gridEl.appendChild(lineNode);

        const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
        label.setAttribute("x", 8);
        label.setAttribute("y", y + 4);
        label.setAttribute("class", "axis-label");
        label.textContent = value.toFixed(1);
        gridEl.appendChild(label);
      }
    }

    function renderHistoryForCard(card, samples) {
      const line = card.querySelector(".temp-line");
      const grid = card.querySelector(".grid");
      if (!line || !grid) {
        return;
      }
      if (!samples || !samples.length) {
        line.setAttribute("points", "");
        return;
      }
      const left = 52;
      const right = 900;
      const top = 18;
      const bottom = 155;
      const values = samples.map((s) => s.temperature_celsius);
      let yMin = Math.min(...values);
      let yMax = Math.max(...values);
      if (Math.abs(yMax - yMin) < 0.5) {
        yMin -= 0.25;
        yMax += 0.25;
      }
      const tMin = samples[0].unix_time;
      const tMax = samples[samples.length - 1].unix_time;
      const tSpan = Math.max(1, tMax - tMin);
      drawGrid(grid, yMin, yMax);
      const points = samples.map((sample) => {
        const x = left + ((sample.unix_time - tMin) / tSpan) * (right - left);
        const y = top + ((yMax - sample.temperature_celsius) / (yMax - yMin)) * (bottom - top);
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      });
      line.setAttribute("points", points.join(" "));
    }

    function updateCurrentSensors(sensors) {
      const sensorMap = new Map((sensors || []).map((sensor) => [sensor.sensor_id, sensor]));
      const cards = Array.from(sensorList.querySelectorAll(".card"));
      cards.forEach((card) => {
        if (!sensorMap.has(card.dataset.sensorId)) {
          pendingConfigBySensor.delete(card.dataset.sensorId);
          card.remove();
        }
      });

      (sensors || []).forEach((sensor) => {
        const card = ensureCard(sensor.sensor_id);
        const diagnostics = sensor.diagnostics || {};
        const pendingConfig = getPendingConfig(sensor.sensor_id);
        const resolutionBits = pendingConfig.resolution_bits_input ?? String(diagnostics.resolution_bits ?? 12);
        const alarmHigh = pendingConfig.alarm_high_input ?? formatAlarmInput(diagnostics.alarm_high_celsius, "75.0");
        const alarmLow = pendingConfig.alarm_low_input ?? formatAlarmInput(diagnostics.alarm_low_celsius, "-10.0");

        card.querySelector(".sensor-id").textContent = sensor.sensor_id;
        card.querySelector(".temp-c").textContent = Number(sensor.temperature_celsius).toFixed(3);
        card.querySelector(".temp-f").textContent = Number(sensor.temperature_fahrenheit).toFixed(3);
        card.querySelector(".updated").textContent = new Date(sensor.timestamp_utc).toLocaleString();
        card.querySelector(".crc-ok").textContent = diagnostics.crc_ok ? "YES" : "NO";
        card.querySelector(".resolution").textContent = diagnostics.resolution_bits ? `${diagnostics.resolution_bits}-bit` : "n/a";
        card.querySelector(".alarm-state").textContent = diagnostics.alarm_state || "-";
        card.querySelector(".family").textContent = diagnostics.family_code || "-";
        card.querySelector(".alarm-high").textContent = diagnostics.alarm_high_celsius != null ? Number(diagnostics.alarm_high_celsius).toFixed(1) : "-";
        card.querySelector(".alarm-low").textContent = diagnostics.alarm_low_celsius != null ? Number(diagnostics.alarm_low_celsius).toFixed(1) : "-";
        card.querySelector(".raw-temp").textContent = diagnostics.raw_temperature_celsius != null ? Number(diagnostics.raw_temperature_celsius).toFixed(3) : "-";
        card.querySelector(".config").textContent = diagnostics.config_register_hex || "-";
        card.querySelector(".crc-full").textContent = diagnostics.crc_match != null ? `${diagnostics.crc_reported_hex}/${diagnostics.crc_calculated_hex} (${diagnostics.crc_match ? "match" : "mismatch"})` : "-";
        const resolutionInput = card.querySelector(".set-resolution");
        const alarmHighInput = card.querySelector(".set-alarm-high");
        const alarmLowInput = card.querySelector(".set-alarm-low");
        if (document.activeElement !== resolutionInput) {
          resolutionInput.value = String(resolutionBits);
        }
        if (document.activeElement !== alarmHighInput) {
          alarmHighInput.value = alarmHigh;
        }
        if (document.activeElement !== alarmLowInput) {
          alarmLowInput.value = alarmLow;
        }
      });
    }

    function updateHistorySensors(sensorHistory) {
      const historyMap = new Map((sensorHistory || []).map((entry) => [entry.sensor_id, entry.samples]));
      sensorList.querySelectorAll(".card").forEach((card) => {
        const samples = historyMap.get(card.dataset.sensorId) || [];
        renderHistoryForCard(card, samples);
      });
    }

    async function refreshCurrent() {
      const response = await fetch("/api/current");
      const payload = await response.json();
      if (!payload.ok) {
        sensorList.innerHTML = `<div class="card"><div class="meta">Error: ${payload.error}</div></div>`;
        return;
      }
      updateCurrentSensors(payload.sensors);
    }

    async function refreshHistory() {
      const response = await fetch("/api/history");
      const payload = await response.json();
      if (!payload.ok) {
        return;
      }
      updateHistorySensors(payload.sensors);
    }

    async function refreshAll() {
      try {
        await Promise.all([refreshCurrent(), refreshHistory()]);
      } catch (error) {
        sensorList.innerHTML = `<div class="card"><div class="meta">Error: ${String(error)}</div></div>`;
      }
    }

    refreshAll();
    setInterval(refreshCurrent, 5000);
    setInterval(refreshHistory, 15000);
  </script>
</body>
</html>"""

    @app.get("/")
    def index():
        return render_template_string(page_template, sample_interval=sample_interval, sensor_count=len(sensor_paths))

    @app.get("/api/current")
    def api_current():
        sensors: list[dict[str, Any]] = []
        for sensor_path in sensor_paths:
            try:
                diagnostics = read_diagnostics(sensor_path)
            except (OSError, ValueError) as exc:
                return jsonify({"ok": False, "error": str(exc), "sensor_count": len(sensor_paths)}), 500
            sensors.append(
                {
                    "sensor_id": diagnostics["sensor_id"],
                    "timestamp_utc": diagnostics["timestamp_utc"],
                    "temperature_celsius": diagnostics["temperature_celsius"],
                    "temperature_fahrenheit": diagnostics["temperature_fahrenheit"],
                    "diagnostics": {
                        "crc_ok": diagnostics["crc_ok"],
                        "crc_match": diagnostics["crc_match"],
                        "crc_reported_hex": diagnostics["crc_reported_hex"],
                        "crc_calculated_hex": diagnostics["crc_calculated_hex"],
                        "resolution_bits": diagnostics["resolution_bits"],
                        "family_code": diagnostics["family_code"],
                        "alarm_high_celsius": diagnostics["alarm_high_celsius"],
                        "alarm_low_celsius": diagnostics["alarm_low_celsius"],
                        "alarm_triggered": diagnostics["alarm_triggered"],
                        "alarm_state": diagnostics["alarm_state"],
                        "raw_temperature_celsius": diagnostics["raw_temperature_celsius"],
                        "config_register_hex": diagnostics["config_register_hex"],
                    },
                }
            )

        return jsonify({"ok": True, "sensor_count": len(sensors), "sensors": sensors})

    @app.post("/api/configure")
    def api_configure():
        if request is None:
            return jsonify({"ok": False, "error": "Flask request handling is unavailable."}), 500

        payload = request.get_json(silent=True) or {}
        sensor_id = payload.get("sensor_id")
        if not sensor_id:
            return jsonify({"ok": False, "error": "Missing sensor_id."}), 400

        sensor_path = next((path for path in sensor_paths if path.name == sensor_id), None)
        if sensor_path is None:
            return jsonify({"ok": False, "error": f"Sensor {sensor_id!r} was not found."}), 404

        try:
            resolution_bits = payload.get("resolution_bits")
            if resolution_bits is not None:
                resolution_bits = int(resolution_bits)

            alarm_high_celsius = payload.get("alarm_high_celsius")
            if alarm_high_celsius is not None:
                alarm_high_celsius = float(alarm_high_celsius)

            alarm_low_celsius = payload.get("alarm_low_celsius")
            if alarm_low_celsius is not None:
                alarm_low_celsius = float(alarm_low_celsius)

            result = configure_sensor(
                sensor_path,
                resolution_bits=resolution_bits,
                alarm_high_celsius=alarm_high_celsius,
                alarm_low_celsius=alarm_low_celsius,
            )
            if result.get("ok"):
                return jsonify({"ok": True, "supported": result.get("supported", True), "sensor_id": sensor_id, "settings": result.get("settings", {})})
            return jsonify({"ok": False, "supported": False, "sensor_id": sensor_id, "reason": result.get("reason", "Configuration is not supported on this backend."), "settings": result.get("settings", {})}), 409
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.get("/api/diagnostics")
    def api_diagnostics():
        diagnostics: list[dict[str, Any]] = []
        for sensor_path in sensor_paths:
            try:
                diagnostics.append(read_diagnostics(sensor_path))
            except (OSError, ValueError) as exc:
                return jsonify({"ok": False, "error": str(exc), "sensor_count": len(sensor_paths)}), 500
        return jsonify({"ok": True, "sensor_count": len(diagnostics), "sensors": diagnostics})

    @app.get("/api/history")
    def api_history():
        history_payload = []
        for sensor_path in sensor_paths:
            history = histories[sensor_path.name]
            history_payload.append({
                "sensor_id": sensor_path.name,
                "samples": history.get_history(),
                "last_error": history.last_error,
            })
        return jsonify(
            {
                "ok": True,
                "window_seconds": SIX_HOURS_SECONDS,
                "sample_interval_seconds": sample_interval,
                "sensor_count": len(history_payload),
                "sensors": history_payload,
            }
        )

    return app


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read temperature from a DS18B20 1-Wire sensor.")
    parser.add_argument(
        "--sensor-id",
        default=None,
        help="Exact sensor ID to read, such as 28-0123456789ab. Defaults to the first device found.",
    )
    parser.add_argument(
        "--w1-root",
        type=Path,
        default=DEFAULT_W1_ROOT,
        help=f"Override the 1-Wire sysfs root (default: {DEFAULT_W1_ROOT})",
    )
    parser.add_argument(
        "--fahrenheit",
        action="store_true",
        help="Convert the result to Fahrenheit before printing it.",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print parsed sensor diagnostics (JSON) and exit.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Run Flask dashboard with a live card and six-hour plot.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host address for --web mode (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port for --web mode (default: 5000).",
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=DEFAULT_SAMPLE_INTERVAL,
        help=f"Sampling interval in seconds for --web history collection (default: {DEFAULT_SAMPLE_INTERVAL}).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.sample_interval <= 0:
        print("Error: --sample-interval must be greater than zero.", file=sys.stderr)
        return 2

    try:
        sensor_paths = [find_sensor_path(sensor_id=args.sensor_id, root=args.w1_root)]
        if args.sensor_id is None:
            sensor_paths = find_sensor_paths(root=args.w1_root)
            if not sensor_paths:
                raise FileNotFoundError(
                    f"No DS18B20 sensor found under {args.w1_root}. "
                    "Ensure 1-Wire is enabled and the sensor is connected to the default Pi data pin."
                )
    except (FileNotFoundError, OSError, ValueError) as exc:  # pragma: no cover - CLI error handling
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.web:
        try:
            app = create_web_app(sensor_paths=sensor_paths, sample_interval=args.sample_interval)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        app.run(host=args.host, port=args.port)
        return 0

    if args.diagnostics:
        diagnostics_list: list[dict[str, Any]] = []
        for sensor_path in sensor_paths:
            try:
                diagnostics_list.append(read_diagnostics(sensor_path))
            except (OSError, ValueError) as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1

        if len(diagnostics_list) == 1:
            print(json.dumps(diagnostics_list[0], indent=2, sort_keys=True))
        else:
            print(json.dumps({"sensor_count": len(diagnostics_list), "sensors": diagnostics_list}, indent=2, sort_keys=True))
        return 0

    for sensor_path in sensor_paths:
        try:
            temperature_c = read_temperature_celsius(sensor_path)
        except (OSError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        temperature = temperature_c * 9.0 / 5.0 + 32.0 if args.fahrenheit else temperature_c
        unit = "F" if args.fahrenheit else "C"
        if len(sensor_paths) == 1:
            print(f"{temperature:.3f}°{unit}")
        else:
            print(f"{sensor_path.name}: {temperature:.3f}°{unit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
