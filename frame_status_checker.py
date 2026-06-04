#!/usr/bin/env python3
"""
Frame Status Checker Utility
Provides tools to check frame status, generate reports, and manage frame tracking
"""

import sys
import os
import argparse
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from image_downloader import ImageDownloader
from config import FRAME_TRACKING_CONFIG

def main():
    parser = argparse.ArgumentParser(description='Frame Status Checker and Management Tool')
    parser.add_argument('--report', '-r', action='store_true', 
                       help='Generate frame status report')
    parser.add_argument('--hours', '-t', type=int, default=2,
                       help='Number of hours to check (default: 2)')
    parser.add_argument('--stats', '-s', action='store_true',
                       help='Show frame statistics')
    parser.add_argument('--missing', '-m', action='store_true',
                       help='List missing frames')
    parser.add_argument('--retry', action='store_true',
                       help='Process retry queue manually')
    parser.add_argument('--catchup', action='store_true',
                       help='Run catch-up downloads')
    parser.add_argument('--cleanup', action='store_true',
                       help='Cleanup old tracking data')
    
    args = parser.parse_args()
    
    if not FRAME_TRACKING_CONFIG['enable_tracking']:
        print("Frame tracking is disabled in configuration.")
        print("Enable it by setting FRAME_TRACKING_CONFIG['enable_tracking'] = True")
        return
    
    # Initialize downloader
    downloader = ImageDownloader()
    
    if args.report:
        print(downloader.get_frame_status_report(args.hours))
        
    elif args.stats:
        stats = downloader.get_frame_statistics()
        if stats:
            print("Frame Download Statistics:")
            print(f"  Success Rate: {stats['success_rate']:.1f}%")
            print(f"  Total Attempts: {stats['total_attempts']}")
            print(f"  Successful Downloads: {stats['successful_downloads']}")
            print(f"  Failed Attempts: {stats['failed_attempts']}")
            print(f"  Retry Attempts: {stats['retry_attempts']}")
            print(f"  Recent Frames: {stats['recent_downloaded']}/{stats['recent_frames_total']}")
            print(f"  Pending Retries: {stats['pending_retries']}")
        else:
            print("No statistics available")
            
    elif args.missing:
        missing_frames = downloader.get_comprehensive_missing_frames(args.hours)
        if missing_frames:
            print(f"Missing frames in the past {args.hours} hours:")
            for frame in missing_frames:
                dt = frame['datetime']
                from config import get_local_time
                local_time = get_local_time(dt)
                age_str = f"{frame['frame_age_minutes']:.1f}m"
                bands_str = ", ".join(frame['missing_bands'])
                print(f"  {local_time.strftime('%Y-%m-%d %H:%M')} (GMT-4) [{age_str}]: {bands_str}")
        else:
            print(f"No missing frames found in the past {args.hours} hours")
            
    elif args.retry:
        print("Processing retry queue...")
        downloader.process_retry_queue()
        print("Retry processing complete")
        
    elif args.catchup:
        print(f"Running catch-up downloads for past {args.hours} hours...")
        downloader.enhanced_catch_up_downloads(args.hours)
        print("Catch-up complete")
        
    elif args.cleanup:
        if downloader.frame_tracker:
            cleaned_count = downloader.frame_tracker.cleanup_old_tracking_data()
            print(f"Cleaned up {cleaned_count} old tracking records")
        else:
            print("Frame tracker not available")
            
    else:
        # Default: show brief status
        stats = downloader.get_frame_statistics()
        missing_frames = downloader.get_comprehensive_missing_frames(2)
        
        print("Frame Status Summary:")
        if stats:
            print(f"  Success Rate: {stats['success_rate']:.1f}%")
            print(f"  Recent Frames: {stats['recent_downloaded']}/{stats['recent_frames_total']}")
        print(f"  Missing Frames (2h): {len(missing_frames)}")
        
        if missing_frames:
            print("\nRecent missing frames:")
            for frame in missing_frames[:5]:  # Show first 5
                dt = frame['datetime']
                from config import get_local_time
                local_time = get_local_time(dt)
                age_str = f"{frame['frame_age_minutes']:.1f}m"
                bands_str = ", ".join(frame['missing_bands'])
                print(f"    {local_time.strftime('%H:%M')} [{age_str}]: {bands_str}")
        
        print("\nUse --help for more options")

if __name__ == "__main__":
    main() 