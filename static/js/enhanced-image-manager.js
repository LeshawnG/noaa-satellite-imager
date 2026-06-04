/**
 * Enhanced Image Manager for Satellite Weather Display
 * Implements double-buffering, smooth transitions, and advanced preloading
 */

class EnhancedImageManager {
    constructor(options = {}) {
        this.options = {
            transitionDuration: 200, // Reduced from 500ms for smoother loop playback
            preloadDistance: 5, // frames ahead/behind to preload
            maxConcurrentLoads: 6,
            retryAttempts: 3,
            retryDelay: 1000, // ms
            fastLoopMode: true, // Enable fast updates for loop playback
            ...options
        };
        
        // Image cache and loading state
        this.imageCache = new Map();
        this.loadingQueue = [];
        this.activeLoaders = 0;
        this.loadingPromises = new Map();
        
        // Performance tracking
        this.loadStats = {
            totalLoads: 0,
            successfulLoads: 0,
            failedLoads: 0,
            averageLoadTime: 0
        };
        
        // Cell state tracking
        this.cellStates = new Map();
        
        this.init();
    }
    
    init() {
        // Initialize cell states
        const cellIds = ['top-left', 'top-right', 'bottom-left', 'bottom-right'];
        
        cellIds.forEach(cellId => {
            const cell = document.getElementById(`cell-${cellId}`);
            if (cell) {
                const primaryImg = cell.querySelector('img.primary');
                const secondaryImg = cell.querySelector('img.secondary');
                const loadingOverlay = cell.querySelector('.loading-overlay');
                const errorOverlay = cell.querySelector('.error-overlay');
                
                this.cellStates.set(cellId, {
                    element: cell,
                    primaryImg,
                    secondaryImg,
                    loadingOverlay,
                    errorOverlay,
                    currentSrc: null,
                    isTransitioning: false,
                    lastLoadTime: 0,
                    errorCount: 0
                });
                
                // Set up image event handlers
                this.setupImageHandlers(cellId, primaryImg);
                this.setupImageHandlers(cellId, secondaryImg);
            }
        });
    }
    
    setupImageHandlers(cellId, img) {
        if (!img) return;
        
        img.addEventListener('load', () => {
            this.onImageLoad(cellId, img);
        });
        
        img.addEventListener('error', () => {
            this.onImageError(cellId, img);
        });
        
        img.addEventListener('loadstart', () => {
            img.classList.add('loading');
        });
    }
    
    onImageLoad(cellId, img) {
        const state = this.cellStates.get(cellId);
        if (!state) return;
        
        img.classList.remove('loading');
        img.classList.add('loaded');
        
        // Update load stats
        this.loadStats.successfulLoads++;
        const loadTime = Date.now() - state.lastLoadTime;
        this.updateAverageLoadTime(loadTime);
        
        // Reset error count on successful load
        state.errorCount = 0;

        // Hide error overlay if showing
        this.hideErrorOverlay(cellId);

        if (window.APP_DEBUG) console.log(`Image loaded successfully for ${cellId}: ${img.src}`);
    }
    
    onImageError(cellId, img) {
        const state = this.cellStates.get(cellId);
        if (!state) return;
        
        img.classList.remove('loading');
        img.classList.add('error');
        
        // Update error stats
        this.loadStats.failedLoads++;
        state.errorCount++;
        
        console.error(`Failed to load image for ${cellId}: ${img.src}`);
        
        // Hide any existing error overlays first before potentially showing new ones
        this.hideErrorOverlay(cellId);
        
        // Show error overlay if too many failures
        if (state.errorCount >= this.options.retryAttempts) {
            this.showErrorOverlay(cellId);
        } else {
            // Retry loading
            setTimeout(() => {
                this.retryImageLoad(cellId);
            }, this.options.retryDelay * state.errorCount);
        }
    }
    
