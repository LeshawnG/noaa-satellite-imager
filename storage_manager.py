"""
Storage Manager Module for Satellite Weather Looping System
Manages image storage, provides efficient data access, monitors disk usage,
and coordinates cleanup for 24/7 operation
"""

import os
import sys
import time
import logging
import threading
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict, OrderedDict
from typing import Dict, List, Tuple, Optional
import heapq

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    BANDS, IMAGES_DIR, LOGS_DIR, IMAGE_SETTINGS, CROP_SETTINGS, TIME_PERIODS, STORAGE_CONFIG,
    GRID_THUMBNAIL_CONFIG, parse_timestamp, get_local_time, generate_timestamp
)

class StorageManager:
    """Manages satellite image storage and provides efficient data access"""
    
    def __init__(self, logger=None):
        """Initialize the storage manager for 24/7 operation"""
        self.logger = logger or self._setup_logger()
        self.stop_event = threading.Event()
        
        # Cache for image listings
        self.image_cache = {}
        self.cache_lock = threading.RLock()
        self.cache_expiry = 30  # Cache expires after 30 seconds
        
        # Disk usage monitoring
        self.disk_stats = {
            'total_space': 0,
            'used_space': 0,
            'free_space': 0,
            'image_space': 0,
            'image_count': 0,
            'last_update': None
        }
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(
            target=self._monitor_storage,
            daemon=True
        )
        self.monitor_thread.start()
        
        # Initialize storage structure
        self._ensure_directory_structure()
        
        # Perform initial scan
        self._update_disk_stats()
        
        self.logger.info("Storage Manager initialized for 24/7 operation")
    
    def _setup_logger(self):
        """Set up logging for the storage manager"""
        logger = logging.getLogger('StorageManager')
        
        # Only set up handlers if they don't already exist
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # File handler with rotation
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                os.path.join(LOGS_DIR, 'storage_manager.log'),
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
    
    def _ensure_directory_structure(self):
        """Ensure all required directories exist"""
        for band_key, band_info in BANDS.items():
            band_folder = os.path.join(IMAGES_DIR, band_info['folder_name'])
            
            # Create raw images directory
            raw_dir = os.path.join(band_folder, 'raw_images')
            os.makedirs(raw_dir, exist_ok=True)
            
            # Create zoom directories
            zoom_dir = os.path.join(band_folder, 'Zoom')
            for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                zoom_level_dir = os.path.join(zoom_dir, zoom_level)
                os.makedirs(zoom_level_dir, exist_ok=True)
    
    def _monitor_storage(self):
        """Monitor storage usage and maintain cache"""
        while not self.stop_event.is_set():
            try:
                # Update disk statistics
                self._update_disk_stats()
                
                # Clean expired cache entries
                self._clean_cache()
                
                # Check disk space warnings
                self._check_disk_space()
                
                # Sleep for configured interval
                time.sleep(STORAGE_CONFIG['check_interval_seconds'])
                
            except Exception as e:
                self.logger.error(f"Error in storage monitor: {e}")
                time.sleep(STORAGE_CONFIG['check_interval_seconds'])
    
    def _update_disk_stats(self):
        """Update disk usage statistics"""
        try:
            # Get disk usage for the images directory
            stat = shutil.disk_usage(IMAGES_DIR)
            
            # Calculate total image size and count
            total_size = 0
            total_count = 0
            
            for root, dirs, files in os.walk(IMAGES_DIR):
                for file in files:
                    if file.endswith('.jpg') and not file.startswith('._'):
                        file_path = os.path.join(root, file)
                        try:
                            total_size += os.path.getsize(file_path)
                            total_count += 1
                        except OSError:
                            pass
            
            # Update stats
            self.disk_stats = {
                'total_space': stat.total,
                'used_space': stat.used,
                'free_space': stat.free,
                'image_space': total_size,
                'image_count': total_count,
                'last_update': datetime.now(timezone.utc)
            }
            
            self.logger.debug(f"Disk stats updated: {total_count} images, {total_size / (1024**3):.2f} GB")
            
        except Exception as e:
            self.logger.error(f"Error updating disk stats: {e}")
    
    def _check_disk_space(self):
        """Check if disk space is running low and trigger cleanup if needed"""
        if self.disk_stats['free_space'] > 0 and self.disk_stats['image_space'] > 0:
            free_gb = self.disk_stats['free_space'] / (1024**3)
            image_gb = self.disk_stats['image_space'] / (1024**3)
            
            # Check if images directory exceeds maximum size
            if image_gb > STORAGE_CONFIG['max_directory_size_gb']:
                self.logger.warning(
                    f"Images directory size ({image_gb:.2f} GB) exceeds maximum "
                    f"({STORAGE_CONFIG['max_directory_size_gb']} GB) - triggering cleanup"
                )
                self._trigger_emergency_cleanup()
                return
            
            # Check if free space is below cleanup threshold
            if free_gb < STORAGE_CONFIG['cleanup_threshold_gb']:
                if free_gb < STORAGE_CONFIG['aggressive_cleanup_gb']:
                    self.logger.warning(
                        f"Critical disk space: {free_gb:.2f} GB free - triggering aggressive cleanup"
                    )
                    self._trigger_emergency_cleanup(aggressive=True)
                else:
                    self.logger.warning(
                        f"Low disk space: {free_gb:.2f} GB free - triggering cleanup"
                    )
                    self._trigger_emergency_cleanup()
            else:
                # Just log status if space is adequate
                self.logger.debug(
                    f"Disk space OK: {free_gb:.2f} GB free, images using {image_gb:.2f} GB"
                )
    
    def _clean_cache(self):
        """Remove expired cache entries"""
        with self.cache_lock:
            current_time = time.time()
            expired_keys = []
            
            for key, entry in self.image_cache.items():
                if current_time - entry['timestamp'] > self.cache_expiry:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.image_cache[key]
            
            if expired_keys:
                self.logger.debug(f"Cleaned {len(expired_keys)} expired cache entries")

    def _trigger_emergency_cleanup(self, aggressive=False):
        """Trigger emergency cleanup to free disk space"""
        try:
            # Run cleanup in a separate thread to avoid blocking the monitor
            cleanup_thread = threading.Thread(
                target=self._emergency_cleanup_worker,
                args=(aggressive,),
                daemon=True
            )
            cleanup_thread.start()
        except Exception as e:
            self.logger.error(f"Error starting emergency cleanup: {e}")
    
    def _emergency_cleanup_worker(self, aggressive=False):
        """Worker method for emergency cleanup"""
        try:
            if aggressive:
                # Aggressive cleanup: remove oldest 50% of images
                self.logger.info("Starting aggressive emergency cleanup")
                stats = self.cleanup_old_images_aggressive()
            else:
                # Standard cleanup: remove images older than retention period
                self.logger.info("Starting standard emergency cleanup")
                stats = self.cleanup_old_images(force=True)
            
            # Update disk stats after cleanup
            self._update_disk_stats()
            
            free_gb = self.disk_stats['free_space'] / (1024**3)
            image_gb = self.disk_stats['image_space'] / (1024**3)
            
            self.logger.info(
                f"Emergency cleanup complete: freed {stats.get('space_freed', 0) / (1024**3):.2f} GB, "
                f"removed {stats.get('raw_removed', 0) + stats.get('processed_removed', 0)} images. "
                f"Free space: {free_gb:.2f} GB, Images: {image_gb:.2f} GB"
            )
            
        except Exception as e:
            self.logger.error(f"Error in emergency cleanup: {e}")
    
    def get_image_list(self, band_key: str, zoom_level: str, hours: int = 24) -> List[Dict]:
        """
        Get list of available images for a specific band and zoom level
        
        Args:
            band_key: Band identifier (e.g., 'GeoColor', 'Band_2')
            zoom_level: Zoom level ('Zoom1', 'Zoom2', 'Zoom3')
            hours: Number of hours to look back (default: 24)
        
        Returns:
            List of image metadata dictionaries
        """
        # Generate cache key
        cache_key = f"{band_key}_{zoom_level}_{hours}"
        
        # Check cache first
        with self.cache_lock:
            if cache_key in self.image_cache:
                entry = self.image_cache[cache_key]
                if time.time() - entry['timestamp'] < self.cache_expiry:
                    return entry['data']
        
        # Generate new image list
        image_list = self._generate_image_list(band_key, zoom_level, hours)
        
        # Update cache
        with self.cache_lock:
            self.image_cache[cache_key] = {
                'data': image_list,
                'timestamp': time.time()
            }
        
        return image_list
    
    def _generate_image_list(self, band_key: str, zoom_level: str, hours: int) -> List[Dict]:
        """Generate list of available images"""
        if band_key not in BANDS:
            self.logger.error(f"Invalid band key: {band_key}")
            return []
        
        band_info = BANDS[band_key]
        image_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'Zoom', zoom_level)
        
        if not os.path.exists(image_dir):
            return []
        
        # Calculate cutoff time
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        images = []
        grid_suffix = GRID_THUMBNAIL_CONFIG.get('suffix', '_grid')
        url_prefix = f"/images/{band_info['folder_name']}/Zoom/{zoom_level}"

        try:
            dir_files = set(os.listdir(image_dir))

            for filename in dir_files:
                if not filename.endswith('.jpg') or filename.startswith('._'):
                    continue

                # Skip the downscaled grid thumbnails themselves; they are mapped
                # onto their full-size image below as 'grid_path'.
                base, ext = os.path.splitext(filename)
                if base.endswith(grid_suffix):
                    continue

                try:
                    # Extract timestamp from filename
                    timestamp_str = filename.split('_')[0]
                    image_dt = parse_timestamp(timestamp_str)

                    # Check if within time range
                    if image_dt >= cutoff_time:
                        # Get file info
                        file_path = os.path.join(image_dir, filename)
                        file_size = os.path.getsize(file_path)

                        # Convert to local time
                        local_dt = get_local_time(image_dt)

                        # Use the downscaled thumbnail for the grid when present,
                        # otherwise fall back to the full-size image.
                        grid_filename = f"{base}{grid_suffix}{ext}"
                        grid_path = (
                            f"{url_prefix}/{grid_filename}"
                            if grid_filename in dir_files
                            else f"{url_prefix}/{filename}"
                        )

                        images.append({
                            'filename': filename,
                            'path': f"{url_prefix}/{filename}",
                            'grid_path': grid_path,
                            'timestamp': image_dt.isoformat(),
                            'local_time': local_dt.strftime('%Y-%m-%d %H:%M'),
                            'size': file_size,
                            'band': band_key,
                            'zoom': zoom_level
                        })

                except Exception as e:
                    self.logger.error(f"Error processing {filename}: {e}")
            
            # Sort by timestamp (oldest first for proper chronological playback)
            images.sort(key=lambda x: x['timestamp'], reverse=False)
            
        except Exception as e:
            self.logger.error(f"Error listing images in {image_dir}: {e}")
        
        return images
    
    def get_grid_images(self, hours: int = 24, zoom_level: str = 'Zoom1') -> Dict:
        """
        Get time-aligned images for all bands suitable for grid display.

        All bands are aligned to a single master timeline (the sorted union of
        every timestamp present in any band within the window). Each band's list
        is padded to that timeline with None where the band has no image at that
        timestamp, so index N refers to the SAME moment in every panel. This
        guarantees the four grid cells stay time-aligned even when a band is
        daytime-only (e.g. Band 2) or has a missing/failed frame.

        Args:
            hours: Number of hours to look back
            zoom_level: Zoom level ('Zoom1', 'Zoom2', 'Zoom3') - defaults to 'Zoom1'

        Returns:
            {
              'timestamps':       [iso, ...],            # master timeline
              'timestamps_local': ['YYYY-MM-DD HH:MM', ...],
              'bands': { band_key: [entry|None, ...] }   # all aligned to timestamps
            }
        """
        # Raw per-band lists (each already sorted oldest-first)
        per_band = {}
        for band_key in BANDS.keys():
            per_band[band_key] = self.get_image_list(band_key, zoom_level, hours)

        # Master timeline: sorted union of all timestamps across bands.
        # ISO timestamps with a common UTC offset sort chronologically.
        timestamp_set = set()
        for images in per_band.values():
            for img in images:
                timestamp_set.add(img['timestamp'])
        master = sorted(timestamp_set)

        # Local-time labels for the master timeline (authoritative for the UI).
        timestamps_local = []
        for ts in master:
            try:
                dt = datetime.fromisoformat(ts)
                timestamps_local.append(get_local_time(dt).strftime('%Y-%m-%d %H:%M'))
            except Exception:
                timestamps_local.append('')

        # Align each band to the master timeline (None where missing).
        aligned = {}
        for band_key, images in per_band.items():
            by_ts = {img['timestamp']: img for img in images}
            aligned[band_key] = [by_ts.get(ts) for ts in master]

        return {
            'timestamps': master,
            'timestamps_local': timestamps_local,
            'bands': aligned
        }
    
    def get_available_timestamps(self, hours: int = 48) -> List[str]:
        """
        Get list of unique timestamps that have images available
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            List of timestamp strings in NOAA format
        """
        timestamps = set()
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Check all bands for available timestamps
        for band_key, band_info in BANDS.items():
            for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                image_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'Zoom', zoom_level)
                
                if not os.path.exists(image_dir):
                    continue
                
                for filename in os.listdir(image_dir):
                    if filename.endswith('.jpg') and not filename.startswith('._'):
                        try:
                            timestamp_str = filename.split('_')[0]
                            image_dt = parse_timestamp(timestamp_str)
                            
                            if image_dt >= cutoff_time:
                                timestamps.add(timestamp_str)
                        except:
                            pass
        
        return sorted(list(timestamps), reverse=False)
    
    def get_missing_images(self, hours: int = 48) -> Dict[str, List[str]]:
        """
        Get list of missing images for each band
        
        Returns:
            Dictionary with band keys and lists of missing timestamps
        """
        missing = defaultdict(list)
        
        # Get expected timestamps
        expected_timestamps = []
        current_time = datetime.now(timezone.utc)
        current_minutes = (current_time.minute // 10) * 10
        current_slot = current_time.replace(minute=current_minutes, second=0, microsecond=0)
        
        for i in range(hours * 6):  # 6 images per hour
            timestamp_dt = current_slot - timedelta(minutes=i * 10)
            expected_timestamps.append(generate_timestamp(timestamp_dt))
        
        # Check each band
        for band_key, band_info in BANDS.items():
            existing = set()
            
            # Check all zoom levels
            for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                image_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'Zoom', zoom_level)
                
                if os.path.exists(image_dir):
                    for filename in os.listdir(image_dir):
                        if filename.endswith('.jpg') and not filename.startswith('._'):
                            try:
                                timestamp_str = filename.split('_')[0]
                                existing.add(timestamp_str)
                            except:
                                pass
            
            # Find missing timestamps
            for timestamp in expected_timestamps:
                if timestamp not in existing:
                    missing[band_key].append(timestamp)
        
        return dict(missing)
    
    def cleanup_old_images(self, force: bool = False) -> Dict[str, int]:
        """
        Clean up images older than retention period
        
        Args:
            force: Force cleanup even if disk space is okay
            
        Returns:
            Dictionary with cleanup statistics
        """
        retention_hours = IMAGE_SETTINGS['retention_hours']
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
        
        stats = {
            'raw_removed': 0,
            'processed_removed': 0,
            'space_freed': 0
        }
        
        # Check if cleanup is needed based on new storage configuration
        if not force:
            free_gb = self.disk_stats['free_space'] / (1024**3)
            image_gb = self.disk_stats['image_space'] / (1024**3)
            
            # Skip if we have enough free space AND images directory is under limit
            if (free_gb >= STORAGE_CONFIG['cleanup_threshold_gb'] and 
                image_gb <= STORAGE_CONFIG['max_directory_size_gb']):
                self.logger.info(
                    f"Storage space adequate: {free_gb:.2f} GB free, "
                    f"images using {image_gb:.2f} GB - skipping cleanup"
                )
                return stats
        
        self.logger.info("Starting image cleanup based on retention period")
        
        for band_key, band_info in BANDS.items():
            band_folder = os.path.join(IMAGES_DIR, band_info['folder_name'])
            
            # Clean raw images
            raw_dir = os.path.join(band_folder, 'raw_images')
            if os.path.exists(raw_dir):
                stats['raw_removed'] += self._cleanup_directory(raw_dir, cutoff_time, stats)
            
            # Clean processed images
            zoom_dir = os.path.join(band_folder, 'Zoom')
            for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                zoom_level_dir = os.path.join(zoom_dir, zoom_level)
                if os.path.exists(zoom_level_dir):
                    stats['processed_removed'] += self._cleanup_directory(zoom_level_dir, cutoff_time, stats)
        
        # Clear cache after cleanup
        with self.cache_lock:
            self.image_cache.clear()
        
        self.logger.info(f"Cleanup complete: {stats}")
        return stats
    
    def cleanup_old_images_aggressive(self) -> Dict[str, int]:
        """
        Aggressive cleanup: remove oldest 50% of images regardless of retention period
        Used when disk space is critically low
        
        Returns:
            Dictionary with cleanup statistics
        """
        stats = {
            'raw_removed': 0,
            'processed_removed': 0,
            'space_freed': 0
        }
        
        self.logger.info("Starting aggressive cleanup - removing oldest 50% of images")
        
        # Collect all image files with timestamps
        all_images = []
        
        for band_key, band_info in BANDS.items():
            band_folder = os.path.join(IMAGES_DIR, band_info['folder_name'])
            
            # Process raw images
            raw_dir = os.path.join(band_folder, 'raw_images')
            if os.path.exists(raw_dir):
                for filename in os.listdir(raw_dir):
                    if filename.endswith('.jpg') and not filename.startswith('._'):
                        try:
                            timestamp_str = filename.split('_')[0]
                            file_dt = parse_timestamp(timestamp_str)
                            file_path = os.path.join(raw_dir, filename)
                            file_size = os.path.getsize(file_path)
                            
                            all_images.append({
                                'path': file_path,
                                'timestamp': file_dt,
                                'size': file_size,
                                'type': 'raw'
                            })
                        except Exception as e:
                            self.logger.error(f"Error processing {filename}: {e}")
            
            # Process zoom images
            zoom_dir = os.path.join(band_folder, 'Zoom')
            for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                zoom_level_dir = os.path.join(zoom_dir, zoom_level)
                if os.path.exists(zoom_level_dir):
                    for filename in os.listdir(zoom_level_dir):
                        if filename.endswith('.jpg') and not filename.startswith('._'):
                            try:
                                timestamp_str = filename.split('_')[0]
                                file_dt = parse_timestamp(timestamp_str)
                                file_path = os.path.join(zoom_level_dir, filename)
                                file_size = os.path.getsize(file_path)
                                
                                all_images.append({
                                    'path': file_path,
                                    'timestamp': file_dt,
                                    'size': file_size,
                                    'type': 'processed'
                                })
                            except Exception as e:
                                self.logger.error(f"Error processing {filename}: {e}")
        
        # Sort by timestamp (oldest first)
        all_images.sort(key=lambda x: x['timestamp'])
        
        # Remove oldest 50%
        images_to_remove = len(all_images) // 2
        
        for i in range(images_to_remove):
            try:
                image = all_images[i]
                os.remove(image['path'])
                
                if image['type'] == 'raw':
                    stats['raw_removed'] += 1
                else:
                    stats['processed_removed'] += 1
                
                stats['space_freed'] += image['size']
                
            except Exception as e:
                self.logger.error(f"Error removing {image['path']}: {e}")
        
        # Clear cache after cleanup
        with self.cache_lock:
            self.image_cache.clear()
        
        self.logger.info(f"Aggressive cleanup complete: {stats}")
        return stats
    
    def _cleanup_directory(self, directory: str, cutoff_time: datetime, stats: Dict) -> int:
        """Clean up old files in a directory"""
        removed_count = 0
        
        try:
            for filename in os.listdir(directory):
                if not filename.endswith('.jpg') or filename.startswith('._'):
                    continue
                
                try:
                    # Extract timestamp from filename
                    timestamp_str = filename.split('_')[0]
                    file_dt = parse_timestamp(timestamp_str)
                    
                    # Remove if older than cutoff
                    if file_dt < cutoff_time:
                        file_path = os.path.join(directory, filename)
                        file_size = os.path.getsize(file_path)
                        
                        os.remove(file_path)
                        removed_count += 1
                        stats['space_freed'] += file_size
                        
                except Exception as e:
                    self.logger.error(f"Error removing {filename}: {e}")
        
        except Exception as e:
            self.logger.error(f"Error cleaning directory {directory}: {e}")
        
        return removed_count
    
    def get_storage_status(self) -> Dict:
        """Get current storage status and statistics"""
        # Update stats if needed
        if (not self.disk_stats['last_update'] or 
            (datetime.now(timezone.utc) - self.disk_stats['last_update']).total_seconds() > 300):
            self._update_disk_stats()
        
        # Get image counts by band
        band_stats = {}
        for band_key, band_info in BANDS.items():
            raw_count = 0
            processed_count = 0
            
            # Count raw images
            raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
            if os.path.exists(raw_dir):
                raw_count = len([f for f in os.listdir(raw_dir) 
                               if f.endswith('.jpg') and not f.startswith('._')])
            
            # Count processed images
            zoom_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'Zoom')
            for zoom_level in ['Zoom1', 'Zoom2', 'Zoom3']:
                zoom_level_dir = os.path.join(zoom_dir, zoom_level)
                if os.path.exists(zoom_level_dir):
                    processed_count += len([f for f in os.listdir(zoom_level_dir) 
                                          if f.endswith('.jpg') and not f.startswith('._')])
            
            band_stats[band_key] = {
                'raw_images': raw_count,
                'processed_images': processed_count
            }
        
        # Calculate space usage
        total_gb = self.disk_stats['total_space'] / (1024**3)
        used_gb = self.disk_stats['used_space'] / (1024**3)
        free_gb = self.disk_stats['free_space'] / (1024**3)
        image_gb = self.disk_stats['image_space'] / (1024**3)
        
        return {
            'disk': {
                'total_gb': round(total_gb, 2),
                'used_gb': round(used_gb, 2),
                'free_gb': round(free_gb, 2),
                'free_percent': round((free_gb / total_gb) * 100, 1),
                'image_gb': round(image_gb, 2)
            },
            'storage_limits': {
                'max_directory_size_gb': STORAGE_CONFIG['max_directory_size_gb'],
                'cleanup_threshold_gb': STORAGE_CONFIG['cleanup_threshold_gb'],
                'aggressive_cleanup_gb': STORAGE_CONFIG['aggressive_cleanup_gb'],
                'directory_usage_percent': round((image_gb / STORAGE_CONFIG['max_directory_size_gb']) * 100, 1),
                'status': self._get_storage_status_description(free_gb, image_gb)
            },
            'images': {
                'total_count': self.disk_stats['image_count'],
                'by_band': band_stats
            },
            'cache': {
                'entries': len(self.image_cache),
                'expiry_seconds': self.cache_expiry
            },
            'last_update': self.disk_stats['last_update'].isoformat() if self.disk_stats['last_update'] else None
        }
    
    def _get_storage_status_description(self, free_gb: float, image_gb: float) -> str:
        """Get human-readable storage status description"""
        if image_gb > STORAGE_CONFIG['max_directory_size_gb']:
            return "OVER_LIMIT"
        elif free_gb < STORAGE_CONFIG['aggressive_cleanup_gb']:
            return "CRITICAL"
        elif free_gb < STORAGE_CONFIG['cleanup_threshold_gb']:
            return "LOW"
        else:
            return "OK"
    
    def manual_cleanup(self, cleanup_type: str = "standard") -> Dict[str, int]:
        """
        Manually trigger cleanup with different levels
        
        Args:
            cleanup_type: "standard", "aggressive", or "retention"
            
        Returns:
            Dictionary with cleanup statistics
        """
        self.logger.info(f"Manual cleanup triggered: {cleanup_type}")
        
        if cleanup_type == "aggressive":
            return self.cleanup_old_images_aggressive()
        elif cleanup_type == "retention":
            return self.cleanup_old_images(force=True)
        else:  # standard
            return self.cleanup_old_images(force=False)
    
    def verify_image_integrity(self, band_key: str, zoom_level: str, filename: str) -> bool:
        """Verify that an image file exists and is valid"""
        try:
            band_info = BANDS[band_key]
            file_path = os.path.join(IMAGES_DIR, band_info['folder_name'], 'Zoom', zoom_level, filename)
            
            if not os.path.exists(file_path):
                return False
            
            # Check file size
            if os.path.getsize(file_path) < 1000:  # Less than 1KB is suspicious
                return False
            
            # Try to open with PIL to verify it's a valid image
            from PIL import Image
            with Image.open(file_path) as img:
                img.verify()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Image integrity check failed for {filename}: {e}")
            return False
    
    def stop(self):
        """Stop the storage manager gracefully"""
        self.logger.info("Stopping storage manager")
        self.stop_event.set()
        
        if self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        self.logger.info("Storage manager stopped")


def main():
    """Main function for testing the storage manager"""
    manager = StorageManager()
    
    try:
        while True:
            # Print status every minute
            time.sleep(60)
            status = manager.get_storage_status()
            print(f"\nStorage Status:")
            print(f"Disk: {status['disk']['free_gb']} GB free ({status['disk']['free_percent']}%)")
            print(f"Total images: {status['images']['total_count']}")
            print(f"Cache entries: {status['cache']['entries']}")
            
    except KeyboardInterrupt:
        print("\nShutting down storage manager...")
        manager.stop()


if __name__ == "__main__":
    main()
