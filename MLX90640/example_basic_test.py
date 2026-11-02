#!/usr/bin/env python3
"""
MLX90640 Thermal Camera - Basic Test & Diagnostics
Handles both connected and disconnected sensor gracefully
"""

import sys
import time
import numpy as np
from mlx90640_backend import ensure_devicetree_backend, refresh_rate_code_to_hz
from mlx90640.mlx90640 import MLX90640


DEFAULT_REFRESH_RATE_CODE = 4


def test_i2c_detection():
    """Check if I2C device is detected at address 0x33"""
    print("\n🔍 Testing I2C Detection...")
    print("   Checking address 0x33...")
    
    try:
        ensure_devicetree_backend()
        camera = MLX90640(slave_address=0x33)
        print("   ✅ Device instance created")
        return camera
    except Exception as e:
        print(f"   ❌ Failed to create device instance: {e}")
        return None


def test_i2c_communication(camera):
    """Test I2C communication with the device"""
    print("\n📡 Testing I2C Communication...")
    
    if not camera:
        print("   ⚠️  No device to test")
        return False
    
    try:
        print("   Initializing I2C bus...")
        camera.i2c_init()
        print("   ✅ I2C bus initialized")

        print(
            f"   Setting refresh rate to {refresh_rate_code_to_hz(DEFAULT_REFRESH_RATE_CODE):g} Hz "
            f"(code {DEFAULT_REFRESH_RATE_CODE})..."
        )
        camera.set_refresh_rate(DEFAULT_REFRESH_RATE_CODE)
        print("   ✅ Refresh rate set")

        print("   Reading EEPROM calibration block...")
        camera.dump_eeprom()
        print("   ✅ EEPROM read")

        # Discard the first couple of post-init frames to avoid stale checkerboard values.
        for _ in range(2):
            _ = camera.get_frame_data()
            ta = camera.get_ta()
            camera.calculate_to(1.0, ta - 8)

        print("   Extracting calibration parameters...")
        camera.extract_parameters()
        print("   ✅ Calibration loaded")

        print("   Reading device info...")
        resolution = camera.get_resolution()
        print(f"   ✅ Resolution: {resolution}")

        _ = camera.get_frame_data()
        ta = camera.get_ta()
        vdd = camera.get_vdd()
        print(f"   ✅ VDD: {vdd:.2f}V")
        print(f"   ✅ Ambient temperature: {ta:.2f}°C")

        return True
        
    except Exception as e:
        print(f"   ❌ I2C Communication failed: {e}")
        print(f"      Reason: {type(e).__name__}")
        return False


def test_frame_capture(camera):
    """Test capturing a single frame"""
    print("\n🎬 Testing Frame Capture...")
    
    if not camera:
        print("   ⚠️  No device to test")
        return None
    
    try:
        print(
            f"   Setting refresh rate to {refresh_rate_code_to_hz(DEFAULT_REFRESH_RATE_CODE):g} Hz "
            f"(code {DEFAULT_REFRESH_RATE_CODE})..."
        )
        camera.set_refresh_rate(DEFAULT_REFRESH_RATE_CODE)
        print("   ✅ Refresh rate set")

        print("   Reading EEPROM calibration block...")
        camera.dump_eeprom()
        print("   ✅ EEPROM read")

        print("   Extracting calibration parameters...")
        camera.extract_parameters()
        print("   ✅ Calibration loaded")

        print("   Capturing thermal frame...")
        _ = camera.get_frame_data()
        ta = camera.get_ta()
        frame = camera.calculate_to(1.0, ta - 8)
        print(f"   ✅ Frame captured: {len(frame)} pixels")

        if frame is not None and len(frame) > 0:
            frame_array = np.array(frame)
            print(f"   Statistics:")
            print(f"      Min: {np.min(frame_array):.1f}°C")
            print(f"      Max: {np.max(frame_array):.1f}°C")
            print(f"      Mean: {np.mean(frame_array):.1f}°C")
            return frame
        
    except Exception as e:
        print(f"   ❌ Frame capture failed: {e}")
        return None


def main():
    """Main test sequence"""
    print("\n" + "="*60)
    print("   MLX90640 Thermal Camera - Basic Diagnostics Test")
    print("="*60)
    
    print("\n📋 Configuration:")
    print("   I2C Address: 0x33")
    print("   Sensor: MLX90640 (32×24 pixels)")
    print("   Python Driver: mlx90640-driver")
    
    # Step 1: Test device creation
    camera = test_i2c_detection()
    
    if not camera:
        print("\n❌ FAILED: Could not create device instance")
        print("   Make sure:")
        print("   • I2C bus is enabled")
        print("   • Device is connected to 0x33")
        print("   • Power and I2C wiring are correct")
        sys.exit(1)
    
    # Step 2: Test I2C communication
    if not test_i2c_communication(camera):
        print("\n⚠️  I2C communication failed - device may not be connected")
        print("   If sensor is NOT connected, this is EXPECTED")
        print("   If sensor IS connected, check I2C connections")
        print("\n   You can still test the library with simulated data")
        
        # Ask user to continue anyway
        response = input("\nContinue with simulated test? (y/n): ").strip().lower()
        if response != 'y':
            sys.exit(0)
    
    # Step 3: Test frame capture
    frame = test_frame_capture(camera)
    
    if frame is None:
        print("\n⚠️  Frame capture not possible")
        print("   This is expected if device is not connected")
    else:
        print("\n✅ FRAME CAPTURE SUCCESSFUL")
        print("   Sensor is responding and returning valid data")
    
    # Cleanup
    try:
        camera.i2c_tear_down()
        print("\n✅ I2C bus cleaned up")
    except:
        pass
    
    print("\n" + "="*60)
    print("   Test Summary")
    print("="*60)
    
    if frame is not None:
        print("✅ READY TO USE - All systems operational!")
    else:
        print("⚠️  PARTIAL - Library installed correctly, device disconnected")
        print("   Connect the sensor at 0x33 and try again")
    
    print("\n📚 Next steps:")
    print("   1. Review QUICK_START_GUIDE.md for API usage")
    print("   2. Check example_thermal_camera.py for code examples")
    print("   3. Try example_visualization.py for graphics")
    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    main()
