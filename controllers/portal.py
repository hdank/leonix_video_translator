from odoo.http import Controller, request, route
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.osv.expression import OR
from odoo.exceptions import AccessError, MissingError
from odoo.tools.translate import _
import json
import logging
import os

_logger = logging.getLogger(__name__)

class VideoTranslatorPortal(CustomerPortal):
    
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        
        VideoTranslator = request.env['leonix.video.translator']
        
        if 'video_count' in counters:
            video_count = VideoTranslator.search_count([])
            values['video_count'] = video_count
        
        return values
    
    @route(['/my/video-translations', '/my/video-translations/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_video_translations(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, search=None, search_in='content', groupby=None, **kw):
        values = self._prepare_portal_layout_values()
        VideoTranslator = request.env['leonix.video.translator']
        
        domain = []
        
        # Count for pager
        video_count = VideoTranslator.search_count(domain)
        
        # Pager
        pager = portal_pager(
            url="/my/video-translations",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby},
            total=video_count,
            page=page,
            step=self._items_per_page
        )
        
        # Content according to pager and archive selected
        videos = VideoTranslator.search(domain, limit=self._items_per_page, offset=pager['offset'])
        
        values.update({
            'videos': videos,
            'page_name': 'video_translation',
            'pager': pager,
            'default_url': '/my/video-translations',
        })
        
        return request.render("leonix_video_translator.portal_my_video_translations", values)
        
    @route(['/my/video-translations/<int:video_id>'], type='http', auth="user", website=True)
    def portal_my_video_translation(self, video_id=None, access_token=None, **kw):
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        
        # Fix MIME type if needed for proper video playback
        if video_sudo.state == 'downloaded' and video_sudo.video_attachment_id:
            video_sudo.fix_attachment_mimetype()
            
        values = {
            'video': video_sudo,
            'page_name': 'video_translation',
        }
        return request.render("leonix_video_translator.portal_my_video_translation", values)
        
    @route(['/my/video-translations/<int:video_id>/download'], type='http', auth="user", website=True, methods=['POST'])
    def portal_download_video(self, video_id=None, access_token=None, **kw):
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
            
        if video_sudo.state == 'draft':
            try:
                video_sudo.action_download_video()
                
                # Try to trigger immediate processing
                try:
                    pending_queue = request.env['leonix.video.download.queue'].sudo().search([
                        ('video_translator_id', '=', video_id),
                        ('state', '=', 'pending')
                    ], limit=1)
                    
                    if pending_queue:
                        request.env['leonix.video.download.queue'].sudo().process_pending_downloads()
                        
                except Exception as e:
                    # Log but don't fail the request
                    _logger.info("Could not trigger immediate processing: %s", e)
                    
            except Exception as e:
                _logger.error("Error starting download: %s", str(e))
            
        return request.redirect('/my/video-translations/%s' % video_id)
        
    @route(['/my/video-translations/create'], type='http', auth="user", website=True)
    def portal_create_video_translation(self, **kw):
        if request.httprequest.method == 'POST':
            # Create a new video translation from form data
            values = {
                'name': kw.get('name'),
                'video_url': kw.get('video_url'),
                'description': kw.get('description'),
                'user_id': request.env.user.id
            }
            
            try:
                new_video = request.env['leonix.video.translator'].sudo().create(values)
                return request.redirect('/my/video-translations/%s' % new_video.id)
            except Exception as e:
                request.env.cr.rollback()
                values = {
                    'error_message': str(e),
                    'form_values': values,
                }
                return request.render("leonix_video_translator.portal_create_video_translation", values)
        
        return request.render("leonix_video_translator.portal_create_video_translation", {})
    
    @route(['/my/video-translations/<int:video_id>/progress'], type='json', auth="user", methods=['POST'])
    def portal_video_download_progress(self, video_id=None, **kw):
        """Get download progress for a video"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id)
            return {
                'progress': video_sudo.download_progress,
                'speed': video_sudo.download_speed,
                'eta': video_sudo.estimated_time,
                'state': video_sudo.state,
                'success': True
            }
        except (AccessError, MissingError):
            return {'success': False, 'error': 'Access denied'}
    
    @route(['/my/video-translations/<int:video_id>/watch'], type='http', auth="user", website=True)
    def portal_watch_video(self, video_id=None, access_token=None, **kw):
        """Display video player page"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
            
        if video_sudo.state != 'downloaded' or not video_sudo.video_attachment_id:
            return request.redirect(f'/my/video-translations/{video_id}')
            
        values = {
            'video': video_sudo,
            'page_name': 'video_translation',
        }
        return request.render("leonix_video_translator.portal_watch_video", values)
        
    @route(['/my/video-translations/<int:video_id>/delete'], type='http', auth="user", website=True, methods=['POST'])
    def portal_delete_video(self, video_id=None, access_token=None, **kw):
        """Delete video record completely from portal"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
            
        try:
            # Store video name for success message
            video_name = video_sudo.name
            
            # Completely delete the record (this will also clean up files)
            video_sudo.action_delete_record()
                
            # Add a success message
            request.env['bus.bus']._sendone(
                request.env.user.partner_id, 
                'simple_notification', 
                {
                    'title': "Success", 
                    'message': f"Video '{video_name}' successfully deleted!", 
                    'type': 'success'
                }
            )
        except Exception as e:
            # Log the error and continue
            _logger.error("Error deleting video record: %s", str(e))
            request.env['bus.bus']._sendone(
                request.env.user.partner_id, 
                'simple_notification', 
                {
                    'title': "Error", 
                    'message': f"Error deleting video: {str(e)}", 
                    'type': 'danger'
                }
            )
            
        return request.redirect('/my/video-translations')
    
    @route(['/my/video-translations/<int:video_id>/debug'], type='http', auth="user", website=True)
    def portal_debug_video(self, video_id=None, access_token=None, **kw):
        """Debug video storage locations"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
            
        debug_info = video_sudo.debug_video_storage_locations()
        
        # Add more detailed file information
        custom_storage = debug_info.get('custom_storage')
        if custom_storage and os.path.exists(custom_storage):
            files_info = []
            for file_name in os.listdir(custom_storage):
                file_path = os.path.join(custom_storage, file_name)
                if os.path.isfile(file_path):
                    file_stat = os.stat(file_path)
                    files_info.append({
                        'name': file_name,
                        'size': file_stat.st_size,
                        'size_mb': file_stat.st_size / (1024 * 1024),
                        'modified': file_stat.st_mtime,
                        'path': file_path
                    })
            debug_info['custom_storage_files'] = files_info
        
        # Add streaming URL information
        debug_info['streaming_urls'] = {
            'custom_stream': f'/my/video-translations/{video_id}/stream',
            'odoo_default': f'/web/content/{debug_info.get("attachment_id")}?download=false' if debug_info.get("attachment_id") else None
        }
        
        # Return debug information as formatted JSON
        return request.make_response(
            json.dumps(debug_info, indent=2, default=str),
            headers=[('Content-Type', 'application/json')]
        )
    
    @route(['/my/video-translations/<int:video_id>/repair'], type='http', auth="user", website=True, methods=['POST'])
    def portal_repair_video(self, video_id=None, access_token=None, **kw):
        """Repair corrupted video from portal"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
            
        try:
            # Attempt to repair the video
            result = video_sudo.repair_video_attachment()
            if result:
                return request.redirect(f'/my/video-translations/{video_id}?message=repair_started')
            else:
                return request.redirect(f'/my/video-translations/{video_id}?message=repair_failed')
        except Exception as e:
            _logger.error("Error repairing video: %s", str(e))
            return request.redirect(f'/my/video-translations/{video_id}?message=repair_error')
    
    @route(['/my/video-translations/<int:video_id>/set-language'], type='http', auth="user", website=True, methods=['POST'])
    def portal_set_language(self, video_id=None, access_token=None, **kw):
        """Set translation language and dubbing voice from portal"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        
        translation_language = kw.get('translation_language')
        dubbing_voice = kw.get('dubbing_voice')
        
        update_values = {}
        if translation_language:
            update_values['translation_language'] = translation_language
        if dubbing_voice:
            update_values['dubbing_voice'] = dubbing_voice
        
        if update_values:
            video_sudo.write(update_values)
        
        return request.redirect(f'/my/video-translations/{video_id}')
    
    @route(['/my/video-translations/<int:video_id>/transcribe'], type='http', auth="user", website=True, methods=['POST'])
    def portal_start_transcription(self, video_id=None, access_token=None, **kw):
        """Start transcription from portal"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        
        try:
            video_sudo.action_start_transcription()
        except Exception as e:
            _logger.error("Error starting transcription: %s", str(e))
        
        return request.redirect(f'/my/video-translations/{video_id}')
    
    @route(['/my/video-translations/<int:video_id>/translate'], type='http', auth="user", website=True, methods=['POST'])
    def portal_start_translation(self, video_id=None, access_token=None, **kw):
        """Start translation from portal"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        
        try:
            video_sudo.action_start_translation()
        except Exception as e:
            _logger.error("Error starting translation: %s", str(e))
        
        return request.redirect(f'/my/video-translations/{video_id}')
    
    @route(['/my/video-translations/<int:video_id>/dub'], type='http', auth="user", website=True, methods=['POST'])
    def portal_start_dubbing(self, video_id=None, access_token=None, **kw):
        """Start dubbing from portal"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        
        try:
            video_sudo.action_start_dubbing()
        except Exception as e:
            _logger.error("Error starting dubbing: %s", str(e))
        
        return request.redirect(f'/my/video-translations/{video_id}')
    
    @route(['/my/video-translations/<int:video_id>/transcribe-and-dub'], type='http', auth="user", website=True, methods=['POST'])
    def portal_transcribe_and_dub(self, video_id=None, access_token=None, **kw):
        """Start complete transcription and dubbing workflow from portal"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        
        try:
            video_sudo.action_transcribe_and_dub()
        except Exception as e:
            _logger.error("Error starting complete workflow: %s", str(e))
        
        return request.redirect(f'/my/video-translations/{video_id}')
    
    @route(['/my/video-translations/<int:video_id>/processing-status'], type='json', auth="user", methods=['POST'])
    def portal_processing_status(self, video_id=None, **kw):
        """Get processing status for a video via AJAX"""
        try:
            video_sudo = self._document_check_access('leonix.video.translator', video_id)
            return {
                'transcription_status': video_sudo.transcription_status,
                'translation_status': video_sudo.translation_status,
                'dubbing_status': video_sudo.dubbing_status,
                'state': video_sudo.state,
                'transcription_text': video_sudo.transcription_text or '',
                'translation_text': video_sudo.translation_text or '',
                'has_dubbed_video': bool(video_sudo.dubbed_video_attachment_id),
                'success': True
            }
        except (AccessError, MissingError):
            return {'success': False, 'error': 'Access denied'}
    
    @route(['/my/video-translations/<int:video_id>/processed/<path:filename>'], type='http', auth="user", methods=['GET'])
    def portal_video_processed_stream(self, video_id, filename, **kw):
        """Stream processed video file (dubbed/subtitled)"""
        try:
            video_sudo = self._get_video_check_access(video_id)
            
            if not video_sudo.processed_video_path or not os.path.exists(video_sudo.processed_video_path):
                return request.not_found()
            
            # Stream the processed video file
            return request.env['ir.http']._send_file(video_sudo.processed_video_path)
            
        except (AccessError, MissingError):
            return request.not_found()
    
    @route(['/my/video-translations/<int:video_id>/original/<path:filename>'], type='http', auth="user", methods=['GET'])
    def portal_video_original_stream(self, video_id, filename, **kw):
        """Stream original video file"""
        try:
            video_sudo = self._get_video_check_access(video_id)
            
            if not video_sudo.video_file_path or not os.path.exists(video_sudo.video_file_path):
                return request.not_found()
            
            # Stream the original video file
            return request.env['ir.http']._send_file(video_sudo.video_file_path)
            
        except (AccessError, MissingError):
            return request.not_found()
    
    @route(['/my/video-translations/<int:video_id>/play/processed'], type='http', auth="user", methods=['GET'])
    def portal_video_play_processed(self, video_id, **kw):
        """Play processed video in browser"""
        try:
            video_sudo = self._get_video_check_access(video_id)
            
            if not video_sudo.processed_video_path or not os.path.exists(video_sudo.processed_video_path):
                return request.not_found()
            
            # Return video with proper headers for browser playback
            response = request.env['ir.http']._send_file(video_sudo.processed_video_path)
            response.headers['Content-Type'] = 'video/mp4'
            response.headers['Accept-Ranges'] = 'bytes'
            return response
            
        except (AccessError, MissingError):
            return request.not_found()
    
    @route(['/my/video-translations/<int:video_id>/play/original'], type='http', auth="user", methods=['GET'])
    def portal_video_play_original(self, video_id, **kw):
        """Play original video in browser"""
        try:
            video_sudo = self._get_video_check_access(video_id)
            
            if not video_sudo.video_file_path or not os.path.exists(video_sudo.video_file_path):
                return request.not_found()
            
            # Return video with proper headers for browser playbook
            response = request.env['ir.http']._send_file(video_sudo.video_file_path)
            response.headers['Content-Type'] = 'video/mp4'
            response.headers['Accept-Ranges'] = 'bytes'
            return response
            
        except (AccessError, MissingError):
            return request.not_found()
    
    @route(['/my/video-translations/<int:video_id>/download/<path:filename>'], type='http', auth="user", methods=['GET'])
    def portal_video_download(self, video_id, filename, **kw):
        """Download processed video file"""
        try:
            video_sudo = self._get_video_check_access(video_id)
            
            if not video_sudo.processed_video_path or not os.path.exists(video_sudo.processed_video_path):
                return request.not_found()
            
            # Force download
            response = request.env['ir.http']._send_file(video_sudo.processed_video_path)
            response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
            
        except (AccessError, MissingError):
            return request.not_found()
