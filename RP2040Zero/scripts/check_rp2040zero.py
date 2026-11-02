#!/usr/bin/env python3
"""Check RP2040 Zero connectivity and optionally upload firmware with PlatformIO.

Usage examples:
  python3 scripts/check_rp2040zero.py
  python3 scripts/check_rp2040zero.py --upload
  python3 scripts/check_rp2040zero.py --upload --port /dev/ttyACM0
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = "rp2040zero"
DEFAULT_PIO_CANDIDATES = (
    "pio",
    str(Path.home() / ".local/bin/pio"),
)


@dataclass
class Device:
    port: str
    description: str


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def ensure_pio_available() -> None:
    if resolve_pio_executable() is None:
        print("ERROR: PlatformIO CLI not found in PATH or ~/.local/bin.")
        print("  pipx install platformio")
        print("If installed with pipx, add this to your shell profile:")
        print("  export PATH=\"$HOME/.local/bin:$PATH\"")
        sys.exit(1)


def resolve_pio_executable() -> str | None:
    explicit = os.environ.get("PIO_EXE", "").strip()
    if explicit:
        return explicit if Path(explicit).exists() else None

    for candidate in DEFAULT_PIO_CANDIDATES:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        if Path(candidate).exists():
            return candidate

    return None


def parse_devices(raw_devices: Iterable[dict]) -> list[Device]:
    devices: list[Device] = []
    for entry in raw_devices:
        port = str(entry.get("port", "")).strip()
        if not port:
            continue

        fields = [
            str(entry.get("description", "")),
            str(entry.get("hwid", "")),
            str(entry.get("vid", "")),
            str(entry.get("pid", "")),
        ]
        description = " | ".join(field for field in fields if field).strip() or "Unknown"
        devices.append(Device(port=port, description=description))
    return devices


def list_serial_devices(pio_exe: str) -> list[Device]:
    result = run_command([pio_exe, "device", "list", "--json-output"])
    if result.returncode != 0:
        print("ERROR: Failed to list serial devices via PlatformIO.")
        if result.stderr.strip():
            print(result.stderr.strip())
        sys.exit(result.returncode)

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print("ERROR: Could not parse PlatformIO device list JSON output:")
        print(str(exc))
        sys.exit(1)

    if not isinstance(payload, list):
        print("ERROR: Unexpected PlatformIO device list format.")
        sys.exit(1)

    return parse_devices(payload)


def pick_rp2040_port(devices: list[Device]) -> str | None:
    markers = (
        "rp2040",
        "usb serial",
        "cdc",
        "acm",
        "tinyusb",
    )
    for device in devices:
        haystack = f"{device.port} {device.description}".lower()
        if any(marker in haystack for marker in markers):
            return device.port
    return None


def run_upload(pio_exe: str, environment: str, port: str | None) -> int:
    command = [pio_exe, "run", "-e", environment, "-t", "upload"]
    if port:
        command.extend(["--upload-port", port])

    print("\nRunning:", " ".join(command))
    result = subprocess.run(command, cwd=PROJECT_ROOT, text=True, check=False)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check RP2040 Zero connection and optionally upload the Arduino Blink test.",
    )
    parser.add_argument(
        "--env",
        default=DEFAULT_ENV,
        help=f"PlatformIO environment name (default: {DEFAULT_ENV})",
    )
    parser.add_argument(
        "--port",
        default=None,
        help="Serial port override, e.g. /dev/ttyACM0",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Build and upload firmware after connection check",
    )
    args = parser.parse_args()

    ensure_pio_available()
    pio_exe = resolve_pio_executable()
    if not pio_exe:
        print("ERROR: PlatformIO CLI resolution failed unexpectedly.")
        return 1

    devices = list_serial_devices(pio_exe)
    print("Detected serial devices:")
    if not devices:
        print("  (none)")
    else:
        for device in devices:
            print(f"  - {device.port}: {device.description}")

    selected_port = args.port or pick_rp2040_port(devices)
    if selected_port:
        print(f"\nCandidate RP2040 port: {selected_port}")
    else:
        print("\nNo obvious RP2040 port detected.")
        print("If the board is in BOOTSEL mode, it may appear as a USB mass-storage device first.")
        print("Try reconnecting the board or pass --port explicitly.")

    if not args.upload:
        print("\nConnectivity check complete. Re-run with --upload to program the board.")
        return 0

    return run_upload(pio_exe, args.env, args.port or selected_port)


if __name__ == "__main__":
    sys.exit(main())
