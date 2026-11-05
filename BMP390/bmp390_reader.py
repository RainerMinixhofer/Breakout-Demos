#!/usr/bin/env python3
"""Read and monitor a BMP390 via CLI or Flask dashboard."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import threading
import time
from collections import deque


DEFAULT_I2C_ADDRESS = 0x77
DEFAULT_READ_TIMEOUT = 2.0
DEFAULT_INTERVAL = 1.0
SIX_HOURS = dt.timedelta(hours=6)


def parse_i2c_address(value: str) -> int:
    try:
        address = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"Invalid I2C address '{value}'. Use decimal or hex (for example 0x77)."
        ) from error
    if not 0x03 <= address <= 0x77:
        raise argparse.ArgumentTypeError(
            f"I2C address out of range: {hex(address)} (expected 0x03..0x77)."
        )
    return address


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read BMP390 sensor data over I2C or SPI."
    )
    parser.add_argument(
        "--bus",
        choices=("i2c", "spi"),
        default="i2c",
        help="Bus type used to communicate with the sensor (default: i2c).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"Seconds between samples (default: {DEFAULT_INTERVAL}).",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=0,
        help="Number of samples to read (0 means run forever).",
    )
    parser.add_argument(
        "--sea-level-hpa",
        type=float,
        default=None,
        help="Optional sea-level pressure in hPa for altitude calculation.",
    )
    parser.add_argument(
        "--spi-cs-pin",
        default="D5",
        help="SPI chip-select pin name from the board module (default: D5).",
    )
    parser.add_argument(
        "--i2c-address",
        type=parse_i2c_address,
        default=DEFAULT_I2C_ADDRESS,
        help="I2C sensor address (default: 0x77). Common BMP390 values are 0x76 or 0x77.",
    )
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=DEFAULT_READ_TIMEOUT,
        help=f"Timeout in seconds for one sensor conversion/read cycle (default: {DEFAULT_READ_TIMEOUT}).",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start the Flask-based web dashboard with plots for the last 6 hours.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Hostname for the Flask web interface (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port for the Flask web interface (default: 5000).",
    )
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be > 0")
    if args.samples < 0:
        parser.error("--samples must be >= 0")
    if args.read_timeout <= 0:
        parser.error("--read-timeout must be > 0")
    return args


def create_sensor(args: argparse.Namespace):
    try:
        import adafruit_bmp3xx
        import board
    except ImportError as error:
        raise RuntimeError(
            "Missing dependencies. Install with: pip install adafruit-circuitpython-bmp3xx"
        ) from error

    if args.bus == "i2c":
        i2c = board.I2C()
        if hasattr(i2c, "try_lock") and hasattr(i2c, "scan"):
            scan_result: list[int] | None = None
            if i2c.try_lock():
                try:
                    scan_result = list(i2c.scan())
                finally:
                    i2c.unlock()
            if scan_result is not None and args.i2c_address not in scan_result:
                found = ", ".join(hex(addr) for addr in scan_result) or "none"
                raise RuntimeError(
                    f"I2C address {hex(args.i2c_address)} not found on bus. "
                    f"Detected addresses: {found}."
                )
        return adafruit_bmp3xx.BMP3XX_I2C(i2c, address=args.i2c_address)

    try:
        import digitalio
    except ImportError as error:
        raise RuntimeError(
            "Missing dependency for SPI GPIO access. Install with: pip install adafruit-circuitpython-bmp3xx"
        ) from error

    if not hasattr(board, args.spi_cs_pin):
        raise RuntimeError(
            f"Invalid SPI CS pin '{args.spi_cs_pin}'. "
            "Use a valid pin name from the board module (for example D5, CE0, CE1)."
        )

    cs_pin = getattr(board, args.spi_cs_pin)
    spi = board.SPI()
    cs = digitalio.DigitalInOut(cs_pin)
    return adafruit_bmp3xx.BMP3XX_SPI(spi, cs)


def read_sample(sensor, timeout_s: float) -> tuple[float, float]:
    import adafruit_bmp3xx

    status_reg = adafruit_bmp3xx._REGISTER_STATUS
    control_reg = adafruit_bmp3xx._REGISTER_CONTROL
    cmd_rdy_mask = 0x10
    drdy_both_mask = 0x60
    op_mode_mask = 0x30

    deadline = time.monotonic() + timeout_s
    while True:
        status = sensor._read_byte(status_reg)
        if status & cmd_rdy_mask:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Timed out waiting for BMP390 command-ready state before starting measurement "
                f"(status=0x{status:02x})."
            )
        time.sleep(sensor._wait_time)

    sensor._write_register_byte(adafruit_bmp3xx._REGISTER_CONTROL, 0x13)

    deadline = time.monotonic() + timeout_s
    last_status = 0
    last_control = 0
    while True:
        last_status = sensor._read_byte(status_reg)
        last_control = sensor._read_byte(control_reg)
        op_mode = (last_control & op_mode_mask) >> 4

        if (last_status & drdy_both_mask) == drdy_both_mask or op_mode == 0:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Timed out waiting for BMP390 measurement to complete "
                f"(status=0x{last_status:02x}, pwr_ctrl=0x{last_control:02x})."
            )
        time.sleep(sensor._wait_time)

    data = sensor._read_register(adafruit_bmp3xx._REGISTER_PRESSUREDATA, 6)
    adc_p = data[2] << 16 | data[1] << 8 | data[0]
    adc_t = data[5] << 16 | data[4] << 8 | data[3]

    t1, t2, t3 = sensor._temp_calib
    pd1 = adc_t - t1
    pd2 = pd1 * t2
    temperature = pd2 + (pd1 * pd1) * t3

    p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11 = sensor._pressure_calib
    pd1 = p6 * temperature
    pd2 = p7 * temperature**2.0
    pd3 = p8 * temperature**3.0
    po1 = p5 + pd1 + pd2 + pd3

    pd1 = p2 * temperature
    pd2 = p3 * temperature**2.0
    pd3 = p4 * temperature**3.0
    po2 = adc_p * (p1 + pd1 + pd2 + pd3)

    pd1 = adc_p**2.0
    pd2 = p9 + p10 * temperature
    pd3 = pd1 * pd2
    pd4 = pd3 + p11 * adc_p**3.0

    pressure_pa = po1 + po2 + pd4
    pressure_hpa = pressure_pa / 100.0
    return temperature, pressure_hpa


def calculate_altitude_m(pressure_hpa: float, sea_level_hpa: float) -> float:
    return 44330.0 * (1.0 - (pressure_hpa / sea_level_hpa) ** 0.1903)


def read_console(args: argparse.Namespace) -> int:
    sensor = create_sensor(args)
    if args.sea_level_hpa is not None:
        sensor.sea_level_pressure = args.sea_level_hpa

    sensor.pressure_oversampling = 1
    sensor.temperature_oversampling = 1

    print("timestamp,temperature_c,pressure_hpa,altitude_m", flush=True)
    count = 0
    try:
        while True:
            timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
            try:
                temperature, pressure = read_sample(sensor, args.read_timeout)
                altitude = calculate_altitude_m(pressure, sensor.sea_level_pressure)
            except TimeoutError as error:
                print(f"ERROR: {error}", file=sys.stderr)
                print(
                    f"Hint: verify wiring and I2C address (currently {hex(args.i2c_address)}; "
                    "BMP390 is usually 0x76 or 0x77).",
                    file=sys.stderr,
                )
                return 2
            except OSError as error:
                print(f"ERROR: Read failed: {error}", file=sys.stderr)
                return 2
            except RuntimeError as error:
                print(f"ERROR: Sensor returned invalid data: {error}", file=sys.stderr)
                return 2

            print(f"{timestamp},{temperature:.3f},{pressure:.3f},{altitude:.3f}", flush=True)
            count += 1
            if args.samples and count >= args.samples:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        return 130


def create_web_app(args: argparse.Namespace):
    from flask import Flask, jsonify, render_template_string, request

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    sensor = create_sensor(args)
    if args.sea_level_hpa is not None:
        sensor.sea_level_pressure = args.sea_level_hpa
    sensor.pressure_oversampling = 1
    sensor.temperature_oversampling = 1

    history = deque()
    history_lock = threading.Lock()
    stop_event = threading.Event()

    def poll_sensor() -> None:
        while not stop_event.is_set():
            try:
                temperature, pressure = read_sample(sensor, args.read_timeout)
                altitude = calculate_altitude_m(pressure, sensor.sea_level_pressure)
                sample = {
                    "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "temperature": float(temperature),
                    "pressure": float(pressure),
                    "altitude": float(altitude),
                }
                with history_lock:
                    history.append(sample)
                    cutoff = dt.datetime.now(dt.timezone.utc) - SIX_HOURS
                    while history and dt.datetime.fromisoformat(history[0]["timestamp"]) < cutoff:
                        history.popleft()
            except Exception as exc:  # noqa: BLE001
                timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
                with history_lock:
                    history.append({
                        "timestamp": timestamp,
                        "temperature": None,
                        "pressure": None,
                        "altitude": None,
                        "error": str(exc),
                    })
            time.sleep(args.interval)

    worker = threading.Thread(target=poll_sensor, daemon=True)
    worker.start()

    @app.route("/")
    def index():
        return render_template_string(
            """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BMP390 Monitor</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }
    .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
    .grid { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 20px; }
    .panel { background: rgba(15, 23, 42, 0.92); border: 1px solid #334155; border-radius: 12px; padding: 18px; box-shadow: 0 8px 24px rgba(0,0,0,0.18); }
    h1 { margin-top: 0; }
    .stats { display: grid; grid-template-columns: repeat(3, minmax(120px,1fr)); gap: 12px; margin-bottom: 18px; }
    .stat { background: rgba(30,41,59,0.8); border-radius: 10px; padding: 12px; }
    .stat-label { display: block; font-size: 12px; opacity: 0.72; margin-bottom: 8px; }
    .stat-value { font-size: 1.4rem; font-weight: bold; }
    .charts { display: grid; gap: 18px; }
    canvas { width: 100%; height: 180px; background: rgba(15,23,42,0.8); border-radius: 8px; border: 1px solid rgba(148,163,184,0.3); }
    .settings { display: grid; gap: 12px; }
    label { display: flex; flex-direction: column; gap: 6px; font-size: 0.9rem; }
    input, select, button { font: inherit; }
    input, select { padding: 8px 10px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: #e2e8f0; }
    button { padding: 10px 16px; border: none; border-radius: 8px; background: #22c55e; color: #06210d; font-weight: bold; cursor: pointer; }
    .error { color: #fca5a5; margin-top: 10px; min-height: 1.2rem; }
    @media (max-width: 860px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="container">
    <h1>BMP390 Monitor</h1>
    <div class="grid">
      <div class="panel">
        <div class="stats" id="stats"></div>
        <div class="charts">
          <div>
            <h3>Temperature (°C)</h3>
            <canvas id="tempChart" width="800" height="180"></canvas>
          </div>
          <div>
            <h3>Pressure (hPa)</h3>
            <canvas id="pressureChart" width="800" height="180"></canvas>
          </div>
          <div>
            <h3>Altitude (m)</h3>
            <canvas id="altitudeChart" width="800" height="180"></canvas>
          </div>
        </div>
      </div>
      <div class="panel">
        <h2>Settings</h2>
        <div class="settings">
          <label>
            Pressure oversampling
            <select id="pressureOversampling">
              <option value="1">1x</option>
              <option value="2">2x</option>
              <option value="4">4x</option>
              <option value="8">8x</option>
              <option value="16">16x</option>
              <option value="32">32x</option>
            </select>
          </label>
          <label>
            Temperature oversampling
            <select id="temperatureOversampling">
              <option value="1">1x</option>
              <option value="2">2x</option>
              <option value="4">4x</option>
              <option value="8">8x</option>
              <option value="16">16x</option>
              <option value="32">32x</option>
            </select>
          </label>
          <label>
            IIR filter coefficient
            <select id="filterCoefficient">
              <option value="0">0</option>
              <option value="2">2</option>
              <option value="4">4</option>
              <option value="8">8</option>
              <option value="16">16</option>
              <option value="32">32</option>
              <option value="64">64</option>
              <option value="128">128</option>
            </select>
          </label>
          <label>
            Sea level pressure (hPa)
            <input id="seaLevel" type="number" min="800" max="1100" step="0.1" value="1013.25" />
          </label>
          <label>
            Poll interval (s)
            <input id="interval" type="number" min="0.5" max="60" step="0.5" value="1" />
          </label>
          <button id="saveSettings">Apply settings</button>
          <div id="settingsError" class="error"></div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const state = { data: [] };
    const sixHoursMs = 6 * 60 * 60 * 1000;

    function isoToMs(ts) { return new Date(ts).getTime(); }

    function filterLast6Hours(series) {
      const cutoff = Date.now() - sixHoursMs;
      return series.filter((point) => isoToMs(point.timestamp) >= cutoff);
    }

    function setupChart(canvas, seriesKey, strokeStyle) {
      const ctx = canvas.getContext('2d');
      return (points) => {
        const width = canvas.width;
        const height = canvas.height;
        ctx.clearRect(0, 0, width, height);
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.35)';
        ctx.lineWidth = 1;

        for (let i = 0; i < 5; i++) {
          const y = (height / 5) * i;
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(width, y);
          ctx.stroke();
        }

        if (!points.length) {
          ctx.fillStyle = '#94a3b8';
          ctx.font = '12px sans-serif';
          ctx.fillText('No data yet', 12, 18);
          return;
        }

        const values = points.map((p) => p[seriesKey]).filter((v) => v !== null && v !== undefined);
        if (!values.length) return;

        const min = Math.min(...values);
        const max = Math.max(...values);
        const range = max - min || 1;
        const paddedMin = min - range * 0.1;
        const paddedMax = max + range * 0.1;

        ctx.beginPath();
        points.forEach((point, index) => {
          const v = point[seriesKey];
          if (v === null || v === undefined) return;
          const x = (index / Math.max(points.length - 1, 1)) * width;
          const y = height - ((v - paddedMin) / (paddedMax - paddedMin || 1)) * height;
          if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.strokeStyle = strokeStyle;
        ctx.lineWidth = 2;
        ctx.stroke();

        ctx.fillStyle = '#e2e8f0';
        ctx.font = '12px sans-serif';
        ctx.fillText(`${paddedMin.toFixed(1)}`, 8, height - 8);
        ctx.fillText(`${paddedMax.toFixed(1)}`, 8, 18);
      };
    }

    const tempChart = setupChart(document.getElementById('tempChart'), 'temperature', '#60a5fa');
    const pressureChart = setupChart(document.getElementById('pressureChart'), 'pressure', '#a78bfa');
    const altitudeChart = setupChart(document.getElementById('altitudeChart'), 'altitude', '#34d399');

    function renderStats(points) {
      const latest = points[points.length - 1];
      const stats = document.getElementById('stats');
      if (!latest) {
        stats.innerHTML = '<div class="stat"><span class="stat-label">Status</span><span class="stat-value">Waiting</span></div>';
        return;
      }
      stats.innerHTML = `
        <div class="stat"><span class="stat-label">Temperature</span><span class="stat-value">${latest.temperature !== null ? `${latest.temperature.toFixed(2)} °C` : 'N/A'}</span></div>
        <div class="stat"><span class="stat-label">Pressure</span><span class="stat-value">${latest.pressure !== null ? `${latest.pressure.toFixed(2)} hPa` : 'N/A'}</span></div>
        <div class="stat"><span class="stat-label">Altitude</span><span class="stat-value">${latest.altitude !== null ? `${latest.altitude.toFixed(2)} m` : 'N/A'}</span></div>
      `;
    }

    function render() {
      const points = filterLast6Hours(state.data);
      tempChart(points);
      pressureChart(points);
      altitudeChart(points);
      renderStats(points);
    }

    async function refreshData() {
      const response = await fetch('/api/data');
      const data = await response.json();
      state.data = data.points || [];
      render();
    }

    async function refreshSettings() {
      const response = await fetch('/api/settings');
      const data = await response.json();
      document.getElementById('pressureOversampling').value = String(data.pressure_oversampling ?? 1);
      document.getElementById('temperatureOversampling').value = String(data.temperature_oversampling ?? 1);
      document.getElementById('filterCoefficient').value = String(data.filter_coefficient ?? 0);
      document.getElementById('seaLevel').value = String(data.sea_level_pressure ?? 1013.25);
      document.getElementById('interval').value = String(data.interval ?? 1);
    }

    document.getElementById('saveSettings').addEventListener('click', async () => {
      const payload = {
        pressure_oversampling: Number(document.getElementById('pressureOversampling').value),
        temperature_oversampling: Number(document.getElementById('temperatureOversampling').value),
        filter_coefficient: Number(document.getElementById('filterCoefficient').value),
        sea_level_pressure: Number(document.getElementById('seaLevel').value),
        interval: Number(document.getElementById('interval').value),
      };
      const errorEl = document.getElementById('settingsError');
      try {
        const response = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Settings update failed.');
        errorEl.textContent = 'Settings updated.';
        setTimeout(() => { errorEl.textContent = ''; }, 1500);
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });

    refreshSettings();
    refreshData();
    setInterval(refreshData, 2000);
  </script>
</body>
</html>
            """
        )

    @app.route("/api/data")
    def api_data():
        cutoff = dt.datetime.now(dt.timezone.utc) - SIX_HOURS
        with history_lock:
            filtered = [
                sample for sample in history if dt.datetime.fromisoformat(sample["timestamp"]) >= cutoff
            ]
        return jsonify({"points": list(filtered)})

    @app.route("/api/settings", methods=["GET", "POST"])
    def api_settings():
        nonlocal args
        if request.method == "GET":
            return jsonify({
                "pressure_oversampling": int(sensor.pressure_oversampling),
                "temperature_oversampling": int(sensor.temperature_oversampling),
                "filter_coefficient": int(sensor.filter_coefficient),
                "sea_level_pressure": float(sensor.sea_level_pressure),
                "interval": float(args.interval),
            })

        payload = request.get_json(silent=True) or {}
        try:
            if "pressure_oversampling" in payload:
                sensor.pressure_oversampling = int(payload["pressure_oversampling"])
            if "temperature_oversampling" in payload:
                sensor.temperature_oversampling = int(payload["temperature_oversampling"])
            if "filter_coefficient" in payload:
                sensor.filter_coefficient = int(payload["filter_coefficient"])
            if "sea_level_pressure" in payload:
                sensor.sea_level_pressure = float(payload["sea_level_pressure"])
            if "interval" in payload:
                args.interval = max(0.5, float(payload["interval"]))
        except (TypeError, ValueError) as exc:
            return jsonify({"error": f"Invalid setting: {exc}"}), 400
        return jsonify({"ok": True})

    return app


def main() -> int:
    args = parse_args()
    try:
        if args.web:
            app = create_web_app(args)
            app.run(host=args.host, port=args.port, debug=False, threaded=True)
            return 0
        return read_console(args)
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"ERROR: Sensor initialization failed: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"ERROR: Bus communication failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
