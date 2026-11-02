#!/usr/bin/env python3
#pylint: disable=C0301
"""Read BME280 environmental values over I2C and serve a small Flask dashboard."""

from __future__ import annotations

import json
import hashlib
import importlib
import threading
import time
from collections import deque
from typing import Any

try:
    flask = importlib.import_module("flask")
    Flask = flask.Flask
    render_template_string = flask.render_template_string
    jsonify = flask.jsonify
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "Install Flask in the venv: pip install flask"
    ) from exc

try:
    smbus2 = importlib.import_module("smbus2")
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "Install smbus2 in the venv: pip install smbus2"
    ) from exc


class BME280:
    """BME280 sensor driver using smbus2 I2C communication."""
    EXPECTED_CHIP_ID = 0x60
    REG_CTRL_HUM = 0xF2
    REG_STATUS = 0xF3
    REG_CTRL_MEAS = 0xF4
    REG_CONFIG = 0xF5

    def __init__(self, bus: int = 1, address: int = 0x76, *, timeout: float = 0.05) -> None:
        self.bus = bus
        self.address = address
        self.timeout = timeout
        self.i2c = smbus2.SMBus(bus)
        self._configure_sensor()
        self.calibration = self._read_calibration_data()
        self.t_fine = 0

    def _write_register_byte(self, register: int, value: int) -> None:
        self.i2c.write_byte_data(self.address, register, value & 0xFF)

    def _configure_sensor(self) -> None:
        """Configure BME280 in normal mode with x1 oversampling."""
        # Per datasheet: write ctrl_hum first, then ctrl_meas.
        self._write_register_byte(self.REG_CTRL_HUM, 0x01)   # humidity oversampling x1
        self._write_register_byte(self.REG_CONFIG, 0x00)     # filter off, default standby
        self._write_register_byte(self.REG_CTRL_MEAS, 0x27)  # temp x1, press x1, mode normal

    def _read_register_byte(self, register: int) -> int:
        return self.i2c.read_byte_data(self.address, register)

    def _read_register_bytes(self, start_register: int, length: int) -> bytes:
        return bytes(self.i2c.read_i2c_block_data(self.address, start_register, length))

    @staticmethod
    def _u16_le(msb_lsb: bytes) -> int:
        return (msb_lsb[1] << 8) | msb_lsb[0]

    @classmethod
    def _s16_le(cls, msb_lsb: bytes) -> int:
        return cls._sign_extend(cls._u16_le(msb_lsb), bits=16)

    @staticmethod
    def _sign_extend(value: int, bits: int) -> int:
        sign_bit = 1 << (bits - 1)
        return (value ^ sign_bit) - sign_bit

    def _read_calibration_data(self):
        temp_press = self._read_register_bytes(0x88, 24)
        humidity = self._read_register_bytes(0xE1, 7)
        h1 = self._read_register_byte(0xA1)

        h4_raw = (humidity[3] << 4) | (humidity[4] & 0x0F)
        h5_raw = (humidity[5] << 4) | (humidity[4] >> 4)

        return {
            "temperature_calibration": {
                "T1": self._u16_le(temp_press[0:2]),
                "T2": self._s16_le(temp_press[2:4]),
                "T3": self._s16_le(temp_press[4:6]),
            },
            "pressure_calibration": {
                "P1": self._u16_le(temp_press[6:8]),
                "P2": self._s16_le(temp_press[8:10]),
                "P3": self._s16_le(temp_press[10:12]),
                "P4": self._s16_le(temp_press[12:14]),
                "P5": self._s16_le(temp_press[14:16]),
                "P6": self._s16_le(temp_press[16:18]),
                "P7": self._s16_le(temp_press[18:20]),
                "P8": self._s16_le(temp_press[20:22]),
                "P9": self._s16_le(temp_press[22:24]),
            },
            "humidity_calibration": {
                "H1": h1,
                "H2": self._s16_le(humidity[0:2]),
                "H3": humidity[2],
                "H4": self._sign_extend(h4_raw, bits=12),
                "H5": self._sign_extend(h5_raw, bits=12),
                "H6": self._sign_extend(humidity[6], bits=8),
            },
        }

    def _compensate_temperature(self, adc_temp: int) -> int:
        """Compensate temperature value using calibration data.
        Returns t_fine which is temperature in 0.005°C units."""
        t1 = self.calibration["temperature_calibration"]["T1"]
        t2 = self.calibration["temperature_calibration"]["T2"]
        t3 = self.calibration["temperature_calibration"]["T3"]

        var1 = (adc_temp >> 3) - (t1 << 1)
        var2 = (var1 * t2) >> 11
        var3 = ((var1 >> 1) * (var1 >> 1)) >> 12
        var3 = ((var3) * (t3)) >> 14
        self.t_fine = var2 + var3
        return self.t_fine

    def _get_temperature_celsius(self) -> float:
        """Convert t_fine to temperature in Celsius."""
        return self.t_fine / 5120.0

    def _compensate_pressure(self, adc_pres: int) -> float:
        """Compensate pressure value using calibration data.
        Uses floating-point algorithm for accuracy."""
        p1 = self.calibration["pressure_calibration"]["P1"]
        p2 = self.calibration["pressure_calibration"]["P2"]
        p3 = self.calibration["pressure_calibration"]["P3"]
        p4 = self.calibration["pressure_calibration"]["P4"]
        p5 = self.calibration["pressure_calibration"]["P5"]
        p6 = self.calibration["pressure_calibration"]["P6"]
        p7 = self.calibration["pressure_calibration"]["P7"]
        p8 = self.calibration["pressure_calibration"]["P8"]
        p9 = self.calibration["pressure_calibration"]["P9"]

        var1 = (self.t_fine / 2.0) - 64000.0
        var2 = var1 * var1 * p6 / 32768.0
        var2 = var2 + var1 * p5 * 2.0
        var2 = (var2 / 4.0) + (p4 * 65536.0)
        var1 = (p3 * var1 * var1 / 524288.0 + p2 * var1) / 524288.0
        var1 = (1.0 + var1 / 32768.0) * p1
        
        if var1 == 0:
            return 0
        
        pressure = 1048576.0 - adc_pres
        pressure = ((pressure - var2 / 4096.0) * 6250.0) / var1
        var1 = p9 * pressure * pressure / 2147483648.0
        var2 = pressure * p8 / 32768.0
        pressure = pressure + (var1 + var2 + p7) / 16.0
        
        return pressure / 100.0

    def _compensate_humidity(self, adc_hum: int) -> float:
        """Compensate humidity value using calibration data."""
        h1 = self.calibration["humidity_calibration"]["H1"]
        h2 = self.calibration["humidity_calibration"]["H2"]
        h3 = self.calibration["humidity_calibration"]["H3"]
        h4 = self.calibration["humidity_calibration"]["H4"]
        h5 = self.calibration["humidity_calibration"]["H5"]
        h6 = self.calibration["humidity_calibration"]["H6"]

        var_h = self.t_fine - 76800
        var_h = (adc_hum - (h4 * 64 + h5 / 16384.0 * var_h)) * (
            h2 / 65536.0 * (1.0 + h6 / 67108864.0 * var_h * (1.0 + h3 / 67108864.0 * var_h))
        )
        var_h = var_h * (1.0 - h1 * var_h / 524288.0)
        return max(0.0, min(100.0, var_h))

    def read(self):
        """Read the latest temperature, pressure, and humidity values."""
        time.sleep(self.timeout)

        ctrl_meas = self._read_register_byte(self.REG_CTRL_MEAS)
        if (ctrl_meas & 0x03) == 0:
            self._configure_sensor()
            time.sleep(self.timeout)

        data = self._read_register_bytes(0xF7, 8)
        adc_pres = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        adc_temp = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)
        adc_hum = (data[6] << 8) | data[7]

        t_fine = self._compensate_temperature(adc_temp)
        temp_c = self._get_temperature_celsius()
        pres_hpa = self._compensate_pressure(adc_pres)
        hum_pct = self._compensate_humidity(adc_hum)

        return {
            "temperature_c": round(temp_c, 2),
            "pressure_hpa": round(pres_hpa, 2),
            "humidity_pct": round(hum_pct, 2),
        }

    @staticmethod
    def _format_unique_id(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, int):
            return f"0x{value:X}"
        if isinstance(value, (bytes, bytearray)):
            return value.hex()
        if isinstance(value, (tuple, list)) and all(isinstance(item, int) and 0 <= item <= 0xFF for item in value):
            return bytes(value).hex()
        return str(value)

    def _detect_unique_id(self) -> tuple[str | None, str | None]:
        try:
            chip_id = self._read_register_byte(0xD0)
            return self._format_unique_id(chip_id), "chip_id"
        except Exception:
            return None, None

    def read_info(self):
        """Return the chip and calibration information stored in the BME280 registers."""
        chip_id = self._read_register_byte(0xD0)
        status = self._read_register_byte(0xF3)
        ctrl_hum = self._read_register_byte(0xF2)
        ctrl_meas = self._read_register_byte(0xF4)
        config = self._read_register_byte(0xF5)
        calibration = self.calibration
        unique_id, unique_id_source = self._detect_unique_id()

        return {
            "chip_id": chip_id,
            "chip_id_matches_expected": chip_id == self.EXPECTED_CHIP_ID,
            "status": status,
            "status_flags": {
                "measuring": bool(status & 0b0000_1000),
                "im_update": bool(status & 0b0000_0001),
            },
            "ctrl_hum": ctrl_hum,
            "ctrl_meas": ctrl_meas,
            "config": config,
            "i2c_bus": self.bus,
            "i2c_address": self.address,
            "unique_id": unique_id,
            "unique_id_source": unique_id_source,
            "temperature_calibration": calibration["temperature_calibration"],
            "pressure_calibration": calibration["pressure_calibration"],
            "humidity_calibration": calibration["humidity_calibration"],
        }

    def read_calibration_table(self):
        """Return the full BME280 calibration table in a flat dictionary."""
        info = self.read_info()
        table = {}
        table.update({f"T{i}": v for i, v in enumerate(
            [
                info["temperature_calibration"]["T1"],
                info["temperature_calibration"]["T2"],
                info["temperature_calibration"]["T3"],
            ],
            start=1,
        )})
        table.update({f"P{i}": v for i, v in enumerate(
            [
                info["pressure_calibration"]["P1"],
                info["pressure_calibration"]["P2"],
                info["pressure_calibration"]["P3"],
                info["pressure_calibration"]["P4"],
                info["pressure_calibration"]["P5"],
                info["pressure_calibration"]["P6"],
                info["pressure_calibration"]["P7"],
                info["pressure_calibration"]["P8"],
                info["pressure_calibration"]["P9"],
            ],
            start=1,
        )})
        table.update({f"H{i}": v for i, v in enumerate(
            [
                info["humidity_calibration"]["H1"],
                info["humidity_calibration"]["H2"],
                info["humidity_calibration"]["H3"],
                info["humidity_calibration"]["H4"],
                info["humidity_calibration"]["H5"],
                info["humidity_calibration"]["H6"],
            ],
            start=1,
        )})
        table["chip_id"] = info["chip_id"]
        table["chip_id_matches_expected"] = info["chip_id_matches_expected"]
        table["status"] = info["status"]
        table["ctrl_hum"] = info["ctrl_hum"]
        table["ctrl_meas"] = info["ctrl_meas"]
        table["config"] = info["config"]
        table["i2c_bus"] = info["i2c_bus"]
        table["i2c_address"] = info["i2c_address"]
        table["unique_id"] = info["unique_id"]
        table["unique_id_source"] = info["unique_id_source"]
        table["status_flags"] = info["status_flags"]
        return table

    def close(self) -> None:
        """Close the I2C connection."""
        if self.i2c:
            self.i2c.close()

    def __enter__(self) -> "BME280":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


