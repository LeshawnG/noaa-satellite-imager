"""
Image Downloader Module for Satellite Weather Looping System
Handles downloading of GOES-19 satellite imagery from NOAA servers
"""

import os
import sys
import time
import logging
import requests
import threading
import queue
import json
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    BANDS, IMAGES_DIR, LOGS_DIR, DOWNLOAD_CONFIG, IMAGE_SETTINGS, FRAME_TRACKING_CONFIG,
    generate_timestamp, parse_timestamp, get_local_time, create_directories
)

class FrameTracker:
    """Manages comprehensive tracking of frame download attempts and status"""
    
    def __init__(self, tracking_file_path):
        self.tracking_file = tracking_file_path
        self.tracking_data = self._load_tracking_data()
        self.lock = threading.Lock()
    
    def _load_tracking_data(self):
        """Load existing tracking data from file"""
        if os.path.exists(self.tracking_file):
            try:
                with open(self.tracking_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            'frames': {},  # timestamp -> {band -> status_data}
            'last_cleanup': None,
            'statistics': {
                'total_attempts': 0,
                'successful_downloads': 0,
                'failed_attempts': 0,
                'retry_attempts': 0
            }
        }
    
    def _save_tracking_data(self):
        """Save tracking data to file"""
        try:
            with open(self.tracking_file, 'w') as f:
                json.dump(self.tracking_data, f, indent=2, default=str)
        except Exception as e:
            logging.error(f"Failed to save tracking data: {e}")
    
    def record_download_attempt(self, timestamp, band_key, success=False, error_msg=None):
        """Record a download attempt for a specific frame and band"""
        with self.lock:
            current_time = datetime.now(timezone.utc).isoformat()
            
            # Initialize frame record if not exists
            if timestamp not in self.tracking_data['frames']:
                self.tracking_data['frames'][timestamp] = {}
            
            # Initialize band record if not exists
            if band_key not in self.tracking_data['frames'][timestamp]:
                self.tracking_data['frames'][timestamp][band_key] = {
                    'status': 'pending',
                    'attempts': [],
                    'first_attempt': current_time,
                    'last_attempt': current_time,
                    'success_time': None,
                    'retry_count': 0,
                    'marked_missing': False
                }
            
            band_data = self.tracking_data['frames'][timestamp][band_key]
            
            # Record this attempt
            attempt_data = {
                'timestamp': current_time,
                'success': success,
                'error': error_msg
            }
            band_data['attempts'].append(attempt_data)
            band_data['last_attempt'] = current_time
            
            # Update status
            if success:
                band_data['status'] = 'downloaded'
                band_data['success_time'] = current_time
                self.tracking_data['statistics']['successful_downloads'] += 1
            else:
                band_data['status'] = 'failed'
                band_data['retry_count'] += 1
                self.tracking_data['statistics']['failed_attempts'] += 1
                
                if band_data['retry_count'] > 1:
                    self.tracking_data['statistics']['retry_attempts'] += 1
            
            self.tracking_data['statistics']['total_attempts'] += 1
            self._save_tracking_data()
    
    def get_frame_status(self, timestamp, band_key):
        """Get the current status of a frame"""
        with self.lock:
            if timestamp in self.tracking_data['frames']:
                if band_key in self.tracking_data['frames'][timestamp]:
                    return self.tracking_data['frames'][timestamp][band_key]
            return None
    
    def get_frames_needing_retry(self, max_age_hours=2):
        """Get frames that need retry attempts"""
        with self.lock:
            retry_frames = {}
            current_time = datetime.now(timezone.utc)
            cutoff_time = current_time - timedelta(hours=max_age_hours)
            
            for timestamp, frame_data in self.tracking_data['frames'].items():
                try:
                    frame_dt = parse_timestamp(timestamp)
                    if frame_dt < cutoff_time:
                        continue  # Too old
                        
                    for band_key, band_data in frame_data.items():
                        if self._should_retry_frame(band_data, current_time):
                            if timestamp not in retry_frames:
                                retry_frames[timestamp] = set()
                            retry_frames[timestamp].add(band_key)
                            
                except Exception:
                    continue
                    
            return retry_frames
    
    def _should_retry_frame(self, band_data, current_time):
        """Determine if a frame should be retried with improved logic"""
        if band_data['status'] == 'downloaded':
            return False
            
        if band_data['marked_missing']:
            return False
            
        retry_count = band_data['retry_count']
        if retry_count >= FRAME_TRACKING_CONFIG['max_retry_attempts']:
            return False
        
        # Check the last error to determine if retry is worthwhile
        if band_data['attempts']:
            last_attempt = band_data['attempts'][-1]
            last_error = last_attempt.get('error', '')
            
            # Don't retry certain permanent errors immediately
            permanent_error_indicators = [
                'Directory creation failed',
                'Critical error in download_image'
            ]
            
            if any(indicator in last_error for indicator in permanent_error_indicators):
                # For permanent errors, use longer retry intervals
                retry_count += 1  # Effectively skip to next retry interval
            
            # For server errors (5xx), use shorter retry intervals
            if 'Server temporarily unavailable' in last_error:
                # Allow more frequent retries for server issues
                pass  # Use normal retry intervals
        
        # Check if enough time has passed for retry
        last_attempt_time = datetime.fromisoformat(band_data['last_attempt'].replace('Z', '+00:00'))
        if retry_count < len(FRAME_TRACKING_CONFIG['retry_intervals']):
            retry_interval = FRAME_TRACKING_CONFIG['retry_intervals'][retry_count]
        else:
            retry_interval = FRAME_TRACKING_CONFIG['retry_intervals'][-1]
            
        time_since_last = (current_time - last_attempt_time).total_seconds() / 60
        should_retry = time_since_last >= retry_interval
        
        if should_retry:
            self.logger.debug(f"Should retry frame (retry_count: {retry_count}, time_since_last: {time_since_last:.1f}m, interval: {retry_interval}m)")
        
        return should_retry
    
    def mark_frame_persistent_missing(self, timestamp, band_key):
        """Mark a frame as persistently missing after threshold"""
        with self.lock:
            if timestamp in self.tracking_data['frames']:
                if band_key in self.tracking_data['frames'][timestamp]:
                    self.tracking_data['frames'][timestamp][band_key]['marked_missing'] = True
                    self.tracking_data['frames'][timestamp][band_key]['status'] = 'missing'
                    self._save_tracking_data()
    
    def get_expected_frames(self, hours_back=48):
        """Get all expected frame timestamps based on the schedule"""
        expected_frames = []
        current_time = datetime.now(timezone.utc)
        current_minutes = (current_time.minute // 10) * 10
        current_slot = current_time.replace(minute=current_minutes, second=0, microsecond=0)
        
        # Generate expected timestamps
        images_needed = hours_back * 6  # 6 images per hour (every 10 minutes)
        for i in range(images_needed):
            frame_time = current_slot - timedelta(minutes=i * 10)
            timestamp = generate_timestamp(frame_time)
            expected_frames.append({
                'timestamp': timestamp,
                'datetime': frame_time
            })
            
        return expected_frames
    
    def cleanup_old_tracking_data(self):
        """Remove old tracking data"""
        with self.lock:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=FRAME_TRACKING_CONFIG['cleanup_tracking_days'])
            timestamps_to_remove = []
            
            for timestamp in self.tracking_data['frames'].keys():
                try:
                    frame_dt = parse_timestamp(timestamp)
                    if frame_dt < cutoff_time:
                        timestamps_to_remove.append(timestamp)
                except Exception:
                    timestamps_to_remove.append(timestamp)  # Remove invalid timestamps
            
            for timestamp in timestamps_to_remove:
                del self.tracking_data['frames'][timestamp]
            
            self.tracking_data['last_cleanup'] = datetime.now(timezone.utc).isoformat()
            self._save_tracking_data()
            
            return len(timestamps_to_remove)

