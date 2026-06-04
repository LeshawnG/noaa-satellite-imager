/**
 * Loop Controller for Satellite Weather Images
 * Manages image preloading, playback, and frame timing
 */

// Verbose logging is gated behind window.APP_DEBUG to keep the per-frame
// hot path cheap on low-power devices (e.g. Raspberry Pi).
function lcLog(...args) {
    if (typeof window !== 'undefined' && window.APP_DEBUG) console.log(...args);
}

class LoopController {
    constructor(options = {}) {
        this.options = {
            frameRate: 5, // Increased from 4 fps for smoother playback
            preloadAhead: 10, // frames to preload ahead
            preloadBehind: 5, // frames to keep behind
            onFrameChange: null,
            onLoadProgress: null,
            ...options
        };
        
        // Image sets for each grid cell
        this.imageSets = {};
        
        // Current state
        this.currentFrame = 0;
        this.totalFrames = 0;
        this.isPlaying = false;
        this.isPaused = false;
        this.isZoomChanging = false; // Track zoom changes for optimized preloading
        
        // Preloading.
        // The actual decoded-image cache lives in EnhancedImageManager (single
        // source of truth, set via setImageManager). LoopController only tracks
        // which URLs it has requested/loaded so it never hoards bitmaps itself.
        this.imageManager = null;
        this.imageCache = new Map();      // fallback decode cache only when no imageManager
        this.requestedUrls = new Set();   // URLs already queued/loaded (dedupe)
        this.loadedUrls = new Set();      // URLs confirmed loaded (progress)
        this.loadingQueue = [];
        this.activeLoaders = 0;
        this.maxConcurrentLoads = 4;
        
        // Animation
        this.animationId = null;
        this.lastFrameTime = 0;
        this.frameInterval = 1000 / this.options.frameRate;
        
        // Performance monitoring
        this.frameDrops = 0;
        this.lastFrameTimestamp = 0;
    }
    
    setImageSets(imageSets) {
        console.log('LoopController: Setting new image sets', {
            previousTotalFrames: this.totalFrames,
            newImageSets: Object.keys(imageSets),
            wasPlaying: this.isPlaying
        });
        
        this.imageSets = imageSets;
        this.currentFrame = 0;
        
        // Calculate total frames from the first non-cycle set
        let newTotalFrames = 0;
        for (const [cellId, imageSet] of Object.entries(imageSets)) {
            if (!imageSet.type || imageSet.type !== 'cycle') {
                newTotalFrames = imageSet.length;
                console.log(`LoopController: Using ${cellId} for frame count: ${newTotalFrames} frames`);
                break;
            }
        }
        this.totalFrames = newTotalFrames;
        
        // Log image set details for debugging
        for (const [cellId, imageSet] of Object.entries(imageSets)) {
            if (imageSet.type === 'cycle') {
                const bandCounts = {};
                for (const [bandKey, images] of Object.entries(imageSet.images)) {
                    bandCounts[bandKey] = images.length;
                }
                console.log(`LoopController: ${cellId} cycle set:`, bandCounts);
            } else {
                console.log(`LoopController: ${cellId} static set: ${imageSet.length} images`);
                if (imageSet.length > 0) {
                    console.log(`LoopController: First image URL: ${imageSet[0].url}`);
                }
            }
        }
        
        // Clear cache when changing image sets
        this.clearCache();
        
        // Start preloading
        this.preloadImages();
        
        console.log(`LoopController: Image sets updated. Total frames: ${this.totalFrames}`);
    }
    