sensor = BME280(bus=1, address=0x76)
readings = deque(maxlen=24 * 60 * 60)
lock = threading.Lock()
sensor_runtime_diagnostics = {
    "successful_reads": 0,
    "failed_reads": 0,
    "last_read_duration_ms": None,
    "last_success_timestamp": None,
    "last_error_timestamp": None,
    "last_error": None,
}


def _format_epoch(value):
    if value is None:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def _calibration_fingerprint(info):
    calibration_keys = [
        "T1", "T2", "T3",
        "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9",
        "H1", "H2", "H3", "H4", "H5", "H6",
    ]
    fingerprint_payload = {key: info[key] for key in calibration_keys}
    encoded = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_diagnostics_payload(history, info, runtime):
    calibration_fingerprint = _calibration_fingerprint(info)
    return {
        "response": {
            "successful_reads": runtime["successful_reads"],
            "failed_reads": runtime["failed_reads"],
            "last_read_duration_ms": runtime["last_read_duration_ms"],
            "last_success_at": _format_epoch(runtime["last_success_timestamp"]),
            "last_error_at": _format_epoch(runtime["last_error_timestamp"]),
            "last_error": runtime["last_error"],
            "buffered_samples": len(history),
        },
        "sensor": {
            "chip_id": f"0x{info['chip_id']:02X}",
            "chip_id_matches_expected": info["chip_id"] == BME280.EXPECTED_CHIP_ID,
            "i2c_bus": info["i2c_bus"],
            "i2c_address": f"0x{info['i2c_address']:02X}",
            "status": f"0x{info['status']:02X}",
            "ctrl_hum": f"0x{info['ctrl_hum']:02X}",
            "ctrl_meas": f"0x{info['ctrl_meas']:02X}",
            "config": f"0x{info['config']:02X}",
            "unique_id": info["unique_id"],
            "unique_id_source": info["unique_id_source"],
            "calibration_fingerprint": calibration_fingerprint,
        },
    }


