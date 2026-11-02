from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

try:
    import gpiod
except ImportError:  # pragma: no cover - optional runtime dependency
    gpiod = None

try:
    from smbus2 import SMBus
except ImportError:  # pragma: no cover - optional runtime dependency
    SMBus = None


class AS3935Error(RuntimeError):
    """Raised when a sensor operation fails."""


class InterruptReason:
    NOISE = 0x01
    DISTURBER = 0x04
    LIGHTNING = 0x08

    @staticmethod
    def describe(value: int) -> str:
        reasons = {
            InterruptReason.NOISE: "noise level too high",
            InterruptReason.DISTURBER: "disturber detected",
            InterruptReason.LIGHTNING: "lightning detected",
        }
        return reasons.get(value & 0x0F, "unknown interrupt")


class GPIODInterrupt:
    """Small wrapper around libgpiod for interrupt monitoring."""

    def __init__(self, chip_path: str = "/dev/gpiochip0", line_offset: int = 17):
        if gpiod is None:
            raise AS3935Error("gpiod is required for interrupt monitoring. Install python3-gpiod or python-gpiod.")

        self.chip_path = chip_path
        self.line_offset = int(line_offset)
        self.request = gpiod.request_lines(
            self.chip_path,
            consumer="as3935",
            config={
                self.line_offset: gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT,
                    edge_detection=gpiod.line.Edge.RISING,
                    bias=gpiod.line.Bias.AS_IS,
                )
            },
        )

    def wait(self, timeout: Optional[float] = None) -> bool:
        if timeout is None:
            timeout = 1.0
        return bool(self.request.wait_edge_events(timeout))

    def read_event(self):
        events = self.request.read_edge_events()
        return events[0] if events else None

    def close(self) -> None:
        if self.request is not None:
            self.request.release()
            self.request = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


@dataclass
class SensorStatus:
    indoors: bool
    noise_floor: int
    min_strikes: int
    mask_disturber: bool
    distance: Optional[int]
    energy: int
    interrupt: int


