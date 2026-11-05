# *****************************************************************************
# * Copyright by ams OSRAM AG                                                 *
# * All rights are reserved.                                                  *
# *                                                                           *
# *FOR FULL LICENSE TEXT SEE LICENSES-MIT.TXT                                 *
# *****************************************************************************
"""
Linux native I2C backend for /dev/i2c-* nodes.
"""

import ctypes
import fcntl
import os
import errno

from aos_com.ic_com import IcCom

I2C_SLAVE = 0x0703
I2C_RDWR = 0x0707
I2C_M_RD = 0x0001


class _I2cMsg(ctypes.Structure):
    _fields_ = [
        ("addr", ctypes.c_uint16),
        ("flags", ctypes.c_uint16),
        ("len", ctypes.c_uint16),
        ("buf", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _I2cRdwrIoctlData(ctypes.Structure):
    _fields_ = [
        ("msgs", ctypes.POINTER(_I2cMsg)),
        ("nmsgs", ctypes.c_uint32),
    ]


class LinuxI2cCom(IcCom):
    """Communicate with TMF8829 directly via Linux i2c-dev."""

    def __init__(self, dev_node: str, log: bool = False, exception_on_error: bool = True) -> None:
        super().__init__(log=log, exception_on_error=exception_on_error)
        self.dev_node = dev_node
        self._fd = None

        # Keep GPIO semantics for the rest of the stack.
        self.enable_pin = 0x01
        self.interrupt_pin = 0x02
        self._gpio_state = 0
        self._gpio_dir_mask = 0

    def _ensure_open(self):
        if self._fd is None:
            raise RuntimeError(f"I2C device is not open: {self.dev_node}")

    def _read_exact(self, rx_size: int, fn_name: str) -> bytes:
        chunks = []
        remaining = rx_size
        while remaining > 0:
            data = os.read(self._fd, remaining)
            if not data:
                break
            chunks.append(data)
            remaining -= len(data)

        output = b"".join(chunks)
        if len(output) != rx_size:
            self._setError(f"Incomplete I2C read ({len(output)}/{rx_size} bytes)", fn_name)
        return output

    def i2cOpen(self, i2c_speed: int = 1000000) -> int:
        del i2c_speed
        fn_name = "i2cOpen"
        try:
            self._fd = os.open(self.dev_node, os.O_RDWR)
            return self._OK
        except OSError as err:
            self._setError(f"Failed to open {self.dev_node}: {err}", fn_name)
            return self._ERROR_NOT_IMPLEMENTED

    def i2cClose(self) -> int:
        fn_name = "i2cClose"
        try:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            return self._OK
        except OSError as err:
            self._setError(f"Failed to close {self.dev_node}: {err}", fn_name)
            return self._ERROR_NOT_IMPLEMENTED

    def _set_slave(self, devaddr: int, fn_name: str) -> None:
        self._ensure_open()
        try:
            fcntl.ioctl(self._fd, I2C_SLAVE, devaddr)
        except OSError as err:
            self._setError(f"Failed to select I2C address 0x{devaddr:02x}: {err}", fn_name)

    def i2cTx(self, devaddr: int, tx: list) -> int:
        fn_name = "i2cTx"
        self._set_slave(devaddr, fn_name)
        data = bytes(tx)
        try:
            written = os.write(self._fd, data)
            if written != len(data):
                self._setError(f"Incomplete I2C write ({written}/{len(data)} bytes)", fn_name)
            return self._OK
        except OSError as err:
            self._setError(f"I2C write failed at address 0x{devaddr:02x}: {err}", fn_name)
            return self._ERROR_NOT_IMPLEMENTED

    def i2cRx(self, devaddr: int, rx_size: int) -> bytearray:
        fn_name = "i2cRx"
        self._set_slave(devaddr, fn_name)
        try:
            data = self._read_exact(rx_size=rx_size, fn_name=fn_name)
            return bytearray(data)
        except OSError as err:
            self._setError(f"I2C read failed at address 0x{devaddr:02x}: {err}", fn_name)
            return bytearray()

    def i2cTxRx(self, devaddr: int, tx: list, rx_size: int) -> bytearray:
        fn_name = "i2cTxRx"
        self._ensure_open()

        tx_buffer = (ctypes.c_ubyte * len(tx))(*tx) if tx else None
        rx_buffer = (ctypes.c_ubyte * rx_size)()

        messages = []
        if tx:
            messages.append(
                _I2cMsg(
                    addr=devaddr,
                    flags=0,
                    len=len(tx),
                    buf=ctypes.cast(tx_buffer, ctypes.POINTER(ctypes.c_ubyte)),
                )
            )
        messages.append(
            _I2cMsg(
                addr=devaddr,
                flags=I2C_M_RD,
                len=rx_size,
                buf=ctypes.cast(rx_buffer, ctypes.POINTER(ctypes.c_ubyte)),
            )
        )

        msg_array = (_I2cMsg * len(messages))(*messages)
        ioctl_data = _I2cRdwrIoctlData(
            msgs=ctypes.cast(msg_array, ctypes.POINTER(_I2cMsg)),
            nmsgs=len(messages),
        )
        try:
            fcntl.ioctl(self._fd, I2C_RDWR, ioctl_data)
            return bytearray(rx_buffer)
        except OSError as err:
            if err.errno == errno.EINVAL:
                # Some Linux adapter drivers reject I2C_RDWR for certain payloads.
                # Fall back to plain write + read operations on the same slave address.
                self._set_slave(devaddr, fn_name)
                try:
                    if tx:
                        written = os.write(self._fd, bytes(tx))
                        if written != len(tx):
                            self._setError(
                                f"Incomplete I2C write in fallback path ({written}/{len(tx)} bytes)",
                                fn_name,
                            )
                    data = self._read_exact(rx_size=rx_size, fn_name=fn_name)
                    return bytearray(data)
                except OSError as fallback_err:
                    self._setError(
                        f"I2C write/read fallback failed at address 0x{devaddr:02x}: {fallback_err}",
                        fn_name,
                    )
                    return bytearray()
            self._setError(f"I2C write/read failed at address 0x{devaddr:02x}: {err}", fn_name)
            return bytearray()

    def gpioSetDirection(self, out_mask: int, out_value: int):
        self._gpio_dir_mask |= out_mask
        self._gpio_state = (self._gpio_state & ~out_mask) | (out_value & out_mask)

    def gpioSet(self, w_mask: int, value: int):
        self._gpio_state = (self._gpio_state & ~w_mask) | (value & w_mask)

    def gpioGet(self, r_mask: int) -> int:
        # Keep INT as inactive by default when no real GPIO is wired.
        return self._gpio_state & r_mask
