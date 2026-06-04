"""
Configuration file for Satellite Weather Looping System
"""
import os
from datetime import datetime, timezone, timedelta

# Base directory for the application
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, 'images')

# All log files are written here (created on import so handlers can open files).
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

# GOES-19 Satellite Band Configuration
BANDS = {
    'GeoColor': {
        'folder_name': 'GeoColor',
        'url_base': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/taw/GEOCOLOR/',
        'url_pattern': '{timestamp}_GOES19-ABI-taw-GEOCOLOR-7200x4320.jpg',
        'label': 'GeoColor',
        'available_24h': True
    },
    'Sandwich_RGB': {
        'folder_name': 'Sandwich RGB',
        'url_base': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/taw/Sandwich/',
        'url_pattern': '{timestamp}_GOES19-ABI-taw-Sandwich-7200x4320.jpg',
        'label': 'Sandwich RGB',
        'available_24h': True
    },
    'Band_2': {
        'folder_name': 'Band 2 (Red-Visible - 0.64 um)',
        'url_base': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/taw/02/',
        'url_pattern': '{timestamp}_GOES19-ABI-taw-02-7200x4320.jpg',
        'label': 'Band 2 (Red-Visible - 0.64 μm)',
        'available_24h': False  # Only available during daylight
    },
    'Band_13': {
        'folder_name': 'Band 13 (Clean Longwave IR - 10.3 um)',
        'url_base': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/taw/13/',
        'url_pattern': '{timestamp}_GOES19-ABI-taw-13-7200x4320.jpg',
        'label': 'Band 13 (Clean Longwave IR - 10.3 μm)',
        'available_24h': True
    },
    'Band_10': {
        'folder_name': 'Band 10 (Lower-level Water Vapor - 7.3 um)',
        'url_base': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/taw/10/',
        'url_pattern': '{timestamp}_GOES19-ABI-taw-10-7200x4320.jpg',
        'label': 'Band 10 (Lower-level Water Vapor - 7.3 μm)',
        'available_24h': True
    },
    'Band_9': {
        'folder_name': 'Band 9 (Mid-Level Water Vapour - 6.9 um)',
        'url_base': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/taw/09/',
        'url_pattern': '{timestamp}_GOES19-ABI-taw-09-7200x4320.jpg',
        'label': 'Band 9 (Mid-Level Water Vapour - 6.9 μm)',
        'available_24h': True
    },
    'Band_8': {
        'folder_name': 'Band 8 (Upper-Level Water Vapor - 6.2 um)',
        'url_base': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/taw/08/',
        'url_pattern': '{timestamp}_GOES19-ABI-taw-08-7200x4320.jpg',
        'label': 'Band 8 (Upper-Level Water Vapor - 6.2 μm)',
        'available_24h': True
    }
}

# Trinidad and Tobago Location Configuration
TRINIDAD_LOCATION = {
    'name': 'Trinidad and Tobago',
    'latitude': 10.6918,
    'longitude': -61.2225,
    'timezone': 'America/Port_of_Spain',  # GMT-4
    'elevation': 0  # Sea level
}

# Image Processing Configuration
IMAGE_SETTINGS = {
    'source_resolution': (7200, 4320),  # Original image resolution
    'retention_hours': 48,  # Keep images for 48 hours
    'update_interval_seconds': 600,  # 10 minutes between updates
    'max_frames': 288,  # Maximum frames to keep (48 hours * 6 per hour)
    'image_format': 'jpg',
    'compression_quality': 85,  # JPEG compression quality (1-100)
}

# Storage Management Configuration
STORAGE_CONFIG = {
    'max_directory_size_gb': 50,  # Maximum total size of images directory
    'cleanup_threshold_gb': 5,    # Trigger cleanup when less than this much free space
    'aggressive_cleanup_gb': 2,   # More aggressive cleanup when below this threshold
    'check_interval_seconds': 7200, # How often to check disk space
}

