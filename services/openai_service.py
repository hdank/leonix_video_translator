import openai
import os
import logging
import tempfile
import subprocess
from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Language name to code mapping (same as in gcloud_service)
LANGUAGE_NAME_TO_CODE = {
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
    # Add more as needed
}

class OpenAIService:
    """Service class for OpenAI API interactions"""
    
    def __init__(self, env):
        self.env = env
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """Initialize OpenAI client with API key from system parameters"""
        api_key = self.env['ir.config_parameter'].sudo().get_param('leonix_video_translator.openai_api_key')
        
        if not api_key:
            raise UserError(_("OpenAI API key is not configured. Please set 'leonix_video_translator.openai_api_key' in system parameters."))
        
        self.client = openai.OpenAI(api_key=api_key)
    
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
            
        # If no match found, log warning and return original
        _logger.warning(f"Unknown language '{language}', using as-is")
        return language_lower
    
    def _get_audio_duration(self, audio_file_path):
        """Get audio file duration using ffprobe"""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                '-of', 'csv=p=0', audio_file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
            else:
                _logger.warning(f"Could not get audio duration from {audio_file_path}")
                return 0.0
        except Exception as e:
            _logger.error(f"Error getting audio duration: {e}")
            return 0.0
    
    def transcribe_audio(self, audio_file_path, language=None, model="whisper-1", prompt=None):
        """
        Transcribe audio file using OpenAI Whisper API with auto-chunking and prompts
        
        Args:
            audio_file_path (str): Path to the audio file
            language (str, optional): Language code (e.g., 'en', 'vi', 'ja')
            model (str): OpenAI model to use for transcription
            prompt (str, optional): Prompt to guide transcription for better accuracy
        
        Returns:
            dict: Transcription result with text and metadata including detailed timeline
        """
        if not os.path.exists(audio_file_path):
            raise Exception(f"Audio file not found: {audio_file_path}")
        
        # Check file size (OpenAI has a 25MB limit for audio files)
        file_size = os.path.getsize(audio_file_path)
        max_size = 25 * 1024 * 1024  # 25MB
        
        # If file is too large, split it into chunks instead of just compressing
        if file_size > max_size:
            _logger.info(f"Audio file is {file_size / (1024*1024):.1f}MB, splitting into chunks...")
            return self._transcribe_large_audio_chunks(audio_file_path, language, model, prompt)
        
        # Create a detailed prompt for better timeline accuracy
        if not prompt:
            prompt = "Please transcribe this audio with precise timing. Pay attention to speech patterns, pauses, and natural breaks in conversation. Include all spoken words and maintain accurate timing for synchronization purposes."
        
        try:
            _logger.info(f"Starting transcription for audio file: {audio_file_path} ({file_size / (1024*1024):.1f}MB)")
            
            # Get audio duration first for fallback timestamps
            audio_duration = self._get_audio_duration(audio_file_path)
            
            with open(audio_file_path, 'rb') as audio_file:
                # Use Whisper with auto-chunking by OpenAI server
                transcribe_params = {
                    "file": audio_file,
                    "model": model,
                    "response_format": "verbose_json",  # Get detailed timestamps and metadata
                    "timestamp_granularities": ["segment"]  # Get segment-level timestamps
                }
                
                # Add language if specified
                if language:
                    normalized_lang = self._normalize_language_code(language)
                    transcribe_params["language"] = normalized_lang
                
                # Add prompt for better transcription accuracy
                if prompt:
                    transcribe_params["prompt"] = prompt
                
                # Call OpenAI transcription API with auto-chunking
                response = self.client.audio.transcriptions.create(**transcribe_params)
                
                # Process the response
                result = {
                    'text': response.text,
                    'language': self._normalize_language_code(response.language if hasattr(response, 'language') else language),
                    'duration': response.duration if hasattr(response, 'duration') else audio_duration,
                    'segments': [],
                    'words': [],
                    'timeline_analysis': {}  # For speech speed and tone analysis
                }
                
                # Extract segments with timestamps
                if hasattr(response, 'segments') and response.segments:
                    for segment in response.segments:
                        segment_data = {
                            'start': segment.start,
                            'end': segment.end,
                            'text': segment.text.strip(),
                            'confidence': getattr(segment, 'avg_logprob', 0),
                            'duration': segment.end - segment.start,
                            'word_count': len(segment.text.split()) if segment.text else 0
                        }
                        if segment_data['text']:  # Only add non-empty segments
                            # Calculate speaking speed (words per minute)
                            if segment_data['duration'] > 0 and segment_data['word_count'] > 0:
                                segment_data['speaking_speed'] = (segment_data['word_count'] / segment_data['duration']) * 60
                            else:
                                segment_data['speaking_speed'] = 0
                            result['segments'].append(segment_data)
                
                # Extract word-level timestamps if available
                if hasattr(response, 'words') and response.words:
                    for word in response.words:
                        word_data = {
                            'start': word.start,
                            'end': word.end,
                            'word': word.word
                        }
                        result['words'].append(word_data)
                
                # Calculate timeline analysis for speech characteristics
                if result['segments']:
                    speeds = [s['speaking_speed'] for s in result['segments'] if 'speaking_speed' in s and s['speaking_speed'] > 0]
                    if speeds:
                        result['timeline_analysis'] = {
                            'average_speaking_speed': sum(speeds) / len(speeds),
                            'min_speaking_speed': min(speeds),
                            'max_speaking_speed': max(speeds),
                            'speed_variance': max(speeds) - min(speeds) if speeds else 0,
                            'total_segments': len(result['segments']),
                            'total_words': sum(s.get('word_count', 0) for s in result['segments'])
                        }
                
                # If no segments available, create a single segment for the entire text
                if not result['segments'] and result['text']:
                    word_count = len(result['text'].split())
                    duration = result.get('duration', 0)
                    # If we still don't have duration, use the calculated audio duration
                    if duration <= 0:
                        duration = audio_duration
                    # If still no duration, estimate based on word count (average ~150 words per minute)
                    if duration <= 0:
                        duration = max(5.0, (word_count / 150.0) * 60.0)  # Minimum 5 seconds
                    
                    speaking_speed = (word_count / duration) * 60 if duration > 0 else 0
                    result['segments'] = [{
                        'start': 0,
                        'end': duration,
                        'text': result['text'],
                        'confidence': 1.0,
                        'duration': duration,
                        'word_count': word_count,
                        'speaking_speed': speaking_speed
                    }]
                
                _logger.info(f"Transcription completed successfully. Text length: {len(result['text'])} characters, Segments: {len(result['segments'])}")
                return result
                
        except Exception as e:
            _logger.error(f"Transcription failed: {str(e)}")
            raise Exception(f"OpenAI transcription failed: {str(e)}")
        finally:
            # Clean up compressed file if it was created
            if audio_file_path != audio_file_path and os.path.exists(audio_file_path):
                try:
                    os.remove(audio_file_path)
                except:
                    pass
    
    def _compress_audio(self, audio_file_path):
        """
        Compress audio file to reduce size for OpenAI API
        
        Args:
            audio_file_path (str): Path to the original audio file
            
        Returns:
            str: Path to the compressed audio file
        """
        try:
            # Create compressed audio file path
            temp_dir = tempfile.mkdtemp(prefix="compressed_audio_")
            compressed_path = os.path.join(temp_dir, "compressed_audio.mp3")
            
            # Use ffmpeg to compress audio
            cmd = [
                'ffmpeg',
                '-i', audio_file_path,
                '-ac', '1',  # Convert to mono
                '-ar', '16000',  # Reduce sample rate to 16kHz
                '-ab', '64k',  # Reduce bitrate to 64kbps
                '-y',  # Overwrite output files
                compressed_path
            ]
            
            _logger.info(f"Compressing audio: {audio_file_path} -> {compressed_path}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0 and os.path.exists(compressed_path):
                compressed_size = os.path.getsize(compressed_path)
                original_size = os.path.getsize(audio_file_path)
                _logger.info(f"Audio compression completed: {original_size / (1024*1024):.1f}MB -> {compressed_size / (1024*1024):.1f}MB")
                return compressed_path
            else:
                _logger.error(f"Audio compression failed: {result.stderr}")
                raise Exception("Failed to compress audio file")
                
        except subprocess.TimeoutExpired:
            _logger.error("Audio compression timed out")
            raise Exception("Audio compression timed out")
        except Exception as e:
            _logger.error(f"Audio compression failed: {e}")
            raise Exception(f"Failed to compress audio: {str(e)}")

    def _transcribe_large_audio_chunks(self, audio_file_path, language=None, model="gpt-4o-mini-transcribe", prompt=None):
        """
        Transcribe large audio files by splitting into chunks
        
        Args:
            audio_file_path (str): Path to the audio file
            language (str, optional): Language code
            model (str): OpenAI model to use for transcription
            prompt (str, optional): Prompt for transcription
        
        Returns:
            dict: Combined transcription result with timeline data
        """
        try:
            # First, get audio duration
            duration_cmd = [
                'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                '-of', 'csv=p=0', audio_file_path
            ]
            result = subprocess.run(duration_cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                raise Exception("Could not get audio duration")
            
            total_duration = float(result.stdout.strip())
            
            # Calculate chunk size based on file size (aim for ~20MB chunks)
            file_size = os.path.getsize(audio_file_path)
            target_chunk_size_mb = 20
            estimated_chunks = max(2, int(file_size / (target_chunk_size_mb * 1024 * 1024)) + 1)
            chunk_duration = total_duration / estimated_chunks
            
            # Ensure minimum chunk duration of 30 seconds
            chunk_duration = max(30, chunk_duration)
            
            _logger.info(f"Splitting {file_size / (1024*1024):.1f}MB audio into chunks of ~{chunk_duration:.1f} seconds")
            
            # Create temporary directory for chunks
            temp_dir = tempfile.mkdtemp(prefix="audio_chunks_")
            chunk_paths = []
            
            # Split audio into chunks
            chunk_num = 0
            start_time = 0
            
            while start_time < total_duration:
                chunk_num += 1
                end_time = min(start_time + chunk_duration, total_duration)
                actual_duration = end_time - start_time
                
                if actual_duration < 5:  # Skip very short chunks
                    break
                
                chunk_path = os.path.join(temp_dir, f"chunk_{chunk_num:03d}.mp3")
                
                # Create chunk with ffmpeg
                cmd = [
                    'ffmpeg',
                    '-i', audio_file_path,
                    '-ss', str(start_time),
                    '-t', str(actual_duration),
                    '-ac', '1',  # Convert to mono to reduce size
                    '-ar', '16000',  # Reduce sample rate to 16kHz
                    '-b:a', '64k',  # Reduce bitrate
                    '-y',  # Overwrite output files
                    chunk_path
                ]
                
                _logger.info(f"Creating chunk {chunk_num}: {start_time:.1f}s - {end_time:.1f}s")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                
                if result.returncode == 0 and os.path.exists(chunk_path):
                    chunk_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
                    _logger.info(f"Chunk {chunk_num} created: {chunk_size_mb:.1f}MB")
                    
                    if chunk_size_mb <= 25:  # Within OpenAI limit
                        chunk_paths.append((chunk_path, start_time, end_time))
                    else:
                        _logger.warning(f"Chunk {chunk_num} is still too large ({chunk_size_mb:.1f}MB), skipping")
                else:
                    _logger.error(f"Failed to create chunk {chunk_num}: {result.stderr}")
                
                start_time = end_time
            
            if not chunk_paths:
                raise Exception("No valid chunks were created")
            
            # Transcribe each chunk and combine results
            combined_result = {
                'text': '',
                'language': language,
                'duration': total_duration,
                'segments': [],
                'words': [],
                'timeline_analysis': {}
            }
            
            all_speeds = []
            
            try:
                for i, (chunk_path, chunk_start, chunk_end) in enumerate(chunk_paths):
                    _logger.info(f"Transcribing chunk {i+1}/{len(chunk_paths)}: {chunk_start:.1f}s - {chunk_end:.1f}s")
                    
                    chunk_result = self.transcribe_audio(chunk_path, language, model, prompt)
                    
                    # Combine text
                    if combined_result['text']:
                        combined_result['text'] += ' '
                    combined_result['text'] += chunk_result['text']
                    
                    # Adjust segment timestamps to absolute time
                    for segment in chunk_result.get('segments', []):
                        adjusted_segment = segment.copy()
                        adjusted_segment['start'] += chunk_start
                        adjusted_segment['end'] += chunk_start
                        combined_result['segments'].append(adjusted_segment)
                        
                        if 'speaking_speed' in adjusted_segment:
                            all_speeds.append(adjusted_segment['speaking_speed'])
                    
                    # Adjust word timestamps to absolute time
                    for word in chunk_result.get('words', []):
                        adjusted_word = word.copy()
                        adjusted_word['start'] += chunk_start
                        adjusted_word['end'] += chunk_start
                        combined_result['words'].append(adjusted_word)
                    
                    # Set language from first successful chunk
                    if not combined_result['language'] and chunk_result.get('language'):
                        combined_result['language'] = chunk_result['language']
                
                # Calculate overall timeline analysis
                if all_speeds:
                    combined_result['timeline_analysis'] = {
                        'average_speaking_speed': sum(all_speeds) / len(all_speeds),
                        'min_speaking_speed': min(all_speeds),
                        'max_speaking_speed': max(all_speeds),
                        'speed_variance': max(all_speeds) - min(all_speeds),
                        'total_segments': len(combined_result['segments']),
                        'total_words': sum(s.get('word_count', 0) for s in combined_result['segments'])
                    }
                
            finally:
                # Clean up chunk files
                for chunk_path, _, _ in chunk_paths:
                    try:
                        os.remove(chunk_path)
                        _logger.info(f"Cleaned up chunk: {chunk_path}")
                    except Exception as e:
                        _logger.warning(f"Failed to cleanup chunk {chunk_path}: {e}")
                
                # Clean up temp directory
                try:
                    os.rmdir(temp_dir)
                except:
                    pass
            
            _logger.info(f"Large audio transcription completed. Total text length: {len(combined_result['text'])} characters, Chunks: {len(chunk_paths)}")
            return combined_result
            
        except Exception as e:
            _logger.error(f"Chunked transcription failed: {e}")
            raise Exception(f"Failed to transcribe large audio file: {str(e)}")

    def get_available_models(self):
        """Get list of available OpenAI models"""
        try:
            models = self.client.models.list()
            whisper_models = [model.id for model in models.data if 'whisper' in model.id]
            return whisper_models
        except Exception as e:
            _logger.warning(f"Failed to get available models: {e}")
            return ['whisper-1']  # Default model
