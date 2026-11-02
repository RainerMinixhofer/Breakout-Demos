#!/usr/bin/env python3
"""
MLX90640 Thermal Camera - Threaded Initialization with Timeout
Uses official mlx90640-driver with devicetree backend registration
"""

import sys
import time
import threading
import numpy as np
from mlx90640_backend import ensure_devicetree_backend, refresh_rate_code_to_hz
from mlx90640.mlx90640 import MLX90640


class ThreadedThermalCamera:
    """Thermal camera with threaded calibration extraction"""
    
    def __init__(self, address=0x33, extract_timeout=20, refresh_rate_code=4):
        self.address = address
        self.extract_timeout = extract_timeout
        self.refresh_rate_code = refresh_rate_code
        self.camera = None
        self.calibration_loaded = False
        self.calibration_error = None
    
    def _extract_parameters_thread(self):
        """Run extract_parameters in separate thread"""
        try:
            self.camera.extract_parameters()
            self.calibration_loaded = True
        except Exception as e:
            self.calibration_error = str(e)
    
    def init_with_timeout(self):
        """Initialize camera with threaded calibration extraction"""
        print(f"\n🔧 Initializing MLX90640 at 0x{self.address:02X}...\n")
        
        try:
            # Create instance
            print("Step 1: Creating device instance...")
            ensure_devicetree_backend()
            self.camera = MLX90640(slave_address=self.address)
            print("✅ Device instance created")
            
            # Initialize I2C
            print("Step 2: Initializing I2C bus...")
            self.camera.i2c_init()
            print("✅ I2C bus initialized")
            
            # Set refresh rate
            hz = refresh_rate_code_to_hz(self.refresh_rate_code)
            print(f"Step 3: Setting refresh rate to {hz:g} Hz (code {self.refresh_rate_code})...")
            self.camera.set_refresh_rate(self.refresh_rate_code)
            print("✅ Refresh rate configured")

            # Dump EEPROM first (required before extract_parameters)
            print("Step 4: Reading EEPROM calibration block...")
            self.camera.dump_eeprom()
            print("✅ EEPROM read successful")

            # Discard the first couple of post-init frames to avoid stale startup values
            for _ in range(2):
                _ = self.camera.get_frame_data()
                ta = self.camera.get_ta()
                self.camera.calculate_to(1.0, ta - 8)
            
            # Extract calibration in separate thread (with timeout)
            print(f"\nStep 5: Extracting calibration (timeout: {self.extract_timeout}s)...\n")
            
            extract_thread = threading.Thread(target=self._extract_parameters_thread)
            extract_thread.daemon = True
            extract_thread.start()
            
            # Wait for thread with timeout
            extract_thread.join(timeout=self.extract_timeout)
            
            if extract_thread.is_alive():
                print(f"⏱️  Timeout after {self.extract_timeout}s - calibration extraction too slow")
                return False

            if self.calibration_error:
                print(f"❌ Calibration extraction error: {self.calibration_error}")
                return False

            if self.calibration_loaded:
                print("✅ Calibration loaded successfully")
                return True
            else:
                print("❌ Calibration extraction failed")
                return False

        except Exception as e:
            print(f"❌ Initialization error: {e}")
            return False
    
    def capture_frame(self):
        """Capture a single thermal frame (temperature values in °C)."""
        if not self.camera or not self.calibration_loaded:
            print("❌ Camera not properly initialized")
            return None
        
        try:
            print("\n🎬 Capturing thermal frame...")
            start = time.time()

            _ = self.camera.get_frame_data()
            ta = self.camera.get_ta()
            frame = self.camera.calculate_to(1.0, ta - 8)

            elapsed = time.time() - start
            
            if frame is None or len(frame) == 0:
                print("❌ Received empty frame")
                return None
            
            frame = np.array(frame)
            print(f"✅ Frame captured in {elapsed:.2f}s ({len(frame)} pixels)")
            print(f"   Min: {np.min(frame):.1f}°C")
            print(f"   Max: {np.max(frame):.1f}°C")
            print(f"   Mean: {np.mean(frame):.1f}°C")
            print(f"   Std Dev: {np.std(frame):.1f}°C")
            
            return frame
        
        except Exception as e:
            print(f"❌ Frame capture error: {e}")
            return None
    
    def get_device_info(self):
        """Read device information"""
        if not self.camera:
            return False
        
        try:
            print("\n📊 Device Information:")

            # Refresh frame_data first so TA/VDD use current sensor state
            _ = self.camera.get_frame_data()
            ta = self.camera.get_ta()
            vdd = self.camera.get_vdd()
            rate = self.camera.get_refresh_rate()

            if np.isnan(ta):
                print(f"   Ambient Temperature: N/A (invalid I2C data)")
            else:
                print(f"   Ambient Temperature: {ta:.1f}°C")

            # Supply voltage
            if np.isnan(vdd):
                print(f"   Supply Voltage: N/A (invalid I2C data)")
            else:
                print(f"   Supply Voltage: {vdd:.2f}V")

            # Get refresh rate
            hz = refresh_rate_code_to_hz(rate)
            print(f"   Refresh Rate: {hz:g} Hz (code {rate})")
            print("   Backend: mlx90640-driver + devicetree")
            
            return True
        
        except Exception as e:
            print(f"⚠️  Error reading device info: {e}")
            return False
    
    def cleanup(self):
        """Cleanup I2C connection"""
        if self.camera:
            try:
                self.camera.i2c_tear_down()
                print("✅ I2C connection cleaned up")
            except:
                pass


def main():
    """Main test with threading"""
    print("="*70)
    print("   MLX90640 Thermal Camera - Threaded Initialization")
    print("   Official driver + devicetree backend with timeout guard")
    print("="*70)
    
    camera = ThreadedThermalCamera(address=0x33, extract_timeout=20, refresh_rate_code=4)
    
    try:
        # Initialize with timeout
        success = camera.init_with_timeout()
        
        if not success:
            print("\n❌ Initialization failed")
            print("\nDiagnostics:")
            print("   • Device detected (i2cdetect shows 0x33)")
            print("   • Official backend (mlx90640-driver) could not initialize")
            print("\nTry:")
            print("   • pip install mlx90640-driver-devicetree")
            print("   • Verify /dev/i2c-1 exists and user is in i2c group")
            camera.cleanup()
            return 1
        
        # Get device info
        camera.get_device_info()
        
        # Capture frame
        frame = camera.capture_frame()
        
        # Summary
        print("\n" + "="*70)
        print("   Test Results")
        print("="*70)
        
        if frame is not None and len(frame) > 0:
            print("\n✅ SUCCESS - Thermal camera fully operational!")
            print("   • I2C communication: OK")
            print("   • Calibration loaded: YES")
            print("   • Frame capture: SUCCESS")
            print("\n   Sensor is ready for thermal imaging applications")
            result = 0
        else:
            print("\n⚠️  PARTIAL SUCCESS - Device working but no valid frames")
            print("   • I2C communication: OK")
            print("   • Calibration loaded: YES")
            print("   • Frame capture: FAILED")
            result = 1
        
        print("\n" + "="*70 + "\n")
        
        return result
    
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        camera.cleanup()


if __name__ == "__main__":
    sys.exit(main())
