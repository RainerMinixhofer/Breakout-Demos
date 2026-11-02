import atexit
import math
import os
import threading
import time
from dataclasses import dataclass

from flask import Flask, jsonify, render_template, request

try:
    import lgpio
except ImportError:  # pragma: no cover - only on a real Raspberry Pi
    lgpio = None

try:
    import serial
except ImportError:  # pragma: no cover - optional dependency
    serial = None


class GPIOAdapter:
    BCM = 1
    INPUT = 0
    OUTPUT = 1
    LOW = 0
    HIGH = 1

    def __init__(self):
        self._chip = int(os.getenv("LGPIO_CHIP", "0"))
        self._handle = None
        self._claimed: dict[int, int] = {}
        self.available = False
        self._connect()

    def _connect(self):
        if lgpio is None:
            self.available = False
            return
        try:
            self._handle = lgpio.gpiochip_open(self._chip)
            self.available = self._handle is not None and self._handle >= 0
        except Exception:
            self._handle = None
            self.available = False

    def setmode(self, _mode):
        if self._handle is None:
            raise RuntimeError("lgpio is not available on this system")

    def setwarnings(self, _enabled):
        return None

    def _release_if_claimed(self, pin):
        if self._handle is None:
            raise RuntimeError("lgpio is not available on this system")
        if pin in self._claimed:
            try:
                lgpio.gpio_free(self._handle, pin)
            except Exception:
                pass
            self._claimed.pop(pin, None)

    def _claim_output(self, pin, initial_level):
        if self._handle is None:
            raise RuntimeError("lgpio is not available on this system")
        try:
            lgpio.gpio_claim_output(self._handle, pin, initial_level)
        except TypeError:
            lgpio.gpio_claim_output(self._handle, 0, pin, initial_level)
        self._claimed[pin] = self.OUTPUT

    def _claim_input(self, pin):
        if self._handle is None:
            raise RuntimeError("lgpio is not available on this system")
        try:
            lgpio.gpio_claim_input(self._handle, pin)
        except TypeError:
            lgpio.gpio_claim_input(self._handle, 0, pin)
        self._claimed[pin] = self.INPUT

    def setup(self, pin, mode, initial=None):
        if self._handle is None:
            raise RuntimeError("lgpio is not available on this system")
        self._release_if_claimed(pin)
        if mode == self.OUTPUT:
            level = self.LOW if initial is None else (self.HIGH if initial else self.LOW)
            self._claim_output(pin, level)
        elif mode == self.INPUT:
            self._claim_input(pin)
        else:
            raise ValueError(f"Unsupported GPIO mode: {mode}")

    def output(self, pin, level):
        if self._handle is None:
            raise RuntimeError("lgpio is not available on this system")
        lgpio.gpio_write(self._handle, pin, 1 if level else 0)

    def input(self, pin):
        if self._handle is None:
            raise RuntimeError("lgpio is not available on this system")
        return lgpio.gpio_read(self._handle, pin)

    def cleanup(self):
        if self._handle is not None:
            for pin in list(self._claimed.keys()):
                try:
                    lgpio.gpio_free(self._handle, pin)
                except Exception:
                    pass
            self._claimed.clear()
            lgpio.gpiochip_close(self._handle)
            self._handle = None
        self.available = False


GPIO = GPIOAdapter()


def crc8_atm(data):
    """CRC-8/ATM used by TMC2209 UART datagrams."""
    crc = 0
    for byte in data:
        for _ in range(8):
            bit = ((crc >> 7) ^ (byte & 0x01)) & 0x01
            crc = ((crc << 1) & 0xFF) ^ (0x07 if bit else 0)
            byte >>= 1
    return crc


