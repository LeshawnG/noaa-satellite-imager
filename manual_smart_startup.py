#!/usr/bin/env python3
"""
Manual Smart Startup Download Script
Use this script to manually trigger smart startup downloads when needed
"""

import sys
import os
import logging
from datetime import datetime, timezone
import argparse

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from image_downloader import ImageDownloader
from image_processor import ImageProcessor
from config import get_local_time

def setup_logging(verbose=False):
    """Set up logging"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

def main():
    parser = argparse.ArgumentParser(
        description='Manual Smart Startup Download Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Download with default 2 hours
  %(prog)s --hours 6          # Download last 6 hours
  %(prog)s --analyze-only     # Just analyze, don't download
  %(prog)s --with-processing  # Download and trigger processing
  %(prog)s --verbose          # Show debug information
        """
    )
    
    parser.add_argument(
        '--hours', 
        type=int, 
        default=2,
        help='Number of hours to look back for missing frames (default: 2)'
    )
    
    parser.add_argument(
        '--analyze-only',
        action='store_true',
        help='Only analyze filesystem, do not download'
    )
    
    parser.add_argument(
        '--with-processing',
        action='store_true',
        help='Initialize processor and trigger processing after downloads'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose debug logging'
    )
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    print("🚀 MANUAL SMART STARTUP DOWNLOAD")
    print(f"Current time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Local time: {get_local_time(datetime.now(timezone.utc)).strftime('%Y-%m-%d %H:%M:%S')} GMT-4")
    print("=" * 60)
    
    try:
        # Initialize downloader
        downloader = ImageDownloader()
        
        # Initialize processor if requested
        processor = None
        if args.with_processing:
            print("🔧 Initializing image processor...")
            processor = ImageProcessor()
            downloader.set_processor(processor)
            print("✅ Processor initialized and linked to downloader")
        
        if args.analyze_only:
            print("🔍 ANALYSIS MODE - No downloads will be performed")
            
            # Just analyze the filesystem
            fs_status = downloader.get_filesystem_frame_status(args.hours)
            missing_frames = fs_status['missing_frames']
            
            print(f"\n📊 Filesystem Analysis Results:")
            print(f"   Existing frames: {fs_status['existing_frame_count']}")
            print(f"   Missing frames: {len(missing_frames)}")
            print(f"   Time range: {fs_status['time_range_hours']:.1f} hours")
            
            if fs_status['oldest_frame_time']:
                oldest_local = get_local_time(fs_status['oldest_frame_time'])
                newest_local = get_local_time(fs_status['newest_frame_time'])
                print(f"   Existing range: {oldest_local.strftime('%Y-%m-%d %H:%M')} to {newest_local.strftime('%Y-%m-%d %H:%M')} (GMT-4)")
            
            total_bands = sum(len(frame['missing_bands']) for frame in missing_frames)
            recent_frames = [f for f in missing_frames if f['frame_age_minutes'] < 60]
            older_frames = [f for f in missing_frames if f['frame_age_minutes'] >= 60]
            
            print(f"   Total missing band-frames: {total_bands}")
            print(f"   Recent frames (< 1h): {len(recent_frames)}")
            print(f"   Older frames (≥ 1h): {len(older_frames)}")
            
            if missing_frames:
                print(f"\n📋 Sample Missing Frames (first 10):")
                for i, frame in enumerate(missing_frames[:10]):
                    local_time = get_local_time(frame['datetime'])
                    age_str = f"{frame['frame_age_minutes']:.1f}m"
                    bands_str = ", ".join(frame['missing_bands'][:3])
                    if len(frame['missing_bands']) > 3:
                        bands_str += f" (+{len(frame['missing_bands'])-3} more)"
                    print(f"   {i+1:2d}. {local_time.strftime('%Y-%m-%d %H:%M')} (GMT-4) [{age_str}]: {bands_str}")
            
        else:
            print(f"📥 DOWNLOAD MODE - Looking for missing frames in past {args.hours} hours")
            
            # Run smart startup downloads
            print("\n🎯 Starting smart startup downloads...")
            downloader.smart_startup_downloads(default_hours_back=args.hours)
            print("✅ Smart startup downloads completed")
            
            if args.with_processing:
                print("\n🔄 Waiting for processing to complete...")
                # Give processing some time to catch up
                import time
                time.sleep(5)
                print("✅ Processing triggered - monitor logs for progress")
        
        print("\n" + "=" * 60)
        print("✅ OPERATION COMPLETED SUCCESSFULLY")
        
        if not args.analyze_only:
            print("\n💡 Tips:")
            print("   - Check the logs for detailed download progress")
            print("   - Use --analyze-only to preview what would be downloaded")
            print("   - Use --with-processing to trigger image processing")
            print("   - Monitor the web interface to see new images appear")
        
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 