    updateAverageLoadTime(loadTime) {
        const total = this.loadStats.totalLoads;
        this.loadStats.averageLoadTime = 
            (this.loadStats.averageLoadTime * total + loadTime) / (total + 1);
        this.loadStats.totalLoads++;
    }
    
    /**
     * Update image for a cell with smooth transition
     */
    async updateCellImage(cellId, newSrc, options = {}) {
        const state = this.cellStates.get(cellId);
        if (!state || state.isTransitioning) return false;
        
        // Skip if same source
        if (state.currentSrc === newSrc) return true;
        
        // Use fast update for loop playback if enabled
        if (this.options.fastLoopMode && !options.forceTransition) {
            return this.fastUpdateCellImage(cellId, newSrc);
        }
        
        state.isTransitioning = true;
        state.lastLoadTime = Date.now();
        
        // Ensure any previous overlays are cleared
        this.hideErrorOverlay(cellId);
        
        try {
            // Determine which image element to use for new image
            const currentImg = state.primaryImg.style.opacity === '1' || 
                             state.primaryImg.style.opacity === '' ? 
                             state.primaryImg : state.secondaryImg;
            const nextImg = currentImg === state.primaryImg ? 
                           state.secondaryImg : state.primaryImg;
            
            // Preload the new image with timeout (no loading overlay shown)
            const preloadPromise = this.preloadImage(newSrc);
            const timeoutPromise = new Promise((_, reject) => 
                setTimeout(() => reject(new Error('Image load timeout')), 15000)
            );
            
            await Promise.race([preloadPromise, timeoutPromise]);
            
            // Set up the next image
            nextImg.src = newSrc;
            nextImg.style.opacity = '0';
            nextImg.classList.remove('error', 'loading');
            nextImg.classList.add('transitioning');
            
            // Wait for image to be ready
            await this.waitForImageReady(nextImg);
            
            // Perform crossfade transition
            await this.performCrossfade(currentImg, nextImg);
            
            // Update state
            state.currentSrc = newSrc;
            state.isTransitioning = false;
            
            return true;
            
        } catch (error) {
            console.error(`Failed to update image for ${cellId}:`, error);
            state.isTransitioning = false;
            
            // Only show error overlay if this is a repeated failure
            state.errorCount = (state.errorCount || 0) + 1;
            if (state.errorCount >= this.options.retryAttempts) {
                this.showErrorOverlay(cellId);
            }
            
            return false;
        }
    }
    
    /**
     * Fast update for loop playback - minimal transition for smoothness
     */
    async fastUpdateCellImage(cellId, newSrc) {
        const state = this.cellStates.get(cellId);
        if (!state) return false;
        
        // Skip if same source
        if (state.currentSrc === newSrc) return true;
        
        try {
            // Get the primary image element
            const img = state.primaryImg;
            if (img) {
                // Check if image is already cached or preloaded
                const cachedImg = this.imageCache.get(newSrc);
                if (cachedImg) {
                    // Use cached image for instant update
                    img.src = cachedImg.src;
                } else {
                    // Direct update for uncached images
                    img.src = newSrc;
                }
                
                state.currentSrc = newSrc;
                this.hideErrorOverlay(cellId);
                return true;
            }
        } catch (error) {
            console.error(`Failed to fast update image for ${cellId}:`, error);
        }
        
        return false;
    }
    
    /**
     * Immediate update for zoom changes - instant display with no transitions
     */
    async updateCellImageImmediate(cellId, newSrc) {
        const state = this.cellStates.get(cellId);
        if (!state) return false;
        
        // Skip if same source
        if (state.currentSrc === newSrc) return true;
        
        try {
            // Get the primary image element for instant update
            const img = state.primaryImg;
            if (img) {
                // Clear any loading states
                this.hideErrorOverlay(cellId);
                
                // Reset any transition states
                state.isTransitioning = false;
                img.classList.remove('transitioning', 'error', 'loading');
                img.style.transition = '';
                img.style.opacity = '1';
                
                // Set new source immediately
                img.src = newSrc;
                
                // Update state immediately
                state.currentSrc = newSrc;
                state.lastLoadTime = Date.now();
                
                return true;
            }
        } catch (error) {
            console.error(`Failed to immediately update image for ${cellId}:`, error);
        }
        
        return false;
    }
    
