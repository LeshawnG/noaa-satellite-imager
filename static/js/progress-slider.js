/**
 * Progress Slider Controller for Satellite Weather Loop
 * Manages the progress slider for scrubbing through time periods
 */

class ProgressSlider {
    constructor(options = {}) {
        this.options = {
            onSliderChange: null,
            onSliderStart: null,
            onSliderEnd: null,
            updateInterval: 100, // Update frequency when playing
            ...options
        };
        
        // DOM elements
        this.slider = null;
        this.progressTrack = null;
        this.sliderContainer = null;
        
        // State
        this.totalFrames = 0;
        this.currentFrame = 0;
        this.isDragging = false;
        this.isPlaying = false;
        this.wasPlayingBeforeDrag = false;
        
        // Animation
        this.updateAnimationId = null;
        
        this.init();
    }
    
    init() {
        // Get DOM elements
        this.slider = document.getElementById('progress-slider');
        this.progressTrack = document.getElementById('slider-progress');
        this.sliderContainer = document.querySelector('.progress-slider-container');
        
        if (!this.slider || !this.progressTrack || !this.sliderContainer) {
            console.error('ProgressSlider: Required DOM elements not found');
            return;
        }
        
        this.setupEventHandlers();
        console.log('ProgressSlider: Initialized successfully');
    }
    
    setupEventHandlers() {
        // Slider input events
        this.slider.addEventListener('input', (e) => this.onSliderInput(e));
        this.slider.addEventListener('mousedown', (e) => this.onSliderStart(e));
        this.slider.addEventListener('mouseup', (e) => this.onSliderEnd(e));
        this.slider.addEventListener('touchstart', (e) => this.onSliderStart(e));
        this.slider.addEventListener('touchend', (e) => this.onSliderEnd(e));
        
        // Prevent context menu on slider
        this.slider.addEventListener('contextmenu', (e) => e.preventDefault());
        
        // Track clicks for direct seeking
        this.sliderContainer.addEventListener('click', (e) => this.onTrackClick(e));
        
        // Keyboard support
        this.slider.addEventListener('keydown', (e) => this.onKeyDown(e));
    }
    
    onSliderInput(e) {
        const value = parseInt(e.target.value);
        this.setCurrentFrame(value);
        this.updateProgressTrack();
        
        // Notify parent of frame change
        if (this.options.onSliderChange) {
            this.options.onSliderChange(value);
        }
    }
    
    onSliderStart(e) {
        this.isDragging = true;
        this.wasPlayingBeforeDrag = this.isPlaying;
        
        // Pause playback during dragging for smooth scrubbing
        if (this.options.onSliderStart) {
            this.options.onSliderStart();
        }
        
        // Add global mouse/touch move and up events for smooth dragging
        document.addEventListener('mousemove', this.onGlobalMouseMove.bind(this));
        document.addEventListener('mouseup', this.onGlobalMouseUp.bind(this));
        document.addEventListener('touchmove', this.onGlobalTouchMove.bind(this));
        document.addEventListener('touchend', this.onGlobalTouchEnd.bind(this));
        
        // Prevent text selection during drag
        document.body.style.userSelect = 'none';
        
        console.log('ProgressSlider: Started dragging');
    }
    
    onSliderEnd(e) {
        this.isDragging = false;
        
        // Clean up global event listeners
        document.removeEventListener('mousemove', this.onGlobalMouseMove.bind(this));
        document.removeEventListener('mouseup', this.onGlobalMouseUp.bind(this));
        document.removeEventListener('touchmove', this.onGlobalTouchMove.bind(this));
        document.removeEventListener('touchend', this.onGlobalTouchEnd.bind(this));
        
        // Restore text selection
        document.body.style.userSelect = '';
        
        // Resume playback if it was playing before dragging
        if (this.options.onSliderEnd) {
            this.options.onSliderEnd(this.wasPlayingBeforeDrag);
        }
        
        console.log('ProgressSlider: Ended dragging');
    }
    
    onGlobalMouseMove(e) {
        if (this.isDragging) {
            this.updateSliderFromPosition(e.clientX);
        }
    }
    
    onGlobalMouseUp(e) {
        if (this.isDragging) {
            this.onSliderEnd(e);
        }
    }
    
    onGlobalTouchMove(e) {
        if (this.isDragging && e.touches.length > 0) {
            e.preventDefault();
            this.updateSliderFromPosition(e.touches[0].clientX);
        }
    }
    
    onGlobalTouchEnd(e) {
        if (this.isDragging) {
            this.onSliderEnd(e);
        }
    }
    
    updateSliderFromPosition(clientX) {
        const rect = this.slider.getBoundingClientRect();
        const percentage = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        const frame = Math.round(percentage * (this.totalFrames - 1)) + 1;
        
        this.slider.value = frame;
        this.onSliderInput({ target: { value: frame } });
    }
    
