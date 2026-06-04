/**
 * Enhanced Grid Manager for Satellite Weather Display
 * Manages 4-panel grid layout with enhanced image transitions
 */

class GridManager {
    constructor(options = {}) {
        this.options = {
            config: null,
            loopController: null,
            onCellClick: null,
            cycleDuration: 30000, // 30 seconds per band in cycle
            transitionDuration: 500, // 500ms fade transition
            loopsPerBand: 2, // Number of loops to play before switching bands
            ...options
        };
        
        this.currentMode = 'day'; // day or night
        this.gridConfig = null;
        this.currentCycleBands = {};
        this.cycleLoopCounts = {}; // Track how many loops have played for each cell
        this.isPaused = false;
        
        // Enhanced image manager
        this.imageManager = new EnhancedImageManager({
            transitionDuration: this.options.transitionDuration
        });
        
        // Global progress indicator
        this.progressIndicator = new GlobalProgressIndicator();
        
        // Cell configurations
        this.cells = {
            'top-left': { element: null, band: null },
            'top-right': { element: null, band: null, isCycle: false },
            'bottom-left': { element: null, band: null },
            'bottom-right': { element: null, band: null, isCycle: false }
        };
        
        // Performance monitoring
        this.performanceStats = {
            frameCount: 0,
            lastFrameTime: 0,
            fps: 0
        };
        
        // Initialize
        this.init();
    }
    
    init() {
        // Get cell elements
        for (const cellId in this.cells) {
            this.cells[cellId].element = document.getElementById(`cell-${cellId}`);
            
            // Add click handler
            if (this.cells[cellId].element) {
                this.cells[cellId].element.addEventListener('click', () => {
                    if (this.options.onCellClick) {
                        this.options.onCellClick(cellId);
                    }
                });
            }
        }
        
        // Set initial mode
        this.setMode(this.currentMode);
        
        // Start performance monitoring
        this.startPerformanceMonitoring();
    }
    
    setMode(mode) {
        this.currentMode = mode;
        
        // Get grid configuration for current mode
        if (this.options.config) {
            this.gridConfig = this.options.config.grid_config[`${mode}_mode`];
            this.updateGridConfiguration();
        }
    }
    
    updateGridConfiguration() {
        if (!this.gridConfig) return;
        
        // Stop existing cycles
        this.stopAllCycles();
        
        // Update cell configurations based on mode
        if (this.currentMode === 'day') {
            // Day mode configuration
            this.cells['top-left'].band = 'GeoColor';
            this.cells['top-left'].isCycle = false;
            
            // Top-right cycles in day mode
            this.cells['top-right'].band = this.gridConfig.top_right_cycle;
            this.cells['top-right'].isCycle = true;
            
            this.cells['bottom-left'].band = 'Band_2';
            this.cells['bottom-left'].isCycle = false;
            
            this.cells['bottom-right'].band = 'Band_13';
            this.cells['bottom-right'].isCycle = false;
            
        } else {
            // Night mode configuration
            this.cells['top-left'].band = 'GeoColor';
            this.cells['top-left'].isCycle = false;
            
            // Top-right cycles in night mode
            this.cells['top-right'].band = this.gridConfig.top_right_cycle;
            this.cells['top-right'].isCycle = true;
            
            this.cells['bottom-left'].band = 'Band_13';
            this.cells['bottom-left'].isCycle = false;
            
            this.cells['bottom-right'].band = 'Sandwich_RGB';
            this.cells['bottom-right'].isCycle = false;
        }
        
        // Update labels
        this.updateCellLabels();
        
        // Start cycles for cells that need them
        this.startCycles();
    }
    
    updateCellLabels() {
        // Update labels for all cells based on current configuration
        for (const [cellId, cell] of Object.entries(this.cells)) {
            const element = cell.element;
            if (!element) continue;
            
            const label = element.querySelector('.grid-label');
            if (!label) continue;
            
            if (cell.isCycle && Array.isArray(cell.band)) {
                // For cycling cells, show the first band initially
                const currentBand = this.currentCycleBands[cellId] || cell.band[0];
                const bandInfo = this.getBandLabel(currentBand);
                
                label.setAttribute('data-band-name', bandInfo);
                
                // Show just the band name
                label.innerHTML = bandInfo;
            } else {
                // For static cells, just show the band name
                const bandInfo = this.getBandLabel(cell.band);
                label.setAttribute('data-band-name', bandInfo);
                label.innerHTML = bandInfo;
            }
        }
    }
    
