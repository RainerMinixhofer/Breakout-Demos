#!/usr/bin/env python3
"""
Helpers to ensure mlx90640-driver is wired to the Linux devicetree I2C backend.
"""

REFRESH_RATE_CODE_TO_HZ = {
    0: 0.5,
    1: 1.0,
    2: 2.0,
    3: 4.0,
    4: 8.0,
    5: 16.0,
    6: 32.0,
    7: 64.0,
}


def refresh_rate_code_to_hz(rate_code):
    """Convert MLX90640 refresh-rate register code (0..7) to nominal Hz."""
    try:
        return REFRESH_RATE_CODE_TO_HZ[int(rate_code)]
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Invalid refresh-rate code: {rate_code}. Expected 0..7.") from exc


def refresh_rate_hz_to_code(rate_hz):
    """Convert nominal MLX90640 refresh-rate Hz to register code (0..7)."""
    canonical_hz = {
        0.5: 0,
        1.0: 1,
        2.0: 2,
        4.0: 3,
        8.0: 4,
        16.0: 5,
        32.0: 6,
        64.0: 7,
    }
    try:
        return canonical_hz[float(rate_hz)]
    except (ValueError, KeyError) as exc:
        raise ValueError(
            f"Invalid refresh-rate Hz: {rate_hz}. "
            "Expected one of: 0.5, 1, 2, 4, 8, 16, 32, 64."
        ) from exc


def ensure_devicetree_backend():
    """
    Load mlx90640-driver devicetree backend registration.

    The upstream `mlx90640-driver` package requires a separate backend package on
    Linux SBCs (`mlx90640-driver-devicetree`) so I2C calls are routed to
    `/dev/i2c-*`.
    """
    try:
        import mlx90640_devicetree  # noqa: F401 - import has required side effects
    except Exception as exc:
        raise RuntimeError(
            "Failed to load mlx90640 devicetree backend. "
            "Install with: pip install mlx90640-driver-devicetree"
        ) from exc
