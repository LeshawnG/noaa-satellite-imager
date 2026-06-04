"""
Standalone NOAA Satellite Update Monitor
Monitors GOES-19 satellite imagery update intervals from NOAA servers
to determine optimal refresh timing for the main application.

This module:
1. Checks every 1 minute for new satellite frames
2. Logs when new frames are published
3. Tracks time intervals between frame publications
4. Uses UTC time standard throughout
"""

import os
import time
import requests
import logging
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Configuration
MONITOR_CONFIG = {
    'check_interval_seconds': 60,  # Check every 1 minute
    'timeout_seconds': 10,         # HTTP request timeout
    'user_agent': 'SatelliteWeatherLoop-Monitor/1.0 (+https://github.com/yourusername/satellite-weather-imager)',
    'max_history_hours': 72,       # Keep tracking data for 72 hours
}

# NOAA GOES-19 Configuration (using GeoColor as primary monitor band)
NOAA_CONFIG = {
    'base_url': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/taw/GEOCOLOR/',
    'url_pattern': '{timestamp}_GOES19-ABI-taw-GEOCOLOR-7200x4320.jpg',
    'expected_interval_minutes': 10,  # Expected update every 10 minutes
}

# All log files go into a logs/ directory next to this script.
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

# Logging Configuration
LOG_CONFIG = {
    'update_time_log': os.path.join(LOGS_DIR, 'noaa_update_times.log'),
    'update_interval_log': os.path.join(LOGS_DIR, 'noaa_update_intervals.log'),
    'monitor_log': os.path.join(LOGS_DIR, 'monitor_debug.log'),
    'tracking_data': 'update_tracking.json'
}