    getBandLabel(bandKey) {
        // Map band keys to display labels
        const labels = {
            'GeoColor': 'GeoColor',
            'Band_2': 'Band 2 (Red-Visible)',
            'Band_13': 'Band 13 (Clean Longwave IR)',
            'Band_10': 'Band 10 (Lower-level Water Vapor)',
            'Band_9': 'Band 9 (Mid-Level Water Vapor)',
            'Band_8': 'Band 8 (Upper-Level Water Vapor)',
            'Sandwich_RGB': 'Sandwich RGB'
        };
        
        return labels[bandKey] || bandKey;
    }
    
    startCycles() {
        if (this.isPaused) return;
        
        for (const [cellId, cell] of Object.entries(this.cells)) {
            if (cell.isCycle && Array.isArray(cell.band)) {
                this.startCycleForCell(cellId, cell.band);
            }
        }
    }
    
    startCycleForCell(cellId, cycleBands) {
        // Initialize current band if not set
        if (!this.currentCycleBands[cellId]) {
            this.currentCycleBands[cellId] = cycleBands[0];
            this.updateCellDisplay(cellId, cycleBands[0]);
        }
        
        // Initialize loop count for this cell
        this.cycleLoopCounts[cellId] = {
            currentBandIndex: 0,
            loopsCompleted: 0,
            totalFrames: 0,
            lastFrame: -1
        };
        
        // Get the total frames from loop controller if available
        if (this.options.loopController) {
            this.cycleLoopCounts[cellId].totalFrames = this.options.loopController.getTotalFrames();
        }
        
        console.log(`Starting cycle for ${cellId} with ${cycleBands.length} bands, ${this.options.loopsPerBand} loops per band`);
    }
    
    async transitionCellToBand(cellId, newBand) {
        const cell = this.cells[cellId];
        if (!cell.element) return;
        
        // Update current band
        this.currentCycleBands[cellId] = newBand;
        
        // Get current frame from loop controller
        const currentFrame = this.options.loopController ? 
                            this.options.loopController.getCurrentFrame() : 0;
        
        // Update label to show the new band name
        this.updateCellLabel(cellId, newBand, true);
        
        // Get image URL for the new band
        const imageUrl = this.getImageUrlForBand(cellId, newBand, currentFrame);
        
        if (imageUrl) {
            // Use enhanced image manager for smooth transition
            await this.imageManager.updateCellImage(cellId, imageUrl);
        }
    }
    
    updateCellLabel(cellId, bandKey, isCycling = false) {
        const cell = this.cells[cellId];
        if (!cell.element) return;
        
        const label = cell.element.querySelector('.grid-label');
        if (label) {
            const bandInfo = this.getBandLabel(bandKey);
            
            // Store the original band name for future reference
            label.setAttribute('data-band-name', bandInfo);
            
            // Simply display the band name without any timestamps or cycling info
            label.innerHTML = bandInfo;
        }
    }
    
    updateCellTimestamp(cellId, bandKey, frameIndex) {
        const cell = this.cells[cellId];
        if (!cell.element || !this.options.loopController) return;
        
        const label = cell.element.querySelector('.grid-label');
        if (!label) return;
        
        // Get the band name only (no timestamp)
        const bandInfo = this.getBandLabel(bandKey);
        
        // Simply set the band name without timestamp to prevent flashing
        label.innerHTML = bandInfo;
    }
    
    async updateCellDisplay(cellId, bandKey) {
        const cell = this.cells[cellId];
        if (!cell.element || !this.options.loopController) return;
        
        // Get current frame from loop controller
        const currentFrame = this.options.loopController.getCurrentFrame();
        
        // Get image URL
        const imageUrl = this.getImageUrlForBand(cellId, bandKey, currentFrame);
        
        if (imageUrl) {
            // Use enhanced image manager for smooth updates
            await this.imageManager.updateCellImage(cellId, imageUrl);
        }
    }
    
    async updateCellDisplayImmediate(cellId, bandKey) {
        const cell = this.cells[cellId];
        if (!cell.element || !this.options.loopController) return;
        
        // Get current frame from loop controller
        const currentFrame = this.options.loopController.getCurrentFrame();
        
        // IMMEDIATE: Get image URL directly from image sets for instant display
        const imageUrl = this.getImageUrlDirectFromSets(cellId, bandKey, currentFrame);
        
        if (imageUrl) {
            // Use enhanced image manager for immediate update
            await this.imageManager.updateCellImageImmediate(cellId, imageUrl);
        }
        // No URL = timeline gap for this band at this frame: carry forward the
        // last good image (do nothing) so panels stay time-aligned.
    }