# Frame Tracking Configuration
FRAME_TRACKING_CONFIG = {
    'enable_tracking': True,  # Enable comprehensive frame tracking
    'tracking_file': 'frame_tracking.json',  # File to store frame tracking data
    'max_retry_attempts': 6,  # Increased retry attempts for missing frames
    'retry_intervals': [5, 15, 30, 60, 180, 360],  # Retry intervals in minutes: 5m, 15m, 30m, 1h, 3h, 6h
    'persistent_missing_threshold': 480,  # Increased to 8 hours (480 minutes) before marking as persistently missing
    'track_failed_attempts': True,  # Track failed download attempts
    'cleanup_tracking_days': 7,  # Days to keep tracking data
}

# Crop Settings for Different Zoom Levels
# These are placeholder values - adjust after testing with actual images
# Format: (left, top, right, bottom) in pixels from original 7200x4320 image
CROP_SETTINGS = {
    'Zoom1': {
        'name': 'Close Zoom - Trinidad & Tobago',
        'coordinates': (3140, 2320, 3960, 3060),  # Moved right and down significantly
        'output_size': (1920, 1080)  # 16:9 aspect ratio
    },
    'Zoom2': {
        'name': 'Medium Zoom - Regional Weather Systems',
        'coordinates': (3000, 2000, 4500, 3350),  # Reverted to previous settings
        'output_size': (1920, 1080)
    },
    'Zoom3': {
        'name': 'Wide Zoom - Atlantic Ocean View',
        'coordinates': (2925, 1200, 5625, 3900),  # Moved further to the right
        'output_size': (1920, 1080)
    }
}

# Downscaled variant generated for the 4-panel grid view.
# Each grid cell is only ~1/4 of the screen, so serving a half-size image there
# cuts browser decode CPU and memory ~4x. The full 1920x1080 image is still kept
# for the fullscreen viewer. The thumbnail is saved alongside the full image with
# a filename suffix so the existing cleanup logic removes both together.
GRID_THUMBNAIL_CONFIG = {
    'enabled': True,
    'size': (960, 540),   # half of the 1920x1080 full output
    'quality': 80,        # slightly lower quality is fine at grid size
    'suffix': '_grid',
}

# Grid Display Configuration
GRID_CONFIG = {
    'day_mode': {
        'top_left': 'GeoColor',
        'top_right_cycle': ['Sandwich_RGB', 'Band_10', 'Band_9', 'Band_8'],
        'bottom_left': 'Band_2',
        'bottom_right': 'Band_13'
    },
    'night_mode': {
        'top_left': 'GeoColor',
        'top_right_cycle': ['Band_10', 'Band_9', 'Band_8'],
        'bottom_left': 'Band_13',
        'bottom_right': 'Sandwich_RGB'
    },
    'default_frames': 144,  # 24 hours of frames
    'cycle_duration_seconds': 30  # How long each band shows in cycle
}

# Time Period Options (in hours)
TIME_PERIODS = [
    {'hours': 2, 'label': '2 Hours', 'frames': 12},
    {'hours': 6, 'label': '6 Hours', 'frames': 36},
    {'hours': 12, 'label': '12 Hours', 'frames': 72},
    {'hours': 24, 'label': '24 Hours', 'frames': 144},
    {'hours': 48, 'label': '48 Hours', 'frames': 288}
]

# FPS Configuration for different time periods
FPS_CONFIG = {
    'default_fps': {
        2: 10,  # 2 hour loop - 10 FPS
        6: 10,  # 6 hour loop - 10 FPS
        12: 5,  # 12 hour loop - 5 FPS
        24: 5,  # 24 hour loop - 5 FPS
        48: 1   # 48 hour loop - 1 FPS
    },
    'min_fps': 1,      # Minimum allowed FPS
    'max_fps': 10,     # Maximum allowed FPS
    'fps_step': 1,     # Step size for FPS adjustment
    'auto_adjust': True, # Automatically adjust FPS when time period changes
    'available_fps': [10, 5, 1]  # Available FPS options
}

# Label Configuration for Image Overlays
LABEL_CONFIG = {
    'font_size': 24,
    'font_color': 'black',
    'background_color': 'white',
    'padding': 10,
    'position': 'top_left',  # Options: top_left, top_right, bottom_left, bottom_right
    'opacity': 0.9,
    'font_family': 'Arial'
}