TMC2209_REGISTER_MAP = [
    {"name": "GCONF", "address": 0x00, "access": "RW", "primary_function": "Global configuration flags (UART mode, direction, stealthChop options)."},
    {"name": "GSTAT", "address": 0x01, "access": "R+WC", "primary_function": "Global status flags and clear-on-write fault bits."},
    {"name": "IFCNT", "address": 0x02, "access": "R", "primary_function": "UART interface transmission counter."},
    {"name": "SLAVECONF", "address": 0x03, "access": "RW", "primary_function": "UART slave timing and response configuration."},
    {"name": "OTP_PROG", "address": 0x04, "access": "W", "primary_function": "OTP programming control register."},
    {"name": "OTP_READ", "address": 0x05, "access": "R", "primary_function": "Readback of OTP memory content."},
    {"name": "IOIN", "address": 0x06, "access": "R", "primary_function": "Digital input pin status and version bits."},
    {"name": "FACTORY_CONF", "address": 0x07, "access": "RW", "primary_function": "Factory trim and analog tuning configuration."},
    {"name": "IHOLD_IRUN", "address": 0x10, "access": "RW", "primary_function": "Hold current, run current, and current ramp timing."},
    {"name": "TPOWERDOWN", "address": 0x11, "access": "RW", "primary_function": "Delay before standstill current reduction."},
    {"name": "TSTEP", "address": 0x12, "access": "R", "primary_function": "Measured step period for velocity-dependent features."},
    {"name": "TPWMTHRS", "address": 0x13, "access": "RW", "primary_function": "Threshold for stealthChop/spreadCycle transition."},
    {"name": "TCOOLTHRS", "address": 0x14, "access": "RW", "primary_function": "Threshold for CoolStep and stallGuard operation."},
    {"name": "VACTUAL", "address": 0x22, "access": "RW", "primary_function": "Internal velocity target in UART velocity mode."},
    {"name": "SGTHRS", "address": 0x40, "access": "RW", "primary_function": "stallGuard sensitivity threshold."},
    {"name": "SG_RESULT", "address": 0x41, "access": "R", "primary_function": "Current stallGuard load measurement result."},
    {"name": "COOLCONF", "address": 0x42, "access": "RW", "primary_function": "CoolStep current scaling configuration."},
    {"name": "MSCNT", "address": 0x6A, "access": "R", "primary_function": "Microstep counter (electrical angle position)."},
    {"name": "MSCURACT", "address": 0x6B, "access": "R", "primary_function": "Actual microstep current vector components."},
    {"name": "CHOPCONF", "address": 0x6C, "access": "RW", "primary_function": "Chopper settings (toff, blank time, hysteresis, mode)."},
    {"name": "DRV_STATUS", "address": 0x6F, "access": "R", "primary_function": "Driver status and fault indicators."},
    {"name": "PWMCONF", "address": 0x70, "access": "RW", "primary_function": "stealthChop PWM control parameters."},
    {"name": "PWM_SCALE", "address": 0x71, "access": "R", "primary_function": "Actual PWM scaling value."},
    {"name": "PWM_AUTO", "address": 0x72, "access": "R", "primary_function": "Automatically adapted PWM offsets/gradients."},
]
TMC2209_REG_BY_ADDR = {entry["address"]: entry for entry in TMC2209_REGISTER_MAP}
TMC2209_REG_BY_NAME = {entry["name"]: entry for entry in TMC2209_REGISTER_MAP}


@dataclass
class MotorState:
    position_steps: int = 0
    target_steps: int = 0
    speed_hz: float = 200.0
    acceleration_hz_per_s: float = 800.0
    direction: int = 1
    running: bool = False
    enabled: bool = True
    microsteps: int = 16
    current_ma: int = 800
    uart_connected: bool = False
    last_error: str | None = None