    /**
     * Preload image and cache it
     */
    async preloadImage(src) {
        if (this.imageCache.has(src)) {
            return this.imageCache.get(src);
        }
        
        // Check if already loading
        if (this.loadingPromises.has(src)) {
            return this.loadingPromises.get(src);
        }
        
        const loadPromise = new Promise((resolve, reject) => {
            const img = new Image();
            
            const cleanup = () => {
                this.loadingPromises.delete(src);
                this.activeLoaders--;
            };
            
            img.onload = () => {
                this.imageCache.set(src, img);
                cleanup();
                resolve(img);
            };
            
            img.onerror = () => {
                cleanup();
                reject(new Error(`Failed to preload image: ${src}`));
            };
            
            // Set loading attributes for better performance
            img.loading = 'eager';
            img.decoding = 'async';
            img.src = src;
            
            this.activeLoaders++;
        });
        
        this.loadingPromises.set(src, loadPromise);
        return loadPromise;
    }
    
    /**
     * Wait for image element to be ready for display
     */
    async waitForImageReady(img) {
        return new Promise((resolve) => {
            if (img.complete && img.naturalHeight !== 0) {
                resolve();
            } else {
                const onLoad = () => {
                    img.removeEventListener('load', onLoad);
                    resolve();
                };
                img.addEventListener('load', onLoad);
            }
        });
    }
    
    /**
     * Perform smooth crossfade between images
     */
    async performCrossfade(currentImg, nextImg) {
        return new Promise((resolve) => {
            // Set up transition
            const duration = this.options.transitionDuration;
            
            currentImg.style.transition = `opacity ${duration}ms ease-in-out`;
            nextImg.style.transition = `opacity ${duration}ms ease-in-out`;
            
            // Start crossfade
            requestAnimationFrame(() => {
                currentImg.style.opacity = '0';
                nextImg.style.opacity = '1';
                
                // Clean up after transition
                setTimeout(() => {
                    currentImg.classList.remove('transitioning');
                    nextImg.classList.remove('transitioning');
                    currentImg.style.transition = '';
                    nextImg.style.transition = '';
                    resolve();
                }, duration);
            });
        });
    }
    
    /**
     * Batch preload multiple images
     */
    async batchPreload(sources, onProgress = null) {
        const total = sources.length;
        let completed = 0;
        
        const loadPromises = sources.map(async (src) => {
            try {
                await this.preloadImage(src);
                completed++;
                if (onProgress) {
                    onProgress(completed / total);
                }
            } catch (error) {
                console.warn(`Failed to preload ${src}:`, error);
                completed++;
                if (onProgress) {
                    onProgress(completed / total);
                }
            }
        });
        
        await Promise.allSettled(loadPromises);
    }
    
    /**
     * Show error overlay for a cell
     */
    showErrorOverlay(cellId) {
        const state = this.cellStates.get(cellId);
        if (state && state.errorOverlay) {
            state.errorOverlay.classList.add('show');
        }
    }
    
    /**
     * Hide error overlay for a cell
     */
    hideErrorOverlay(cellId) {
        const state = this.cellStates.get(cellId);
        if (state && state.errorOverlay) {
            state.errorOverlay.classList.remove('show');
        }
    }
    
    /**
     * Retry loading image for a cell
     */
    async retryImageLoad(cellId) {
        const state = this.cellStates.get(cellId);
        if (!state) return;
        
        // Reset error state
        state.errorCount = 0;
        this.hideErrorOverlay(cellId);
        
        // Clear any cached failed images
        const currentSrc = state.currentSrc;
        if (currentSrc && this.imageCache.has(currentSrc)) {
            this.imageCache.delete(currentSrc);
        }
        
        // Retry the load
        if (currentSrc) {
            await this.updateCellImage(cellId, currentSrc);
        }
    }
    
