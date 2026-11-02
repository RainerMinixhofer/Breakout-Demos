#!/usr/bin/env python3
"""Read data from a u-blox NEO-6M GPS connected to the Raspberry Pi UART."""

from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import date as dt_date, datetime, time as dt_time
from typing import Any

try:
    import serial
    from serial import SerialException
except ImportError as exc:  # pragma: no cover - dependency install guidance
    raise SystemExit(
        "pyserial is not installed. Activate the project venv and run:\n"
        "  python -m pip install -r requirements.txt"
    ) from exc

try:
    from pyubx2 import UBXMessage, UBXReader
    from pyubx2.ubxhelpers import process_monver
except ImportError as exc:  # pragma: no cover - dependency install guidance
    raise SystemExit(
        "pyubx2 is not installed. Activate the project venv and run:\n"
        "  python -m pip install -r requirements.txt"
    ) from exc

try:
    from flask import Flask, jsonify, render_template_string, request
except ImportError:  # pragma: no cover - optional for JSON-only mode
    Flask = None
    jsonify = None
    render_template_string = None
    request = None

FIX_TYPE_LABELS = {
    0: "NO_FIX",
    1: "DR",
    2: "2D",
    3: "3D",
    4: "GPS_PLUS_DR",
    5: "TIME_ONLY",
}

NMEA_FIX_TYPE_LABELS = {
    0: "NO_FIX",
    1: "GPS_FIX",
    2: "DGPS_FIX",
    3: "PPS_FIX",
    4: "RTK_FIX",
    5: "RTK_FLOAT",
    6: "ESTIMATED",
    7: "MANUAL",
    8: "SIMULATION",
}

DEFAULT_PORT_CANDIDATES = ("/dev/ttyAMA0", "/dev/serial0", "/dev/ttyS0", "/dev/ttyUSB0", "/dev/ttyUSB1")
UBX_POLL_IDS = {
    "MON-VER": (b"\x0a", b"\x04"),
    "MON-HW": (b"\x0a", b"\x09"),
    "NAV-PVT": (b"\x01", b"\x07"),
    "NAV-STATUS": (b"\x01", b"\x03"),
    "NAV-SVINFO": (b"\x01", b"\x30"),
}


