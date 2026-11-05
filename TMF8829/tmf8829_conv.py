# *****************************************************************************
# * Copyright by ams OSRAM AG                                                 *
# * All rights are reserved.                                                  *
# *                                                                           *
# *FOR FULL LICENSE TEXT SEE LICENSES-MIT.TXT                                 *
# *****************************************************************************
"""
A set of convenience functions and imports.
"""

import __init__
import os
import glob
from tmf8829_linux_i2c_com import LinuxI2cCom

FRESNEL_I2C_ADDR=0x41

def _resolveLinuxI2cDevice(i2c_slave_addr:int) -> str:
    """Resolve a Linux i2c-dev node for the given slave address."""
    env_device = os.environ.get("TMF8829_I2C_DEVICE")
    if env_device:
        return env_device

    env_bus = os.environ.get("TMF8829_I2C_BUS")
    if env_bus is not None:
        return f"/dev/i2c-{env_bus}"

    candidates = sorted(glob.glob("/dev/i2c-*"))
    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise ConnectionError(
            "No /dev/i2c-* device found. Set TMF8829_I2C_DEVICE (for example /dev/i2c-1)."
        )

    for candidate in candidates:
        try:
            com = LinuxI2cCom(dev_node=candidate, log=False, exception_on_error=True)
            com.i2cOpen()
            com.i2cTxRx(i2c_slave_addr, [0], 1)
            com.i2cClose()
            return candidate
        except Exception:
            try:
                com.i2cClose()
            except Exception:
                pass

    raise ConnectionError(
        f"Could not auto-detect TMF8829 on {candidates}. "
        "Set TMF8829_I2C_DEVICE to the correct node (for example /dev/i2c-1)."
    )


def createTmf8829(i2c_slave_addr=FRESNEL_I2C_ADDR, log=False):
    """Create a TMF8829 application instance for native Linux I2C communication."""
    import sys
    from tmf8829_application import Tmf8829Application
    
    print(sys.path)
    i2c_dev = _resolveLinuxI2cDevice(i2c_slave_addr=i2c_slave_addr)
    print(f"TMF8829 backend: native Linux I2C ({i2c_dev})")
    com = LinuxI2cCom(dev_node=i2c_dev, log=log)

    from aos_com.i2c_hal_register_io import I2cHalRegisterIo as Hal
    hal = Hal( ic_com=com, dev_addr = i2c_slave_addr )
    
    return Tmf8829Application( hal=hal, gpio_hal=hal )
