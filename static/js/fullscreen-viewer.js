/**
 * Fullscreen Viewer for Satellite Weather Display
 * Manages fullscreen viewing of individual satellite bands
 */

class FullscreenViewer {
    constructor(options = {}) {
        this.options = {
            loopController: null,
            onExit: null,
            frameRate: 10,
            ...options
        };
        
        // Current state
        this.isVisible = false;
        this.currentCellId = null;
        this.currentBand = null;
        this.currentFrame = 0;
        this.isPlaying = true;
        
        // Image data
        this.images = [];
        this.imageCache = new Map();
        
        // Animation
        this.animationId = null;
        this.lastFrameTime = 0;
        this.frameInterval = 1000 / this.options.frameRate;
        
        // DOM elements
        this.overlay = null;
        this.container = null;
        this.elements = {};
        
        // Initialize
        this.init();
    }
    
    init() {
        // Create fullscreen overlay structure
        this.createOverlay();
        
        // Attach event listeners
        this.attachEventListeners();
    }
    
    createOverlay() {
        // Check if overlay already exists
        this.overlay = document.getElementById('fullscreen-overlay');
        
        if (!this.overlay) {
            // Create new overlay
            this.overlay = document.createElement('div');
            this.overlay.id = 'fullscreen-overlay';
            this.overlay.style.display = 'none';
            document.body.appendChild(this.overlay);
        }
        
        // Get the original header and status bar from the main page
        const originalHeader = document.querySelector('.header');
        const originalStatusBar = document.querySelector('.status-bar');
        
        // Create fullscreen structure with full controls
        this.overlay.innerHTML = `
            <div class="fullscreen-main-container">
                <!-- Clone of main header with all controls -->
                <div class="fullscreen-header">
                    <h1>Satellite Weather Loop - Trinidad & Tobago</h1>
                    <div class="controls">
                        <div class="playback-controls">
                            <button id="fs-play-pause-btn" class="active">
                                <span id="fs-play-pause-text">Pause</span>
                            </button>
                            <div class="progress-slider-container">
                                <input type="range" id="fs-progress-slider" min="1" max="100" value="1" class="progress-slider">
                                <div class="slider-track">
                                    <div class="slider-progress" id="fs-slider-progress"></div>
                                </div>
                            </div>
                            <button id="fs-reset-btn">Reset</button>
                        </div>
                        <div class="fps-controls">
                            <label>FPS:</label>
                            <div class="fps-buttons">
                                <button class="fps-btn active" data-fps="10">10</button>
                                <button class="fps-btn" data-fps="5">5</button>
                                <button class="fps-btn" data-fps="1">1</button>
                            </div>
                            <button id="fs-fps-auto-btn" class="fps-auto active" title="Auto-adjust FPS based on time period">Auto</button>
                        </div>
                        <div class="time-selector">
                            <label for="fs-time-period">Time Period:</label>
                            <select id="fs-time-period">
                                <option value="2">Last 2 Hours</option>
                                <option value="6">Last 6 Hours</option>
                                <option value="12">Last 12 Hours</option>
                                <option value="24" selected>Last 24 Hours</option>
                                <option value="48">Last 48 Hours</option>
                            </select>
                        </div>
                        <div class="zoom-selector">
                            <label for="fs-zoom-level">Zoom:</label>
                            <select id="fs-zoom-level">
                                <option value="Zoom1" selected>Close</option>
                                <option value="Zoom2">Medium</option>
                                <option value="Zoom3">Wide</option>
                            </select>
                        </div>
                    </div>
                </div>
                
                <!-- Main fullscreen image content -->
                <div class="fullscreen-content">
                    <img class="fullscreen-image" id="fs-image" src="" alt="">
                </div>
                
                <!-- Clone of status bar -->
                <div class="fullscreen-status-bar">
                    <!-- Left section: Current time, Mode, Next sunrise -->
                    <div class="status-left">
                        <div class="time-container">
                            <span id="fs-current-time">--:--:--</span>
                        </div>
                        <div class="mode-container">
                            <span>Mode: <span id="fs-mode-text">--</span></span>
                        </div>
                        <div class="sunrise-container">
                            <span id="fs-next-sunrise">Next Sunrise: --:--</span>
                        </div>
                    </div>
                    
                    <!-- Center: Timestamp -->
                    <div class="central-timestamp">
                        <div id="fs-current-timestamp">Current: --:--:--</div>
                    </div>
                    
                    <!-- Right section: Frame info, Last updated -->
                    <div class="status-right">
                        <div class="frame-container">
                            <span id="fs-frame-info">Frame: 0/0</span>
                        </div>
                        <div class="update-container">
                            <span id="fs-update-status">Last Update: --:--</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="fullscreen-close" id="fs-close-btn">&times;</div>
        `;
        
        // Get element references
        this.elements = {
            playPauseBtn: document.getElementById('fs-play-pause-btn'),
            playPauseText: document.getElementById('fs-play-pause-text'),
            progressSlider: document.getElementById('fs-progress-slider'),
            sliderProgress: document.getElementById('fs-slider-progress'),
            resetBtn: document.getElementById('fs-reset-btn'),
            fpsButtons: document.querySelectorAll('#fullscreen-overlay .fps-btn'),
            fpsAutoBtn: document.getElementById('fs-fps-auto-btn'),
            timePeriod: document.getElementById('fs-time-period'),
            zoomLevel: document.getElementById('fs-zoom-level'),
            closeBtn: document.getElementById('fs-close-btn'),
            image: document.getElementById('fs-image'),
            currentTime: document.getElementById('fs-current-time'),
            modeText: document.getElementById('fs-mode-text'),
            nextSunrise: document.getElementById('fs-next-sunrise'),
            currentTimestamp: document.getElementById('fs-current-timestamp'),
            frameInfo: document.getElementById('fs-frame-info'),
            updateStatus: document.getElementById('fs-update-status')
        };
        
        // Add fullscreen-specific styles
        this.addStyles();
    }
    
