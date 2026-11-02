#!/usr/bin/env python3
"""Flask web frontend for MLX90640 live stream and camera controls."""

import argparse
import logging
import threading
import time
from typing import Dict, Optional

from mlx90640.mlx90640 import MLX90640

# pylint: disable=E1101
import cv2

# pylint: enable=E1101

import numpy as np
from flask import Flask, Response, jsonify, render_template, request

from mlx90640_backend import ensure_devicetree_backend, refresh_rate_code_to_hz

LOGGER = logging.getLogger("mlx90640-web")

# pylint: disable=E1101
PALETTES = {
    "inferno": cv2.COLORMAP_INFERNO,
    "jet": cv2.COLORMAP_JET,
    "turbo": cv2.COLORMAP_TURBO,
    "hot": cv2.COLORMAP_HOT,
    "plasma": cv2.COLORMAP_PLASMA,
}

INTERPOLATION = {
    "nearest": cv2.INTER_NEAREST,
    "linear": cv2.INTER_LINEAR,
}
# pylint: enable=E1101


def _coerce_int(value: object, field_name: str) -> int:
    """Convert a user-controlled value to an integer with validation."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{field_name} must be an integer")
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an integer") from exc
    raise ValueError(f"{field_name} must be an integer")


def _coerce_float(value: object, field_name: str) -> float:
    """Convert a user-controlled value to a float with validation."""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{field_name} must be numeric")
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be numeric") from exc
    raise ValueError(f"{field_name} must be numeric")


def _coerce_str(value: object, field_name: str) -> str:
    """Convert a user-controlled value to a string with validation."""
    if value is None:
        raise ValueError(f"{field_name} must be a string")
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    raise ValueError(f"{field_name} must be a string")




class ThermalWebBackend:
    """Hold the camera state, image capture loop, and live-process controls."""

    def __init__(self, i2c_address: int, refresh_rate_code: int, average_frames: int):
        """Initialize the MLX90640 device and its runtime state."""
        ensure_devicetree_backend()
        self.camera = MLX90640(slave_address=i2c_address)
        self.camera_lock = threading.RLock()
        self.state_lock = threading.RLock()
        self.running = False
        self.thread: Optional[threading.Thread] = None

        self.refresh_rate_code = refresh_rate_code
        self.sensor_resolution = 0
        self.sensor_mode = "chess"
        self.emissivity = 1.0
        self.tr_offset = 8.0
        self.palette = "inferno"
        self.interpolation = "nearest"
        self.display_enhancement_enabled = True
        self.auto_scale = True
        self.min_temp = 20.0
        self.max_temp = 35.0
        self.average_frames = average_frames
        self.integration_time_seconds = 1.0
        self.stripe_correction_enabled = False
        self.stripe_correction_strength = 1.0
        self.median_filter_enabled = False
        self.median_kernel = 3

        self.last_error: Optional[str] = None
        self.latest_jpeg: Optional[bytes] = None
        self.latest_integrated_jpeg: Optional[bytes] = None
        self._integration_samples: list[tuple[float, np.ndarray]] = []
        self.latest_stats: Dict[str, float] = {
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "fps": 0.0,
        }
        self.status_register_polling_enabled = False
        self.latest_status_registers: Dict[str, object] = {
            "resolution": 0.0,
            "refresh_rate": 0.0,
            "mode": 0.0,
            "sub_page": 0.0,
            "vdd": 0.0,
            "ta": 0.0,
            "frame_data_words": [0] * 12,
            "eeprom_words": [0] * 12,
        }

        self._initialize_camera()

    @staticmethod
    def _mode_name_from_code(mode_code: int) -> str:
        """Map the driver mode code to a user-friendly mode label."""
        if mode_code == 1:
            return "interleaved"
        return "chess"

    def _initialize_camera(self) -> None:
        """Prepare the MLX90640 sensor for frame acquisition."""
        with self.camera_lock:
            self.camera.i2c_init()
            self.camera.set_refresh_rate(self.refresh_rate_code)
            self.camera.dump_eeprom()
            self.camera.extract_parameters()
            self.sensor_resolution = int(self.camera.get_resolution())
            self.sensor_mode = self._mode_name_from_code(self.camera.get_cur_mode())
            for _ in range(2):
                self._read_frame_array(self.emissivity, self.tr_offset)

    def _read_frame_array(self, emissivity: float, tr_offset: float) -> np.ndarray:
        """Read one raw thermal frame and convert it to temperature values."""
        _ = self.camera.get_frame_data()
        ta = self.camera.get_ta()
        values = self.camera.calculate_to(emissivity, ta - tr_offset)
        return np.array(values, dtype=np.float32).reshape(24, 32)

    def _read_averaged_frame_array(
        self, emissivity: float, tr_offset: float, average_frames: int
    ) -> np.ndarray:
        """Average multiple consecutive frames before exposing them to the UI."""
        frames_to_average = max(1, average_frames)
        accumulator = self._read_frame_array(emissivity, tr_offset)
        for _ in range(frames_to_average - 1):
            accumulator += self._read_frame_array(emissivity, tr_offset)
        return accumulator / float(frames_to_average)

    def _apply_mitigations(
        self,
        frame: np.ndarray,
        stripe_correction_enabled: bool,
        stripe_correction_strength: float,
        median_filter_enabled: bool,
        median_kernel: int,
    ) -> np.ndarray:
        """Apply the configured stripe-noise mitigation steps to a frame."""
        finite_mask = np.isfinite(frame)
        if not np.any(finite_mask):
            raise RuntimeError("No finite temperatures in frame")

        finite_values = frame[finite_mask]
        fill_value = float(np.median(finite_values))
        output = np.nan_to_num(
            frame, nan=fill_value, posinf=fill_value, neginf=fill_value
        ).astype(np.float32)

        if stripe_correction_enabled:
            column_medians = np.median(output, axis=0)
            global_median = float(np.median(output))
            column_bias = (column_medians - global_median) * stripe_correction_strength
            output = output - column_bias[np.newaxis, :]

        if median_filter_enabled:
            kernel = int(median_kernel)
            if kernel % 2 == 0:
                kernel += 1
            kernel = max(3, min(kernel, 7))
            output = cv2.medianBlur(output, kernel)  # pylint: disable=E1101

        return output

    def _frame_to_jpeg(
        self,
        frame: np.ndarray,
        fps: float,
        refresh_rate_code: int,
        average_frames: int,
        auto_scale: bool,
        min_temp: float,
        max_temp: float,
        palette: str,
        interpolation: str,
        display_enhancement_enabled: bool,
        integration_label: str = "",
    ) -> bytes:
        """Render a temperature frame into a JPEG with overlays and colormap."""
        finite_mask = np.isfinite(frame)
        if not np.any(finite_mask):
            raise RuntimeError("No finite temperatures in frame")

        finite_values = frame[finite_mask]
        frame_min = float(np.min(finite_values))
        frame_max = float(np.max(finite_values))
        frame_mean = float(np.mean(finite_values))
        if auto_scale:
            vmin, vmax = frame_min, frame_max
        else:
            vmin, vmax = min_temp, max_temp
        if vmax <= vmin:
            vmax = vmin + 0.01

        frame_clean = np.nan_to_num(frame, nan=vmin, posinf=vmax, neginf=vmin)
        normalized = np.clip((frame_clean - vmin) / (vmax - vmin), 0.0, 1.0)
        gray = (normalized * 255.0).astype(np.uint8)
        # pylint: disable=E1101
        colored = cv2.applyColorMap(gray, PALETTES[palette])
        if display_enhancement_enabled:
            enlarged = cv2.resize(
                colored,
                (640, 480),
                interpolation=cv2.INTER_LANCZOS4,
            )
            blurred = cv2.GaussianBlur(enlarged, (0, 0), 1.0)
            resized = cv2.addWeighted(enlarged, 1.18, blurred, -0.18, 0)
        else:
            resized = cv2.resize(
                colored, (640, 480), interpolation=INTERPOLATION[interpolation]
            )
        integration_suffix = (
            f"  int {integration_label}" if integration_label else ""
        )
        overlay = (
            f"min {frame_min:.1f}C  max {frame_max:.1f}C  mean {frame_mean:.1f}C  "
            f"fps {fps:.1f}  code {refresh_rate_code}  avg {average_frames}{integration_suffix}"
        )
        cv2.putText(
            resized,
            overlay,
            (8, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        ok, encoded = cv2.imencode(
            ".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
        )
        # pylint: enable=E1101
        if not ok:
            raise RuntimeError("Failed to encode MJPEG frame")
        return encoded.tobytes()

    # pylint: disable=E1101
    def _error_jpeg(self, message: str) -> bytes:
        """Render an error placeholder frame for MJPEG streaming."""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(
            img,
            "MLX90640 stream error",
            (20, 220),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )  # pylint: disable=E1101
        cv2.putText(
            img,
            message[:70],
            (20, 260),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (200, 200, 200),
            1,
        )  # pylint: disable=E1101
        ok, encoded = cv2.imencode(
            ".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
        )  # pylint: disable=E1101
        if not ok:
            raise RuntimeError("Failed to encode error frame")
        return encoded.tobytes()
    # pylint: enable=E1101

    def start(self) -> None:
        """Start the background capture thread."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop the background capture thread and clean up the bus."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        with self.camera_lock:
            self.camera.i2c_tear_down()

    def _read_status_registers(self) -> None:
        """Read the MLX90640 status words used by the diagnostics panel."""
        with self.camera_lock:
            frame_data_words = [int(v) for v in list(self.camera.frame_data[:12])]
            eeprom_words = [int(v) for v in list(self.camera.eeprom_data[:12])]
            self.latest_status_registers = {
                "resolution": float(self.camera.get_resolution()),
                "refresh_rate": float(self.camera.get_refresh_rate()),
                "mode": float(self.camera.get_cur_mode()),
                "sub_page": float(self.camera.get_sub_page_number()),
                "vdd": float(self.camera.get_vdd()),
                "ta": float(self.camera.get_ta()),
                "frame_data_words": frame_data_words,
                "eeprom_words": eeprom_words,
            }

    def _capture_loop(self) -> None:
        """Continuously read, process, and publish camera frames."""
        previous = time.perf_counter()
        while self.running:
            try:
                with self.state_lock:
                    refresh_rate_code = self.refresh_rate_code
                    emissivity = self.emissivity
                    tr_offset = self.tr_offset
                    palette = self.palette
                    interpolation = self.interpolation
                    auto_scale = self.auto_scale
                    min_temp = self.min_temp
                    max_temp = self.max_temp
                    average_frames = self.average_frames
                    integration_time_seconds = self.integration_time_seconds
                    stripe_correction_enabled = self.stripe_correction_enabled
                    stripe_correction_strength = self.stripe_correction_strength
                    median_filter_enabled = self.median_filter_enabled
                    median_kernel = self.median_kernel
                    status_registers_enabled = self.status_register_polling_enabled

                with self.camera_lock:
                    raw_frame = self._read_averaged_frame_array(
                        emissivity, tr_offset, average_frames
                    )

                frame = self._apply_mitigations(
                    raw_frame,
                    stripe_correction_enabled,
                    stripe_correction_strength,
                    median_filter_enabled,
                    median_kernel,
                )
                now = time.perf_counter()
                dt = max(now - previous, 1e-6)
                previous = now
                fps = 1.0 / dt
                finite_values = frame[np.isfinite(frame)]
                latest_stats = {
                    "min": float(np.min(finite_values)),
                    "max": float(np.max(finite_values)),
                    "mean": float(np.mean(finite_values)),
                    "fps": fps,
                }
                display_enhancement_enabled = self.display_enhancement_enabled
                latest_jpeg = self._frame_to_jpeg(
                    frame,
                    fps,
                    refresh_rate_code,
                    average_frames,
                    auto_scale,
                    min_temp,
                    max_temp,
                    palette,
                    interpolation,
                    display_enhancement_enabled,
                )
                integrated_jpeg = latest_jpeg
                if integration_time_seconds > 0.0:
                    sample_time = time.monotonic()
                    self._integration_samples.append((sample_time, frame.copy()))
                    cutoff = sample_time - integration_time_seconds
                    self._integration_samples = [
                        sample
                        for sample in self._integration_samples
                        if sample[0] >= cutoff
                    ]
                    if self._integration_samples:
                        stacked = np.stack(
                            [sample[1] for sample in self._integration_samples], axis=0
                        )
                        integrated_frame = stacked.mean(axis=0)
                        integrated_jpeg = self._frame_to_jpeg(
                            integrated_frame,
                            fps,
                            refresh_rate_code,
                            average_frames,
                            auto_scale,
                            min_temp,
                            max_temp,
                            palette,
                            interpolation,
                            display_enhancement_enabled,
                            integration_label=f"{integration_time_seconds:.1f}s",
                        )
                with self.state_lock:
                    self.latest_stats = latest_stats
                    self.latest_jpeg = latest_jpeg
                    self.latest_integrated_jpeg = integrated_jpeg
                    self.last_error = None
                    if status_registers_enabled:
                        self._read_status_registers()
            except (
                AttributeError,
                KeyError,
                IndexError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
                ZeroDivisionError,
                OverflowError,
                cv2.error,  # pylint: disable=E1101
            ) as exc:
                LOGGER.exception("Capture loop error: %s", exc)
                with self.state_lock:
                    self.last_error = str(exc)
                    self.latest_jpeg = self._error_jpeg(self.last_error)
                time.sleep(0.1)
            time.sleep(0)

    def get_state(self, include_status_registers: bool = True) -> Dict[str, object]:
        """Return the current backend configuration and latest live statistics."""
        with self.state_lock:
            state = {
                "refresh_rate_code": self.refresh_rate_code,
                "refresh_rate_hz": refresh_rate_code_to_hz(self.refresh_rate_code),
                "sensor_resolution": self.sensor_resolution,
                "sensor_mode": self.sensor_mode,
                "emissivity": self.emissivity,
                "tr_offset": self.tr_offset,
                "palette": self.palette,
                "interpolation": self.interpolation,
                "display_enhancement_enabled": self.display_enhancement_enabled,
                "auto_scale": self.auto_scale,
                "min_temp": self.min_temp,
                "max_temp": self.max_temp,
                "average_frames": self.average_frames,
                "integration_time_seconds": self.integration_time_seconds,
                "stripe_correction_enabled": self.stripe_correction_enabled,
                "stripe_correction_strength": self.stripe_correction_strength,
                "median_filter_enabled": self.median_filter_enabled,
                "median_kernel": self.median_kernel,
                "last_error": self.last_error,
                "stats": dict(self.latest_stats),
            }
            if include_status_registers:
                state["status_registers"] = dict(self.latest_status_registers)
            return state

    def apply_controls(self, payload: Dict[str, object]) -> Dict[str, object]:
        """Apply a validated batch of control updates to the capture pipeline."""
        refresh_code = None
        if "refresh_rate_code" in payload:
            refresh_code = _coerce_int(
                payload["refresh_rate_code"], "refresh_rate_code"
            )
            if refresh_code < 0 or refresh_code > 7:
                raise ValueError("refresh_rate_code must be in range 0..7")

        sensor_resolution = None
        if "sensor_resolution" in payload:
            sensor_resolution = _coerce_int(payload["sensor_resolution"], "sensor_resolution")
            if sensor_resolution < 0 or sensor_resolution > 3:
                raise ValueError("sensor_resolution must be in range 0..3")

        sensor_mode = None
        if "sensor_mode" in payload:
            sensor_mode = _coerce_str(payload["sensor_mode"], "sensor_mode").lower()
            if sensor_mode not in {"chess", "interleaved"}:
                raise ValueError("sensor_mode must be 'chess' or 'interleaved'")

        emissivity = None
        if "emissivity" in payload:
            emissivity = _coerce_float(payload["emissivity"], "emissivity")
            if emissivity <= 0.0 or emissivity > 1.0:
                raise ValueError("emissivity must be in range (0.0, 1.0]")

        tr_offset = (
            _coerce_float(payload["tr_offset"], "tr_offset")
            if "tr_offset" in payload
            else None
        )

        palette = None
        if "palette" in payload:
            palette = _coerce_str(payload["palette"], "palette")
            if palette not in PALETTES:
                raise ValueError(
                    f"palette must be one of: {', '.join(PALETTES.keys())}"
                )

        interpolation = None
        if "interpolation" in payload:
            interpolation = _coerce_str(payload["interpolation"], "interpolation")
            if interpolation not in INTERPOLATION:
                raise ValueError("interpolation must be 'nearest' or 'linear'")

        display_enhancement_enabled = (
            bool(payload["display_enhancement_enabled"])
            if "display_enhancement_enabled" in payload
            else None
        )
        auto_scale = bool(payload["auto_scale"]) if "auto_scale" in payload else None
        min_temp = (
            _coerce_float(payload["min_temp"], "min_temp")
            if "min_temp" in payload
            else None
        )
        max_temp = (
            _coerce_float(payload["max_temp"], "max_temp")
            if "max_temp" in payload
            else None
        )

        average_frames = None
        if "average_frames" in payload:
            average_frames = _coerce_int(payload["average_frames"], "average_frames")
            if average_frames < 1 or average_frames > 32:
                raise ValueError("average_frames must be in range 1..32")

        integration_time_seconds = None
        if "integration_time_seconds" in payload:
            integration_time_seconds = _coerce_float(
                payload["integration_time_seconds"], "integration_time_seconds"
            )
            if integration_time_seconds < 0.0 or integration_time_seconds > 30.0:
                raise ValueError("integration_time_seconds must be in range 0.0..30.0")

        stripe_correction_enabled = (
            bool(payload["stripe_correction_enabled"])
            if "stripe_correction_enabled" in payload
            else None
        )
        stripe_correction_strength = None
        if "stripe_correction_strength" in payload:
            stripe_correction_strength = _coerce_float(
                payload["stripe_correction_strength"], "stripe_correction_strength"
            )
            if stripe_correction_strength < 0.0 or stripe_correction_strength > 1.0:
                raise ValueError("stripe_correction_strength must be in range 0.0..1.0")

        median_filter_enabled = (
            bool(payload["median_filter_enabled"])
            if "median_filter_enabled" in payload
            else None
        )
        median_kernel = None
        if "median_kernel" in payload:
            median_kernel = _coerce_int(payload["median_kernel"], "median_kernel")
            if median_kernel not in (3, 5, 7):
                raise ValueError("median_kernel must be one of: 3, 5, 7")

        with self.camera_lock:
            if refresh_code is not None:
                self.camera.set_refresh_rate(refresh_code)
            if sensor_resolution is not None:
                self.camera.set_resolution(sensor_resolution)
            if sensor_mode is not None:
                if sensor_mode == "chess":
                    self.camera.set_chess_mode()
                else:
                    self.camera.set_interleaved_mode()

        with self.state_lock:
            if refresh_code is not None:
                self.refresh_rate_code = refresh_code
            if sensor_resolution is not None:
                self.sensor_resolution = sensor_resolution
            if sensor_mode is not None:
                self.sensor_mode = sensor_mode
            if emissivity is not None:
                self.emissivity = emissivity
            if tr_offset is not None:
                self.tr_offset = tr_offset
            if palette is not None:
                self.palette = palette
            if interpolation is not None:
                self.interpolation = interpolation
            if display_enhancement_enabled is not None:
                self.display_enhancement_enabled = display_enhancement_enabled
            if auto_scale is not None:
                self.auto_scale = auto_scale
            if average_frames is not None:
                self.average_frames = average_frames
            if integration_time_seconds is not None:
                self.integration_time_seconds = integration_time_seconds
                if integration_time_seconds <= 0.0:
                    self._integration_samples = []
            if stripe_correction_enabled is not None:
                self.stripe_correction_enabled = stripe_correction_enabled
            if stripe_correction_strength is not None:
                self.stripe_correction_strength = stripe_correction_strength
            if median_filter_enabled is not None:
                self.median_filter_enabled = median_filter_enabled
            if median_kernel is not None:
                self.median_kernel = median_kernel
            if min_temp is not None:
                self.min_temp = min_temp
            if max_temp is not None:
                self.max_temp = max_temp
            if self.max_temp <= self.min_temp:
                raise ValueError("max_temp must be greater than min_temp")

        return self.get_state()


