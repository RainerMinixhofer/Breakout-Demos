#include <Arduino.h>
#include "hardware/clocks.h"
#include "hardware/pio.h"
#include "hardware/regs/io_qspi.h"
#include "hardware/structs/ioqspi.h"
#include "hardware/structs/sio.h"
#include "hardware/sync.h"
#include "pico/platform.h"

constexpr uint8_t WS2812_PIN = 16;
constexpr uint8_t PIO_SM = 0;
constexpr uint8_t MAX_BRIGHTNESS = 120;
constexpr uint8_t STEP = 1;
constexpr uint16_t FRAME_DELAY_MS = 16;
constexpr uint8_t BREATH_MIN = 48;
constexpr uint8_t BREATH_MAX = 255;
constexpr uint8_t BREATH_STEP = 2;

static const uint16_t WS2812_PROGRAM_INSTRUCTIONS[] = {
    0x6221,  // out x, 1         side 0 [2]
    0x1123,  // jmp !x, 3        side 1 [1]
    0x1400,  // jmp 0            side 1 [4]
    0xa442,  // nop              side 0 [4]
};

static const pio_program WS2812_PROGRAM = {
    .instructions = WS2812_PROGRAM_INSTRUCTIONS,
    .length = 4,
    .origin = -1,
};

extern "C" {
  int _getpid(void) {
    return 1;
  }

  int _kill(int, int) {
    return -1;
  }
}

void ws2812Init(PIO pio, uint sm, uint offset, uint pin, float freq) {
  pio_sm_config config = pio_get_default_sm_config();
  sm_config_set_wrap(&config, offset, offset + WS2812_PROGRAM.length - 1);
  sm_config_set_sideset(&config, 1, false, false);
  sm_config_set_sideset_pins(&config, pin);
  sm_config_set_out_shift(&config, false, true, 24);
  sm_config_set_fifo_join(&config, PIO_FIFO_JOIN_TX);

  const int cycles_per_bit = 10;
  const float div = static_cast<float>(clock_get_hz(clk_sys)) / (freq * cycles_per_bit);
  sm_config_set_clkdiv(&config, div);

  pio_gpio_init(pio, pin);
  pio_sm_set_consecutive_pindirs(pio, sm, pin, 1, true);
  pio_sm_init(pio, sm, offset, &config);
  pio_sm_set_enabled(pio, sm, true);
}

void ws2812Put(PIO pio, uint sm, uint8_t r, uint8_t g, uint8_t b) {
  const uint32_t grb = (static_cast<uint32_t>(g) << 16) |
                       (static_cast<uint32_t>(r) << 8) |
                       static_cast<uint32_t>(b);
  pio_sm_put_blocking(pio, sm, grb << 8);
}

bool __no_inline_not_in_flash_func(isBootselPressed)() {
  constexpr uint32_t CS_PIN_INDEX = 1U;

  uint32_t irqState = save_and_disable_interrupts();
  hw_write_masked(&ioqspi_hw->io[CS_PIN_INDEX].ctrl,
                  GPIO_OVERRIDE_LOW << IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_LSB,
                  IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_BITS);

  for (volatile uint32_t i = 0; i < 200U; ++i) {
  }

  const bool pressed = (sio_hw->gpio_hi_in & (1U << CS_PIN_INDEX)) == 0U;

  hw_write_masked(&ioqspi_hw->io[CS_PIN_INDEX].ctrl,
                  GPIO_OVERRIDE_NORMAL << IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_LSB,
                  IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_BITS);
  restore_interrupts(irqState);
  return pressed;
}

struct BreathState {
  uint8_t level = BREATH_MIN;
  int8_t direction = 1;
};

uint8_t applyBreathing(uint8_t channel, uint8_t breathLevel) {
  return static_cast<uint8_t>((static_cast<uint16_t>(channel) * breathLevel) / 255U);
}

void updateBreath(BreathState &breath) {
  if (breath.direction > 0) {
    if (breath.level >= BREATH_MAX - BREATH_STEP) {
      breath.level = BREATH_MAX;
      breath.direction = -1;
    } else {
      breath.level = static_cast<uint8_t>(breath.level + BREATH_STEP);
    }
  } else {
    if (breath.level <= BREATH_MIN + BREATH_STEP) {
      breath.level = BREATH_MIN;
      breath.direction = 1;
    } else {
      breath.level = static_cast<uint8_t>(breath.level - BREATH_STEP);
    }
  }
}

bool updateLedToggle(bool &ledEnabled, bool &lastButtonState) {
  static uint32_t lastToggleMs = 0;
  const bool buttonPressed = isBootselPressed();
  if (buttonPressed && !lastButtonState) {
    const uint32_t now = millis();
    if (now - lastToggleMs >= 120U) {
      ledEnabled = !ledEnabled;
      lastToggleMs = now;
      if (!ledEnabled) {
        ws2812Put(pio0, PIO_SM, 0, 0, 0);
      }
    }
  }
  lastButtonState = buttonPressed;
  return ledEnabled;
}

void setup() {
  Serial.begin(115200);
  const uint ws2812Offset = pio_add_program(pio0, &WS2812_PROGRAM);
  ws2812Init(pio0, PIO_SM, ws2812Offset, WS2812_PIN, 800000.0f);
  ws2812Put(pio0, PIO_SM, 0, 0, 0);

  // Allow USB CDC to come up so the host can see a ready message.
  uint32_t start = millis();
  while (!Serial && (millis() - start) < 4000) {
    delay(10);
  }

  Serial.println("RP2040 Zero RGB fade + breathing heartbeat ready. BOOTSEL toggles effect on/off.");
}

bool runPhase(uint8_t startR, uint8_t startG, uint8_t startB, int8_t dR, int8_t dG, int8_t dB,
              BreathState &breath, bool &ledEnabled, bool &lastButtonState) {
  int16_t r = startR;
  int16_t g = startG;
  int16_t b = startB;

  for (uint16_t level = 0; level <= MAX_BRIGHTNESS; level += STEP) {
    if (!updateLedToggle(ledEnabled, lastButtonState)) {
      return false;
    }

    ws2812Put(pio0, PIO_SM, applyBreathing(static_cast<uint8_t>(r), breath.level),
              applyBreathing(static_cast<uint8_t>(g), breath.level),
              applyBreathing(static_cast<uint8_t>(b), breath.level));
    updateBreath(breath);
    r += dR * STEP;
    g += dG * STEP;
    b += dB * STEP;
    delay(FRAME_DELAY_MS);
  }

  return true;
}

void loop() {
  static BreathState breath;
  static bool ledEnabled = true;
  static bool lastButtonState = false;

  if (!updateLedToggle(ledEnabled, lastButtonState)) {
    ws2812Put(pio0, PIO_SM, 0, 0, 0);
    delay(10);
    return;
  }

  // Red -> Green
  if (!runPhase(MAX_BRIGHTNESS, 0, 0, -1, +1, 0, breath, ledEnabled, lastButtonState)) {
    return;
  }

  // Green -> Blue
  if (!runPhase(0, MAX_BRIGHTNESS, 0, 0, -1, +1, breath, ledEnabled, lastButtonState)) {
    return;
  }

  // Blue -> Red
  runPhase(0, 0, MAX_BRIGHTNESS, +1, 0, -1, breath, ledEnabled, lastButtonState);
}
