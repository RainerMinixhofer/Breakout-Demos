#!/usr/bin/env python3
"""
MLX90640 Thermal Image Visualization Example
Requires: matplotlib, numpy
"""

import sys
import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.colors import Normalize
from mlx90640_backend import ensure_devicetree_backend, refresh_rate_code_to_hz
from mlx90640.mlx90640 import MLX90640


class ThermalImageViewer:
    """Real-time thermal image visualization"""
    
    def __init__(self, i2c_address=0x33, refresh_rate_code=4):
        """Initialize camera and display"""
        try:
            ensure_devicetree_backend()
            self.camera = MLX90640(slave_address=i2c_address)
            self.camera.i2c_init()
            self.camera.set_refresh_rate(refresh_rate_code)
            self.camera.dump_eeprom()
            self.camera.extract_parameters()

            # The first post-init frame can contain stale / partially updated pixels,
            # which show up as alternating 0°C values before the sensor settles.
            for _ in range(2):
                self._read_frame()

            print(f"✅ Camera initialized at 0x{i2c_address:02X}")
            print(f"   Refresh rate: {refresh_rate_code_to_hz(refresh_rate_code):g} Hz "
                  f"(code {refresh_rate_code})")
        except Exception as e:
            print(f"❌ Camera initialization failed: {e}")
            sys.exit(1)

    def _read_frame(self):
        """Read a calibrated thermal frame as a 768-element temperature array."""
        _ = self.camera.get_frame_data()
        ta = self.camera.get_ta()
        return np.array(self.camera.calculate_to(1.0, ta - 8), dtype=np.float32)
    
    def capture_and_display_single(self, filename=None):
        """Capture and display a single thermal frame"""
        
        try:
            # Capture frame
            frame = self._read_frame()
            
            # Reshape to 24x32 image
            image = frame.reshape(24, 32)
            
            # Create figure with temperature colorbar
            fig, ax = plt.subplots(figsize=(12, 9))
            
            # Display thermal image
            im = ax.imshow(image, cmap='hot', interpolation='bilinear')
            
            # Add colorbar
            cbar = plt.colorbar(im, ax=ax, label='Temperature (°C)')
            
            # Labels and title
            ax.set_xlabel('X (pixels)')
            ax.set_ylabel('Y (pixels)')
            ax.set_title(f'MLX90640 Thermal Image\n'
                        f'Min: {np.min(image):.1f}°C | '
                        f'Max: {np.max(image):.1f}°C | '
                        f'Mean: {np.mean(image):.1f}°C')
            
            # Add grid
            ax.set_xticks(np.arange(0, 32, 4))
            ax.set_yticks(np.arange(0, 24, 4))
            ax.grid(True, alpha=0.3, linestyle='--')
            
            plt.tight_layout()
            
            # Save if filename provided
            if filename:
                plt.savefig(filename, dpi=150, bbox_inches='tight')
                print(f"✅ Image saved to {filename}")
            
            plt.show()
            
        except Exception as e:
            print(f"❌ Error: {e}")
    
    def capture_multiple_frames(self, num_frames=10, interval=0.5):
        """Capture multiple frames and create a grid view"""
        
        frames = []
        
        print(f"Capturing {num_frames} frames...")
        
        try:
            for i in range(num_frames):
                frame = self._read_frame()
                frames.append(frame.reshape(24, 32))
                print(f"  Frame {i+1}/{num_frames} - "
                      f"Temp: {np.min(frame):.1f}°C - {np.max(frame):.1f}°C")
                time.sleep(interval)
            
            # Create grid of thermal images
            rows = int(np.sqrt(num_frames))
            cols = int(np.ceil(num_frames / rows))
            
            fig, axes = plt.subplots(rows, cols, figsize=(15, 10))
            axes = axes.flatten()
            
            # Normalize colorscale across all frames for consistency
            all_temps = np.concatenate([f.flatten() for f in frames])
            vmin, vmax = np.percentile(all_temps, [2, 98])
            
            for idx, frame in enumerate(frames):
                im = axes[idx].imshow(frame, cmap='hot', 
                                     vmin=vmin, vmax=vmax,
                                     interpolation='bilinear')
                axes[idx].set_title(f'Frame {idx+1}\n'
                                   f'Min: {np.min(frame):.1f}°C, '
                                   f'Max: {np.max(frame):.1f}°C')
                axes[idx].set_xticks([])
                axes[idx].set_yticks([])
            
            # Hide unused subplots
            for idx in range(num_frames, len(axes)):
                axes[idx].axis('off')
            
            # Add single colorbar for all
            fig.colorbar(im, ax=axes, orientation='horizontal', 
                        pad=0.05, label='Temperature (°C)')
            
            plt.tight_layout()
            plt.show()
            
        except Exception as e:
            print(f"❌ Capture error: {e}")
    
    def create_temperature_profile(self, direction='horizontal'):
        """Extract and plot temperature profile through image center"""
        
        try:
            frame = self._read_frame()
            image = frame.reshape(24, 32)
            
            if direction == 'horizontal':
                profile = image[12, :]  # Middle row
                axis_label = 'X (pixels)'
            else:  # vertical
                profile = image[:, 16]  # Middle column
                axis_label = 'Y (pixels)'
            
            fig, ax = plt.subplots(figsize=(12, 5))
            
            # Plot temperature profile
            x = np.arange(len(profile))
            ax.plot(x, profile, 'r-', linewidth=2, marker='o', markersize=4)
            ax.fill_between(x, profile, alpha=0.3)
            
            # Labels
            ax.set_xlabel(axis_label)
            ax.set_ylabel('Temperature (°C)')
            ax.set_title(f'Thermal Profile ({direction.capitalize()})\n'
                        f'Min: {np.min(profile):.1f}°C | '
                        f'Max: {np.max(profile):.1f}°C')
            ax.grid(True, alpha=0.3)
            
            plt.tight_layout()
            plt.show()
            
        except Exception as e:
            print(f"❌ Error: {e}")


def main():
    """Example visualization modes"""
    
    print("MLX90640 Thermal Image Visualization")
    print("=" * 50)
    
    viewer = ThermalImageViewer(i2c_address=0x33, refresh_rate_code=4)
    
    print("\nVisualization options:")
    print("1. Single frame")
    print("2. Multiple frames (grid)")
    print("3. Temperature profile")
    
    try:
        choice = input("\nSelect option (1-3): ").strip()
        
        if choice == "1":
            viewer.capture_and_display_single("thermal_image.png")
        elif choice == "2":
            viewer.capture_multiple_frames(num_frames=9, interval=0.5)
        elif choice == "3":
            direction = input("Direction (h/v) [default: h]: ").strip().lower()
            direction = 'horizontal' if direction != 'v' else 'vertical'
            viewer.create_temperature_profile(direction)
        else:
            print("Invalid option")
            
    except KeyboardInterrupt:
        print("\n⚠️  Visualization interrupted")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
