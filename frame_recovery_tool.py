#!/usr/bin/env python3
"""
Frame Recovery Tool for Satellite Weather Imager
This tool helps recover frames that were previously marked as missing but might now be available.
"""

import json
import logging
import sys
import os
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import FRAME_TRACKING_CONFIG, parse_timestamp, get_local_time
from image_downloader import ImageDownloader

class FrameRecoveryTool:
    """Tool to recover frames that were marked as missing"""
    
    def __init__(self):
        self.setup_logging()
        self.downloader = ImageDownloader(self.logger)
        
    def setup_logging(self):
        """Set up logging for the recovery tool"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger('FrameRecovery')
    
    def find_recoverable_frames(self, hours_back=24):
        """Find frames marked as missing that might be recoverable"""
        if not self.downloader.frame_tracker:
            self.logger.error("Frame tracking not available")
            return []
        
        recoverable_frames = []
        current_time = datetime.now(timezone.utc)
        cutoff_time = current_time - timedelta(hours=hours_back)
        
        tracking_data = self.downloader.frame_tracker.tracking_data
        
        for timestamp, frame_data in tracking_data['frames'].items():
            try:
                frame_dt = parse_timestamp(timestamp)
                
                # Only check frames within our time window
                if frame_dt < cutoff_time:
                    continue
                
                for band_key, band_data in frame_data.items():
                    # Look for frames marked as missing
                    if band_data.get('marked_missing', False) or band_data.get('status') == 'missing':
                        frame_age_hours = (current_time - frame_dt).total_seconds() / 3600
                        
                        # Check if this frame might now be available
                        # Images usually become available within 3-6 hours
                        if frame_age_hours >= 3:  # Give enough time for image to be published
                            recoverable_frames.append({
                                'timestamp': timestamp,
                                'band_key': band_key,
                                'frame_dt': frame_dt,
                                'frame_age_hours': frame_age_hours,
                                'retry_count': band_data.get('retry_count', 0),
                                'last_attempt': band_data.get('last_attempt'),
                                'last_error': band_data.get('attempts', [{}])[-1].get('error', 'Unknown')
                            })
                        
            except Exception as e:
                self.logger.warning(f"Error processing timestamp {timestamp}: {e}")
                continue
        
        return recoverable_frames
    
    def attempt_recovery(self, recoverable_frames, max_workers=2):
        """Attempt to recover the missing frames"""
        if not recoverable_frames:
            self.logger.info("No recoverable frames found")
            return
        
        self.logger.info(f"Attempting to recover {len(recoverable_frames)} missing frames")
        
        # Group by timestamp for efficient processing
        timestamp_groups = {}
        for frame in recoverable_frames:
            timestamp = frame['timestamp']
            if timestamp not in timestamp_groups:
                timestamp_groups[timestamp] = []
            timestamp_groups[timestamp].append(frame)
        
        recovered_count = 0
        failed_count = 0
        
        for timestamp, frames in timestamp_groups.items():
            try:
                local_time = get_local_time(frames[0]['frame_dt'])
                band_keys = [f['band_key'] for f in frames]
                
                self.logger.info(f"Attempting recovery for {local_time.strftime('%Y-%m-%d %H:%M')} (GMT-4) - {len(band_keys)} bands")
                
                # Attempt recovery with limited concurrency
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = []
                    for frame in frames:
                        future = executor.submit(self.recover_single_frame, frame)
                        futures.append((future, frame))
                    
                    # Wait for completion and count results
                    for future, frame in futures:
                        try:
                            success = future.result()
                            if success:
                                recovered_count += 1
                                self.logger.info(f"Successfully recovered {frame['band_key']} for {timestamp}")
                            else:
                                failed_count += 1
                        except Exception as e:
                            failed_count += 1
                            self.logger.error(f"Error recovering {frame['band_key']} for {timestamp}: {e}")
                
                # Small delay between timestamp groups
                import time
                time.sleep(0.5)
                
            except Exception as e:
                self.logger.error(f"Error processing timestamp group {timestamp}: {e}")
                failed_count += len(frames)
        
        self.logger.info(f"Recovery complete: {recovered_count} recovered, {failed_count} failed")
        return recovered_count, failed_count
    
    def recover_single_frame(self, frame):
        """Attempt to recover a single frame"""
        timestamp = frame['timestamp']
        band_key = frame['band_key']
        
        try:
            # Reset the frame status to allow retry
            if self.downloader.frame_tracker:
                # Remove the missing flag
                tracking_data = self.downloader.frame_tracker.tracking_data
                if timestamp in tracking_data['frames']:
                    if band_key in tracking_data['frames'][timestamp]:
                        tracking_data['frames'][timestamp][band_key]['marked_missing'] = False
                        tracking_data['frames'][timestamp][band_key]['status'] = 'failed'  # Reset to failed so it can be retried
            
            # Attempt download
            success = self.downloader.download_image(band_key, timestamp)
            
            if success:
                self.logger.debug(f"Successfully recovered {band_key} for {timestamp}")
                return True
            else:
                self.logger.debug(f"Recovery failed for {band_key} for {timestamp}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error in recover_single_frame for {band_key} {timestamp}: {e}")
            return False
    
    def reset_missing_flags(self, hours_back=24):
        """Reset missing flags for frames within the time window to allow retry"""
        if not self.downloader.frame_tracker:
            self.logger.error("Frame tracking not available")
            return 0
        
        reset_count = 0
        current_time = datetime.now(timezone.utc)
        cutoff_time = current_time - timedelta(hours=hours_back)
        
        tracking_data = self.downloader.frame_tracker.tracking_data
        
        for timestamp, frame_data in tracking_data['frames'].items():
            try:
                frame_dt = parse_timestamp(timestamp)
                
                # Only process frames within our time window
                if frame_dt < cutoff_time:
                    continue
                
                for band_key, band_data in frame_data.items():
                    if band_data.get('marked_missing', False):
                        band_data['marked_missing'] = False
                        band_data['status'] = 'failed'  # Reset to failed so it can be retried
                        reset_count += 1
                        
            except Exception as e:
                self.logger.warning(f"Error processing timestamp {timestamp}: {e}")
                continue
        
        if reset_count > 0:
            self.downloader.frame_tracker._save_tracking_data()
            self.logger.info(f"Reset missing flags for {reset_count} frames")
        
        return reset_count

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Recovery tool for missing satellite image frames')
    parser.add_argument('--hours', type=int, default=24, help='Hours back to check for recoverable frames (default: 24)')
    parser.add_argument('--reset-only', action='store_true', help='Only reset missing flags, don\'t attempt recovery')
    parser.add_argument('--workers', type=int, default=2, help='Number of concurrent download workers (default: 2)')
    
    args = parser.parse_args()
    
    tool = FrameRecoveryTool()
    
    if args.reset_only:
        reset_count = tool.reset_missing_flags(args.hours)
        print(f"Reset missing flags for {reset_count} frames")
    else:
        # Find recoverable frames
        recoverable_frames = tool.find_recoverable_frames(args.hours)
        
        if not recoverable_frames:
            print("No recoverable frames found")
            return
        
        print(f"Found {len(recoverable_frames)} potentially recoverable frames")
        
        # Show summary
        by_band = {}
        for frame in recoverable_frames:
            band = frame['band_key']
            if band not in by_band:
                by_band[band] = 0
            by_band[band] += 1
        
        print("Recoverable frames by band:")
        for band, count in sorted(by_band.items()):
            print(f"  {band}: {count}")
        
        # Ask for confirmation
        try:
            response = input(f"\nAttempt recovery of {len(recoverable_frames)} frames? [y/N]: ")
            if response.lower() not in ['y', 'yes']:
                print("Recovery cancelled")
                return
        except KeyboardInterrupt:
            print("\nRecovery cancelled")
            return
        
        # Attempt recovery
        recovered, failed = tool.attempt_recovery(recoverable_frames, args.workers)
        print(f"\nRecovery complete:")
        print(f"  Recovered: {recovered}")
        print(f"  Failed: {failed}")
        print(f"  Success rate: {recovered/(recovered+failed)*100:.1f}%" if (recovered+failed) > 0 else "N/A")

if __name__ == "__main__":
    main() 