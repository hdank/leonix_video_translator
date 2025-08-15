import os
import psutil
import logging
from odoo import _

_logger = logging.getLogger(__name__)

class ResourceManager:
    """
    Class to manage system resources for video download operations
    """
    
    # Minimum recommended free memory (in MB)
    MIN_FREE_MEMORY_MB = 200
    
    # Minimum recommended free disk space (in MB)
    MIN_FREE_DISK_MB = 500
    
    @classmethod
    def check_system_resources(cls, estimated_video_size_mb=0):
        """
        Check if system has enough resources for the video download operation
        
        Args:
            estimated_video_size_mb: Estimated size of video to download in MB
            
        Returns:
            dict: Status of resource check with details
        """
        result = {
            'can_proceed': True,
            'warnings': [],
        }
        
        # Check memory
        free_memory_mb = cls.get_free_memory_mb()
        if free_memory_mb < cls.MIN_FREE_MEMORY_MB:
            result['warnings'].append(_(
                f"Low memory warning: Only {free_memory_mb}MB free memory available. "
                f"This may affect download performance."
            ))
            _logger.warning(f"Low memory for video download: {free_memory_mb}MB free")
            
        # Check disk space
        free_disk_mb = cls.get_free_disk_mb()
        required_disk_mb = max(estimated_video_size_mb * 2, cls.MIN_FREE_DISK_MB)
        
        if free_disk_mb < required_disk_mb:
            result['can_proceed'] = False
            result['warnings'].append(_(
                f"Insufficient disk space: {free_disk_mb}MB available, but at least "
                f"{required_disk_mb}MB required for this operation."
            ))
            _logger.error(f"Insufficient disk space for video download: {free_disk_mb}MB free, {required_disk_mb}MB required")
        elif free_disk_mb < required_disk_mb * 2:
            result['warnings'].append(_(
                f"Low disk space warning: Only {free_disk_mb}MB available."
            ))
            _logger.warning(f"Low disk space for video download: {free_disk_mb}MB free")
            
        return result
    
    @classmethod
    def get_free_memory_mb(cls):
        """Get free memory in MB"""
        try:
            memory = psutil.virtual_memory()
            return int(memory.available / 1024 / 1024)
        except Exception as e:
            _logger.warning(f"Could not determine free memory: {e}")
            return 1000  # Default assumption
    
    @classmethod
    def get_free_disk_mb(cls):
        """Get free disk space in MB for the data directory"""
        try:
            # Use the temp directory as a reference point
            disk = psutil.disk_usage(os.path.abspath(os.sep))
            return int(disk.free / 1024 / 1024)
        except Exception as e:
            _logger.warning(f"Could not determine free disk space: {e}")
            return 10000  # Default assumption
            
    @classmethod
    def monitor_download_process(cls, process):
        """Monitor a download process for resource usage"""
        try:
            process_info = psutil.Process(process.pid)
            memory_mb = process_info.memory_info().rss / 1024 / 1024
            cpu_percent = process_info.cpu_percent()
            
            _logger.debug(f"Download process: {memory_mb:.1f}MB memory, {cpu_percent}% CPU")
            
            # If process is using too much memory, consider restarting it
            if memory_mb > 1000:  # Over 1GB
                _logger.warning(f"Download process using excessive memory: {memory_mb:.1f}MB")
                return True  # Signal potential issue
                
            return False  # No issues detected
            
        except Exception as e:
            _logger.error(f"Error monitoring download process: {e}")
            return False
