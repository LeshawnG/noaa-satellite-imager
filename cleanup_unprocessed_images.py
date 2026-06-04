#!/usr/bin/env python3
"""
One-time cleanup script for unprocessed satellite images
Compares raw_images directories to zoom directories and processes any missing files
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    BANDS, IMAGES_DIR, IMAGE_SETTINGS, CROP_SETTINGS,
    parse_timestamp, get_local_time
)

class ImageCleanupProcessor:
    """One-time processor for cleaning up unprocessed images"""
    
    def __init__(self):
        self.setup_logging()
        self.processed_count = 0
        self.error_count = 0
        self.skipped_count = 0
        
    def setup_logging(self):
        """Set up logging for the cleanup script"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('cleanup_unprocessed.log')
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def find_unprocessed_images(self):
        """Find all unprocessed images by comparing raw vs zoom directories"""
        unprocessed_images = []
        
        for band_key, band_info in BANDS.items():
            self.logger.info(f"Checking {band_info['label']}...")
            
            raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
            zoom_base = os.path.join(IMAGES_DIR, band_info['folder_name'], 'Zoom')
            
            if not os.path.exists(raw_dir):
                self.logger.warning(f"Raw directory not found: {raw_dir}")
                continue
            
            # Get all raw images
            raw_files = set()
            for filename in os.listdir(raw_dir):
                if filename.endswith('.jpg') and not filename.startswith('._'):
                    raw_files.add(filename)
            
            # Get all processed images from zoom directories
            processed_files = {}
            for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                zoom_dir = os.path.join(zoom_base, zoom_level)
                processed_files[zoom_level] = set()
                
                if os.path.exists(zoom_dir):
                    for filename in os.listdir(zoom_dir):
                        if filename.endswith('.jpg') and not filename.startswith('._'):
                            processed_files[zoom_level].add(filename)
            
            # Find images that need processing
            for filename in raw_files:
                missing_zoom_levels = []
                for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                    if filename not in processed_files[zoom_level]:
                        missing_zoom_levels.append(zoom_level)
                
                if missing_zoom_levels:
                    unprocessed_images.append({
                        'band_key': band_key,
                        'band_info': band_info,
                        'filename': filename,
                        'raw_path': os.path.join(raw_dir, filename),
                        'missing_zoom_levels': missing_zoom_levels
                    })
            
            band_unprocessed = len([img for img in unprocessed_images if img['band_key'] == band_key])
            if band_unprocessed > 0:
                self.logger.info(f"Found {band_unprocessed} unprocessed images in {band_info['label']}")
        
        return unprocessed_images
    
    def validate_image_file(self, file_path):
        """Validate that image file is complete and not corrupted"""
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                return False
            
            # Check minimum file size (should be at least 100KB for these large images)
            file_size = os.path.getsize(file_path)
            if file_size < 100 * 1024:  # 100KB minimum
                return False
            
            # Try to open and verify the image
            try:
                with Image.open(file_path) as img:
                    # Try to load the image completely to detect truncation
                    img.load()
                    
                    # Check if it has the expected dimensions
                    expected_size = tuple(IMAGE_SETTINGS['source_resolution'])
                    if img.size != expected_size:
                        self.logger.warning(f"Image size mismatch: expected {expected_size}, got {img.size} for {file_path}")
                        return False
                    
                return True
                
            except Exception as e:
                self.logger.warning(f"Image validation failed for {file_path}: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error validating file {file_path}: {e}")
            return False
    
    def process_zoom_level(self, img, band_info, filename, zoom_level, zoom_config):
        """Process image for a specific zoom level"""
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
            if abs(crop_aspect_ratio - target_aspect_ratio) < 0.01:
                # Aspect ratios are very close, can resize directly
                resized = cropped.resize(output_size, Image.Resampling.LANCZOS)
                
            elif crop_aspect_ratio > target_aspect_ratio:
                # Crop is wider than target - crop from sides
                new_crop_width = int(crop_height * target_aspect_ratio)
                if new_crop_width <= crop_width:
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
                    resized = self.resize_with_aspect_ratio(cropped, output_size)
                    
            else:
                # Crop is taller than target - crop from top/bottom
                new_crop_height = int(crop_width / target_aspect_ratio)
                if new_crop_height <= crop_height:
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
                    resized = self.resize_with_aspect_ratio(cropped, output_size)
            
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
            resized.save(
                save_path,
                'JPEG',
                quality=IMAGE_SETTINGS['compression_quality'],
                optimize=True
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing zoom level {zoom_level} for {filename}: {e}")
            return False
    
    def resize_with_aspect_ratio(self, img, target_size):
        """Resize image to fit within target size while maintaining aspect ratio"""
        target_width, target_height = target_size
        img_width, img_height = img.size
        
        # Calculate scaling factor to fit within target size
        scale_w = target_width / img_width
        scale_h = target_height / img_height
        scale = min(scale_w, scale_h)
        
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
    
    def process_single_image(self, image_info):
        """Process a single unprocessed image"""
        try:
            band_key = image_info['band_key']
            band_info = image_info['band_info']
            filename = image_info['filename']
            raw_path = image_info['raw_path']
            missing_zoom_levels = image_info['missing_zoom_levels']
            
            # Validate the raw image file
            if not self.validate_image_file(raw_path):
                self.logger.warning(f"Skipping invalid file: {filename}")
                self.skipped_count += 1
                return False
            
            # Open and process the image
            with Image.open(raw_path) as img:
                # Verify image dimensions
                if img.size != tuple(IMAGE_SETTINGS['source_resolution']):
                    self.logger.warning(f"Unexpected image size for {filename}: {img.size}")
                    self.skipped_count += 1
                    return False
                
                # Process each missing zoom level
                success_count = 0
                for zoom_level in missing_zoom_levels:
                    zoom_config = CROP_SETTINGS[zoom_level]
                    
                    if self.process_zoom_level(img, band_info, filename, zoom_level, zoom_config):
                        success_count += 1
                    else:
                        self.error_count += 1
                
                if success_count > 0:
                    self.processed_count += success_count
                    
                    # Extract timestamp for logging
                    try:
                        timestamp_str = filename.split('_')[0]
                        image_dt = parse_timestamp(timestamp_str)
                        local_dt = get_local_time(image_dt)
                        timestamp_label = local_dt.strftime("%Y-%m-%d %H:%M GMT-4")
                    except:
                        timestamp_label = "unknown time"
                    
                    self.logger.info(f"Processed {band_info['label']} - {timestamp_label} ({success_count}/{len(missing_zoom_levels)} zoom levels)")
                    return True
                
        except Exception as e:
            self.logger.error(f"Error processing {raw_path}: {e}")
            self.error_count += 1
            
        return False
    
    def run_cleanup(self, max_workers=3):
        """Run the cleanup process"""
        start_time = time.time()
        
        self.logger.info("Starting cleanup of unprocessed images...")
        self.logger.info("=" * 60)
        
        # Find all unprocessed images
        unprocessed_images = self.find_unprocessed_images()
        
        if not unprocessed_images:
            self.logger.info("No unprocessed images found! System is up to date.")
            return
        
        total_files = len(unprocessed_images)
        total_zoom_levels = sum(len(img['missing_zoom_levels']) for img in unprocessed_images)
        
        self.logger.info(f"Found {total_files} images with {total_zoom_levels} missing zoom levels to process")
        self.logger.info("")
        
        # Group by band for better progress reporting
        by_band = {}
        for img in unprocessed_images:
            band = img['band_key']
            if band not in by_band:
                by_band[band] = []
            by_band[band].append(img)
        
        for band, count in [(k, len(v)) for k, v in by_band.items()]:
            band_info = BANDS[band]
            zoom_count = sum(len(img['missing_zoom_levels']) for img in by_band[band])
            self.logger.info(f"  {band_info['label']}: {count} files ({zoom_count} zoom levels)")
        
        self.logger.info("")
        self.logger.info("Processing images...")
        
        # Process images with controlled concurrency
        processed_files = 0
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_image = {
                executor.submit(self.process_single_image, img_info): img_info 
                for img_info in unprocessed_images
            }
            
            # Process results as they complete
            for future in as_completed(future_to_image):
                img_info = future_to_image[future]
                processed_files += 1
                
                try:
                    success = future.result()
                    
                    # Progress reporting every 10 files or for important milestones
                    if processed_files % 10 == 0 or processed_files in [1, 5] or processed_files == total_files:
                        progress = (processed_files / total_files) * 100
                        self.logger.info(f"Progress: {processed_files}/{total_files} files ({progress:.1f}%)")
                        
                except Exception as e:
                    self.logger.error(f"Exception processing {img_info['filename']}: {e}")
                    self.error_count += 1
        
        # Final report
        elapsed_time = time.time() - start_time
        
        self.logger.info("")
        self.logger.info("=" * 60)
        self.logger.info("CLEANUP COMPLETE")
        self.logger.info("=" * 60)
        self.logger.info(f"Files processed: {processed_files}/{total_files}")
        self.logger.info(f"Zoom levels created: {self.processed_count}")
        self.logger.info(f"Files skipped (invalid): {self.skipped_count}")
        self.logger.info(f"Processing errors: {self.error_count}")
        self.logger.info(f"Total time: {elapsed_time:.1f} seconds")
        
        if self.processed_count > 0:
            rate = self.processed_count / elapsed_time
            self.logger.info(f"Processing rate: {rate:.1f} zoom levels/second")
        
        if self.error_count > 0:
            self.logger.warning(f"There were {self.error_count} errors during processing. Check the log for details.")
        
        self.logger.info("")
        self.logger.info("The system should now be ready for restart with all images processed.")


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='One-time cleanup script for unprocessed satellite images')
    parser.add_argument('--workers', type=int, default=3, help='Number of concurrent processing workers (default: 3)')
    parser.add_argument('--dry-run', action='store_true', help='Just show what would be processed without actually processing')
    
    args = parser.parse_args()
    
    processor = ImageCleanupProcessor()
    
    if args.dry_run:
        print("DRY RUN MODE - No files will be processed")
        print("")
        
        unprocessed_images = processor.find_unprocessed_images()
        
        if not unprocessed_images:
            print("No unprocessed images found! System is up to date.")
            return
        
        total_files = len(unprocessed_images)
        total_zoom_levels = sum(len(img['missing_zoom_levels']) for img in unprocessed_images)
        
        print(f"Would process {total_files} images with {total_zoom_levels} missing zoom levels")
        print("")
        
        # Group by band
        by_band = {}
        for img in unprocessed_images:
            band = img['band_key']
            if band not in by_band:
                by_band[band] = []
            by_band[band].append(img)
        
        for band, images in by_band.items():
            band_info = BANDS[band]
            zoom_count = sum(len(img['missing_zoom_levels']) for img in images)
            print(f"  {band_info['label']}: {len(images)} files ({zoom_count} zoom levels)")
        
        print("")
        print("Run without --dry-run to actually process these files")
        
    else:
        processor.run_cleanup(max_workers=args.workers)


if __name__ == "__main__":
    main() 