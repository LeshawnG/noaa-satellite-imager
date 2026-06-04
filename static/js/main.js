/**
 * Enhanced Main Application Controller for Satellite Weather Loop
 * Coordinates all modules and manages global state with improved image handling
 */

class SatelliteWeatherApp {
    constructor() {
        this.config = null;
        this.sunStatus = null;
        this.gridImages = {};
        this.gridTimestamps = [];        // master timeline (ISO) shared by all bands
        this.gridTimestampsLocal = [];   // local-time labels for the master timeline
        this.eventSource = null;         // SSE connection for new-frame push
        this.currentMode = 'day'; // day or night
        this.currentHours = 24;
        this.currentZoom = 'Zoom1';
        this.isPlaying = true;
        this.isZoomChanging = false; // Track zoom change state
        this.pendingZoom = null; // Latest zoom requested while a change is in flight (latest-wins)
        this.pendingModeChange = null; // Track delayed mode changes during zoom changes
        
        // Module instances
        this.loopController = null;
        this.gridManager = null;
        this.timeControls = null;
        this.fullscreenViewer = null;
        this.progressSlider = null;
        this.globalProgress = null;
        
        // Performance and error tracking
        this.performanceMonitor = {
            frameDrops: 0,
            loadErrors: 0,
            lastUpdateTime: 0,
            averageFPS: 0
        };
        
        // Network status
        this.isOnline = navigator.onLine;
        this.lastSuccessfulUpdate = null;
        
        // API endpoints
        this.api = {
            config: '/api/config',
            sunStatus: '/api/sun-status',
            gridImages: '/api/grid-images',
            systemStatus: '/api/system-status'
        };
        
        // Initialize on DOM ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.init());
        } else {
            this.init();
        }
        