# Flask Application Configuration
FLASK_CONFIG = {
    'SECRET_KEY': os.environ.get('SECRET_KEY', 'dev-key-change-in-production'),  # Use env var in production
    'DEBUG': os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1', 'on'],
    'HOST': os.environ.get('FLASK_HOST', '0.0.0.0'),
    'PORT': int(os.environ.get('FLASK_PORT', 5000)),
    'THREADED': True,
    'JSON_SORT_KEYS': False,
    'SEND_FILE_MAX_AGE_DEFAULT': 300  # Cache static files for 5 minutes
}

# Download Configuration
DOWNLOAD_CONFIG = {
    'timeout': 30,  # Seconds
    'max_retries': 3,
    'retry_delay': 5,  # Seconds
    # Honest, identifying User-Agent (update the URL to your repo). Politely tells
    # NOAA's servers what this client is instead of impersonating a browser.
    'user_agent': 'SatelliteWeatherLoop/1.0 (+https://github.com/yourusername/satellite-weather-imager)',
    'concurrent_downloads': 4  # Number of simultaneous downloads
}

# Logging Configuration
LOGGING_CONFIG = {
    'level': 'INFO',
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'file': 'satellite_weather.log',
    'max_bytes': 10485760,  # 10MB
    'backup_count': 5
}

# Utility Functions
def get_image_timestamp_format():
    """
    Returns the timestamp format used in NOAA filenames
    Format: YYYYDDDHHSS where:
    - YYYY: Year
    - DDD: Day of year (001-365)
    - HH: Hour (00-23)
    - SS: Minute/10 (00-50 in steps of 10)
    """
    return "%Y%j%H%M"

def generate_timestamp(dt=None):
    """
    Generate a timestamp in NOAA format for a given datetime
    If no datetime provided, uses current time
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    
    # Round down to nearest 10 minutes
    minutes = (dt.minute // 10) * 10
    dt = dt.replace(minute=minutes, second=0, microsecond=0)
    
    # Format: YYYYDDDHHSS (SS is actually MM/10)
    year = dt.strftime('%Y')
    day_of_year = dt.strftime('%j')
    hour = dt.strftime('%H')
    minute_code = str(minutes).zfill(2)
    
    return f"{year}{day_of_year}{hour}{minute_code}"

def parse_timestamp(timestamp_str):
    """
    Parse a NOAA timestamp string back into a datetime object
    """
    year = int(timestamp_str[:4])
    day_of_year = int(timestamp_str[4:7])
    hour = int(timestamp_str[7:9])
    minute = int(timestamp_str[9:11])
    
    # Create datetime from year and day of year
    dt = datetime(year, 1, 1, hour, minute, tzinfo=timezone.utc)
    dt += timedelta(days=day_of_year - 1)
    
    return dt

def get_local_time(dt):
    """
    Convert UTC datetime to Trinidad & Tobago local time (GMT-4)
    """
    from pytz import timezone as pytz_timezone
    
    utc_time = dt.replace(tzinfo=timezone.utc)
    local_tz = pytz_timezone(TRINIDAD_LOCATION['timezone'])
    local_time = utc_time.astimezone(local_tz)
    
    return local_time

def create_directories():
    """
    Create all necessary directories for image storage
    """
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

# API Endpoints Configuration
API_ENDPOINTS = {
    'images': '/api/images/<band>/<zoom>/<hours>',
    'sun_status': '/api/sun-status',
    'config': '/api/config',
    'grid_images': '/api/grid-images/<hours>',
    'system_status': '/api/system-status'
}

if __name__ == "__main__":
    # Test configuration loading
    print("Configuration loaded successfully!")
    print(f"Number of bands configured: {len(BANDS)}")
    print(f"Image retention period: {IMAGE_SETTINGS['retention_hours']} hours")
    print(f"Update interval: {IMAGE_SETTINGS['update_interval_seconds']} seconds")
    
    # Test timestamp generation
    test_timestamp = generate_timestamp()
    print(f"\nCurrent timestamp: {test_timestamp}")
    
    # Test timestamp parsing
    parsed_dt = parse_timestamp(test_timestamp)
    print(f"Parsed datetime: {parsed_dt}")
    
    # Test local time conversion
    local_dt = get_local_time(parsed_dt)
    print(f"Local time (GMT-4): {local_dt}")