    setImageSetsSeamless(imageSets) {
        console.log('LoopController: Setting new image sets seamlessly', {
            previousTotalFrames: this.totalFrames,
            newImageSets: Object.keys(imageSets),
            wasPlaying: this.isPlaying,
            currentFrame: this.currentFrame
        });
        
        // Set zoom changing flag for optimized preloading
        this.isZoomChanging = true;
        
        this.imageSets = imageSets;
        
        // Calculate total frames from the first non-cycle set
        let newTotalFrames = 0;
        for (const [cellId, imageSet] of Object.entries(imageSets)) {
            if (!imageSet.type || imageSet.type !== 'cycle') {
                newTotalFrames = imageSet.length;
                console.log(`LoopController: Using ${cellId} for frame count: ${newTotalFrames} frames`);
                break;
            }
        }
        this.totalFrames = newTotalFrames;
        
        // Preserve playback position across background refreshes (new frames
        // are appended to the end of the timeline, so existing indices keep
        // their meaning). Callers that need a reset (e.g. a zoom change) set the
        // frame explicitly afterward.
        this.currentFrame = Math.min(this.currentFrame, Math.max(0, this.totalFrames - 1));

        // Log image set details for debugging
        for (const [cellId, imageSet] of Object.entries(imageSets)) {
            if (imageSet.type === 'cycle') {
                const bandCounts = {};
                for (const [bandKey, images] of Object.entries(imageSet.images)) {
                    bandCounts[bandKey] = images.length;
                }
                console.log(`LoopController: ${cellId} cycle set:`, bandCounts);
            } else {
                console.log(`LoopController: ${cellId} static set: ${imageSet.length} images`);
            }
        }

        // CRITICAL FIX: Clear cache to remove old zoom level images
        this.clearCache();
        console.log('LoopController: Cleared image cache for zoom change');
        
        // IMMEDIATE: Update frame display right now - no delays
        this.updateFrame();
        
        // IMPROVED: Preload critical frames before allowing playback resume
        this.preloadCriticalFramesForZoom().then(() => {
            // Reset zoom changing flag after critical frames are loaded
            this.isZoomChanging = false;
            console.log('LoopController: Critical frames loaded, zoom change complete');
            
            // Start background preloading for remaining frames
            this.preloadImages();
        });
        
        console.log(`LoopController: Image sets updated seamlessly. Total frames: ${this.totalFrames}, Current frame: ${this.currentFrame}`);
    }
    
    clearCache() {
        // Revoke object URLs to free memory (fallback cache only)
        for (const [url, img] of this.imageCache) {
            if (img.src && img.src.startsWith('blob:')) {
                URL.revokeObjectURL(img.src);
            }
        }
        this.imageCache.clear();
        this.requestedUrls.clear();
        this.loadedUrls.clear();

        // Drop decoded frames from the shared cache too (e.g. on zoom change)
        // so we don't keep the previous zoom level's images in memory.
        if (this.imageManager && typeof this.imageManager.clearCache === 'function') {
            this.imageManager.clearCache();
        }
    }
    
    preloadImages() {
        // Use smaller preload range during zoom changes for faster response
        const preloadAhead = this.isZoomChanging ? 3 : this.options.preloadAhead;
        const preloadBehind = this.isZoomChanging ? 1 : this.options.preloadBehind;
        
        // Calculate range of frames to preload
        const start = Math.max(0, this.currentFrame - preloadBehind);
        const end = Math.min(this.totalFrames - 1, this.currentFrame + preloadAhead);
        
        // Queue images for preloading with priority to current frame
        const framesToLoad = [];
        
        // Priority 1: Current frame
        framesToLoad.push(this.currentFrame);
        
        // Priority 2: Next few frames
        for (let i = 1; i <= Math.min(3, preloadAhead); i++) {
            const nextFrame = (this.currentFrame + i) % this.totalFrames;
            framesToLoad.push(nextFrame);
        }
        
        // Priority 3: Remaining frames in range
        for (let i = start; i <= end; i++) {
            if (!framesToLoad.includes(i)) {
                framesToLoad.push(i);
            }
        }
        
        // Queue frames in priority order
        framesToLoad.forEach(frameIndex => {
            this.queueFrameForPreload(frameIndex);
        });
        
        // Start loading
        this.processLoadQueue();
    }
    
    setImageManager(imageManager) {
        // Share a single decoded-image cache with the display layer so frames
        // are never downloaded/decoded twice.
        this.imageManager = imageManager;
    }

    queueFrameForPreload(frameIndex) {
        // Queue images for all cells at this frame
        for (const [cellId, imageSet] of Object.entries(this.imageSets)) {
            if (imageSet.type === 'cycle') {
                // Handle cycle sets differently
                this.queueCycleFrameForPreload(cellId, imageSet, frameIndex);
            } else {
                // Normal image set
                if (frameIndex < imageSet.length) {
                    const image = imageSet[frameIndex];

                    if (image && image.url && !this.requestedUrls.has(image.url)) {
                        this.requestedUrls.add(image.url);
                        this.loadingQueue.push({ url: image.url, frameIndex, cellId });
                    }
                }
            }
        }
    }