def update_readings():
    """Continuously read sensor data and append it to the shared readings buffer."""
    while True:
        start = time.perf_counter()
        try:
            reading = sensor.read()
            now = time.time()
            duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
            with lock:
                readings.append({"timestamp": now, **reading})
                sensor_runtime_diagnostics["successful_reads"] += 1
                sensor_runtime_diagnostics["last_read_duration_ms"] = duration_ms
                sensor_runtime_diagnostics["last_success_timestamp"] = now
                sensor_runtime_diagnostics["last_error"] = None
        except (RuntimeError, OSError, ValueError) as exc:
            now = time.time()
            with lock:
                sensor_runtime_diagnostics["failed_reads"] += 1
                sensor_runtime_diagnostics["last_error_timestamp"] = now
                sensor_runtime_diagnostics["last_error"] = str(exc)
            print(f"BME280 read error: {exc}", flush=True)
        time.sleep(1)


def _chart_value_bounds(samples, key, min_override=None, max_override=None):
    values = [sample[key] for sample in samples]
    min_value = min_override if min_override is not None else min(values)
    max_value = max_override if max_override is not None else max(values)
    if max_value == min_value:
        max_value = min_value + 1.0
    return min_value, max_value


def _chart_path(samples, key, min_value, max_value, pads):
    width = 900
    height = 220
    pad_left, pad_right, pad_top, pad_bottom = pads
    chart_width = width - pad_left - pad_right
    chart_height = height - pad_top - pad_bottom
    points = []
    for sample_index, sample in enumerate(samples):
        x = pad_left + (sample_index / max(len(samples) - 1, 1)) * chart_width
        y = height - pad_bottom - ((sample[key] - min_value) / (max_value - min_value)) * chart_height
        points.append(f"{x:.2f},{y:.2f}")

    if len(points) > 1:
        return "M " + " L ".join(points), width, height, chart_width, chart_height, pad_left, pad_right, pad_top, pad_bottom

    path = f"M {pad_left} {height - pad_bottom} L {pad_left} {height - pad_bottom}"
    return path, width, height, chart_width, chart_height, pad_left, pad_right, pad_top, pad_bottom


