"""
Main Flask Application for Satellite Weather Looping System
Integrates all modules and provides web interface for 24/7 operation
"""

import os
import sys
import logging
import threading
import signal
import queue
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, jsonify, send_file, request, abort, send_from_directory, Response
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import json

# Add modules directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import (
    FLASK_CONFIG, BANDS, TIME_PERIODS, GRID_CONFIG, 
    IMAGES_DIR, API_ENDPOINTS, LOGGING_CONFIG, FPS_CONFIG
)

# Import our modules
from image_downloader import ImageDownloader
from image_processor import ImageProcessor
from storage_manager import StorageManager
from sun_calculator import SunCalculator

# Create Flask app
app = Flask(__name__)
app.config.update(FLASK_CONFIG)

# Enable CORS for local network access
CORS(app)

# Fix for proxy headers if needed
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SatelliteWeatherApp')

# Cache-busting token for static assets. Changes on every app start so browsers
# always pick up the latest JS/CSS after a restart instead of serving stale
# cached files (static files are cached for SEND_FILE_MAX_AGE_DEFAULT seconds).
ASSET_VERSION = int(datetime.now(timezone.utc).timestamp())

# Global instances of our modules
downloader = None
processor = None
storage_manager = None
sun_calculator = None
modules_initialized = False

# Thread management
background_threads = []
shutdown_event = threading.Event()


class EventBroker:
    """Minimal in-process pub/sub for Server-Sent Events.

    Each connected browser gets its own bounded queue; publish() fans a message
    out to all current subscribers. Used to push 'new frame available' events
    so the frontend updates without fragile clock-based polling.
    """

    def __init__(self):
        self._subscribers = []
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=10)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, data):
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass  # slow client; drop this event for it


event_broker = EventBroker()


def _new_image_watcher():
    """Server-side watcher: detect when a newer timestamp finishes processing
    and push it to connected clients via SSE. One check runs regardless of how
    many browsers are connected."""
    last_seen = None
    # Let modules settle before the first check.
    shutdown_event.wait(10)
    while not shutdown_event.is_set():
        try:
            if storage_manager:
                timestamps = storage_manager.get_available_timestamps(hours=1)
                latest = timestamps[-1] if timestamps else None
                if latest and latest != last_seen:
                    last_seen = latest
                    event_broker.publish(latest)
                    logger.info(f"New frame detected, pushing to clients: {latest}")
        except Exception as e:
            logger.error(f"New-image watcher error: {e}")
        # Poll cadence (server-side only): images publish every 10 min.
        shutdown_event.wait(20)

def initialize_modules():
    """Initialize all required modules"""
    global downloader, processor, storage_manager, sun_calculator, modules_initialized
    
    # Prevent multiple initialization
    if modules_initialized:
        logger.info("Modules already initialized, skipping...")
        return
    
    logger.info("Initializing modules...")
    
    # Initialize storage manager first
    storage_manager = StorageManager()
    logger.info("Storage Manager initialized")
    
    # Initialize sun calculator
    sun_calculator = SunCalculator()
    logger.info("Sun Calculator initialized")
    
    # Initialize image processor
    processor = ImageProcessor()
    logger.info("Image Processor initialized")
    
    # Initialize and start image downloader in background
    # Pass processor instance to downloader for processing triggers
    downloader = ImageDownloader()
    downloader.set_processor(processor)  # Add processor reference
    downloader_thread = threading.Thread(
        target=downloader.run_continuous,
        daemon=True
    )
    downloader_thread.start()
    background_threads.append(downloader_thread)
    logger.info("Image Downloader started")

    # Start the new-image watcher that powers SSE push to the frontend
    watcher_thread = threading.Thread(target=_new_image_watcher, daemon=True)
    watcher_thread.start()
    background_threads.append(watcher_thread)
    logger.info("New-image watcher started")

    modules_initialized = True
    logger.info("All modules initialized successfully")

# Initialize modules when app starts
initialize_modules()

# Routes
@app.route('/')
def index():
    """Serve the main web interface"""
    return render_template('index.html')

