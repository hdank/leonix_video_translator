from odoo import _
import hashlib
import os
import json
import re
import subprocess
import tempfile
import logging
import base64
from pathlib import Path

_logger = logging.getLogger(__name__)

class VideoDownloadUtils:
    """Utility class for video download operations"""
    
    @staticmethod
    def get_url_hash(url):
        """Generate a hash for the URL to check for duplicates"""
        return hashlib.sha256(url.encode()).hexdigest()
    
    @staticmethod
    def get_storage_path(env, platform='other'):
        """Get optimized storage path for videos"""
        storage_root = os.path.join(env['ir.attachment']._filestore(), 'leonix_videos')
        os.makedirs(storage_root, exist_ok=True)
        
        platform_dir = os.path.join(storage_root, platform)
        os.makedirs(platform_dir, exist_ok=True)
        
        return platform_dir
    
    @staticmethod
    def check_ytdlp_installation():
        """Check if yt-dlp is installed"""
        try:
            subprocess.check_output(['yt-dlp', '--version'], stderr=subprocess.DEVNULL)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
    
    @staticmethod
    def get_video_info(url):
        """Get video information using yt-dlp"""
        info_cmd = ['yt-dlp', '--dump-json', '--no-playlist', url]
        result = subprocess.run(info_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Failed to get video info: {result.stderr}")
        
        return json.loads(result.stdout)
    
    @staticmethod
    def sanitize_filename(title, max_length=50):
        """Clean filename for safe storage"""
        return re.sub(r'[^\w\s-]', '', title)[:max_length]
    
    @staticmethod
    def get_mime_type(file_extension):
        """Get MIME type based on file extension"""
        mime_types = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.mkv': 'video/x-matroska',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.flv': 'video/x-flv'
        }
        return mime_types.get(file_extension.lower(), 'video/mp4')
    
    @staticmethod
    def format_file_size(size_bytes):
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024.0 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f} {size_names[i]}"
    
    @staticmethod
    def format_duration(seconds):
        """Format duration in human readable format"""
        if not seconds:
            return "Unknown"
        
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

class VideoProgressTracker:
    """Class to handle video download progress tracking"""
    
    def __init__(self, queue_record):
        self.queue_record = queue_record
        
    def update_progress(self, progress_data):
        """Update progress from yt-dlp progress data"""
        downloaded = progress_data.get('downloaded_bytes', 0)
        total = progress_data.get('total_bytes', 0)
        
        if total > 0:
            progress = (downloaded / total) * 100
            speed = progress_data.get('speed', 0)
            eta = progress_data.get('eta', 0)
            
            speed_str = f"{speed / 1024 / 1024:.1f} MB/s" if speed else "Unknown"
            eta_str = f"{eta}s" if eta else "Unknown"
            
            # Update queue record
            self.queue_record.write({
                'progress': progress,
                'download_speed': speed_str,
                'estimated_time': eta_str
            })
            
            # Update video translator record
            self.queue_record.video_translator_id.write({
                'download_progress': progress,
                'download_speed': speed_str,
                'estimated_time': eta_str
            })
            
            # Commit to make progress visible immediately
            self.queue_record.env.cr.commit()

class VideoFileManager:
    """Class to handle video file storage and management"""
    
    def __init__(self, env):
        self.env = env
    
    def create_attachment(self, file_path, video_record, video_info):
        """Create attachment from downloaded video file"""
        # Validate file exists and is not empty
        if not os.path.exists(file_path):
            raise Exception(f"Video file not found: {file_path}")
            
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise Exception(f"Video file is empty: {file_path}")
        
        # Check if it's actually a video file by reading the first few bytes
        with open(file_path, 'rb') as f:
            header = f.read(12)  # Read first 12 bytes to check file type
            
        # Basic MP4 header validation
        if len(header) < 8:
            raise Exception("File too small to be a valid video")
            
        # Check for common video file signatures
        is_valid_video = (
            header[4:8] == b'ftyp' or  # MP4
            header[:4] == b'\x1a\x45\xdf\xa3' or  # WebM/MKV
            header[:4] == b'RIFF'  # AVI
        )
        
        if not is_valid_video:
            _logger.warning("File does not appear to be a valid video file: %s", file_path)
            # Continue anyway, but log the warning
        
        file_ext = Path(file_path).suffix.lower()
        safe_title = VideoDownloadUtils.sanitize_filename(video_info.get('title', 'Unknown'))
        mimetype = VideoDownloadUtils.get_mime_type(file_ext)
        
        # Set the attachment name with file extension
        attachment_name = f"{safe_title}{file_ext}"
        
        # Use the simple, reliable approach for creating attachments
        # Read file content in chunks to avoid memory issues
        file_content = b''
        chunk_size = 1024 * 1024  # 1MB chunks
        
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                file_content += chunk
        
        # Create attachment with the complete file content
        attachment = self.env['ir.attachment'].create({
            'name': attachment_name,
            'type': 'binary',
            'res_model': 'leonix.video.translator',
            'res_id': video_record.id,
            'mimetype': mimetype,
            'description': f"Downloaded from {video_record.video_platform}: {video_record.video_url}",
            'public': True,
            'datas': base64.b64encode(file_content),
        })
        
        # Verify the attachment was created successfully
        if abs(attachment.file_size - file_size) > 100:  # Allow small difference due to encoding
            _logger.warning("File size mismatch: expected %d, got %d", 
                          file_size, attachment.file_size)
        
        # Log the attachment creation
        _logger.info("Video attachment created: %s (ID: %s, Size: %.2f MB)", 
                    attachment_name, attachment.id, file_size / (1024*1024))
        
        return attachment, file_size
    
    def check_existing_file(self, url_hash, title_pattern=None):
        """Check if file already exists in the system"""
        domain = [('res_model', '=', 'leonix.video.translator')]
        
        if title_pattern:
            domain.append(('name', 'ilike', f'%{title_pattern}%'))
            
        return self.env['ir.attachment'].search(domain, limit=1)
    
    def cleanup_temp_files(self, file_paths):
        """Clean up temporary files"""
        for file_path in file_paths:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError as e:
                _logger.warning(f"Failed to remove temporary file {file_path}: {e}")
    
    def delete_video_file(self, file_path):
        """Delete a video file from the filesystem"""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                _logger.info("Successfully deleted file: %s", file_path)
                return True
            else:
                _logger.warning("File not found for deletion: %s", file_path)
                return False
        except Exception as e:
            _logger.error("Error deleting file %s: %s", file_path, str(e))
            return False

