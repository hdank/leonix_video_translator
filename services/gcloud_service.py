from google.cloud import translate_v2 as translate
from google.cloud import texttospeech
import os
import json
import logging
import tempfile
import subprocess
import shutil
from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Language name to code mapping
LANGUAGE_NAME_TO_CODE = {
    # Common variations
    'english': 'en',
    'vietnamese': 'vi',
    'japanese': 'ja',
    'korean': 'ko',
    'chinese': 'zh',
    'spanish': 'es',
    'french': 'fr',
    'german': 'de',
    'italian': 'it',
    'portuguese': 'pt',
    'russian': 'ru',
    'arabic': 'ar',
    'hindi': 'hi',
    'thai': 'th',
    'dutch': 'nl',
    'swedish': 'sv',
    'danish': 'da',
    'norwegian': 'no',
    'finnish': 'fi',
    'greek': 'el',
    'hebrew': 'he',
    'turkish': 'tr',
    'polish': 'pl',
    'czech': 'cs',
    'hungarian': 'hu',
    'romanian': 'ro',
    'bulgarian': 'bg',
    'ukrainian': 'uk',
    'lithuanian': 'lt',
    'latvian': 'lv',
    'estonian': 'et',
    'slovenian': 'sl',
    'slovak': 'sk',
    'croatian': 'hr',
    'serbian': 'sr',
    'macedonian': 'mk',
    'albanian': 'sq',
    'bosnian': 'bs',
    'montenegrin': 'cnr',
    'catalan': 'ca',
    'basque': 'eu',
    'galician': 'gl',
    'irish': 'ga',
    'scottish gaelic': 'gd',
    'welsh': 'cy',
    'icelandic': 'is',
    'maltese': 'mt',
    'luxembourgish': 'lb',
    'afrikaans': 'af',
    'swahili': 'sw',
    'yoruba': 'yo',
    'zulu': 'zu',
    'xhosa': 'xh',
    'hausa': 'ha',
    'amharic': 'am',
    'oromo': 'om',
    'tigrinya': 'ti',
    'somali': 'so',
    'malagasy': 'mg',
    'shona': 'sn',
    'sesotho': 'st',
    'setswana': 'tn',
    'sindhi': 'sd',
    'urdu': 'ur',
    'punjabi': 'pa',
    'gujarati': 'gu',
    'bengali': 'bn',
    'marathi': 'mr',
    'telugu': 'te',
    'tamil': 'ta',
    'kannada': 'kn',
    'malayalam': 'ml',
    'oriya': 'or',
    'assamese': 'as',
    'nepali': 'ne',
    'sinhala': 'si',
    'myanmar': 'my',
    'khmer': 'km',
    'lao': 'lo',
    'georgian': 'ka',
    'armenian': 'hy',
    'azerbaijani': 'az',
    'kazakh': 'kk',
    'kyrgyz': 'ky',
    'tajik': 'tg',
    'turkmen': 'tk',
    'uzbek': 'uz',
    'mongolian': 'mn',
    'tibetan': 'bo',
    'uighur': 'ug',
    'malay': 'ms',
    'indonesian': 'id',
    'tagalog': 'tl',
    'cebuano': 'ceb',
    'hawaiian': 'haw',
    'maori': 'mi',
    'samoan': 'sm',
    'tongan': 'to',
    'fijian': 'fj',
}