@app.route('/api/images/<band>/<zoom>/<int:hours>')
def get_images(band, zoom, hours):
    """
    Get list of images for a specific band, zoom level, and time period
    
    Args:
        band: Band key (e.g., 'GeoColor', 'Band_2')
        zoom: Zoom level ('Zoom1', 'Zoom2', 'Zoom3')
        hours: Number of hours of history to return
    
    Returns:
        JSON array of image metadata
    """
    try:
        # Validate parameters
        if band not in BANDS:
            return jsonify({'error': 'Invalid band'}), 400
        
        if zoom not in ['Zoom1', 'Zoom2', 'Zoom3']:
            return jsonify({'error': 'Invalid zoom level'}), 400
        
        if hours < 1 or hours > 48:
            return jsonify({'error': 'Hours must be between 1 and 48'}), 400
        
        # Get images from storage manager
        images = storage_manager.get_image_list(band, zoom, hours)
        
        return jsonify({
            'band': band,
            'zoom': zoom,
            'hours': hours,
            'count': len(images),
            'images': images
        })
        
    except Exception as e:
        logger.error(f"Error getting images: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/grid-images/<int:hours>')
@app.route('/api/grid-images/<int:hours>/<zoom>')
def get_grid_images(hours, zoom='Zoom1'):
    """
    Get images for all bands suitable for grid display
    
    Args:
        hours: Number of hours of history to return
        zoom: Zoom level ('Zoom1', 'Zoom2', 'Zoom3') - defaults to 'Zoom1'
    
    Returns:
        JSON object with images for each band
    """
    try:
        if hours < 1 or hours > 48:
            return jsonify({'error': 'Hours must be between 1 and 48'}), 400
        
        if zoom not in ['Zoom1', 'Zoom2', 'Zoom3']:
            return jsonify({'error': 'Invalid zoom level'}), 400
        
        # Get current sun status to determine grid mode
        sun_status = sun_calculator.get_status()
        grid_mode = sun_status['grid_mode']
        
        # Get time-aligned images for all bands with the specified zoom level
        grid_data = storage_manager.get_grid_images(hours, zoom)

        # Add grid configuration
        response = {
            'mode': grid_mode,
            'hours': hours,
            'zoom': zoom,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'grid_config': GRID_CONFIG[f'{grid_mode}_mode'],
            'timestamps': grid_data['timestamps'],
            'timestamps_local': grid_data['timestamps_local'],
            'bands': grid_data['bands']
        }

        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error getting grid images: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/sun-status')
def get_sun_status():
    """Get current sun status and day/night information"""
    try:
        status = sun_calculator.get_status()
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"Error getting sun status: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/system-status')
def get_system_status():
    """Get comprehensive system status"""
    try:
        # Get storage status
        storage_status = storage_manager.get_storage_status()
        
        # Get processor status
        processor_status = processor.get_status()
        
        # Get sun status
        sun_status = sun_calculator.get_status()
        
        # Get missing images
        missing_images = storage_manager.get_missing_images(hours=2)
        missing_count = sum(len(timestamps) for timestamps in missing_images.values())
        
        # Combine all status information
        status = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'storage': storage_status,
            'processor': processor_status,
            'sun': {
                'is_daytime': sun_status['is_daytime'],
                'grid_mode': sun_status['grid_mode'],
                'next_change': sun_status['next_change']
            },
            'missing_images': {
                'count': missing_count,
                'by_band': {k: len(v) for k, v in missing_images.items()}
            },
            'uptime_hours': get_uptime_hours()
        }
        
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/config')
def get_config():
    """Get client configuration"""
    try:
        config = {
            'bands': {k: v['label'] for k, v in BANDS.items()},
            'time_periods': TIME_PERIODS,
            'zoom_levels': ['Zoom1', 'Zoom2', 'Zoom3'],
            'grid_config': GRID_CONFIG,
            'fps_config': FPS_CONFIG,
            'update_interval': 600  # 10 minutes in seconds
        }
        
        return jsonify(config)
        
    except Exception as e:
        logger.error(f"Error getting config: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/cleanup', methods=['POST'])
def trigger_cleanup():
    """Manually trigger cleanup of old images"""
    try:
        # Check for admin key (add to config for production)
        data = request.json or {}
        admin_key = data.get('admin_key')
        cleanup_type = data.get('type', 'standard')  # standard, aggressive, or retention
        
        if admin_key != 'your-admin-key':  # Replace with secure key
            return jsonify({'error': 'Unauthorized'}), 401
        
        # Validate cleanup type
        if cleanup_type not in ['standard', 'aggressive', 'retention']:
            return jsonify({'error': 'Invalid cleanup type. Use: standard, aggressive, or retention'}), 400
        
        # Run cleanup with specified type
        stats = storage_manager.manual_cleanup(cleanup_type)
        
        # Get updated storage status
        storage_status = storage_manager.get_storage_status()
        
        return jsonify({
            'success': True,
            'cleanup_type': cleanup_type,
            'stats': {
                'raw_removed': stats['raw_removed'],
                'processed_removed': stats['processed_removed'],
                'total_removed': stats['raw_removed'] + stats['processed_removed'],
                'space_freed_gb': round(stats['space_freed'] / (1024**3), 2)
            },
            'storage_status': storage_status['storage_limits'],
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/available-timestamps/<int:hours>')
def get_available_timestamps(hours):
    """Get list of timestamps that have images available"""
    try:
        if hours < 1 or hours > 48:
            return jsonify({'error': 'Hours must be between 1 and 48'}), 400
        
        timestamps = storage_manager.get_available_timestamps(hours)
        
        return jsonify({
            'hours': hours,
            'count': len(timestamps),
            'timestamps': timestamps
        })
        
    except Exception as e:
        logger.error(f"Error getting timestamps: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/stream')
def stream():
    """Server-Sent Events stream that pushes 'new-frame' events to the browser
    whenever a newer timestamp has finished processing."""
    def event_generator():
        q = event_broker.subscribe()
        try:
            # Tell the client it's connected.
            yield 'event: connected\ndata: {}\n\n'
            while not shutdown_event.is_set():
                try:
                    timestamp = q.get(timeout=25)
                    payload = json.dumps({'timestamp': timestamp})
                    yield f'event: new-frame\ndata: {payload}\n\n'
                except queue.Empty:
                    # Comment line keeps the connection alive through proxies.
                    yield ': keep-alive\n\n'
        finally:
            event_broker.unsubscribe(q)

    response = Response(event_generator(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'  # disable proxy buffering
    response.headers['Connection'] = 'keep-alive'
    return response

# Serve images from the images directory
@app.route('/images/<path:filename>')
def serve_image(filename):
    """Serve processed images with caching headers"""
    try:
        # Security check - prevent directory traversal
        if '..' in filename or filename.startswith('/'):
            abort(403)
        
        # Build full path
        image_path = os.path.join(IMAGES_DIR, filename)
        
        # Check if file exists
        if not os.path.exists(image_path):
            abort(404)
        
        # Get file modification time for ETag
        file_stat = os.stat(image_path)
        file_size = file_stat.st_size
        file_mtime = int(file_stat.st_mtime)
        
        # Generate ETag based on file size and mtime
        etag = f'"{file_size}-{file_mtime}"'
        
        # Check if client has cached version
        if request.headers.get('If-None-Match') == etag:
            return '', 304
        
        # Serve the file with caching headers
        response = send_file(image_path, mimetype='image/jpeg')
        
        # Add caching headers
        response.headers['Cache-Control'] = 'public, max-age=3600, immutable'  # Cache for 1 hour
        response.headers['ETag'] = etag
        response.headers['Last-Modified'] = datetime.fromtimestamp(file_mtime, timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
        
        return response
        
    except Exception as e:
        logger.error(f"Error serving image {filename}: {e}")
        abort(500)

# Serve static files (CSS, JS)
@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

# Serve favicon at the site root (browsers request /favicon.ico directly)
@app.route('/favicon.ico')
def favicon():
    """Serve the favicon from the site root"""
    return send_from_directory('static/favicons', 'favicon.ico',
                               mimetype='image/x-icon')

# Health check endpoint
@app.route('/health')
def health_check():
    """Simple health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now(timezone.utc).isoformat()
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

# Utility functions
app_start_time = datetime.now(timezone.utc)

def get_uptime_hours():
    """Get application uptime in hours"""
    uptime = datetime.now(timezone.utc) - app_start_time
    return round(uptime.total_seconds() / 3600, 2)

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_event.set()
    
    # Stop all modules
    if downloader:
        downloader.stop()
    if processor:
        processor.stop()
    if storage_manager:
        storage_manager.stop()
    if sun_calculator:
        sun_calculator.stop()
    
    # Wait for threads to finish
    for thread in background_threads:
        if thread.is_alive():
            thread.join(timeout=5)
    
    logger.info("Shutdown complete")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Template context processors
@app.context_processor
def inject_config():
    """Inject configuration into templates"""
    return {
        'bands': BANDS,
        'time_periods': TIME_PERIODS,
        'current_year': datetime.now().year,
        'asset_version': ASSET_VERSION
    }

# CLI commands for development
@app.cli.command()
def init_db():
    """Initialize the database (placeholder for future use)"""
    logger.info("Database initialized")

@app.cli.command()
def test_modules():
    """Test all modules"""
    logger.info("Testing modules...")
    
    # Test storage manager
    status = storage_manager.get_storage_status()
    logger.info(f"Storage: {status['disk']['free_gb']} GB free")
    
    # Test sun calculator
    sun_status = sun_calculator.get_status()
    logger.info(f"Sun: {sun_status['grid_mode']} mode")
    
    # Test image processor
    proc_status = processor.get_status()
    logger.info(f"Processor: {proc_status['queue_size']} items in queue")
    
    logger.info("Module tests complete")

def main():
    """Main entry point"""
    logger.info("Starting Satellite Weather Looping System")
    logger.info(f"Images directory: {IMAGES_DIR}")
    
    # Start Flask app
    app.run(
        host=FLASK_CONFIG['HOST'],
        port=FLASK_CONFIG['PORT'],
        debug=FLASK_CONFIG['DEBUG'],
        threaded=FLASK_CONFIG['THREADED'],
        use_reloader=False  # Disable reloader for 24/7 operation
    )

if __name__ == '__main__':
    main()
