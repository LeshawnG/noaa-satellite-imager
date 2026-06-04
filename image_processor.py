"""
Image Processor Module for Satellite Weather Looping System
Handles processing of downloaded satellite images including cropping, labeling, and timezone conversion
Designed for 24/7 continuous operation
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageColor
from concurrent.futures import ThreadPoolExecutor, as_completed
import queue
import hashlib

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    BANDS, IMAGES_DIR, LOGS_DIR, IMAGE_SETTINGS, CROP_SETTINGS, LABEL_CONFIG,
    GRID_THUMBNAIL_CONFIG, parse_timestamp, get_local_time, TRINIDAD_LOCATION
)

class ImageProcessor:
    """Handles processing of satellite images for display"""
    
    def __init__(self, logger=None):
        """Initialize the image processor for 24/7 operation"""
        self.logger = logger or self._setup_logger()
        self.processing_queue = queue.Queue()
        self.processed_images = set()  # Track processed images
        self.stop_event = threading.Event()
        self.monitor_threads = []
        self.processing_threads = []
        
        # Load font for labels
        self.font = self._load_font()
        
        # Load existing processed images
        self._load_processed_history()
        
        # Start monitoring and processing threads
        self._start_workers()
        
        self.logger.info("Image Processor initialized for 24/7 operation")
    
    def _setup_logger(self):
        """Set up logging for the processor"""
        logger = logging.getLogger('ImageProcessor')
        
        # Only set up handlers if they don't already exist
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # File handler with rotation for 24/7 operation
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                os.path.join(LOGS_DIR, 'image_processor.log'),
                maxBytes=10485760,  # 10MB
                backupCount=5
            )
            file_handler.setLevel(logging.INFO)
            
            # Formatter
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            file_handler.setFormatter(formatter)
            
            logger.addHandler(console_handler)
            logger.addHandler(file_handler)

            # Don't propagate to the root logger (app.py's basicConfig adds its
            # own console handler) — otherwise every line is printed twice.
            logger.propagate = False
        
        return logger
    
    def _load_font(self):
        """Load font for image labels"""
        try:
            # Try to load a system font
            font_size = LABEL_CONFIG['font_size']
            font_options = [
                '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                'C:/Windows/Fonts/arial.ttf',
                '/System/Library/Fonts/Helvetica.ttc'
            ]
            
            for font_path in font_options:
                if os.path.exists(font_path):
                    return ImageFont.truetype(font_path, font_size)
            
            # Fallback to default font
            return ImageFont.load_default()
            
        except Exception as e:
            self.logger.warning(f"Could not load font: {e}. Using default.")
            return ImageFont.load_default()
    
    def _load_processed_history(self):
        """Load history of already processed images"""
        for band_key, band_info in BANDS.items():
            zoom_base = os.path.join(IMAGES_DIR, band_info['folder_name'], 'Zoom')
            
            for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                zoom_dir = os.path.join(zoom_base, zoom_level)
                if os.path.exists(zoom_dir):
                    for filename in os.listdir(zoom_dir):
                        if filename.endswith('.jpg') and not filename.startswith('._'):
                            # Create hash of band, zoom, and filename
                            history_key = self._get_history_key(band_key, zoom_level, filename)
                            self.processed_images.add(history_key)
        
        self.logger.info(f"Loaded {len(self.processed_images)} processed images into history")
    
    def _get_history_key(self, band_key, zoom_level, filename):
        """Generate a unique key for tracking processed images"""
        return f"{band_key}_{zoom_level}_{filename}"
    
    def _start_workers(self):
        """Start worker threads for 24/7 operation"""
        # Start monitoring thread for each band
        for band_key in BANDS.keys():
            thread = threading.Thread(
                target=self._monitor_band_directory,
                args=(band_key,),
                daemon=True
            )
            thread.start()
            self.monitor_threads.append(thread)
        
        # Start processing threads
        num_processors = 2  # Adjust based on system capabilities
        for i in range(num_processors):
            thread = threading.Thread(
                target=self._process_queue_worker,
                daemon=True
            )
            thread.start()
            self.processing_threads.append(thread)
        
        # Start cleanup thread
        cleanup_thread = threading.Thread(
            target=self._cleanup_worker,
            daemon=True
        )
        cleanup_thread.start()
        
        self.logger.info(f"Started {len(self.monitor_threads)} monitor threads and {num_processors} processing threads")
    
    def _monitor_band_directory(self, band_key):
        """Monitor a band's raw_images directory for new images"""
        band_info = BANDS[band_key]
        raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
        
        # Create directory if it doesn't exist
        os.makedirs(raw_dir, exist_ok=True)
        
        processed_files = set()
        
        while not self.stop_event.is_set():
            try:
                # Check for new files, excluding macOS metadata files
                current_files = set(f for f in os.listdir(raw_dir) 
                                   if f.endswith('.jpg') and not f.startswith('._'))
                new_files = current_files - processed_files
                
                for filename in new_files:
                    # Check if already processed
                    already_processed = False
                    for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                        history_key = self._get_history_key(band_key, zoom_level, filename)
                        if history_key in self.processed_images:
                            already_processed = True
                            break
                    
                    if not already_processed:
                        # Add to processing queue
                        self.processing_queue.put({
                            'band_key': band_key,
                            'filename': filename,
                            'raw_path': os.path.join(raw_dir, filename)
                        })
                        self.logger.debug(f"Queued for processing: {band_info['label']} - {filename}")
                    
                    processed_files.add(filename)
                
                # Sleep before checking again
                time.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                self.logger.error(f"Error monitoring {band_key}: {e}")
                time.sleep(30)  # Wait longer on error
    
    def _process_queue_worker(self):
        """Worker thread to process images from the queue"""
        while not self.stop_event.is_set():
            try:
                # Get item from queue with timeout
                item = self.processing_queue.get(timeout=5)
                
                # Process the image
                self._process_single_image(
                    item['band_key'],
                    item['filename'],
                    item['raw_path']
                )
                
                self.processing_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Error in processing worker: {e}")
                time.sleep(1)
    
    def _process_single_image(self, band_key, filename, raw_path):
        """Process a single image through all zoom levels"""
        band_info = BANDS[band_key]
        
        try:
            # Validate file before processing
            if not self._validate_image_file(raw_path):
                self.logger.warning(f"Skipping invalid or incomplete file: {filename}")
                return
            
            # Open the raw image
            with Image.open(raw_path) as img:
                # Verify image dimensions
                if img.size != tuple(IMAGE_SETTINGS['source_resolution']):
                    self.logger.warning(f"Unexpected image size for {filename}: {img.size}")
                    return
                
                # Extract timestamp from filename
                timestamp_str = filename.split('_')[0]
                image_dt = parse_timestamp(timestamp_str)
                local_dt = get_local_time(image_dt)
                
                # Format timestamp for label
                timestamp_label = local_dt.strftime("%Y-%m-%d %H:%M GMT-4")
                
                # Process each zoom level
                for zoom_level, zoom_config in CROP_SETTINGS.items():
                    # Check if already processed
                    history_key = self._get_history_key(band_key, zoom_level, filename)
                    if history_key in self.processed_images:
                        continue
                    
                    # Process this zoom level
                    success = self._process_zoom_level(
                        img,
                        band_info,
                        filename,
                        zoom_level,
                        zoom_config,
                        timestamp_label
                    )
                    
                    if success:
                        self.processed_images.add(history_key)
                
                self.logger.info(f"Processed: {band_info['label']} - {filename}")
                
        except Exception as e:
            self.logger.error(f"Error processing {raw_path}: {e}")
    
    def _validate_image_file(self, file_path):
        """Validate that image file is complete and not corrupted"""
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                return False
            
            # Check minimum file size (should be at least 100KB for these large images)
            file_size = os.path.getsize(file_path)
            if file_size < 100 * 1024:  # 100KB minimum
                return False
            
            # Wait for file to be stable (not being written to)
            initial_size = file_size
            time.sleep(0.2)  # Short wait
            current_size = os.path.getsize(file_path)
            
            if current_size != initial_size:
                # File is still being written
                return False
            
            # Try to open and verify the image
            try:
                with Image.open(file_path) as img:
                    # Try to load the image completely to detect truncation
                    img.load()
                    
                    # Check if it has the expected dimensions
                    expected_size = tuple(IMAGE_SETTINGS['source_resolution'])
                    if img.size != expected_size:
                        self.logger.warning(f"Image size mismatch: expected {expected_size}, got {img.size}")
                        return False
                    
                return True
                
            except Exception as e:
                self.logger.warning(f"Image validation failed for {file_path}: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error validating file {file_path}: {e}")
            return False
    
    def _process_zoom_level(self, img, band_info, filename, zoom_level, zoom_config, timestamp_label):
        """Process image for a specific zoom level with improved cropping logic to prevent stretching"""
        try:
            # Get crop and output configuration
            crop_box = zoom_config['coordinates']
            output_size = tuple(zoom_config['output_size'])
            target_width, target_height = output_size
            target_aspect_ratio = target_width / target_height
            
            # Crop the initial region
            cropped = img.crop(crop_box)
            crop_width, crop_height = cropped.size
            crop_aspect_ratio = crop_width / crop_height
            
            # Calculate the best way to fit the crop into the target size
            # while maintaining aspect ratio and prioritizing resolution
            
            if abs(crop_aspect_ratio - target_aspect_ratio) < 0.01:
                # Aspect ratios are very close, can resize directly
                resized = cropped.resize(output_size, Image.Resampling.LANCZOS)
                
            elif crop_aspect_ratio > target_aspect_ratio:
                # Crop is wider than target - we need to crop from sides or resize intelligently
                # Option 1: Crop to exact aspect ratio from center (maintains max resolution)
                new_crop_width = int(crop_height * target_aspect_ratio)
                if new_crop_width <= crop_width:
                    # We can crop to exact aspect ratio
                    x_offset = (crop_width - new_crop_width) // 2
                    adjusted_crop_box = (
                        crop_box[0] + x_offset,
                        crop_box[1],
                        crop_box[0] + x_offset + new_crop_width,
                        crop_box[3]
                    )
                    final_cropped = img.crop(adjusted_crop_box)
                    resized = final_cropped.resize(output_size, Image.Resampling.LANCZOS)
                else:
                    # Fall back to fit method that maintains aspect ratio
                    resized = self._resize_with_aspect_ratio(cropped, output_size)
                    
            else:
                # Crop is taller than target - we need to crop from top/bottom or resize intelligently
                # Option 1: Crop to exact aspect ratio from center (maintains max resolution)
                new_crop_height = int(crop_width / target_aspect_ratio)
                if new_crop_height <= crop_height:
                    # We can crop to exact aspect ratio
                    y_offset = (crop_height - new_crop_height) // 2
                    adjusted_crop_box = (
                        crop_box[0],
                        crop_box[1] + y_offset,
                        crop_box[2],
                        crop_box[1] + y_offset + new_crop_height
                    )
                    final_cropped = img.crop(adjusted_crop_box)
                    resized = final_cropped.resize(output_size, Image.Resampling.LANCZOS)
                else:
                    # Fall back to fit method that maintains aspect ratio
                    resized = self._resize_with_aspect_ratio(cropped, output_size)
            
            # Skip adding label since we're using dynamic frontend labels
            # labeled = self._add_label(resized, band_info['label'], timestamp_label)
            labeled = resized
            
            # Save processed image
            save_dir = os.path.join(
                IMAGES_DIR,
                band_info['folder_name'],
                'Zoom',
                zoom_level
            )
            os.makedirs(save_dir, exist_ok=True)
            
            save_path = os.path.join(save_dir, filename)
            
            # Save with optimization for web display
            labeled.save(
                save_path,
                'JPEG',
                quality=IMAGE_SETTINGS['compression_quality'],
                optimize=True
            )

            self.logger.debug(f"Saved processed image: {save_path}")

            # Generate a downscaled variant for the grid view (full-size image is
            # still kept above for the fullscreen viewer).
            if GRID_THUMBNAIL_CONFIG.get('enabled'):
                self._save_grid_thumbnail(labeled, save_path)

            return True
            
        except Exception as e:
            self.logger.error(f"Error processing zoom level {zoom_level}: {e}")
            return False

    def _save_grid_thumbnail(self, img, full_save_path):
        """
        Save a downscaled copy of a processed image for the grid view.

        The thumbnail is written next to the full-size image with a filename
        suffix (e.g. ..._grid.jpg) so the existing time-based cleanup removes
        both the full image and its thumbnail together.
        """
        try:
            suffix = GRID_THUMBNAIL_CONFIG['suffix']
            size = tuple(GRID_THUMBNAIL_CONFIG['size'])
            quality = GRID_THUMBNAIL_CONFIG['quality']

            # Insert the suffix before the .jpg extension.
            base, ext = os.path.splitext(full_save_path)
            grid_path = f"{base}{suffix}{ext}"

            thumbnail = img.resize(size, Image.Resampling.LANCZOS)
            thumbnail.save(grid_path, 'JPEG', quality=quality, optimize=True)
            self.logger.debug(f"Saved grid thumbnail: {grid_path}")
            return True

        except Exception as e:
            self.logger.error(f"Error saving grid thumbnail for {full_save_path}: {e}")
            return False

    def _resize_with_aspect_ratio(self, img, target_size):
        """
        Resize image to fit within target size while maintaining aspect ratio.
        This creates a letterboxed/pillarboxed image if aspect ratios don't match.
        """
        target_width, target_height = target_size
        img_width, img_height = img.size
        
        # Calculate scaling factor to fit within target size
        scale_w = target_width / img_width
        scale_h = target_height / img_height
        scale = min(scale_w, scale_h)  # Use smaller scale to ensure it fits
        
        # Calculate new size
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)
        
        # Resize image
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Create final image with target size and center the resized image
        final_img = Image.new('RGB', target_size, color='black')
        
        # Calculate position to center the image
        x_offset = (target_width - new_width) // 2
        y_offset = (target_height - new_height) // 2
        
        # Paste the resized image onto the final image
        final_img.paste(resized, (x_offset, y_offset))
        
        return final_img
    
    def _add_label(self, img, band_label, timestamp_label):
        """Add band name and timestamp label to image"""
        # Create a copy to avoid modifying original
        labeled = img.copy()
        
        # Create drawing context
        draw = ImageDraw.Draw(labeled)
        
        # Prepare label text
        label_text = f"{band_label}\n{timestamp_label}"
        
        # Calculate text size
        bbox = draw.textbbox((0, 0), label_text, font=self.font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Add padding
        padding = LABEL_CONFIG['padding']
        bg_width = text_width + (padding * 2)
        bg_height = text_height + (padding * 2)
        
        # Determine position
        position = LABEL_CONFIG['position']
        if position == 'top_left':
            x, y = padding, padding
        elif position == 'top_right':
            x, y = img.width - bg_width - padding, padding
        elif position == 'bottom_left':
            x, y = padding, img.height - bg_height - padding
        else:  # bottom_right
            x, y = img.width - bg_width - padding, img.height - bg_height - padding
        
        # Draw background rectangle
        bg_color = LABEL_CONFIG['background_color']
        opacity = int(LABEL_CONFIG['opacity'] * 255)
        
        # Create background with transparency
        if img.mode == 'RGBA':
            bg_color = (*ImageColor.getrgb(bg_color), opacity)
        
        draw.rectangle(
            [(x, y), (x + bg_width, y + bg_height)],
            fill=bg_color
        )
        
        # Draw text
        text_x = x + padding
        text_y = y + padding
        draw.text(
            (text_x, text_y),
            label_text,
            fill=LABEL_CONFIG['font_color'],
            font=self.font
        )
        
        return labeled
    
    def _cleanup_worker(self):
        """Worker thread to clean up old processed images"""
        while not self.stop_event.is_set():
            try:
                # Run cleanup every hour
                time.sleep(3600)
                self.cleanup_old_processed_images()
            except Exception as e:
                self.logger.error(f"Error in cleanup worker: {e}")
    
    def cleanup_old_processed_images(self):
        """Remove processed images older than retention period"""
        self.logger.info("Starting cleanup of old processed images")
        
        retention_hours = IMAGE_SETTINGS['retention_hours']
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
        
        removed_count = 0
        
        for band_key, band_info in BANDS.items():
            zoom_base = os.path.join(IMAGES_DIR, band_info['folder_name'], 'Zoom')
            
            for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                zoom_dir = os.path.join(zoom_base, zoom_level)
                
                if not os.path.exists(zoom_dir):
                    continue
                
                for filename in os.listdir(zoom_dir):
                    if not filename.endswith('.jpg') or filename.startswith('._'):
                        continue
                    
                    try:
                        # Extract timestamp from filename
                        timestamp_str = filename.split('_')[0]
                        file_dt = parse_timestamp(timestamp_str)
                        
                        # Remove if older than retention period
                        if file_dt < cutoff_time:
                            file_path = os.path.join(zoom_dir, filename)
                            os.remove(file_path)
                            
                            # Remove from history
                            history_key = self._get_history_key(band_key, zoom_level, filename)
                            self.processed_images.discard(history_key)
                            
                            removed_count += 1
                            
                    except Exception as e:
                        self.logger.error(f"Error cleaning up {filename}: {e}")
        
        self.logger.info(f"Cleanup complete. Removed {removed_count} old processed images")
    
    def process_existing_raw_images(self):
        """Process any existing raw images that haven't been processed yet"""
        self.logger.info("Processing existing raw images")
        
        total_queued = 0
        
        for band_key, band_info in BANDS.items():
            raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
            
            if not os.path.exists(raw_dir):
                continue
            
            for filename in sorted(os.listdir(raw_dir)):
                if not filename.endswith('.jpg') or filename.startswith('._'):
                    continue
                
                # Check if already processed
                already_processed = False
                for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                    history_key = self._get_history_key(band_key, zoom_level, filename)
                    if history_key in self.processed_images:
                        already_processed = True
                        break
                
                if not already_processed:
                    self.processing_queue.put({
                        'band_key': band_key,
                        'filename': filename,
                        'raw_path': os.path.join(raw_dir, filename)
                    })
                    total_queued += 1
        
        self.logger.info(f"Queued {total_queued} existing images for processing")
        
        # Wait for queue to empty
        if total_queued > 0:
            self.logger.info("Waiting for initial processing to complete...")
            self.processing_queue.join()
            self.logger.info("Initial processing complete")
    
    def get_status(self):
        """Get current status of the processor"""
        return {
            'processed_images': len(self.processed_images),
            'queue_size': self.processing_queue.qsize(),
            'monitor_threads': len([t for t in self.monitor_threads if t.is_alive()]),
            'processing_threads': len([t for t in self.processing_threads if t.is_alive()])
        }
    
    def stop(self):
        """Stop the processor gracefully"""
        self.logger.info("Stopping image processor")
        self.stop_event.set()
        
        # Wait for threads to finish
        for thread in self.monitor_threads + self.processing_threads:
            thread.join(timeout=5)
        
        self.logger.info("Image processor stopped")

    def trigger_processing_for_timestamp(self, timestamp):
        """
        Trigger immediate processing for a specific timestamp across all bands
        Called by downloader after successful downloads
        """
        try:
            # Check all bands for this timestamp
            queued_count = 0
            
            for band_key, band_info in BANDS.items():
                raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
                
                if not os.path.exists(raw_dir):
                    continue
                
                # Look for files matching this timestamp
                for filename in os.listdir(raw_dir):
                    if not filename.endswith('.jpg') or filename.startswith('._'):
                        continue
                    
                    try:
                        file_timestamp_str = filename.split('_')[0]
                        if file_timestamp_str == timestamp:
                            # Check if already processed
                            already_processed = False
                            for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                                history_key = self._get_history_key(band_key, zoom_level, filename)
                                if history_key in self.processed_images:
                                    already_processed = True
                                    break
                            
                            if not already_processed:
                                # Add to processing queue with high priority
                                self.processing_queue.put({
                                    'band_key': band_key,
                                    'filename': filename,
                                    'raw_path': os.path.join(raw_dir, filename)
                                })
                                queued_count += 1
                                self.logger.debug(f"Priority queued for processing: {band_info['label']} - {filename}")
                    
                    except Exception as e:
                        self.logger.warning(f"Error checking file {filename} for timestamp {timestamp}: {e}")
                        continue
            
            if queued_count > 0:
                self.logger.info(f"Triggered processing for timestamp {timestamp}: {queued_count} images queued")
            
            return queued_count
            
        except Exception as e:
            self.logger.error(f"Error triggering processing for timestamp {timestamp}: {e}")
            return 0

    def trigger_process_all_pending(self):
        """
        Trigger processing for all unprocessed raw images
        Called by downloader after startup downloads
        """
        try:
            self.logger.info("Triggering processing for all pending raw images")
            
            total_queued = 0
            
            for band_key, band_info in BANDS.items():
                raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
                
                if not os.path.exists(raw_dir):
                    continue
                
                for filename in sorted(os.listdir(raw_dir)):
                    if not filename.endswith('.jpg') or filename.startswith('._'):
                        continue
                    
                    # Check if already processed
                    already_processed = False
                    for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                        history_key = self._get_history_key(band_key, zoom_level, filename)
                        if history_key in self.processed_images:
                            already_processed = True
                            break
                    
                    if not already_processed:
                        self.processing_queue.put({
                            'band_key': band_key,
                            'filename': filename,
                            'raw_path': os.path.join(raw_dir, filename)
                        })
                        total_queued += 1
            
            self.logger.info(f"Triggered processing for {total_queued} pending raw images")
            return total_queued
            
        except Exception as e:
            self.logger.error(f"Error triggering global processing: {e}")
            return 0


def main():
    """Main function to run the image processor"""
    processor = ImageProcessor()
    
    try:
        # Process any existing raw images
        processor.process_existing_raw_images()
        
        # Keep running for 24/7 operation
        while True:
            # Log status every 5 minutes
            time.sleep(300)
            status = processor.get_status()
            processor.logger.info(f"Status: {status}")
            
    except KeyboardInterrupt:
        print("\nShutting down image processor...")
        processor.stop()


if __name__ == "__main__":
    main()
