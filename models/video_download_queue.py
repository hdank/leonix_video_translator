from odoo import models, fields, api, _
import logging
import os
import subprocess
import tempfile
import json
import re
import hashlib
import shutil
import time
import signal
from odoo.exceptions import UserError
from pathlib import Path
from ..utils.video_utils import VideoDownloadUtils, VideoProgressTracker, VideoFileManager
from ..utils.progress_utils import DownloadProgressNotifier, VideoQualityOptimizer
from ..utils.video_extractor import VideoExtractor
try:
    from ..utils.resource_manager import ResourceManager
    RESOURCE_MANAGER_AVAILABLE = True
except ImportError:
    RESOURCE_MANAGER_AVAILABLE = False
    _logger = logging.getLogger(__name__)
    _logger.warning("Resource manager not available. Install psutil for better resource management.")

_logger = logging.getLogger(__name__)

class VideoDownloadQueue(models.Model):
    _name = 'leonix.video.download.queue'
    _description = 'Video Download Queue'
    _order = 'create_date desc'
    
    video_translator_id = fields.Many2one('leonix.video.translator', string='Video Translation', required=True, ondelete='cascade')
    video_url = fields.Char(string='Video URL', required=True)
    video_platform = fields.Selection([
        ('youtube', 'YouTube'),
        ('tiktok', 'TikTok'),
        ('other', 'Other')
    ], string='Video Platform')
    url_hash = fields.Char(string='URL Hash', index=True)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('failed', 'Failed')
    ], default='pending', string='State')
    result = fields.Text(string='Result', readonly=True)
    progress = fields.Float(string='Progress (%)', default=0.0)
    download_speed = fields.Char(string='Download Speed')
    estimated_time = fields.Char(string='ETA')
    
    def _send_completion_notification(self):
        """Send notification when download is complete"""
        self.video_translator_id.message_post(
            body=_("Video successfully downloaded and is ready to watch!"),
            message_type='notification'
        )
        
    def _check_system_resources(self, video_info):
        """Check if system has enough resources for download"""
        if not RESOURCE_MANAGER_AVAILABLE:
            return {'can_proceed': True}
            
        # Estimate video size
        estimated_size_mb = VideoQualityOptimizer.estimate_file_size(video_info)
        
        # Check resources
        resource_check = ResourceManager.check_system_resources(estimated_size_mb)
        
        # Log warnings
        for warning in resource_check.get('warnings', []):
            _logger.warning(warning)
            
        return resource_check
        
    def _terminate_process(self, process, timeout=5):
        """Terminate a process gracefully"""
        if not process:
            return
            
        try:
            # Try graceful termination first
            process.terminate()
            try:
                process.wait(timeout=timeout)  # Wait for graceful termination
            except subprocess.TimeoutExpired:
                _logger.warning("Process did not terminate gracefully, killing")
                process.kill()
                process.wait(timeout=3)  # Wait for kill
        except Exception as e:
            _logger.error("Error terminating process: %s", str(e))
            # Make sure it's dead
            try:
                os.kill(process.pid, signal.SIGKILL)
            except:
                pass
                
    @api.model
    def process_pending_downloads(self):
        """Process pending downloads - to be called by cron job"""
        # Process up to 3 downloads simultaneously to improve throughput
        pending_downloads = self.search([('state', '=', 'pending')], limit=3, order='create_date asc')
        
        if not pending_downloads:
            return
            
        _logger.info("Processing %d pending downloads", len(pending_downloads))
        
        # Process each download
        for download in pending_downloads:
            try:
                # Check if there's already a processing download for this video
                existing_processing = self.search([
                    ('video_translator_id', '=', download.video_translator_id.id),
                    ('state', '=', 'processing'),
                    ('id', '!=', download.id)
                ])
                
                if existing_processing:
                    _logger.info("Skipping download %s - already processing", download.id)
                    download.write({'state': 'failed', 'result': 'Another download already in progress'})
                    continue
                    
                # Process the download
                download._process_download()
                
            except Exception as e:
                _logger.error("Error processing download %s: %s", download.id, e)
                download.write({
                    'state': 'failed',
                    'result': f'Processing error: {str(e)}'
                })
                
        # Also check for stuck downloads (processing for more than 30 minutes)
        self._cleanup_stuck_downloads()
    
    @api.model 
    def _cleanup_stuck_downloads(self):
        """Clean up downloads that have been stuck in processing state"""
        import datetime
        thirty_minutes_ago = datetime.datetime.now() - datetime.timedelta(minutes=30)
        
        stuck_downloads = self.search([
            ('state', '=', 'processing'),
            ('write_date', '<', thirty_minutes_ago)
        ])
        
        for stuck in stuck_downloads:
            _logger.warning("Cleaning up stuck download: %s", stuck.id)
            stuck.write({
                'state': 'failed', 
                'result': 'Download timed out after 30 minutes'
            })
            # Reset the associated video translator state
            if stuck.video_translator_id:
                stuck.video_translator_id.write({'state': 'failed'})
    
    def _process_download(self):
        """Download the video using yt-dlp with progress tracking"""
        self.ensure_one()
        
        if not self.video_url:
            self.write({
                'state': 'failed',
                'result': 'No URL provided'
            })
            return False
            
        self.write({'state': 'processing', 'progress': 0.0})
        
        # Check if yt-dlp is installed
        if not VideoDownloadUtils.check_ytdlp_installation():
            self.write({
                'state': 'failed',
                'result': 'yt-dlp is not installed. Please install it with: pip install yt-dlp'
            })
            return False
        
        try:
            # Get video info
            _logger.info("Getting video info for URL: %s", self.video_url)
            video_info = VideoDownloadUtils.get_video_info(self.video_url)
            video_title = video_info.get('title', 'Unknown')
            video_duration = video_info.get('duration', 0)
            safe_title = VideoDownloadUtils.sanitize_filename(video_title)
            
            _logger.debug("Video details: title=%s, duration=%s", video_title, video_duration)
            
            # Check system resources
            resource_check = self._check_system_resources(video_info)
            if not resource_check.get('can_proceed', True):
                self.write({
                    'state': 'failed',
                    'result': "Insufficient system resources for download. " + 
                             "; ".join(resource_check.get('warnings', []))
                })
                self.video_translator_id.write({'state': 'failed'})
                return False
            
            # Check for existing video files in storage
            storage_path = VideoDownloadUtils.get_storage_path(self.env, self.video_platform or 'other')
            url_hash_short = self.url_hash[:12] if self.url_hash else ""
            
            existing_file = None
            if os.path.exists(storage_path):
                for filename in os.listdir(storage_path):
                    if url_hash_short in filename and any(filename.lower().endswith(ext) for ext in ['.mp4', '.webm', '.mkv', '.avi']):
                        existing_file_path = os.path.join(storage_path, filename)
                        if os.path.exists(existing_file_path):
                            existing_file = existing_file_path
                            break
            
            if existing_file:
                # Reuse existing file
                file_stats = os.stat(existing_file)
                file_size = file_stats.st_size
                file_ext = Path(existing_file).suffix.lower()
                mime_type = self._get_mime_type_from_extension(file_ext)
                
                self.video_translator_id.write({
                    'video_file_path': existing_file,
                    'video_file_size': file_size,
                    'video_duration': video_duration,
                    'video_format': mime_type,
                    'download_progress': 100.0,
                    'state': 'downloaded'
                })
                
                self.write({
                    'state': 'done',
                    'progress': 100.0,
                    'result': f"Video reused from existing file: {os.path.basename(existing_file)}"
                })
                return True
            
            # Download video
            storage_path = VideoDownloadUtils.get_storage_path(self.env, self.video_platform)
            filename_template = f"{safe_title}_%(id)s.%(ext)s"
            output_path = os.path.join(storage_path, filename_template)
            
            # Register with progress notifier
            notifier = DownloadProgressNotifier()
            notifier.register_download(self.video_translator_id.id, self)
            
            # Auto-detect platform if not set
            if not self.video_platform or self.video_platform == 'other':
                detected_platform = VideoExtractor.detect_platform(self.video_url)
                if detected_platform != 'other':
                    _logger.info("Auto-detected platform: %s", detected_platform)
                    self.video_platform = detected_platform
            
            # Create progress tracker
            progress_tracker = VideoProgressTracker(self)
            
            # Simple yt-dlp command - let yt-dlp handle everything automatically
            cmd = [
                'yt-dlp',
                '-o', output_path,
                '--no-playlist',
                '--merge-output-format', 'mp4',  # Ensure final format is MP4
                self.video_url
            ]
            
            _logger.info("=== DOWNLOAD EXECUTION DEBUG ===")
            _logger.info("Video URL: %s", self.video_url)
            _logger.info("Platform: %s", self.video_platform)
            _logger.info("Storage path: %s", storage_path)
            _logger.info("Safe title: %s", safe_title)
            _logger.info("Output path: %s", output_path)
            _logger.info("Full command: %s", ' '.join(cmd))
            
            # Check if yt-dlp is available
            try:
                ytdlp_version = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True, timeout=10)
                _logger.info("yt-dlp version: %s", ytdlp_version.stdout.strip() if ytdlp_version.returncode == 0 else "ERROR")
            except Exception as e:
                _logger.warning("Could not check yt-dlp version: %s", e)
            
            # Check if storage directory exists and is writable
            _logger.info("Storage directory exists: %s", os.path.exists(storage_path))
            _logger.info("Storage directory writable: %s", os.access(storage_path, os.W_OK) if os.path.exists(storage_path) else "N/A")
            
            _logger.info("Starting yt-dlp process...")
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                     text=True, bufsize=1, universal_newlines=True)
            
            # Set up monitoring variables
            start_time = time.time()
            last_progress_time = start_time
            last_progress = 0
            
            # Capture all output for logging and debugging
            full_output = []
            error_output = []
            
            _logger.info("yt-dlp process started, monitoring output...")
            
            # Monitor the process output until it completes naturally
            # Add a very generous timeout (30 minutes) as a safety net only
            max_total_time = 1800  # 30 minutes
            
            try:
                for line in iter(process.stdout.readline, ''):
                    if not line:  # Empty line indicates end of output
                        break
                        
                    # Safety check - only terminate if really excessive time has passed
                    current_time = time.time()
                    if current_time - start_time > max_total_time:
                        _logger.error("Download exceeded maximum time limit of 30 minutes, terminating")
                        self._terminate_process(process)
                        break
                        
                    line_stripped = line.strip()
                    if line_stripped:  # Only log non-empty lines
                        full_output.append(line_stripped)
                        _logger.debug("yt-dlp: %s", line_stripped)
                        
                        # Capture potential error lines for better debugging
                        if any(keyword in line_stripped.lower() for keyword in ['error', 'warning', 'failed', 'unable']):
                            error_output.append(line_stripped)
                            _logger.warning("yt-dlp potential issue: %s", line_stripped)
                        
                        # Track progress if available
                        if '[download]' in line_stripped and '%' in line_stripped:
                            current_progress = self._parse_ytdlp_progress(line_stripped, progress_tracker)
                            if current_progress:
                                last_progress_time = time.time()
                                last_progress = current_progress
                
                # Wait for process to complete naturally
                _logger.info("yt-dlp output ended, waiting for process completion...")
                process.wait()  # Let yt-dlp finish completely
                
            except Exception as e:
                _logger.error("Error monitoring yt-dlp process: %s", e)
                # Don't terminate the process here, let it complete
                try:
                    process.wait(timeout=60)  # Give it 1 more minute to finish
                except subprocess.TimeoutExpired:
                    _logger.warning("Process still running after error, will terminate")
                    self._terminate_process(process)
            
            # Handle timeout case
            if time.time() - start_time > max_total_time:
                _logger.error("Download timed out after 30 minutes")
                self._cleanup_partial_downloads(storage_path, safe_title)
                self.write({
                    'state': 'failed',
                    'result': "Download timed out after 30 minutes"
                })
                self.video_translator_id.write({'state': 'failed'})
                return False
            
            # Check the exit code after process completion
            elapsed_time = time.time() - start_time
            _logger.info("yt-dlp process completed in %.2f seconds with exit code: %s", elapsed_time, process.returncode)
            
            if process.returncode != 0:
                _logger.error("Download failed with exit code %s", process.returncode)
                
                # Log the last 10 lines of output for debugging
                if full_output:
                    _logger.error("Last 10 lines of yt-dlp output:")
                    for line in full_output[-10:]:
                        _logger.error("  > %s", line)
                
                # Log specific error lines if any
                if error_output:
                    _logger.error("yt-dlp error messages:")
                    for error_line in error_output[-5:]:  # Last 5 error messages
                        _logger.error("  ERROR: %s", error_line)
                
                # Create user-friendly error message
                error_message = "Download failed"
                all_output = '\n'.join(full_output).lower()
                
                if 'video unavailable' in all_output or 'private video' in all_output:
                    error_message = "Video is unavailable or private"
                elif 'sign in to confirm your age' in all_output:
                    error_message = "Video requires age verification"
                elif 'this video is not available in your country' in all_output:
                    error_message = "Video is geo-restricted"
                elif 'copyright' in all_output:
                    error_message = "Video has copyright restrictions"
                elif 'network' in all_output or 'connection' in all_output:
                    error_message = "Network connectivity issue"
                elif 'quota exceeded' in all_output:
                    error_message = "API quota exceeded"
                elif 'format' in all_output and 'not available' in all_output:
                    error_message = "No suitable video format available"
                else:
                    error_message = f"yt-dlp failed (exit code {process.returncode})"
                
                # Clean up any partial downloads
                self._cleanup_partial_downloads(storage_path, safe_title)
                
                self.write({
                    'state': 'failed',
                    'result': error_message
                })
                self.video_translator_id.write({'state': 'failed'})
                return False
            
            # Find downloaded file
            _logger.info("=== FILE SEARCH DEBUG ===")
            _logger.info("Looking for files in: %s", storage_path)
            _logger.info("Searching for files containing: %s", safe_title)
            
            all_files = os.listdir(storage_path)
            _logger.info("All files in directory: %s", all_files)
            
            downloaded_files = []
            for file in all_files:
                if safe_title in file and not file.endswith('.info.json'):
                    downloaded_files.append(file)
                    _logger.info("Found matching video file: %s", file)
            
            _logger.info("Downloaded files found: %s", downloaded_files)
            
            if not downloaded_files:
                _logger.error("No video files found after successful download!")
                _logger.error("Expected to find files containing: %s", safe_title)
                _logger.error("Available files: %s", all_files)
                
                self.write({
                    'state': 'failed',
                    'result': f"Download completed but no files found. Expected files containing '{safe_title}'. Available files: {all_files}"
                })
                return False
            
            video_file = downloaded_files[0]
            video_file_path = os.path.join(storage_path, video_file)
            
            _logger.info("Selected video file: %s", video_file)
            _logger.info("Full video file path: %s", video_file_path)
            
            # Validate the downloaded file before creating attachment
            _logger.info("Downloaded file: %s (Size: %.2f MB)", 
                        video_file, os.path.getsize(video_file_path) / (1024*1024))
            
            # Check if file is valid
            if os.path.getsize(video_file_path) < 1024:  # Less than 1KB is suspicious
                self.write({
                    'state': 'failed',
                    'result': f"Downloaded file is too small ({os.path.getsize(video_file_path)} bytes)"
                })
                return False
            
            # Quick header check
            try:
                with open(video_file_path, 'rb') as f:
                    header = f.read(16)
                    _logger.info("File header (first 16 bytes): %s", header.hex())
            except Exception as e:
                _logger.error("Failed to read file header: %s", e)
            
            # Store video file path directly instead of creating attachment
            video_stats = os.stat(video_file_path)
            file_size = video_stats.st_size
            
            # Get video format from file extension
            video_format = Path(video_file_path).suffix.lower()
            mime_type = self._get_mime_type_from_extension(video_format)
            
            # Update video translator record with file path instead of attachment
            self.video_translator_id.write({
                'video_file_path': video_file_path,  # Store file path instead of attachment
                'video_file_size': file_size,
                'video_duration': video_duration,
                'video_format': mime_type,
                'download_progress': 100.0,
                'state': 'downloaded'
            })
            
            # Clean up info.json files
            temp_files = [
                video_file_path.replace(Path(video_file_path).suffix, '.info.json')
            ]
            self._cleanup_temp_files(temp_files)
            
            self.write({
                'state': 'done',
                'progress': 100.0,
                'result': f"Download completed: {safe_title} ({VideoDownloadUtils.format_file_size(file_size)})"
            })
            
            # Notify completion
            notifier.finish_download(self.video_translator_id.id, success=True)
            self._send_completion_notification()
            return True
            
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            _logger.exception("Error during video download: %s", str(e))
            _logger.debug("Error trace: %s", error_trace)
            
            # Kill any lingering processes
            try:
                if 'process' in locals() and process:
                    self._terminate_process(process)
            except:
                pass
                
            # Clean up any partial downloads
            try:
                if 'storage_path' in locals() and 'safe_title' in locals():
                    self._cleanup_partial_downloads(storage_path, safe_title)
            except:
                pass
                
            # Notify failure
            notifier = DownloadProgressNotifier()
            notifier.finish_download(self.video_translator_id.id, success=False)
            
            # Create a user-friendly error message
            error_msg = str(e).lower()
            user_message = str(e)
            
            # Check for common error patterns and provide user-friendly messages
            if "http error 429" in error_msg:
                user_message = "Service temporarily unavailable (rate limit). Please try again later."
            elif "http error" in error_msg:
                user_message = f"Service error. Please try again or try a different URL."
            elif "video is unavailable" in error_msg or "private video" in error_msg:
                user_message = "This video is unavailable or private."
            elif "network error" in error_msg or "connection" in error_msg:
                user_message = "Network error. Please check your internet connection and try again."
            elif "no space" in error_msg:
                user_message = "Not enough disk space to complete download."
            elif "timeout" in error_msg:
                user_message = "Connection timed out. The server may be busy, please try again later."
            elif "format" in error_msg and "available" in error_msg:
                user_message = "No suitable video format available. The video might be protected."
                
            _logger.error("Download failed: %s", user_message)
            
            self.write({
                'state': 'failed',
                'result': f"Error: {user_message}"
            })
            self.video_translator_id.write({'state': 'failed'})
            return False
    
    def _parse_ytdlp_progress(self, line, progress_tracker):
        """Parse progress information from yt-dlp output"""
        try:
            # First, try detailed pattern with size and speed
            # Example: [download]  45.2% of 15.30MiB at 2.45MiB/s ETA 00:03
            match = re.search(r'\[download\]\s+(\d+(?:\.\d+)?)%.*?(?:of\s+([^\s]+)\s+)?(?:at\s+([^\s]+)\s+)?(?:ETA\s+([^\s]+))?', line)
            
            if match:
                progress = float(match.group(1))
                file_size = match.group(2) if len(match.groups()) > 1 and match.group(2) else "Unknown"
                speed = match.group(3) if len(match.groups()) > 2 and match.group(3) else "Unknown"
                eta = match.group(4) if len(match.groups()) > 3 and match.group(4) else "Unknown"
                
                _logger.debug("Progress: %s%%, Size: %s, Speed: %s, ETA: %s", 
                             progress, file_size, speed, eta)
                
                progress_data = {
                    'downloaded_bytes': progress,  # We'll use progress directly
                    'total_bytes': 100.0,
                    'speed': speed,
                    'eta': eta
                }
                progress_tracker.update_progress(progress_data)
                return progress
            
            # Try simpler pattern with just percentage
            simple_match = re.search(r'\[download\]\s+(\d+(?:\.\d+)?)%', line)
            if simple_match:
                progress = float(simple_match.group(1))
                _logger.debug("Progress (simple): %s%%", progress)
                
                progress_data = {
                    'downloaded_bytes': progress,
                    'total_bytes': 100.0,
                    'speed': "Unknown",
                    'eta': "Unknown"
                }
                progress_tracker.update_progress(progress_data)
                return progress
                
            # No progress info found
            return None
            
        except Exception as e:
            _logger.debug("Failed to parse progress line: %s, error: %s", line, str(e))
            return None
    
    def _cleanup_partial_downloads(self, storage_path, file_pattern):
        """Clean up any partial downloads from failed attempts"""
        try:
            cleanup_count = 0
            for file in os.listdir(storage_path):
                if file_pattern in file:
                    # Delete the file
                    file_path = os.path.join(storage_path, file)
                    try:
                        os.unlink(file_path)
                        cleanup_count += 1
                    except Exception as e:
                        _logger.warning("Failed to delete partial download: %s - %s", file, str(e))
            
            if cleanup_count > 0:
                _logger.info("Cleaned up %s partial download files", cleanup_count)
        except Exception as e:
            _logger.error("Error during cleanup of partial downloads: %s", str(e))
    
    def _update_progress_from_data(self, data):
        """Update progress from yt-dlp progress data"""
        downloaded = data.get('downloaded_bytes', 0)
        total = data.get('total_bytes', 0)
        
        if total > 0:
            progress = (downloaded / total) * 100
            speed = data.get('speed', 0)
            eta = data.get('eta', 0)
            
            speed_str = f"{speed / 1024 / 1024:.1f} MB/s" if speed else "Unknown"
            eta_str = f"{eta}s" if eta else "Unknown"
            
            self.write({
                'progress': progress,
                'download_speed': speed_str,
                'estimated_time': eta_str
            })
            
            self.video_translator_id.write({
                'download_progress': progress,
                'download_speed': speed_str,
                'estimated_time': eta_str
            })
    
    def _get_mime_type_from_extension(self, extension):
        """Get MIME type from file extension"""
        mime_map = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm', 
            '.mkv': 'video/x-matroska',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.flv': 'video/x-flv',
            '.m4v': 'video/mp4'
        }
        return mime_map.get(extension.lower(), 'video/mp4')
    
    def _cleanup_temp_files(self, temp_files):
        """Clean up temporary files"""
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    _logger.debug("Cleaned up temp file: %s", temp_file)
                except Exception as e:
                    _logger.warning("Failed to clean up temp file %s: %s", temp_file, e)
    
    def _send_completion_notification(self):
        """Send notification when download is complete"""
        self.video_translator_id.message_post(
            body=_("Video successfully downloaded and is ready to watch!"),
            message_type='notification'
        )
