"""
Sun Calculator Module for Satellite Weather Looping System
Calculates sunrise/sunset times and determines day/night status for Trinidad & Tobago
Designed for 24/7 operation with efficient caching
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime, timezone, timedelta, date
from typing import Dict, Tuple, Optional
import pytz
from astral import LocationInfo
from astral.sun import sun, daylight, night, twilight, golden_hour, blue_hour
from astral.moon import phase

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import TRINIDAD_LOCATION, LOGS_DIR

class SunCalculator:
    """Calculates sun position and day/night status for satellite weather display"""
    
    def __init__(self, logger=None):
        """Initialize the sun calculator for 24/7 operation"""
        self.logger = logger or self._setup_logger()
        
        # Set up location
        self.location = LocationInfo(
            name=TRINIDAD_LOCATION['name'],
            region="Caribbean",
            timezone=TRINIDAD_LOCATION['timezone'],
            latitude=TRINIDAD_LOCATION['latitude'],
            longitude=TRINIDAD_LOCATION['longitude']
        )
        
        # Set up timezone
        self.local_tz = pytz.timezone(TRINIDAD_LOCATION['timezone'])
        
        # Cache for sun calculations (refreshed daily)
        self.sun_cache = {}
        self.cache_lock = threading.RLock()
        self.cache_date = None
        
        # Additional astronomical data cache
        self.astro_cache = {}
        
        # Update thread for 24/7 operation
        self.stop_event = threading.Event()
        self.update_thread = threading.Thread(
            target=self._update_worker,
            daemon=True
        )
        self.update_thread.start()
        
        # Initial calculation
        self._update_sun_data()
        
        self.logger.info(f"Sun Calculator initialized for {self.location.name}")
        self.logger.info(f"Location: {self.location.latitude}°N, {self.location.longitude}°W")
    
    def _setup_logger(self):
        """Set up logging for the sun calculator"""
        logger = logging.getLogger('SunCalculator')
        
        # Only set up handlers if they don't already exist
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # File handler with rotation
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                os.path.join(LOGS_DIR, 'sun_calculator.log'),
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
    
    def _update_worker(self):
        """Worker thread to update sun data for 24/7 operation"""
        while not self.stop_event.is_set():
            try:
                # Check if we need to update (new day)
                current_date = date.today()
                if self.cache_date != current_date:
                    self._update_sun_data()
                
                # Sleep for 5 minutes
                time.sleep(300)
                
            except Exception as e:
                self.logger.error(f"Error in update worker: {e}")
                time.sleep(60)
    
    def _update_sun_data(self):
        """Update sun data cache for current and next day"""
        try:
            with self.cache_lock:
                current_date = date.today()
                
                # Calculate for today and tomorrow
                for day_offset in [0, 1]:
                    calc_date = current_date + timedelta(days=day_offset)
                    
                    # Get sun times
                    s = sun(self.location.observer, date=calc_date)
                    
                    # Convert all times to local timezone
                    sun_data = {}
                    for key, value in s.items():
                        if isinstance(value, datetime):
                            sun_data[key] = value.astimezone(self.local_tz)
                    
                    # Store in cache
                    self.sun_cache[calc_date] = sun_data
                    
                    # Calculate additional astronomical data
                    try:
                        # Daylight period
                        daylight_period = daylight(self.location.observer, calc_date)
                        
                        # Twilight periods
                        dawn_dusk = twilight(self.location.observer, calc_date)
                        
                        # Golden hour
                        golden = golden_hour(self.location.observer, calc_date)
                        
                        # Blue hour
                        blue = blue_hour(self.location.observer, calc_date)
                        
                        # Moon phase
                        moon_phase = phase(calc_date)
                        
                        astro_data = {
                            'moon_phase': moon_phase
                        }
                        
                        # Safely handle daylight period (should be tuple)
                        if isinstance(daylight_period, (list, tuple)) and len(daylight_period) >= 2:
                            astro_data['daylight_start'] = daylight_period[0].astimezone(self.local_tz)
                            astro_data['daylight_end'] = daylight_period[1].astimezone(self.local_tz)
                        
                        # Safely handle twilight periods (should be nested tuples)
                        if isinstance(dawn_dusk, (list, tuple)) and len(dawn_dusk) > 0:
                            if isinstance(dawn_dusk[0], (list, tuple)) and len(dawn_dusk[0]) >= 2:
                                astro_data['civil_dawn'] = dawn_dusk[0][0].astimezone(self.local_tz)
                                astro_data['civil_dusk'] = dawn_dusk[0][1].astimezone(self.local_tz)
                        
                        # Safely handle golden hour (should be nested tuples)
                        if isinstance(golden, (list, tuple)) and len(golden) >= 2:
                            if isinstance(golden[0], (list, tuple)) and len(golden[0]) >= 2:
                                astro_data['golden_hour_morning'] = (
                                    golden[0][0].astimezone(self.local_tz), 
                                    golden[0][1].astimezone(self.local_tz)
                                )
                            if isinstance(golden[1], (list, tuple)) and len(golden[1]) >= 2:
                                astro_data['golden_hour_evening'] = (
                                    golden[1][0].astimezone(self.local_tz), 
                                    golden[1][1].astimezone(self.local_tz)
                                )
                        
                        # Safely handle blue hour (should be nested tuples)
                        if isinstance(blue, (list, tuple)) and len(blue) >= 2:
                            if isinstance(blue[0], (list, tuple)) and len(blue[0]) >= 2:
                                astro_data['blue_hour_morning'] = (
                                    blue[0][0].astimezone(self.local_tz), 
                                    blue[0][1].astimezone(self.local_tz)
                                )
                            if isinstance(blue[1], (list, tuple)) and len(blue[1]) >= 2:
                                astro_data['blue_hour_evening'] = (
                                    blue[1][0].astimezone(self.local_tz), 
                                    blue[1][1].astimezone(self.local_tz)
                                )
                        
                        self.astro_cache[calc_date] = astro_data
                        
                    except Exception as e:
                        self.logger.warning(f"Could not calculate additional astronomical data: {e}")
                
                self.cache_date = current_date
                
                # Log today's times
                today_sun = self.sun_cache[current_date]
                self.logger.info(f"Sun times updated for {current_date}")
                self.logger.info(f"Sunrise: {today_sun['sunrise'].strftime('%H:%M')} (GMT-4)")
                self.logger.info(f"Sunset: {today_sun['sunset'].strftime('%H:%M')} (GMT-4)")
                
        except Exception as e:
            self.logger.error(f"Error updating sun data: {e}")
    
    def is_daytime(self, check_time: Optional[datetime] = None) -> bool:
        """
        Check if it's currently daytime
        
        Args:
            check_time: Time to check (default: current time)
            
        Returns:
            True if daytime, False if nighttime
        """
        if check_time is None:
            check_time = datetime.now(self.local_tz)
        else:
            # Ensure timezone aware
            if check_time.tzinfo is None:
                check_time = self.local_tz.localize(check_time)
            else:
                check_time = check_time.astimezone(self.local_tz)
        
        # Get sun data for the date
        check_date = check_time.date()
        
        with self.cache_lock:
            if check_date not in self.sun_cache:
                self._update_sun_data()
            
            if check_date in self.sun_cache:
                sun_data = self.sun_cache[check_date]
                sunrise = sun_data['sunrise']
                sunset = sun_data['sunset']
                
                return sunrise <= check_time <= sunset
        
        # Fallback if cache fails
        self.logger.warning("Using fallback day/night calculation")
        hour = check_time.hour
        return 6 <= hour < 18  # Approximate: 6 AM to 6 PM
    
    def get_sun_times(self, for_date: Optional[date] = None) -> Dict:
        """
        Get sunrise and sunset times for a specific date
        
        Args:
            for_date: Date to get times for (default: today)
            
        Returns:
            Dictionary with sunrise and sunset times
        """
        if for_date is None:
            for_date = date.today()
        
        with self.cache_lock:
            if for_date not in self.sun_cache:
                self._update_sun_data()
            
            if for_date in self.sun_cache:
                sun_data = self.sun_cache[for_date]
                return {
                    'sunrise': sun_data['sunrise'],
                    'sunset': sun_data['sunset'],
                    'noon': sun_data['noon'],
                    'dawn': sun_data.get('dawn'),
                    'dusk': sun_data.get('dusk')
                }
        
        return None
    
    def get_daylight_duration(self, for_date: Optional[date] = None) -> timedelta:
        """Get the duration of daylight for a specific date"""
        sun_times = self.get_sun_times(for_date)
        
        if sun_times and sun_times['sunrise'] and sun_times['sunset']:
            return sun_times['sunset'] - sun_times['sunrise']
        
        return timedelta(hours=12)  # Fallback
    
    def get_time_until_change(self) -> Dict:
        """
        Get time until next sunrise or sunset
        
        Returns:
            Dictionary with next event type and time remaining
        """
        now = datetime.now(self.local_tz)
        today = now.date()
        tomorrow = today + timedelta(days=1)
        
        with self.cache_lock:
            # Ensure we have data for both days
            for check_date in [today, tomorrow]:
                if check_date not in self.sun_cache:
                    self._update_sun_data()
            
            is_day = self.is_daytime(now)
            
            if is_day:
                # Daytime - next event is sunset
                sunset = self.sun_cache[today]['sunset']
                time_until = sunset - now
                next_event = 'sunset'
                next_time = sunset
            else:
                # Nighttime - next event is sunrise
                # Check if we're before or after midnight
                if now.time() < datetime.min.time().replace(hour=12):
                    # After midnight, sunrise is today
                    sunrise = self.sun_cache[today]['sunrise']
                else:
                    # Before midnight, sunrise is tomorrow
                    sunrise = self.sun_cache[tomorrow]['sunrise']
                
                time_until = sunrise - now
                next_event = 'sunrise'
                next_time = sunrise
            
            return {
                'current_period': 'day' if is_day else 'night',
                'next_event': next_event,
                'next_time': next_time,
                'time_until': time_until,
                'hours_until': time_until.total_seconds() / 3600,
                'minutes_until': time_until.total_seconds() / 60
            }
    
    def get_grid_mode(self) -> str:
        """
        Get the current grid display mode based on sun position
        
        Returns:
            'day' or 'night'
        """
        return 'day' if self.is_daytime() else 'night'
    
    def get_astronomical_data(self, for_date: Optional[date] = None) -> Dict:
        """
        Get additional astronomical data
        
        Args:
            for_date: Date to get data for (default: today)
            
        Returns:
            Dictionary with astronomical information
        """
        if for_date is None:
            for_date = date.today()
        
        with self.cache_lock:
            if for_date not in self.astro_cache:
                self._update_sun_data()
            
            if for_date in self.astro_cache:
                return self.astro_cache[for_date].copy()
        
        return {}
    
    def get_sun_position(self, check_time: Optional[datetime] = None) -> Dict:
        """
        Get current sun position (elevation and azimuth)
        
        Args:
            check_time: Time to check (default: current time)
            
        Returns:
            Dictionary with elevation and azimuth in degrees
        """
        if check_time is None:
            check_time = datetime.now(self.local_tz)
        
        try:
            from astral.sun import elevation, azimuth
            
            elev = elevation(self.location.observer, check_time)
            azim = azimuth(self.location.observer, check_time)
            
            return {
                'elevation': round(elev, 2),
                'azimuth': round(azim, 2),
                'is_visible': elev > 0
            }
        except Exception as e:
            self.logger.error(f"Error calculating sun position: {e}")
            return {'elevation': 0, 'azimuth': 0, 'is_visible': False}
    
    def get_status(self) -> Dict:
        """Get comprehensive sun calculator status"""
        now = datetime.now(self.local_tz)
        today = date.today()
        
        status = {
            'location': {
                'name': self.location.name,
                'latitude': self.location.latitude,
                'longitude': self.location.longitude,
                'timezone': str(self.local_tz)
            },
            'current_time': now.isoformat(),
            'is_daytime': self.is_daytime(),
            'grid_mode': self.get_grid_mode()
        }
        
        # Add sun times
        sun_times = self.get_sun_times()
        if sun_times:
            status['sun_times'] = {
                'sunrise': sun_times['sunrise'].isoformat() if sun_times['sunrise'] else None,
                'sunset': sun_times['sunset'].isoformat() if sun_times['sunset'] else None,
                'solar_noon': sun_times['noon'].isoformat() if sun_times['noon'] else None
            }
        
        # Add time until change
        change_info = self.get_time_until_change()
        status['next_change'] = {
            'event': change_info['next_event'],
            'time': change_info['next_time'].isoformat(),
            'minutes_until': round(change_info['minutes_until'], 1)
        }
        
        # Add sun position
        status['sun_position'] = self.get_sun_position()
        
        # Add daylight duration
        daylight_duration = self.get_daylight_duration()
        status['daylight_hours'] = round(daylight_duration.total_seconds() / 3600, 2)
        
        # Add moon phase if available
        astro_data = self.get_astronomical_data()
        if astro_data and 'moon_phase' in astro_data:
            status['moon_phase'] = round(astro_data['moon_phase'], 1)
        
        return status
    
    def format_time_for_display(self, dt: datetime) -> str:
        """Format datetime for display in local time"""
        local_dt = dt.astimezone(self.local_tz)
        return local_dt.strftime("%I:%M %p")  # 12-hour format with AM/PM
    
    def stop(self):
        """Stop the sun calculator gracefully"""
        self.logger.info("Stopping sun calculator")
        self.stop_event.set()
        
        if self.update_thread.is_alive():
            self.update_thread.join(timeout=5)
        
        self.logger.info("Sun calculator stopped")


def main():
    """Main function for testing the sun calculator"""
    calculator = SunCalculator()
    
    try:
        # Print initial status
        status = calculator.get_status()
        print(f"\nSun Calculator Status:")
        print(f"Location: {status['location']['name']}")
        print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Is daytime: {status['is_daytime']}")
        print(f"Grid mode: {status['grid_mode']}")
        
        if 'sun_times' in status:
            sunrise = datetime.fromisoformat(status['sun_times']['sunrise'])
            sunset = datetime.fromisoformat(status['sun_times']['sunset'])
            print(f"Sunrise: {calculator.format_time_for_display(sunrise)}")
            print(f"Sunset: {calculator.format_time_for_display(sunset)}")
        
        print(f"\nNext change: {status['next_change']['event']} in {status['next_change']['minutes_until']:.0f} minutes")
        print(f"Sun elevation: {status['sun_position']['elevation']}°")
        print(f"Daylight hours: {status['daylight_hours']}")
        
        # Monitor for changes
        last_mode = status['grid_mode']
        while True:
            time.sleep(60)  # Check every minute
            
            current_mode = calculator.get_grid_mode()
            if current_mode != last_mode:
                print(f"\nGrid mode changed from {last_mode} to {current_mode}")
                last_mode = current_mode
            
            # Print time until next change
            change_info = calculator.get_time_until_change()
            print(f"\rNext {change_info['next_event']} in {change_info['minutes_until']:.1f} minutes", end='', flush=True)
            
    except KeyboardInterrupt:
        print("\n\nShutting down sun calculator...")
        calculator.stop()


if __name__ == "__main__":
    main()
