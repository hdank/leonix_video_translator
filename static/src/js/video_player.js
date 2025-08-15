/**
 * Video Player Manager for Leonix Video Translator
 * Handles vide    updateSourceStatus(type, statusText, success) {
        const className = success ? 'text-success' : 'text-danger';
        const regex = type === 'custom' 
            ? /• Custom: <span class="[^"]*">.*?<\/span>/
            : /• Odoo: <span class="[^"]*">.*?<\/span>/;
        const replacement = `• ${type === 'custom' ? 'Custom' : 'Odoo'}: <span class="${className}">${statusText}</span>`;
        
        this.sourceStatus.innerHTML = this.sourceStatus.innerHTML.replace(regex, replacement);
    }
    
    getValidMimeType() {
        // If we have a valid video mime type, use it
        if (this.mimetype && this.mimetype.startsWith('video/')) {
            return this.mimetype;
        }
        
        // If mimetype is incorrect (like application/octet-stream), try to detect from URL
        const currentSrc = this.sources[this.currentSourceIndex];
        if (currentSrc && currentSrc.url) {
            // Try to extract file extension from URL
            const urlMatch = currentSrc.url.match(/\.([a-z0-9]+)(?:[?#]|$)/i);
            if (urlMatch) {
                const ext = urlMatch[1].toLowerCase();
                const mimeTypes = {
                    'mp4': 'video/mp4',
                    'webm': 'video/webm',
                    'mkv': 'video/x-matroska',
                    'avi': 'video/x-msvideo',
                    'mov': 'video/quicktime',
                    'flv': 'video/x-flv',
                    'm4v': 'video/mp4',
                    '3gp': 'video/3gpp'
                };
                
                if (mimeTypes[ext]) {
                    return mimeTypes[ext];
                }
            }
        }
        
        // Fallback to most common video format
        return 'video/mp4';
    }detection and playback
 */

class VideoPlayerManager {
    constructor(videoId, attachmentId, mimetype) {
        this.videoId = videoId;
        this.attachmentId = attachmentId;
        this.mimetype = mimetype;
        this.currentSourceIndex = 0;
        
        // DOM elements
        this.video = document.getElementById(`video-player-${videoId}`);
        this.source = document.getElementById(`video-source-${videoId}`);
        this.status = document.getElementById(`video-status-${videoId}`);
        this.sourceStatus = document.getElementById(`source-status-${videoId}`);
        this.customBtn = document.getElementById(`try-custom-${videoId}`);
        this.odooBtn = document.getElementById(`try-odoo-${videoId}`);
        
        // Video sources to try
        this.sources = [
            {
                url: `/my/video-translations/${videoId}/stream`,
                name: 'Custom Storage',
                type: 'custom'
            },
            {
                url: `/web/content/${attachmentId}?download=false`,
                name: 'Odoo Storage',
                type: 'odoo'
            }
        ];
        
        this.init();
    }
    
    init() {
        console.log(`Video Player initialized for video ${this.videoId}:`, {
            attachmentId: this.attachmentId,
            mimetype: this.mimetype,
            sources: this.sources
        });
        this.setupEventListeners();
        this.trySource(0); // Auto-start with first source
    }
    
    setupEventListeners() {
        // Video events
        this.video.addEventListener('loadstart', () => {
            const src = this.sources[this.currentSourceIndex];
            this.status.innerHTML = `<small class="text-info"><i class="fa fa-spinner fa-spin"></i> Loading from ${src.name}...</small>`;
        });
        
        this.video.addEventListener('canplay', () => {
            const src = this.sources[this.currentSourceIndex];
            this.status.innerHTML = `<small class="text-success"><i class="fa fa-check"></i> Playing from ${src.name}</small>`;
            this.updateSourceStatus(src.type, 'Working', true);
        });
        
        this.video.addEventListener('error', () => {
            const src = this.sources[this.currentSourceIndex];
            const error = this.video.error;
            let errorMessage = `${src.name} failed`;
            
            if (error) {
                switch(error.code) {
                    case error.MEDIA_ERR_ABORTED:
                        errorMessage += ' (playback aborted)';
                        break;
                    case error.MEDIA_ERR_NETWORK:
                        errorMessage += ' (network error)';
                        break;
                    case error.MEDIA_ERR_DECODE:
                        errorMessage += ' (decode error - file may be corrupted)';
                        break;
                    case error.MEDIA_ERR_SRC_NOT_SUPPORTED:
                        errorMessage += ' (format not supported)';
                        break;
                    default:
                        errorMessage += ' (unknown error)';
                }
                
                console.error(`Video error for ${src.name}:`, {
                    code: error.code,
                    message: error.message,
                    url: src.url
                });
            }
            
            this.status.innerHTML = `<small class="text-warning"><i class="fa fa-exclamation-triangle"></i> ${errorMessage}, trying next...</small>`;
            this.updateSourceStatus(src.type, 'Failed', false);
            
            // Try next source after a short delay
            setTimeout(() => {
                this.trySource(this.currentSourceIndex + 1);
            }, 1000);
        });
        
        // Button events
        this.customBtn.addEventListener('click', () => this.trySource(0));
        this.odooBtn.addEventListener('click', () => this.trySource(1));
    }
    
    updateSourceStatus(type, statusText, success) {
        const className = success ? 'text-success' : 'text-danger';
        const regex = type === 'custom' 
            ? /• Custom: <span class="[^"]*">.*?<\/span>/
            : /• Odoo: <span class="[^"]*">.*?<\/span>/;
        const replacement = `• ${type === 'custom' ? 'Custom' : 'Odoo'}: <span class="${className}">${statusText}</span>`;
        
        this.sourceStatus.innerHTML = this.sourceStatus.innerHTML.replace(regex, replacement);
    }
    
    trySource(index) {
        if (index >= this.sources.length) {
            this.status.innerHTML = '<small class="text-danger"><i class="fa fa-exclamation-triangle"></i> All sources failed</small>';
            return;
        }
        
        const src = this.sources[index];
        this.status.innerHTML = `<small class="text-info"><i class="fa fa-spinner fa-spin"></i> Trying ${src.name}...</small>`;
        
        this.source.src = src.url;
        
        // Try to set the correct MIME type, but don't set it if we can't determine it
        const validMimeType = this.getValidMimeType();
        if (validMimeType && validMimeType !== 'application/octet-stream') {
            this.source.type = validMimeType;
        } else {
            // Let the browser auto-detect by not setting type
            this.source.removeAttribute('type');
        }
        
        this.video.load();
        
        this.currentSourceIndex = index;
    }
    
    tryCustomSource() {
        this.trySource(0);
    }
    
    tryOdooSource() {
        this.trySource(1);
    }
}

// Global function to initialize video players
function initVideoPlayer(videoId, attachmentId, mimetype) {
    return new VideoPlayerManager(videoId, attachmentId, mimetype);
}

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // This will be called from the template with specific parameters
    console.log('Video Player Manager loaded');
});