class GPSNeo6:
    """Wrapper around a UART-connected u-blox NEO-6M GPS module."""

    def __init__(
        self,
        port: str | None = None,
        baudrate: int = 9600,
        timeout: float = 15.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_port = None
        self.reader = None
        self._serial_lock = threading.Lock()
        self._last_poll_result: dict[str, Any] = {}
        self._connect()

    def _connect(self) -> None:
        candidates = [self.port] if self.port else list(DEFAULT_PORT_CANDIDATES)
        last_error: Exception | None = None

        for candidate in candidates:
            try:
                self.serial_port = serial.Serial(
                    candidate,
                    baudrate=self.baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=self.timeout,
                    rtscts=False,
                    dsrdtr=False,
                    xonxoff=False,
                )
                self.port = candidate
                break
            except (SerialException, OSError) as exc:
                last_error = exc
                continue

        if self.serial_port is None:
            raise SerialException(
                f"Unable to open a GPS serial port. Tried: {', '.join(candidates)}"
            ) from last_error

        self.serial_port.reset_input_buffer()
        self.reader = UBXReader(self.serial_port, quitonerror=False)

    def close(self) -> None:
        if self.serial_port is not None:
            self.serial_port.close()
            self.serial_port = None
            self.reader = None

    @staticmethod
    def _format_utc(message: Any) -> str | None:
        date_obj = getattr(message, "date", None)
        time_obj = getattr(message, "time", None)
        if date_obj is not None and time_obj is not None:
            try:
                return datetime.combine(date_obj, time_obj).strftime("%Y-%m-%dT%H:%M:%SZ")
            except TypeError:
                pass

        year = getattr(message, "year", None)
        month = getattr(message, "month", None)
        day = getattr(message, "day", None)
        hour = getattr(message, "hour", None)
        minute = getattr(message, "min", None)
        second = getattr(message, "second", None)
        if None in (year, month, day, hour, minute, second):
            return None
        return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"

    @staticmethod
    def _normalize_fix_type(value: Any, labels: dict[int, str] | None = None) -> tuple[int | None, str | None]:
        if value in (None, ""):
            return None, None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None, str(value)
        label_map = FIX_TYPE_LABELS if labels is None else labels
        return parsed, label_map.get(parsed, str(value))

    @staticmethod
    def _to_float(value: Any, scale: float = 1.0) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value) / scale
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_plain_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        payload = getattr(value, "__dict__", None)
        if isinstance(payload, dict):
            return {key: val for key, val in payload.items() if not key.startswith("_")}
        return {}

    @classmethod
    def _status_details(cls, message: Any) -> dict[str, Any]:
        identity = getattr(message, "identity", None) or getattr(message, "msgID", None)
        details: dict[str, Any] = {}

        if hasattr(message, "iTOW"):
            details["iTOW"] = getattr(message, "iTOW", None)
        if hasattr(message, "gpsFix"):
            details["gpsFix"] = getattr(message, "gpsFix", None)
        if hasattr(message, "fixType"):
            details["fixType"] = getattr(message, "fixType", None)
        if hasattr(message, "valid_bit"):
            details["valid_bit"] = cls._as_plain_dict(getattr(message, "valid_bit"))
        if hasattr(message, "flags_bit"):
            details["flags_bit"] = cls._as_plain_dict(getattr(message, "flags_bit"))
        if hasattr(message, "flags2_bit"):
            details["flags2_bit"] = cls._as_plain_dict(getattr(message, "flags2_bit"))
        if hasattr(message, "fixStat_bit"):
            details["fixStat_bit"] = cls._as_plain_dict(getattr(message, "fixStat_bit"))
        if hasattr(message, "ttff"):
            details["ttff"] = getattr(message, "ttff", None)
        if hasattr(message, "msss"):
            details["msss"] = getattr(message, "msss", None)
        if hasattr(message, "quality"):
            details["quality"] = getattr(message, "quality", None)
        if hasattr(message, "status"):
            details["status"] = getattr(message, "status", None)
        if hasattr(message, "navMode"):
            details["navMode"] = getattr(message, "navMode", None)
        if hasattr(message, "numSV"):
            details["numSV"] = getattr(message, "numSV", None)
        if hasattr(message, "numCh"):
            details["numCh"] = getattr(message, "numCh", None)

        if identity == "MON-VER":
            try:
                details["mon_ver"] = process_monver(message)
            except Exception:
                pass

        if identity == "GPGSA":
            details["gsa_mode"] = getattr(message, "opMode", None)
            details["gsa_nav_mode"] = getattr(message, "navMode", None)
            details["pdop"] = getattr(message, "PDOP", None)
            details["hdop"] = getattr(message, "HDOP", None)
            details["vdop"] = getattr(message, "VDOP", None)

        if identity == "GPGSV":
            details["num_msg"] = getattr(message, "numMsg", None)
            details["msg_num"] = getattr(message, "msgNum", None)
            details["num_sv"] = getattr(message, "numSV", None)

        if not details:
            return {}
        return details

    def poll_ubx_message(self, identity: str, timeout: float = 2.0) -> dict[str, Any]:
        key = str(identity).strip().upper()
        if key not in UBX_POLL_IDS:
            raise ValueError(f"Unsupported UBX poll message: {identity}. Choices: {', '.join(sorted(UBX_POLL_IDS))}")

        payload_class, payload_id = UBX_POLL_IDS[key]
        poll_message = UBXMessage(payload_class, payload_id, 0)
        start = time.monotonic()
        end = start + timeout
        response: dict[str, Any] = {}
        with self._serial_lock:
            self.serial_port.write(poll_message.serialize())
            self.serial_port.flush()
            while time.monotonic() < end:
                try:
                    raw_data, incoming = self.reader.read()
                except (SerialException, OSError, ValueError):
                    time.sleep(0.05)
                    continue
                if incoming is None:
                    continue
                current_identity = getattr(incoming, "identity", None)
                if current_identity in {"ACK-ACK", "ACK-NAK"}:
                    response = {
                        "message": current_identity,
                        "ok": current_identity == "ACK-ACK",
                        "status": "poll acknowledged" if current_identity == "ACK-ACK" else "poll rejected",
                        "raw_hex": raw_data.hex() if raw_data else None,
                    }
                    continue
                if current_identity == key:
                    fields = self._as_plain_dict(incoming)
                    response = {
                        "message": current_identity,
                        "timestamp_utc": self._format_utc(incoming),
                        "raw_hex": raw_data.hex() if raw_data else None,
                        "status_details": self._status_details(incoming),
                        "fields": fields,
                    }
                    self._last_poll_result = response
                    return response

        response = {
            "message": key,
            "ok": False,
            "status": f"No response received for {key} within {timeout:.1f}s",
            "raw_hex": None,
        }
        self._last_poll_result = response
        return response

    @property
    def last_poll_result(self) -> dict[str, Any]:
        return dict(self._last_poll_result)

    def _nmea_to_snapshot(self, message: Any) -> dict[str, Any]:
        msg_id = getattr(message, "msgID", None)
        identity = getattr(message, "identity", None)
        identity_key = msg_id or identity
        if identity_key not in {"GGA", "RMC", "GLL", "VTG"}:
            return {}

        timestamp_utc = self._format_utc(message)
        lat = self._to_float(getattr(message, "lat", None), 1.0)
        lon = self._to_float(getattr(message, "lon", None), 1.0)
        status = getattr(message, "status", None)
        quality = getattr(message, "quality", None)
        gnss_fix_ok = False

        if identity_key == "GGA":
            fix_code, fix_label = self._normalize_fix_type(quality, NMEA_FIX_TYPE_LABELS)
            gnss_fix_ok = fix_code not in (None, 0)
            snapshot = {
                "message": "GGA",
                "timestamp_utc": timestamp_utc,
                "fix_type_code": fix_code,
                "fix_type": fix_label,
                "gnss_fix_ok": gnss_fix_ok,
                "num_sv": getattr(message, "numSV", None),
                "latitude_deg": lat,
                "longitude_deg": lon,
                "altitude_m": self._to_float(getattr(message, "alt", None), 1.0),
                "horizontal_accuracy_m": None,
                "vertical_accuracy_m": None,
                "ground_speed_mps": None,
                "heading_deg": None,
            }
            details = self._status_details(message)
            if details:
                snapshot["status_details"] = details
            return snapshot

        if identity_key == "RMC":
            valid_status = status == "A"
            if valid_status:
                fix_code, fix_label = 1, "GPS_FIX"
            else:
                fix_code, fix_label = 0, "NO_FIX"
            gnss_fix_ok = valid_status
            spd_knots = self._to_float(getattr(message, "spd", None), 1.0)
            heading_deg = self._to_float(getattr(message, "cog", None), 1.0)
            snapshot = {
                "message": "RMC",
                "timestamp_utc": timestamp_utc,
                "fix_type_code": fix_code,
                "fix_type": fix_label,
                "gnss_fix_ok": gnss_fix_ok,
                "num_sv": None,
                "latitude_deg": lat,
                "longitude_deg": lon,
                "altitude_m": None,
                "horizontal_accuracy_m": None,
                "vertical_accuracy_m": None,
                "ground_speed_mps": spd_knots * 0.514444 if spd_knots is not None else None,
                "heading_deg": heading_deg,
            }
            details = self._status_details(message)
            if details:
                snapshot["status_details"] = details
            return snapshot

        if identity_key in {"GLL", "VTG"}:
            snapshot = {
                "message": identity_key,
                "timestamp_utc": timestamp_utc,
                "fix_type_code": 1 if status == "A" else 0,
                "fix_type": "GPS_FIX" if status == "A" else "NO_FIX",
                "gnss_fix_ok": status == "A",
                "num_sv": None,
                "latitude_deg": lat,
                "longitude_deg": lon,
                "altitude_m": None,
                "horizontal_accuracy_m": None,
                "vertical_accuracy_m": None,
                "ground_speed_mps": self._to_float(getattr(message, "sogn", None), 1.0) * 0.514444 if getattr(message, "sogn", None) not in (None, "") else None,
                "heading_deg": self._to_float(getattr(message, "cogt", None), 1.0) if getattr(message, "cogt", None) not in (None, "") else None,
            }
            details = self._status_details(message)
            if details:
                snapshot["status_details"] = details
            return snapshot

        return {}

    def _message_to_snapshot(self, message: Any) -> dict[str, Any]:
        identity = getattr(message, "identity", None)
        if identity == "NAV-PVT":
            fix_code, fix_label = self._normalize_fix_type(getattr(message, "fixType", None))
            raw_valid = getattr(message, "valid_bit", None)
            flags_bit = getattr(message, "flags_bit", None)
            gnss_fix_ok = False
            if flags_bit is not None:
                gnss_fix_ok = bool(getattr(flags_bit, "gnssFixOk", 0))
            elif raw_valid is not None:
                gnss_fix_ok = bool(getattr(raw_valid, "validTime", 0))

            latitude = getattr(message, "lat", None)
            longitude = getattr(message, "lon", None)
            altitude_mm = getattr(message, "height", None)
            height_above_msl_mm = getattr(message, "hMSL", None)
            ground_speed_cm_s = getattr(message, "gSpeed", None)
            heading = getattr(message, "headMot", None)
            horizontal_accuracy_mm = getattr(message, "hAcc", None)
            vertical_accuracy_mm = getattr(message, "vAcc", None)
            speed_accuracy_mm = getattr(message, "sAcc", None)

            snapshot = {
                "message": "NAV-PVT",
                "timestamp_utc": self._format_utc(message),
                "fix_type_code": fix_code,
                "fix_type": fix_label,
                "gnss_fix_ok": gnss_fix_ok,
                "num_sv": getattr(message, "numSV", None),
                "latitude_deg": self._to_float(latitude, 1_000_000.0) if latitude is not None else None,
                "longitude_deg": self._to_float(longitude, 1_000_000.0) if longitude is not None else None,
                "altitude_m": self._to_float(altitude_mm, 1000.0) if altitude_mm is not None else None,
                "height_above_sea_m": self._to_float(height_above_msl_mm, 1000.0) if height_above_msl_mm is not None else None,
                "ground_speed_mps": self._to_float(ground_speed_cm_s, 100.0) if ground_speed_cm_s is not None else None,
                "heading_deg": self._to_float(heading, 1_000_000.0) if heading is not None else None,
                "horizontal_accuracy_m": self._to_float(horizontal_accuracy_mm, 1000.0) if horizontal_accuracy_mm is not None else None,
                "vertical_accuracy_m": self._to_float(vertical_accuracy_mm, 1000.0) if vertical_accuracy_mm is not None else None,
                "speed_accuracy_m": self._to_float(speed_accuracy_mm, 1000.0) if speed_accuracy_mm is not None else None,
                "velocity_north_cm_s": getattr(message, "velN", None),
                "velocity_east_cm_s": getattr(message, "velE", None),
                "velocity_down_cm_s": getattr(message, "velD", None),
            }
            details = self._status_details(message)
            if details:
                snapshot["status_details"] = details
            return snapshot

        if identity is not None and identity.startswith(("GP", "GN", "GL")):
            return self._nmea_to_snapshot(message)

        if identity in {"MON-VER", "NAV-STATUS", "NAV-SVINFO", "MON-HW"}:
            snapshot = {
                "message": identity,
                "timestamp_utc": self._format_utc(message),
                "fix_type_code": getattr(message, "gpsFix", None),
                "fix_type": FIX_TYPE_LABELS.get(getattr(message, "gpsFix", None), None),
                "gnss_fix_ok": bool(getattr(getattr(message, "flags_bit", None), "gpsFixOk", 0) if hasattr(message, "flags_bit") else False),
                "num_sv": getattr(message, "numSV", None),
            }
            details = self._status_details(message)
            if details:
                snapshot["status_details"] = details
            return snapshot

        return {}

    def read_snapshot(self, timeout: float | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        last_snapshot: dict[str, Any] = {}
        last_seen_message: str | None = None

        while time.monotonic() < deadline:
            try:
                with self._serial_lock:
                    raw_data, message = self.reader.read()
            except (SerialException, OSError, ValueError):
                time.sleep(0.05)
                continue

            if message is None:
                continue

            last_seen_message = getattr(message, "identity", type(message).__name__)

            # UBX reader may yield NMEA and UBX frames; only NAV-PVT contains the keyed telemetry.
            snapshot = self._message_to_snapshot(message)
            if snapshot:
                last_snapshot = snapshot
                if snapshot.get("fix_type_code") is not None:
                    return snapshot

        if last_snapshot:
            return last_snapshot

        if last_seen_message is not None:
            hint = (
                f"The port opened successfully but no valid UBX NAV-PVT message was received. "
                f"The GPS may still be acquiring a fix or the module may be outputting a different UART/baud format. "
                f"Last message seen: {last_seen_message}."
            )
        else:
            hint = (
                "The port opened successfully but the GPS is not sending UBX data. "
                "Check the wiring, enable the Pi UART, and verify the GPS is configured for UBX/NMEA at 9600 baud."
            )

        raise TimeoutError(
            f"No valid UBX NAV-PVT data from {self.port} within {timeout if timeout is not None else self.timeout} seconds. {hint}"
        )

    def diagnostic_scan(self, timeout: float | None = None) -> None:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        packets_seen = 0
        bytes_seen = 0

        print(f"GPS diagnostic mode: port={self.port}, baudrate={self.baudrate}, timeout={timeout if timeout is not None else self.timeout}s")
        print("Listening for raw serial data... Ctrl+C to stop early.\n")

        while time.monotonic() < deadline:
            try:
                with self._serial_lock:
                    raw_data, message = self.reader.read()
            except (SerialException, OSError, ValueError) as exc:
                print(f"Serial read error: {exc}")
                time.sleep(0.1)
                continue

            if raw_data:
                bytes_seen += len(raw_data)
                print(f"[RAW] {len(raw_data)} bytes: {raw_data.hex()}")

            if message is not None:
                packets_seen += 1
                identity = getattr(message, "identity", type(message).__name__)
                snapshot = self._message_to_snapshot(message)
                print(f"[MSG] identity={identity} fix={snapshot.get('fix_type') if snapshot else 'N/A'}")
                if snapshot:
                    print(json.dumps(snapshot, indent=2, sort_keys=True))
                else:
                    print(message)

            if not raw_data and message is None:
                time.sleep(0.05)

        print(f"\nDiagnostic complete: {packets_seen} parsed messages, {bytes_seen} raw bytes received.")


class GPSNeo6Monitor:
    """Background thread wrapper for periodic GPS sampling."""

    def __init__(self, gps: GPSNeo6, interval_seconds: float = 1.0) -> None:
        self.gps = gps
        self.interval_seconds = interval_seconds
        self._latest: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                snapshot = self.gps.read_snapshot(timeout=2.0)
            except (TimeoutError, SerialException, OSError):
                snapshot = {"error": "gps read failed"}
            with self._lock:
                self._latest = snapshot
            time.sleep(self.interval_seconds)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest)


