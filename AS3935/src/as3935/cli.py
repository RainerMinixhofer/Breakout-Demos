from __future__ import annotations

import argparse
import json
import time
from typing import Optional

from .driver import AS3935, InterruptReason


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--bus", type=int, default=1, help="I2C bus number (default: 1)")
    common.add_argument("--address", type=lambda value: int(value, 0), default=0x03, help="AS3935 I2C address (default: 0x03)")
    common.add_argument("--irq-chip", default="/dev/gpiochip0", help="GPIO chip path (default: /dev/gpiochip0)")
    common.add_argument("--irq-line", type=int, default=None, help="GPIO line number for the IRQ interrupt pin; omit to use polling mode")
    common.add_argument("--polling", action="store_true", help="Poll the AS3935 interrupt register instead of waiting on the IRQ pin")
    common.add_argument("--poll-interval", type=float, default=0.1, help="Polling interval in seconds (default: 0.1)")
    common.add_argument("--mock", action="store_true", help="Use a mock sensor instead of real hardware")

    parser = argparse.ArgumentParser(description="AS3935 lightning sensor tester", parents=[common])
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Read the current sensor configuration", parents=[common])
    status.set_defaults(handler=_handle_status)

    calibrate = subparsers.add_parser("calibrate", help="Run the AS3935 calibration cycle", parents=[common])
    calibrate.add_argument("--tune-cap", type=int, default=None, help="Tune capacitor value (0-15)")
    calibrate.set_defaults(handler=_handle_calibrate)

    listen = subparsers.add_parser("listen", help="Wait for interrupts and report reason", parents=[common])
    listen.add_argument("--timeout", type=float, default=30.0, help="Seconds to wait before exiting (default: 30)")
    listen.set_defaults(handler=_handle_listen)

    demo = subparsers.add_parser("demo", help="Run a basic sensor test sequence", parents=[common])
    demo.add_argument("--timeout", type=float, default=15.0, help="Seconds to spend listening for events")
    demo.add_argument("--tune-cap", type=int, default=0, help="Tune capacitor value (0-15)")
    demo.set_defaults(handler=_handle_demo)

    return parser


def _connect(args) -> AS3935:
    irq_line = None if getattr(args, "polling", False) else args.irq_line
    return AS3935(
        address=args.address,
        bus=args.bus,
        irq_chip=args.irq_chip,
        irq_line=irq_line,
        mock=args.mock,
    )


def _print_status(sensor: AS3935) -> None:
    status = sensor.get_status()
    print(json.dumps({
        "indoors": status.indoors,
        "noise_floor": status.noise_floor,
        "min_strikes": status.min_strikes,
        "mask_disturber": status.mask_disturber,
        "distance": status.distance,
        "energy": status.energy,
        "interrupt": status.interrupt,
        "interrupt_reason": InterruptReason.describe(status.interrupt),
    }, indent=2, sort_keys=True))


def _handle_status(args):
    sensor = _connect(args)
    try:
        _print_status(sensor)
    finally:
        sensor.close()


def _handle_calibrate(args):
    sensor = _connect(args)
    try:
        sensor.calibrate(args.tune_cap)
        print(f"Calibration complete (tune_cap={args.tune_cap})")
        _print_status(sensor)
    finally:
        sensor.close()


def _handle_listen(args):
    sensor = _connect(args)
    try:
        if args.mock:
            print("Mock mode enabled: simulating interrupts every 2 seconds.")
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                time.sleep(2.0)
                reason = InterruptReason.LIGHTNING
                print(f"Interrupt: {reason:#x} -> {InterruptReason.describe(reason)}")
                print(f"Distance: {sensor.get_distance()}")
                print(f"Energy: {sensor.get_energy()}")
            return

        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            reason = sensor.wait_for_interrupt(timeout=max(0.1, remaining), interval=args.poll_interval)
            if reason is None:
                continue
            print(f"Interrupt: {reason:#x} -> {InterruptReason.describe(reason)}")
            print(f"Distance: {sensor.get_distance()}")
            if reason == InterruptReason.NOISE:
                sensor.raise_noise_floor()
                print(f"Adjusted noise floor to {sensor.get_noise_floor()}")
    finally:
        sensor.close()


def _handle_demo(args):
    sensor = _connect(args)
    try:
        sensor.set_indoors(True)
        sensor.set_noise_floor(2)
        sensor.calibrate(args.tune_cap)
        print("Sensor configured. Waiting for lightning events...")
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if args.mock:
                reason = InterruptReason.LIGHTNING
                print(f"Mock interrupt: {InterruptReason.describe(reason)}")
                print(f"Distance: {sensor.get_distance()}")
                print(f"Energy: {sensor.get_energy()}")
                time.sleep(1.0)
                continue
            reason = sensor.wait_for_interrupt(timeout=max(0.1, remaining), interval=args.poll_interval)
            if reason is None:
                continue
            print(f"Event: {InterruptReason.describe(reason)}")
            print(f"Distance: {sensor.get_distance()}")
            print(f"Energy: {sensor.get_energy()}")
            if reason == InterruptReason.NOISE:
                sensor.raise_noise_floor()
        print("Demo finished.")
    finally:
        sensor.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
