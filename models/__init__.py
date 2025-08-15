# -*- coding: utf-8 -*-

from . import video_translator
from . import video_download_queue
from . import res_config_settings

import atexit
import threading
import logging

_logger = logging.getLogger(__name__)

def cleanup_module_threads():
    """Clean up any remaining threads when module is unloaded"""
    try:
        # Get all active threads
        active_threads = threading.enumerate()
        
        # Find threads related to our module
        module_threads = [
            t for t in active_threads 
            if hasattr(t, 'name') and (
                'VideoDownloader' in t.name
            )
        ]
        
        for thread in module_threads:
            if thread.is_alive():
                _logger.info(f"Cleaning up thread: {thread.name}")
                thread.join(timeout=2.0)  # Wait up to 2 seconds
                
    except Exception as e:
        _logger.error(f"Error during thread cleanup: {e}")

# Register cleanup function
atexit.register(cleanup_module_threads)