    onTrackClick(e) {
        // Only handle clicks on the track, not on the slider thumb
        if (e.target === this.slider) return;
        
        const rect = this.sliderContainer.getBoundingClientRect();
        const percentage = (e.clientX - rect.left) / rect.width;
        const frame = Math.round(percentage * (this.totalFrames - 1)) + 1;
        
        this.setSliderValue(frame);
        this.onSliderInput({ target: { value: frame } });
    }
    
    onKeyDown(e) {
        let handled = false;
        
        switch (e.key) {
            case 'ArrowLeft':
                this.previousFrame();
                handled = true;
                break;
            case 'ArrowRight':
                this.nextFrame();
                handled = true;
                break;
            case 'Home':
                this.setSliderValue(1);
                this.onSliderInput({ target: { value: 1 } });
                handled = true;
                break;
            case 'End':
                this.setSliderValue(this.totalFrames);
                this.onSliderInput({ target: { value: this.totalFrames } });
                handled = true;
                break;
        }
        
        if (handled) {
            e.preventDefault();
        }
    }
    
    previousFrame() {
        const newFrame = Math.max(1, this.currentFrame - 1);
        this.setSliderValue(newFrame);
        this.onSliderInput({ target: { value: newFrame } });
    }
    
    nextFrame() {
        const newFrame = Math.min(this.totalFrames, this.currentFrame + 1);
        this.setSliderValue(newFrame);
        this.onSliderInput({ target: { value: newFrame } });
    }
    
    // Public methods for external control
    
    setTotalFrames(totalFrames) {
        this.totalFrames = Math.max(1, totalFrames);
        this.slider.max = this.totalFrames;
        
        // Reset to frame 1 if current frame is beyond new total
        if (this.currentFrame > this.totalFrames) {
            this.setCurrentFrame(1);
        }
        
        this.updateProgressTrack();
        console.log(`ProgressSlider: Set total frames to ${this.totalFrames}`);
    }
    
    setCurrentFrame(frame) {
        this.currentFrame = Math.max(1, Math.min(this.totalFrames, frame));
        
        // Only update slider value if not currently dragging
        if (!this.isDragging) {
            this.setSliderValue(this.currentFrame);
        }
        
        this.updateProgressTrack();
    }
    
    setSliderValue(value) {
        this.slider.value = value;
        this.currentFrame = value;
    }
    
    updateProgressTrack() {
        if (this.totalFrames <= 1) {
            this.progressTrack.style.width = '0%';
            return;
        }
        
        const percentage = ((this.currentFrame - 1) / (this.totalFrames - 1)) * 100;
        this.progressTrack.style.width = `${percentage}%`;
    }
    
    setPlayingState(isPlaying) {
        this.isPlaying = isPlaying;
        
        // Add visual indication when playing
        if (isPlaying && !this.isDragging) {
            this.sliderContainer.classList.add('playing');
        } else {
            this.sliderContainer.classList.remove('playing');
        }
    }
    
    // Auto-update when playing
    startAutoUpdate() {
        if (this.updateAnimationId) {
            cancelAnimationFrame(this.updateAnimationId);
        }
        
        this.updateLoop();
    }
    
    stopAutoUpdate() {
        if (this.updateAnimationId) {
            cancelAnimationFrame(this.updateAnimationId);
            this.updateAnimationId = null;
        }
    }
    
    updateLoop() {
        // Only update if not dragging and playing
        if (!this.isDragging && this.isPlaying) {
            // Update will be handled by external frame change notifications
        }
        
        this.updateAnimationId = requestAnimationFrame(() => this.updateLoop());
    }
    
    // Utility methods
    
    getProgress() {
        if (this.totalFrames <= 1) return 0;
        return (this.currentFrame - 1) / (this.totalFrames - 1);
    }
    
    setProgress(progress) {
        const frame = Math.round(progress * (this.totalFrames - 1)) + 1;
        this.setCurrentFrame(frame);
    }
    
    reset() {
        this.setCurrentFrame(1);
        this.setPlayingState(false);
    }
    
    destroy() {
        this.stopAutoUpdate();
        
        // Remove event listeners
        if (this.slider) {
            this.slider.removeEventListener('input', this.onSliderInput);
            this.slider.removeEventListener('mousedown', this.onSliderStart);
            this.slider.removeEventListener('mouseup', this.onSliderEnd);
            this.slider.removeEventListener('touchstart', this.onSliderStart);
            this.slider.removeEventListener('touchend', this.onSliderEnd);
            this.slider.removeEventListener('contextmenu', (e) => e.preventDefault());
            this.slider.removeEventListener('keydown', this.onKeyDown);
        }
        
        if (this.sliderContainer) {
            this.sliderContainer.removeEventListener('click', this.onTrackClick);
        }
        
        console.log('ProgressSlider: Destroyed');
    }
} 