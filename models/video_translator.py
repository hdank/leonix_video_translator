from odoo import models, fields, api, _
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.http import request
import re
import os
import logging
import tempfile
import shutil
import json
import base64
import subprocess
import unicodedata
import threading  # Still used in download method
from ..utils.video_utils import VideoDownloadUtils
from .video_download_queue import VideoDownloadQueue

_logger = logging.getLogger(__name__)

class VideoTranslator(models.Model):
    _name = 'leonix.video.translator'
    _description = 'Video Translator'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    
    def _compute_access_url(self):
        for record in self:
            record.access_url = '/my/video-translations/%s' % record.id

    name = fields.Char(string='Name', required=True, tracking=True)
    description = fields.Text(string='Description')
    video_url = fields.Char(string='Video URL', required=True, tracking=True, 
                          help="YouTube or TikTok video URL to be translated")
    video_platform = fields.Selection([
        ('youtube', 'YouTube'),
        ('tiktok', 'TikTok'),
        ('other', 'Other')
    ], string='Video Platform', compute='_compute_video_platform', store=True)
    video_id = fields.Char(string='Video ID', compute='_compute_video_id', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('downloading', 'Downloading'),
        ('downloaded', 'Downloaded'),
        ('translating', 'Translating'),
        ('done', 'Done'),
        ('failed', 'Failed')
    ], default='draft', string='Status', tracking=True)
    user_id = fields.Many2one('res.users', string='Responsible', default=lambda self: self.env.user)
    
    # Video file management
    video_attachment_id = fields.Many2one('ir.attachment', string='Video File', readonly=True)
    video_file_path = fields.Char(string='Video File Path', readonly=True, 
                                 help="Path to original downloaded video file")
    processed_video_path = fields.Char(string='Processed Video Path', readonly=True,
                                      help="Path to final processed video (dubbed/subtitled)")
    video_file_hash = fields.Char(string='File Hash', readonly=True, index=True)
    video_file_size = fields.Integer(string='File Size (bytes)', readonly=True)
    video_duration = fields.Float(string='Duration (seconds)', readonly=True)
    video_format = fields.Char(string='Video Format', readonly=True)
    download_progress = fields.Float(string='Download Progress (%)', default=0.0, readonly=True)
    download_speed = fields.Char(string='Download Speed', readonly=True)
    estimated_time = fields.Char(string='Estimated Time', readonly=True)
    
    # Transcription and translation fields
    transcription_text = fields.Text(string='Transcription', readonly=True)
    transcription_language = fields.Char(string='Detected Language', readonly=True)
    transcription_segments = fields.Json(string='Transcription Segments', readonly=True)
    translation_text = fields.Text(string='Translation', readonly=True)
    translation_language = fields.Selection([
        ('vi', 'Vietnamese'),
        ('en', 'English'),
        ('ja', 'Japanese'),
        ('ko', 'Korean'),
        ('zh', 'Chinese'),
        ('es', 'Spanish'),
        ('fr', 'French'),
        ('de', 'German'),
    ], string='Target Language')
    translated_segments = fields.Json(string='Translated Segments', readonly=True)
    
    # Subtitle fields
    subtitle_file_path = fields.Char(string='Subtitle File Path', readonly=True)
    subtitle_attachment_id = fields.Many2one('ir.attachment', string='Subtitle File', readonly=True)
    
    # Dubbing fields
    dubbing_voice = fields.Selection([
        ('vi-VN-Chirp3-HD-Achernar', 'Vietnamese Female (Chirp3-HD-Achernar)'),
        ('vi-VN-Chirp3-HD-Bastian', 'Vietnamese Male (Chirp3-HD-Bastian)'),
        ('vi-VN-Standard-A', 'Vietnamese Standard Female'),
        ('vi-VN-Standard-B', 'Vietnamese Standard Male'),
    ], string='Dubbing Voice', default='vi-VN-Chirp3-HD-Achernar')
    
    # Processing mode
    processing_mode = fields.Selection([
        ('dubbing', 'Dubbing (Replace Audio)'),
        ('subtitles', 'Subtitles (Keep Original Audio)'),
        ('both', 'Both Dubbing and Subtitles (Recommended)')
    ], string='Processing Mode', default='both', required=True)
    
    # Processing status fields - simplified to single processing status
    processing_status = fields.Selection([
        ('not_started', 'Not Started'),
        ('transcribing', 'Transcribing...'),
        ('translating', 'Translating...'),
        ('generating', 'Generating Final Video...'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ], default='not_started', string='Processing Status')
    
    @api.depends('video_url')
    def _compute_video_platform(self):
        for record in self:
            if record.video_url:
                if 'youtube.com' in record.video_url or 'youtu.be' in record.video_url:
                    record.video_platform = 'youtube'
                elif 'tiktok.com' in record.video_url:
                    record.video_platform = 'tiktok'
                else:
                    record.video_platform = 'other'
            else:
                record.video_platform = False
    
    @api.depends('video_url', 'video_platform')
    def _compute_video_id(self):
        for record in self:
            record.video_id = False
            if record.video_url:
                if record.video_platform == 'youtube':
                    # Extract YouTube video ID
                    youtube_regex = r'(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
                    match = re.search(youtube_regex, record.video_url)
                    if match:
                        record.video_id = match.group(1)
                elif record.video_platform == 'tiktok':
                    # Extract TikTok video ID
                    tiktok_regex = r'tiktok\.com\/@[^\/]+\/video\/(\d+)'
                    match = re.search(tiktok_regex, record.video_url)
                    if match:
                        record.video_id = match.group(1)
    
    @api.constrains('video_url')
    def _check_video_url(self):
        for record in self:
            if record.video_url:
                if not (('youtube.com' in record.video_url or 'youtu.be' in record.video_url) or 'tiktok.com' in record.video_url):
                    raise ValidationError(_("Please provide a valid YouTube or TikTok video URL."))
    
    # This ensures the record will show in the portal with the correct name
    def _get_portal_return_action(self):
        return self.env.ref('leonix_video_translator.action_video_translator_list')
        
    def _compute_access_warning(self):
        for record in self:
            record.access_warning = ''
    
    def action_download_video(self):
        """Trigger the video download process using yt-dlp"""
        for record in self:
            # Check if video already exists by URL hash
            url_hash = VideoDownloadUtils.get_url_hash(record.video_url)
            existing_video = self.search([
                ('video_file_hash', '=', url_hash),
                ('state', 'in', ['downloaded', 'done']),
                ('id', '!=', record.id)
            ], limit=1)
            
            if existing_video and existing_video.video_attachment_id:
                # Reuse existing video file
                record.write({
                    'video_attachment_id': existing_video.video_attachment_id.id,
                    'video_file_hash': existing_video.video_file_hash,
                    'video_file_size': existing_video.video_file_size,
                    'video_duration': existing_video.video_duration,
                    'video_format': existing_video.video_format,
                    'download_progress': 100.0,
                    'state': 'downloaded'
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Video Ready'),
                        'message': _('Video is already available and ready to watch!'),
                        'sticky': False,
                        'type': 'success',
                    }
                }
            
            # Change state to downloading
            record.write({
                'state': 'downloading',
                'download_progress': 0.0,
                'video_file_hash': url_hash
            })
            
            # Add to download queue for processing
            queue_item = self.env['leonix.video.download.queue'].create({
                'video_translator_id': record.id,
                'video_url': record.video_url,
                'video_platform': record.video_platform,
                'url_hash': url_hash,
            })
            
            # Try to process immediately (async) instead of waiting for cron
            try:
                self.env.cr.commit()  # Commit the queue item creation
                # Process in background without blocking the UI
                record.process_download_background()
            except Exception as e:
                _logger.warning("Immediate processing failed, will use cron: %s", e)
                # Fallback to cron processing if immediate fails
                pass
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Video Download Started'),
                    'message': _('Video download has been queued and will start processing immediately.'),
                    'sticky': False,
                    'type': 'info',
                }
            }
    def process_download_background(self):
        """Process downloads in background thread with proper cleanup"""
        def safe_download_target():
            try:
                # Use a separate database cursor for background processing
                with self.env.registry.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, self.env.context)
                    queue_model = env['leonix.video.download.queue']
                    queue_model.process_pending_downloads()
            except Exception as e:
                _logger.error(f"Background download thread error: {e}")
            finally:
                # Ensure proper cleanup
                import threading
                current_thread = threading.current_thread()
                if hasattr(current_thread, '_cleanup'):
                    current_thread._cleanup()
        
        thread = threading.Thread(target=safe_download_target, name="VideoDownloader")
        thread.daemon = False  # Don't use daemon threads to avoid cleanup issues
        thread.start()
        
        # Don't join immediately, but ensure thread cleanup happens
        def cleanup_thread():
            if thread.is_alive():
                _logger.info("Waiting for download thread to complete...")
                thread.join(timeout=5.0)  # Wait up to 5 seconds for thread to finish
                if thread.is_alive():
                    _logger.warning("Download thread still running after timeout")
        
        # Register cleanup for when the method completes
        import atexit
        atexit.register(cleanup_thread)

    def get_video_url(self):
        """Get the URL to access the processed video (dubbed/subtitled) or original"""
        self.ensure_one()
        if self.processed_video_path and os.path.exists(self.processed_video_path):
            # Return URL for processed video
            video_filename = os.path.basename(self.processed_video_path)
            return f"/my/video-translations/{self.id}/processed/{video_filename}"
        elif self.video_file_path and os.path.exists(self.video_file_path):
            # Fallback to original video
            video_filename = os.path.basename(self.video_file_path)
            return f"/my/video-translations/{self.id}/original/{video_filename}"
        elif self.video_attachment_id:
            # Legacy fallback to attachment
            return f"/my/video-translations/{self.id}/stream"
        return False
    
    def get_video_play_url(self):
        """Get the play URL for better UX"""
        self.ensure_one()
        if self.processed_video_path and os.path.exists(self.processed_video_path):
            return f"/my/video-translations/{self.id}/play/processed"
        elif self.video_file_path and os.path.exists(self.video_file_path):
            return f"/my/video-translations/{self.id}/play/original"
        elif self.video_attachment_id:
            return f"/my/video-translations/{self.id}/play"
        return False
    
    def get_video_download_url(self):
        """Get the download URL for the processed video"""
        self.ensure_one()
        if self.processed_video_path and os.path.exists(self.processed_video_path):
            video_filename = os.path.basename(self.processed_video_path)
            return f"/my/video-translations/{self.id}/download/{video_filename}"
        return False

    def action_watch_video(self):
        """Action to watch the processed video"""
        self.ensure_one()
        play_url = self.get_video_play_url()
        if play_url:
            return {
                'type': 'ir.actions.act_url',
                'url': play_url,
                'target': 'new',
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Video Available'),
                    'message': _('No processed video available to watch.'),
                    'sticky': False,
                    'type': 'warning',
                }
            }
    
    def action_watch_original(self):
        """Action to watch the original video"""
        self.ensure_one()
        if self.video_file_path and os.path.exists(self.video_file_path):
            video_filename = os.path.basename(self.video_file_path)
            url = f"/my/video-translations/{self.id}/original/{video_filename}"
            return {
                'type': 'ir.actions.act_url',
                'url': url,
                'target': 'new',
            }
        elif self.video_attachment_id:
            return {
                'type': 'ir.actions.act_url',
                'url': f"/my/video-translations/{self.id}/stream",
                'target': 'new',
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Video Available'),
                    'message': _('No original video available to watch.'),
                    'sticky': False,
                    'type': 'warning',
                }
            }
    
    def action_download_processed(self):
        """Action to download the processed video"""
        self.ensure_one()
        download_url = self.get_video_download_url()
        if download_url:
            return {
                'type': 'ir.actions.act_url',
                'url': download_url,
                'target': 'self',
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Video Available'),
                    'message': _('No processed video available for download.'),
                    'sticky': False,
                    'type': 'warning',
                }
            }

    
    def get_video_fallback_url(self):
        """Get the fallback URL using Odoo's default content handler"""
        self.ensure_one()
        if self.video_attachment_id:
            return f"/web/content/{self.video_attachment_id.id}?download=false"
        return False
    
    def get_formatted_file_size(self):
        """Get human-readable file size"""
        self.ensure_one()
        return VideoDownloadUtils.format_file_size(self.video_file_size)
    
    def get_formatted_duration(self):
        """Get human-readable duration"""
        self.ensure_one()
        return VideoDownloadUtils.format_duration(self.video_duration)
    
    def debug_video_storage_locations(self):
        """Debug method to show all possible video storage locations"""
        self.ensure_one()
        _logger.info("=== DEBUGGING VIDEO STORAGE LOCATIONS ===")
        _logger.info("Video Record: %s (ID: %s)", self.name, self.id)
        
        if not self.video_attachment_id:
            _logger.info("No video attachment found")
            return {'error': 'No video attachment found'}
            
        attachment = self.video_attachment_id
        _logger.info("Attachment ID: %s", attachment.id)
        _logger.info("Attachment Name: %s", attachment.name)
        _logger.info("Store Filename: %s", attachment.store_fname)
        _logger.info("Mimetype: %s", attachment.mimetype)
        _logger.info("File Size (database): %s", attachment.file_size)
        
        # Get Odoo filestore path
        filestore_path = self.env['ir.attachment']._filestore()
        _logger.info("Odoo Filestore Path: %s", filestore_path)
        
        # Check full path in filestore
        filestore_file_exists = False
        filestore_file_size = 0
        if attachment.store_fname:
            full_path = os.path.join(filestore_path, attachment.store_fname)
            _logger.info("Full File Path: %s", full_path)
            filestore_file_exists = os.path.exists(full_path)
            _logger.info("File Exists: %s", filestore_file_exists)
            
            if filestore_file_exists:
                file_stats = os.stat(full_path)
                filestore_file_size = file_stats.st_size
                _logger.info("Physical File Size: %d bytes", file_stats.st_size)
                _logger.info("Physical File Modified: %s", file_stats.st_mtime)
        
        # Check custom leonix_videos directory
        from ..utils.video_utils import VideoDownloadUtils
        custom_storage = VideoDownloadUtils.get_storage_path(self.env, self.video_platform or 'other')
        _logger.info("Custom Storage Path: %s", custom_storage)
        
        # List all files in custom storage
        custom_files = []
        if os.path.exists(custom_storage):
            files = os.listdir(custom_storage)
            _logger.info("Files in custom storage: %s", files)
            
            for file_name in files:
                file_path = os.path.join(custom_storage, file_name)
                if os.path.isfile(file_path):
                    file_stat = os.stat(file_path)
                    custom_files.append({
                        'name': file_name,
                        'size': file_stat.st_size,
                        'modified': file_stat.st_mtime,
                        'is_video': any(file_name.lower().endswith(ext) for ext in ['.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv'])
                    })
        
        return {
            'attachment_id': attachment.id,
            'attachment_name': attachment.name,
            'store_fname': attachment.store_fname,
            'mimetype': attachment.mimetype,
            'database_file_size': attachment.file_size,
            'filestore_path': filestore_path,
            'full_path': os.path.join(filestore_path, attachment.store_fname) if attachment.store_fname else None,
            'filestore_file_exists': filestore_file_exists,
            'filestore_file_size': filestore_file_size,
            'custom_storage': custom_storage,
            'custom_storage_exists': os.path.exists(custom_storage),
            'custom_files': custom_files,
            'video_platform': self.video_platform,
            'video_url': self.video_url,
            'state': self.state,
        }
    
    def can_retry_download(self):
        """Check if download can be retried"""
        self.ensure_one()
        return self.state in ['draft', 'failed']
    
    def reset_download(self):
        """Reset download state for retry"""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'download_progress': 0.0,
            'download_speed': False,
            'estimated_time': False,
            'video_attachment_id': False,
            'video_file_path': False,
            'processed_video_path': False,
            'video_file_size': 0,
            'video_duration': 0.0,
            'video_format': False,
            'processing_status': 'not_started'
        })
        
    def action_delete_record(self):
        """Completely delete the video record and its files from the database"""
        self.ensure_one()
        _logger = logging.getLogger(__name__)
        _logger.info("=== STARTING RECORD DELETION ===")
        _logger.info("Completely deleting record %s (ID: %s)", self.name, self.id)
        
        # First clean up any video files
        if self.video_attachment_id:
            try:
                # Store attachment info for debugging
                att_id = self.video_attachment_id.id
                att_name = self.video_attachment_id.name
                store_fname = self.video_attachment_id.store_fname
                
                _logger.info("Deleting attachment %s (ID: %s) before record deletion", att_name, att_id)
                
                # Check if there are other records using the same attachment
                other_records = self.search([
                    ('video_attachment_id', '=', att_id),
                    ('id', '!=', self.id)
                ])
                
                if not other_records:
                    # Safe to delete the attachment as no other records use it
                    filestore_path = self.env['ir.attachment']._filestore()
                    if store_fname:
                        full_path = os.path.join(filestore_path, store_fname)
                        if os.path.exists(full_path):
                            try:
                                os.remove(full_path)
                                _logger.info("Deleted physical file: %s", full_path)
                            except Exception as e:
                                _logger.warning("Could not delete physical file %s: %s", full_path, e)
                    
                    # Also delete from custom storage if it exists
                    files_deleted = self._cleanup_custom_storage_files(att_name)
                    if files_deleted:
                        _logger.info("Deleted files from custom storage: %s", files_deleted)
                    else:
                        _logger.info("No matching files found in custom storage for deletion")
                    
                    # Delete the attachment from database
                    self.video_attachment_id.unlink()
                    _logger.info("Deleted attachment from database")
                else:
                    _logger.info("Attachment kept as it's used by %d other records", len(other_records))
            except Exception as e:
                _logger.error("Error during attachment cleanup: %s", str(e))
        
        # Delete the record itself
        record_name = self.name
        record_id = self.id
        
        # Use unlink to completely remove the record from database
        self.unlink()
        
        _logger.info("=== RECORD DELETION COMPLETED ===")
        _logger.info("Successfully deleted record '%s' (ID: %s) from database", record_name, record_id)
        
        return True

    def _cleanup_custom_storage_files(self, att_name=None):
        """Helper method to clean up files from custom storage"""
        from ..utils.video_utils import VideoDownloadUtils, VideoFileManager
        
        custom_storage = VideoDownloadUtils.get_storage_path(self.env, self.video_platform or 'other')
        file_manager = VideoFileManager(self.env)
        files_deleted = []
        
        if not os.path.exists(custom_storage):
            return files_deleted
        
        video_extensions = ['.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv']
        files_in_storage = os.listdir(custom_storage)
        
        # Look for files that might belong to this video
        attachment_name_base = os.path.splitext(att_name)[0] if att_name else None
        video_url_hash = VideoDownloadUtils.get_url_hash(self.video_url) if self.video_url else None
        
        for file_name in files_in_storage:
            file_ext = os.path.splitext(file_name)[1].lower()
            if file_ext in video_extensions:
                should_delete = False
                
                # Check if this file might belong to our video by name
                if attachment_name_base and attachment_name_base in file_name:
                    should_delete = True
                
                # Check if this file might belong to our video by URL hash
                if video_url_hash and video_url_hash[:12] in file_name:
                    should_delete = True
                
                if should_delete:
                    custom_file_path = os.path.join(custom_storage, file_name)
                    if file_manager.delete_video_file(custom_file_path):
                        files_deleted.append(file_name)
        
        return files_deleted

    def unlink(self):
        """Override unlink to clean up video files and threads before deletion"""
        _logger = logging.getLogger(__name__)
        for record in self:
            _logger.info("Unlinking video record: %s (ID: %s)", record.name, record.id)
            
            # Clean up video attachments
            if record.video_attachment_id:
                att_id = record.video_attachment_id.id
                att_name = record.video_attachment_id.name
                store_fname = record.video_attachment_id.store_fname
                
                # Check if other records use the same attachment
                other_records = self.search([
                    ('video_attachment_id', '=', att_id),
                    ('id', '!=', record.id)
                ])
                
                if not other_records:
                    # Safe to delete the attachment
                    try:
                        filestore_path = self.env['ir.attachment']._filestore()
                        if store_fname:
                            full_path = os.path.join(filestore_path, store_fname)
                            if os.path.exists(full_path):
                                os.remove(full_path)
                                _logger.info("Removed physical file during unlink: %s", full_path)
                        
                        # Also delete from custom storage if it exists
                        files_deleted = record._cleanup_custom_storage_files(att_name)
                        if files_deleted:
                            _logger.info("Deleted files from custom storage during unlink: %s", files_deleted)

                        record.video_attachment_id.unlink()
                        _logger.info("Removed attachment %s during record unlink", att_name)
                    except Exception as e:
                        _logger.warning("Error cleaning up attachment during unlink: %s", e)
                else:
                    _logger.info("Kept attachment %s as it's used by other records", att_name)
        
        # Call parent unlink to actually remove the records
        return super().unlink()

    def action_delete_video(self):
        """Delete the downloaded video and reset download state"""
        self.ensure_one()
        _logger = logging.getLogger(__name__)
        _logger.info("=== STARTING VIDEO DELETION DEBUG ===")
        _logger.info("Deleting video for record %s (ID: %s)", self.name, self.id)
        
        # Delete processed video file first
        if self.processed_video_path and os.path.exists(self.processed_video_path):
            try:
                os.remove(self.processed_video_path)
                _logger.info("Deleted processed video file: %s", self.processed_video_path)
            except Exception as e:
                _logger.warning("Failed to delete processed video file %s: %s", self.processed_video_path, e)
        
        # Delete original video file if it exists as file path
        if self.video_file_path and os.path.exists(self.video_file_path):
            try:
                os.remove(self.video_file_path)
                _logger.info("Deleted original video file: %s", self.video_file_path)
            except Exception as e:
                _logger.warning("Failed to delete original video file %s: %s", self.video_file_path, e)
        
        if self.video_attachment_id:
            try:
                # Store attachment info for debugging
                att_id = self.video_attachment_id.id
                att_name = self.video_attachment_id.name
                store_fname = self.video_attachment_id.store_fname
                
                _logger.info("DEBUG: Attachment ID: %s", att_id)
                _logger.info("DEBUG: Attachment Name: %s", att_name)
                _logger.info("DEBUG: Store Filename: %s", store_fname)
                
                # Get all possible file locations
                filestore_path = self.env['ir.attachment']._filestore()
                _logger.info("DEBUG: Filestore Path: %s", filestore_path)
                
                if store_fname:
                    # Build full path to the file
                    full_file_path = os.path.join(filestore_path, store_fname)
                    _logger.info("DEBUG: Full File Path: %s", full_file_path)
                    _logger.info("DEBUG: File exists: %s", os.path.exists(full_file_path))
                    
                    if os.path.exists(full_file_path):
                        file_size = os.path.getsize(full_file_path)
                        _logger.info("DEBUG: File size: %d bytes (%.2f MB)", file_size, file_size / (1024*1024))
                
                # Check if there are other records using the same attachment
                other_records = self.search([
                    ('video_attachment_id', '=', att_id),
                    ('id', '!=', self.id)
                ])
                _logger.info("DEBUG: Other records using same attachment: %d", len(other_records))
                
                if other_records:
                    _logger.info("DEBUG: Not deleting file as it's used by other records: %s", other_records.mapped('name'))
                    # Only reset this record, don't delete the shared file
                    self.write({
                        'state': 'draft',
                        'download_progress': 0.0,
                        'download_speed': False,
                        'estimated_time': False,
                        'video_attachment_id': False,
                        'video_file_size': 0,
                        'video_duration': 0.0,
                        'video_format': False
                    })
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Video Removed'),
                            'message': _('Video removed from this record (file kept as it\'s used by other records).'),
                            'sticky': False,
                            'type': 'success',
                        }
                    }
                
                # Delete the physical file first if it exists
                if store_fname:
                    from ..utils.video_utils import VideoFileManager, VideoDownloadUtils
                    file_manager = VideoFileManager(self.env)
                    
                    # Try to delete from filestore first
                    full_path = os.path.join(filestore_path, store_fname)
                    deletion_result = file_manager.delete_video_file(full_path)
                    _logger.info("DEBUG: Filestore deletion result: %s", deletion_result)
                    
                    # Also try to delete from custom storage using helper method
                    files_deleted = self._cleanup_custom_storage_files(att_name)
                    if files_deleted:
                        _logger.info("DEBUG: Deleted files from custom storage: %s", files_deleted)
                    else:
                        _logger.info("DEBUG: No matching files found in custom storage for deletion")
                
                # Delete the attachment from database
                self.video_attachment_id.unlink()
                _logger.info("DEBUG: Successfully deleted attachment %s (ID: %s)", att_name, att_id)
                
                # Reset the record
                self.write({
                    'state': 'draft',
                    'download_progress': 0.0,
                    'download_speed': False,
                    'estimated_time': False,
                    'video_attachment_id': False,
                    'video_file_path': False,
                    'processed_video_path': False,
                    'video_file_size': 0,
                    'video_duration': 0.0,
                    'video_format': False,
                    'processing_status': 'not_started',
                    'transcription_text': False,
                    'translation_text': False,
                    'transcription_segments': False,
                    'translated_segments': False
                })
                
                _logger.info("=== VIDEO DELETION COMPLETED SUCCESSFULLY ===")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Video Deleted'),
                        'message': _('The video has been completely deleted from the system.'),
                        'sticky': False,
                        'type': 'success',
                    }
                }
            except Exception as e:
                _logger.error("=== ERROR DURING VIDEO DELETION ===")
                _logger.error("Error deleting video attachment: %s", str(e), exc_info=True)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Error'),
                        'message': _('Failed to delete video: %s') % str(e),
                        'sticky': False,
                        'type': 'danger',
                    }
                }
        else:
            _logger.warning("DEBUG: No video attachment found to delete for record %s (ID: %s)", self.name, self.id)
            # Still reset the record state
            self.write({
                'state': 'draft',
                'download_progress': 0.0,
                'download_speed': False,
                'estimated_time': False,
                'video_file_path': False,
                'processed_video_path': False,
                'video_file_size': 0,
                'video_duration': 0.0,
                'video_format': False,
                'processing_status': 'not_started'
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Record Reset'),
                    'message': _('Video record has been reset to draft state.'),
                    'sticky': False,
                    'type': 'warning',
                }
            }
    
    def fix_attachment_mimetype(self):
        """Fix attachment MIME type based on filename extension"""
        self.ensure_one()
        if not self.video_attachment_id:
            return False
            
        attachment = self.video_attachment_id
        if attachment.mimetype == 'application/octet-stream' or not attachment.mimetype.startswith('video/'):
            # Extract extension from filename
            if attachment.name:
                file_ext = os.path.splitext(attachment.name)[1].lower()
                from ..utils.video_utils import VideoDownloadUtils
                correct_mimetype = VideoDownloadUtils.get_mime_type(file_ext)
                
                if correct_mimetype != attachment.mimetype:
                    attachment.write({'mimetype': correct_mimetype})
                    _logger.info("Fixed MIME type for attachment %s: %s -> %s", 
                               attachment.id, attachment.mimetype, correct_mimetype)
                    return True
        return False
    
    @api.model
    def fix_all_attachment_mimetypes(self):
        """Fix MIME types for all video attachments with incorrect types"""
        videos = self.search([
            ('video_attachment_id', '!=', False),
            ('state', '=', 'downloaded')
        ])
        
        fixed_count = 0
        for video in videos:
            if video.fix_attachment_mimetype():
                fixed_count += 1
                
        _logger.info("Fixed MIME types for %d video attachments", fixed_count)
        return fixed_count
    
    def action_process_video(self):
        """New streamlined action to process video with dubbing or subtitles"""
        self.ensure_one()
        
        # Validate prerequisites
        if not self.video_attachment_id and not self.video_file_path:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Video must be downloaded first before processing.'),
                    'sticky': False,
                    'type': 'danger',
                }
            }
        
        if self.state != 'downloaded':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Video must be in downloaded state to start processing.'),
                    'sticky': False,
                    'type': 'danger',
                }
            }
        
        if not self.translation_language:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Please select a target language first.'),
                    'sticky': False,
                    'type': 'danger',
                }
            }
        
        if not self.processing_mode:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Please select a processing mode (Dubbing or Subtitles).'),
                    'sticky': False,
                    'type': 'danger',
                }
            }
        
        if self.processing_mode == 'dubbing' and not self.dubbing_voice:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Please select a dubbing voice for dubbing mode.'),
                    'sticky': False,
                    'type': 'danger',
                }
            }
        
        # Check if already processing
        if self.processing_status in ['transcribing', 'translating', 'generating']:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Already Processing'),
                    'message': _('This video is already being processed. Please wait for completion.'),
                    'sticky': False,
                    'type': 'warning',
                }
            }
        
        try:
            # Start processing workflow immediately in current transaction
            # This avoids threading issues and concurrent database access
            self.write({
                'processing_status': 'transcribing',
                'state': 'translating'
            })
            
            # Use cron job to handle background processing instead of threads
            self._schedule_video_processing()
            
            mode_text = 'dubbing' if self.processing_mode == 'dubbing' else 'subtitles'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Processing Started'),
                    'message': _('Video processing with %s has started. This may take several minutes.') % mode_text,
                    'sticky': False,
                    'type': 'info',
                }
            }
        except Exception as e:
            _logger.error(f"Failed to start video processing for video {self.id}: {e}")
            self.write({
                'processing_status': 'failed',
                'state': 'downloaded'
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Failed to start processing: %s') % str(e),
                    'sticky': False,
                    'type': 'danger',
                }
            }
    
    def _schedule_video_processing(self):
        """Schedule video processing via cron job to avoid concurrent database access"""
        # Create a cron job that will run immediately to process this video
        cron_vals = {
            'name': f'Process Video {self.id} - {self.name}',
            'model_id': self.env.ref('leonix_video_translator.model_leonix_video_translator').id,
            'state': 'code',
            'code': f'model.browse({self.id})._process_video_workflow_cron()',
            'interval_number': 1,
            'interval_type': 'minutes',
            'nextcall': fields.Datetime.now(),  # Run immediately
            'active': True,
            'user_id': self.env.user.id,
        }
        
        cron_job = self.env['ir.cron'].sudo().create(cron_vals)
        _logger.info(f"Created cron job {cron_job.id} for video processing of video {self.id}")
        
        # Trigger the cron job to run immediately
        cron_job._trigger()
        
        return cron_job
    
    def _process_video_workflow_cron(self):
        """Cron job method to process video workflow safely"""
        self.ensure_one()
        
        # Find the cron job that's running this (for cleanup)
        cron_job = None
        try:
            # Look for the cron job by name pattern
            cron_name_pattern = f'Process Video {self.id} -'
            cron_job = self.env['ir.cron'].sudo().search([
                ('name', 'like', cron_name_pattern),
                ('active', '=', True)
            ], limit=1)
        except Exception as e:
            _logger.warning(f"Could not find cron job for cleanup: {e}")
        
        try:
            # Check if we should still process this video
            if self.processing_status != 'transcribing' or self.state != 'translating':
                _logger.info(f"Video {self.id} no longer needs processing (status: {self.processing_status}, state: {self.state})")
                return
            
            _logger.info(f"Starting cron-based video processing for video {self.id}")
            self._process_video_workflow()
            
        except Exception as e:
            _logger.error(f"Cron video processing failed for video {self.id}: {e}")
            try:
                self.write({
                    'processing_status': 'failed',
                    'state': 'downloaded'
                })
            except Exception as write_error:
                _logger.error(f"Failed to update error state for video {self.id}: {write_error}")
        finally:
            # Clean up the cron job after processing (success or failure)
            if cron_job:
                try:
                    cron_job.sudo().unlink()
                    _logger.info(f"Cleaned up cron job {cron_job.id} for video {self.id}")
                except Exception as cleanup_error:
                    _logger.warning(f"Failed to cleanup cron job for video {self.id}: {cleanup_error}")
                    # If we can't delete it, just deactivate it
                    try:
                        cron_job.sudo().write({'active': False})
                        _logger.info(f"Deactivated cron job {cron_job.id} for video {self.id}")
                    except Exception as deactivate_error:
                        _logger.error(f"Failed to deactivate cron job for video {self.id}: {deactivate_error}")
    
    def _process_video_workflow(self):
        """Complete video processing workflow: transcribe -> translate -> generate final video"""
        try:
            _logger.info(f"Starting video processing workflow for video {self.id}")
            
            # Step 1: Transcription using OpenAI
            self._safe_update_status('transcribing')
            transcription_result = self._process_transcription_openai()
            
            # Step 2: Translation using Google Cloud
            self._safe_update_status('translating')
            translation_result = self._process_translation_gcloud(transcription_result)
            
            # Step 3: Generate final video (dubbing or subtitles)
            self._safe_update_status('generating')
            final_video_path = self._generate_final_video_simple(translation_result)
            
            # Final update
            self._safe_update_record({
                'processed_video_path': final_video_path,
                'processing_status': 'completed',
                'state': 'done'
            })
            
            _logger.info(f"Video processing completed successfully for video {self.id}")
            
        except Exception as e:
            _logger.error(f"Video processing failed for video {self.id}: {e}")
            self._safe_update_record({
                'processing_status': 'failed',
                'state': 'downloaded'
            })
            raise e
    
    def _safe_update_status(self, status):
        """Update processing status"""
        self.write({'processing_status': status})
    
    def _safe_update_record(self, values):
        """Update record with values"""
        self.write(values)

    def _process_transcription_openai(self):
        """Process video transcription using OpenAI Whisper with auto-chunking"""
        from ..services.openai_service import OpenAIService
        import subprocess
        import tempfile
        
        try:
            # Get video file path
            video_file_path = self._get_video_file_path()
            if not video_file_path:
                raise Exception("Could not locate video file for transcription")
            
            # Extract audio from video using FFmpeg
            temp_dir = tempfile.mkdtemp(prefix="video_audio_")
            temp_audio_path = os.path.join(temp_dir, "extracted_audio.mp3")
            
            extract_audio_cmd = [
                'ffmpeg', '-i', video_file_path, 
                '-vn', '-acodec', 'mp3', '-ab', '192k', 
                '-ar', '16000', '-ac', '1',
                '-y', temp_audio_path
            ]
            
            result = subprocess.run(extract_audio_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"FFmpeg audio extraction failed: {result.stderr}")
            
            if not os.path.exists(temp_audio_path):
                raise Exception("Audio extraction failed: file not created")
            
            try:
                # Initialize OpenAI service and transcribe (with auto-chunking)
                openai_service = OpenAIService(self.env)
                
                # Create enhanced prompt for better timeline accuracy
                enhanced_prompt = f"""Please transcribe this {self.video_platform or 'video'} content with high precision timing. 
This is for video synchronization purposes, so accurate word timing and natural speech flow detection is crucial.
Pay special attention to:
- Speaking speed variations
- Natural pauses and breaks  
- Clear word boundaries
- Maintaining synchronization timing

The target translation language will be {self.translation_language}, so clear segmentation will help with dubbing alignment."""
                
                transcription_result = openai_service.transcribe_audio(
                    temp_audio_path, 
                    language=None,  # Let OpenAI detect language
                    model="whisper-1",  # Use correct Whisper model
                    prompt=enhanced_prompt
                )
                
                # Update record with transcription results using safe encoding
                transcription_text = transcription_result['text']
                if isinstance(transcription_text, bytes):
                    transcription_text = transcription_text.decode('utf-8', errors='replace')
                elif not isinstance(transcription_text, str):
                    transcription_text = str(transcription_text)
                
                # Clean and normalize transcription text
                import re
                import unicodedata
                transcription_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', transcription_text)
                transcription_text = unicodedata.normalize('NFC', transcription_text)
                
                # Safe update with retry mechanism
                self._safe_update_record({
                    'transcription_text': transcription_text,
                    'transcription_language': transcription_result.get('language', 'unknown'),
                    'transcription_segments': transcription_result.get('segments', [])
                })
                
                # Log timeline analysis for debugging
                timeline_analysis = transcription_result.get('timeline_analysis', {})
                if timeline_analysis:
                    _logger.info(f"Timeline Analysis for video {self.id}: {timeline_analysis}")
                
                _logger.info(f"OpenAI transcription completed for video {self.id}")
                return transcription_result
                
            finally:
                # Clean up audio file and temp directory
                try:
                    if os.path.exists(temp_audio_path):
                        os.remove(temp_audio_path)
                    if os.path.exists(temp_dir):
                        os.rmdir(temp_dir)
                except Exception as cleanup_error:
                    _logger.warning(f"Failed to clean up temp files: {cleanup_error}")
                    
        except Exception as e:
            _logger.error(f"OpenAI transcription failed for video {self.id}: {e}")
            raise e

    def _process_translation_gcloud(self, transcription_result):
        """Translate transcribed text using Google Cloud Translation API with proper encoding handling"""
        from ..services.gcloud_service import GoogleCloudService
        
        try:
            # Initialize Google Cloud service
            gcloud_service = GoogleCloudService(self.env)
            
            # Ensure proper encoding for the transcription text
            transcription_text = transcription_result['text']
            if isinstance(transcription_text, bytes):
                transcription_text = transcription_text.decode('utf-8', errors='replace')
            elif not isinstance(transcription_text, str):
                transcription_text = str(transcription_text)
            
            # Clean and normalize text
            import unicodedata
            import re
            # Remove any null bytes and control characters that could cause encoding issues
            transcription_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', transcription_text)
            transcription_text = unicodedata.normalize('NFC', transcription_text)
            
            _logger.info(f"Starting Google Cloud translation for video {self.id}")
            _logger.info(f"Input text length: {len(transcription_text)} characters")
            
            # Translate main text
            translation_result = gcloud_service.translate_text(
                text=transcription_text,
                target_language=self.translation_language,
                source_language=self.transcription_language
            )
            
            # Ensure proper encoding for translated text
            translated_text = translation_result['translated_text']
            if isinstance(translated_text, bytes):
                translated_text = translated_text.decode('utf-8', errors='replace')
            elif not isinstance(translated_text, str):
                translated_text = str(translated_text)
            
            # Normalize translated text
            translated_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', translated_text)
            translated_text = unicodedata.normalize('NFC', translated_text)
            
            # Translate segments if available with proper encoding
            translated_segments = []
            if transcription_result.get('segments'):
                segments_to_translate = []
                for segment in transcription_result['segments']:
                    # Ensure proper encoding for segment text
                    segment_text = segment.get('text', '')
                    if isinstance(segment_text, bytes):
                        segment_text = segment_text.decode('utf-8', errors='replace')
                    elif not isinstance(segment_text, str):
                        segment_text = str(segment_text)
                    
                    # Normalize and clean segment text
                    segment_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', segment_text)
                    segment_text = unicodedata.normalize('NFC', segment_text)
                    
                    # Update segment with cleaned text
                    clean_segment = segment.copy()
                    clean_segment['text'] = segment_text
                    segments_to_translate.append(clean_segment)
                
                translated_segments = gcloud_service.translate_segments(
                    segments=segments_to_translate,
                    target_language=self.translation_language,
                    source_language=self.transcription_language
                )
                
                # Ensure proper encoding for all translated segments
                for segment in translated_segments:
                    if 'text' in segment:
                        segment_text = segment['text']
                        if isinstance(segment_text, bytes):
                            segment_text = segment_text.decode('utf-8', errors='replace')
                        elif not isinstance(segment_text, str):
                            segment_text = str(segment_text)
                        segment['text'] = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', segment_text)
                        segment['text'] = unicodedata.normalize('NFC', segment['text'])
            
            # Update record with translation results using proper encoding
            update_values = {
                'translation_text': translated_text,
                'translated_segments': translated_segments
            }
            
            # Validate data before database write to prevent encoding issues
            for key, value in update_values.items():
                if isinstance(value, str):
                    # Double-check encoding is clean
                    try:
                        value.encode('utf-8')
                    except UnicodeEncodeError as e:
                        _logger.error(f"Encoding error in {key}: {e}")
                        # Replace problematic characters
                        update_values[key] = value.encode('utf-8', errors='replace').decode('utf-8')
            
            # Use safe database write with retry mechanism for concurrent updates
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Use sudo() and disable tracking to avoid conflicts
                    self.with_context(skip_tracking=True).sudo().write(update_values)
                    self.env.cr.commit()  # Commit immediately to avoid transaction issues
                    break  # Success, exit retry loop
                    
                except Exception as write_error:
                    _logger.warning(f"Database write attempt {attempt + 1} failed: {write_error}")
                    if "concurrent update" in str(write_error).lower() or "could not serialize access" in str(write_error).lower():
                        if attempt < max_retries - 1:
                            import time
                            time.sleep(1 * (attempt + 1))  # Progressive delay: 1s, 2s, 3s
                            continue
                        else:
                            _logger.error(f"Max retries reached for database write on video {self.id}")
                            raise write_error  # Re-raise on final attempt
                    else:
                        raise write_error  # Re-raise non-concurrency errors immediately
            
            _logger.info(f"Google Cloud translation completed for video {self.id}")
            _logger.info(f"Translated text length: {len(translated_text)} characters")
            
            return {
                'translated_text': translated_text,
                'translated_segments': translated_segments,
                'source_language': translation_result.get('source_language'),
                'target_language': self.translation_language,
                'timeline_analysis': transcription_result.get('timeline_analysis', {})  # Pass through timeline data
            }
            
        except Exception as e:
            _logger.error(f"Google Cloud translation failed for video {self.id}: {e}")
            raise Exception(f"Translation failed: {str(e)}")

    def _generate_final_video_simple(self, translation_result):
        """Generate final video with advanced synchronization and both dubbing and subtitles"""
        from ..services.gcloud_service import GoogleCloudService
        from ..utils.video_utils import VideoDownloadUtils
        
        try:
            # Get original video file path
            original_video_path = self._get_video_file_path()
            if not original_video_path:
                raise Exception("Could not locate original video file")
            
            # Create output file path in /tmp for easy access
            base_name = os.path.splitext(os.path.basename(original_video_path))[0]
            mode_suffix = 'processed'  # Always create processed version
            output_filename = f"{base_name}_{mode_suffix}_{self.id}.mp4"
            output_path = f"/tmp/{output_filename}"
            
            # Also create a backup in storage directory
            storage_path = VideoDownloadUtils.get_storage_path(self.env, self.video_platform or 'other')
            storage_output_path = os.path.join(storage_path, output_filename)
            
            # Initialize Google Cloud service for advanced processing
            gcloud_service = GoogleCloudService(self.env)
            
            # Determine processing mode - now we can do both!
            if self.processing_mode == 'dubbing':
                processing_mode = 'dubbing'
            elif self.processing_mode == 'subtitles':
                processing_mode = 'subtitles'
            else:
                # Default to both for better user experience
                processing_mode = 'both'
            
            # Use the new synchronized video creation method
            result = gcloud_service.create_synchronized_video(
                original_video_path=original_video_path,
                segments=translation_result.get('translated_segments', []),
                output_path=output_path,
                processing_mode=processing_mode
            )
            
            if not result.get('success'):
                raise Exception(f"Synchronized video creation failed: {result.get('error', 'Unknown error')}")
            
            final_video_path = result.get('video_path')
            if not final_video_path or not os.path.exists(final_video_path):
                error_msg = result.get('error', 'Unknown error')
                _logger.error(f"Synchronized video creation failed: {error_msg}")
                _logger.error(f"Result: {result}")
                raise Exception(f"Failed to create final video: {error_msg}")
            
            # Validate the created file
            if os.path.getsize(final_video_path) == 0:
                raise Exception(f"Created video file is empty: {final_video_path}")
                
            _logger.info(f"Successfully created final video: {final_video_path} ({os.path.getsize(final_video_path)} bytes)")
            
            # Save subtitle file as attachment if created
            subtitle_path = result.get('subtitle_path')
            if subtitle_path and os.path.exists(subtitle_path):
                self._save_subtitle_as_attachment(subtitle_path)
                _logger.info(f"Subtitle file saved as attachment: {subtitle_path}")
            
            # Copy to storage directory as backup
            try:
                os.makedirs(os.path.dirname(storage_output_path), exist_ok=True)
                shutil.copy2(final_video_path, storage_output_path)
                _logger.info(f"Final video also saved to storage: {storage_output_path}")
            except Exception as copy_error:
                _logger.warning(f"Failed to copy to storage directory: {copy_error}")
            
            _logger.info(f"Final synchronized video created successfully at {final_video_path}")
            _logger.info(f"Processing mode: {processing_mode}")
            _logger.info(f"Subtitles included: {'Yes' if subtitle_path else 'No'}")
            _logger.info(f"Audio dubbed: {'Yes' if processing_mode in ['dubbing', 'both'] else 'No'}")
            
            return final_video_path
            
        except Exception as e:
            _logger.error(f"Failed to generate final synchronized video for video {self.id}: {e}")
            # Fallback to simple method if advanced method fails
            _logger.info("Attempting fallback to simple video generation...")
            return self._generate_final_video_fallback(translation_result)

    def _generate_final_video_fallback(self, translation_result):
        """Fallback video generation using simple ffmpeg commands"""
        from ..services.gcloud_service import GoogleCloudService
        from ..utils.video_utils import VideoDownloadUtils
        
        try:
            # Get original video file path
            original_video_path = self._get_video_file_path()
            if not original_video_path:
                raise Exception("Could not locate original video file")
            
            # Create output file path in /tmp for easy access
            base_name = os.path.splitext(os.path.basename(original_video_path))[0]
            mode_suffix = 'dubbed' if self.processing_mode == 'dubbing' else 'subtitled'
            output_filename = f"{base_name}_{mode_suffix}_{self.id}.mp4"
            output_path = f"/tmp/{output_filename}"
            
            # Also create a backup in storage directory
            storage_path = VideoDownloadUtils.get_storage_path(self.env, self.video_platform or 'other')
            storage_output_path = os.path.join(storage_path, output_filename)
            
            if self.processing_mode == 'dubbing':
                # Generate dubbing with simple approach
                final_video_path = self._create_dubbed_video_simple(original_video_path, translation_result, output_path)
            else:
                # Generate subtitles with simple approach
                final_video_path = self._create_subtitled_video_simple(original_video_path, translation_result, output_path)
            
            if not os.path.exists(final_video_path):
                raise Exception(f"Failed to create final video at {final_video_path}")
            
            # Copy to storage directory as backup
            try:
                os.makedirs(os.path.dirname(storage_output_path), exist_ok=True)
                shutil.copy2(final_video_path, storage_output_path)
                _logger.info(f"Final video also saved to storage: {storage_output_path}")
            except Exception as copy_error:
                _logger.warning(f"Failed to copy to storage directory: {copy_error}")
            
            _logger.info(f"Fallback video created successfully at {final_video_path}")
            return final_video_path
            
        except Exception as e:
            _logger.error(f"Failed to generate fallback video for video {self.id}: {e}")
            raise e

    def _create_dubbed_video_simple(self, original_video_path, translation_result, output_path):
        """Create dubbed video using simple ffmpeg approach with speed synchronization"""
        from ..services.gcloud_service import GoogleCloudService
        
        try:
            # Initialize Google Cloud service
            gcloud_service = GoogleCloudService(self.env)
            
            # Create audio file in /tmp for easy access
            temp_audio_path = f"/tmp/dubbed_audio_{self.id}_{self.env.uid}.wav"
            
            try:
                # Get timeline analysis for speed synchronization
                timeline_analysis = translation_result.get('timeline_analysis', {})
                average_speed = timeline_analysis.get('average_speaking_speed', 150)  # Default 150 WPM
                
                # Adjust speaking rate based on original speech speed
                # Normal speaking rate is 1.0, we can adjust between 0.5 and 2.0
                if average_speed > 200:  # Fast speech
                    speaking_rate = min(1.5, average_speed / 150)
                elif average_speed < 100:  # Slow speech
                    speaking_rate = max(0.7, average_speed / 150)
                else:
                    speaking_rate = 1.0
                
                _logger.info(f"Using speaking rate: {speaking_rate:.2f} based on detected speed: {average_speed:.1f} WPM")
                
                # Convert translated segments to simple text for TTS
                full_text = translation_result['translated_text']
                if not full_text.strip():
                    raise Exception("No translated text available for dubbing")
                
                # Generate single audio file for entire text using Google TTS with adjusted speed
                language_code = f"{self.translation_language}-VN" if self.translation_language == 'vi' else self.translation_language
                
                # Use Google TTS with speed adjustment
                audio_config = {
                    'speaking_rate': speaking_rate,
                    'pitch': 0.0,
                    'volume_gain_db': 0.0
                }
                
                gcloud_service.text_to_speech_with_config(
                    text=full_text,
                    language_code=language_code,
                    voice_name=self.dubbing_voice,
                    output_path=temp_audio_path,
                    audio_config=audio_config
                )
                
                _logger.info(f"Dubbed audio saved to: {temp_audio_path}")
                
                # Use simple ffmpeg command to replace audio
                cmd = [
                    'ffmpeg',
                    '-i', original_video_path,  # Video input
                    '-i', temp_audio_path,      # Audio input
                    '-c:v', 'copy',             # Copy video codec
                    '-c:a', 'aac',              # Convert audio to AAC
                    '-b:a', '128k',             # Audio bitrate
                    '-map', '0:v:0',            # Use video from first input
                    '-map', '1:a:0',            # Use audio from second input
                    '-shortest',                # End when shortest stream ends
                    '-y',                       # Overwrite output
                    output_path
                ]
                
                _logger.info(f"Creating dubbed video with command: {' '.join(cmd)}")
                _logger.info(f"Audio file location: {temp_audio_path}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                
                if result.returncode != 0:
                    _logger.error(f"FFmpeg dubbing stderr: {result.stderr}")
                    _logger.error(f"FFmpeg dubbing stdout: {result.stdout}")
                    raise Exception(f"FFmpeg dubbing failed: {result.stderr}")
                
                _logger.info(f"Dubbed video created successfully: {output_path}")
                return output_path
                
            except Exception as dubbing_error:
                _logger.error(f"Dubbing creation error: {dubbing_error}")
                # Don't remove temp file on error so we can debug
                raise dubbing_error
                    
        except Exception as e:
            _logger.error(f"Simple dubbing failed: {e}")
            raise e

    def _create_subtitled_video_simple(self, original_video_path, translation_result, output_path):
        """Create subtitled video using simple ffmpeg approach"""
        try:
            # Create subtitle file in /tmp for easy access
            temp_subtitle_path = f"/tmp/subtitles_{self.id}_{self.env.uid}.srt"
            
            try:
                # Generate simple SRT content
                srt_content = self._generate_simple_srt(translation_result['translated_segments'])
                
                # Write subtitle file
                with open(temp_subtitle_path, 'w', encoding='utf-8') as f:
                    f.write(srt_content)
                
                _logger.info(f"Subtitle file saved to: {temp_subtitle_path}")
                
                # Save subtitle as attachment
                self._save_subtitle_as_attachment(temp_subtitle_path)
                
                # Use simple ffmpeg command to burn subtitles into video
                cmd = [
                    'ffmpeg',
                    '-i', original_video_path,
                    '-vf', f"subtitles='{temp_subtitle_path}':force_style='FontSize=20,FontName=Arial,PrimaryColour=&H00ffffff,BackColour=&H80000000'",
                    '-c:a', 'copy',             # Copy audio
                    '-c:v', 'libx264',          # Re-encode video to burn in subtitles
                    '-preset', 'medium',        # Encoding preset
                    '-crf', '23',              # Quality setting
                    '-y',                       # Overwrite output
                    output_path
                ]
                
                _logger.info(f"Creating subtitled video with command: {' '.join(cmd)}")
                _logger.info(f"Subtitle file location: {temp_subtitle_path}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                
                if result.returncode != 0:
                    _logger.error(f"FFmpeg subtitling stderr: {result.stderr}")
                    _logger.error(f"FFmpeg subtitling stdout: {result.stdout}")
                    raise Exception(f"FFmpeg subtitling failed: {result.stderr}")
                
                _logger.info(f"Subtitled video created successfully: {output_path}")
                return output_path
                
            except Exception as subtitle_error:
                _logger.error(f"Subtitle creation error: {subtitle_error}")
                # Don't remove temp file on error so we can debug
                raise subtitle_error
                    
        except Exception as e:
            _logger.error(f"Simple subtitling failed: {e}")
            raise e

    def _generate_simple_srt(self, segments):
        """Generate simple SRT subtitle content"""
        if not segments:
            return "1\n00:00:00,000 --> 00:00:05,000\nNo subtitles available\n\n"
        
        srt_content = ""
        for i, segment in enumerate(segments, 1):
            start_time = segment.get('start', 0)
            end_time = segment.get('end', start_time + 5)
            text = segment.get('text', '').strip()
            
            if not text:
                continue
            
            # Convert seconds to SRT time format (HH:MM:SS,mmm)
            start_srt = self._seconds_to_srt_time(start_time)
            end_srt = self._seconds_to_srt_time(end_time)
            
            srt_content += f"{i}\n{start_srt} --> {end_srt}\n{text}\n\n"
        
        return srt_content
    
    def _seconds_to_srt_time(self, seconds):
        """Convert seconds to SRT time format (HH:MM:SS,mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
    

    
    def _get_video_file_path(self):
        """Get the path to the video file (preferring file path over attachment)"""
        if self.video_file_path and os.path.exists(self.video_file_path):
            return self.video_file_path
        elif self.video_attachment_id:
            # Try to get path from attachment
            attachment = self.video_attachment_id
            if attachment.store_fname:
                filestore_path = self.env['ir.attachment']._filestore()
                full_path = os.path.join(filestore_path, attachment.store_fname)
                if os.path.exists(full_path):
                    return full_path
        return None
    
    def validate_video_file(self):
        """Validate that the video file is not corrupted"""
        self.ensure_one()
        if not self.video_attachment_id:
            return False
            
        attachment = self.video_attachment_id
        
        # Check if attachment has data
        if not attachment.datas:
            _logger.error("Attachment %s has no data", attachment.id)
            return False
            
        # Check file size
        if attachment.file_size < 1024:  # Less than 1KB
            _logger.error("Attachment %s is too small (%d bytes)", 
                         attachment.id, attachment.file_size)
            return False
            
        # Try to decode the base64 data and check header
        try:
            import base64
            file_content = base64.b64decode(attachment.datas)
            
            if len(file_content) < 16:
                _logger.error("Decoded file content too small")
                return False
                
            # Check for common video headers
            # MP4 signature
            if file_content[4:8] == b'ftyp':
                _logger.info("Valid MP4 file detected")
                return True
            # WebM/MKV signature  
            elif file_content[:4] == b'\x1a\x45\xdf\xa3':
                _logger.info("Valid WebM/MKV file detected")
                return True
            # AVI signature
            elif file_content[:4] == b'RIFF' and file_content[8:12] == b'AVI ':
                _logger.info("Valid AVI file detected")
                return True
            else:
                _logger.warning("Unknown video format or corrupted file")
                return False
                
        except Exception as e:
            _logger.error("Error validating video file: %s", e)
            return False
    
    def _save_subtitle_as_attachment(self, subtitle_path):
        """Save subtitle file as attachment"""
        try:
            if not os.path.exists(subtitle_path):
                raise Exception(f"Subtitle file not found: {subtitle_path}")
                
            # Read subtitle content
            with open(subtitle_path, 'rb') as subtitle_file:
                subtitle_content = subtitle_file.read()
            
            # Create attachment
            attachment_name = f"{self.name or 'Video'}_subtitles.srt"
            attachment = self.env['ir.attachment'].create({
                'name': attachment_name,
                'datas': base64.b64encode(subtitle_content),
                'res_model': self._name,
                'res_id': self.id,
                'type': 'binary',
                'mimetype': 'text/plain'
            })
            
            # Update record
            self.write({
                'subtitle_attachment_id': attachment.id,
                'subtitle_file_path': subtitle_path
            })
            
            _logger.info(f"Subtitle file saved as attachment: {attachment_name}")
            return attachment
            
        except Exception as e:
            _logger.error(f"Failed to save subtitle as attachment: {e}")
            return False
    
    def action_download_subtitle_file(self):
        """Download the generated subtitle file"""
        if not self.subtitle_attachment_id:
            raise ValidationError(_("No subtitle file available for download."))
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.subtitle_attachment_id.id}?download=true',
            'target': 'new'
        }