        // Make app globally available for debugging
        window.app = this;
    }
    
    async init() {
        try {
            console.log('Initializing Enhanced Satellite Weather App...');
            
            // Initialize global progress indicator
            this.globalProgress = new GlobalProgressIndicator();
            this.globalProgress.show();
            this.globalProgress.updateProgress(0.1);
            
            // Load configuration
            await this.loadConfig();
            this.globalProgress.updateProgress(0.3);
            
            // Initialize modules
            this.initializeModules();
            this.globalProgress.updateProgress(0.5);
            
            // Load initial data
            await this.loadInitialData();
            this.globalProgress.updateProgress(0.8);
            
            // Set up event handlers
            this.setupEventHandlers();

            // Start update timers
            this.startUpdateTimers();

            // Open the SSE push stream for real-time new-frame notifications
            this.setupEventStream();
            
            // Complete initialization
            this.globalProgress.updateProgress(1.0);
            
            console.log('Enhanced Satellite Weather App initialized successfully');
            
        } catch (error) {
            console.error('Failed to initialize app:', error);
            this.showError('Failed to initialize application. Please refresh the page.');
            this.globalProgress.hide();
        }
    }
    
    async loadConfig() {
        try {
            const response = await fetch(this.api.config);
            if (!response.ok) throw new Error('Failed to load configuration');
            
            this.config = await response.json();
            console.log('Configuration loaded:', this.config);
            
        } catch (error) {
            console.error('Error loading config:', error);
            throw error;
        }
    }
    
    initializeModules() {
        // Initialize Loop Controller with improved error handling
        this.loopController = new LoopController({
            frameRate: this.getDefaultFPS(), // Use default FPS from config
            preloadAhead: 10,
            preloadBehind: 5,
            onFrameChange: (frameIndex) => this.onFrameChange(frameIndex),
            onLoadProgress: (progress) => this.onLoadProgress(progress),
            onPerformanceUpdate: (stats) => this.onPerformanceUpdate(stats)
        });
        
        // Initialize Enhanced Grid Manager
        this.gridManager = new GridManager({
            config: this.config,
            loopController: this.loopController,
            onCellClick: (cellId) => this.onGridCellClick(cellId),
            onImageError: (cellId, error) => this.onImageError(cellId, error),
            onTransitionComplete: (cellId) => this.onTransitionComplete(cellId)
        });
        
        // Share the grid's image cache with the loop controller so frames are
        // downloaded/decoded exactly once (single source of truth).
        if (this.gridManager && this.gridManager.imageManager) {
            this.loopController.setImageManager(this.gridManager.imageManager);
        }

        // Initialize Time Controls
        this.timeControls = new TimeControls({
            config: this.config,
            onTimeChange: (hours) => this.onTimeChange(hours),
            onZoomChange: (zoom) => this.onZoomChange(zoom),
            onPlayPause: () => this.togglePlayPause(),
            onReset: () => this.resetLoop(),
            onFPSChange: (fps) => this.onFPSChange(fps)
        });
        
        // Initialize Fullscreen Viewer
        this.fullscreenViewer = new FullscreenViewer({
            loopController: this.loopController,
            onExit: () => this.onFullscreenExit()
        });
        
        // Initialize Progress Slider
        this.progressSlider = new ProgressSlider({
            onSliderChange: (frame) => this.onSliderChange(frame),
            onSliderStart: () => this.onSliderStart(),
            onSliderEnd: (wasPlaying) => this.onSliderEnd(wasPlaying)
        });
    }
    
    async loadInitialData() {
        // Load sun status
        await this.updateSunStatus();
        
        // Load grid images (initial load should show progress)
        await this.loadGridImages(false);
        
        // Start the loops
        this.startLoops();
        
        // Mark successful initialization
        this.lastSuccessfulUpdate = new Date();
    }
    
    async updateSunStatus() {
        try {
            const response = await fetch(this.api.sunStatus);
            if (!response.ok) throw new Error('Failed to load sun status');
            
            this.sunStatus = await response.json();
            
            // Update mode if changed - BUT ONLY if we're not currently changing zoom
            if (this.sunStatus.grid_mode !== this.currentMode) {
                console.log(`Mode changed from ${this.currentMode} to ${this.sunStatus.grid_mode}`);
                
                // CRITICAL FIX: Don't change mode if we're in the middle of a zoom change
                if (this.isZoomChanging) {
                    console.log('Sun status update: Delaying mode change because zoom change is in progress');
                    // Store the pending mode change for later
                    this.pendingModeChange = this.sunStatus.grid_mode;
                    return;
                }
                
                this.currentMode = this.sunStatus.grid_mode;
                this.gridManager.setMode(this.currentMode);
                
                // Clear any pending mode change since we just processed it
                this.pendingModeChange = null;
            }
            
            // Update UI
            this.updateSunStatusUI();
            
        } catch (error) {
            console.error('Error updating sun status:', error);
            this.performanceMonitor.loadErrors++;
        }
    }
    
    async loadGridImages(seamlessMode = false) {
        try {
            // CRITICAL FIX: If we're changing zoom and this is not seamless mode, defer this call
            if (this.isZoomChanging && !seamlessMode) {
                console.log('LoadGridImages: Deferring non-seamless load during zoom change');
                return;
            }
            
            console.log(`Loading grid images for ${this.currentHours} hours, zoom ${this.currentZoom}${seamlessMode ? ' (seamless mode)' : ''}`);
            
            // Clear any stuck loading states before starting (unless in seamless mode)
            if (!seamlessMode && this.gridManager && this.gridManager.imageManager) {
                this.gridManager.imageManager.clearAllLoadingStates();
            }
            
            const apiUrl = `${this.api.gridImages}/${this.currentHours}/${this.currentZoom}`;
            console.log(`API URL: ${apiUrl}`);
            
            const response = await fetch(apiUrl);
            
            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`API request failed: ${response.status} ${response.statusText} - ${errorText}`);
            }
            
            const data = await response.json();
            
            // Validate response data
            if (!data.bands) {
                throw new Error('Invalid API response: missing bands data');
            }
            
            // CRITICAL: Enforce the zoom level we requested
            if (data.zoom !== this.currentZoom) {
                console.warn(`API returned zoom ${data.zoom} but requested ${this.currentZoom} - forcing consistency`);
                // Don't change our zoom level based on API response
                // The API should return the requested zoom level
            }
            
            // CRITICAL FIX: Assign the bands data structure that the rest of the code expects.
            // Bands are now time-aligned to a shared master timeline (null = gap).
            this.gridImages = data.bands;
            this.gridTimestamps = data.timestamps || [];
            this.gridTimestampsLocal = data.timestamps_local || [];

            // Log image counts for debugging
            const imageCounts = {};
            for (const [band, images] of Object.entries(this.gridImages)) {
                imageCounts[band] = images.length;
            }
            console.log(`Loaded images for ${this.currentZoom}:`, imageCounts);
            
            // Update loop controller first
            this.updateLoopController();
            
            // Update grid display - pass seamlessMode to grid manager
            if (!seamlessMode) {
                await this.gridManager.updateImages(this.gridImages, this.currentZoom, false);
            } else {
                // In seamless mode, just update the current display without heavy preloading
                await this.gridManager.updateImages(this.gridImages, this.currentZoom, true);
            }
            
            // Update UI with current data info - USE OUR zoom level, not API's
            this.updateStatusBar({
                frameCount: data.image_count || 0,
                timeRange: `${this.currentHours}h`,
                zoom: this.currentZoom, // Use our zoom level
                lastUpdate: new Date().toLocaleTimeString()
            });
            
            // Mark successful load
            this.lastSuccessfulUpdate = new Date();
            
            console.log(`Grid images loaded successfully for zoom ${this.currentZoom}`);
            
        } catch (error) {
            console.error('Error loading grid images:', error);
            
            // Clear any stuck loading states on error (unless in seamless mode)
            if (!seamlessMode && this.gridManager && this.gridManager.imageManager) {
                this.gridManager.imageManager.clearAllLoadingStates();
            }
            
            this.performanceMonitor.loadErrors++;
            throw error;
        }
    }
    
    updateLoopController() {
        // Store current playing state and frame
        const wasPlaying = this.loopController.isPlaying;
        const currentFrame = this.loopController.getCurrentFrame();
        
        console.log('Updating loop controller', {
            wasPlaying,
            currentFrame,
            currentMode: this.currentMode,
            totalImages: Object.keys(this.gridImages).length
        });
        
        // Prepare image sets for each cell
        const imageSets = {};
        
        // Get grid configuration for current mode
        const gridConfig = this.config.grid_config[`${this.currentMode}_mode`];
        
        // Top-left: Always GeoColor
        imageSets['top-left'] = this.prepareImageSet('GeoColor');
        
        // Top-right: Always cycles (both day and night have top_right_cycle)
        imageSets['top-right'] = this.prepareCycleImageSet(gridConfig.top_right_cycle);
        
        // Bottom-left: Band 2 (day) or Band 13 (night)
        if (this.currentMode === 'day') {
            imageSets['bottom-left'] = this.prepareImageSet('Band_2');
        } else {
            imageSets['bottom-left'] = this.prepareImageSet('Band_13');
        }
        
        // Bottom-right: Band 13 (day) or Sandwich RGB (night)
        if (this.currentMode === 'day') {
            imageSets['bottom-right'] = this.prepareImageSet('Band_13');
        } else {
            imageSets['bottom-right'] = this.prepareImageSet('Sandwich_RGB');
        }
        
        // Log prepared image sets
        console.log('Prepared image sets:', Object.keys(imageSets).map(key => ({
            cellId: key,
            type: imageSets[key].type || 'static',
            imageCount: imageSets[key].length || Object.keys(imageSets[key].images || {}).length
        })));
        
        // Use seamless update for smooth zoom transitions
        this.loopController.setImageSetsSeamless(imageSets);
        
        // Update progress slider with new total frames
        if (this.progressSlider) {
            const totalFrames = this.loopController.getTotalFrames();
            this.progressSlider.setTotalFrames(totalFrames);
        }
        
        // If loop was playing, ensure it continues playing with new images
        if (wasPlaying && this.isPlaying) {
            // No delay - seamless transition
            if (!this.loopController.isPlaying) {
                this.loopController.start();
            }
            this.gridManager.startCycles();
            console.log('Loop controller updated seamlessly');
        }
    }
    
    prepareImageSet(bandKey) {
        const images = this.gridImages[bandKey] || [];
        // Preserve nulls (timeline gaps) so every band stays index-aligned to
        // the master timeline; the display layer carries the last good frame.
        return images.map(img => img ? {
            url: img.grid_path || img.path,  // small variant for the grid display
            fullUrl: img.path,               // full-res for the fullscreen viewer
            timestamp: img.timestamp,
            localTime: img.local_time
        } : null);
    }
    
    prepareCycleImageSet(cycleBands) {
        // For cycle loops, prepare multiple bands
        const cycleSet = {
            type: 'cycle',
            bands: cycleBands,
            duration: this.config.grid_config.cycle_duration_seconds * 1000,
            images: {}
        };
        
        // Prepare images for each band in the cycle
        cycleBands.forEach(bandKey => {
            cycleSet.images[bandKey] = this.prepareImageSet(bandKey);
        });
        
        return cycleSet;
    }
    
    startLoops() {
        this.loopController.start();
        this.gridManager.startCycles();
    }
    
    setupEventHandlers() {
        // Window resize with debouncing
        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => this.handleResize(), 250);
        });
        
        // Visibility change (tab switching)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.loopController.pause();
                this.gridManager.pauseCycles();
            } else if (this.isPlaying) {
                this.loopController.resume();
                this.gridManager.resumeCycles();
            }
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => this.handleKeyPress(e));
        
        // Network status
        window.addEventListener('online', () => this.handleNetworkChange(true));
        window.addEventListener('offline', () => this.handleNetworkChange(false));
        
        // Page unload cleanup
        window.addEventListener('beforeunload', () => this.cleanup());
    }
    
    startUpdateTimers() {
        // Update sun status every minute
        setInterval(() => this.updateSunStatus(), 60000);
        
        // Update current time display every second
        setInterval(() => this.updateCurrentTime(), 1000);
        
        // Check for new images every 5 minutes
        setInterval(() => this.checkForNewImages(), 300000);
        
        // Update system status every 5 minutes
        setInterval(() => this.updateSystemStatus(), 300000);
    }

    setupEventStream() {
        // Real-time push: the server emits a 'new-frame' event when a newer
        // timestamp finishes processing. Falls back gracefully (the 5-min
        // checkForNewImages poll still runs) if SSE is unavailable.
        if (typeof EventSource === 'undefined') {
            console.warn('EventSource not supported; relying on polling for updates');
            return;
        }

        try {
            this.eventSource = new EventSource('/api/stream');

            this.eventSource.addEventListener('new-frame', (e) => {
                console.log('SSE: new frame available', e.data);
                // Don't disrupt an in-progress zoom change.
                if (!this.isZoomChanging) {
                    this.loadGridImages().catch(err =>
                        console.error('Error loading images after SSE event:', err));
                }
            });

            this.eventSource.addEventListener('connected', () => {
                console.log('SSE: connected to update stream');
            });

            // Browser auto-reconnects on error; just log it.
            this.eventSource.onerror = () => {
                console.warn('SSE: stream error (will auto-reconnect)');
            };
        } catch (error) {
            console.warn('SSE setup failed; relying on polling:', error);
        }
    }

    updateCurrentTime() {
        const now = new Date();
        const timeStr = now.toLocaleTimeString('en-US', { 
            timeZone: 'America/Port_of_Spain',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
        
        // Update current time in left section with timezone
        const currentTimeElement = document.getElementById('current-time');
        if (currentTimeElement) {
            currentTimeElement.textContent = `${timeStr} (UTC-4)`;
        }
        
        // Update central timestamp only if no frame timestamp is available
        const element = document.getElementById('current-timestamp');
        if (element) {
            const frameTimestamp = this.getCurrentFrameTimestamp();
            if (!frameTimestamp) {
                element.textContent = timeStr;
            }
        }
        
        // Update next sunrise if sun status is available
        this.updateNextSunrise();
    }
    
    getCurrentFrameTimestamp() {
        // The master timeline is authoritative: index N is the same moment in
        // every band, so this label is correct for all four panels at once.
        if (!this.loopController) return null;

        const currentFrame = this.loopController.getCurrentFrame();

        if (this.gridTimestampsLocal && this.gridTimestampsLocal.length > currentFrame) {
            const label = this.gridTimestampsLocal[currentFrame];
            if (label) return label;
        }

        // Fallback: any band that has an image at this frame.
        for (const [bandKey, images] of Object.entries(this.gridImages)) {
            if (images && images.length > currentFrame && images[currentFrame]) {
                const image = images[currentFrame];
                if (image.local_time) return image.local_time;
                if (image.localTime) return image.localTime;
            }
        }

        return null;
    }
    
    updateNextSunrise() {
        if (!this.sunStatus) return;
        
        const element = document.getElementById('next-sunrise');
        if (!element) return;
        
        // Get the next change event information
        if (this.sunStatus.next_change) {
            const nextEvent = this.sunStatus.next_change.event;
            const nextTime = new Date(this.sunStatus.next_change.time);
            const now = new Date();
            
            // Calculate real-time countdown
            const timeDiff = nextTime.getTime() - now.getTime();
            const minutesUntil = Math.max(0, Math.round(timeDiff / (1000 * 60)));
            
            // Format the time in 12-hour format
            const timeString = nextTime.toLocaleTimeString('en-US', {
                timeZone: 'America/Port_of_Spain',
                hour: '2-digit',
                minute: '2-digit',
                hour12: true
            });
            
            // Calculate hours and minutes for countdown
            const hoursUntil = Math.floor(minutesUntil / 60);
            const remainingMinutes = minutesUntil % 60;
            
            // Format countdown - handle different cases
            let countdownText = '';
            if (minutesUntil <= 0) {
                countdownText = 'now';
            } else if (hoursUntil > 0) {
                countdownText = `${hoursUntil}hr ${remainingMinutes}min`;
            } else if (remainingMinutes > 0) {
                countdownText = `${remainingMinutes}min`;
            } else {
                countdownText = '<1min';
            }
            
            // Capitalize the event name for display
            const eventName = nextEvent.charAt(0).toUpperCase() + nextEvent.slice(1);
            
            // Update the display with proper formatting
            element.innerHTML = `Next ${eventName}: <span class="time-value">${timeString}</span> <span class="countdown">(${countdownText})</span>`;
        } else {
            element.innerHTML = 'Next Event: <span class="time-value">--:--</span> <span class="countdown">(--)</span>';
        }
    }
    
    formatMinutesToHoursMinutes(totalMinutes) {
        const hours = Math.floor(totalMinutes / 60);
        const minutes = totalMinutes % 60;
        
        if (hours === 0) {
            return `${minutes}m`;
        } else if (minutes === 0) {
            return `${hours}h`;
        } else {
            return `${hours}h ${minutes}m`;
        }
    }
    
    updateSunStatusUI() {
        if (!this.sunStatus) return;
        
        // Update mode display
        const modeElement = document.getElementById('mode-text');
        if (modeElement) {
            modeElement.textContent = this.currentMode.charAt(0).toUpperCase() + this.currentMode.slice(1);
        }
        
        // Update next change display
        const nextChangeElement = document.getElementById('next-change');
        if (nextChangeElement && this.sunStatus.next_change) {
            const minutes = Math.round(this.sunStatus.next_change.minutes_until);
            const event = this.sunStatus.next_change.event;
            const formattedTime = this.formatMinutesToHoursMinutes(minutes);
            nextChangeElement.textContent = `Next ${event}: ${formattedTime}`;
        }
        
        // Update next sunrise display
        this.updateNextSunrise();
    }
    
    async checkForNewImages() {
        // Fallback only: SSE (setupEventStream) is the primary update path.
        // This safety net reloads if we somehow haven't updated in a while
        // (e.g. the SSE stream dropped and didn't reconnect).
        if (this.isZoomChanging) {
            return;
        }

        const staleMs = 12 * 60 * 1000; // a bit longer than the 10-min cadence
        const lastUpdate = this.lastSuccessfulUpdate ? this.lastSuccessfulUpdate.getTime() : 0;

        if (Date.now() - lastUpdate > staleMs) {
            console.log('Fallback poll: data looks stale, reloading images...');
            await this.loadGridImages();
        }
    }
    
    async updateSystemStatus() {
        try {
            const response = await fetch(this.api.systemStatus);
            if (!response.ok) throw new Error('Failed to load system status');
            
            const status = await response.json();
            console.log('System status:', status);
            
            // Update UI with system status
            this.updateStatusBar(status);
            
        } catch (error) {
            console.error('Error updating system status:', error);
            this.performanceMonitor.loadErrors++;
        }
    }
    
    updateStatusBar(status) {
        // Update frame info with consistent formatting
        const frameInfo = document.getElementById('frame-info');
        if (frameInfo && this.loopController) {
            const current = this.loopController.getCurrentFrame();
            const total = this.loopController.getTotalFrames();
            frameInfo.textContent = `Frame: ${current + 1}/${total}`;
        }
        
        // Update last update time
        const updateStatus = document.getElementById('update-status');
        if (updateStatus && this.lastSuccessfulUpdate) {
            const timeStr = this.lastSuccessfulUpdate.toLocaleTimeString('en-US', { 
                timeZone: 'America/Port_of_Spain',
                hour: '2-digit',
                minute: '2-digit'
            });
            updateStatus.textContent = `Last updated: ${timeStr}`;
        }
        
        // Update current time
        this.updateCurrentTime();
    }
    
    // Enhanced Event Handlers
    onFrameChange(frameIndex) {
        // Notify grid manager of frame change for cycling logic
        if (this.gridManager) {
            this.gridManager.onFrameChange(frameIndex);
        }
        
        // Update progress slider (convert from 0-based to 1-based frame index)
        if (this.progressSlider && !this.progressSlider.isDragging) {
            this.progressSlider.setCurrentFrame(frameIndex + 1);
        }
        
        // Update central timestamp with current frame timestamp
        this.updateFrameTimestamp();
        
        this.updateStatusBar({});
        
        // Update performance tracking
        const now = performance.now();
        if (this.performanceMonitor.lastUpdateTime > 0) {
            const delta = now - this.performanceMonitor.lastUpdateTime;
            const fps = Math.round(1000 / delta);
            this.performanceMonitor.averageFPS = 
                (this.performanceMonitor.averageFPS * 0.9) + (fps * 0.1);
        }
        this.performanceMonitor.lastUpdateTime = now;
    }
    
    updateFrameTimestamp() {
        const element = document.getElementById('current-timestamp');
        if (element) {
            const frameTimestamp = this.getCurrentFrameTimestamp();
            if (frameTimestamp) {
                element.textContent = frameTimestamp;
            } else {
                // Fallback to current time if no frame timestamp available
                const now = new Date();
                const timeStr = now.toLocaleTimeString('en-US', { 
                    timeZone: 'America/Port_of_Spain',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
                element.textContent = timeStr;
            }
        }
    }
    
    onLoadProgress(progress) {
        console.log(`Loading progress: ${Math.round(progress * 100)}%`);
        
        // Update global progress if visible
        if (this.globalProgress && this.globalProgress.isVisible) {
            this.globalProgress.updateProgress(progress);
        }
    }
    
    onPerformanceUpdate(stats) {
        if (stats.frameDrops > this.performanceMonitor.frameDrops) {
            console.warn(`Frame drops detected: ${stats.frameDrops - this.performanceMonitor.frameDrops}`);
            this.performanceMonitor.frameDrops = stats.frameDrops;
        }
    }
    
    onImageError(cellId, error) {
        console.error(`Image error in ${cellId}:`, error);
        this.performanceMonitor.loadErrors++;
        
        // Show error state for the specific cell
        this.showCellError(cellId, 'Failed to load image');
    }
    
    onTransitionComplete(cellId) {
        console.log(`Transition completed in ${cellId}`);
    }
    
    onGridCellClick(cellId) {
        if (this.fullscreenViewer) {
            this.fullscreenViewer.show(cellId);
        }
    }
    
    async onTimeChange(hours) {
        console.log(`Main: Time period changed to ${hours} hours`);
        
        // Check if in zoom change state
        if (this.isZoomChanging) {
            console.log('Main: Currently changing zoom, ignoring time change');
            return;
        }
        
        this.currentHours = hours;
        
        // Update loop controller FPS if auto-FPS is enabled
        if (this.timeControls && this.timeControls.autoFPS) {
            const defaultFPS = this.getDefaultFPS();
            if (this.loopController) {
                this.loopController.setFrameRate(defaultFPS);
            }
        }
        
        try {
            await this.loadGridImages();
        } catch (error) {
            console.error('Error loading images after time change:', error);
            this.showError(`Failed to load images for ${hours} hour period`);
        }
    }
    
    async onZoomChange(zoom) {
        const changeId = Date.now(); // Unique ID for this change
        console.log(`[${changeId}] Main: Zoom level change requested to ${zoom} (current: ${this.currentZoom})`);
        
        // Validate zoom level
        if (!zoom || !['Zoom1', 'Zoom2', 'Zoom3'].includes(zoom)) {
            console.error(`[${changeId}] Main: Invalid zoom level: ${zoom}`);
            return;
        }

        // If a change is already running, remember the LATEST requested zoom and
        // bail. It will be applied when the current change finishes, so the final
        // displayed view always matches the last selection (no stale dropdown).
        if (this.isZoomChanging) {
            console.log(`[${changeId}] Main: Change in progress, queuing latest zoom: ${zoom}`);
            this.pendingZoom = zoom;
            return;
        }

        // Check if this is actually a change
        if (zoom === this.currentZoom) {
            console.log(`[${changeId}] Main: Zoom already set to ${zoom}, no change needed`);
            // Still make sure the selector reflects reality.
            if (this.timeControls) this.timeControls.setZoomLevel(this.currentZoom);
            return;
        }

        // FORCE the zoom level - don't let anything override it
        const oldZoom = this.currentZoom;
        const wasPlaying = this.isPlaying;
        // Zoom keeps the same timeline (same timestamps), so remember the frame
        // we're on and continue from it after the switch.
        const keepFrame = this.loopController ? this.loopController.getCurrentFrame() : 0;
        this.currentZoom = zoom;
        this.isZoomChanging = true;
        this.pendingZoom = null;

        console.log(`[${changeId}] Main: Starting immediate zoom change from ${oldZoom} to ${zoom}`);

        try {
            // Briefly pause so the old frames don't advance while we swap image
            // sets; the frame index itself is preserved.
            if (this.loopController) {
                this.loopController.pause();
            }

            // Load + immediately display the new zoom (seamless = instant src
            // swap on every cell; the loop's frame index is preserved).
            await this.loadGridImages(true);

            // Continue from the same frame/timestamp in the new zoom and resume
            // immediately — no multi-second wait.
            if (this.loopController) {
                const total = this.loopController.getTotalFrames();
                const frame = Math.max(0, Math.min(keepFrame, total - 1));
                this.loopController.setFrameFromUser(frame + 1); // 1-based
                this.loopController.updateFrame();

                if (wasPlaying) {
                    this.loopController.resume();
                    if (this.gridManager) {
                        this.gridManager.startCycles();
                    }
                }
            }

            console.log(`[${changeId}] Main: Zoom changed to ${zoom}, continuing from frame ${keepFrame + 1}`);

        } catch (error) {
            console.error(`[${changeId}] Error during immediate zoom change:`, error);
            
            // Revert zoom level on failure
            console.log(`[${changeId}] Reverting zoom from ${this.currentZoom} back to ${oldZoom}`);
            this.currentZoom = oldZoom;
            if (this.timeControls) {
                this.timeControls.setZoomLevel(oldZoom);
            }
            
            this.showError(`Failed to switch to ${zoom} view. Please try again.`);
            
            // Resume playback even if zoom change failed
            if (this.loopController && wasPlaying) {
                this.loopController.resume();
            }
        } finally {
            // Always clean up
            console.log(`[${changeId}] Cleaning up zoom change state`);
            this.isZoomChanging = false;

            // CRITICAL FIX: Process any pending mode change that was delayed during zoom change
            if (this.pendingModeChange && this.pendingModeChange !== this.currentMode) {
                console.log(`[${changeId}] Processing delayed mode change to ${this.pendingModeChange}`);
                this.currentMode = this.pendingModeChange;
                this.gridManager.setMode(this.currentMode);
                this.pendingModeChange = null;
                console.log(`[${changeId}] Delayed mode change completed`);
            }

            // Latest-wins: if the user picked another zoom mid-change, apply it now.
            if (this.pendingZoom && this.pendingZoom !== this.currentZoom) {
                const next = this.pendingZoom;
                this.pendingZoom = null;
                console.log(`[${changeId}] Applying queued zoom: ${next}`);
                // Re-run; this call will reconcile the selector when it finishes.
                this.onZoomChange(next);
            } else {
                this.pendingZoom = null;
                // Guarantee the dropdown matches the view that is actually displayed.
                if (this.timeControls) {
                    this.timeControls.setZoomLevel(this.currentZoom);
                }
            }
        }
    }
    
    togglePlayPause() {
        this.isPlaying = !this.isPlaying;
        
        const button = document.getElementById('play-pause-btn');
        const text = document.getElementById('play-pause-text');
        
        if (this.isPlaying) {
            this.loopController.resume();
            this.gridManager.resumeCycles();
            if (button) button.classList.add('active');
            if (text) text.textContent = 'Pause';
        } else {
            this.loopController.pause();
            this.gridManager.pauseCycles();
            if (button) button.classList.remove('active');
            if (text) text.textContent = 'Play';
        }
        
        // Update slider playing state
        if (this.progressSlider) {
            this.progressSlider.setPlayingState(this.isPlaying);
        }
    }
    
    onFullscreenExit() {
        // Resume normal playback
        if (this.isPlaying) {
            this.loopController.resume();
            this.gridManager.resumeCycles();
        }
    }
    
    handleResize() {
        // Grid manager handles its own resize logic
        console.log('Window resized, updating layout...');
    }
    
    handleKeyPress(e) {
        switch(e.key) {
            case ' ':
                e.preventDefault();
                this.togglePlayPause();
                break;
            case 'f':
            case 'F':
                // Toggle fullscreen for focused element
                break;
            case 'Escape':
                // Handled by fullscreen viewer
                break;
            case 'r':
            case 'R':
                if (e.ctrlKey || e.metaKey) {
                    e.preventDefault();
                    this.refreshImages();
                }
                break;
        }
    }
    
    handleNetworkChange(online) {
        this.isOnline = online;
        
        if (online) {
            console.log('Network connection restored');
            this.hideError();
            this.loadGridImages(false); // Network restoration should show progress
        } else {
            console.log('Network connection lost');
            this.showError('Network connection lost. Displaying cached images.');
        }
    }
    
    // Enhanced UI Methods
    showError(message, duration = 5000) {
        console.error(message);
        
        // Create or update error display
        let errorElement = document.getElementById('global-error');
        if (!errorElement) {
            errorElement = document.createElement('div');
            errorElement.id = 'global-error';
            errorElement.className = 'error-message';
            errorElement.style.cssText = `
                position: fixed;
                top: 80px;
                left: 50%;
                transform: translateX(-50%);
                background-color: rgba(204, 0, 0, 0.9);
                color: white;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
                z-index: 1000;
                box-shadow: 0 4px 20px rgba(204, 0, 0, 0.3);
                animation: slideDown 0.3s ease-out;
            `;
            document.body.appendChild(errorElement);
        }
        
        errorElement.textContent = message;
        errorElement.style.display = 'block';
        
        // Auto-hide after duration
        if (duration > 0) {
            setTimeout(() => this.hideError(), duration);
        }
    }
    
    showCellError(cellId, message) {
        // This is handled by the enhanced image manager
        if (this.gridManager) {
            this.gridManager.showErrorOverlay(cellId);
        }
    }
    
    hideError() {
        const errorElement = document.getElementById('global-error');
        if (errorElement) {
            errorElement.style.display = 'none';
        }
    }
    
    async refreshImages() {
        console.log('Manually refreshing images...');
        
        // Clear any stuck loading states before refresh
        if (this.gridManager && this.gridManager.imageManager) {
            this.gridManager.imageManager.clearAllLoadingStates();
        }
        
        this.globalProgress.show();
        
        try {
            await this.loadGridImages(false); // Explicitly use non-seamless mode for refresh
        } catch (error) {
            console.error('Error refreshing images:', error);
            this.showError('Failed to refresh images. Please try again.');
        } finally {
            this.globalProgress.hide();
        }
    }
    
    cleanup() {
        console.log('Cleaning up application...');
        
        if (this.gridManager) {
            this.gridManager.destroy();
        }
        
        if (this.loopController) {
            this.loopController.destroy();
        }
        
        if (this.progressSlider) {
            this.progressSlider.destroy();
        }

        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
    }
    
    // Debug methods
    getDebugInfo() {
        return {
            config: this.config,
            currentMode: this.currentMode,
            currentHours: this.currentHours,
            currentZoom: this.currentZoom,
            isPlaying: this.isPlaying,
            isOnline: this.isOnline,
            performanceMonitor: this.performanceMonitor,
            lastSuccessfulUpdate: this.lastSuccessfulUpdate,
            imageManagerStats: this.gridManager ? this.gridManager.getImageManagerStats() : null
        };
    }
    
    onFPSChange(fps) {
        console.log(`Main: FPS changed to ${fps}`);
        
        if (this.loopController) {
            this.loopController.setFrameRate(fps);
        }
        
        // Update performance monitoring
        this.performanceMonitor.lastUpdateTime = performance.now();
    }
    
    getDefaultFPS() {
        // Get default FPS for current time period from config
        if (this.config && this.config.fps_config && this.config.fps_config.default_fps) {
            const defaultFPS = this.config.fps_config.default_fps[this.currentHours];
            if (defaultFPS) {
                return defaultFPS;
            }
        }
        return 10; // Fallback default (middle button)
    }
    
    // Progress Slider Event Handlers
    onSliderChange(frame) {
        console.log(`Main: Slider changed to frame ${frame}`);
        
        // Update loop controller to the new frame
        if (this.loopController) {
            this.loopController.setFrameFromUser(frame);
        }
    }
    
    onSliderStart() {
        console.log('Main: Slider dragging started');
        
        // Store current playing state and pause playback for smooth scrubbing
        if (this.isPlaying) {
            this.loopController.pause();
            this.gridManager.pauseCycles();
        }
    }
    
    onSliderEnd(wasPlaying) {
        console.log(`Main: Slider dragging ended, was playing: ${wasPlaying}`);
        
        // Resume playback if it was playing before dragging
        if (wasPlaying && this.isPlaying) {
            this.loopController.resume();
            this.gridManager.resumeCycles();
        }
    }
    
    // Reset functionality
    resetLoop() {
        console.log('Main: Resetting loop to frame 1');
        
        // Reset loop controller to frame 1
        if (this.loopController) {
            this.loopController.setFrameFromUser(1);
        }
        
        // Reset progress slider
        if (this.progressSlider) {
            this.progressSlider.reset();
        }
    }
}

// Initialize the application
const app = new SatelliteWeatherApp();