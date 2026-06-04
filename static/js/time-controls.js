/**
 * Time Controls Module for Satellite Weather Display
 * Manages time period selection, zoom controls, and playback functionality
 */

class TimeControls {
    constructor(options = {}) {
        this.options = {
            config: null,
            onTimeChange: null,
            onZoomChange: null,
            onPlayPause: null,
            onReset: null,
            onFPSChange: null,
            ...options
        };
        
        // Current state
        this.currentHours = 24; // Default 24 hours
        this.currentZoom = 'Zoom1'; // Default close zoom
        this.currentFPS = 10; // Default FPS (changed to 10 to match middle button)
        this.autoFPS = true; // Auto-adjust FPS enabled by default
        this.isPlaying = true;
        this.isChangingZoom = false;
        
        // DOM elements
        this.elements = {
            timePeriod: null,
            zoomLevel: null,
            playPauseBtn: null,
            playPauseText: null,
            resetBtn: null,
            fpsButtons: null,
            fpsAutoBtn: null,
            frameInfo: null,
            updateStatus: null
        };
        
        // Initialize
        this.init();
    }
    
    init() {
        // Get DOM elements
        this.elements.timePeriod = document.getElementById('time-period');
        this.elements.zoomLevel = document.getElementById('zoom-level');
        this.elements.playPauseBtn = document.getElementById('play-pause-btn');
        this.elements.playPauseText = document.getElementById('play-pause-text');
        this.elements.resetBtn = document.getElementById('reset-btn');
        this.elements.fpsButtons = document.querySelectorAll('.fps-btn');
        this.elements.fpsAutoBtn = document.getElementById('fps-auto-btn');
        this.elements.frameInfo = document.getElementById('frame-info');
        this.elements.updateStatus = document.getElementById('update-status');
        
        // Populate time period options if config is available
        if (this.options.config && this.options.config.time_periods) {
            this.populateTimePeriods();
        }
        
        // Set initial values
        this.setInitialValues();
        
        // Initialize FPS display and auto setting
        this.initializeFPS();
        
        // Set auto button state
        if (this.elements.fpsAutoBtn) {
            this.elements.fpsAutoBtn.classList.toggle('active', this.autoFPS);
        }
        
        // Attach event listeners
        this.attachEventListeners();
        
        // Update UI state
        this.updatePlayPauseButton();
    }
    
    populateTimePeriods() {
        if (!this.elements.timePeriod) return;
        
        // Clear existing options
        this.elements.timePeriod.innerHTML = '';
        
        // Add options from config
        this.options.config.time_periods.forEach(period => {
            const option = document.createElement('option');
            option.value = period.hours;
            option.textContent = period.label;
            
            // Set default selection for 24 hours
            if (period.hours === 24) {
                option.selected = true;
            }
            
            this.elements.timePeriod.appendChild(option);
        });
    }
    
    setInitialValues() {
        // Set time period
        if (this.elements.timePeriod) {
            this.currentHours = parseInt(this.elements.timePeriod.value) || 24;
        }
        
        // Set zoom level
        if (this.elements.zoomLevel) {
            this.currentZoom = this.elements.zoomLevel.value || 'Zoom1';
        }
        
        // Set FPS
        if (this.elements.fpsButtons) {
            // Find the initially active button and set current FPS
            const activeButton = document.querySelector('.fps-btn.active');
            if (activeButton) {
                this.currentFPS = parseInt(activeButton.dataset.fps) || 10;
            }
        }
        
        // Set auto FPS
        if (this.elements.fpsAutoBtn) {
            this.autoFPS = this.elements.fpsAutoBtn.classList.contains('active');
        }
    }
    
