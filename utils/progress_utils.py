from odoo import _
import threading
import time
import logging

_logger = logging.getLogger(__name__)

class DownloadProgressNotifier:
    """Real-time progress notification system for video downloads"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(DownloadProgressNotifier, cls).__new__(cls)
                    cls._instance.active_downloads = {}
                    cls._instance.progress_callbacks = {}
        return cls._instance
    
    def register_download(self, video_id, queue_record):
        """Register a new download for progress tracking"""
        self.active_downloads[video_id] = {
            'queue_record': queue_record,
            'start_time': time.time(),
            'last_update': time.time()
        }
        _logger.info(f"Registered download for video {video_id}")
    
    def update_progress(self, video_id, progress_data):
        """Update progress for a specific video download"""
        if video_id in self.active_downloads:
            download_info = self.active_downloads[video_id]
            download_info['last_update'] = time.time()
            download_info['progress_data'] = progress_data
            
            # Execute any registered callbacks
            if video_id in self.progress_callbacks:
                for callback in self.progress_callbacks[video_id]:
                    try:
                        callback(progress_data)
                    except Exception as e:
                        _logger.error(f"Progress callback failed: {e}")
    
    def finish_download(self, video_id, success=True):
        """Mark download as finished and clean up"""
        if video_id in self.active_downloads:
            download_info = self.active_downloads[video_id]
            total_time = time.time() - download_info['start_time']
            
            _logger.info(f"Download finished for video {video_id}: "
                        f"{'Success' if success else 'Failed'} in {total_time:.1f}s")
            
            # Clean up
            del self.active_downloads[video_id]
            if video_id in self.progress_callbacks:
                del self.progress_callbacks[video_id]
    
    def register_callback(self, video_id, callback):
        """Register a callback for progress updates"""
        if video_id not in self.progress_callbacks:
            self.progress_callbacks[video_id] = []
        self.progress_callbacks[video_id].append(callback)
    
    def get_active_downloads(self):
        """Get list of currently active downloads"""
        return list(self.active_downloads.keys())
    
    def is_download_active(self, video_id):
        """Check if a download is currently active"""
        return video_id in self.active_downloads

class VideoQualityOptimizer:
    """Utility class to optimize video quality vs storage"""
    
    QUALITY_PRESETS = {
        'low': {
            'format': 'worst[ext=mp4][vcodec!*=av01]/worst[ext=webm]/worst[height<=360]/worst',
            'description': '360p or lower (smallest file)',
            'target_size_mb': 50
        },
        'medium': {
            'format': 'best[height<=480][ext=mp4][vcodec!*=av01]/best[height<=720][ext=mp4][vcodec!*=av01]/best[ext=mp4][vcodec!*=av01]/best[ext=webm]/best',
            'description': '480-720p (balanced)',
            'target_size_mb': 150
        },
        'high': {
            'format': 'best[height<=720][ext=mp4][vcodec!*=av01]/best[ext=mp4][vcodec!*=av01]/best[ext=webm]/best',
            'description': '720p (good quality)',
            'target_size_mb': 300
        },
        'auto': {
            'format': 'best[filesize<200M][ext=mp4][vcodec!*=av01]/best[height<=720][ext=mp4][vcodec!*=av01]/best[ext=mp4][vcodec!*=av01]/best[ext=webm]/best',
            'description': 'Auto (browser-compatible, size limited)',
            'target_size_mb': 200
        }
    }
    
    @classmethod
    def get_optimal_format(cls, video_info, preference='auto'):
        """Get optimal video format based on preferences and video info"""
        if preference in cls.QUALITY_PRESETS:
            return cls.QUALITY_PRESETS[preference]['format']
        
        # Auto-select based on duration and estimated size
        duration = video_info.get('duration', 0)
        
        if duration > 3600:  # >1 hour
            return cls.QUALITY_PRESETS['medium']['format']
        elif duration > 1800:  # >30 minutes
            return cls.QUALITY_PRESETS['high']['format']
        else:
            return cls.QUALITY_PRESETS['high']['format']
    
    @classmethod
    def estimate_file_size(cls, video_info, quality='medium'):
        """Estimate file size based on video info and quality"""
        duration = video_info.get('duration', 0)
        if not duration:
            return 0
        
        # Rough estimates based on typical bitrates
        bitrate_estimates = {
            'low': 0.5,     # Mbps
            'medium': 1.5,   # Mbps
            'high': 3.0,     # Mbps
            'auto': 2.0      # Mbps
        }
        
        bitrate = bitrate_estimates.get(quality, 2.0)
        estimated_mb = (duration * bitrate * 60) / (8 * 1024)  # Convert to MB
        
        return int(estimated_mb)

class StorageManager:
    """Manage video storage and cleanup"""
    
    def __init__(self, env):
        self.env = env
    
    def cleanup_old_files(self, days_old=30):
        """Clean up old video files to save storage"""
        cutoff_date = time.time() - (days_old * 24 * 60 * 60)
        
        old_attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'leonix.video.translator'),
            ('create_date', '<', cutoff_date)
        ])
        
        total_size_freed = 0
        for attachment in old_attachments:
            # Check if the video record still exists and is being used
            video_records = self.env['leonix.video.translator'].search([
                ('video_attachment_id', '=', attachment.id)
            ])
            
            if not video_records:
                total_size_freed += attachment.file_size or 0
                attachment.unlink()
                _logger.info(f"Cleaned up orphaned video file: {attachment.name}")
        
        return total_size_freed
    
    def get_storage_stats(self):
        """Get storage statistics for video files"""
        video_attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'leonix.video.translator')
        ])
        
        total_files = len(video_attachments)
        total_size = sum(att.file_size or 0 for att in video_attachments)
        
        return {
            'total_files': total_files,
            'total_size_mb': total_size / (1024 * 1024),
            'average_size_mb': (total_size / total_files / (1024 * 1024)) if total_files > 0 else 0
        }
    
    def find_duplicates(self):
        """Find duplicate video files that can be consolidated"""
        video_records = self.env['leonix.video.translator'].search([
            ('video_file_hash', '!=', False)
        ])
        
        hash_groups = {}
        for record in video_records:
            if record.video_file_hash not in hash_groups:
                hash_groups[record.video_file_hash] = []
            hash_groups[record.video_file_hash].append(record)
        
        # Find groups with multiple records (duplicates)
        duplicates = {hash_val: records for hash_val, records in hash_groups.items() 
                     if len(records) > 1}
        
        return duplicates