class HardwareUARTTMC2209:
    """TMC2209 UART helper using Raspberry Pi default hardware UART (/dev/serial0)."""

    def __init__(self, device: str | None = None, baudrate: int = 115200):
        self.device = str(device or os.getenv("TMC2209_UART_DEVICE", "/dev/serial0"))
        self.baudrate = int(os.getenv("TMC2209_UART_BAUD", str(baudrate)))
        self.slave_address = int(os.getenv("TMC2209_UART_ADDRESS", "0")) & 0x03
        self.connected = False
        self.simulation = serial is None
        self._serial = None

    def connect(self):
        if self.simulation:
            self.connected = False
            return False

        if self._serial is not None and self._serial.is_open:
            self.connected = True
            return True

        try:
            self._serial = serial.Serial(
                self.device,
                baudrate=self.baudrate,
                timeout=0.05,
                write_timeout=0.05,
            )
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            self.connected = True
            return True
        except Exception:
            self._serial = None
            self.connected = False
            return False

    def disconnect(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self.connected = False

    def _write_frame(self, register: int, value: int):
        register_index = int(register) & 0x7F
        payload = [0x05, self.slave_address, register_index | 0x80, 0, 0, 0, 0]
        payload[3:7] = [
            (value >> 24) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ]
        payload.append(crc8_atm(payload))
        return bytes(payload)

    def _read_request_frame(self, register: int):
        register_index = int(register) & 0x7F
        payload = [0x05, self.slave_address, register_index]
        payload.append(crc8_atm(payload))
        return bytes(payload)

    def _parse_read_response(self, raw: bytes):
        if len(raw) < 8:
            raise TimeoutError(f"UART timeout/short read ({len(raw)} byte)")

        for index in range(0, len(raw) - 7):
            frame = raw[index : index + 8]
            if frame[0] != 0x05:
                continue
            expected_crc = crc8_atm(frame[:-1])
            if frame[-1] != expected_crc:
                continue
            return (
                (frame[3] << 24)
                | (frame[4] << 16)
                | (frame[5] << 8)
                | frame[6]
            )

        raise ValueError("UART response had no valid frame (sync/CRC mismatch)")

    def self_check(self):
        if self.simulation:
            return {
                "ok": False,
                "mode": "simulation",
                "kind": "uart_self_check",
                "device": self.device,
                "baudrate": self.baudrate,
                "address": self.slave_address,
                "message": "pyserial ist nicht verfügbar. Installiere pyserial in der Python-Umgebung.",
            }

        checks: dict[str, object] = {
            "device": self.device,
            "baudrate": self.baudrate,
            "address": self.slave_address,
            "kind": "uart_self_check",
            "mode": "hardware_uart",
        }
        errors: list[str] = []

        device_exists = os.path.exists(self.device)
        checks["device_exists"] = device_exists
        if not device_exists:
            errors.append(f"UART device {self.device} does not exist")

        if device_exists:
            checks["readable"] = os.access(self.device, os.R_OK)
            checks["writable"] = os.access(self.device, os.W_OK)
            if not checks["readable"] or not checks["writable"]:
                errors.append(
                    f"Missing permissions for {self.device} "
                    f"(readable={checks['readable']}, writable={checks['writable']})"
                )

        if not errors:
            if not self.connect():
                errors.append(f"Unable to open UART device {self.device}")
            else:
                try:
                    self._serial.reset_input_buffer()
                    self._serial.reset_output_buffer()
                    self._serial.write(b"\x55\x00\xFF")
                    self._serial.flush()
                    time.sleep(0.002)
                    waiting_attr = getattr(self._serial, "in_waiting", 0)
                    checks["in_waiting"] = int(waiting_attr) if waiting_attr is not None else 0
                    checks["port_open"] = bool(self._serial.is_open)
                except Exception as exc:  # pragma: no cover - hardware dependent
                    errors.append(f"UART write/flush failed: {exc}")
                finally:
                    self.disconnect()

        ok = len(errors) == 0
        checks["ok"] = ok
        checks["errors"] = errors
        checks["message"] = (
            "UART self-check OK: device vorhanden, Zugriffsrechte korrekt, Port kann geöffnet werden."
            if ok
            else "UART self-check failed: " + " | ".join(errors)
        )
        return checks

    def write_register(self, register: int, value: int):
        if self.simulation:
            return 0

        if not self.connect():
            raise OSError(f"cannot open TMC2209 UART on {self.device}")

        frame = self._write_frame(register, int(value))
        self._serial.write(frame)
        self._serial.flush()
        time.sleep(0.002)
        return value

    def read_register(self, register: int):
        if self.simulation:
            return 0

        if not self.connect():
            raise OSError(f"cannot open TMC2209 UART on {self.device}")

        self._serial.reset_input_buffer()
        frame = self._read_request_frame(register)
        self._serial.write(frame)
        self._serial.flush()
        time.sleep(0.003)
        raw = self._serial.read(32)
        return self._parse_read_response(raw)

    def test_connectivity(self, register: int = 0x6F):
        if self.simulation:
            return {
                "ok": False,
                "mode": "simulation",
                "register": int(register),
                "address": self.slave_address,
                "value": 0,
                "message": (
                    "Simulation mode: pyserial is not available on this host, so no real UART read is possible. "
                    "Install pyserial and run this app on the Raspberry Pi."
                ),
            }

        attempts = 3
        values = []
        errors = []
        for _ in range(attempts):
            try:
                values.append(self.read_register(int(register)))
            except Exception as exc:  # pragma: no cover - depends on hardware
                errors.append(str(exc))
            time.sleep(0.01)

        if len(values) < 2:
            detail = f" Details: {errors[0]}" if errors else ""
            return {
                "ok": False,
                "mode": "hardware_uart",
                "register": int(register),
                "address": self.slave_address,
                "value": 0,
                "samples": values,
                "errors": errors,
                "message": "UART test failed: not enough valid responses (need at least 2 of 3)." + detail,
            }

        if len(set(values)) != 1:
            return {
                "ok": False,
                "mode": "hardware_uart",
                "register": int(register),
                "address": self.slave_address,
                "value": int(values[0]),
                "samples": values,
                "errors": errors,
                "message": "UART test failed: unstable register values across retries.",
            }

        value = int(values[0])
        if value in (0x00000000, 0xFFFFFFFF):
            return {
                "ok": False,
                "mode": "hardware_uart",
                "register": int(register),
                "address": self.slave_address,
                "value": value,
                "samples": values,
                "errors": errors,
                "message": (
                    f"UART test failed: suspicious constant value 0x{value:08X} "
                    "received on all retries."
                ),
            }

        return {
            "ok": True,
            "mode": "hardware_uart",
            "register": int(register),
            "address": self.slave_address,
            "value": value,
            "samples": values,
            "errors": errors,
            "message": f"UART antwortet stabil auf Register 0x{register:02X}: 0x{value:08X}",
        }

    def configure(self, microsteps: int = 16, current_ma: int = 800):
        self.microsteps = int(microsteps)
        self.current_ma = int(current_ma)

        if self.simulation:
            return {
                "mode": "simulation",
                "uart_device": self.device,
                "baudrate": self.baudrate,
                "address": self.slave_address,
                "microsteps": self.microsteps,
                "current_ma": self.current_ma,
            }

        try:
            self.write_register(0x00, 0x00000000)
            self.write_register(0x10, 0x00000000)
            self.write_register(0x11, 0x00000014)
            self.write_register(0x6C, 0x000100C3)
            return {
                "mode": "hardware_uart",
                "uart_device": self.device,
                "baudrate": self.baudrate,
                "address": self.slave_address,
                "microsteps": self.microsteps,
                "current_ma": self.current_ma,
            }
        except OSError as exc:
            return {"mode": "error", "error": str(exc)}


class BetterMotorController:
    def __init__(self):
        self.step_pin = int(os.getenv("STEP_PIN", "17"))
        self.dir_pin = int(os.getenv("DIR_PIN", "27"))
        self.enable_pin = int(os.getenv("ENABLE_PIN", "22"))
        self.uart = HardwareUARTTMC2209(device=os.getenv("TMC2209_UART_DEVICE", "/dev/serial0"))
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.state = MotorState()
        self.state.microsteps = int(os.getenv("TMC2209_MICROSTEPS", "16"))
        self.state.current_ma = int(os.getenv("TMC2209_CURRENT_MA", "800"))
        self.state.acceleration_hz_per_s = float(os.getenv("TMC2209_ACCEL_HZ", "800.0"))
        self.state.speed_hz = float(os.getenv("TMC2209_MAX_SPEED_HZ", "200.0"))
        self.last_uart_test_result: dict | None = None
        self.last_uart_self_check_result: dict | None = None
        self.last_register_access_result: dict | None = None
        self.simulation = not GPIO.available

    def setup(self):
        if self.simulation:
            self.state.last_error = "GPIO/UART backend unavailable; demo mode is active."
            self.state.uart_connected = False
            return

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.enable_pin, GPIO.OUTPUT, initial=GPIO.LOW)
            GPIO.setup(self.dir_pin, GPIO.OUTPUT, initial=GPIO.LOW)
            GPIO.setup(self.step_pin, GPIO.OUTPUT, initial=GPIO.LOW)
            self.uart.connect()
            self.state.uart_connected = self.uart.connected
            self.configure_driver()
            self.enable()
        except Exception as exc:
            self.simulation = True
            self.state.uart_connected = False
            self.state.last_error = f"GPIO setup failed ({exc}); switched to demo mode."

    def configure_driver(self, microsteps: int | None = None, current_ma: int | None = None):
        if microsteps is not None:
            self.state.microsteps = int(microsteps)
        if current_ma is not None:
            self.state.current_ma = int(current_ma)

        cfg = self.uart.configure(self.state.microsteps, self.state.current_ma)
        if cfg.get("mode") == "error":
            self.state.last_error = cfg.get("error")
        else:
            self.state.last_error = None
        return cfg

    def test_uart_connectivity(self, register: int = 0x6F):
        result = self.uart.test_connectivity(register=int(register))
        self.last_uart_test_result = result
        self.state.uart_connected = bool(result.get("ok"))
        if result.get("ok"):
            self.state.last_error = None
        else:
            self.state.last_error = result.get("message")
        return result

    def run_uart_self_check(self):
        result = self.uart.self_check()
        self.last_uart_self_check_result = result
        self.state.uart_connected = bool(result.get("ok"))
        if result.get("ok"):
            self.state.last_error = None
        else:
            self.state.last_error = result.get("message")
        return result

    def update_uart_settings(
        self,
        device: str | None = None,
        baudrate: int | None = None,
        address: int | None = None,
    ):
        if device is not None:
            device_value = str(device).strip()
            if not device_value.startswith("/dev/"):
                raise ValueError("uart_device must be a /dev/* path")
            self.uart.device = device_value
        if baudrate is not None:
            baud = int(baudrate)
            if baud <= 0:
                raise ValueError("uart_baudrate must be greater than 0")
            self.uart.baudrate = baud
        if address is not None:
            addr = int(address)
            if addr < 0 or addr > 3:
                raise ValueError("uart_address must be between 0 and 3")
            self.uart.slave_address = addr
        self.uart.disconnect()
        self.last_uart_test_result = None
        return {
            "uart_device": self.uart.device,
            "uart_baudrate": self.uart.baudrate,
            "uart_address": self.uart.slave_address,
        }

    @staticmethod
    def _parse_register_address(value):
        if isinstance(value, str):
            return int(value, 0)
        return int(value)

    @staticmethod
    def _parse_register_value(value):
        if isinstance(value, str):
            return int(value, 0)
        return int(value)

    def get_register_map(self):
        return TMC2209_REGISTER_MAP

    def read_register_by_address(self, address):
        register_address = self._parse_register_address(address)
        if register_address < 0x00 or register_address > 0x7F:
            raise ValueError("register address must be between 0x00 and 0x7F")
        info = TMC2209_REG_BY_ADDR.get(register_address)
        name = info["name"] if info else "UNKNOWN"
        value = self.uart.read_register(register_address)
        result = {
            "ok": True,
            "name": name,
            "address": register_address,
            "value": int(value) & 0xFFFFFFFF,
            "access": info["access"] if info else "UNKNOWN",
        }
        self.last_register_access_result = result
        return result

    def write_register_by_address(self, address, value):
        register_address = self._parse_register_address(address)
        register_value = self._parse_register_value(value) & 0xFFFFFFFF
        if register_address < 0x00 or register_address > 0x7F:
            raise ValueError("register address must be between 0x00 and 0x7F")

        info = TMC2209_REG_BY_ADDR.get(register_address)
        if info and "W" not in info["access"]:
            raise ValueError(
                f"register {info['name']} (0x{register_address:02X}) is not writable ({info['access']})"
            )

        self.uart.write_register(register_address, register_value)
        result = {
            "ok": True,
            "name": info["name"] if info else "UNKNOWN",
            "address": register_address,
            "value": register_value,
            "access": info["access"] if info else "UNKNOWN",
        }
        self.last_register_access_result = result
        return result

    def enable(self):
        self.state.enabled = True
        if self.simulation:
            return
        GPIO.output(self.enable_pin, GPIO.LOW)

    def disable(self):
        self.state.enabled = False
        if self.simulation:
            return
        GPIO.output(self.enable_pin, GPIO.HIGH)

    def set_direction(self, direction: int):
        if direction not in (-1, 1):
            raise ValueError("direction must be 1 or -1")
        self.state.direction = direction
        if self.simulation:
            return
        GPIO.output(self.dir_pin, GPIO.HIGH if direction > 0 else GPIO.LOW)

    def step_once(self, direction: int):
        self.set_direction(direction)
        if self.simulation:
            time.sleep(0.0005)
            return
        GPIO.output(self.step_pin, GPIO.HIGH)
        time.sleep(0.00035)
        GPIO.output(self.step_pin, GPIO.LOW)

    def move_steps(self, steps: int, direction: int = 1, speed_hz: float | None = None, acceleration_hz_per_s: float | None = None):
        if steps == 0:
            return

        direction = int(direction)
        if direction not in (-1, 1):
            raise ValueError("direction must be 1 or -1")

        speed_hz = self.state.speed_hz if speed_hz is None else float(speed_hz)
        acceleration_hz_per_s = self.state.acceleration_hz_per_s if acceleration_hz_per_s is None else float(acceleration_hz_per_s)
        if speed_hz <= 0:
            raise ValueError("speed_hz must be greater than 0")
        if acceleration_hz_per_s <= 0:
            raise ValueError("acceleration_hz_per_s must be greater than 0")

        self._stop_event.clear()
        self.state.speed_hz = speed_hz
        self.state.acceleration_hz_per_s = acceleration_hz_per_s
        self.state.target_steps = int(abs(steps))

        with self._lock:
            if self._thread and self._thread.is_alive():
                self.stop()
                while self._thread.is_alive():
                    time.sleep(0.01)

            self._thread = threading.Thread(
                target=self._profiled_move,
                args=(int(abs(steps)), direction, speed_hz, acceleration_hz_per_s),
                daemon=True,
            )
            self._thread.start()

    def move_to(self, target_steps: int, speed_hz: float | None = None, acceleration_hz_per_s: float | None = None):
        current = self.state.position_steps
        delta = int(target_steps) - current
        if delta == 0:
            return
        direction = 1 if delta > 0 else -1
        self.move_steps(abs(delta), direction=direction, speed_hz=speed_hz, acceleration_hz_per_s=acceleration_hz_per_s)

    def _profiled_move(self, step_count: int, direction: int, speed_hz: float, acceleration_hz_per_s: float):
        self.state.running = True
        self.enable()
        self.set_direction(direction)

        remaining = step_count
        current_speed = 0.0
        max_speed = float(speed_hz)
        acceleration = float(acceleration_hz_per_s)
        brake_distance = (max_speed * max_speed) / (2.0 * acceleration)
        last_time = time.perf_counter()

        while remaining > 0 and not self._stop_event.is_set():
            now = time.perf_counter()
            elapsed = max(0.001, now - last_time)
            last_time = now

            if remaining > brake_distance:
                target_speed = max_speed
            else:
                target_speed = math.sqrt(max(0.0, 2.0 * acceleration * remaining))

            if current_speed < target_speed:
                current_speed = min(target_speed, current_speed + acceleration * elapsed)
            elif current_speed > target_speed:
                current_speed = max(target_speed, current_speed - acceleration * elapsed)

            pulse_interval = 0.5 / max(current_speed, 1.0)
            self.step_once(direction)
            time.sleep(max(0.00005, pulse_interval - 0.00035))

            remaining -= 1
            self.state.position_steps += direction
            self.state.target_steps = remaining

        self.state.running = False
        self.state.target_steps = 0

    def stop(self):
        self._stop_event.set()
        self.state.running = False
        self.state.target_steps = 0

    def cleanup(self):
        self.stop()
        self.uart.disconnect()
        if not self.simulation and GPIO.available:
            GPIO.cleanup()


