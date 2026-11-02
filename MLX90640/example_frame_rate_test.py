#!/usr/bin/env python3
"""Measure MLX90640 frame readout speed and report the maximum usable rate."""

import sys
import time
from statistics import mean

import numpy as np

from mlx90640_backend import ensure_devicetree_backend, refresh_rate_code_to_hz
from mlx90640.mlx90640 import MLX90640


def read_calibrated_frame(camera):
    """Read a single frame and return calibrated temperature values in °C."""
    _ = camera.get_frame_data()
    ta = camera.get_ta()
    return np.array(camera.calculate_to(1.0, ta - 8), dtype=np.float32)


def measure_refresh_rate(camera, refresh_rate_code, sample_count=12):
    """Measure actual readout performance at a given refresh-rate code."""
    camera.set_refresh_rate(refresh_rate_code)
    active_code = camera.get_refresh_rate()
    target_hz = refresh_rate_code_to_hz(active_code)

    # Ignore startup frames that can contain stale checkerboard values.
    for _ in range(2):
        read_calibrated_frame(camera)

    durations = []
    start = time.perf_counter()

    for _ in range(sample_count):
        t0 = time.perf_counter()
        read_calibrated_frame(camera)
        dt = time.perf_counter() - t0
        durations.append(dt)

    elapsed = time.perf_counter() - start
    fps = sample_count / elapsed if elapsed > 0 else 0.0
    avg_latency_ms = mean(durations) * 1000.0 if durations else 0.0
    min_latency_ms = min(durations) * 1000.0 if durations else 0.0
    max_latency_ms = max(durations) * 1000.0 if durations else 0.0

    return {
        "refresh_rate_code": active_code,
        "target_hz": target_hz,
        "samples": sample_count,
        "fps": fps,
        "avg_latency_ms": avg_latency_ms,
        "min_latency_ms": min_latency_ms,
        "max_latency_ms": max_latency_ms,
    }


def main():
    print("=" * 70)
    print("MLX90640 Frame Readout Speed Test")
    print("Checks sustained frame throughput and the maximum usable refresh rate")
    print("=" * 70)

    try:
        ensure_devicetree_backend()
        camera = MLX90640(slave_address=0x33)
        camera.i2c_init()

        rate_codes_to_test = [0, 1, 2, 3, 4, 5, 6, 7]
        results = []

        for rate_code in rate_codes_to_test:
            result = measure_refresh_rate(camera, rate_code, sample_count=10)
            results.append(result)
            print(
                f"Code {result['refresh_rate_code']} ({result['target_hz']:>4g} Hz) | "
                f"Measured: {result['fps']:.2f} fps | "
                f"avg: {result['avg_latency_ms']:.2f} ms | "
                f"min/max: {result['min_latency_ms']:.2f}/{result['max_latency_ms']:.2f} ms"
            )

        best = max(results, key=lambda item: item["fps"])
        print("\n" + "-" * 70)
        print(
            f"Maximum usable configured rate: "
            f"code {best['refresh_rate_code']} ({best['target_hz']:g} Hz)"
        )
        print(f"Measured maximum throughput: {best['fps']:.2f} fps")
        print(f"Average per-frame latency at that rate: {best['avg_latency_ms']:.2f} ms")
        print("\nNotes:")
        print("  • set_refresh_rate() expects register codes 0..7, not literal Hz values.")
        print("  • Code mapping: 0=0.5Hz, 1=1Hz, 2=2Hz, 3=4Hz, 4=8Hz, 5=16Hz, 6=32Hz, 7=64Hz.")
        print("  • The actual Python readout rate is limited by I2C timing and host processing.")
        print("  • The test reports practical host-side throughput for this system.")
        print("=" * 70)

        camera.i2c_tear_down()
        return 0

    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
        return 1
    except Exception as exc:
        print(f"\n❌ Frame-rate test failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