    addStyles() {
        // Check if styles already exist
        if (document.getElementById('fullscreen-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'fullscreen-styles';
        style.textContent = `
            .fullscreen-main-container {
                height: 100%;
                display: flex;
                flex-direction: column;
                background-color: #0a0a0a;
            }
            
            .fullscreen-header {
                background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%);
                padding: 8px 64px 8px 20px;  /* reserve right space for the close button */
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid #333;
                box-shadow: 0 2px 15px rgba(0, 0, 0, 0.6);
                z-index: 1002;
                backdrop-filter: blur(10px);
                position: relative;
            }
            
            .fullscreen-header::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 1px;
                background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
            }
            
            .fullscreen-header h1 {
                font-size: 22px;
                font-weight: 400;
                letter-spacing: -0.3px;
                background: linear-gradient(135deg, #fff 0%, #e0e0e0 50%, #ccc 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
            }
            
            .fullscreen-content {
                flex: 1;
                min-height: 0;       /* allow the image to shrink instead of pushing the status bar off-screen */
                overflow: hidden;
                display: flex;
                align-items: center;
                justify-content: center;
                background-color: #000;
                position: relative;
                cursor: zoom-out;    /* clicking the image returns to the grid */
            }
            
            .fullscreen-image {
                max-width: 100%;
                max-height: 100%;
                object-fit: contain;
                object-position: center;
                transition: opacity 0.3s ease;
            }
            
            .fullscreen-status-bar {
                background-color: #1a1a1a;
                padding: 4px 15px;
                border-top: 1px solid #333;
                height: 28px;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                font-size: 11px;
                display: grid;
                grid-template-columns: 1fr 200px 1fr;
                align-items: center;
                width: 100%;
                z-index: 1002;
            }
            
            .fullscreen-status-bar .status-left {
                display: flex;
                gap: 15px;
                align-items: center;
                justify-content: flex-start;
                justify-self: start;
            }
            
            .fullscreen-status-bar .central-timestamp {
                display: flex;
                align-items: center;
                justify-content: center;
                justify-self: center;
                width: 100%;
            }
            
            .fullscreen-status-bar .status-right {
                display: flex;
                gap: 15px;
                align-items: center;
                justify-content: flex-end;
                justify-self: end;
            }
            
            .fullscreen-close {
                position: absolute;
                top: 6px;
                right: 14px;
                background-color: rgba(0, 0, 0, 0.7);
                color: #fff;
                border: none;
                width: 36px;
                height: 36px;
                border-radius: 50%;
                cursor: pointer;
                font-size: 18px;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.3s ease;
                z-index: 1003;
            }
            
            .fullscreen-close:hover {
                background-color: rgba(139, 0, 0, 0.9);
                transform: scale(1.1);
            }
            
            @keyframes fadeIn {
                from { opacity: 0; transform: scale(0.95); }
                to { opacity: 1; transform: scale(1); }
            }
            
            #fullscreen-overlay.show {
                animation: fadeIn 0.3s ease-out;
            }
        `;
        document.head.appendChild(style);
    }
    
    attachEventListeners() {
        // Close buttons
        if (this.elements.closeBtn) {
            this.elements.closeBtn.addEventListener('click', () => this.hide());
        }
        
        // Play/Pause
        if (this.elements.playPauseBtn) {
            this.elements.playPauseBtn.addEventListener('click', () => this.togglePlayPause());
        }
        
        // Reset button
        if (this.elements.resetBtn) {
            this.elements.resetBtn.addEventListener('click', () => this.resetToFirstFrame());
        }
        
        // Progress slider
        if (this.elements.progressSlider) {
            this.elements.progressSlider.addEventListener('input', (e) => {
                this.handleProgressSliderChange(parseInt(e.target.value));
            });
        }
        
        // FPS buttons
        if (this.elements.fpsButtons) {
            this.elements.fpsButtons.forEach(btn => {
                btn.addEventListener('click', () => this.handleFpsChange(parseInt(btn.dataset.fps)));
            });
        }
        
        // FPS Auto button
        if (this.elements.fpsAutoBtn) {
            this.elements.fpsAutoBtn.addEventListener('click', () => this.toggleFpsAuto());
        }
        
        // Time period change
        if (this.elements.timePeriod) {
            this.elements.timePeriod.addEventListener('change', (e) => {
                this.handleTimeChange(parseInt(e.target.value));
            });
        }
        
        // Zoom level change
        if (this.elements.zoomLevel) {
            this.elements.zoomLevel.addEventListener('change', (e) => {
                this.handleZoomChange(e.target.value);
            });
        }
        
        // Keyboard events
        document.addEventListener('keydown', (e) => this.handleKeyPress(e));
        
        // Click the image, the content area, or the backdrop to return to the grid.
        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.overlay ||
                e.target.classList.contains('fullscreen-content') ||
                e.target.classList.contains('fullscreen-image')) {
                this.hide();
            }
        });
    }
    
    // Alias used by the ⛶ icon (enterFullscreen) and other callers.
    enter(cellId, bandData = null) {
        this.show(cellId, bandData);
    }

    // Resolve which band a cell is currently showing. Cycling cells (e.g. the
    // top-right panel) must enlarge the band that is visible right now.
    resolveBand(cellId) {
        const gm = window.app && window.app.gridManager;
        if (gm && gm.cells && gm.cells[cellId]) {
            const cell = gm.cells[cellId];
            if (cell.isCycle) {
                return gm.getCurrentCycleBand(cellId) ||
                       (Array.isArray(cell.band) ? cell.band[0] : cell.band);
            }
            return cell.band;
        }
        return null;
    }

    show(cellId, bandData = null) {
        if (!this.overlay) return;

        this.currentCellId = cellId;
        this.currentBand = bandData || this.resolveBand(cellId);
        this.isVisible = true;

        // Show overlay (block container; .fullscreen-main-container fills it at 100%)
        this.overlay.style.display = 'block';
        setTimeout(() => {
            this.overlay.classList.add('show');
        }, 10);

        // Sync with main application state (play state, fps, slider range)
        this.syncWithMainApp();

        // Continue from the frame the grid is currently showing so the
        // transition is seamless rather than jumping back to the start.
        if (this.options.loopController) {
            this.currentFrame = this.options.loopController.getCurrentFrame() || 0;
        }

        // Load images for the selected band (full-res) and display current frame
        this.loadBandImages();
        this.updateProgressTracking();

        // Start animation if playing
        if (this.isPlaying) {
            this.startAnimation();
        }

        // Start status sync timer
        this.startStatusSync();

        console.log(`Showing fullscreen for cell: ${cellId}, band: ${this.currentBand}`);
    }
    
    syncWithMainApp() {
        // Sync time period
        const mainTimePeriod = document.getElementById('time-period');
        if (mainTimePeriod && this.elements.timePeriod) {
            this.elements.timePeriod.value = mainTimePeriod.value;
        }
        
        // Sync zoom level
        const mainZoomLevel = document.getElementById('zoom-level');
        if (mainZoomLevel && this.elements.zoomLevel) {
            this.elements.zoomLevel.value = mainZoomLevel.value;
        }
        
        // Sync play/pause state
        const mainPlayPause = document.getElementById('play-pause-btn');
        if (mainPlayPause) {
            const isMainPlaying = mainPlayPause.classList.contains('active');
            this.isPlaying = isMainPlaying;
            this.updatePlayPauseButton();
        }
        
        // Sync FPS settings
        const mainFpsButtons = document.querySelectorAll('.fps-btn');
        const mainFpsAuto = document.getElementById('fps-auto-btn');
        
        if (mainFpsButtons && this.elements.fpsButtons) {
            // Find active FPS button
            const activeFpsBtn = Array.from(mainFpsButtons).find(btn => btn.classList.contains('active'));
            if (activeFpsBtn) {
                const fps = parseInt(activeFpsBtn.dataset.fps);
                this.setActiveFpsButton(fps);
                this.options.frameRate = fps;
                this.frameInterval = 1000 / fps;
            }
        }
        
        if (mainFpsAuto && this.elements.fpsAutoBtn) {
            const isAutoActive = mainFpsAuto.classList.contains('active');
            if (isAutoActive) {
                this.elements.fpsAutoBtn.classList.add('active');
            } else {
                this.elements.fpsAutoBtn.classList.remove('active');
            }
        }
        
        // Sync progress slider
        const mainProgressSlider = document.getElementById('progress-slider');
        if (mainProgressSlider && this.elements.progressSlider) {
            this.elements.progressSlider.value = mainProgressSlider.value;
            this.elements.progressSlider.max = mainProgressSlider.max;
            this.updateProgressDisplay();
        }
        
        // Sync status bar data
        this.syncStatusBarData();
    }
    
    syncStatusBarData() {
        // Sync current time
        const mainCurrentTime = document.getElementById('current-time');
        if (mainCurrentTime && this.elements.currentTime) {
            this.elements.currentTime.textContent = mainCurrentTime.textContent;
        }
        
        // Sync mode
        const mainModeText = document.getElementById('mode-text');
        if (mainModeText && this.elements.modeText) {
            this.elements.modeText.textContent = mainModeText.textContent;
        }
        
        // Sync next sunrise
        const mainNextSunrise = document.getElementById('next-sunrise');
        if (mainNextSunrise && this.elements.nextSunrise) {
            this.elements.nextSunrise.textContent = mainNextSunrise.textContent;
        }
        
        // Sync current timestamp
        const mainCurrentTimestamp = document.getElementById('current-timestamp');
        if (mainCurrentTimestamp && this.elements.currentTimestamp) {
            this.elements.currentTimestamp.textContent = mainCurrentTimestamp.textContent;
        }
        
        // Sync frame info
        const mainFrameInfo = document.getElementById('frame-info');
        if (mainFrameInfo && this.elements.frameInfo) {
            this.elements.frameInfo.textContent = mainFrameInfo.textContent;
        }
        
        // Sync update status
        const mainUpdateStatus = document.getElementById('update-status');
        if (mainUpdateStatus && this.elements.updateStatus) {
            this.elements.updateStatus.textContent = mainUpdateStatus.textContent;
        }
    }
    
    startStatusSync() {
        // Sync status bar data every second
        this.statusSyncInterval = setInterval(() => {
            if (this.isVisible) {
                this.syncStatusBarData();
            } else {
                clearInterval(this.statusSyncInterval);
            }
        }, 1000);
    }
    
    hide() {
        if (!this.isVisible) return;
        
        this.isVisible = false;
        
        // Stop animation
        this.stopAnimation();
        
        // Stop status sync
        if (this.statusSyncInterval) {
            clearInterval(this.statusSyncInterval);
            this.statusSyncInterval = null;
        }
        
        // Hide overlay with animation
        this.overlay.classList.remove('show');
        
        setTimeout(() => {
            this.overlay.style.display = 'none';
            
            // Clear image cache
            this.clearCache();
            
            // Notify callback
            if (this.options.onExit) {
                this.options.onExit();
            }
        }, 300);
        
        console.log('Hiding fullscreen viewer');
    }
    
    loadBandImages() {
        const lc = this.options.loopController;
        if (!lc || !lc.imageSets) {
            this.images = [];
            return;
        }

        const cellId = this.currentCellId;
        const imageSet = lc.imageSets[cellId];
        const isCycle = imageSet && imageSet.type === 'cycle';

        // Pick the right frame list: a cycling cell uses its currently-visible
        // band; a static cell uses its own array.
        let frameList = [];
        if (isCycle) {
            const band = this.currentBand && imageSet.images[this.currentBand]
                ? this.currentBand
                : Object.keys(imageSet.images || {})[0];
            this.currentBand = band;
            frameList = (band && imageSet.images[band]) || [];
        } else if (imageSet && !imageSet.type) {
            frameList = imageSet;
        }

        // Use the full-res image for fullscreen (the grid uses a downscaled variant).
        this.images = frameList.map((meta, i) => ({
            src: (meta && (meta.fullUrl || meta.url)) || '',
            timestamp: (meta && meta.localTime) || `Frame ${i + 1}`
        }));

        // Keep the current frame in range.
        if (this.currentFrame >= this.images.length) {
            this.currentFrame = 0;
        }

        // Preload the full-res frames through the shared cache so playback is
        // smooth instead of stalling while each large frame downloads.
        const im = window.app && window.app.gridManager && window.app.gridManager.imageManager;
        if (im && this.images.length) {
            const urls = this.images.map(img => img.src).filter(Boolean);
            if (urls.length) im.batchPreload(urls).catch(() => {});
        }

        this.updateFrameInfo();

        if (this.images.length > 0) {
            this.displayFrame(this.currentFrame);
        }
    }
    
    startAnimation() {
        if (!this.isPlaying) return;
        
        this.lastFrameTime = performance.now();
        this.animate();
    }
    
    stopAnimation() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
    }
    
    animate() {
        if (!this.isPlaying || !this.isVisible || this.images.length === 0) return;

        const now = performance.now();
        const elapsed = now - this.lastFrameTime;
        
        if (elapsed >= this.frameInterval) {
            // Advance frame
            this.currentFrame = (this.currentFrame + 1) % this.images.length;
            this.lastFrameTime = now - (elapsed % this.frameInterval);
            
            // Display frame
            this.displayFrame(this.currentFrame);
            
            // Update progress tracking
            this.updateProgressTracking();
        }
        
        this.animationId = requestAnimationFrame(() => this.animate());
    }
    
    displayFrame(frameIndex) {
        if (frameIndex >= 0 && frameIndex < this.images.length) {
            const image = this.images[frameIndex];

            if (image && this.elements.image) {
                // Only swap the image if this frame actually has one; on a
                // timeline gap (empty src) keep the previous frame on screen.
                if (image.src) {
                    this.elements.image.src = image.src;
                }

                // Prefer the authoritative master-timeline label so the
                // timestamp matches the rest of the app.
                let label = image.timestamp;
                const masterLocal = window.app && window.app.gridTimestampsLocal;
                if (masterLocal && masterLocal[frameIndex]) {
                    label = masterLocal[frameIndex];
                }
                if (this.elements.currentTimestamp && label) {
                    this.elements.currentTimestamp.textContent = label;
                }

                this.updateFrameInfo();
                this.updateProgressDisplay();
            }
        }
    }
    
    updateFrameInfo() {
        if (this.elements.frameInfo) {
            this.elements.frameInfo.textContent = 
                `Frame: ${this.currentFrame + 1}/${this.images.length}`;
        }
    }
    
    togglePlayPause() {
        this.isPlaying = !this.isPlaying;
        this.updatePlayPauseButton();
        
        // Sync play/pause state to main app
        const mainPlayPause = document.getElementById('play-pause-btn');
        if (mainPlayPause) {
            if (this.isPlaying) {
                mainPlayPause.classList.add('active');
                const mainText = document.getElementById('play-pause-text');
                if (mainText) mainText.textContent = 'Pause';
            } else {
                mainPlayPause.classList.remove('active');
                const mainText = document.getElementById('play-pause-text');
                if (mainText) mainText.textContent = 'Play';
            }
            
            // Trigger click event on main element to sync with loop controller
            mainPlayPause.dispatchEvent(new Event('click', { bubbles: true }));
        }
        
        if (this.isPlaying) {
            this.startAnimation();
        } else {
            this.stopAnimation();
        }
    }
    
    async handleTimeChange(hours) {
        console.log(`Fullscreen time changed to: ${hours} hours`);

        // Keep the main selector in sync (no event dispatch — we drive main directly).
        const mainTime = document.getElementById('time-period');
        if (mainTime) mainTime.value = String(hours);

        // Drive the main change and WAIT for the image sets to actually update
        // before rebuilding our view, otherwise we'd reload from the old period.
        if (window.app && typeof window.app.onTimeChange === 'function') {
            await window.app.onTimeChange(hours);
        }

        this.reloadFromMain();
    }

    async handleZoomChange(zoom) {
        console.log(`Fullscreen zoom changed to: ${zoom}`);

        // Keep the main selector in sync (no event dispatch — we drive main directly).
        const mainZoom = document.getElementById('zoom-level');
        if (mainZoom) mainZoom.value = zoom;

        // Drive the main zoom change and WAIT for it to finish updating the image
        // sets. Rebuilding immediately would read the PREVIOUS zoom (one-change lag).
        if (window.app && typeof window.app.onZoomChange === 'function') {
            await window.app.onZoomChange(zoom);
        }

        this.reloadFromMain();
    }

    // Rebuild the fullscreen view from the main app's now-current image sets,
    // continuing from the same frame and re-resolving the cell's current band.
    reloadFromMain() {
        if (window.app && window.app.loopController) {
            this.currentFrame = window.app.loopController.getCurrentFrame() || 0;
        }
        this.currentBand = this.resolveBand(this.currentCellId);

        this.loadBandImages();
        this.updateProgressTracking();

        if (this.isPlaying) {
            this.stopAnimation();
            this.startAnimation();
        }
    }
    
    syncToMainApp(elementId, value) {
        // Sync changes back to main application
        const mainElement = document.getElementById(elementId);
        if (mainElement) {
            if (mainElement.tagName === 'SELECT') {
                mainElement.value = value;
                // Trigger change event on main element
                mainElement.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }
    }
    
    handleKeyPress(event) {
        if (!this.isVisible) return;
        
        switch(event.key) {
            case 'Escape':
                event.preventDefault();
                this.hide();
                break;
                
            case ' ':
            case 'k':
                event.preventDefault();
                this.togglePlayPause();
                break;
                
            case 'ArrowRight':
                event.preventDefault();
                this.nextFrame();
                break;
                
            case 'ArrowLeft':
                event.preventDefault();
                this.previousFrame();
                break;
                
            case 'f':
                event.preventDefault();
                this.toggleBrowserFullscreen();
                break;
        }
    }
    
    nextFrame() {
        this.currentFrame = (this.currentFrame + 1) % this.images.length;
        this.displayFrame(this.currentFrame);
        this.updateProgressTracking();
        
        // Pause if playing
        if (this.isPlaying) {
            this.togglePlayPause();
        }
    }
    
    previousFrame() {
        this.currentFrame = (this.currentFrame - 1 + this.images.length) % this.images.length;
        this.displayFrame(this.currentFrame);
        this.updateProgressTracking();
        
        // Pause if playing
        if (this.isPlaying) {
            this.togglePlayPause();
        }
    }
    
    toggleBrowserFullscreen() {
        if (!document.fullscreenElement) {
            this.overlay.requestFullscreen().catch(err => {
                console.error(`Error attempting to enable fullscreen: ${err.message}`);
            });
        } else {
            document.exitFullscreen();
        }
    }
    
    clearCache() {
        this.imageCache.clear();
        this.images = [];
    }
    
    destroy() {
        // Remove event listeners
        this.stopAnimation();
        
        // Remove overlay
        if (this.overlay && this.overlay.parentNode) {
            this.overlay.parentNode.removeChild(this.overlay);
        }
        
        // Clear cache
        this.clearCache();
    }
    
    updatePlayPauseButton() {
        if (this.elements.playPauseBtn && this.elements.playPauseText) {
            if (this.isPlaying) {
                this.elements.playPauseBtn.classList.add('active');
                this.elements.playPauseText.textContent = 'Pause';
            } else {
                this.elements.playPauseBtn.classList.remove('active');
                this.elements.playPauseText.textContent = 'Play';
            }
        }
    }
    
    handleProgressSliderChange(value) {
        // Slider is frame-based (1..totalFrames), matching the main scrubber.
        this.currentFrame = Math.max(0, Math.min(value - 1, this.images.length - 1));
        this.displayFrame(this.currentFrame);
        
        // Pause if playing
        if (this.isPlaying) {
            this.togglePlayPause();
        }
        
        // Update progress display
        this.updateProgressDisplay();
    }
    
    updateProgressDisplay() {
        if (this.elements.sliderProgress && this.images.length > 0) {
            const progress = (this.currentFrame / (this.images.length - 1)) * 100;
            this.elements.sliderProgress.style.width = `${progress}%`;
        }
    }
    
    resetToFirstFrame() {
        this.currentFrame = 0;
        this.displayFrame(this.currentFrame);
        
        // Update progress slider
        if (this.elements.progressSlider) {
            this.elements.progressSlider.value = 1;
        }
        this.updateProgressDisplay();
        
        // Restart animation if it was playing
        if (this.isPlaying) {
            this.stopAnimation();
            this.startAnimation();
        }
    }
    
    handleFpsChange(fps) {
        this.options.frameRate = fps;
        this.frameInterval = 1000 / fps;
        
        // Update active button in fullscreen
        this.setActiveFpsButton(fps);
        
        // Sync to main app FPS buttons
        const mainFpsButtons = document.querySelectorAll('.fps-btn');
        if (mainFpsButtons) {
            mainFpsButtons.forEach(btn => {
                btn.classList.remove('active');
                if (parseInt(btn.dataset.fps) === fps) {
                    btn.classList.add('active');
                    // Trigger click event to sync with main app
                    btn.dispatchEvent(new Event('click', { bubbles: true }));
                }
            });
        }
        
        // Disable auto FPS when manually selecting
        if (this.elements.fpsAutoBtn) {
            this.elements.fpsAutoBtn.classList.remove('active');
        }
        
        // Disable main auto FPS
        const mainFpsAuto = document.getElementById('fps-auto-btn');
        if (mainFpsAuto) {
            mainFpsAuto.classList.remove('active');
        }
        
        // Restart animation with new FPS
        if (this.isPlaying) {
            this.stopAnimation();
            this.startAnimation();
        }
    }
    
    setActiveFpsButton(fps) {
        if (this.elements.fpsButtons) {
            this.elements.fpsButtons.forEach(btn => {
                btn.classList.remove('active');
                if (parseInt(btn.dataset.fps) === fps) {
                    btn.classList.add('active');
                }
            });
        }
    }
    
    toggleFpsAuto() {
        const isActive = this.elements.fpsAutoBtn.classList.contains('active');
        
        if (isActive) {
            this.elements.fpsAutoBtn.classList.remove('active');
            
            // Sync to main app
            const mainFpsAuto = document.getElementById('fps-auto-btn');
            if (mainFpsAuto) {
                mainFpsAuto.classList.remove('active');
            }
        } else {
            this.elements.fpsAutoBtn.classList.add('active');
            
            // Sync to main app
            const mainFpsAuto = document.getElementById('fps-auto-btn');
            if (mainFpsAuto) {
                mainFpsAuto.classList.add('active');
                // Trigger click event
                mainFpsAuto.dispatchEvent(new Event('click', { bubbles: true }));
            }
            
            // Auto-adjust FPS based on time period (options: 10, 5, 1)
            const timePeriodValue = parseInt(this.elements.timePeriod.value);
            let autoFps = 5; // default

            if (timePeriodValue <= 6) {
                autoFps = 10; // Higher FPS for shorter periods
            } else if (timePeriodValue <= 24) {
                autoFps = 5;  // Medium FPS
            } else {
                autoFps = 1;  // Lower FPS for longer periods
            }
            
            this.handleFpsChange(autoFps);
            this.elements.fpsAutoBtn.classList.add('active');
        }
    }
    
    updateProgressTracking() {
        // Frame-based slider position (1..totalFrames), matching the main scrubber.
        if (this.elements.progressSlider && this.images.length > 0) {
            this.elements.progressSlider.max = this.images.length;
            this.elements.progressSlider.value = this.currentFrame + 1;
        }

        // Update progress display
        this.updateProgressDisplay();
    }
}

// Make FullscreenViewer globally available
window.FullscreenViewer = FullscreenViewer;