    attachEventListeners() {
        // Time period change
        if (this.elements.timePeriod) {
            this.elements.timePeriod.addEventListener('change', (e) => {
                this.handleTimeChange(e);
            });
        }
        
        // Zoom level change
        if (this.elements.zoomLevel) {
            this.elements.zoomLevel.addEventListener('change', (e) => {
                this.handleZoomChange(e);
            });
        }
        
        // Play/Pause button
        if (this.elements.playPauseBtn) {
            this.elements.playPauseBtn.addEventListener('click', () => {
                this.handlePlayPause();
            });
        }
        
        // Reset button
        if (this.elements.resetBtn) {
            this.elements.resetBtn.addEventListener('click', () => {
                this.handleReset();
            });
        }
        
        // FPS buttons
        if (this.elements.fpsButtons) {
            this.elements.fpsButtons.forEach(button => {
                button.addEventListener('click', () => {
                    this.handleFPSChange(button);
                });
            });
        }
        
        // FPS auto button
        if (this.elements.fpsAutoBtn) {
            this.elements.fpsAutoBtn.addEventListener('click', () => {
                this.handleFPSAutoToggle();
            });
        }
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            this.handleKeyPress(e);
        });
    }
    
    handleTimeChange(event) {
        if (!event || !event.target) return;
        
        const hours = parseInt(event.target.value);
        this.currentHours = hours;
        
        // Auto-adjust FPS if enabled
        if (this.autoFPS && this.options.config && this.options.config.fps_config) {
            const defaultFPS = this.options.config.fps_config.default_fps[hours];
            if (defaultFPS) {
                this.setFPS(defaultFPS);
            }
        }
        
        this.updateFrameCount(hours);
        
        console.log(`TimeControls: Changed time period to ${hours} hours`);
        
        if (this.options.onTimeChange) {
            this.options.onTimeChange(hours);
        }
    }
    
    handleZoomChange(event) {
        if (!event || !event.target) return;

        const zoom = event.target.value;

        // Ignore only if it's genuinely the same as what's selected.
        if (zoom === this.currentZoom) {
            return;
        }

        console.log(`TimeControls: Zoom change from ${this.currentZoom} to ${zoom}`);

        // Keep the selector responsive (no disabling). main.onZoomChange handles
        // ordering via a latest-wins queue, so rapid changes are safe and the
        // dropdown always reflects the user's latest pick immediately.
        this.currentZoom = zoom;
        this.updateZoomLabel(zoom);

        if (this.options.onZoomChange) {
            this.options.onZoomChange(zoom);
        }
    }
    
    handlePlayPause() {
        this.isPlaying = !this.isPlaying;
        
        console.log(`Playback ${this.isPlaying ? 'resumed' : 'paused'}`);
        
        // Update button state
        this.updatePlayPauseButton();
        
        // Notify callback
        if (this.options.onPlayPause) {
            this.options.onPlayPause(this.isPlaying);
        }
    }
    
    handleReset() {
        console.log('Resetting to first frame');
        
        // Reset to beginning
        if (this.options.onReset) {
            this.options.onReset();
        }
        
        // Ensure playing
        if (!this.isPlaying) {
            this.isPlaying = true;
            this.updatePlayPauseButton();
            
            if (this.options.onPlayPause) {
                this.options.onPlayPause(true);
            }
        }
    }
    
    handleFPSChange(button) {
        if (!button) return;
        
        // Get FPS from data attribute
        const fps = parseInt(button.dataset.fps);
        if (!fps) return;
        
        this.currentFPS = fps;
        
        // Update button states
        this.updateFPSButtonStates(fps);
        
        console.log(`TimeControls: Changed FPS to ${fps}`);
        
        if (this.options.onFPSChange) {
            this.options.onFPSChange(fps);
        }
    }
    
    updateFPSButtonStates(fps) {
        if (!this.elements.fpsButtons) return;
        
        // Remove active class from all buttons
        this.elements.fpsButtons.forEach(button => {
            button.classList.remove('active');
        });
        
        // Add active class to the selected FPS button
        this.elements.fpsButtons.forEach(button => {
            if (parseInt(button.dataset.fps) === fps) {
                button.classList.add('active');
            }
        });
    }
    
    handleFPSAutoToggle() {
        if (!this.elements.fpsAutoBtn) return;
        
        this.autoFPS = !this.autoFPS;
        this.elements.fpsAutoBtn.classList.toggle('active', this.autoFPS);
        
        // If enabling auto FPS, set it to the default for current time period
        if (this.autoFPS && this.options.config && this.options.config.fps_config) {
            const defaultFPS = this.options.config.fps_config.default_fps[this.currentHours];
            if (defaultFPS) {
                this.setFPS(defaultFPS);
            }
        }
        
        console.log(`TimeControls: Auto FPS ${this.autoFPS ? 'enabled' : 'disabled'}`);
    }
    
    handleKeyPress(event) {
        // Don't handle if user is typing in an input
        if (event.target.tagName === 'INPUT' || event.target.tagName === 'SELECT') {
            return;
        }
        
        switch(event.key) {
            case ' ':
            case 'k': // YouTube-style pause
                event.preventDefault();
                this.handlePlayPause();
                break;
                
            case 'r':
                event.preventDefault();
                this.handleReset();
                break;
                
            case '1':
            case '2':
            case '3':
                // Quick zoom level switching
                event.preventDefault();
                const zoomLevel = `Zoom${event.key}`;
                if (this.elements.zoomLevel) {
                    this.elements.zoomLevel.value = zoomLevel;
                    this.handleZoomChange({ target: { value: zoomLevel } });
                }
                break;
                
            case 'ArrowUp':
                // Increase time period
                event.preventDefault();
                this.changeTimePeriod(1);
                break;
                
            case 'ArrowDown':
                // Decrease time period
                event.preventDefault();
                this.changeTimePeriod(-1);
                break;
        }
    }
    
    changeTimePeriod(direction) {
        if (!this.elements.timePeriod) return;
        
        const options = this.elements.timePeriod.options;
        let currentIndex = this.elements.timePeriod.selectedIndex;
        let newIndex = currentIndex + direction;
        
        // Clamp to valid range
        newIndex = Math.max(0, Math.min(options.length - 1, newIndex));
        
        if (newIndex !== currentIndex) {
            this.elements.timePeriod.selectedIndex = newIndex;
            this.handleTimeChange({ target: this.elements.timePeriod });
        }
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
    
    updateFrameCount(hours) {
        if (!this.options.config) return;
        
        // Find the time period config
        const period = this.options.config.time_periods.find(p => p.hours === hours);
        if (period && this.elements.frameInfo) {
            // This will be updated by the main app with actual frame numbers
            const totalFrames = period.frames;
            console.log(`Total frames for ${hours} hours: ${totalFrames}`);
        }
    }
    
    updateZoomLabel(zoom) {
        // Get zoom configuration if available
        if (this.options.config && this.options.config.zoom_levels) {
            const zoomConfig = this.options.config.zoom_levels[zoom];
            if (zoomConfig) {
                console.log(`Zoom: ${zoomConfig.name}`);
            }
        }
    }
    
    // Public methods for external control
    
    setTimePeriod(hours) {
        if (this.elements.timePeriod) {
            this.elements.timePeriod.value = hours;
            this.currentHours = hours;
        }
    }
    
    setZoomLevel(zoom) {
        console.log(`TimeControls: setZoomLevel called with ${zoom}, current: ${this.currentZoom}`);
        
        if (this.elements.zoomLevel) {
            // Only update if different and not currently changing
            if (zoom !== this.currentZoom || this.isChangingZoom) {
                console.log(`TimeControls: Setting zoom level to ${zoom}`);
                this.elements.zoomLevel.value = zoom;
                this.currentZoom = zoom;
                
                // Force the UI to reflect the zoom level
                this.updateZoomLabel(zoom);
            }
            
            // Always reset the changing state when manually setting
            this.isChangingZoom = false;
            
            // Ensure the selector is enabled
            if (this.elements.zoomLevel.disabled) {
                this.elements.zoomLevel.disabled = false;
                this.elements.zoomLevel.style.opacity = '1';
            }
        }
    }
    
    setPlayState(playing) {
        this.isPlaying = playing;
        this.updatePlayPauseButton();
    }
    
    updateFrameInfo(current, total) {
        if (this.elements.frameInfo) {
            this.elements.frameInfo.textContent = `Frame: ${current}/${total}`;
        }
    }
    
    updateLastUpdateTime() {
        if (this.elements.updateStatus) {
            const now = new Date();
            const timeStr = now.toLocaleTimeString('en-US', { 
                timeZone: 'America/Port_of_Spain',
                hour: '2-digit',
                minute: '2-digit'
            });
            this.elements.updateStatus.textContent = `Last Update: ${timeStr}`;
        }
    }
    
    enableControls() {
        // No need to call showLoadingState as it's removed
    }
    
    disableControls() {
        // No need to call showLoadingState as it's removed
    }
    
    getCurrentSettings() {
        return {
            hours: this.currentHours,
            zoom: this.currentZoom,
            isPlaying: this.isPlaying,
            fps: this.currentFPS,
            autoFPS: this.autoFPS
        };
    }
    
    showTooltip(message, duration = 3000) {
        // Create tooltip element
        const tooltip = document.createElement('div');
        tooltip.className = 'control-tooltip slide-up';
        tooltip.textContent = message;
        tooltip.style.cssText = `
            position: fixed;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            background-color: rgba(0, 0, 0, 0.9);
            color: #fff;
            padding: 10px 20px;
            border-radius: 6px;
            font-size: 14px;
            z-index: 1000;
            pointer-events: none;
        `;
        
        document.body.appendChild(tooltip);
        
        // Remove after duration
        setTimeout(() => {
            tooltip.style.opacity = '0';
            setTimeout(() => {
                document.body.removeChild(tooltip);
            }, 300);
        }, duration);
    }
    
    destroy() {
        // Remove event listeners
        if (this.elements.timePeriod) {
            this.elements.timePeriod.removeEventListener('change', this.handleTimeChange);
        }
        
        if (this.elements.zoomLevel) {
            this.elements.zoomLevel.removeEventListener('change', this.handleZoomChange);
        }
        
        if (this.elements.playPauseBtn) {
            this.elements.playPauseBtn.removeEventListener('click', this.handlePlayPause);
        }
        
        if (this.elements.resetBtn) {
            this.elements.resetBtn.removeEventListener('click', this.handleReset);
        }
        
        if (this.elements.fpsButtons) {
            this.elements.fpsButtons.forEach(button => {
                button.removeEventListener('click', this.handleFPSChange);
            });
        }
        
        if (this.elements.fpsAutoBtn) {
            this.elements.fpsAutoBtn.removeEventListener('click', this.handleFPSAutoToggle);
        }
    }
    
    resetZoomChangeState() {
        this.isChangingZoom = false;
        // No need to call showLoadingState as it's removed
    }
    
    setFPS(fps) {
        if (!this.elements.fpsButtons) return;
        
        // Validate FPS - only allow 10, 5, 1
        const validFPS = [10, 5, 1];
        if (!validFPS.includes(fps)) {
            // Find closest valid FPS
            fps = validFPS.reduce((prev, curr) => 
                Math.abs(curr - fps) < Math.abs(prev - fps) ? curr : prev
            );
        }
        
        this.currentFPS = fps;
        this.updateFPSButtonStates(fps);
        
        console.log(`TimeControls: Set FPS to ${fps}`);
        
        if (this.options.onFPSChange) {
            this.options.onFPSChange(fps);
        }
    }
    
    initializeFPS() {
        // Initialize FPS based on current time period if auto is enabled
        if (this.autoFPS && this.options.config && this.options.config.fps_config) {
            const defaultFPS = this.options.config.fps_config.default_fps[this.currentHours];
            if (defaultFPS) {
                this.setFPS(defaultFPS);
                return;
            }
        }
        
        // Update display with current FPS
        this.updateFPSDisplay(this.currentFPS);
    }
    
    updateFPSDisplay(fps) {
        this.updateFPSButtonStates(fps);
    }
}