class AS3935:
    """A modern AS3935 driver compatible with current Linux/Raspberry Pi systems."""

    DEFAULT_ADDRESS = 0x03
    DEFAULT_BUS = 1
    DEFAULT_IRQ_LINE = 17

    def __init__(
        self,
        address: int = DEFAULT_ADDRESS,
        bus: int = DEFAULT_BUS,
        irq_chip: str = "/dev/gpiochip0",
        irq_line: Optional[int] = None,
        *,
        mock: bool = False,
    ):
        self.address = int(address)
        self.bus = int(bus)
        self.irq_chip = irq_chip
        self.irq_line = irq_line
        self.mock = mock
        self._registers = [0] * 9
        self._special_registers = {}
        self._irq = None

        if self.mock:
            self._i2c = None
            self._registers = [0x24, 0x20, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            return

        if SMBus is None:
            raise AS3935Error("smbus2 is required. Install it with 'python -m pip install smbus2'.")

        self._i2c = SMBus(self.bus)

        if self.irq_line is not None:
            self._irq = GPIODInterrupt(self.irq_chip, self.irq_line)

    def close(self) -> None:
        if self._irq is not None:
            self._irq.close()
            self._irq = None
        if self._i2c is not None:
            self._i2c.close()
            self._i2c = None

    def _read_block(self) -> list[int]:
        if self.mock:
            return list(self._registers)
        if self._i2c is None:
            raise AS3935Error("I2C bus is not available")
        return list(self._i2c.read_i2c_block_data(self.address, 0x00, 9))

    def read_registers(self) -> list[int]:
        self._registers = self._read_block()
        return list(self._registers)

    def _write_byte(self, register: int, value: int) -> None:
        if self.mock:
            if 0x00 <= register <= 0x08:
                self._registers[register] = value & 0xFF
            else:
                self._special_registers[register] = value & 0xFF
            return
        if self._i2c is None:
            raise AS3935Error("I2C bus is not available")
        self._i2c.write_byte_data(self.address, register, value & 0xFF)

    def reset(self) -> None:
        self._write_byte(0x3C, 0x96)

    def calibrate(self, tune_cap: Optional[int] = None) -> None:
        """Run the AS3935 calibration routine.

        `tune_cap` accepts values 0-15 and sets the internal tuning capacitors.
        """
        time.sleep(0.08)
        self.read_registers()

        if tune_cap is not None:
            if not 0 <= tune_cap <= 0x0F:
                raise ValueError("tune_cap must be between 0 and 15")
            self._write_byte(0x08, (self._registers[0x08] & 0xF0) | tune_cap)
            time.sleep(0.002)

        self._write_byte(0x3D, 0x96)
        time.sleep(0.002)
        self.read_registers()

        self._write_byte(0x08, self._registers[0x08] | 0x20)
        time.sleep(0.002)
        self._write_byte(0x08, self._registers[0x08] & 0xDF)
        time.sleep(0.002)

    def get_interrupt(self) -> int:
        self.read_registers()
        return self._registers[0x03] & 0x0F

    def get_distance(self) -> Optional[int]:
        self.read_registers()
        distance = self._registers[0x07] & 0x3F
        return None if distance == 0x3F else distance

    def get_energy(self) -> int:
        self.read_registers()
        return ((self._registers[0x06] & 0x1F) << 16) | (self._registers[0x05] << 8) | self._registers[0x04]

    def get_noise_floor(self) -> int:
        self.read_registers()
        return (self._registers[0x01] & 0x70) >> 4

    def set_noise_floor(self, noise_floor: int) -> int:
        if not 0 <= noise_floor <= 7:
            raise ValueError("noise_floor must be between 0 and 7")
        self.read_registers()
        masked = (noise_floor & 0x07) << 4
        write_value = (self._registers[0x01] & 0x8F) | masked
        self._write_byte(0x01, write_value)
        return self.get_noise_floor()

    def lower_noise_floor(self, min_noise: int = 0) -> int:
        floor = self.get_noise_floor()
        if floor > min_noise:
            floor -= 1
            self.set_noise_floor(floor)
        return floor

    def raise_noise_floor(self, max_noise: int = 7) -> int:
        floor = self.get_noise_floor()
        if floor < max_noise:
            floor += 1
            self.set_noise_floor(floor)
        return floor

    def get_min_strikes(self) -> int:
        self.read_registers()
        value = (self._registers[0x02] >> 4) & 0x03
        mapping = {0: 1, 1: 5, 2: 9, 3: 16}
        return mapping[value]

    def set_min_strikes(self, strikes: int) -> int:
        mapping = {1: 0, 5: 1, 9: 2, 16: 3}
        if strikes not in mapping:
            raise ValueError("strikes must be one of 1, 5, 9, or 16")

        self.read_registers()
        value = (mapping[strikes] & 0x03) << 4
        self._write_byte(0x02, (self._registers[0x02] & 0xCF) | value)
        return self.get_min_strikes()

    def get_indoors(self) -> bool:
        self.read_registers()
        return bool(self._registers[0x00] & 0x20)

    def set_indoors(self, indoors: bool) -> bool:
        self.read_registers()
        if indoors:
            write_value = (self._registers[0x00] & 0xC1) | 0x24
        else:
            write_value = (self._registers[0x00] & 0xC1) | 0x1C
        self._write_byte(0x00, write_value)
        return self.get_indoors()

    def set_mask_disturber(self, mask_disturber: bool) -> bool:
        self.read_registers()
        if mask_disturber:
            write_value = self._registers[0x03] | 0x20
        else:
            write_value = self._registers[0x03] & 0xDF
        self._write_byte(0x03, write_value)
        return self.get_mask_disturber()

    def get_mask_disturber(self) -> bool:
        self.read_registers()
        return bool(self._registers[0x03] & 0x20)

    def set_disp_lco(self, display_lco: bool) -> bool:
        self.read_registers()
        if display_lco:
            self._write_byte(0x08, self._registers[0x08] | 0x80)
        else:
            self._write_byte(0x08, self._registers[0x08] & 0x7F)
        time.sleep(0.002)
        return self.get_disp_lco()

    def get_disp_lco(self) -> bool:
        self.read_registers()
        return bool(self._registers[0x08] & 0x80)

    def get_status(self) -> SensorStatus:
        self.read_registers()
        return SensorStatus(
            indoors=self.get_indoors(),
            noise_floor=self.get_noise_floor(),
            min_strikes=self.get_min_strikes(),
            mask_disturber=self.get_mask_disturber(),
            distance=self.get_distance(),
            energy=self.get_energy(),
            interrupt=self.get_interrupt(),
        )

    def poll_for_interrupt(self, timeout: float = 1.0, interval: float = 0.1) -> Optional[int]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reason = self.get_interrupt()
            if reason != 0:
                return reason
            time.sleep(interval)
        return None

    def wait_for_interrupt(self, timeout: float = 1.0, interval: float = 0.1) -> Optional[int]:
        if self._irq is not None:
            if not self._irq.wait(timeout):
                return None
            event = self._irq.read_event()
            return self.get_interrupt() if event is not None else None
        return self.poll_for_interrupt(timeout=timeout, interval=interval)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