    queueCycleFrameForPreload(cellId, cycleSet, frameIndex) {
        // For cycle sets, preload all bands for this frame
        for (const [bandKey, images] of Object.entries(cycleSet.images)) {
            if (frameIndex < images.length) {
                const image = images[frameIndex];

                if (image && image.url && !this.requestedUrls.has(image.url)) {
                    this.requestedUrls.add(image.url);
                    this.loadingQueue.push({ url: image.url, frameIndex, cellId, bandKey });
                }
            }
        }
    }
    
    async processLoadQueue() {
        while (this.loadingQueue.length > 0 && this.activeLoaders < this.maxConcurrentLoads) {
            const item = this.loadingQueue.shift();
            this.activeLoaders++;
            
            try {
                await this.loadImage(item);
            } catch (error) {
                console.error('Error loading image:', error);
            } finally {
                this.activeLoaders--;
                
                // Continue processing queue
                if (this.loadingQueue.length > 0) {
                    this.processLoadQueue();
                }
            }
        }
        
        // Update load progress
        this.updateLoadProgress();
    }
    
    async loadImage(item) {
        // Preferred path: delegate to the shared EnhancedImageManager cache so
        // the image is decoded once and reused by the display layer.
        if (this.imageManager) {
            try {
                await this.imageManager.preloadImage(item.url);
                this.loadedUrls.add(item.url);
            } catch (error) {
                // Allow a retry later by clearing the dedupe flag.
                this.requestedUrls.delete(item.url);
                throw error;
            }
            return;
        }

        // Fallback (no image manager wired): decode locally.
        return new Promise((resolve, reject) => {
            const img = new Image();

            img.onload = () => {
                this.imageCache.set(item.url, img);
                this.loadedUrls.add(item.url);
                resolve();
            };

            img.onerror = () => {
                this.requestedUrls.delete(item.url);
                reject(new Error(`Failed to load image: ${item.url}`));
            };

            img.src = item.url;
        });
    }

    updateLoadProgress() {
        if (this.options.onLoadProgress) {
            const totalImages = this.requestedUrls.size;
            const loadedImages = this.loadedUrls.size;
            const progress = totalImages > 0 ? loadedImages / totalImages : 0;

            this.options.onLoadProgress(progress);
        }
    }
    
    start() {
        this.isPlaying = true;
        this.isPaused = false;
        this.lastFrameTime = performance.now();
        this.animate();
    }
    
    pause() {
        this.isPaused = true;
        
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
    }
    
    resume() {
        if (this.isPlaying && this.isPaused) {
            this.isPaused = false;
            this.lastFrameTime = performance.now();
            this.animate();
        }
    }
    
    stop() {
        this.isPlaying = false;
        this.isPaused = false;
        this.currentFrame = 0;
        
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        
        this.updateFrame();
    }
    
    animate() {
        if (!this.isPlaying || this.isPaused) return;
        
        try {
            const now = performance.now();
            const elapsed = now - this.lastFrameTime;
            
            if (elapsed >= this.frameInterval) {
                // Calculate how many frames we should have advanced
                const framesToAdvance = Math.floor(elapsed / this.frameInterval);
                
                // Only warn about frame drops if significant (more than 2 frames)
                if (framesToAdvance > 2) {
                    this.frameDrops += framesToAdvance - 1;
                    console.warn(`Dropped ${framesToAdvance - 1} frames`);
                }
                
                // Advance frame with proper modulo to ensure smooth looping
                this.currentFrame = (this.currentFrame + framesToAdvance) % this.totalFrames;
                this.lastFrameTime = now - (elapsed % this.frameInterval);
                
                // Update display
                this.updateFrame();
                
                // Preload upcoming frames (non-blocking)
                setTimeout(() => this.preloadImages(), 0);
            }
            
            this.animationId = requestAnimationFrame(() => this.animate());
        } catch (error) {
            console.error('Error in animation loop:', error);
            // Restart animation after a brief delay to prevent getting stuck
            setTimeout(() => {
                if (this.isPlaying && !this.isPaused) {
                    this.lastFrameTime = performance.now();
                    this.animate();
                }
            }, 50); // Reduced delay from 100ms to 50ms
        }
    }
    