class GPSStatusPoller:
    """Background thread for regular UBX status polling."""

    def __init__(self, gps: GPSNeo6, poll_sequence: list[str] | None = None, interval_seconds: float = 10.0) -> None:
        self.gps = gps
        self.poll_sequence = poll_sequence or ["NAV-STATUS", "MON-VER", "NAV-PVT"]
        self.interval_seconds = interval_seconds
        self._latest: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            for identity in self.poll_sequence:
                if self._stop_event.is_set():
                    break
                try:
                    result = self.gps.poll_ubx_message(identity, timeout=2.0)
                except ValueError:
                    result = {"message": identity, "ok": False, "status": "unsupported poll request"}
                with self._lock:
                    self._latest[identity] = result
                time.sleep(0.25)
            time.sleep(self.interval_seconds)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest)


def build_flask_app(gps: GPSNeo6, *, refresh_interval_ms: int = 2000) -> Flask:
    if Flask is None:
        raise RuntimeError("Flask is required for the HTTP dashboard.")

    app = Flask(__name__)
    monitor = GPSNeo6Monitor(gps, interval_seconds=1.0)
    status_poller = GPSStatusPoller(gps, interval_seconds=12.0)
    monitor.start()
    status_poller.start()

    @app.route("/")
    def index() -> str:
        snapshot = monitor.snapshot()
        result = gps.last_poll_result
        poll_status = status_poller.snapshot()
        return render_template_string(
            """
            <!doctype html>
            <html lang="en">
            <head>
                <meta charset="utf-8">
                <title>GPSNeo6 Dashboard</title>
                <meta http-equiv="refresh" content="{{ refresh_interval_ms // 1000 }}">
                <style>
                    body { font-family: sans-serif; background: #0f172a; color: #e2e8f0; margin: 2rem; }
                    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; }
                    .card { background: #1e293b; padding: 1rem 1.2rem; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.15); }
                    .label { color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; }
                    .value { font-size: clamp(1.3rem, 4vw, 2.2rem); font-weight: bold; margin-top: 0.4rem; }
                    .button-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1rem; }
                    button { background: #2563eb; color: white; border: none; border-radius: 8px; padding: 0.6rem 0.9rem; cursor: pointer; }
                    code { background: rgba(148,163,184,0.12); padding: 0.1rem 0.3rem; border-radius: 6px; }
                    pre { white-space: pre-wrap; word-break: break-word; }
                    .status-preview { margin-top: 1rem; }
                </style>
            </head>
            <body>
                <h1>GPSNeo6</h1>
                <div class="grid">
                    <div class="card">
                        <div class="label">Fix</div>
                        <div class="value">{{ snapshot.get('fix_type', 'N/A') }}</div>
                    </div>
                    <div class="card">
                        <div class="label">Position</div>
                        <div class="value">{{ snapshot.get('latitude_deg', 'N/A') }}, {{ snapshot.get('longitude_deg', 'N/A') }}</div>
                    </div>
                    <div class="card">
                        <div class="label">Altitude</div>
                        <div class="value">{{ snapshot.get('altitude_m', 'N/A') }} m</div>
                    </div>
                    <div class="card">
                        <div class="label">GNSS fix ok</div>
                        <div class="value">{{ 'YES' if snapshot.get('gnss_fix_ok') else 'NO' }}</div>
                    </div>
                </div>
                <div class="card" style="margin-top: 1.5rem;">
                    <div class="label">Live snapshot</div>
                    <pre><code>{{ snapshot }}</code></pre>
                </div>
                <div class="card" style="margin-top: 1.5rem;">
                    <div class="label">Automatic status poll results</div>
                    <pre><code>{{ poll_status }}</code></pre>
                </div>
                <div class="card" style="margin-top: 1.5rem;">
                    <div class="label">UBX poll commands</div>
                    <div class="button-row">
                        {% for identity in supported_polls %}
                        <button type="button" onclick="poll('{{ identity }}')">{{ identity }}</button>
                        {% endfor %}
                    </div>
                    <div style="margin-top: 1rem;">
                        <div class="label">Last poll result</div>
                        <pre><code>{{ result }}</code></pre>
                    </div>
                </div>
            </body>
            </html>
            """,
            snapshot=snapshot,
            refresh_interval_ms=refresh_interval_ms,
            result=result,
            poll_status=poll_status,
            supported_polls=sorted(UBX_POLL_IDS),
        )

    @app.route("/api/position")
    def api_position():
        return jsonify(monitor.snapshot())

    @app.route("/api/poll", methods=["POST"])
    def api_poll():
        identity = request.form.get("identity", "NAV-STATUS")
        try:
            response = gps.poll_ubx_message(identity)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(response)

    @app.route("/api/status")
    def api_status():
        return jsonify({
            "snapshot": monitor.snapshot(),
            "polls": status_poller.snapshot(),
            "last_poll": gps.last_poll_result,
            "supported_polls": sorted(UBX_POLL_IDS),
        })

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read position and navigation data from a u-blox NEO-6M connected to the Raspberry Pi TX/RX UART. "
            "On the Pi this is usually /dev/serial0."
        )
    )
    parser.add_argument(
        "--port",
        default=None,
        help="Serial device path. Defaults to common Pi UART candidates: /dev/serial0, /dev/ttyAMA0, /dev/ttyS0",
    )
    parser.add_argument("--baudrate", type=int, default=9600, help="UART baud rate (default: 9600)")
    parser.add_argument("--timeout", type=float, default=15.0, help="Read timeout in seconds (default: 15.0)")
    parser.add_argument("--samples", type=int, default=1, help="Number of snapshots to fetch before exiting (default: 1)")
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Print raw serial traffic and parsed UBX/NMEA frames for debugging the GPS connection.",
    )
    parser.add_argument(
        "--serve",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run a small Flask dashboard instead of a one-off read.",
    )
    parser.add_argument(
        "--poll",
        type=str,
        default=None,
        help="Send a UBX poll command and print the response. Supported: MON-VER, MON-HW, NAV-PVT, NAV-STATUS, NAV-SVINFO.",
    )
    parser.add_argument("--poll-timeout", type=float, default=2.0, help="Timeout for UBX polling in seconds (default: 2.0)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Flask host for dashboard mode (default: 0.0.0.0)")
    parser.add_argument("--port-http", type=int, default=5000, help="Flask port for dashboard mode (default: 5000)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gps = GPSNeo6(port=args.port, baudrate=args.baudrate, timeout=args.timeout)
    try:
        if args.diagnostic:
            gps.diagnostic_scan(timeout=args.timeout)
            return

        if args.poll:
            result = gps.poll_ubx_message(args.poll, timeout=args.poll_timeout)
            print(json.dumps(result, indent=2, sort_keys=True))
            return

        if args.serve:
            if Flask is None:
                raise SystemExit("Flask is required for --serve. Install it with: python -m pip install -r requirements.txt")
            app = build_flask_app(gps)
            app.run(host=args.host, port=args.port_http, debug=False)
            return

        snapshots: list[dict[str, Any]] = []
        for _ in range(max(1, args.samples)):
            snapshot = gps.read_snapshot(timeout=args.timeout)
            snapshots.append(snapshot)
        print(json.dumps(snapshots[0] if len(snapshots) == 1 else snapshots, indent=2))
    finally:
        gps.close()


if __name__ == "__main__":
    main()
