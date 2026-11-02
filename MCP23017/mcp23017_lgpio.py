#!/usr/bin/env python
"""
lg_mcp23017.py
2026-10-15
Public Domain

MCP23017 16-bit I/O expander over I2C.

http://abyz.me.uk/lg/py_lgpio.html
http://abyz.me.uk/lg/py_rgpio.html
"""

class MCP23017:
   """
   MCP23017 16-bit I/O expander.

   GPA0..GPA7 are pins 0..7
   GPB0..GPB7 are pins 8..15
   """

   INPUT = 1
   OUTPUT = 0

   _IODIRA = 0x00
   _IODIRB = 0x01
   _IPOLA = 0x02
   _IPOLB = 0x03
   _GPPUA = 0x0C
   _GPPUB = 0x0D
   _GPIOA = 0x12
   _GPIOB = 0x13
   _OLATA = 0x14
   _OLATB = 0x15

   def __init__(self, sbc, bus, address=0x20, flags=0):
      """
      Open an MCP23017 on a given I2C bus/address.

      sbc may be lgpio (module style API) or rgpio.sbc().
      """
      self._sbc = sbc
      self._bus = bus
      self._address = address
      self._i2c = sbc.i2c_open(bus, address, flags)
      self._check(self._i2c, "i2c_open")

   def _check(self, status, action):
      if status < 0:
         raise RuntimeError("{} failed with status {}".format(action, status))
      return status

   def _validate_pin(self, pin):
      if not 0 <= pin <= 15:
         raise ValueError("pin must be in range 0..15")

   def _port_and_bit(self, pin):
      self._validate_pin(pin)
      return (pin >> 3), (pin & 7)

   def _port_to_index(self, port):
      if port in (0, "A", "a"):
         return 0
      if port in (1, "B", "b"):
         return 1
      raise ValueError("port must be 0/1 or A/B")

   def write_register(self, reg, value):
      """
      Write an 8-bit value to any device register.
      """
      try:
         self._check(
            self._sbc.i2c_write_byte_data(self._i2c, reg, value & 0xFF),
            "i2c_write_byte_data",
         )
      except Exception as exc:
         raise RuntimeError(
            "I2C write failed on bus {} address 0x{:02X} register 0x{:02X}. "
            "Check MCP23017 address pins (A0-A2), wiring, power, and selected I2C bus."
            .format(self._bus, self._address, reg)
         ) from exc

   def read_register(self, reg):
      """
      Read and return an 8-bit value from any device register.
      """
      try:
         return self._check(
            self._sbc.i2c_read_byte_data(self._i2c, reg),
            "i2c_read_byte_data",
         )
      except Exception as exc:
         raise RuntimeError(
            "I2C read failed on bus {} address 0x{:02X} register 0x{:02X}. "
            "Check MCP23017 address pins (A0-A2), wiring, power, and selected I2C bus."
            .format(self._bus, self._address, reg)
         ) from exc

   def set_pin_mode(self, pin, mode):
      """
      Set one pin as INPUT (1) or OUTPUT (0).
      """
      if mode not in (self.INPUT, self.OUTPUT):
         raise ValueError("mode must be MCP23017.INPUT or MCP23017.OUTPUT")

      port, bit = self._port_and_bit(pin)
      reg = self._IODIRA + port
      iodir = self.read_register(reg)

      if mode == self.INPUT:
         iodir |= (1 << bit)
      else:
         iodir &= ~(1 << bit)

      self.write_register(reg, iodir)

   def set_pullup(self, pin, enabled):
      """
      Enable/disable 100k pull-up for one pin.
      """
      port, bit = self._port_and_bit(pin)
      reg = self._GPPUA + port
      gppu = self.read_register(reg)

      if enabled:
         gppu |= (1 << bit)
      else:
         gppu &= ~(1 << bit)

      self.write_register(reg, gppu)

   def set_polarity_inversion(self, pin, enabled):
      """
      Enable/disable input polarity inversion for one pin.
      """
      port, bit = self._port_and_bit(pin)
      reg = self._IPOLA + port
      ipol = self.read_register(reg)

      if enabled:
         ipol |= (1 << bit)
      else:
         ipol &= ~(1 << bit)

      self.write_register(reg, ipol)

   def write_pin(self, pin, level):
      """
      Set one output pin low (0) or high (1).
      """
      port, bit = self._port_and_bit(pin)
      reg = self._OLATA + port
      value = self.read_register(reg)

      if level:
         value |= (1 << bit)
      else:
         value &= ~(1 << bit)

      self.write_register(self._GPIOA + port, value)

   def read_pin(self, pin):
      """
      Read one input/output pin and return 0 or 1.
      """
      port, bit = self._port_and_bit(pin)
      value = self.read_register(self._GPIOA + port)
      return 1 if (value & (1 << bit)) else 0

   def write_port(self, port, value):
      """
      Write all 8 bits of port A/B.
      """
      idx = self._port_to_index(port)
      self.write_register(self._GPIOA + idx, value)

   def read_port(self, port):
      """
      Read all 8 bits of port A/B.
      """
      idx = self._port_to_index(port)
      return self.read_register(self._GPIOA + idx)

   def write_gpio(self, value16):
      """
      Write all 16 GPIO bits at once.
      """
      self.write_port("A", value16 & 0xFF)
      self.write_port("B", (value16 >> 8) & 0xFF)

   def read_gpio(self):
      """
      Read all 16 GPIO bits and return as a 16-bit integer.
      """
      a = self.read_port("A")
      b = self.read_port("B")
      return a | (b << 8)

   def close(self):
      """
      Release the I2C handle.
      """
      self._check(self._sbc.i2c_close(self._i2c), "i2c_close")

   def __enter__(self):
      return self

   def __exit__(self, exc_type, exc_val, exc_tb):
      self.close()