def _chart_grid(width, chart_height, pads):
    pad_left, pad_right, pad_top, _pad_bottom = pads
    return [
        f'<line x1="{pad_left}" y1="{pad_top + (chart_height / 4) * i}" x2="{width - pad_right}" y2="{pad_top + (chart_height / 4) * i}" stroke="#2d3748" />'
        for i in range(5)
    ]


def _chart_ticks(samples, pads, width, height):
    pad_left, _pad_right, pad_top, pad_bottom = pads
    start_time = samples[0]["timestamp"]
    end_time = samples[-1]["timestamp"]
    chart_width = width - pad_left - _pad_right
    tick_markup = []
    for pos in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = pad_left + pos * chart_width
        ts = start_time + (end_time - start_time) * pos
        label_text = time.strftime("%H:%M", time.localtime(ts))
        tick_markup.append(f'<line x1="{x}" y1="{pad_top}" x2="{x}" y2="{height - pad_bottom}" stroke="#2d3748" stroke-dasharray="4 4" />')
        tick_markup.append(f'<text x="{x}" y="{height - 8}" text-anchor="middle" fill="#94a3b8" font-size="11">{label_text}</text>')
    return tick_markup


def _chart_trend(samples, key, unit):
    last_value = samples[-1][key]
    first_value = samples[0][key]
    delta = last_value - first_value
    trend_text = "rising" if delta > 0 else "falling" if delta < 0 else "steady"
    return trend_text, f"{delta:+.2f}{unit}"