motor = BetterMotorController()
motor.setup()
app = Flask(__name__)


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/status")
def status_api():
    return jsonify(
        {
            "running": motor.state.running,
            "position_steps": motor.state.position_steps,
            "target_steps": motor.state.target_steps,
            "speed_hz": motor.state.speed_hz,
            "acceleration_hz_per_s": motor.state.acceleration_hz_per_s,
            "direction": motor.state.direction,
            "enabled": motor.state.enabled,
            "microsteps": motor.state.microsteps,
            "current_ma": motor.state.current_ma,
            "uart_connected": motor.state.uart_connected,
            "uart_device": motor.uart.device,
            "uart_address": motor.uart.slave_address,
            "uart_baudrate": motor.uart.baudrate,
            "uart_last_test": motor.last_uart_test_result,
            "uart_last_self_check": motor.last_uart_self_check_result,
            "uart_last_register_access": motor.last_register_access_result,
            "gpio_available": GPIO.available,
            "simulation": motor.simulation,
            "last_error": motor.state.last_error,
        }
    )


@app.post("/api/config")
def config_api():
    payload = request.get_json(silent=True) or {}
    try:
        microsteps = int(payload.get("microsteps", motor.state.microsteps))
        current_ma = int(payload.get("current_ma", motor.state.current_ma))
        max_speed_hz = float(payload.get("max_speed_hz", motor.state.speed_hz))
        acceleration_hz_per_s = float(payload.get("acceleration_hz_per_s", motor.state.acceleration_hz_per_s))
        motor.state.speed_hz = max_speed_hz
        motor.state.acceleration_hz_per_s = acceleration_hz_per_s
        cfg = motor.configure_driver(microsteps=microsteps, current_ma=current_ma)
        return jsonify({"ok": True, **cfg, "max_speed_hz": max_speed_hz, "acceleration_hz_per_s": acceleration_hz_per_s})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/uart-settings")