    /**
     * Get current image source for a cell
     */
    getCurrentImageSrc(cellId) {
        const state = this.cellStates.get(cellId);
        return state ? state.currentSrc : null;
    }
    
    /**
     * Check if cell is currently transitioning
     */
    isTransitioning(cellId) {
        const state = this.cellStates.get(cellId);
        return state ? state.isTransitioning : false;
    }
    
    /**
     * Get loading statistics
     */
    getLoadStats() {
        return {
            ...this.loadStats,
            cacheSize: this.imageCache.size,
            activeLoaders: this.activeLoaders,
            successRate: this.loadStats.totalLoads > 0 ? 
                        this.loadStats.successfulLoads / this.loadStats.totalLoads : 0
        };
    }
    
    /**
     * Clear image cache to free memory
     */
    clearCache() {
        // Revoke object URLs if any
        for (const [url, img] of this.imageCache) {
            if (img.src && img.src.startsWith('blob:')) {
                URL.revokeObjectURL(img.src);
            }
        }
        
        this.imageCache.clear();
        console.log('Image cache cleared');
    }
    
    /**
     * Optimize cache by removing old entries
     */
    optimizeCache(maxSize = 100) {
        if (this.imageCache.size <= maxSize) return;
        
        // Convert to array and sort by usage (simple LRU)
        const entries = Array.from(this.imageCache.entries());
        const toRemove = entries.slice(0, entries.length - maxSize);
        
        toRemove.forEach(([url, img]) => {
            if (img.src && img.src.startsWith('blob:')) {
                URL.revokeObjectURL(img.src);
            }
            this.imageCache.delete(url);
        });
        
        console.log(`Cache optimized: removed ${toRemove.length} entries`);
    }
    
    /**
     * Destroy the image manager and clean up resources
     */
    destroy() {
        this.clearCache();
        this.cellStates.clear();
        this.loadingPromises.clear();
        this.loadingQueue = [];
    }
    
    /**
     * Clear all loading states for emergency cleanup
     */
    clearAllLoadingStates() {
        this.cellStates.forEach((state, cellId) => {
            state.isTransitioning = false;
        });
        console.log('All loading states cleared');
    }
    
    /**
     * Force update image without transition (useful for loop playback)
     */
    forceUpdateCellImage(cellId, newSrc) {
        const state = this.cellStates.get(cellId);
        if (!state) return false;
        
        // Skip if same source
        if (state.currentSrc === newSrc) return true;
        
        try {
            // Get the primary image element
            const img = state.primaryImg;
            if (img) {
                img.src = newSrc;
                state.currentSrc = newSrc;
                this.hideErrorOverlay(cellId);
                return true;
            }
        } catch (error) {
            console.error(`Failed to force update image for ${cellId}:`, error);
        }
        
        return false;
    }
}

// Global progress indicator management
class GlobalProgressIndicator {
    constructor() {
        this.element = document.getElementById('global-loading');
        this.progressFill = document.getElementById('progress-fill');
        this.progressText = document.getElementById('progress-text');
        this.isVisible = false;
    }
    
    show() {
        if (this.element && !this.isVisible) {
            this.element.classList.add('show');
            this.isVisible = true;
        }
    }
    
    hide() {
        if (this.element && this.isVisible) {
            this.element.classList.remove('show');
            this.isVisible = false;
        }
    }
    
    updateProgress(progress) {
        const percentage = Math.round(progress * 100);
        
        if (this.progressFill) {
            this.progressFill.style.width = `${percentage}%`;
        }
        
        if (this.progressText) {
            this.progressText.textContent = `${percentage}%`;
        }
        
        // Auto-hide when complete
        if (progress >= 1) {
            setTimeout(() => this.hide(), 500);
        }
    }
}

// Export for use in other modules
window.EnhancedImageManager = EnhancedImageManager;
window.GlobalProgressIndicator = GlobalProgressIndicator; 