def build_chart_svg(samples, chart):
    """Render an SVG chart for a sensor sample series."""
    if not samples:
        return ""

    key = chart["key"]
    label = chart["label"]
    color = chart["color"]
    unit = chart["unit"]
    last_value = samples[-1][key]
    min_value, max_value = _chart_value_bounds(samples, key, chart.get("min_override"), chart.get("max_override"))
    path, width, height, chart_width, chart_height, pad_left, pad_right, pad_top, pad_bottom = _chart_path(
        samples,
        key,
        min_value,
        max_value,
        (40, 20, 10, 30),
    )
    tick_markup = _chart_ticks(samples, (pad_left, pad_right, pad_top, pad_bottom), width, height)
    trend_text, delta_text = _chart_trend(samples, key, unit)

    return f"""
    <div class="chart-box">
      <div class="chart-header">
        <span>{label}</span>
        <span>{trend_text} {delta_text}</span>
      </div>
      <svg viewBox="0 0 {width} {height}" width="100%" height="220" aria-label="{label} chart">
                {''.join(_chart_grid(width, chart_height, (pad_left, pad_right, pad_top, pad_bottom)))}
        {''.join(tick_markup)}
        <path d="{path}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="{pad_left + chart_width}" cy="{height - pad_bottom - ((last_value - min_value) / (max_value - min_value)) * chart_height}" r="4" fill="{color}" />
      </svg>
    </div>
    """


def trend_summary(samples):
    """Summarize the overall trend for each metric in a sample list."""
    if len(samples) < 2:
        return {
            "temperature": "stable",
            "pressure": "stable",
            "humidity": "stable",
        }

    summary = {}
    for key, label in (("temperature_c", "temperature"), ("pressure_hpa", "pressure"), ("humidity_pct", "humidity")):
        first = samples[0][key]
        last = samples[-1][key]
        delta = last - first
        if delta > 0.5:
            direction = "rising"
        elif delta < -0.5:
            direction = "falling"
        else:
            direction = "stable"
        summary[label] = f"{direction} ({delta:+.2f})"
    return summary


def _pressure_outlook(samples):
    """Return a short weather outlook based on recent mean pressure trend."""
    if len(samples) < 2:
        return {
            "trend": "steady",
            "change_hpa": 0.0,
            "forecast": "No trend data yet; expect stable conditions.",
        }

    window = samples[-min(len(samples), 1800):]
    first = window[0]["pressure_hpa"]
    last = window[-1]["pressure_hpa"]
    delta = last - first
    average_rate = delta / max((window[-1]["timestamp"] - window[0]["timestamp"]) / 3600.0, 1.0 / 3600.0)
    forecast_hpa = last + average_rate * 6.0

    if delta > 2.0:
        trend = "rising"
        forecast = "Pressure is climbing; expect improving weather and clearer skies over the next few hours."
    elif delta < -2.0:
        trend = "falling"
        forecast = "Pressure is dropping; unsettled weather, rain, or storms are more likely soon."
    else:
        trend = "steady"
        forecast = "Pressure is stable; conditions should remain fairly consistent for the next several hours."

    return {
        "trend": trend,
        "change_hpa": delta,
        "forecast": forecast,
        "projected_hpa": forecast_hpa,
    }