def create_app(backend: ThermalWebBackend) -> Flask:
    """Create the Flask application that serves the UI and streaming endpoints."""
    app = Flask(__name__, template_folder="templates")

    @app.get("/")
    def index() -> str:
        """Render the dashboard HTML page for the thermal camera UI."""
        return render_template("thermal_camera.html")

    @app.get("/api/state")
    def api_state():
        """Return the current backend state and live statistics as JSON."""
        include_status_registers = (
            request.args.get("include_status_registers", "false").lower()
            in {"1", "true", "yes", "on"}
        )
        with backend.state_lock:
            backend.status_register_polling_enabled = include_status_registers
        return jsonify(backend.get_state(include_status_registers=include_status_registers))

    @app.post("/api/control")
    def api_control():
        """Apply a JSON payload of control changes to the camera backend."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON body must be an object"}), 400
        try:
            state = backend.apply_controls(payload)
            return jsonify(state)
        except (TypeError, ValueError) as exc:
            LOGGER.exception("Failed to apply control payload: %s", exc)
            return jsonify({"error": str(exc)}), 400

    @app.get("/stream.mjpg")
    def stream():
        """Return a multipart MJPEG stream of the latest processed image."""

        def generate():
            """Yield JPEG frames for the browser to render as a live stream."""
            while True:
                frame = backend.latest_jpeg
                if frame is None:
                    time.sleep(0.02)
                    continue
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: "
                    + str(len(frame)).encode()
                    + b"\r\n\r\n"
                    + frame
                    + b"\r\n"
                )
                time.sleep(0.001)

        return Response(
            generate(), mimetype="multipart/x-mixed-replace; boundary=frame"
        )

    @app.get("/integrated.jpg")
    def integrated_image():
        """Return the time-integrated thermal image as a JPEG snapshot."""
        frame = backend.latest_integrated_jpeg
        if frame is None:
            frame = backend.latest_jpeg
        if frame is None:
            frame = backend._error_jpeg("No integrated image available yet")
        return Response(frame, mimetype="image/jpeg")

    return app


def main() -> int:
    """Run the thermal camera web UI using the configured sensor settings."""
    parser = argparse.ArgumentParser(description="MLX90640 Flask web frontend")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=5000, help="Bind port (default: 5000)"
    )
    parser.add_argument(
        "--refresh-rate-code",
        type=int,
        default=4,
        help="MLX90640 refresh-rate code 0..7 (default: 4 = 8Hz)",
    )
    parser.add_argument(
        "--average-frames",
        type=int,
        default=1,
        help="Average this many raw frames per output frame (default: 1, range: 1..32)",
    )
    parser.add_argument(
        "--integration-time-seconds",
        type=float,
        default=1.0,
        help="Average thermal frames over this duration for the separate integrated image (0..30s)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if args.average_frames < 1 or args.average_frames > 32:
        raise ValueError("--average-frames must be in range 1..32")
    if args.integration_time_seconds < 0.0 or args.integration_time_seconds > 30.0:
        raise ValueError("--integration-time-seconds must be in range 0.0..30.0")

    backend = ThermalWebBackend(
        i2c_address=0x33,
        refresh_rate_code=args.refresh_rate_code,
        average_frames=args.average_frames,
    )
    backend.integration_time_seconds = args.integration_time_seconds
    backend.start()
    app = create_app(backend)
    try:
        app.run(host=args.host, port=args.port, threaded=True)
        return 0
    finally:
        backend.stop()


if __name__ == "__main__":
    raise SystemExit(main())