class VideoProcessUtils:
    """Class to handle video processing tasks"""
    
    def __init__(self, env):
        self.env = env
    
    def get_video_platform(self, video_record):
        """Get the video platform from video record"""
        return video_record.video_platform if video_record else 'other'
    
    def get_video_file_path(self, video_record):
        """Get the actual video file path from the attachment"""
        if not video_record or not video_record.video_attachment_id:
            return None
            
        attachment = video_record.video_attachment_id
        if not attachment.store_fname:
            return None
            
        # Get the filestore path and build full path
        filestore_path = self.env['ir.attachment']._filestore()
        full_path = os.path.join(filestore_path, attachment.store_fname)
        
        if os.path.exists(full_path):
            return full_path
        else:
            _logger.warning(f"Video file not found at path: {full_path}")
            return None
    
    def extract_audio_from_video(self, video_file_path, output_format='wav'):
        """Extract audio from video file using ffmpeg"""
        if not video_file_path or not os.path.exists(video_file_path):
            raise Exception(f"Video file not found: {video_file_path}")
        
        # Check if ffmpeg is available
        try:
            subprocess.check_output(['ffmpeg', '-version'], stderr=subprocess.DEVNULL)
        except (subprocess.SubprocessError, FileNotFoundError):
            raise Exception("ffmpeg is not installed or not available in PATH")
        
        # Generate output audio file path
        video_dir = os.path.dirname(video_file_path)
        video_name = os.path.splitext(os.path.basename(video_file_path))[0]
        audio_file_path = os.path.join(video_dir, f"{video_name}_audio.{output_format}")
        
        # FFmpeg command to extract audio
        ffmpeg_cmd = [
            'ffmpeg',
            '-i', video_file_path,  # Input video file
            '-vn',  # No video
            '-acodec', 'pcm_s16le' if output_format == 'wav' else 'libmp3lame',  # Audio codec
            '-ar', '16000',  # Sample rate (16kHz is good for speech recognition)
            '-ac', '1',  # Mono audio
            '-y',  # Overwrite output file if it exists
            audio_file_path
        ]
        
        try:
            _logger.info(f"Extracting audio from {video_file_path} to {audio_file_path}")
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)  # 5 minute timeout
            
            if result.returncode != 0:
                _logger.error(f"FFmpeg error: {result.stderr}")
                raise Exception(f"FFmpeg failed with error: {result.stderr}")
            
            if not os.path.exists(audio_file_path):
                raise Exception("Audio extraction completed but output file not found")
            
            audio_size = os.path.getsize(audio_file_path)
            _logger.info(f"Audio extracted successfully: {audio_file_path} ({audio_size} bytes)")
            
            return audio_file_path
            
        except subprocess.TimeoutExpired:
            raise Exception("Audio extraction timed out (took more than 5 minutes)")
        except Exception as e:
            # Clean up partial file if extraction failed
            if os.path.exists(audio_file_path):
                try:
                    os.remove(audio_file_path)
                except:
                    pass
            raise Exception(f"Audio extraction failed: {str(e)}")
    
    def get_audio_duration(self, audio_file_path):
        """Get duration of audio file using ffmpeg"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'csv=p=0',
                audio_file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception as e:
            _logger.warning(f"Failed to get audio duration: {e}")
        return 0.0
    
    def cleanup_audio_file(self, audio_file_path):
        """Clean up temporary audio file"""
        try:
            if audio_file_path and os.path.exists(audio_file_path):
                os.remove(audio_file_path)
                _logger.info(f"Cleaned up audio file: {audio_file_path}")
                return True
        except Exception as e:
            _logger.warning(f"Failed to cleanup audio file {audio_file_path}: {e}")
        return False