def build_pressure_forecast_svg(samples, *, hours=24):
    """Render a long-term pressure chart with a simple future-weather forecast."""
    if len(samples) < 2:
        return ""

    window = samples[-min(len(samples), hours * 60 * 60):]
    if len(window) < 2:
        return ""

    values = [sample["pressure_hpa"] for sample in window]
    min_value = min(values) - 2.0
    max_value = max(values) + 2.0
    width = 900
    height = 240
    pad_left, pad_right, pad_top, pad_bottom = 40, 20, 12, 36
    chart_width = width - pad_left - pad_right
    chart_height = height - pad_top - pad_bottom

    points = []
    for sample_index, sample in enumerate(window):
        x = pad_left + (sample_index / max(len(window) - 1, 1)) * chart_width
        y = height - pad_bottom - ((sample["pressure_hpa"] - min_value) / (max_value - min_value)) * chart_height
        points.append(f"{x:.2f},{y:.2f}")
    path = "M " + " L ".join(points)

    start_time = window[0]["timestamp"]
    end_time = window[-1]["timestamp"]
    tick_markup = []
    for pos in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = pad_left + pos * chart_width
        ts = start_time + (end_time - start_time) * pos
        label_text = time.strftime("%H:%M", time.localtime(ts))
        tick_markup.append(
            f'<line x1="{x}" y1="{pad_top}" x2="{x}" y2="{height - pad_bottom}" stroke="#2d3748" stroke-dasharray="4 4" />'
        )
        tick_markup.append(f'<text x="{x}" y="{height - 8}" text-anchor="middle" fill="#94a3b8" font-size="11">{label_text}</text>')

    trend = _pressure_outlook(samples)
    forecast_hpa = trend["projected_hpa"]
    forecast_end_x = width - pad_right
    forecast_end_y = height - pad_bottom - ((forecast_hpa - min_value) / (max_value - min_value)) * chart_height
    current_end_x = pad_left + chart_width
    current_end_y = height - pad_bottom - ((window[-1]["pressure_hpa"] - min_value) / (max_value - min_value)) * chart_height

    return f"""
    <div class="chart-box">
      <div class="chart-header">
        <span>Barometric trend / future weather</span>
        <span>{trend['trend']} ({trend['change_hpa']:+.2f} hPa over window)</span>
      </div>
      <svg viewBox="0 0 {width} {height}" width="100%" height="240" aria-label="Barometric trend forecast chart">
        {''.join(f'<line x1="{pad_left}" y1="{pad_top + (chart_height / 4) * i}" x2="{width - pad_right}" y2="{pad_top + (chart_height / 4) * i}" stroke="#2d3748" />' for i in range(5))}
        {''.join(tick_markup)}
        <path d="{path}" fill="none" stroke="#34d399" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        <line x1="{current_end_x}" y1="{current_end_y}" x2="{forecast_end_x}" y2="{forecast_end_y}" stroke="#fbbf24" stroke-width="2" stroke-dasharray="8 6" />
        <circle cx="{current_end_x}" cy="{current_end_y}" r="4" fill="#34d399" />
        <circle cx="{forecast_end_x}" cy="{forecast_end_y}" r="4" fill="#fbbf24" />
      </svg>
      <div class="forecast-note">{trend['forecast']}</div>
    </div>
    """


app = Flask(__name__)


@app.route("/diagnostics")
def diagnostics():
    """Return current sensor diagnostics as JSON."""
    with lock:
        history = list(readings)
        latest = history[-1] if history else {"temperature_c": 0.0, "pressure_hpa": 0.0, "humidity_pct": 0.0}
        runtime = dict(sensor_runtime_diagnostics)
    calibration = sensor.read_calibration_table()
    payload = {
        "latest": latest,
        "diagnostics": _build_diagnostics_payload(history, calibration, runtime),
        "calibration": calibration,
    }
    return jsonify(payload)