    getImageUrlDirectFromSets(cellId, bandKey, frameIndex) {
        if (!this.options.loopController || !this.options.loopController.imageSets) return null;

        const imageSets = this.options.loopController.imageSets;
        const cell = this.cells[cellId];

        if (cell.isCycle) {
            // For cycle cells, get image for specific band from cycle image sets
            if (imageSets[cellId] && imageSets[cellId].type === 'cycle') {
                const bandImages = imageSets[cellId].images[bandKey];
                const entry = bandImages && frameIndex < bandImages.length ? bandImages[frameIndex] : null;
                if (entry && entry.url) return entry.url;
            }
        } else {
            // For static cells, get image directly from static image sets
            if (imageSets[cellId] && frameIndex < imageSets[cellId].length) {
                const entry = imageSets[cellId][frameIndex];
                if (entry && entry.url) return entry.url;
            }
        }

        return null;
    }

    getImageUrlForBand(cellId, bandKey, frameIndex) {
        if (!this.options.loopController) return null;

        const cell = this.cells[cellId];
        let entry = null;

        if (cell.isCycle) {
            entry = this.options.loopController.getCycleImageForCell(cellId, bandKey, frameIndex);
        } else {
            entry = this.options.loopController.getImageForCell(cellId, frameIndex);
        }

        // entry is null on a timeline gap -> return null so the caller carries
        // forward the previous frame instead of blanking the panel.
        return entry ? (entry.url || entry.src || null) : null;
    }
    
    async updateImages(gridImages, zoom, seamlessMode = false) {
        // Skip heavy operations if in seamless mode (zoom changes)
        if (seamlessMode) {
            console.log('GridManager: Seamless update mode - immediate display update');
            
            // For zoom changes, reinitialize the current cycle bands to ensure proper display
            for (const [cellId, cell] of Object.entries(this.cells)) {
                if (cell.isCycle && Array.isArray(cell.band)) {
                    // Reset to first band in cycle for zoom changes
                    this.currentCycleBands[cellId] = cell.band[0];
                    console.log(`GridManager: Reset ${cellId} cycle to ${cell.band[0]} for zoom change`);
                }
            }
            
            // IMMEDIATE: Update all cell displays right now - no waiting
            const updatePromises = [];
            for (const [cellId, cell] of Object.entries(this.cells)) {
                if (cell.isCycle) {
                    // Update the current band display
                    const currentBand = this.currentCycleBands[cellId];
                    if (currentBand) {
                        updatePromises.push(this.updateCellDisplayImmediate(cellId, currentBand));
                    }
                } else {
                    // Update static cell
                    updatePromises.push(this.updateCellDisplayImmediate(cellId, cell.band));
                }
            }
            
            // Wait for all immediate updates to complete
            await Promise.all(updatePromises);
            console.log('GridManager: All cells updated immediately for zoom change');
            return;
        }
        
        // Show global loading indicator for non-seamless updates
        this.progressIndicator.show();
        
        // Collect all image URLs for preloading
        const imagesToPreload = [];
        
        // Get current frame range for preloading
        const currentFrame = this.options.loopController ? 
                            this.options.loopController.getCurrentFrame() : 0;
        const preloadRange = 5; // frames ahead and behind
        
        for (let frame = Math.max(0, currentFrame - preloadRange); 
             frame <= currentFrame + preloadRange; frame++) {
            
            for (const [cellId, cell] of Object.entries(this.cells)) {
                if (cell.isCycle && Array.isArray(cell.band)) {
                    // For cycle cells, preload all bands
                    cell.band.forEach(bandKey => {
                        const imageUrl = this.getImageUrlForBand(cellId, bandKey, frame);
                        if (imageUrl && !imagesToPreload.includes(imageUrl)) {
                            imagesToPreload.push(imageUrl);
                        }
                    });
                } else {
                    // For static cells
                    const imageUrl = this.getImageUrlForBand(cellId, cell.band, frame);
                    if (imageUrl && !imagesToPreload.includes(imageUrl)) {
                        imagesToPreload.push(imageUrl);
                    }
                }
            }
        }
        
        // Batch preload images with progress tracking
        await this.imageManager.batchPreload(imagesToPreload, (progress) => {
            this.progressIndicator.updateProgress(progress);
        });
        
        // Update current frame display
        for (const [cellId, cell] of Object.entries(this.cells)) {
            if (cell.isCycle) {
                // Update the current band display
                const currentBand = this.currentCycleBands[cellId];
                if (currentBand) {
                    await this.updateCellDisplay(cellId, currentBand);
                }
            } else {
                // Update static cell
                await this.updateCellDisplay(cellId, cell.band);
            }
        }
    }
    
    stopAllCycles() {
        // Clear loop counters instead of timers
        this.cycleLoopCounts = {};
        this.currentCycleBands = {};
        
        console.log('All cycles stopped and loop counters cleared');
    }
    
    pauseCycles() {
        this.isPaused = true;
        console.log('Cycles paused - loop counting will continue but band switching is paused');
    }
    
    resumeCycles() {
        this.isPaused = false;
        console.log('Cycles resumed - band switching will resume on next loop completion');
    }
    
