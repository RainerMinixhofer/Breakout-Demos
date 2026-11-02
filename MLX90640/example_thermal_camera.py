#!/usr/bin/env python3
"""
MLX90640 Thermal Camera - Basic Implementation Example
Uses the recommended mlx90640-driver package
"""

import sys
import time
import numpy as np
from mlx90640_backend import (
    ensure_devicetree_backend,
    refresh_rate_code_to_hz,
)
from mlx90640.mlx90640 import MLX90640


class ThermalCamera:
    """Wrapper class for MLX90640 thermal camera at I2C address 0x33"""
    
    def __init__(self, i2c_address=0x33, refresh_rate_code=4):
        """
        Initialize thermal camera.
        
        Args:
            i2c_address: I2C slave address (default: 0x33 = 51 decimal)
            refresh_rate_code: Sensor refresh-rate register code (0-7, default: 4 = 8Hz)
        """
        try:
            ensure_devicetree_backend()

            # MLX90640 driver only takes slave address
            self.camera = MLX90640(slave_address=i2c_address)
            
            # Initialize I2C bus (will auto-detect bus)
            self.camera.i2c_init()
            
            # Set refresh rate register code (0..7)
            self.camera.set_refresh_rate(refresh_rate_code)

            # Read EEPROM calibration block
            self.camera.dump_eeprom()
            
            # Extract calibration parameters
            self.camera.extract_parameters()

            # Discard a couple of startup frames. The first post-init frames can
            # contain stale checkerboard values before the sensor fully settles.
            for _ in range(2):
                self.capture_frame()
            
            print(f"✅ MLX90640 initialized at address 0x{i2c_address:02X}")
            print(f"   Resolution: 32×24 pixels (768 total)")
            print(f"   Refresh rate: {refresh_rate_code_to_hz(refresh_rate_code):g} Hz "
                  f"(code {refresh_rate_code})")
            print(f"   Temperature range: -40°C to +85°C")
            
        except Exception as e:
            print(f"❌ Failed to initialize camera: {e}")
            print(f"   (Make sure I2C device is connected at address 0x{i2c_address:02X})")
            sys.exit(1)
    
    def capture_frame(self):
        """
        Capture a single thermal frame.
        
        Returns:
            numpy array: 768-element array of temperatures in °C, or None on error
        """
        try:
            _ = self.camera.get_frame_data()
            ta = self.camera.get_ta()
            return self.camera.calculate_to(1.0, ta - 8)
        except Exception as e:
            print(f"❌ Frame capture failed: {e}")
            return None
    
    def get_statistics(self, frame):
        """
        Calculate thermal statistics for a frame.
        
        Args:
            frame: Thermal frame data (list of temperatures)
            
        Returns:
            dict: Statistics including min, max, mean, median
        """
        if not frame:
            return None
        
        frame_array = np.array(frame)
        return {
            "min": np.min(frame_array),
            "max": np.max(frame_array),
            "mean": np.mean(frame_array),
            "median": np.median(frame_array),
            "std": np.std(frame_array)
        }
    
    def get_2d_array(self, frame):
        """
        Convert 1D frame to 2D image array (24 rows × 32 columns).
        
        Args:
            frame: 1D thermal frame (768 elements)
            
        Returns:
            numpy.ndarray: 24×32 2D array
        """
        if not frame or len(frame) != 768:
            return None
        return np.array(frame).reshape(24, 32)
    
    def detect_hotspots(self, frame, threshold_percentile=95):
        """
        Detect hotspots above a temperature threshold.
        
        Args:
            frame: Thermal frame data
            threshold_percentile: Percentile above which to flag hotspots (0-100)
            
        Returns:
            dict: Hotspot analysis
        """
        frame_array = np.array(frame)
        threshold_temp = np.percentile(frame_array, threshold_percentile)
        hotspot_pixels = np.sum(frame_array > threshold_temp)
        
        return {
            "threshold_temperature": threshold_temp,
            "hotspot_count": hotspot_pixels,
            "hotspot_percentage": (hotspot_pixels / len(frame)) * 100,
            "max_temperature": np.max(frame_array),
            "max_pixel_index": np.argmax(frame_array)
        }


def main():
    """Example usage: Capture and analyze thermal frames"""
    
    print("MLX90640 Thermal Camera Example")
    print("=" * 50)
    
    # Initialize camera at I2C address 0x33
    camera = ThermalCamera(i2c_address=0x33, refresh_rate_code=4)
    
    print("\nCapturing 5 thermal frames...\n")
    
    try:
        for frame_num in range(5):
            # Capture frame
            frame = camera.capture_frame()
            if frame is None:
                continue
            
            # Get statistics
            stats = camera.get_statistics(frame)
            
            print(f"Frame {frame_num + 1}:")
            print(f"  Temperature: min={stats['min']:.1f}°C, "
                  f"max={stats['max']:.1f}°C, mean={stats['mean']:.1f}°C")
            
            # Detect hotspots (above 95th percentile)
            hotspots = camera.detect_hotspots(frame, threshold_percentile=95)
            if hotspots['hotspot_count'] > 0:
                print(f"  Hotspots: {hotspots['hotspot_count']} pixels "
                      f"({hotspots['hotspot_percentage']:.1f}%) "
                      f"above {hotspots['threshold_temperature']:.1f}°C")
            
            # Get 2D representation
            image_2d = camera.get_2d_array(frame)
            if image_2d is not None:
                print(f"  2D Image: {image_2d.shape}")
            
            print()
            time.sleep(0.5)  # Wait between captures
        
        print("✅ Thermal capture completed successfully!")
        
    except KeyboardInterrupt:
        print("\n⚠️  Capture interrupted by user")
    except Exception as e:
        print(f"❌ Capture failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
