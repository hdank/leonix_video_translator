from odoo import _
import logging
import re

_logger = logging.getLogger(__name__)

class VideoExtractor:
    """Class to handle video platform detection and URL normalization"""
    
    # Platform detection patterns
    PLATFORM_PATTERNS = {
        'youtube': [
            r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=)?([a-zA-Z0-9_-]{11})',
            r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})'
        ],
        'tiktok': [
            r'(?:https?:\/\/)?(?:www\.)?tiktok\.com\/@[^\/]+\/video\/(\d+)',
            r'(?:https?:\/\/)?(?:www\.)?vm\.tiktok\.com\/([a-zA-Z0-9]+)'
        ],
        'vimeo': [
            r'(?:https?:\/\/)?(?:www\.)?vimeo\.com\/(\d+)'
        ],
        'facebook': [
            r'(?:https?:\/\/)?(?:www\.)?facebook\.com\/[^\/]+\/videos\/(\d+)'
        ],
        'instagram': [
            r'(?:https?:\/\/)?(?:www\.)?instagram\.com\/(?:p|reel)\/([a-zA-Z0-9_-]+)'
        ],
        'twitter': [
            r'(?:https?:\/\/)?(?:www\.)?twitter\.com\/\w+\/status\/(\d+)'
        ],
    }
    
    @classmethod
    def detect_platform(cls, url):
        """Detect video platform from URL"""
        if not url:
            return 'other'
            
        for platform, patterns in cls.PLATFORM_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, url):
                    _logger.debug("Detected %s video from URL: %s", platform, url)
                    return platform
                    
        return 'other'
    
    @classmethod
    def extract_video_id(cls, url, platform=None):
        """Extract video ID from URL"""
        if not url:
            return None
            
        if not platform:
            platform = cls.detect_platform(url)
            
        if platform == 'other':
            return None
            
        for pattern in cls.PLATFORM_PATTERNS.get(platform, []):
            match = re.search(pattern, url)
            if match:
                return match.group(1)
                
        return None
    
    @classmethod
    def get_download_options(cls, platform):
        """Get platform-specific download options"""
        options = {
            'youtube': [
            ],
            'tiktok': [
                '--referer', 'https://www.tiktok.com/',
                '--add-header', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            ],
            'instagram': [
                '--add-header', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                '--add-header', 'Cookie: ig_pr=1; ig_vw=1920'
            ],
            'twitter': [
                '--referer', 'https://twitter.com/'
            ]
        }
        
        return options.get(platform, [])