if __name__ == "__main__":

   RGPIO = False # set to True if using rgpio, False if using lgpio

   import argparse
   import time

   parser = argparse.ArgumentParser(description="MCP23017 example using lgpio/rgpio")
   parser.add_argument("--bus", type=int, default=1, help="I2C bus number (default: 1)")
   parser.add_argument(
      "--address",
      type=lambda x: int(x, 0),
      default=0x20,
      help="I2C address (default: 0x20)",
   )
   parser.add_argument(
      "--scan",
      action="store_true",
      help="scan MCP23017 address range 0x20-0x27 on selected bus and exit",
   )
   args = parser.parse_args()

   if RGPIO:
      try:
         import rgpio
      except ModuleNotFoundError as exc:
         raise SystemExit(
            "rgpio is not installed for this interpreter.\n"
            "Install it with:\n"
            "  python -m pip install ./lg-master/PY_RGPIO"
         ) from exc
      sbc = rgpio.sbc()
      if not sbc.connected:
         raise RuntimeError("not connected to rgpiod")
   else:
      try:
         import lgpio as sbc
      except ModuleNotFoundError as exc:
         raise SystemExit(
            "lgpio is not installed for this interpreter.\n"
            "Install it with:\n"
            "  python -m pip install ./lg-master/PY_LGPIO"
         ) from exc

   def scan_addresses(controller, bus):
      found = []
      for address in range(0x20, 0x28):
         handle = None
         try:
            handle = controller.i2c_open(bus, address)
            controller.i2c_read_byte_data(handle, 0x00)
            found.append(address)
         except Exception:
            pass
         finally:
            if handle is not None:
               try:
                  controller.i2c_close(handle)
               except Exception:
                  pass
      return found

   if args.scan:
      detected = scan_addresses(sbc, args.bus)
      if detected:
         print("Detected MCP23017-like device(s): {}".format(
            ", ".join("0x{:02X}".format(a) for a in detected)
         ))
      else:
         print("No MCP23017 devices detected on bus {}".format(args.bus))
      raise SystemExit(0)

   io = MCP23017(sbc, args.bus, args.address)

   LED_PIN = 0      # GPA0 (output)
   BUTTON_PIN = 8   # GPB0 (input with pull-up)

   io.set_pin_mode(LED_PIN, io.OUTPUT)
   io.set_pin_mode(BUTTON_PIN, io.INPUT)
   io.set_pullup(BUTTON_PIN, True)

   end = time.time() + 10
   state = 0
   while time.time() < end:
      io.write_pin(LED_PIN, state)
      button = io.read_pin(BUTTON_PIN)
      print("LED={}, BUTTON={}".format(state, button))
      state ^= 1
      time.sleep(0.5)

   io.write_pin(LED_PIN, 0)
   io.close()

   if RGPIO:
      sbc.stop()