    updateFrame() {
        lcLog(`LoopController: Updating frame ${this.currentFrame}/${this.totalFrames}`);
        
        // Update frame info in status bar
        this.updateFrameInfo();
        
        // Skip direct image updates for grid cells since GridManager handles these
        // through the onFrameChange callback to prevent conflicts and flashing
        
        // Notify frame change - GridManager will handle the actual image updates
        if (this.options.onFrameChange) {
            try {
                this.options.onFrameChange(this.currentFrame);
            } catch (callbackError) {
                console.error('Error in onFrameChange callback:', callbackError);
            }
        }
    }
    
    updateFrameInfo() {
        const frameInfoElement = document.getElementById('frame-info');
        if (frameInfoElement) {
            frameInfoElement.textContent = `Frame: ${this.currentFrame + 1}/${this.totalFrames}`;
        }
    }

    async loadImageImmediate(cellId, frameIndex, url, cacheKey) {
        // Warm the shared cache; GridManager handles the actual display update
        // via updateCellDisplayImmediate to avoid touching the DOM from here.
        try {
            if (this.imageManager) {
                await this.imageManager.preloadImage(url);
                this.loadedUrls.add(url);
            } else {
                await new Promise((resolve, reject) => {
                    const img = new Image();
                    img.onload = () => { this.imageCache.set(url, img); resolve(); };
                    img.onerror = reject;
                    img.src = url;
                });
            }
        } catch (error) {
            lcLog(`Failed to load immediate image for ${cellId}:`, error);
        }
    }
    
    // Public methods for external control
    getCurrentFrame() {
        return this.currentFrame;
    }
    
    getTotalFrames() {
        return this.totalFrames;
    }
    
    setFrame(frameIndex) {
        // Convert from 1-based to 0-based indexing for internal use
        const internalFrame = Math.max(0, frameIndex - 1);
        
        if (internalFrame >= 0 && internalFrame < this.totalFrames) {
            this.currentFrame = internalFrame;
            console.log(`LoopController: Set frame to ${frameIndex} (internal: ${internalFrame})`);
            this.updateFrame();
            this.preloadImages();
        } else {
            console.warn(`LoopController: Invalid frame ${frameIndex}, total frames: ${this.totalFrames}`);
        }
    }
    
    setFrameFromUser(userFrame) {
        // Handle 1-based frame indexing from user interface
        if (userFrame >= 1 && userFrame <= this.totalFrames) {
            this.currentFrame = userFrame - 1; // Convert to 0-based
            console.log(`LoopController: User set frame to ${userFrame} (internal: ${this.currentFrame})`);
            this.updateFrame();
            this.preloadImages();
        } else {
            console.warn(`LoopController: Invalid user frame ${userFrame}, valid range: 1-${this.totalFrames}`);
        }
    }
    
    nextFrame() {
        this.setFrame((this.currentFrame + 1) % this.totalFrames);
    }
    
    previousFrame() {
        this.setFrame((this.currentFrame - 1 + this.totalFrames) % this.totalFrames);
    }
    
    setFrameRate(fps) {
        this.options.frameRate = fps;
        this.frameInterval = 1000 / fps;
    }
    
    getImageForCell(cellId, frameIndex = null) {
        if (frameIndex === null) {
            frameIndex = this.currentFrame;
        }

        // Return frame metadata ({ url, fullUrl, timestamp, localTime }) from the
        // image set. The decoded bitmap lives in the shared EnhancedImageManager.
        const imageSet = this.imageSets[cellId];
        if (imageSet && !imageSet.type && frameIndex >= 0 && frameIndex < imageSet.length) {
            return imageSet[frameIndex];
        }
        return null;
    }

    getCycleImageForCell(cellId, bandKey, frameIndex = null) {
        if (frameIndex === null) {
            frameIndex = this.currentFrame;
        }

        const imageSet = this.imageSets[cellId];
        if (imageSet && imageSet.type === 'cycle' && imageSet.images[bandKey]) {
            const images = imageSet.images[bandKey];
            if (frameIndex >= 0 && frameIndex < images.length) {
                return images[frameIndex];
            }
        }
        return null;
    }
    
    getPerformanceStats() {
        return {
            frameDrops: this.frameDrops,
            cacheSize: this.imageCache.size,
            activeLoaders: this.activeLoaders,
            queueLength: this.loadingQueue.length
        };
    }
    
    destroy() {
        this.stop();
        this.clearCache();
        this.loadingQueue = [];
    }

