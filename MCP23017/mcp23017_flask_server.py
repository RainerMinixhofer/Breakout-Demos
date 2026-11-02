#!/usr/bin/env python
"""
Flask API server for MCP23017 over I2C.

Exposes:
- live register state
- pin/port state
- all configurable pin settings
- full register read/write access
- diagnostics and address scanning
- chip-id availability information
"""

from __future__ import annotations

import argparse
import atexit
import logging
import time
from threading import RLock
from typing import Any

from flask import Flask, jsonify, render_template_string, request
from werkzeug.exceptions import HTTPException

from mcp23017_lgpio import MCP23017

LOG = logging.getLogger("mcp23017-server")

REGISTER_MAP = {
    0x00: "IODIRA",
    0x01: "IODIRB",
    0x02: "IPOLA",
    0x03: "IPOLB",
    0x04: "GPINTENA",
    0x05: "GPINTENB",
    0x06: "DEFVALA",
    0x07: "DEFVALB",
    0x08: "INTCONA",
    0x09: "INTCONB",
    0x0A: "IOCON",
    0x0B: "IOCON",
    0x0C: "GPPUA",
    0x0D: "GPPUB",
    0x0E: "INTFA",
    0x0F: "INTFB",
    0x10: "INTCAPA",
    0x11: "INTCAPB",
    0x12: "GPIOA",
    0x13: "GPIOB",
    0x14: "OLATA",
    0x15: "OLATB",
}

REGISTER_NAME_TO_ADDR = {name: addr for addr, name in REGISTER_MAP.items()}


class DeviceContext:
    def __init__(self, backend: str, bus: int, address: int, flags: int):
        self.backend = backend
        self.bus = bus
        self.address = address
        self.flags = flags
        self.lock = RLock()
        self.started_at = time.time()
        self.request_count = 0
        self.i2c_errors = 0
        self.last_error = None
        self._sbc: Any | None = None
        self._device: MCP23017 | None = None
        self.pin_modes: dict[int, str] = {}

    def open(self) -> None:
        if self.backend == "lgpio":
            try:
                import lgpio as sbc
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "lgpio is not installed. Install with: python -m pip install ./lg-master/PY_LGPIO"
                ) from exc
            self._sbc = sbc
        elif self.backend == "rgpio":
            try:
                import rgpio
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "rgpio is not installed. Install with: python -m pip install ./lg-master/PY_RGPIO"
                ) from exc
            self._sbc = rgpio.sbc()
            if not self._sbc.connected:
                raise RuntimeError("rgpio backend selected but not connected to rgpiod")
        else:
            raise ValueError("backend must be 'lgpio' or 'rgpio'")

        self._device = MCP23017(self._sbc, self.bus, self.address, self.flags)
        LOG.info(
            "Connected to MCP23017 at bus=%d address=0x%02X backend=%s",
            self.bus,
            self.address,
            self.backend,
        )

    def close(self) -> None:
        if self._device is not None:
            try:
                self._device.close()
            finally:
                self._device = None
        if self.backend == "rgpio" and self._sbc is not None:
            try:
                self._sbc.stop()
            finally:
                self._sbc = None

    @property
    def device(self) -> MCP23017:
        if self._device is None:
            raise RuntimeError("device is not connected")
        return self._device

    def _record_error(self, exc: Exception) -> None:
        self.i2c_errors += 1
        self.last_error = str(exc)
        LOG.exception("I2C operation failed")

    def safe_call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            self._record_error(exc)
            raise

    def scan_mcp23017_addresses(self) -> list[int]:
        found = []
        sbc = self._sbc
        if sbc is None:
            raise RuntimeError("device is not connected")

        for addr in range(0x20, 0x28):
            handle = None
            try:
                handle = sbc.i2c_open(self.bus, addr, self.flags)
                sbc.i2c_read_byte_data(handle, 0x00)
                found.append(addr)
            except Exception:
                continue
            finally:
                if handle is not None:
                    try:
                        sbc.i2c_close(handle)
                    except Exception:
                        LOG.warning(
                            "Failed to close temporary scan handle for 0x%02X", addr
                        )
        return found

    def read_registers(self) -> dict[str, int]:
        values = {}
        for reg, name in REGISTER_MAP.items():
            values[name] = self.safe_call(self.device.read_register, reg)
        return values

    def read_state(self) -> dict[str, Any]:
        regs = self.read_registers()
        state = {
            "registers": regs,
            "ports": {
                "A": {
                    "direction": regs["IODIRA"],
                    "polarity_inversion": regs["IPOLA"],
                    "pullup": regs["GPPUA"],
                    "gpio": regs["GPIOA"],
                    "output_latch": regs["OLATA"],
                },
                "B": {
                    "direction": regs["IODIRB"],
                    "polarity_inversion": regs["IPOLB"],
                    "pullup": regs["GPPUB"],
                    "gpio": regs["GPIOB"],
                    "output_latch": regs["OLATB"],
                },
            },
            "pins": {},
        }

        for pin in range(16):
            port = "A" if pin < 8 else "B"
            bit = pin if pin < 8 else pin - 8
            direction = state["ports"][port]["direction"]
            polarity = state["ports"][port]["polarity_inversion"]
            pullup = state["ports"][port]["pullup"]
            gpio = state["ports"][port]["gpio"]
            latch = state["ports"][port]["output_latch"]
            pullup_enabled = bool(pullup & (1 << bit))
            input_mode = bool(direction & (1 << bit))
            auto_mode = "output" if not input_mode else "input"
            effective_mode = self.pin_modes.get(pin, auto_mode)
            state["pins"][str(pin)] = {
                "port": port,
                "bit": bit,
                "mode": effective_mode,
                "polarity_inverted": bool(polarity & (1 << bit)),
                "pullup_enabled": pullup_enabled,
                "level": 1 if (gpio & (1 << bit)) else 0,
                "latched_output_level": 1 if (latch & (1 << bit)) else 0,
            }
        return state