class GoogleCloudService:
    """Service class for Google Cloud API interactions"""
    
    def __init__(self, env):
        self.env = env
        self.translate_client = None
        self.tts_client = None
        self._init_clients()
    
    def _normalize_language_code(self, language):
        """
        Convert language names to standard language codes
        
        Args:
            language (str): Language name or code
            
        Returns:
            str: Standardized language code
        """
        if not language:
            return None
            
        # Convert to lowercase for matching
        language_lower = language.lower().strip()
        
        # If it's already a valid 2-letter code, return as-is
        if len(language_lower) == 2 and language_lower.isalpha():
            return language_lower
        
        # Check if it's a language-country code (e.g., 'en-US')
        if '-' in language_lower and len(language_lower.split('-')[0]) == 2:
            return language_lower.split('-')[0]
            
        # Try to find in our mapping
        normalized_code = LANGUAGE_NAME_TO_CODE.get(language_lower)
        if normalized_code:
            return normalized_code
            
        # If no match found, try to detect using Google Cloud
        try:
            # Use a small sample text to detect language
            detection_result = self.translate_client.detect_language("Hello world")
            _logger.warning(f"Unknown language '{language}', using 'en' as fallback")
            return 'en'
        except Exception as e:
            _logger.warning(f"Language normalization failed for '{language}': {e}. Using 'en' as fallback")
            return 'en'
    
    def _init_clients(self):
        """Initialize Google Cloud clients with credentials"""
        # Get credentials from system parameters
        credentials_json = self.env['ir.config_parameter'].sudo().get_param('leonix_video_translator.gcloud_credentials_json')
        
        if not credentials_json:
            raise UserError(_("Google Cloud credentials are not configured. Please set 'leonix_video_translator.gcloud_credentials_json' in system parameters."))
        
        try:
            # Parse credentials JSON
            credentials_data = json.loads(credentials_json)
            
            # Set environment variable for Google Cloud authentication
            os.environ['GOOGLE_APPLICATION_CREDENTIALS_JSON'] = credentials_json
            
            # Initialize clients
            self.translate_client = translate.Client.from_service_account_info(credentials_data)
            self.tts_client = texttospeech.TextToSpeechClient.from_service_account_info(credentials_data)
            
            _logger.info("Google Cloud clients initialized successfully")
            
        except json.JSONDecodeError:
            raise UserError(_("Invalid Google Cloud credentials JSON format"))
        except Exception as e:
            raise UserError(_("Failed to initialize Google Cloud clients: %s") % str(e))
    
    def get_supported_languages(self):
        """Get list of supported languages for translation"""
        try:
            results = self.translate_client.get_languages()
            languages = []
            
            for language in results:
                languages.append({
                    'code': language['language'],
                    'name': language['name']
                })
            
            return sorted(languages, key=lambda x: x['name'])
            
        except Exception as e:
            _logger.error(f"Failed to get supported languages: {e}")
            # Return common languages as fallback
            return [
                {'code': 'vi', 'name': 'Vietnamese'},
                {'code': 'en', 'name': 'English'},
                {'code': 'ja', 'name': 'Japanese'},
                {'code': 'ko', 'name': 'Korean'},
                {'code': 'zh', 'name': 'Chinese'},
                {'code': 'es', 'name': 'Spanish'},
                {'code': 'fr', 'name': 'French'},
                {'code': 'de', 'name': 'German'},
            ]
    
    def detect_language(self, text):
        """Detect language of given text"""
        try:
            result = self.translate_client.detect_language(text)
            return {
                'language': result['language'],
                'confidence': result['confidence']
            }
        except Exception as e:
            _logger.error(f"Language detection failed: {e}")
            return {'language': 'en', 'confidence': 0}
    
    def translate_text(self, text, target_language, source_language=None):
        """
        Translate text using Google Cloud Translation API
        
        Args:
            text (str): Text to translate
            target_language (str): Target language code
            source_language (str, optional): Source language code
        
        Returns:
            dict: Translation result
        """
        if not text or not text.strip():
            return {'translated_text': '', 'source_language': source_language}
        
        try:
            # Normalize language codes
            target_lang = self._normalize_language_code(target_language)
            source_lang = self._normalize_language_code(source_language) if source_language else None
            
            if not target_lang:
                raise Exception(f"Invalid target language: {target_language}")
            
            _logger.info(f"Translating text to '{target_lang}' from '{source_lang}' (original: '{target_language}'/'{source_language}')")
            
            # Prepare translation parameters
            translate_params = {
                'values': text,
                'target_language': target_lang,
            }
            
            if source_lang and source_lang != target_lang:
                translate_params['source_language'] = source_lang
            
            # Perform translation
            result = self.translate_client.translate(**translate_params)
            
            if isinstance(result, list):
                result = result[0]
            
            return {
                'translated_text': result['translatedText'],
                'source_language': result.get('detectedSourceLanguage', source_lang),
                'input': result.get('input', text)
            }
            
        except Exception as e:
            _logger.error(f"Translation failed: {e}")
            # Provide more detailed error information
            error_msg = str(e)
            if "400" in error_msg and "Invalid Value" in error_msg:
                error_msg = f"Invalid language code. Target: '{target_language}' -> '{target_lang}', Source: '{source_language}' -> '{source_lang}'. {error_msg}"
            raise Exception(f"Google Cloud translation failed: {error_msg}")
    
    def translate_segments(self, segments, target_language, source_language=None):
        """
        Translate transcript segments while preserving timing information
        
        Args:
            segments (list): List of transcript segments with text and timestamps
            target_language (str): Target language code
            source_language (str, optional): Source language code
        
        Returns:
            list: Translated segments with preserved timing
        """
        translated_segments = []
        
        for segment in segments:
            try:
                # Translate the segment text
                translation_result = self.translate_text(
                    segment.get('text', ''), 
                    target_language, 
                    source_language
                )
                
                # Create translated segment with preserved timing
                translated_segment = segment.copy()
                translated_segment['text'] = translation_result['translated_text']
                translated_segment['original_text'] = segment.get('text', '')
                translated_segment['source_language'] = translation_result['source_language']
                translated_segment['target_language'] = target_language
                
                translated_segments.append(translated_segment)
                
            except Exception as e:
                _logger.error(f"Failed to translate segment: {e}")
                # Keep original segment if translation fails
                error_segment = segment.copy()
                error_segment['translation_error'] = str(e)
                translated_segments.append(error_segment)
        
        return translated_segments
    
    def get_available_voices(self, language_code=None):
        """Get available text-to-speech voices"""
        try:
            voices = self.tts_client.list_voices()
            available_voices = []
            
            for voice in voices.voices:
                # Filter by language if specified
                if language_code and not any(lang.startswith(language_code) for lang in voice.language_codes):
                    continue
                
                voice_info = {
                    'name': voice.name,
                    'language_codes': list(voice.language_codes),
                    'ssml_gender': voice.ssml_gender.name,
                    'natural_sample_rate': voice.natural_sample_rate_hertz
                }
                available_voices.append(voice_info)
            
            return available_voices
            
        except Exception as e:
            _logger.error(f"Failed to get available voices: {e}")
            # Return default Vietnamese voice as fallback
            return [
                {
                    'name': 'vi-VN-Chirp3-HD-Achernar',
                    'language_codes': ['vi-VN'],
                    'ssml_gender': 'FEMALE',
                    'natural_sample_rate': 24000
                }
            ]
    
    def text_to_speech(self, text, language_code='vi-VN', voice_name='vi-VN-Chirp3-HD-Achernar', output_path=None):
        """
        Convert text to speech using Google Cloud Text-to-Speech API
        
        Args:
            text (str): Text to convert to speech
            language_code (str): Language code (e.g., 'vi-VN')
            voice_name (str): Voice name to use
            output_path (str, optional): Output file path
        
        Returns:
            str: Path to the generated audio file
        """
        if not text or not text.strip():
            raise Exception("No text provided for text-to-speech conversion")
        
        try:
            # Prepare synthesis input
            synthesis_input = texttospeech.SynthesisInput(text=text)
            
            # Set voice selection parameters
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_name
            )
            
            # Set audio configuration
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=1.0,
                pitch=0.0,
                volume_gain_db=0.0
            )
            
            # Perform text-to-speech request
            _logger.info(f"Converting text to speech: {len(text)} characters using voice {voice_name}")
            response = self.tts_client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            # Generate output path if not provided
            if not output_path:
                import tempfile
                temp_dir = tempfile.gettempdir()
                output_path = os.path.join(temp_dir, f"tts_output_{hash(text) % 10000}.mp3")
            
            # Write audio content to file
            with open(output_path, 'wb') as audio_file:
                audio_file.write(response.audio_content)
            
            if not os.path.exists(output_path):
                raise Exception("Audio file was not created successfully")
            
            file_size = os.path.getsize(output_path)
            _logger.info(f"Text-to-speech completed: {output_path} ({file_size} bytes)")
            
            return output_path
            
        except Exception as e:
            _logger.error(f"Text-to-speech failed: {e}")
            raise Exception(f"Google Cloud text-to-speech failed: {str(e)}")
    
    def text_to_speech_with_config(self, text, language_code='vi-VN', voice_name='vi-VN-Chirp3-HD-Achernar', output_path=None, audio_config=None):
        """
        Convert text to speech with custom audio configuration
        
        Args:
            text (str): Text to convert to speech
            language_code (str): Language code (e.g., 'vi-VN')
            voice_name (str): Voice name to use
            output_path (str, optional): Output file path
            audio_config (dict, optional): Audio configuration with speaking_rate, pitch, volume_gain_db
        
        Returns:
            str: Path to the generated audio file
        """
        if not text or not text.strip():
            raise Exception("No text provided for text-to-speech conversion")
        
        try:
            # Prepare synthesis input
            synthesis_input = texttospeech.SynthesisInput(text=text)
            
            # Set voice selection parameters
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_name
            )
            
            # Set audio configuration with custom settings
            if audio_config is None:
                audio_config = {}
            
            tts_audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=audio_config.get('speaking_rate', 1.0),
                pitch=audio_config.get('pitch', 0.0),
                volume_gain_db=audio_config.get('volume_gain_db', 0.0)
            )
            
            # Perform text-to-speech request
            _logger.info(f"Converting text to speech with config: rate={audio_config.get('speaking_rate', 1.0):.2f}, pitch={audio_config.get('pitch', 0.0):.2f}")
            response = self.tts_client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=tts_audio_config
            )
            
            # Generate output path if not provided
            if not output_path:
                import tempfile
                temp_dir = tempfile.gettempdir()
                output_path = os.path.join(temp_dir, f"tts_configured_{hash(text) % 10000}.mp3")
            
            # Write audio content to file
            with open(output_path, 'wb') as audio_file:
                audio_file.write(response.audio_content)
            
            if not os.path.exists(output_path):
                raise Exception("Audio file was not created successfully")
            
            file_size = os.path.getsize(output_path)
            _logger.info(f"Text-to-speech with config completed: {output_path} ({file_size} bytes)")
            
            return output_path
            
        except Exception as e:
            _logger.error(f"Text-to-speech with config failed: {e}")
            raise Exception(f"Google Cloud text-to-speech failed: {str(e)}")
    
    def synthesize_segments_audio(self, segments, language_code='vi-VN', voice_name='vi-VN-Chirp3-HD-Achernar', output_dir=None):
        """
        Convert multiple text segments to speech with timing information
        
        Args:
            segments (list): List of segments with text and timing
            language_code (str): Language code
            voice_name (str): Voice name to use
            output_dir (str, optional): Output directory for audio files
        
        Returns:
            list: List of audio file paths with timing information
        """
        if not segments:
            return []
        
        if not output_dir:
            import tempfile
            output_dir = tempfile.mkdtemp(prefix="tts_segments_")
        
        os.makedirs(output_dir, exist_ok=True)
        audio_segments = []
        
        for i, segment in enumerate(segments):
            text = segment.get('text', '').strip()
            if not text:
                continue
            
            try:
                # Generate audio for this segment
                segment_audio_path = os.path.join(output_dir, f"segment_{i+1:03d}.mp3")
                
                audio_path = self.text_to_speech(
                    text=text,
                    language_code=language_code,
                    voice_name=voice_name,
                    output_path=segment_audio_path
                )
                
                # Add timing information
                audio_segment = {
                    'audio_path': audio_path,
                    'start_time': segment.get('start', 0),
                    'end_time': segment.get('end', segment.get('start', 0) + 5),  # Ensure end_time is set
                    'text': text,
                    'original_text': segment.get('original_text', ''),
                    'segment_index': i
                }
                
                audio_segments.append(audio_segment)
                _logger.info(f"Generated audio for segment {i+1}/{len(segments)}: start={audio_segment['start_time']}s, end={audio_segment['end_time']}s, text='{text[:50]}...'")
                
            except Exception as e:
                _logger.error(f"Failed to generate audio for segment {i+1}: {e}")
                # Add error info but continue with other segments
                audio_segments.append({
                    'error': str(e),
                    'text': text,
                    'segment_index': i
                })
        
        return audio_segments
    
    def create_synchronized_video(self, original_video_path, segments, output_path=None, processing_mode='both'):
        """
        Create synchronized video with both dubbing and subtitles using advanced alignment
        
        Args:
            original_video_path (str): Path to original video file
            segments (list): List of translated segments with timing
            output_path (str, optional): Output video path
            processing_mode (str): 'dubbing', 'subtitles', or 'both'
        
        Returns:
            dict: Result with paths to created files
        """
        import subprocess
        import tempfile
        from ..utils.audio_sync import AudioSyncProcessor
        
        if not output_path:
            video_dir = os.path.dirname(original_video_path)
            video_name = os.path.splitext(os.path.basename(original_video_path))[0]
            output_path = os.path.join(video_dir, f"{video_name}_synchronized.mp4")
        
        try:
            result = {'success': False, 'video_path': None, 'subtitle_path': None, 'audio_path': None}
            
            # Initialize audio sync processor
            sync_processor = AudioSyncProcessor()
            
            # Extract original audio for analysis
            original_audio_path = os.path.join(tempfile.gettempdir(), f"original_audio_{hash(original_video_path) % 10000}.wav")
            extract_audio_cmd = [
                'ffmpeg', '-i', original_video_path, '-acodec', 'pcm_s16le', 
                '-ar', '16000', '-ac', '1', '-y', original_audio_path
            ]
            subprocess.run(extract_audio_cmd, capture_output=True, text=True)
            
            # Analyze original audio for synchronization
            voice_segments = sync_processor.detect_voice_activity(original_audio_path)
            
            # Get video duration as a float
            try:
                duration_output = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', 
                                               '-of', 'csv=p=0', original_video_path], 
                                              capture_output=True, text=True).stdout.strip()
                video_duration = float(duration_output) if duration_output else 0.0
            except (ValueError, TypeError, subprocess.SubprocessError) as e:
                _logger.warning(f"Could not determine video duration: {e}, using fallback")
                video_duration = 0.0
            
            # Ensure video_duration is a valid number
            if not isinstance(video_duration, (int, float)) or video_duration <= 0:
                _logger.warning(f"Invalid video duration: {video_duration}, using default")
                video_duration = 60.0  # Use 60 seconds as fallback
            
            speaking_rate = sync_processor.calculate_speaking_rate(segments, video_duration)
            
            _logger.info(f"Detected {len(voice_segments)} voice segments")
            _logger.info(f"Speaking rate: {speaking_rate}")
            
            if processing_mode in ['dubbing', 'both']:
                # Create dubbed version with synchronization
                result.update(self._create_synchronized_dubbing(
                    original_video_path, segments, voice_segments, speaking_rate, sync_processor
                ))
            
            if processing_mode in ['subtitles', 'both']:
                # Create subtitle file
                subtitle_path = self._create_synchronized_subtitles(segments, output_path)
                result['subtitle_path'] = subtitle_path
                
                # First create subtitled video
                subtitled_video_path = output_path.replace('.mp4', '_with_subtitles.mp4')
                subtitled_video = self._embed_subtitles_in_video(
                    original_video_path, subtitle_path, subtitled_video_path
                )
                
                if processing_mode == 'subtitles':
                    # Only subtitles requested
                    result['video_path'] = subtitled_video
                elif processing_mode == 'both' and result.get('audio_path') and subtitled_video:
                    # Replace audio in subtitled video (no duplicate subtitles)
                    result['video_path'] = self._replace_audio_in_subtitled_video(
                        subtitled_video, result['audio_path'], output_path
                    )
            
            # Clean up temporary files
            if os.path.exists(original_audio_path):
                os.remove(original_audio_path)
            
            result['success'] = True
            return result
            
        except Exception as e:
            _logger.error(f"Synchronized video creation failed: {e}")
            result['error'] = str(e)
            return result
    
    def _create_synchronized_dubbing(self, original_video_path, segments, voice_segments, speaking_rate, sync_processor):
        """Create synchronized dubbed audio with individual segment speed rates using batched processing"""
        import tempfile
        
        try:
            # Generate individual audio segments with per-segment speed optimization
            temp_audio_dir = tempfile.mkdtemp(prefix="sync_audio_")
            audio_segments = []
            
            # Get global speaking rate as fallback
            global_wpm = speaking_rate.get('words_per_minute', 150) if speaking_rate else 150
            
            # Process segments in smaller batches to avoid 120s timeout
            batch_size = 8  # Smaller batches to ensure we stay under timeout
            total_segments = len(segments)
            
            for batch_start in range(0, total_segments, batch_size):
                batch_end = min(batch_start + batch_size, total_segments)
                batch_segments = segments[batch_start:batch_end]
                
                _logger.info(f"Processing TTS batch {batch_start//batch_size + 1}/{(total_segments + batch_size - 1)//batch_size}: segments {batch_start+1}-{batch_end}")
                
                # Process this batch
                batch_audio_segments = self._process_tts_batch(
                    batch_segments, batch_start, temp_audio_dir, global_wpm
                )
                audio_segments.extend(batch_audio_segments)
                
                # Commit progress after each batch to reset timeout counter
                try:
                    self.env.cr.commit()
                    _logger.info(f"Completed TTS batch {batch_start//batch_size + 1}, total segments processed: {len(audio_segments)}")
                except Exception as commit_error:
                    _logger.warning(f"Could not commit batch progress: {commit_error}")
            
            # Combine audio segments with proper timing and error handling
            if audio_segments:
                combined_audio_path = os.path.join(tempfile.gettempdir(), f"combined_dubbed_{hash(original_video_path) % 10000}.wav")
                
                # Get video duration safely
                try:
                    duration_output = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', 
                                                   '-of', 'csv=p=0', original_video_path], 
                                                  capture_output=True, text=True, timeout=30).stdout.strip()
                    video_duration = float(duration_output) if duration_output else 60.0
                except Exception as e:
                    _logger.warning(f"Could not get video duration: {e}, using 60s default")
                    video_duration = 60.0
                
                combined_path = self._combine_audio_segments_with_timing(audio_segments, combined_audio_path, video_duration)
                if combined_path and os.path.exists(combined_path):
                    return {'audio_path': combined_path}
                else:
                    _logger.error("Failed to combine audio segments")
                    return {'error': 'Failed to combine audio segments'}
            else:
                _logger.warning("No valid audio segments generated")
                return {'error': 'No valid audio segments generated'}
            
        except Exception as e:
            _logger.error(f"Synchronized dubbing creation failed: {e}")
            return {'error': str(e)}
    
    def _process_tts_batch(self, batch_segments, batch_start_index, temp_audio_dir, global_wpm):
        """Process a batch of TTS segments to avoid timeout"""
        batch_audio_segments = []
        
        for i, segment in enumerate(batch_segments):
            actual_index = batch_start_index + i
            text = segment.get('text', '').strip()
            if not text:
                continue
            
            segment_audio_path = os.path.join(temp_audio_dir, f"segment_{actual_index:03d}.mp3")
            
            # Calculate individual segment speed rate
            segment_duration = segment.get('duration', segment.get('end', 0) - segment.get('start', 0))
            segment_word_count = len(text.split())
            
            if segment_duration > 0 and segment_word_count > 0:
                # Calculate segment-specific words per minute
                segment_wpm = (segment_word_count / segment_duration) * 60
                _logger.info(f"Segment {actual_index}: {segment_word_count} words in {segment_duration:.1f}s = {segment_wpm:.1f} WPM")
            else:
                # Use global rate as fallback
                segment_wpm = global_wpm
                _logger.warning(f"Segment {actual_index}: Using global WPM {global_wpm:.1f} (duration={segment_duration}, words={segment_word_count})")
            
            # Calculate optimal TTS rate for this segment
            if segment_wpm > 220:  # Very fast speech
                tts_rate = min(2.0, segment_wpm / 150)
            elif segment_wpm > 180:  # Fast speech
                tts_rate = min(1.6, segment_wpm / 150)
            elif segment_wpm < 80:  # Very slow speech
                tts_rate = max(0.5, segment_wpm / 150)
            elif segment_wpm < 120:  # Slow speech
                tts_rate = max(0.7, segment_wpm / 150)
            else:  # Normal speech
                tts_rate = segment_wpm / 150
            
            # Ensure rate is within reasonable bounds
            tts_rate = max(0.5, min(2.0, tts_rate))
            
            _logger.info(f"Segment {actual_index}: Using TTS rate {tts_rate:.2f} for {segment_wpm:.1f} WPM")
            
            # Use segment-specific TTS settings
            audio_config = {
                'speaking_rate': tts_rate,
                'pitch': 0.0,
                'volume_gain_db': 0.0
            }
            
            try:
                _logger.info(f"Starting TTS for segment {actual_index+1}: '{text[:50]}...' (rate: {tts_rate:.2f})")
                
                self.text_to_speech_with_config(
                    text=text,
                    language_code='vi-VN',  # Adjust as needed
                    voice_name='vi-VN-Chirp3-HD-Achird',
                    output_path=segment_audio_path,
                    audio_config=audio_config
                )
                
                _logger.info(f"Completed TTS for segment {actual_index+1}")
                
                if os.path.exists(segment_audio_path) and os.path.getsize(segment_audio_path) > 0:
                    batch_audio_segments.append({
                        'path': segment_audio_path,
                        'start': segment.get('start', 0),
                        'end': segment.get('end', segment.get('start', 0) + 5),
                        'text': text,
                        'tts_rate': tts_rate,
                        'segment_wpm': segment_wpm
                    })
                    _logger.info(f"Successfully generated audio for segment {actual_index+1}: {segment_audio_path} ({os.path.getsize(segment_audio_path)} bytes)")
                else:
                    _logger.error(f"Failed to generate audio for segment {actual_index+1}: file not created or empty")
                    
            except Exception as segment_error:
                _logger.error(f"Error generating TTS for segment {actual_index+1}: {segment_error}")
                continue
        
        return batch_audio_segments
    
    def _combine_audio_segments_with_timing(self, audio_segments, output_path, video_duration):
        """Combine audio segments with precise timing and error handling"""
        import subprocess
        
        try:
            if not audio_segments:
                _logger.warning("No audio segments to combine")
                return None
            
            _logger.info(f"Combining {len(audio_segments)} audio segments for {video_duration:.1f}s video")
            
            # Validate all segment files exist
            valid_segments = []
            for i, segment in enumerate(audio_segments):
                if os.path.exists(segment['path']) and os.path.getsize(segment['path']) > 0:
                    valid_segments.append(segment)
                    _logger.debug(f"Valid segment {i}: {segment['path']} ({os.path.getsize(segment['path'])} bytes)")
                else:
                    _logger.warning(f"Invalid or missing segment {i}: {segment['path']}")
            
            if not valid_segments:
                _logger.error("No valid audio segments found for combination")
                return None
            
            # Create silent base track
            _logger.info("Creating silent base track...")
            silent_cmd = [
                'ffmpeg', '-f', 'lavfi', '-i', f'anullsrc=channel_layout=mono:sample_rate=16000',
                '-t', str(video_duration), '-y', output_path
            ]
            result = subprocess.run(silent_cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                _logger.error(f"Failed to create silent track: {result.stderr}")
                return None
            
            # Layer each audio segment at its specific time
            filter_inputs = ["[0:a]"]
            input_files = [output_path]
            delayed_labels = []
            
            for i, segment in enumerate(valid_segments):
                input_files.append(segment['path'])
                delay_ms = max(0, int(segment['start'] * 1000))  # Ensure non-negative delay
                
                # Create delay filter for this segment
                filter_inputs.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms}[delayed{i}]")
                delayed_labels.append(f"[delayed{i}]")
                
                _logger.debug(f"Segment {i}: delay={delay_ms}ms, start={segment['start']:.2f}s")
            
            # Process in smaller batches to avoid thread limit errors
            if len(delayed_labels) > 0:
                # Group segments into smaller batches (5 segments per batch)
                batch_size = 5
                current_output = output_path
                
                for batch_idx in range(0, len(valid_segments), batch_size):
                    batch_end = min(batch_idx + batch_size, len(valid_segments))
                    batch_range = range(batch_idx, batch_end)
                    
                    # Create filter for just this batch
                    batch_filter_parts = []
                    batch_delayed_labels = []
                    
                    # Always start with current output as input[0]
                    batch_input_files = [current_output]
                    
                    # Add just this batch of segments
                    for batch_pos, i in enumerate(batch_range):
                        segment = valid_segments[i]
                        batch_input_files.append(segment['path'])
                        delay_ms = max(0, int(segment['start'] * 1000))
                        
                        # Note input[0] is base, so segment inputs start at index 1
                        batch_filter_parts.append(f"[{batch_pos+1}:a]adelay={delay_ms}|{delay_ms}[delayed{batch_pos}]")
                        batch_delayed_labels.append(f"[delayed{batch_pos}]")
                    
                    # Simple mix for just this batch
                    batch_inputs = "[0:a]" + "".join(batch_delayed_labels)
                    batch_num_inputs = len(batch_delayed_labels) + 1
                    
                    batch_filter_complex = ";".join(batch_filter_parts) + f";{batch_inputs}amix=inputs={batch_num_inputs}:duration=longest:normalize=0[mixed]"
                    
                    temp_output = f"{output_path}_batch_{batch_idx}.wav"
                    
                    # Build command with more conservative settings
                    mix_cmd = [
                        'ffmpeg', '-y',
                        *[item for sublist in [['-i', f] for f in batch_input_files] for item in sublist],
                        '-filter_complex', batch_filter_complex,
                        '-map', '[mixed]',
                        '-c:a', 'pcm_s16le',
                        '-ar', '16000',
                        '-threads', '2',                # Limit threads to avoid resource exhaustion
                        '-max_muxing_queue_size', '1024', # Avoid queue errors
                        temp_output
                    ]
                    
                    _logger.info(f"Running batch {batch_idx//batch_size + 1}/{(len(valid_segments) + batch_size - 1)//batch_size} with {len(batch_input_files)} inputs")
                    
                    result = subprocess.run(mix_cmd, capture_output=True, text=True, timeout=300)
                    if result.returncode == 0:
                        if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
                            # Use this output as input for next batch
                            if os.path.exists(current_output) and current_output != output_path:
                                os.remove(current_output)  # Clean up intermediate file
                            
                            if batch_end >= len(valid_segments):  # Last batch
                                os.replace(temp_output, output_path)
                                _logger.info(f"Final batch complete: {output_path} ({os.path.getsize(output_path)} bytes)")
                            else:
                                # Intermediate batch - save for next iteration
                                current_output = temp_output
                                _logger.info(f"Batch {batch_idx//batch_size + 1} complete")
                        else:
                            _logger.error(f"Batch {batch_idx//batch_size + 1} output file is empty")
                            return None
                    else:
                        _logger.error(f"Batch {batch_idx//batch_size + 1} audio mixing failed: {result.stderr}")
                        _logger.debug(f"Audio mixing stdout: {result.stdout}")
                        return None
            
            return output_path if os.path.exists(output_path) else None
            
        except Exception as e:
            _logger.error(f"Audio segment combination failed: {e}")
            return None
    
    def _create_synchronized_subtitles(self, segments, base_output_path):
        """Create synchronized subtitle file"""
        try:
            subtitle_path = base_output_path.replace('.mp4', '.srt')
            
            with open(subtitle_path, 'w', encoding='utf-8') as f:
                for i, segment in enumerate(segments, 1):
                    start_time = segment.get('start', 0)
                    end_time = segment.get('end', start_time + 5)
                    text = segment.get('text', '').strip()
                    
                    if not text:
                        continue
                    
                    start_srt = self._seconds_to_srt_time(start_time)
                    end_srt = self._seconds_to_srt_time(end_time)
                    
                    f.write(f"{i}\n{start_srt} --> {end_srt}\n{text}\n\n")
            
            return subtitle_path
            
        except Exception as e:
            _logger.error(f"Subtitle creation failed: {e}")
            return None
    
    def _escape_subtitle_path(self, path: str) -> str:
        """Escape subtitle path for ffmpeg subtitles filter on Linux."""
        if not path:
            return path
        # Escape backslashes, colons, single quotes and commas which break filter args
        escaped = (
            path
            .replace('\\', r'\\\\')
            .replace(':', r'\:')
            .replace("'", r"\\'")
            .replace(',', r'\,')
        )
        return escaped
    
    def _mux_soft_subtitles(self, video_path, subtitle_path, output_path):
        """Prefer soft-subtitles: keep video/audio streams, mux SRT as mov_text into MP4."""
        try:
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,            # 0: original video+audio
                '-i', subtitle_path,         # 1: srt
                '-map', '0:v:0',             # video from original
                '-map', '0:a?',              # optional audio from original
                '-map', '1:0',               # subtitle stream from srt
                '-c:v', 'copy',              # no re-encode video
                '-c:a', 'copy',              # no re-encode audio
                '-c:s', 'mov_text',          # mp4-friendly subtitle codec
                '-movflags', '+faststart',   # web-friendly
                output_path
            ]
            _logger.info(f"Muxing soft subtitles (no re-encode): {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if result.returncode != 0:
                _logger.error(f"Soft-sub muxing failed: {result.stderr}")
                return None
            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                _logger.error("Soft-sub output file not created or empty")
                return None
            return output_path
        except Exception as e:
            _logger.error(f"Soft-sub muxing error: {e}")
            return None
    
    def _embed_subtitles_in_video(self, video_path, subtitle_path, output_path):
        """Embed subtitles into video.
        Strategy:
        1) Try soft-subtitles (no re-encode) into MP4 using mov_text.
        2) If that fails, try external subtitle file alongside the video
        3) If that fails, try simpler hard-burn approach
        4) Last resort: simplest possible hard-burn with minimum options
        """
        try:
            # 1) Try soft-subtitles first (no re-encode)
            _logger.info("ATTEMPT 1: Soft-subtitle muxing (no re-encode)")
            soft_out = self._mux_soft_subtitles(video_path, subtitle_path, output_path)
            if soft_out and os.path.exists(soft_out) and os.path.getsize(soft_out) > 0:
                _logger.info(f"Soft subtitle muxing succeeded: {soft_out}")
                return soft_out
            
            # 2) Try creating a copy of the video with external subtitle file
            _logger.info("ATTEMPT 2: External subtitle with remux")
            ext_sub_path = output_path.replace('.mp4', '_with_external_sub.mp4')
            ext_sub_cmd = [
                'ffmpeg', '-y',
                '-i', video_path,
                '-c:v', 'copy',        # Copy video stream as-is
                '-c:a', 'copy',        # Copy audio stream as-is
                ext_sub_path
            ]
            
            try:
                # Just try a simple stream copy
                subprocess.run(ext_sub_cmd, capture_output=True, text=True, timeout=900)
                if os.path.exists(ext_sub_path) and os.path.getsize(ext_sub_path) > 0:
                    # Successfully created a copy - use external subtitle file
                    dst_subtitle = ext_sub_path.replace('.mp4', '.srt')
                    shutil.copy2(subtitle_path, dst_subtitle)
                    _logger.info(f"Created video copy with external subtitle: {ext_sub_path}")
                    return ext_sub_path
            except Exception as ext_error:
                _logger.warning(f"External subtitle approach failed: {ext_error}")

            # 3) Try alternative simpler hardburn method
            _logger.info("ATTEMPT 3: Simple hard-burn with minimal options")
            try:
                simple_output = output_path.replace('.mp4', '_simple.mp4')
                escaped_sub_path = self._escape_subtitle_path(subtitle_path)
                simple_cmd = [
                    'ffmpeg', '-y',
                    '-i', video_path,
                    '-vf', f"subtitles='{escaped_sub_path}'",  # Simpler subtitle filter without styles
                    '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p',
                    '-preset', 'ultrafast',  # Fastest encoding
                    '-crf', '28',            # Lower quality but faster
                    '-c:a', 'copy',
                    simple_output
                ]
                
                _logger.info(f"Simple hardburn attempt: {' '.join(simple_cmd)}")
                result = subprocess.run(simple_cmd, capture_output=True, text=True, timeout=1800)
                
                if result.returncode == 0 and os.path.exists(simple_output) and os.path.getsize(simple_output) > 0:
                    os.rename(simple_output, output_path)
                    _logger.info(f"Simple hard-burn succeeded: {output_path}")
                    return output_path
            except Exception as simple_error:
                _logger.warning(f"Simple hard-burn failed: {simple_error}")

            # 4) Last resort: absolute bare minimum approach
            _logger.info("ATTEMPT 4: Absolute minimal hardcoded subtitle approach")
            minimal_output = output_path.replace('.mp4', '_minimal.mp4')
            # Create a temporary SRT file with ASCII-only text to avoid encoding issues
            simplified_srt = subtitle_path + ".simplified"
            
            try:
                with open(subtitle_path, 'r', encoding='utf-8') as f_in:
                    srt_content = f_in.read()
                    
                # Keep timestamps but simplify text (remove non-ASCII chars)
                simplified_content = ""
                for line in srt_content.split('\n'):
                    if '-->' in line or line.strip().isdigit() or not line.strip():
                        simplified_content += line + '\n'
                    else:
                        # Keep ASCII only and simplify
                        simplified_content += ''.join(c if ord(c) < 128 else '_' for c in line) + '\n'
                        
                with open(simplified_srt, 'w', encoding='utf-8') as f_out:
                    f_out.write(simplified_content)
                    
                # Absolute minimal approach
                minimal_cmd = [
                    'ffmpeg', '-y',
                    '-i', video_path,
                    '-sub_charenc', 'UTF-8',
                    '-i', simplified_srt,
                    '-c:v', 'copy',             # Copy video
                    '-c:a', 'copy',             # Copy audio
                    '-c:s', 'mov_text',         # Convert subtitle to mov_text
                    minimal_output
                ]
                
                _logger.info(f"Minimal subtitle approach: {' '.join(minimal_cmd)}")
                subprocess.run(minimal_cmd, capture_output=True, text=True, timeout=900)
                
                if os.path.exists(minimal_output) and os.path.getsize(minimal_output) > 0:
                    os.rename(minimal_output, output_path)
                    _logger.info(f"Minimal subtitle approach succeeded: {output_path}")
                    return output_path
                    
            except Exception as minimal_error:
                _logger.error(f"Minimal subtitle approach failed: {minimal_error}")
            
            # If we get here, all attempts failed
            _logger.error("All subtitle embedding methods failed")
            return None
            
        except Exception as e:
            _logger.error(f"Subtitle embedding failed: {e}")
            return None
    
    def _replace_audio_in_subtitled_video(self, subtitled_video_path, audio_path, output_path):
        """Replace audio in an already-subtitled video and preserve subtitle streams if present."""
        try:
            # Validate input files exist
            if not os.path.exists(subtitled_video_path):
                raise Exception(f"Subtitled video file not found: {subtitled_video_path}")
            if not os.path.exists(audio_path):
                raise Exception(f"Audio file not found: {audio_path}")

            _logger.info(f"Replacing audio in subtitled video: {output_path}")
            _logger.info(f"Subtitled Video: {subtitled_video_path} ({os.path.getsize(subtitled_video_path)} bytes)")
            _logger.info(f"New Audio: {audio_path} ({os.path.getsize(audio_path)} bytes)")

            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Preserve video and any subtitle streams; replace audio
            cmd = [
                'ffmpeg', '-y',
                '-i', subtitled_video_path,  # 0: video (+ maybe subs)
                '-i', audio_path,            # 1: new dubbed audio
                '-map', '0:v:0',             # keep video
                '-map', '0:s?',              # keep existing subs if any (optional)
                '-map', '1:a:0',             # replace audio
                '-c:v', 'copy',              # no re-encode video
                '-c:a', 'aac', '-b:a', '128k',
                '-c:s', 'copy',              # keep subs codec (mov_text if soft-subbed)
                '-shortest',
                '-movflags', '+faststart',
                output_path
            ]

            _logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

            if result.returncode != 0:
                _logger.error(f"FFmpeg stdout: {result.stdout}")
                _logger.error(f"FFmpeg stderr: {result.stderr}")
                raise Exception(f"FFmpeg audio replacement failed with code {result.returncode}: {result.stderr}")

            if not os.path.exists(output_path):
                raise Exception(f"Output file was not created: {output_path}")

            output_size = os.path.getsize(output_path)
            _logger.info(f"Successfully replaced audio in subtitled video: {output_path} ({output_size} bytes)")

            # Clean up temporary subtitled video when different from output
            if os.path.exists(subtitled_video_path) and os.path.abspath(subtitled_video_path) != os.path.abspath(output_path):
                try:
                    os.remove(subtitled_video_path)
                    _logger.debug(f"Cleaned up temporary subtitled video: {subtitled_video_path}")
                except Exception as cleanup_error:
                    _logger.warning(f"Could not clean up temporary file {subtitled_video_path}: {cleanup_error}")

            return output_path
        except Exception as e:
            _logger.error(f"Audio replacement in subtitled video failed: {e}")
            return None

    def _create_dubbed_and_subtitled_video(self, video_path, audio_path, subtitle_path, output_path):
        """Create video with both dubbed audio and subtitles"""
        try:
            # Validate input files exist
            if not os.path.exists(video_path):
                raise Exception(f"Video file not found: {video_path}")
            if not os.path.exists(audio_path):
                raise Exception(f"Audio file not found: {audio_path}")
            if not os.path.exists(subtitle_path):
                raise Exception(f"Subtitle file not found: {subtitle_path}")
            
            _logger.info(f"Creating dubbed and subtitled video: {output_path}")
            _logger.info(f"Video: {video_path} ({os.path.getsize(video_path)} bytes)")
            _logger.info(f"Audio: {audio_path} ({os.path.getsize(audio_path)} bytes)")
            _logger.info(f"Subtitle: {subtitle_path} ({os.path.getsize(subtitle_path)} bytes)")
            
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            cmd = [
                'ffmpeg', 
                '-i', video_path,       # Original video
                '-i', audio_path,       # Dubbed audio
                '-vf', f"subtitles='{subtitle_path}':force_style='FontSize=18,FontName=Arial,PrimaryColour=&H00ffffff,BackColour=&H80000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=20'",
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
                '-c:a', 'aac', '-b:a', '128k',
                '-map', '0:v:0',        # Video from first input
                '-map', '1:a:0',        # Audio from second input
                '-shortest',
                '-y', output_path
            ]
            
            _logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            
            if result.returncode != 0:
                _logger.error(f"FFmpeg stdout: {result.stdout}")
                _logger.error(f"FFmpeg stderr: {result.stderr}")
                raise Exception(f"FFmpeg combining failed with code {result.returncode}: {result.stderr}")
            
            if not os.path.exists(output_path):
                raise Exception(f"Output file was not created: {output_path}")
            
            output_size = os.path.getsize(output_path)
            _logger.info(f"Successfully created combined video: {output_path} ({output_size} bytes)")
            
            return output_path
            
        except Exception as e:
            _logger.error(f"Combined video creation failed: {e}")
            return None
            output_dir = tempfile.mkdtemp(prefix="tts_segments_")
        
        os.makedirs(output_dir, exist_ok=True)
        audio_segments = []
        
        for i, segment in enumerate(segments):
            text = segment.get('text', '').strip()
            if not text:
                continue
            
            try:
                # Generate audio for this segment
                segment_audio_path = os.path.join(output_dir, f"segment_{i+1:03d}.mp3")
                
                audio_path = self.text_to_speech(
                    text=text,
                    language_code=language_code,
                    voice_name=voice_name,
                    output_path=segment_audio_path
                )
                
                # Add timing information
                audio_segment = {
                    'audio_path': audio_path,
                    'start_time': segment.get('start', 0),
                    'end_time': segment.get('end', segment.get('start', 0) + 5),  # Ensure end_time is set
                    'text': text,
                    'original_text': segment.get('original_text', ''),
                    'segment_index': i
                }
                
                audio_segments.append(audio_segment)
                _logger.info(f"Generated audio for segment {i+1}/{len(segments)}: start={audio_segment['start_time']}s, end={audio_segment['end_time']}s, text='{text[:50]}...'")
                
            except Exception as e:
                _logger.error(f"Failed to generate audio for segment {i+1}: {e}")
                # Add error info but continue with other segments
                audio_segments.append({
                    'error': str(e),
                    'text': text,
                    'segment_index': i
                })
        
        return audio_segments
    
    def create_dubbed_video(self, original_video_path, audio_segments, output_path=None):
        """
        Create dubbed video by replacing original audio with generated speech
        
        Args:
            original_video_path (str): Path to original video file
            audio_segments (list): List of audio segments with timing
            output_path (str, optional): Output video path
        
        Returns:
            str: Path to the dubbed video file
        """
        import subprocess
        import tempfile
        
        if not output_path:
            video_dir = os.path.dirname(original_video_path)
            video_name = os.path.splitext(os.path.basename(original_video_path))[0]
            output_path = os.path.join(video_dir, f"{video_name}_dubbed.mp4")
        
        try:
            # Create a temporary audio track by combining all segments
            temp_audio_path = os.path.join(tempfile.gettempdir(), "combined_dubbed_audio.wav")
            
            # Get original video duration
            duration_cmd = [
                'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                '-of', 'csv=p=0', original_video_path
            ]
            duration_result = subprocess.run(duration_cmd, capture_output=True, text=True)
            if duration_result.returncode != 0:
                raise Exception("Could not get original video duration")
            
            video_duration = float(duration_result.stdout.strip())
            
            # Create silent audio track with same duration as video
            silent_audio_cmd = [
                'ffmpeg', '-f', 'lavfi', '-i', f'anullsrc=channel_layout=mono:sample_rate=48000',
                '-t', str(video_duration), '-y', temp_audio_path
            ]
            
            subprocess.run(silent_audio_cmd, capture_output=True, text=True)
            
            # Mix in the dubbed audio segments
            filter_complex_parts = []
            input_files = [original_video_path, temp_audio_path]
            
            # Sort segments by start time to avoid overlapping
            valid_segments = []
            for segment in audio_segments:
                if 'audio_path' in segment and os.path.exists(segment['audio_path']):
                    valid_segments.append(segment)
            
            # Sort by start time
            valid_segments.sort(key=lambda x: x.get('start_time', 0))
            
            # Remove overlapping segments to prevent multiple voices
            non_overlapping_segments = self._resolve_overlapping_segments(valid_segments)
            
            _logger.info(f"Processing {len(non_overlapping_segments)} non-overlapping audio segments (out of {len(valid_segments)} total)")
            
            for i, segment in enumerate(non_overlapping_segments):
                input_files.append(segment['audio_path'])
                start_time = segment['start_time']
                
                # Log segment timing for debugging
                _logger.info(f"Segment {i}: start={start_time}s, audio_path={segment['audio_path']}")
                
                # Add this segment to the filter complex with proper delay
                # Convert start time to milliseconds for adelay filter
                delay_ms = int(start_time * 1000)
                filter_complex_parts.append(f"[{i+2}:a]adelay={delay_ms}|{delay_ms}[delayed{i}]")
            
            # Combine all audio tracks
            if filter_complex_parts:
                # Build the input list for amix: base silent track + all delayed segments
                input_labels = ['[1:a]'] + [f"[delayed{i}]" for i in range(len(filter_complex_parts))]
                
                # Construct the complete filter complex with proper syntax
                filter_complex = ';'.join(filter_complex_parts)
                # Use proper amix syntax with volume control to prevent overlapping
                amix_inputs = ''.join(input_labels)
                # Reduce volume of each input to prevent clipping when mixing multiple audio tracks
                volume_per_input = 1.0 / len(input_labels)
                filter_complex += f";{amix_inputs}amix=inputs={len(input_labels)}:duration=longest:weights='{' '.join([str(volume_per_input)] * len(input_labels))}'[mixed]"
                
                _logger.info(f"Filter complex: {filter_complex}")
                _logger.info(f"Input files: {input_files}")
                _logger.info(f"Volume per input: {volume_per_input}")
                
                # Validate that we don't have too many overlapping segments
                if len(non_overlapping_segments) > 10:
                    _logger.warning(f"Large number of audio segments ({len(non_overlapping_segments)}). This might cause audio quality issues.")
                
                # Create final dubbed video
                ffmpeg_cmd = [
                    'ffmpeg',
                    *[item for sublist in [['-i', f] for f in input_files] for item in sublist],
                    '-filter_complex', filter_complex,
                    '-map', '0:v',  # Video from original
                    '-map', '[mixed]',  # Mixed audio
                    '-c:v', 'copy',  # Copy video without re-encoding
                    '-c:a', 'aac',  # Encode audio as AAC
                    '-b:a', '128k',  # Set audio bitrate
                    '-y',  # Overwrite output
                    output_path
                ]
                
                _logger.info(f"Creating dubbed video: {output_path}")
                _logger.info(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
                result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=1800)  # 30 minutes timeout
                
                if result.returncode != 0:
                    _logger.error(f"FFmpeg error: {result.stderr}")
                    raise Exception(f"Video dubbing failed: {result.stderr}")
            else:
                # No audio segments to mix, just copy original video with silent audio
                ffmpeg_cmd = [
                    'ffmpeg',
                    '-i', original_video_path,
                    '-i', temp_audio_path,
                    '-map', '0:v',  # Video from original
                    '-map', '1:a',  # Silent audio
                    '-c:v', 'copy',  # Copy video without re-encoding
                    '-c:a', 'aac',  # Encode audio as AAC
                    '-y',  # Overwrite output
                    output_path
                ]
                
                _logger.info(f"Creating dubbed video with silent audio: {output_path}")
                result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=1800)
                
                if result.returncode != 0:
                    _logger.error(f"FFmpeg error: {result.stderr}")
                    raise Exception(f"Video dubbing failed: {result.stderr}")
            
            # Clean up temporary files
            if os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
            
            if not os.path.exists(output_path):
                raise Exception("Dubbed video was not created successfully")
            
            file_size = os.path.getsize(output_path)
            _logger.info(f"Dubbed video created successfully: {output_path} ({file_size / (1024*1024):.1f}MB)")
            
            return output_path
            
        except Exception as e:
            _logger.error(f"Video dubbing failed: {e}")
            raise Exception(f"Failed to create dubbed video: {str(e)}")
    
    def _resolve_overlapping_segments(self, segments):
        """
        Remove overlapping segments to prevent multiple voices speaking at the same time
        
        Args:
            segments (list): List of audio segments sorted by start_time
        
        Returns:
            list: List of non-overlapping segments
        """
        if not segments:
            return []
        
        non_overlapping = []
        current_end_time = 0
        
        for segment in segments:
            start_time = segment.get('start_time', 0)
            end_time = segment.get('end_time', start_time + 5)  # Default 5 second duration
            
            # If this segment starts after the current end time, it doesn't overlap
            if start_time >= current_end_time + 0.1:  # Add 0.1 second buffer between segments
                non_overlapping.append(segment)
                current_end_time = end_time
                _logger.info(f"Added segment: start={start_time}s, end={end_time}s")
            else:
                # This segment overlaps, skip it
                _logger.warning(f"Skipping overlapping segment: start={start_time}s, end={end_time}s (conflicts with previous ending at {current_end_time}s)")
        
        return non_overlapping
    
    def generate_subtitle_file(self, segments, output_path=None, subtitle_format='srt'):
        """
        Generate subtitle file from translated segments
        
        Args:
            segments (list): List of translated segments with timing
            output_path (str, optional): Output subtitle file path
            subtitle_format (str): Subtitle format ('srt', 'vtt', 'ass')
        
        Returns:
            str: Path to the generated subtitle file
        """
        import tempfile
        
        if not segments:
            raise Exception("No segments provided for subtitle generation")
        
        if not output_path:
            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"subtitles.{subtitle_format}")
        
        try:
            subtitle_content = ""
            
            if subtitle_format.lower() == 'srt':
                subtitle_content = self._generate_srt_content(segments)
            elif subtitle_format.lower() == 'vtt':
                subtitle_content = self._generate_vtt_content(segments)
            elif subtitle_format.lower() == 'ass':
                subtitle_content = self._generate_ass_content(segments)
            else:
                raise Exception(f"Unsupported subtitle format: {subtitle_format}")
            
            # Write subtitle content to file
            with open(output_path, 'w', encoding='utf-8') as subtitle_file:
                subtitle_file.write(subtitle_content)
            
            if not os.path.exists(output_path):
                raise Exception("Subtitle file was not created successfully")
            
            file_size = os.path.getsize(output_path)
            _logger.info(f"Subtitle file created successfully: {output_path} ({file_size} bytes)")
            
            return output_path
            
        except Exception as e:
            _logger.error(f"Subtitle generation failed: {e}")
            raise Exception(f"Failed to generate subtitle file: {str(e)}")
    
    def _generate_srt_content(self, segments):
        """Generate SRT subtitle content"""
        srt_content = ""
        
        for i, segment in enumerate(segments, 1):
            start_time = segment.get('start', segment.get('start_time', 0))
            end_time = segment.get('end', segment.get('end_time', start_time + 5))
            text = segment.get('text', '')
            
            if not text.strip():
                continue
            
            # Convert time to SRT format (HH:MM:SS,mmm)
            start_srt = self._seconds_to_srt_time(start_time)
            end_srt = self._seconds_to_srt_time(end_time)
            
            srt_content += f"{i}\n{start_srt} --> {end_srt}\n{text.strip()}\n\n"
        
        return srt_content
    
    def _generate_vtt_content(self, segments):
        """Generate WebVTT subtitle content"""
        vtt_content = "WEBVTT\n\n"
        
        for i, segment in enumerate(segments, 1):
            start_time = segment.get('start', segment.get('start_time', 0))
            end_time = segment.get('end', segment.get('end_time', start_time + 5))
            text = segment.get('text', '')
            
            if not text.strip():
                continue
            
            # Convert time to VTT format (HH:MM:SS.mmm)
            start_vtt = self._seconds_to_vtt_time(start_time)
            end_vtt = self._seconds_to_vtt_time(end_time)
            
            vtt_content += f"{start_vtt} --> {end_vtt}\n{text.strip()}\n\n"
        
        return vtt_content
    
    def _generate_ass_content(self, segments):
        """Generate ASS subtitle content"""
        ass_header = """[Script Info]
Title: Generated Subtitles
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        ass_content = ass_header
        
        for segment in segments:
            start_time = segment.get('start', segment.get('start_time', 0))
            end_time = segment.get('end', segment.get('end_time', start_time + 5))
            text = segment.get('text', '')
            
            if not text.strip():
                continue
            
            # Convert time to ASS format (H:MM:SS.cc)
            start_ass = self._seconds_to_ass_time(start_time)
            end_ass = self._seconds_to_ass_time(end_time)
            
            # Escape text for ASS format
            text_escaped = text.replace('\n', '\\N').replace('{', '\\{').replace('}', '\\}')
            
            ass_content += f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{text_escaped}\n"
        
        return ass_content
    
    def _seconds_to_srt_time(self, seconds):
        """Convert seconds to SRT time format (HH:MM:SS,mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
    
    def _seconds_to_vtt_time(self, seconds):
        """Convert seconds to WebVTT time format (HH:MM:SS.mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"
    
    def _seconds_to_ass_time(self, seconds):
        """Convert seconds to ASS time format (H:MM:SS.cc)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:05.2f}"
    
    def create_subtitled_video(self, original_video_path, subtitle_path, output_path=None):
        """
        Create video with embedded subtitles
        
        Args:
            original_video_path (str): Path to original video file
            subtitle_path (str): Path to subtitle file
            output_path (str, optional): Output video path
        
        Returns:
            str: Path to the subtitled video file
        """
        import subprocess
        
        if not output_path:
            video_dir = os.path.dirname(original_video_path)
            video_name = os.path.splitext(os.path.basename(original_video_path))[0]
            output_path = os.path.join(video_dir, f"{video_name}_subtitled.mp4")
        
        try:
            # Create subtitled video using FFmpeg
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', original_video_path,
                '-vf', f"subtitles='{subtitle_path}'",
                '-c:a', 'copy',  # Copy audio without re-encoding
                '-y',  # Overwrite output
                output_path
            ]
            
            _logger.info(f"Creating subtitled video: {output_path}")
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=1800)  # 30 minutes timeout
            
            if result.returncode != 0:
                _logger.error(f"FFmpeg error: {result.stderr}")
                raise Exception(f"Video subtitling failed: {result.stderr}")
            
            if not os.path.exists(output_path):
                raise Exception("Subtitled video was not created successfully")
            
            file_size = os.path.getsize(output_path)
            _logger.info(f"Subtitled video created successfully: {output_path} ({file_size / (1024*1024):.1f}MB)")
            
            return output_path
            
        except Exception as e:
            _logger.error(f"Video subtitling failed: {e}")
            raise Exception(f"Failed to create subtitled video: {str(e)}")