    async loadCurrentFrameImmediate() {
        console.log(`LoopController: Loading current frame ${this.currentFrame} immediately`);
        
        // Load current frame for all cells with high priority
        const loadPromises = [];
        
        for (const [cellId, imageSet] of Object.entries(this.imageSets)) {
            if (imageSet.type === 'cycle') {
                // Handle cycle sets - load all bands for current frame
                for (const [bandKey, images] of Object.entries(imageSet.images)) {
                    if (this.currentFrame < images.length) {
                        const image = images[this.currentFrame];
                        if (image.url) {
                            const cacheKey = `${cellId}_${bandKey}_${this.currentFrame}`;
                            loadPromises.push(
                                this.loadImageImmediate(cellId, this.currentFrame, image.url, cacheKey)
                            );
                        }
                    }
                }
            } else {
                // Normal image set
                if (this.currentFrame < imageSet.length) {
                    const image = imageSet[this.currentFrame];
                    if (image.url) {
                        const cacheKey = `${cellId}_${this.currentFrame}`;
                        loadPromises.push(
                            this.loadImageImmediate(cellId, this.currentFrame, image.url, cacheKey)
                        );
                    }
                }
            }
        }
        
        // Wait for all current frame images to load
        try {
            await Promise.allSettled(loadPromises);
            console.log(`LoopController: Current frame ${this.currentFrame} loaded immediately`);
        } catch (error) {
            console.error('Error loading current frame immediately:', error);
        }
    }

    preloadCurrentFrameImmediate() {
        console.log(`LoopController: Preloading current frame ${this.currentFrame} immediately`);
        
        // Load current frame for all cells synchronously for instant display
        for (const [cellId, imageSet] of Object.entries(this.imageSets)) {
            if (imageSet.type === 'cycle') {
                // Handle cycle sets - load all bands for current frame
                for (const [bandKey, images] of Object.entries(imageSet.images)) {
                    if (this.currentFrame < images.length) {
                        const image = images[this.currentFrame];
                        if (image.url) {
                            const cacheKey = `${cellId}_${bandKey}_${this.currentFrame}`;
                            // Start loading immediately but don't wait for completion
                            this.loadImageImmediate(cellId, this.currentFrame, image.url, cacheKey)
                                .catch(error => console.warn(`Failed to preload ${cacheKey}:`, error));
                        }
                    }
                }
            } else {
                // Normal image set
                if (this.currentFrame < imageSet.length) {
                    const image = imageSet[this.currentFrame];
                    if (image.url) {
                        const cacheKey = `${cellId}_${this.currentFrame}`;
                        // Start loading immediately but don't wait for completion
                        this.loadImageImmediate(cellId, this.currentFrame, image.url, cacheKey)
                            .catch(error => console.warn(`Failed to preload ${cacheKey}:`, error));
                    }
                }
            }
        }
        
        console.log(`LoopController: Current frame ${this.currentFrame} preload started immediately`);
    }

    async preloadCriticalFramesForZoom() {
        console.log('LoopController: Preloading critical frames for zoom');
        
        // Load critical frames for all cells with high priority
        const loadPromises = [];
        
        for (const [cellId, imageSet] of Object.entries(this.imageSets)) {
            if (imageSet.type === 'cycle') {
                // Handle cycle sets - load all bands for current frame
                for (const [bandKey, images] of Object.entries(imageSet.images)) {
                    if (this.currentFrame < images.length) {
                        const image = images[this.currentFrame];
                        if (image.url) {
                            const cacheKey = `${cellId}_${bandKey}_${this.currentFrame}`;
                            loadPromises.push(
                                this.loadImageImmediate(cellId, this.currentFrame, image.url, cacheKey)
                            );
                        }
                    }
                }
            } else {
                // Normal image set
                if (this.currentFrame < imageSet.length) {
                    const image = imageSet[this.currentFrame];
                    if (image.url) {
                        const cacheKey = `${cellId}_${this.currentFrame}`;
                        loadPromises.push(
                            this.loadImageImmediate(cellId, this.currentFrame, image.url, cacheKey)
                        );
                    }
                }
            }
        }
        
        // Wait for all critical frames to load
        try {
            await Promise.allSettled(loadPromises);
            console.log('LoopController: Critical frames loaded');
        } catch (error) {
            console.error('Error loading critical frames:', error);
        }
    }
}