def parse_register(register: str) -> int:
    reg = register.strip().upper()
    if reg in REGISTER_NAME_TO_ADDR:
        return REGISTER_NAME_TO_ADDR[reg]
    try:
        value = int(reg, 0)
    except ValueError as exc:
        raise ValueError(
            "register must be a name like IODIRA or a number like 0x12"
        ) from exc
    if not 0x00 <= value <= 0x15:
        raise ValueError("register must be in range 0x00..0x15")
    return value


def read_required_json() -> dict[str, Any]:
    payload = request.get_json(silent=False)
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def create_app(ctx: DeviceContext) -> Flask:
    app = Flask(__name__)

    @app.before_request
    def _count_request():
        ctx.request_count += 1

    @app.errorhandler(ValueError)
    def _handle_value_error(err):
        return jsonify({"error": "bad_request", "message": str(err)}), 400

    @app.errorhandler(RuntimeError)
    def _handle_runtime_error(err):
        return jsonify({"error": "runtime_error", "message": str(err)}), 500

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        return jsonify({"error": err.name, "message": err.description}), err.code

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        LOG.exception("Unhandled server error")
        return jsonify({"error": "internal_server_error", "message": str(err)}), 500

    @app.get("/")
    def root():
        return jsonify(
            {
                "name": "mcp23017-flask-server",
                "endpoints": [
                    "/health",
                    "/ui",
                    "/api/v1/info",
                    "/api/v1/chip-id",
                    "/api/v1/settings",
                    "/api/v1/diagnostics",
                    "/api/v1/scan",
                    "/api/v1/state",
                    "/api/v1/registers",
                    "/api/v1/registers/<register>",
                    "/api/v1/pins/<pin>",
                    "/api/v1/pins/<pin>/mode",
                    "/api/v1/pins/<pin>/pullup",
                    "/api/v1/pins/<pin>/polarity",
                    "/api/v1/pins/<pin>/level",
                ],
            }
        )

    @app.get("/ui")
    def ui_page():
        return render_template_string(
            """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MCP23017 Dashboard</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #111827;
      --panel-alt: #1f2937;
      --muted: #94a3b8;
      --text: #e5e7eb;
      --accent: #22c55e;
      --danger: #ef4444;
      --warning: #f59e0b;
      --border: #374151;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: Arial, sans-serif; background: var(--bg); color: var(--text);
    }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 24px; }
    .head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
    .head h1 { margin: 0; font-size: 2rem; }
    .status { padding: 8px 12px; border-radius: 999px; background: rgba(34,197,94,.15); color: #bbf7d0; border: 1px solid rgba(34,197,94,.35); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
    .pin-card {
      background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 12px;
    }
    .pin-header { display: flex; justify-content: space-between; align-items: center; }
    .pin-num { font-weight: bold; font-size: 1.1rem; }
    .led { width: 14px; height: 14px; border-radius: 50%; background: var(--danger); box-shadow: 0 0 10px rgba(239,68,68,.7); }
    .led.on { background: var(--accent); box-shadow: 0 0 12px rgba(34,197,94,.9); }
    .meta { color: var(--muted); font-size: 0.82rem; margin: 8px 0 10px 0; }
    select, button, input[type="checkbox"] { font: inherit; }
    select, button {
      width: 100%; margin-top: 6px; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border);
      background: var(--panel-alt); color: var(--text);
    }
    .row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 10px; }
    .toggle { display: flex; align-items: center; gap: 6px; color: var(--text); }
    .pill { display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 0.72rem; }
    .output { background: rgba(34,197,94,.16); color: #bbf7d0; }
    .input { background: rgba(59,130,246,.14); color: #bfdbfe; }
    .highz { background: rgba(245,158,11,.14); color: #fcd34d; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h1>MCP23017 Dashboard</h1>
      <div id="chip-status" class="status">Loading…</div>
    </div>
    <div id="pin-grid" class="grid"></div>
  </div>

  <script>
    const pinGrid = document.getElementById('pin-grid');
    const chipStatus = document.getElementById('chip-status');

    function modeClass(mode) {
      if (mode === 'output') return 'output';
      if (mode === 'high-z') return 'highz';
      return 'input';
    }

    function pinCard(pin) {
      const card = document.createElement('div');
      card.className = 'pin-card';
      const mode = pin.mode || 'input';
      const active = pin.level === 1;
      const label = pin.mode === 'high-z' ? 'high-z' : pin.mode;
      card.innerHTML = `
        <div class="pin-header">
          <div class="pin-num">Pin ${pin.port}${pin.bit}</div>
          <div class="led ${active ? 'on' : ''}" title="level ${pin.level}"></div>
        </div>
        <div class="meta">Port ${pin.port} / bit ${pin.bit}</div>
        <div class="row">
          <span class="pill ${modeClass(mode)}">${label}</span>
          <span class="pullup-text">${mode === 'input' ? (pin.pullup_enabled ? 'pullup' : 'no pullup') : 'n/a'}</span>
        </div>
        <label class="row" style="justify-content:space-between;">
          <span>Mode</span>
          <select data-pin="${pin.pin}" data-action="mode">
            <option value="output" ${mode === 'output' ? 'selected' : ''}>output</option>
            <option value="input" ${mode === 'input' ? 'selected' : ''}>input</option>
            <option value="high-z" ${mode === 'high-z' ? 'selected' : ''}>high-z</option>
          </select>
        </label>
        <label class="row toggle" style="${mode === 'input' ? '' : 'opacity:0.45;'}">
          <span>Pull-up</span>
          <input data-pin="${pin.pin}" data-action="pullup" type="checkbox" ${pin.pullup_enabled ? 'checked' : ''} ${mode === 'input' ? '' : 'disabled'}>
        </label>
        <label class="row toggle">
          <span>Output level</span>
          <button data-pin="${pin.pin}" data-action="level" data-level="${active ? 0 : 1}" ${mode !== 'output' ? 'disabled' : ''} style="${mode !== 'output' ? 'opacity:0.45; cursor:not-allowed;' : ''}">${active ? 'Set LOW' : 'Set HIGH'}</button>
        </label>
      `;
      return card;
    }

    async function fetchJson(url, options = {}) {
      const response = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.message || 'request failed');
      }
      return data;
    }

    const pinMap = new Map();

    function activeModeSelectInfo() {
      const active = document.activeElement;
      if (!(active instanceof HTMLSelectElement)) return null;
      if (!active.matches('[data-action="mode"]')) return null;
      return {
        pin: Number(active.dataset.pin),
        value: active.value,
        element: active,
      };
    }

    async function refreshState() {
      try {
        const info = await fetchJson('/api/v1/info');
        const state = await fetchJson('/api/v1/state');
        const pins = Object.entries(state.pins).map(([pin, values]) => ({ pin: Number(pin), ...values }));
        const focusedSelect = activeModeSelectInfo();
        chipStatus.textContent = `${info.chip} @ ${info.address} / ${info.backend}`;

        pins.forEach(pin => {
          let card = pinMap.get(pin.pin);
          if (!card) {
            card = pinCard(pin);
            pinMap.set(pin.pin, card);
            pinGrid.appendChild(card);
          }

          const mode = pin.mode || 'input';
          const level = pin.level === 1;
          const pill = card.querySelector('.pill');
          const led = card.querySelector('.led');
          const modeSelect = card.querySelector('[data-action="mode"]');
          const pullupCheck = card.querySelector('[data-action="pullup"]');
          const pullupText = card.querySelector('.pullup-text');
          const levelButton = card.querySelector('[data-action="level"]');

          const displayedMode = mode === 'high-z' ? 'high-z' : mode;
          pill.textContent = displayedMode;
          pill.className = `pill ${modeClass(displayedMode)}`;
          led.classList.toggle('on', level);
          if (!focusedSelect || focusedSelect.pin !== pin.pin) {
            modeSelect.value = displayedMode;
          }
          const isInputMode = displayedMode === 'input';
          const isOutput = displayedMode === 'output';
          pullupCheck.checked = !!pin.pullup_enabled;
          pullupCheck.disabled = !isInputMode;
          if (pullupText) {
            pullupText.textContent = isInputMode ? (pin.pullup_enabled ? 'pullup' : 'no pullup') : 'n/a';
          }
          const toggleRow = pullupCheck.closest('.toggle');
          if (toggleRow) {
            toggleRow.style.opacity = isInputMode ? '1' : '0.45';
          }
          levelButton.disabled = !isOutput;
          levelButton.style.opacity = isOutput ? '1' : '0.45';
          levelButton.style.cursor = isOutput ? 'pointer' : 'not-allowed';
          levelButton.dataset.level = isOutput ? (level ? 0 : 1) : 0;
          levelButton.textContent = level ? 'Set LOW' : 'Set HIGH';
          levelButton.title = `Set pin ${pin.pin} to ${level ? 'LOW' : 'HIGH'}`;
          const label = card.querySelector('.meta');
          label.textContent = `Port ${pin.port} / bit ${pin.bit}`;
        });

        for (const [pin, card] of pinMap.entries()) {
          if (!pins.some(p => p.pin === pin)) {
            pinGrid.removeChild(card);
            pinMap.delete(pin);
          }
        }

        for (const el of document.querySelectorAll('[data-action="mode"]')) {
          el.onchange = async function() {
            const pin = Number(this.dataset.pin);
            const mode = this.value;
            await fetchJson(`/api/v1/pins/${pin}/mode`, { method: 'PUT', body: JSON.stringify({ mode }) });
            await refreshState();
          };
        }
        for (const el of document.querySelectorAll('[data-action="pullup"]')) {
          el.onchange = async function() {
            const pin = Number(this.dataset.pin);
            await fetchJson(`/api/v1/pins/${pin}/pullup`, { method: 'PUT', body: JSON.stringify({ enabled: this.checked }) });
            await refreshState();
          };
        }
        for (const el of document.querySelectorAll('[data-action="level"]')) {
          el.onclick = async function() {
            const pin = Number(this.dataset.pin);
            const level = Number(this.dataset.level);
            await fetchJson(`/api/v1/pins/${pin}/level`, { method: 'PUT', body: JSON.stringify({ level }) });
            await refreshState();
          };
        }
      } catch (err) {
        chipStatus.textContent = 'Connection error';
        chipStatus.style.background = 'rgba(239,68,68,.15)';
        chipStatus.style.color = '#fecaca';
        console.error(err);
      }
    }

    refreshState();
    setInterval(refreshState, 1500);
  </script>
</body>
</html>
"""
        )

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/api/v1/info")
    def info():
        return jsonify(
            {
                "chip": "MCP23017",
                "backend": ctx.backend,
                "bus": ctx.bus,
                "address": "0x{:02X}".format(ctx.address),
                "flags": ctx.flags,
                "started_at_unix": ctx.started_at,
            }
        )

    @app.get("/api/v1/chip-id")
    def chip_id():
        return jsonify(
            {
                "available": False,
                "reason": "MCP23017 does not expose a dedicated chip-id register.",
                "detection_method": "device probed via I2C register transactions",
            }
        )

    @app.get("/api/v1/settings")
    def settings():
        return jsonify(
            {
                "address_range": {"min": "0x20", "max": "0x27"},
                "pin_range": {"min": 0, "max": 15},
                "pin_mode_values": {
                    "input": 1,
                    "output": 0,
                    "high-z": "input-no-pullup",
                },
                "pin_level_values": [0, 1],
                "boolean_settings": ["pullup_enabled", "polarity_inverted"],
                "high_z_available": True,
                "registers": [
                    {"name": name, "address": "0x{:02X}".format(addr), "width_bits": 8}
                    for addr, name in REGISTER_MAP.items()
                ],
            }
        )

    @app.get("/api/v1/diagnostics")
    def diagnostics():
        return jsonify(
            {
                "uptime_seconds": int(time.time() - ctx.started_at),
                "request_count": ctx.request_count,
                "i2c_error_count": ctx.i2c_errors,
                "last_i2c_error": ctx.last_error,
                "current_bus": ctx.bus,
                "current_address": "0x{:02X}".format(ctx.address),
            }
        )

    @app.get("/api/v1/scan")
    def scan():
        with ctx.lock:
            found = ctx.scan_mcp23017_addresses()
        return jsonify(
            {
                "bus": ctx.bus,
                "addresses": ["0x{:02X}".format(addr) for addr in found],
                "count": len(found),
            }
        )

    @app.get("/api/v1/state")
    def state():
        with ctx.lock:
            data = ctx.read_state()
        return jsonify(data)

    @app.get("/api/v1/registers")
    def registers():
        with ctx.lock:
            data = ctx.read_registers()
        return jsonify(data)

    @app.get("/api/v1/registers/<register>")
    def register_get(register: str):
        reg = parse_register(register)
        name = REGISTER_MAP[reg]
        with ctx.lock:
            value = ctx.safe_call(ctx.device.read_register, reg)
        return jsonify(
            {"register": name, "address": "0x{:02X}".format(reg), "value": value}
        )

    @app.put("/api/v1/registers/<register>")
    def register_set(register: str):
        reg = parse_register(register)
        body = read_required_json()
        if "value" not in body:
            raise ValueError("JSON body must include 'value'")
        value = int(body["value"])
        if not 0 <= value <= 255:
            raise ValueError("register value must be in range 0..255")
        with ctx.lock:
            ctx.safe_call(ctx.device.write_register, reg, value)
            updated = ctx.safe_call(ctx.device.read_register, reg)
        return jsonify(
            {
                "register": REGISTER_MAP[reg],
                "address": "0x{:02X}".format(reg),
                "value": updated,
            }
        )

    @app.get("/api/v1/pins/<int:pin>")
    def pin_get(pin: int):
        if not 0 <= pin <= 15:
            raise ValueError("pin must be in range 0..15")
        with ctx.lock:
            data = ctx.read_state()["pins"][str(pin)]
        return jsonify(data)

    @app.put("/api/v1/pins/<int:pin>/mode")
    def pin_mode(pin: int):
        if not 0 <= pin <= 15:
            raise ValueError("pin must be in range 0..15")
        body = read_required_json()
        mode = body.get("mode")
        if mode not in ("input", "output", "high-z"):
            raise ValueError("mode must be 'input', 'output', or 'high-z'")
        mode_value = MCP23017.INPUT if mode in ("input", "high-z") else MCP23017.OUTPUT
        with ctx.lock:
            ctx.safe_call(ctx.device.set_pin_mode, pin, mode_value)
            if mode in ("output", "high-z"):
                ctx.safe_call(ctx.device.set_pullup, pin, False)
            ctx.pin_modes[pin] = mode
        return jsonify({"pin": pin, "mode": mode})

    @app.put("/api/v1/pins/<int:pin>/pullup")
    def pin_pullup(pin: int):
        if not 0 <= pin <= 15:
            raise ValueError("pin must be in range 0..15")
        body = read_required_json()
        if "enabled" not in body:
            raise ValueError("JSON body must include 'enabled'")
        enabled = bool(body["enabled"])
        with ctx.lock:
            ctx.safe_call(ctx.device.set_pullup, pin, enabled)
        return jsonify({"pin": pin, "pullup_enabled": enabled})

    @app.put("/api/v1/pins/<int:pin>/polarity")
    def pin_polarity(pin: int):
        if not 0 <= pin <= 15:
            raise ValueError("pin must be in range 0..15")
        body = read_required_json()
        if "inverted" not in body:
            raise ValueError("JSON body must include 'inverted'")
        inverted = bool(body["inverted"])
        with ctx.lock:
            ctx.safe_call(ctx.device.set_polarity_inversion, pin, inverted)
        return jsonify({"pin": pin, "polarity_inverted": inverted})

    @app.put("/api/v1/pins/<int:pin>/level")
    def pin_level(pin: int):
        if not 0 <= pin <= 15:
            raise ValueError("pin must be in range 0..15")
        body = read_required_json()
        if "level" not in body:
            raise ValueError("JSON body must include 'level'")
        level = int(body["level"])
        if level not in (0, 1):
            raise ValueError("level must be 0 or 1")
        with ctx.lock:
            ctx.safe_call(ctx.device.write_pin, pin, level)
            applied = ctx.safe_call(ctx.device.read_pin, pin)
        return jsonify({"pin": pin, "level": applied})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP23017 Flask server")
    parser.add_argument("--backend", choices=["lgpio", "rgpio"], default="lgpio")
    parser.add_argument(
        "--bus", type=int, default=1, help="I2C bus number (default: 1)"
    )
    parser.add_argument(
        "--address",
        type=lambda x: int(x, 0),
        default=0x20,
        help="MCP23017 I2C address (default: 0x20)",
    )
    parser.add_argument("--flags", type=int, default=0, help="I2C open flags")
    parser.add_argument("--host", default="0.0.0.0", help="Flask bind host")
    parser.add_argument("--port", type=int, default=5000, help="Flask bind port")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ctx = DeviceContext(args.backend, args.bus, args.address, args.flags)
    ctx.open()
    atexit.register(ctx.close)

    app = create_app(ctx)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