    async onFrameChange(frameIndex) {
        // Track loop completions for cycling cells
        this.onLoopFrameChange(frameIndex);
        
        // Update performance stats
        this.updatePerformanceStats();
        
        // Update all cells for the new frame ensuring synchronized display
        for (const [cellId, cell] of Object.entries(this.cells)) {
            if (cell.isCycle) {
                // For cycle cells, update with current band
                const currentBand = this.currentCycleBands[cellId];
                if (currentBand) {
                    // Use non-blocking update for smoother loop performance
                    this.updateCellDisplay(cellId, currentBand);
                }
            } else {
                // For static cells, update with cell band
                this.updateCellDisplay(cellId, cell.band);
            }
        }
    }
    
    updatePerformanceStats() {
        const now = performance.now();
        
        if (this.performanceStats.lastFrameTime > 0) {
            const frameDelta = now - this.performanceStats.lastFrameTime;
            this.performanceStats.fps = Math.round(1000 / frameDelta);
        }
        
        this.performanceStats.lastFrameTime = now;
        this.performanceStats.frameCount++;
    }
    
    startPerformanceMonitoring() {
        // Periodically optimize the cache (and log stats only in debug mode)
        setInterval(() => {
            const stats = this.imageManager.getLoadStats();
            if (window.APP_DEBUG) console.log('Image Manager Stats:', stats);

            // Optimize cache periodically
            if (stats.cacheSize > 150) {
                this.imageManager.optimizeCache(100);
            }
        }, 5000);
    }
    
    async retryImageLoad(cellId) {
        await this.imageManager.retryImageLoad(cellId);
    }
    
    getCurrentCycleBand(cellId) {
        return this.currentCycleBands[cellId] || null;
    }
    
    getCycleStatus() {
        const status = {};
        for (const [cellId, cell] of Object.entries(this.cells)) {
            if (cell.isCycle) {
                const loopData = this.cycleLoopCounts[cellId];
                status[cellId] = {
                    currentBand: this.currentCycleBands[cellId],
                    availableBands: cell.band,
                    currentBandIndex: loopData ? loopData.currentBandIndex : 0,
                    loopsCompleted: loopData ? loopData.loopsCompleted : 0,
                    loopsPerBand: this.options.loopsPerBand,
                    totalFrames: loopData ? loopData.totalFrames : 0,
                    isActive: !this.isPaused && !!loopData
                };
            }
        }
        return status;
    }
    
    getImageManagerStats() {
        return this.imageManager.getLoadStats();
    }
    
    destroy() {
        this.stopAllCycles();
        
        if (this.imageManager) {
            this.imageManager.destroy();
        }
        
        if (this.progressIndicator) {
            this.progressIndicator.hide();
        }
        
        this.cells = {};
        this.currentCycleBands = {};
    }
    
    onLoopFrameChange(frameIndex) {
        // Don't process cycling if paused
        if (this.isPaused) return;
        
        // Check cycling cells for loop completion
        for (const [cellId, cell] of Object.entries(this.cells)) {
            if (cell.isCycle && this.cycleLoopCounts[cellId]) {
                const loopData = this.cycleLoopCounts[cellId];
                
                // Update total frames if it has changed
                if (this.options.loopController) {
                    const currentTotalFrames = this.options.loopController.getTotalFrames();
                    if (currentTotalFrames !== loopData.totalFrames) {
                        loopData.totalFrames = currentTotalFrames;
                    }
                }
                
                // Check if we've completed a loop (went from last frame back to first)
                if (loopData.lastFrame !== -1 && frameIndex === 0 && loopData.lastFrame === loopData.totalFrames - 1) {
                    loopData.loopsCompleted++;
                    
                    console.log(`Loop completed for ${cellId}: ${loopData.loopsCompleted}/${this.options.loopsPerBand}`);
                    
                    // Check if we need to switch to next band
                    if (loopData.loopsCompleted >= this.options.loopsPerBand) {
                        this.switchToNextBand(cellId);
                    }
                }
                
                loopData.lastFrame = frameIndex;
            }
        }
    }
    
    switchToNextBand(cellId) {
        const cell = this.cells[cellId];
        if (!cell || !cell.isCycle || !Array.isArray(cell.band)) return;
        
        const loopData = this.cycleLoopCounts[cellId];
        if (!loopData) return;
        
        // Move to next band
        loopData.currentBandIndex = (loopData.currentBandIndex + 1) % cell.band.length;
        loopData.loopsCompleted = 0; // Reset loop counter
        
        const nextBand = cell.band[loopData.currentBandIndex];
        
        console.log(`Switching ${cellId} to band: ${nextBand} (index ${loopData.currentBandIndex})`);
        
        // Transition to next band
        this.transitionCellToBand(cellId, nextBand);
    }
}