def uart_settings_api():
    payload = request.get_json(silent=True) or {}
    try:
        updated = motor.update_uart_settings(
            device=payload.get("uart_device"),
            baudrate=payload.get("uart_baudrate"),
            address=payload.get("uart_address"),
        )
        return jsonify({"ok": True, **updated})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/uart-test")
def uart_test_api():
    payload = request.get_json(silent=True) or {}
    register = int(payload.get("register", 0x6F))
    result = motor.test_uart_connectivity(register=register)
    return jsonify(result)


@app.post("/api/uart-self-check")
def uart_self_check_api():
    result = motor.run_uart_self_check()
    return jsonify(result)


@app.get("/api/register-map")
def register_map_api():
    return jsonify({"ok": True, "registers": motor.get_register_map()})


@app.post("/api/register-read")
def register_read_api():
    payload = request.get_json(silent=True) or {}
    try:
        result = motor.read_register_by_address(payload.get("address"))
        return jsonify(result)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/register-write")
def register_write_api():
    payload = request.get_json(silent=True) or {}
    try:
        result = motor.write_register_by_address(
            payload.get("address"),
            payload.get("value"),
        )
        return jsonify(result)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/move")
def move_api():
    payload = request.get_json(silent=True) or {}
    try:
        steps = int(payload.get("steps", 0))
        direction = int(payload.get("direction", 1))
        speed_hz = float(payload.get("speed_hz", motor.state.speed_hz))
        acceleration_hz_per_s = float(payload.get("acceleration_hz_per_s", motor.state.acceleration_hz_per_s))
        motor.move_steps(steps=steps, direction=direction, speed_hz=speed_hz, acceleration_hz_per_s=acceleration_hz_per_s)
        return jsonify({"ok": True, "steps": steps, "direction": direction, "speed_hz": speed_hz, "acceleration_hz_per_s": acceleration_hz_per_s})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/move_to")
def move_to_api():
    payload = request.get_json(silent=True) or {}
    try:
        target_steps = int(payload.get("target_steps", 0))
        speed_hz = float(payload.get("speed_hz", motor.state.speed_hz))
        acceleration_hz_per_s = float(payload.get("acceleration_hz_per_s", motor.state.acceleration_hz_per_s))
        motor.move_to(target_steps, speed_hz=speed_hz, acceleration_hz_per_s=acceleration_hz_per_s)
        return jsonify({"ok": True, "target_steps": target_steps, "speed_hz": speed_hz, "acceleration_hz_per_s": acceleration_hz_per_s})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/stop")
def stop_api():
    motor.stop()
    return jsonify({"ok": True, "running": False})


@app.post("/api/enable")
def enable_api():
    motor.enable()
    return jsonify({"ok": True, "enabled": True})


@app.post("/api/disable")
def disable_api():
    motor.disable()
    return jsonify({"ok": True, "enabled": False})


atexit.register(motor.cleanup)


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    app.run(host=host, port=port, debug=False, threaded=True)