class ImageDownloader:
    """Handles downloading of satellite images from NOAA servers"""
    
    def __init__(self, logger=None):
        """Initialize the image downloader"""
        self.logger = logger or self._setup_logger()
        self.session = self._setup_session()
        self.download_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.download_history = set()  # Track downloaded files to avoid duplicates
        self.processor = None  # Will be set by app.py after processor initialization
        
        # Initialize frame tracker
        if FRAME_TRACKING_CONFIG['enable_tracking']:
            tracking_file_path = os.path.join(os.path.dirname(__file__), FRAME_TRACKING_CONFIG['tracking_file'])
            self.frame_tracker = FrameTracker(tracking_file_path)
        else:
            self.frame_tracker = None
        
        # Create directories if they don't exist
        create_directories()
        
        # Load existing images to download history
        self._load_existing_images()
        
        self.logger.info("Image Downloader initialized with enhanced frame tracking")
    
    def _setup_logger(self):
        """Set up logging for the downloader"""
        logger = logging.getLogger('ImageDownloader')
        
        # Only set up handlers if they don't already exist
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # File handler with rotation to bound SD-card writes during 24/7 operation
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                os.path.join(LOGS_DIR, 'image_downloader.log'),
                maxBytes=5242880,  # 5MB
                backupCount=3
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
    
    def _setup_session(self):
        """Set up requests session with retry logic"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': DOWNLOAD_CONFIG['user_agent']
        })
        
        # Configure retry logic
        from requests.adapters import HTTPAdapter
        from requests.packages.urllib3.util.retry import Retry
        
        retry_strategy = Retry(
            total=DOWNLOAD_CONFIG['max_retries'],
            backoff_factor=DOWNLOAD_CONFIG['retry_delay'],
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def _load_existing_images(self):
        """Load existing images into download history to avoid re-downloading"""
        for band_key, band_info in BANDS.items():
            raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
            if os.path.exists(raw_dir):
                for filename in os.listdir(raw_dir):
                    if filename.endswith('.jpg') and not filename.startswith('._'):
                        self.download_history.add(f"{band_key}_{filename}")
        
        self.logger.info(f"Loaded {len(self.download_history)} existing images into history")
    
    def generate_image_url(self, band_key, timestamp):
        """Generate the full URL for a satellite image"""
        band_info = BANDS[band_key]
        filename = band_info['url_pattern'].format(timestamp=timestamp)
        url = band_info['url_base'] + filename
        return url, filename
    
    def download_image(self, band_key, timestamp):
        """Download a single image with comprehensive error handling and tracking"""
        try:
            url, filename = self.generate_image_url(band_key, timestamp)
            
            # Create directory structure
            band_info = BANDS[band_key]
            band_dir = os.path.join(IMAGES_DIR, band_info['folder_name'])
            raw_dir = os.path.join(band_dir, 'raw_images')
            
            # Ensure directories exist with better error handling
            try:
                os.makedirs(raw_dir, exist_ok=True)
            except Exception as e:
                self.logger.error(f"Failed to create directory {raw_dir}: {e}")
                if self.frame_tracker:
                    self.frame_tracker.record_download_attempt(timestamp, band_key, False, f"Directory creation failed: {e}")
                return False
            
            file_path = os.path.join(raw_dir, filename)
            
            # Check if file already exists and is valid
            if os.path.exists(file_path):
                if self._validate_downloaded_file(file_path):
                    file_size_mb = os.path.getsize(file_path) / 1024 / 1024
                    history_key = f"{band_key}_{filename}"
                    self.download_history.add(history_key)
                    if self.frame_tracker:
                        self.frame_tracker.record_download_attempt(timestamp, band_key, True, None)
                    return True
                else:
                    # Remove invalid file
                    try:
                        os.remove(file_path)
                        self.logger.warning(f"Removed invalid existing file: {filename}")
                    except Exception:
                        pass
            
            # Download the image
            try:
                response = self.session.get(url, timeout=DOWNLOAD_CONFIG['timeout'], stream=True)
                
                if response.status_code == 200:
                    # Download to temporary file first, then move to final location
                    temp_path = file_path + '.tmp'
                    
                    try:
                        total_size = 0
                        with open(temp_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                                    total_size += len(chunk)
                        
                        # Verify download completed successfully
                        if total_size > 0 and self._validate_downloaded_file(temp_path):
                            # Move to final location atomically
                            os.rename(temp_path, file_path)
                            
                            file_size_mb = total_size / 1024 / 1024
                            history_key = f"{band_key}_{filename}"
                            self.download_history.add(history_key)
                            self.logger.info(f"Downloaded: {filename} ({file_size_mb:.2f} MB)")
                            
                            if self.frame_tracker:
                                self.frame_tracker.record_download_attempt(timestamp, band_key, True, None)
                            return True
                        else:
                            # Remove incomplete/invalid file
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                            error_msg = "Downloaded file was invalid or incomplete"
                            self.logger.warning(f"Invalid file downloaded: {filename}")
                            if self.frame_tracker:
                                self.frame_tracker.record_download_attempt(timestamp, band_key, False, error_msg)
                            return False
                    
                    except Exception as e:
                        # Clean up temp file on error
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        raise e
                
                elif response.status_code == 404:
                    # Image not available - this is common and expected for recent images
                    error_msg = "Image not available (404)"
                    if self.frame_tracker:
                        self.frame_tracker.record_download_attempt(timestamp, band_key, False, error_msg)
                    return False
                
                elif response.status_code in [429, 503, 502, 500]:
                    # Server overload or temporary issues - worth retrying
                    error_msg = f"Server temporarily unavailable ({response.status_code})"
                    self.logger.warning(f"Server temporarily unavailable for {filename}: {response.status_code}")
                    if self.frame_tracker:
                        self.frame_tracker.record_download_attempt(timestamp, band_key, False, error_msg)
                    return False
                
                else:
                    # Other HTTP errors
                    error_msg = f"HTTP error {response.status_code}"
                    self.logger.warning(f"HTTP error {response.status_code} for {filename}")
                    if self.frame_tracker:
                        self.frame_tracker.record_download_attempt(timestamp, band_key, False, error_msg)
                    return False
                    
            except requests.exceptions.Timeout:
                error_msg = "Download timeout"
                self.logger.warning(f"Timeout downloading {filename}")
                if self.frame_tracker:
                    self.frame_tracker.record_download_attempt(timestamp, band_key, False, error_msg)
                return False
                
            except requests.exceptions.ConnectionError as e:
                error_msg = f"Connection error: {str(e)}"
                self.logger.warning(f"Connection error downloading {filename}: {e}")
                if self.frame_tracker:
                    self.frame_tracker.record_download_attempt(timestamp, band_key, False, error_msg)
                return False
                
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                self.logger.error(f"Error downloading {filename}: {e}")
                if self.frame_tracker:
                    self.frame_tracker.record_download_attempt(timestamp, band_key, False, error_msg)
                return False
                
        except Exception as e:
            error_msg = f"Critical error in download_image: {str(e)}"
            self.logger.error(f"Critical error in download_image for {band_key} {timestamp}: {e}")
            if self.frame_tracker:
                self.frame_tracker.record_download_attempt(timestamp, band_key, False, error_msg)
            return False
    
    def _validate_downloaded_file(self, file_path):
        """Validate that a downloaded file is complete and valid"""
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                return False
            
            # Check minimum file size (satellite images should be at least 1MB)
            file_size = os.path.getsize(file_path)
            if file_size < 1024 * 1024:  # 1MB minimum
                return False
            
            # Try to open as image to verify it's not corrupted
            try:
                from PIL import Image
                with Image.open(file_path) as img:
                    # Try to load the image to detect truncation
                    img.load()
                    # Check if dimensions are reasonable for satellite imagery
                    if img.size[0] < 1000 or img.size[1] < 1000:
                        return False
                return True
            except Exception:
                return False
                
        except Exception:
            return False
    
    def download_all_bands_for_timestamp(self, timestamp):
        """Download all bands for a specific timestamp"""
        results = {}
        
        with ThreadPoolExecutor(max_workers=DOWNLOAD_CONFIG['concurrent_downloads']) as executor:
            # Submit download tasks
            future_to_band = {}
            for band_key in BANDS.keys():
                future = executor.submit(self.download_image, band_key, timestamp)
                future_to_band[future] = band_key
            
            # Collect results
            for future in as_completed(future_to_band):
                band_key = future_to_band[future]
                try:
                    success = future.result()
                    results[band_key] = success
                except Exception as e:
                    self.logger.error(f"Exception downloading {band_key}: {e}")
                    results[band_key] = False
        
        return results
    
    def get_missing_timestamps(self, hours_back=48):
        """Get list of timestamps that should be downloaded"""
        missing_timestamps = []
        
        # Current time rounded to 10 minutes
        now = datetime.now(timezone.utc)
        current_minutes = (now.minute // 10) * 10
        current_time = now.replace(minute=current_minutes, second=0, microsecond=0)
        
        # Calculate how many images we should have
        images_needed = hours_back * 6  # 6 images per hour
        
        # Generate timestamps for the past hours
        for i in range(images_needed):
            timestamp_dt = current_time - timedelta(minutes=i * 10)
            timestamp = generate_timestamp(timestamp_dt)
            
            # Check if we have all bands for this timestamp
            missing_bands = []
            for band_key, band_info in BANDS.items():
                _, filename = self.generate_image_url(band_key, timestamp)
                history_key = f"{band_key}_{filename}"
                if history_key not in self.download_history:
                    missing_bands.append(band_key)
            
            if missing_bands:
                missing_timestamps.append({
                    'timestamp': timestamp,
                    'datetime': timestamp_dt,
                    'missing_bands': missing_bands
                })
        
        return missing_timestamps
    
    def get_comprehensive_missing_frames(self, hours_back=2):
        """Get comprehensive list of missing frames including expected but not attempted frames"""
        missing_frames = []
        
        if self.frame_tracker:
            # Get all expected frames
            expected_frames = self.frame_tracker.get_expected_frames(hours_back)
            
            # Also check filesystem state to catch discrepancies
            existing_files = {}
            for band_key, band_info in BANDS.items():
                raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
                if os.path.exists(raw_dir):
                    for filename in os.listdir(raw_dir):
                        if filename.endswith('.jpg') and not filename.startswith('._'):
                            try:
                                timestamp_str = filename.split('_')[0]
                                frame_dt = parse_timestamp(timestamp_str)
                                timestamp = generate_timestamp(frame_dt)
                                
                                if timestamp not in existing_files:
                                    existing_files[timestamp] = set()
                                existing_files[timestamp].add(band_key)
                            except Exception:
                                continue
            
            for frame_info in expected_frames:
                timestamp = frame_info['timestamp']
                frame_dt = frame_info['datetime']
                
                missing_bands = []
                
                for band_key in BANDS.keys():
                    # Check frame tracker status
                    frame_status = self.frame_tracker.get_frame_status(timestamp, band_key)
                    
                    # Cross-reference with filesystem
                    file_exists = timestamp in existing_files and band_key in existing_files[timestamp]
                    
                    if frame_status is None:
                        # Never attempted
                        missing_bands.append(band_key)
                    elif frame_status['status'] == 'downloaded' and not file_exists:
                        # Tracking says downloaded but file is missing - need to re-download
                        missing_bands.append(band_key)
                        self.logger.warning(f"Frame {timestamp} {band_key} marked as downloaded but file missing - will re-download")
                    elif frame_status['status'] != 'downloaded':
                        # Failed or pending
                        missing_bands.append(band_key)
                
                if missing_bands:
                    missing_frames.append({
                        'timestamp': timestamp,
                        'datetime': frame_dt,
                        'missing_bands': missing_bands,
                        'frame_age_minutes': (datetime.now(timezone.utc) - frame_dt).total_seconds() / 60
                    })
        else:
            # Fallback to original method if tracking disabled
            return self.get_missing_timestamps(hours_back)
        
        return sorted(missing_frames, key=lambda x: x['timestamp'])
    
    def process_retry_queue(self):
        """Process frames needing retry with intelligent prioritization and responsive timing"""
        if not self.frame_tracker:
            return
        
        retry_frames = self.frame_tracker.get_frames_needing_retry(max_age_hours=6)  # Extended window
        
        if not retry_frames:
            self.logger.debug("No frames needing retry")
            return
        
        # Filter and prioritize retry frames based on realistic availability
        current_time = datetime.now(timezone.utc)
        worthy_retries = []
        
        for timestamp, bands in retry_frames.items():
            try:
                frame_dt = parse_timestamp(timestamp)
                age_minutes = (current_time - frame_dt).total_seconds() / 60
                
                # Only retry frames that are mature enough to likely be available
                if age_minutes < 20:  # Frames younger than 20 minutes may still be in publishing pipeline (15-min delay + buffer)
                    continue  # Too young, likely still not available
                
                # Analyze failure patterns to avoid repeated futile attempts
                bands_to_retry = []
                for band_key in bands:
                    frame_status = self.frame_tracker.get_frame_status(timestamp, band_key)
                    
                    # Skip bands that have failed too many times recently
                    if frame_status and frame_status.get('retry_count', 0) > 5:
                        # If we've tried 5+ times and it's been more than 3 hours, mark as missing
                        if age_minutes > 180:
                            self.frame_tracker.mark_frame_persistent_missing(timestamp, band_key)
                            continue
                    
                    bands_to_retry.append(band_key)
                
                if bands_to_retry:
                    worthy_retries.append({
                        'timestamp': timestamp,
                        'bands': bands_to_retry,
                        'age_minutes': age_minutes
                    })
            
            except Exception as e:
                self.logger.error(f"Error processing retry frame {timestamp}: {e}")
        
        if not worthy_retries:
            self.logger.debug("No worthy retry candidates found")
            return
        
        # Sort by age (oldest first - highest priority)
        worthy_retries.sort(key=lambda x: x['age_minutes'], reverse=True)
        
        # Limit retries to avoid overwhelming the server  
        max_retries_per_session = 20  # Increased from 15 to 20 for more thorough retry processing
        if len(worthy_retries) > max_retries_per_session:
            worthy_retries = worthy_retries[:max_retries_per_session]
        
        self.logger.info(f"Processing {len(worthy_retries)} worthy retry candidates (20+ min old)")
        
        total_success = 0
        for retry_info in worthy_retries:
            timestamp = retry_info['timestamp']
            bands = retry_info['bands']
            age_minutes = retry_info['age_minutes']
            
            dt = parse_timestamp(timestamp)
            local_time = get_local_time(dt)
            
            self.logger.debug(f"Retry: {local_time.strftime('%Y-%m-%d %H:%M')} (GMT-4) - "
                            f"{age_minutes:.1f}m old - {len(bands)} bands")
            
            frame_success = 0
            for band_key in bands:
                try:
                    if self.download_image(band_key, timestamp):
                        frame_success += 1
                        total_success += 1
                except Exception as e:
                    self.logger.error(f"Retry error downloading {band_key} for {timestamp}: {e}")
            
            # Trigger processing if any downloads succeeded
            if frame_success > 0:
                self._trigger_processing_for_timestamp(timestamp)
            
            # Brief pause between retry attempts
            time.sleep(0.6)  # Faster retry processing
        
        if total_success > 0:
            self.logger.info(f"Retry session complete: {total_success} images downloaded successfully")
        else:
            self.logger.debug("Retry session complete: no new images available")
    
    def enhanced_catch_up_downloads(self, hours_back=2):
        """Enhanced catch-up downloads with comprehensive frame tracking"""
        self.logger.info(f"Starting enhanced catch-up for past {hours_back} hours")
        
        # First, process any pending retries
        self.process_retry_queue()
        
        # Then check for new missing frames
        missing_frames = self.get_comprehensive_missing_frames(hours_back)
        
        if not missing_frames:
            self.logger.info("No missing frames found")
            return
        
        # Separate frames by age for prioritized processing
        recent_frames = []  # < 20 minutes old
        older_frames = []   # >= 20 minutes old
        
        for frame in missing_frames:
            if frame['frame_age_minutes'] < 20:
                recent_frames.append(frame)
            else:
                older_frames.append(frame)
        
        self.logger.info(f"Found {len(recent_frames)} recent missing frames, {len(older_frames)} older missing frames")
        
        # Process recent frames first (higher priority)
        for frame_list, priority_name in [(recent_frames, "recent"), (older_frames, "older")]:
            if not frame_list:
                continue
                
            self.logger.info(f"Processing {len(frame_list)} {priority_name} frames")
            
            for item in frame_list:
                timestamp = item['timestamp']
                dt = item['datetime']
                local_time = get_local_time(dt)
                
                self.logger.info(f"Downloading missing {priority_name} frame for {local_time.strftime('%Y-%m-%d %H:%M')} (GMT-4) - {len(item['missing_bands'])} bands")
                
                # Download missing bands with appropriate concurrency
                max_workers = 4 if priority_name == "recent" else 2
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = []
                    for band_key in item['missing_bands']:
                        future = executor.submit(self.download_image, band_key, timestamp)
                        futures.append(future)
                    
                    # Wait for all downloads to complete
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as e:
                            self.logger.error(f"Error in enhanced catch-up download: {e}")
                
                # Adjust delay based on priority
                delay = 0.5 if priority_name == "recent" else 1.0
                time.sleep(delay)
    
    def cleanup_old_images(self):
        """Remove images older than retention period"""
        self.logger.info("Starting cleanup of old images")
        
        retention_hours = IMAGE_SETTINGS['retention_hours']
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
        
        removed_count = 0
        
        for band_key, band_info in BANDS.items():
            raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
            
            if not os.path.exists(raw_dir):
                continue
            
            for filename in os.listdir(raw_dir):
                if not filename.endswith('.jpg') or filename.startswith('._'):
                    continue
                
                # Extract timestamp from filename
                try:
                    timestamp_str = filename.split('_')[0]
                    file_dt = parse_timestamp(timestamp_str)
                    
                    # Remove if older than retention period
                    if file_dt < cutoff_time:
                        file_path = os.path.join(raw_dir, filename)
                        os.remove(file_path)
                        
                        # Remove from download history
                        history_key = f"{band_key}_{filename}"
                        self.download_history.discard(history_key)
                        
                        removed_count += 1
                        self.logger.debug(f"Removed old image: {filename}")
                
                except Exception as e:
                    self.logger.error(f"Error processing {filename}: {e}")
        
        self.logger.info(f"Cleanup complete. Removed {removed_count} old images")
    
    def download_current_images(self):
        """Download images for the current time slot with progressive strategy"""
        timestamp = generate_timestamp()
        dt = parse_timestamp(timestamp)
        local_time = get_local_time(dt)
        
        # Calculate how long ago this time slot was
        now = datetime.now(timezone.utc)
        slot_age_minutes = (now - dt).total_seconds() / 60
        
        self.logger.info(f"Downloading images for {local_time.strftime('%Y-%m-%d %H:%M')} (GMT-4) - {slot_age_minutes:.1f} minutes old")
        
        # Progressive download strategy based on slot age
        # NOAA typically has 15-minute publishing delay, so we expect:
        # - Very recent slots (< 15 min): Likely not available yet
        # - Recent slots (15-30 min): Should be available
        # - Mature slots (30+ min): Definitely should be available
        
        if slot_age_minutes < 15:
            self.logger.debug(f"Slot is very recent ({slot_age_minutes:.1f}m) - likely not published yet")
        elif slot_age_minutes < 30:
            self.logger.debug(f"Slot is recent ({slot_age_minutes:.1f}m) - should be available")
        else:
            self.logger.debug(f"Slot is mature ({slot_age_minutes:.1f}m) - should definitely be available")
        
        # Always attempt download regardless of age - let the server/tracking handle failures
        results = self.download_all_bands_for_timestamp(timestamp)
        
        # Log results
        success_count = sum(1 for success in results.values() if success)
        self.logger.info(f"Downloaded {success_count}/{len(results)} images successfully")
        
        # If no images downloaded, provide helpful feedback
        if success_count == 0:
            if slot_age_minutes < 15:
                self.logger.debug(f"No images available yet - expected for slots < 15 minutes old")
            elif slot_age_minutes < 30:
                self.logger.info(f"No images available yet - may still be in publishing pipeline")
            else:
                self.logger.warning(f"No images downloaded for mature slot - possible server issue or missing data")
        
        return results
    
    def catch_up_downloads(self, hours_back=2):
        """Download any missing images from the past N hours (legacy method for compatibility)"""
        return self.enhanced_catch_up_downloads(hours_back)
    
    def get_frame_statistics(self):
        """Get frame download statistics"""
        if not self.frame_tracker:
            return None
            
        stats = self.frame_tracker.tracking_data['statistics'].copy()
        
        # Add current status counts
        current_time = datetime.now(timezone.utc)
        cutoff_time = current_time - timedelta(hours=2)
        
        recent_frames = 0
        downloaded_frames = 0
        failed_frames = 0
        missing_frames = 0
        pending_retries = 0
        
        for timestamp, frame_data in self.frame_tracker.tracking_data['frames'].items():
            try:
                frame_dt = parse_timestamp(timestamp)
                if frame_dt < cutoff_time:
                    continue
                    
                recent_frames += len(frame_data)
                
                for band_key, band_data in frame_data.items():
                    status = band_data['status']
                    if status == 'downloaded':
                        downloaded_frames += 1
                    elif status == 'failed':
                        failed_frames += 1
                    elif status == 'missing':
                        missing_frames += 1
                    elif band_data['retry_count'] > 0:
                        pending_retries += 1
                        
            except Exception:
                continue
        
        stats.update({
            'recent_frames_total': recent_frames,
            'recent_downloaded': downloaded_frames,
            'recent_failed': failed_frames,
            'recent_missing': missing_frames,
            'pending_retries': pending_retries,
            'success_rate': (downloaded_frames / recent_frames * 100) if recent_frames > 0 else 0
        })
        
        return stats
    
    def run_continuous(self):
        """Run the downloader continuously with simplified 10-minute intervals"""
        self.logger.info("Starting continuous download mode with simplified 10-minute intervals")
        
        # Use intelligent startup downloads
        self.smart_startup_downloads(default_hours_back=2)
        
        # Initial cleanup
        self.cleanup_old_images()
        
        # Cleanup old tracking data if enabled
        if self.frame_tracker:
            cleaned_count = self.frame_tracker.cleanup_old_tracking_data()
            if cleaned_count > 0:
                self.logger.info(f"Cleaned up {cleaned_count} old tracking records")
        
        last_check_time = None
        last_cleanup_time = datetime.now()
        last_stats_report = datetime.now()
        
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                current_minutes = (now.minute // 10) * 10
                current_slot = now.replace(minute=current_minutes, second=0, microsecond=0)
                
                # Run comprehensive check every 10 minutes
                if last_check_time != current_slot:
                    slot_age_minutes = (now - current_slot).total_seconds() / 60
                    
                    # Modified logic: Always attempt downloads, but adjust strategy based on age
                    # The 16-minute delay should apply to when images were taken, not current time slot
                    self.logger.info(f"Starting 10-minute check cycle at {now.strftime('%H:%M:%S')} UTC")
                    
                    # Step 1: Download current images (always attempt - let download logic handle availability)
                    self.logger.debug("Step 1: Downloading current images...")
                    results = self.download_current_images()
                    success_count = sum(1 for success in results.values() if success)
                    
                    if success_count > 0:
                        current_timestamp = generate_timestamp(current_slot)
                        self._trigger_processing_for_timestamp(current_timestamp)
                        self.logger.debug(f"Downloaded {success_count} new images for current slot")
                    else:
                        self.logger.debug("No new images downloaded for current slot")
                    
                    # Step 2: Process retry queue
                    self.logger.debug("Step 2: Processing retry queue...")
                    retry_count_before = len(self.frame_tracker.get_frames_needing_retry(max_age_hours=6)) if self.frame_tracker else 0
                    self.process_retry_queue()
                    
                    # Step 3: Run gap fill to catch any missing frames
                    self.logger.debug("Step 3: Running gap fill...")
                    self._intelligent_gap_fill()
                    
                    last_check_time = current_slot
                    self.logger.info(f"10-minute check cycle complete")
                    
                    # Run cleanup every hour
                    if (datetime.now() - last_cleanup_time).total_seconds() > 3600:
                        self.cleanup_old_images()
                        last_cleanup_time = datetime.now()
                        
                        # Also cleanup tracking data
                        if self.frame_tracker:
                            cleaned_count = self.frame_tracker.cleanup_old_tracking_data()
                            if cleaned_count > 0:
                                self.logger.info(f"Cleaned up {cleaned_count} old tracking records")
                
                # Report statistics every 30 minutes
                if (datetime.now() - last_stats_report).total_seconds() > 1800:
                    if self.frame_tracker:
                        stats = self.get_frame_statistics()
                        if stats:
                            self.logger.info(f"Frame Statistics - Success Rate: {stats['success_rate']:.1f}%, "
                                           f"Recent: {stats['recent_downloaded']}/{stats['recent_frames_total']}, "
                                           f"Pending Retries: {stats['pending_retries']}, "
                                           f"Total Attempts: {stats['total_attempts']}")
                    last_stats_report = datetime.now()
                
                # Check every 30 seconds for the next 10-minute slot
                time.sleep(30)
                
            except KeyboardInterrupt:
                self.logger.info("Received keyboard interrupt, stopping...")
                break
            except Exception as e:
                self.logger.error(f"Error in continuous download loop: {e}")
                time.sleep(60)  # Wait a minute before retrying
    
    def _intelligent_gap_fill(self):
        """Intelligently fill gaps in available frames with responsive timing"""
        try:
            # Look for missing frames that are old enough to likely be available
            missing_frames = self.get_comprehensive_missing_frames(hours_back=3)
            
            # Filter for frames that are likely to be available (20+ minutes old - accounts for confirmed 15-minute publishing delay)
            current_time = datetime.now(timezone.utc)
            mature_missing = []
            
            for frame in missing_frames:
                if frame['frame_age_minutes'] >= 20:  # Conservative threshold accounting for 15-minute publishing delay + buffer
                    mature_missing.append(frame)
            
            if not mature_missing:
                self.logger.debug("No mature missing frames found for gap filling")
                return
            
            # Limit gap filling to avoid overwhelming the server
            max_gap_fill = 15  # Increased from 10 to 15 for more efficient gap filling
            if len(mature_missing) > max_gap_fill:
                # Sort by age (oldest first) and take the most mature
                mature_missing.sort(key=lambda x: x['frame_age_minutes'], reverse=True)
                mature_missing = mature_missing[:max_gap_fill]
            
            self.logger.info(f"Gap filling: attempting {len(mature_missing)} mature missing frames (20+ min old)")
            
            success_count = 0
            for frame in mature_missing:
                timestamp = frame['timestamp']
                dt = frame['datetime']
                local_time = get_local_time(dt)
                
                self.logger.debug(f"Gap fill: {local_time.strftime('%Y-%m-%d %H:%M')} (GMT-4) - "
                                f"{frame['frame_age_minutes']:.1f}m old - {len(frame['missing_bands'])} bands")
                
                # Download missing bands for this frame
                frame_success_count = 0
                for band_key in frame['missing_bands']:
                    try:
                        if self.download_image(band_key, timestamp):
                            frame_success_count += 1
                            success_count += 1
                    except Exception as e:
                        self.logger.error(f"Gap fill error downloading {band_key} for {timestamp}: {e}")
                
                # Trigger processing if any downloads succeeded
                if frame_success_count > 0:
                    self._trigger_processing_for_timestamp(timestamp)
                
                # Brief pause between gap fill attempts
                time.sleep(0.8)  # Slightly faster gap filling
            
            if success_count > 0:
                self.logger.info(f"Gap filling complete: {success_count} images downloaded")
            else:
                self.logger.debug("Gap filling complete: no new images available")
                
        except Exception as e:
            self.logger.error(f"Error in intelligent gap fill: {e}")

    def get_frame_status_report(self, hours_back=2):
        """Generate a detailed frame status report"""
        if not self.frame_tracker:
            return "Frame tracking not enabled"
            
        report_lines = []
        report_lines.append(f"Frame Status Report (Past {hours_back} hours)")
        report_lines.append("=" * 50)
        
        # Get statistics
        stats = self.get_frame_statistics()
        if stats:
            report_lines.append(f"Success Rate: {stats['success_rate']:.1f}%")
            report_lines.append(f"Total Attempts: {stats['total_attempts']}")
            report_lines.append(f"Successful Downloads: {stats['successful_downloads']}")
            report_lines.append(f"Failed Attempts: {stats['failed_attempts']}")
            report_lines.append(f"Retry Attempts: {stats['retry_attempts']}")
            report_lines.append(f"Pending Retries: {stats['pending_retries']}")
            report_lines.append("")
        
        # Get expected frames
        expected_frames = self.frame_tracker.get_expected_frames(hours_back)
        missing_frames = self.get_comprehensive_missing_frames(hours_back)
        
        report_lines.append(f"Expected Frames: {len(expected_frames)}")
        report_lines.append(f"Missing Frames: {len(missing_frames)}")
        report_lines.append("")
        
        if missing_frames:
            report_lines.append("Missing Frames Details:")
            for frame in missing_frames[:10]:  # Show first 10
                dt = frame['datetime']
                local_time = get_local_time(dt)
                age_str = f"{frame['frame_age_minutes']:.1f}m"
                bands_str = ", ".join(frame['missing_bands'])
                report_lines.append(f"  {local_time.strftime('%Y-%m-%d %H:%M')} (GMT-4) [{age_str}]: {bands_str}")
            
            if len(missing_frames) > 10:
                report_lines.append(f"  ... and {len(missing_frames) - 10} more")
        
        return "\n".join(report_lines)
    
    def stop(self):
        """Stop the continuous download"""
        self.logger.info("Stopping image downloader")
        self.stop_event.set()

    def get_filesystem_frame_status(self, hours_back=48):
        """
        Get actual filesystem status of frames, regardless of tracking data
        Returns the oldest frame found and missing frames based on filesystem
        """
        existing_frames = {}  # timestamp -> {band_key: True/False}
        oldest_frame_time = None
        newest_frame_time = None
        
        # Scan all band directories for existing files
        for band_key, band_info in BANDS.items():
            raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
            
            if not os.path.exists(raw_dir):
                continue
                
            for filename in os.listdir(raw_dir):
                if not filename.endswith('.jpg') or filename.startswith('._'):
                    continue
                    
                try:
                    # Extract timestamp from filename
                    timestamp_str = filename.split('_')[0]
                    frame_dt = parse_timestamp(timestamp_str)
                    timestamp = generate_timestamp(frame_dt)
                    
                    # Initialize frame record if not exists
                    if timestamp not in existing_frames:
                        existing_frames[timestamp] = {}
                    
                    existing_frames[timestamp][band_key] = True
                    
                    # Track oldest and newest frames
                    if oldest_frame_time is None or frame_dt < oldest_frame_time:
                        oldest_frame_time = frame_dt
                    if newest_frame_time is None or frame_dt > newest_frame_time:
                        newest_frame_time = frame_dt
                        
                except Exception as e:
                    self.logger.warning(f"Could not parse timestamp from {filename}: {e}")
                    continue
        
        # Determine the time range to check based on existing frames
        current_time = datetime.now(timezone.utc)
        current_minutes = (current_time.minute // 10) * 10
        current_slot = current_time.replace(minute=current_minutes, second=0, microsecond=0)
        
        if not existing_frames:
            # No frames at all - download last N hours
            start_time = current_slot - timedelta(hours=hours_back)
            self.logger.info(f"No existing frames found - will download last {hours_back} hours")
        else:
            # Frames exist - download from oldest frame to current
            # Add some buffer to account for timing differences between bands
            buffer_minutes = 30  # 30 minute buffer before oldest frame
            start_time = oldest_frame_time - timedelta(minutes=buffer_minutes)
            self.logger.info(f"Existing frames found from {oldest_frame_time.strftime('%Y-%m-%d %H:%M')} to {newest_frame_time.strftime('%Y-%m-%d %H:%M')} UTC")
            self.logger.info(f"Will fill gaps from {start_time.strftime('%Y-%m-%d %H:%M')} UTC to current time")
        
        # Generate expected frames for the determined time range
        missing_frames = []
        current_check_time = current_slot
        
        while current_check_time >= start_time:
            timestamp = generate_timestamp(current_check_time)
            missing_bands = []
            
            # Check each band
            for band_key in BANDS.keys():
                if timestamp not in existing_frames or band_key not in existing_frames[timestamp]:
                    missing_bands.append(band_key)
            
            if missing_bands:
                frame_age_minutes = (current_time - current_check_time).total_seconds() / 60
                missing_frames.append({
                    'timestamp': timestamp,
                    'datetime': current_check_time,
                    'missing_bands': missing_bands,
                    'frame_age_minutes': frame_age_minutes
                })
            
            current_check_time -= timedelta(minutes=10)
        
        return {
            'missing_frames': sorted(missing_frames, key=lambda x: x['timestamp']),
            'existing_frame_count': len(existing_frames),
            'oldest_frame_time': oldest_frame_time,
            'newest_frame_time': newest_frame_time,
            'time_range_hours': (current_slot - start_time).total_seconds() / 3600 if start_time else hours_back
        }

    def smart_startup_downloads(self, default_hours_back=2):
        """
        Intelligent startup downloads with realistic timing expectations
        Strategy: Download older frames first (most likely to be available), then work forward
        """
        self.logger.info("Starting intelligent startup downloads with realistic timing")
        
        # Analyze filesystem state
        fs_status = self.get_filesystem_frame_status(default_hours_back)
        missing_frames = fs_status['missing_frames']
        
        if not missing_frames:
            self.logger.info("No missing frames detected - system is up to date")
            return
        
        # Log analysis results
        total_bands_missing = sum(len(frame['missing_bands']) for frame in missing_frames)
        self.logger.info(f"Filesystem analysis complete:")
        self.logger.info(f"  - Existing frames: {fs_status['existing_frame_count']}")
        self.logger.info(f"  - Missing frames: {len(missing_frames)}")
        self.logger.info(f"  - Total missing band-frames: {total_bands_missing}")
        self.logger.info(f"  - Time range: {fs_status['time_range_hours']:.1f} hours")
        
        if fs_status['oldest_frame_time']:
            oldest_local = get_local_time(fs_status['oldest_frame_time'])
            newest_local = get_local_time(fs_status['newest_frame_time'])
            self.logger.info(f"  - Existing range: {oldest_local.strftime('%Y-%m-%d %H:%M')} to {newest_local.strftime('%Y-%m-%d %H:%M')} (GMT-4)")
        
        # Smart prioritization: Download older frames first (higher success probability)
        # Categorize frames by age and availability likelihood
        stable_frames = []    # > 2 hours old - very likely to be available
        settling_frames = []  # 45 minutes to 2 hours - likely available
        recent_frames = []    # 15-45 minutes - might be available
        too_recent_frames = []  # < 15 minutes - unlikely to be available
        
        current_time = datetime.now(timezone.utc)
        
        for frame in missing_frames:
            age_minutes = frame['frame_age_minutes']
            if age_minutes > 120:  # > 2 hours
                stable_frames.append(frame)
            elif age_minutes > 45:  # 45 min - 2 hours
                settling_frames.append(frame)
            elif age_minutes > 15:  # 15-45 minutes
                recent_frames.append(frame)
            else:  # < 15 minutes
                too_recent_frames.append(frame)
        
        # Sort each category by age (oldest first within category)
        stable_frames.sort(key=lambda x: x['frame_age_minutes'], reverse=True)
        settling_frames.sort(key=lambda x: x['frame_age_minutes'], reverse=True)
        recent_frames.sort(key=lambda x: x['frame_age_minutes'], reverse=True)
        
        self.logger.info(f"Frame categorization:")
        self.logger.info(f"  - Stable frames (>2h old): {len(stable_frames)}")
        self.logger.info(f"  - Settling frames (45m-2h): {len(settling_frames)}")
        self.logger.info(f"  - Recent frames (15-45m): {len(recent_frames)}")
        self.logger.info(f"  - Too recent (<15m): {len(too_recent_frames)} (will skip)")
        
        # Process frames in order of decreasing reliability
        total_downloaded = 0
        processed_count = 0
        
        for frame_list, category_name, batch_size, delay_between_batches in [
            (stable_frames, "stable", 8, 1.0),      # Fast processing for stable frames
            (settling_frames, "settling", 6, 2.0),  # Moderate processing
            (recent_frames, "recent", 4, 3.0),      # Careful processing for recent frames
        ]:
            if not frame_list:
                continue
                
            self.logger.info(f"Downloading {len(frame_list)} {category_name} frames (batch size: {batch_size})")
            
            # Process in batches to avoid overwhelming the server
            for i in range(0, len(frame_list), batch_size):
                batch = frame_list[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (len(frame_list) + batch_size - 1) // batch_size
                
                self.logger.info(f"Processing {category_name} batch {batch_num}/{total_batches} ({len(batch)} frames)")
                
                for frame in batch:
                    timestamp = frame['timestamp']
                    dt = frame['datetime']
                    local_time = get_local_time(dt)
                    processed_count += 1
                    
                    self.logger.info(f"Frame {processed_count}/{len(stable_frames + settling_frames + recent_frames)}: "
                                   f"{local_time.strftime('%Y-%m-%d %H:%M')} (GMT-4) - "
                                   f"{frame['frame_age_minutes']:.1f}m old - {len(frame['missing_bands'])} bands")
                    
                    # Download missing bands for this frame
                    frame_success_count = 0
                    for band_key in frame['missing_bands']:
                        try:
                            if self.download_image(band_key, timestamp):
                                frame_success_count += 1
                                total_downloaded += 1
                        except Exception as e:
                            self.logger.error(f"Error downloading {band_key} for {timestamp}: {e}")
                    
                    # Trigger processing if any downloads succeeded
                    if frame_success_count > 0:
                        self._trigger_processing_for_timestamp(timestamp)
                        self.logger.debug(f"Downloaded {frame_success_count}/{len(frame['missing_bands'])} bands")
                    
                    # Brief pause between frames to be server-friendly
                    time.sleep(0.5)
                
                # Longer pause between batches
                if i + batch_size < len(frame_list):  # Not the last batch
                    self.logger.debug(f"Pausing {delay_between_batches}s between {category_name} batches")
                    time.sleep(delay_between_batches)
        
        # Report on skipped frames
        if too_recent_frames:
            self.logger.info(f"Skipped {len(too_recent_frames)} frames that are too recent (< 15 minutes old)")
            self.logger.info("These will be handled by the continuous download process")
        
        self.logger.info(f"Intelligent startup downloads complete: {total_downloaded} images downloaded successfully")
        
        # Final processing pass for any existing images that weren't processed
        self._trigger_processing_all_pending()

    def set_processor(self, processor):
        """Set the processor instance for triggering processing after downloads"""
        self.processor = processor
        self.logger.info("Processor instance set for download-triggered processing")

    def _trigger_processing_for_timestamp(self, timestamp):
        """Trigger processing for a specific timestamp across all bands"""
        try:
            # Small delay to ensure all file operations are complete before processing
            time.sleep(1.0)  # 1 second delay to allow file system operations to complete
            
            if self.processor:
                queued_count = self.processor.trigger_processing_for_timestamp(timestamp)
                if queued_count > 0:
                    self.logger.debug(f"Triggered processing for {queued_count} images at timestamp {timestamp}")
            else:
                self.logger.debug(f"No processor available - processing will be handled by monitoring threads")
            
        except Exception as e:
            self.logger.warning(f"Could not trigger processing for {timestamp}: {e}")

    def _trigger_processing_all_pending(self):
        """Trigger processing for all pending raw images"""
        try:
            if self.processor:
                queued_count = self.processor.trigger_process_all_pending()
                self.logger.info(f"Triggered processing for {queued_count} pending raw images")
            else:
                self.logger.info("No processor available - processing will be handled by monitoring threads")
            
        except Exception as e:
            self.logger.warning(f"Could not trigger global processing: {e}")

    def check_for_timing_differences(self, hours_back=1):
        """
        Check for frames where some bands are available but others are missing
        This handles the case where bands are updated at slightly different times
        """
        try:
            partial_frames = []
            current_time = datetime.now(timezone.utc)
            
            # Get filesystem state
            fs_status = self.get_filesystem_frame_status(hours_back)
            
            # Look for frames that have some bands but not all
            current_slot = current_time.replace(minute=(current_time.minute // 10) * 10, second=0, microsecond=0)
            check_time = current_slot
            
            while check_time >= current_slot - timedelta(hours=hours_back):
                timestamp = generate_timestamp(check_time)
                existing_bands = set()
                missing_bands = set()
                
                # Check each band directory
                for band_key, band_info in BANDS.items():
                    raw_dir = os.path.join(IMAGES_DIR, band_info['folder_name'], 'raw_images')
                    if os.path.exists(raw_dir):
                        url, filename = self.generate_image_url(band_key, timestamp)
                        file_path = os.path.join(raw_dir, filename)
                        
                        if os.path.exists(file_path):
                            existing_bands.add(band_key)
                        else:
                            missing_bands.add(band_key)
                
                # If we have some bands but not all, this indicates timing differences
                if existing_bands and missing_bands:
                    frame_age_minutes = (current_time - check_time).total_seconds() / 60
                    
                    # Only consider recent frames (last 30 minutes) for timing difference handling
                    if frame_age_minutes <= 30:
                        partial_frames.append({
                            'timestamp': timestamp,
                            'datetime': check_time,
                            'existing_bands': list(existing_bands),
                            'missing_bands': list(missing_bands),
                            'frame_age_minutes': frame_age_minutes
                        })
                
                check_time -= timedelta(minutes=10)
            
            if partial_frames:
                self.logger.info(f"Found {len(partial_frames)} frames with timing differences")
                
                # Download missing bands for partial frames
                for frame in partial_frames:
                    timestamp = frame['timestamp']
                    local_time = get_local_time(frame['datetime'])
                    
                    self.logger.info(f"Downloading missing bands for {local_time.strftime('%Y-%m-%d %H:%M')} (GMT-4): {', '.join(frame['missing_bands'])}")
                    
                    # Download missing bands with higher concurrency since these are recent
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        futures = []
                        for band_key in frame['missing_bands']:
                            future = executor.submit(self.download_image, band_key, timestamp)
                            futures.append((future, band_key))
                        
                        # Wait for downloads and trigger processing if any succeed
                        success_count = 0
                        for future, band_key in futures:
                            try:
                                if future.result():
                                    success_count += 1
                            except Exception as e:
                                self.logger.error(f"Error downloading {band_key} for timing difference: {e}")
                        
                        if success_count > 0:
                            self._trigger_processing_for_timestamp(timestamp)
                            self.logger.info(f"Successfully downloaded {success_count}/{len(frame['missing_bands'])} missing bands for {timestamp}")
            
            return len(partial_frames)
            
        except Exception as e:
            self.logger.error(f"Error checking for timing differences: {e}")
            return 0


def main():
    """Main function to run the image downloader"""
    downloader = ImageDownloader()
    
    try:
        # Run continuous download
        downloader.run_continuous()
    except KeyboardInterrupt:
        print("\nShutting down image downloader...")
        downloader.stop()


if __name__ == "__main__":
    main()