@app.route("/")
def index():
    """Render the main dashboard page with current readings and charts."""
    with lock:
        history = list(readings)
        latest = history[-1] if history else {"temperature_c": 0.0, "pressure_hpa": 0.0, "humidity_pct": 0.0}
        runtime = dict(sensor_runtime_diagnostics)

    info = sensor.read_calibration_table()
    diagnostics = _build_diagnostics_payload(history, info, runtime)
    calibration_fingerprint = _calibration_fingerprint(info)
    calibration_fingerprint_short = calibration_fingerprint[:12]
    temperature_chart = build_chart_svg(history, {"key": "temperature_c", "label": "Temperature", "color": "#60a5fa", "unit": "°C", "min_override": 15.0, "max_override": 35.0})
    pressure_chart = build_chart_svg(history, {"key": "pressure_hpa", "label": "Pressure", "color": "#34d399", "unit": "hPa", "min_override": 960.0, "max_override": 1040.0})
    humidity_chart = build_chart_svg(history, {"key": "humidity_pct", "label": "Humidity", "color": "#fbbf24", "unit": "%", "min_override": 20.0, "max_override": 80.0})
    pressure_forecast_chart = build_pressure_forecast_svg(history)
    trend = trend_summary(history)
    pressure_outlook = _pressure_outlook(history)
    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta http-equiv="refresh" content="2">
            <title>BME280 Dashboard</title>
            <style>
                body { font-family: sans-serif; background: #111827; color: #f9fafb; margin: 2rem; }
                .cards { display: flex; gap: 1rem; flex-wrap: wrap; }
                .card { background: #1f2937; border-radius: 10px; padding: 1rem 1.5rem; min-width: 180px; }
                .label { color: #9ca3af; font-size: 0.8rem; }
                .value { font-size: 2rem; font-weight: bold; }
                .mono { font-family: monospace; font-size: 1rem; word-break: break-all; }
                .trend-grid { display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0 2rem; }
                .trend-box { background: #1f2937; border-radius: 10px; padding: 1rem 1.2rem; min-width: 180px; }
                .chart-box { background: #0f172a; border-radius: 10px; padding: 0.75rem; margin: 1rem 0; }
                .chart-header { display: flex; justify-content: space-between; font-weight: 600; margin-bottom: 0.5rem; }
                .forecast-note { margin-top: 0.6rem; color: #d1fae5; font-size: 0.95rem; }
                pre { background: #0b1220; padding: 1rem; border-radius: 8px; overflow-x: auto; }
                details { margin-top: 1rem; background: #111827; border: 1px solid #374151; border-radius: 8px; }
                summary { cursor: pointer; padding: 0.8rem 1rem; font-weight: 600; }
                details > pre { margin: 0 1rem 1rem; }
            </style>
        </head>
        <body>
            <h1>BME280 dashboard</h1>
            <div class="cards">
                <div class="card"><div class="label">Temperature</div><div class="value">{{ latest.temperature_c }} °C</div></div>
                <div class="card"><div class="label">Pressure</div><div class="value">{{ latest.pressure_hpa }} hPa</div></div>
                <div class="card"><div class="label">Humidity</div><div class="value">{{ latest.humidity_pct }} %</div></div>
                <div class="card"><div class="label">Fingerprint ID</div><div class="mono">{{ calibration_fingerprint_short }}</div></div>
            </div>

            <h2>Trend analysis</h2>
            <div class="trend-grid">
                <div class="trend-box"><div class="label">Temperature</div><div class="value">{{ trend.temperature }}</div></div>
                <div class="trend-box"><div class="label">Pressure</div><div class="value">{{ trend.pressure }}</div></div>
                <div class="trend-box"><div class="label">Humidity</div><div class="value">{{ trend.humidity }}</div></div>
                <div class="trend-box"><div class="label">Pressure outlook</div><div class="value">{{ pressure_outlook.trend }}</div></div>
            </div>

            {{ pressure_forecast_chart|safe }}
            {{ temperature_chart|safe }}
            {{ pressure_chart|safe }}
            {{ humidity_chart|safe }}

            <details id="sensor-diagnostics-panel">
                <summary>Sensor diagnostics</summary>
                <pre>{{ diagnostics }}</pre>
            </details>

            <details id="calibration-table-panel">
                <summary>Calibration table</summary>
                <pre>{{ calibration }}</pre>
            </details>
            <script>
                (function() {
                    const panelIds = ["sensor-diagnostics-panel", "calibration-table-panel"];

                    function storageKey(panelId) {
                        return `bme280-panel-open:${panelId}`;
                    }

                    panelIds.forEach((panelId) => {
                        const panel = document.getElementById(panelId);
                        if (!panel) {
                            return;
                        }

                        const savedState = localStorage.getItem(storageKey(panelId));
                        if (savedState === "open") {
                            panel.open = true;
                        } else if (savedState === "closed") {
                            panel.open = false;
                        }

                        panel.addEventListener("toggle", () => {
                            localStorage.setItem(storageKey(panelId), panel.open ? "open" : "closed");
                        });
                    });
                })();
            </script>
        </body>
        </html>
        """,
        latest=latest,
        temperature_chart=temperature_chart,
        pressure_chart=pressure_chart,
        humidity_chart=humidity_chart,
        pressure_forecast_chart=pressure_forecast_chart,
        trend=trend,
        pressure_outlook=pressure_outlook,
        calibration_fingerprint=calibration_fingerprint,
        calibration_fingerprint_short=calibration_fingerprint_short,
        diagnostics=json.dumps(diagnostics, indent=2, sort_keys=True),
        calibration=json.dumps(info, indent=2, sort_keys=True),
    )


if __name__ == "__main__":
    thread = threading.Thread(target=update_readings, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=5000)