class NOAASatelliteMonitor:
    """Monitor NOAA satellite imagery update patterns"""
    
    def __init__(self):
        self.setup_logging()
        self.session = self._setup_session()
        self.tracking_data = self._load_tracking_data()
        self.last_known_timestamp = None
        self.running = False
        
        self.logger.info("NOAA Satellite Update Monitor initialized")
        self.logger.info(f"Monitoring URL: {NOAA_CONFIG['base_url']}")
        self.logger.info(f"Check interval: {MONITOR_CONFIG['check_interval_seconds']} seconds")
    
    def setup_logging(self):
        """Setup logging for different purposes"""
        # Main monitor logger
        self.logger = logging.getLogger('NOAAMonitor')
        self.logger.setLevel(logging.INFO)
        
        # Create handlers
        monitor_handler = logging.FileHandler(LOG_CONFIG['monitor_log'])
        monitor_formatter = logging.Formatter('%(asctime)s UTC - %(levelname)s - %(message)s')
        monitor_handler.setFormatter(monitor_formatter)
        self.logger.addHandler(monitor_handler)
        
        # Update time logger (when new frames are found)
        self.update_time_logger = logging.getLogger('UpdateTime')
        self.update_time_logger.setLevel(logging.INFO)
        update_time_handler = logging.FileHandler(LOG_CONFIG['update_time_log'])
        update_time_formatter = logging.Formatter('%(message)s')
        update_time_handler.setFormatter(update_time_formatter)
        self.update_time_logger.addHandler(update_time_handler)
        
        # Update interval logger (time between frames)
        self.interval_logger = logging.getLogger('UpdateInterval')
        self.interval_logger.setLevel(logging.INFO)
        interval_handler = logging.FileHandler(LOG_CONFIG['update_interval_log'])
        interval_formatter = logging.Formatter('%(message)s')
        interval_handler.setFormatter(interval_formatter)
        self.interval_logger.addHandler(interval_handler)
        
        # Console handler for immediate feedback
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
    
    def _setup_session(self):
        """Setup HTTP session with appropriate headers"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': MONITOR_CONFIG['user_agent'],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        return session
    
    def _load_tracking_data(self):
        """Load existing tracking data from file"""
        tracking_file = LOG_CONFIG['tracking_data']
        if os.path.exists(tracking_file):
            try:
                with open(tracking_file, 'r') as f:
                    data = json.load(f)
                    self.logger.info(f"Loaded tracking data with {len(data.get('timestamps', []))} entries")
                    return data
            except Exception as e:
                self.logger.error(f"Failed to load tracking data: {e}")
        
        return {
            'timestamps': [],
            'intervals': [],
            'start_time': datetime.now(timezone.utc).isoformat(),
            'last_update': None
        }
    
    def _save_tracking_data(self):
        """Save tracking data to file"""
        try:
            with open(LOG_CONFIG['tracking_data'], 'w') as f:
                json.dump(self.tracking_data, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"Failed to save tracking data: {e}")
    
    def generate_timestamp(self, dt=None):
        """
        Generate NOAA timestamp format: YYYYDDDHHSS
        SS is minutes rounded down to nearest 10
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        
        # Round down to nearest 10 minutes
        minutes = (dt.minute // 10) * 10
        dt = dt.replace(minute=minutes, second=0, microsecond=0)
        
        year = dt.strftime('%Y')
        day_of_year = dt.strftime('%j')
        hour = dt.strftime('%H')
        minute_code = str(minutes).zfill(2)
        
        return f"{year}{day_of_year}{hour}{minute_code}"
    
    def parse_timestamp(self, timestamp_str):
        """Parse NOAA timestamp back to datetime object"""
        try:
            year = int(timestamp_str[:4])
            day_of_year = int(timestamp_str[4:7])
            hour = int(timestamp_str[7:9])
            minute = int(timestamp_str[9:11])
            
            dt = datetime(year, 1, 1, hour, minute, tzinfo=timezone.utc)
            dt += timedelta(days=day_of_year - 1)
            return dt
        except Exception as e:
            self.logger.error(f"Failed to parse timestamp {timestamp_str}: {e}")
            return None
    
    def generate_image_url(self, timestamp):
        """Generate the full URL for a NOAA image"""
        filename = NOAA_CONFIG['url_pattern'].format(timestamp=timestamp)
        return NOAA_CONFIG['base_url'] + filename
    
    def check_image_exists(self, timestamp):
        """Check if an image exists at the given timestamp"""
        url = self.generate_image_url(timestamp)
        
        try:
            response = self.session.head(url, timeout=MONITOR_CONFIG['timeout_seconds'])
            return response.status_code == 200
        except requests.RequestException as e:
            self.logger.debug(f"Request failed for {timestamp}: {e}")
            return False
    
    def find_latest_available_image(self):
        """Find the most recent available image by checking backwards from current time"""
        current_time = datetime.now(timezone.utc)
        
        # Check current time and go backwards up to 2 hours
        for minutes_back in range(0, 120, 10):  # Check every 10 minutes back for 2 hours
            check_time = current_time - timedelta(minutes=minutes_back)
            timestamp = self.generate_timestamp(check_time)
            
            if self.check_image_exists(timestamp):
                return timestamp
        
        return None
    
    def record_new_frame(self, timestamp):
        """Record discovery of a new frame"""
        current_utc = datetime.now(timezone.utc)
        image_time = self.parse_timestamp(timestamp)
        
        if not image_time:
            return
        
        # Log the update time
        update_msg = f"{timestamp} - published at {current_utc.strftime('%H:%M:%S')} UTC"
        self.update_time_logger.info(update_msg)
        self.logger.info(f"NEW FRAME FOUND: {update_msg}")
        
        # Calculate interval if we have a previous timestamp
        if self.last_known_timestamp:
            last_image_time = self.parse_timestamp(self.last_known_timestamp)
            if last_image_time:
                interval = image_time - last_image_time
                interval_minutes = interval.total_seconds() / 60
                
                # Log the interval
                interval_msg = f"{timestamp} - {interval_minutes:.0f} minutes since last frame published"
                self.interval_logger.info(interval_msg)
                self.logger.info(f"UPDATE INTERVAL: {interval_msg}")
                
                # Store in tracking data
                self.tracking_data['intervals'].append({
                    'timestamp': timestamp,
                    'previous_timestamp': self.last_known_timestamp,
                    'interval_minutes': interval_minutes,
                    'discovered_at': current_utc.isoformat()
                })
        
        # Update tracking data
        self.tracking_data['timestamps'].append({
            'timestamp': timestamp,
            'image_time': image_time.isoformat(),
            'discovered_at': current_utc.isoformat()
        })
        self.tracking_data['last_update'] = current_utc.isoformat()
        
        # Update last known timestamp
        self.last_known_timestamp = timestamp
        
        # Save tracking data
        self._save_tracking_data()
        
        # Clean up old data
        self._cleanup_old_data()
    
    def _cleanup_old_data(self):
        """Remove tracking data older than max_history_hours"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=MONITOR_CONFIG['max_history_hours'])
        
        # Clean timestamps
        self.tracking_data['timestamps'] = [
            entry for entry in self.tracking_data['timestamps']
            if datetime.fromisoformat(entry['discovered_at'].replace('Z', '+00:00')) > cutoff_time
        ]
        
        # Clean intervals
        self.tracking_data['intervals'] = [
            entry for entry in self.tracking_data['intervals']
            if datetime.fromisoformat(entry['discovered_at'].replace('Z', '+00:00')) > cutoff_time
        ]
    
    def get_statistics(self):
        """Get current monitoring statistics"""
        if not self.tracking_data['intervals']:
            return None
        
        intervals = [entry['interval_minutes'] for entry in self.tracking_data['intervals']]
        
        return {
            'total_updates_found': len(self.tracking_data['timestamps']),
            'total_intervals_recorded': len(intervals),
            'average_interval_minutes': sum(intervals) / len(intervals),
            'min_interval_minutes': min(intervals),
            'max_interval_minutes': max(intervals),
            'expected_interval_minutes': NOAA_CONFIG['expected_interval_minutes'],
            'monitoring_since': self.tracking_data['start_time']
        }
    
    def run_monitor(self):
        """Main monitoring loop"""
        self.running = True
        self.logger.info("Starting NOAA satellite update monitoring...")
        
        # Initialize with current latest image
        initial_timestamp = self.find_latest_available_image()
        if initial_timestamp:
            self.last_known_timestamp = initial_timestamp
            self.logger.info(f"Starting monitoring from timestamp: {initial_timestamp}")
        else:
            self.logger.warning("Could not find any available images to start monitoring")
        
        check_count = 0
        
        try:
            while self.running:
                check_count += 1
                current_utc = datetime.now(timezone.utc)
                
                # Find latest available image
                latest_timestamp = self.find_latest_available_image()
                
                if latest_timestamp:
                    # Check if this is a new frame
                    if latest_timestamp != self.last_known_timestamp:
                        self.record_new_frame(latest_timestamp)
                    else:
                        if check_count % 10 == 0:  # Log every 10 checks (10 minutes)
                            self.logger.debug(f"No new frames. Latest: {latest_timestamp}")
                else:
                    self.logger.warning("No images found in recent timeframe")
                
                # Print statistics every hour
                if check_count % 60 == 0:  # Every 60 minutes
                    stats = self.get_statistics()
                    if stats:
                        self.logger.info(f"STATISTICS: Avg interval: {stats['average_interval_minutes']:.1f}min, "
                                       f"Range: {stats['min_interval_minutes']:.0f}-{stats['max_interval_minutes']:.0f}min, "
                                       f"Total updates: {stats['total_updates_found']}")
                
                # Wait for next check
                time.sleep(MONITOR_CONFIG['check_interval_seconds'])
                
        except KeyboardInterrupt:
            self.logger.info("Monitor stopped by user")
        except Exception as e:
            self.logger.error(f"Monitor error: {e}")
        finally:
            self.stop_monitor()
    
    def stop_monitor(self):
        """Stop the monitoring process"""
        self.running = False
        self._save_tracking_data()
        
        # Print final statistics
        stats = self.get_statistics()
        if stats:
            self.logger.info("FINAL STATISTICS:")
            self.logger.info(f"  Total updates found: {stats['total_updates_found']}")
            self.logger.info(f"  Average interval: {stats['average_interval_minutes']:.1f} minutes")
            self.logger.info(f"  Min interval: {stats['min_interval_minutes']:.0f} minutes")
            self.logger.info(f"  Max interval: {stats['max_interval_minutes']:.0f} minutes")
            self.logger.info(f"  Expected interval: {stats['expected_interval_minutes']} minutes")
            self.logger.info(f"  Monitoring duration: {stats['monitoring_since']}")
        
        self.logger.info("NOAA Satellite Update Monitor stopped")

def main():
    """Main entry point"""
    print("NOAA Satellite Update Monitor")
    print("=============================")
    print("This tool monitors GOES-19 satellite imagery update intervals")
    print("Press Ctrl+C to stop monitoring and view final statistics")
    print()
    
    monitor = NOAASatelliteMonitor()
    
    try:
        monitor.run_monitor()
    except KeyboardInterrupt:
        print("\nStopping monitor...")
        monitor.stop_monitor()

if __name__ == "__main__":
    main() 