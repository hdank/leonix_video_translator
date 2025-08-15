import numpy as np
import librosa
import scipy.signal
from scipy.spatial.distance import cdist
from scipy.optimize import linear_sum_assignment
import logging

_logger = logging.getLogger(__name__)

class AudioSyncProcessor:
    """Advanced audio synchronization for video translation"""
    
    def __init__(self):
        self.sample_rate = 16000  # Standard rate for speech processing
        self.hop_length = 512
        self.n_mfcc = 13
        
    def extract_mfcc_features(self, audio_path, segment_start=None, segment_end=None):
        """Extract MFCC features from audio file"""
        try:
            # Load audio file
            y, sr = librosa.load(audio_path, sr=self.sample_rate)
            
            # Extract segment if specified
            if segment_start is not None and segment_end is not None:
                start_sample = int(segment_start * sr)
                end_sample = int(segment_end * sr)
                y = y[start_sample:end_sample]
            
            # Extract MFCC features
            mfccs = librosa.feature.mfcc(
                y=y, 
                sr=sr, 
                n_mfcc=self.n_mfcc, 
                hop_length=self.hop_length
            )
            
            # Calculate delta and delta-delta features for better representation
            delta_mfccs = librosa.feature.delta(mfccs)
            delta2_mfccs = librosa.feature.delta(mfccs, order=2)
            
            # Combine features
            features = np.concatenate([mfccs, delta_mfccs, delta2_mfccs], axis=0)
            
            return features.T  # Return as (time, features)
            
        except Exception as e:
            _logger.error(f"Error extracting MFCC features: {e}")
            return None
    
    def detect_voice_activity(self, audio_path, frame_length=2048, hop_length=512):
        """Detect voice activity in audio using energy-based VAD"""
        try:
            y, sr = librosa.load(audio_path, sr=self.sample_rate)
            
            # Calculate short-time energy
            energy = np.array([
                sum(abs(y[i:i+frame_length]**2)) 
                for i in range(0, len(y), hop_length)
            ])
            
            # Normalize energy
            energy = energy / np.max(energy)
            
            # Simple threshold-based VAD
            threshold = np.mean(energy) + 0.5 * np.std(energy)
            voice_activity = energy > threshold
            
            # Convert to time segments
            time_per_frame = hop_length / sr
            voice_segments = []
            
            in_speech = False
            start_time = 0
            
            for i, is_voice in enumerate(voice_activity):
                current_time = i * time_per_frame
                
                if is_voice and not in_speech:
                    # Start of speech
                    start_time = current_time
                    in_speech = True
                elif not is_voice and in_speech:
                    # End of speech
                    voice_segments.append((start_time, current_time))
                    in_speech = False
            
            # Handle case where audio ends during speech
            if in_speech:
                voice_segments.append((start_time, len(y) / sr))
            
            return voice_segments
            
        except Exception as e:
            _logger.error(f"Error in voice activity detection: {e}")
            return []
    
    def estimate_fundamental_frequency(self, audio_path, segment_start=None, segment_end=None):
        """Estimate F0 (pitch) using YIN algorithm"""
        try:
            y, sr = librosa.load(audio_path, sr=self.sample_rate)
            
            # Extract segment if specified
            if segment_start is not None and segment_end is not None:
                start_sample = int(segment_start * sr)
                end_sample = int(segment_end * sr)
                y = y[start_sample:end_sample]
            
            # Use YIN algorithm for F0 estimation
            f0 = librosa.yin(
                y, 
                fmin=50,   # Minimum frequency (Hz)
                fmax=400,  # Maximum frequency (Hz) 
                sr=sr
            )
            
            # Remove unvoiced frames (where F0 couldn't be estimated reliably)
            voiced_f0 = f0[f0 > 0]
            
            if len(voiced_f0) > 0:
                return {
                    'mean_f0': np.mean(voiced_f0),
                    'std_f0': np.std(voiced_f0),
                    'median_f0': np.median(voiced_f0),
                    'f0_trajectory': f0
                }
            else:
                return None
                
        except Exception as e:
            _logger.error(f"Error estimating F0: {e}")
            return None
    
    def calculate_speaking_rate(self, segments, audio_duration):
        """Calculate words per minute and syllables per second"""
        try:
            # Ensure audio_duration is numeric
            if isinstance(audio_duration, str):
                audio_duration = float(audio_duration)
            elif not isinstance(audio_duration, (int, float)):
                _logger.error(f"Invalid audio_duration type: {type(audio_duration)}")
                return None
            
            total_words = 0
            total_syllables = 0
            
            for segment in segments:
                text = segment.get('text', '')
                if text:
                    # Simple word count
                    words = len(text.split())
                    total_words += words
                    
                    # Rough syllable estimation (vowel counting)
                    vowels = 'aeiouáàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ'
                    syllables = sum(1 for char in text.lower() if char in vowels)
                    total_syllables += max(syllables, words)  # At least one syllable per word
            
            if audio_duration > 0:
                wpm = (total_words / audio_duration) * 60
                sps = total_syllables / audio_duration
                
                return {
                    'words_per_minute': wpm,
                    'syllables_per_second': sps,
                    'total_words': total_words,
                    'total_syllables': total_syllables,
                    'duration': audio_duration
                }
            
            return None
            
        except Exception as e:
            _logger.error(f"Error calculating speaking rate: {e}")
            return None
    
    def dynamic_time_warping(self, features1, features2):
        """Perform DTW alignment between two feature sequences"""
        try:
            # Calculate distance matrix
            distance_matrix = cdist(features1, features2, metric='euclidean')
            
            # Initialize DTW matrix
            n, m = distance_matrix.shape
            dtw_matrix = np.full((n + 1, m + 1), np.inf)
            dtw_matrix[0, 0] = 0
            
            # Fill DTW matrix
            for i in range(1, n + 1):
                for j in range(1, m + 1):
                    cost = distance_matrix[i-1, j-1]
                    dtw_matrix[i, j] = cost + min(
                        dtw_matrix[i-1, j],      # insertion
                        dtw_matrix[i, j-1],      # deletion
                        dtw_matrix[i-1, j-1]     # match
                    )
            
            # Backtrack to find optimal path
            path = []
            i, j = n, m
            while i > 0 and j > 0:
                path.append((i-1, j-1))
                
                # Choose the minimum of three predecessors
                options = [
                    (dtw_matrix[i-1, j-1], i-1, j-1),    # diagonal
                    (dtw_matrix[i-1, j], i-1, j),        # vertical
                    (dtw_matrix[i, j-1], i, j-1)         # horizontal
                ]
                _, i, j = min(options)
            
            path.reverse()
            
            return {
                'path': path,
                'distance': dtw_matrix[n, m],
                'normalized_distance': dtw_matrix[n, m] / (n + m)
            }
            
        except Exception as e:
            _logger.error(f"Error in DTW alignment: {e}")
            return None
    
    def align_audio_segments(self, original_audio_path, dubbed_audio_path, segments):
        """Align dubbed audio segments with original using DTW"""
        try:
            aligned_segments = []
            
            # Extract features from both audio files
            original_features = self.extract_mfcc_features(original_audio_path)
            dubbed_features = self.extract_mfcc_features(dubbed_audio_path)
            
            if original_features is None or dubbed_features is None:
                _logger.error("Could not extract features for alignment")
                return segments
            
            # Perform DTW alignment
            alignment_result = self.dynamic_time_warping(original_features, dubbed_features)
            
            if alignment_result is None:
                _logger.error("DTW alignment failed")
                return segments
            
            # Map original time points to dubbed time points
            path = alignment_result['path']
            time_mapping = {}
            
            for orig_idx, dubbed_idx in path:
                orig_time = orig_idx * self.hop_length / self.sample_rate
                dubbed_time = dubbed_idx * self.hop_length / self.sample_rate
                time_mapping[orig_time] = dubbed_time
            
            # Adjust segment timing based on alignment
            for segment in segments:
                original_start = segment.get('start', 0)
                original_end = segment.get('end', original_start + 5)
                
                # Find closest mapped times
                closest_start_time = min(time_mapping.keys(), 
                                       key=lambda x: abs(x - original_start))
                closest_end_time = min(time_mapping.keys(), 
                                     key=lambda x: abs(x - original_end))
                
                aligned_start = time_mapping[closest_start_time]
                aligned_end = time_mapping[closest_end_time]
                
                aligned_segment = segment.copy()
                aligned_segment['start'] = aligned_start
                aligned_segment['end'] = aligned_end
                aligned_segment['original_start'] = original_start
                aligned_segment['original_end'] = original_end
                
                aligned_segments.append(aligned_segment)
            
            _logger.info(f"Aligned {len(aligned_segments)} segments using DTW")
            return aligned_segments
            
        except Exception as e:
            _logger.error(f"Error in audio segment alignment: {e}")
            return segments
    
    def apply_time_stretching(self, audio_path, output_path, stretch_factor):
        """Apply time stretching to audio without changing pitch"""
        try:
            y, sr = librosa.load(audio_path, sr=self.sample_rate)
            
            # Apply phase vocoder-based time stretching
            y_stretched = librosa.effects.time_stretch(y, rate=stretch_factor)
            
            # Save stretched audio
            librosa.output.write_wav(output_path, y_stretched, sr)
            
            _logger.info(f"Applied time stretching factor {stretch_factor:.2f}: {output_path}")
            return output_path
            
        except Exception as e:
            _logger.error(f"Error in time stretching: {e}")
            return None
    
    def optimize_speech_timing(self, original_segments, dubbed_audio_path, output_audio_path):
        """Optimize dubbed audio timing to match original speech rhythm"""
        try:
            # Calculate original speech statistics
            original_durations = []
            original_gaps = []
            
            for i, segment in enumerate(original_segments):
                duration = segment.get('end', 0) - segment.get('start', 0)
                original_durations.append(duration)
                
                if i < len(original_segments) - 1:
                    gap = original_segments[i+1].get('start', 0) - segment.get('end', 0)
                    original_gaps.append(gap)
            
            # Calculate statistics
            avg_duration = np.mean(original_durations) if original_durations else 3.0
            avg_gap = np.mean(original_gaps) if original_gaps else 0.5
            
            # Load dubbed audio
            y, sr = librosa.load(dubbed_audio_path, sr=self.sample_rate)
            dubbed_duration = len(y) / sr
            original_total_duration = sum(original_durations)
            
            # Calculate optimal stretch factor
            if original_total_duration > 0:
                stretch_factor = original_total_duration / dubbed_duration
                # Limit stretch factor to reasonable range
                stretch_factor = np.clip(stretch_factor, 0.5, 2.0)
            else:
                stretch_factor = 1.0
            
            # Apply time stretching if needed
            if abs(stretch_factor - 1.0) > 0.1:  # Only stretch if significant difference
                _logger.info(f"Applying time stretch factor: {stretch_factor:.2f}")
                return self.apply_time_stretching(dubbed_audio_path, output_audio_path, stretch_factor)
            else:
                # No stretching needed, just copy file
                import shutil
                shutil.copy2(dubbed_audio_path, output_audio_path)
                return output_audio_path
                
        except Exception as e:
            _logger.error(f"Error optimizing speech timing: {e}")
            return dubbed_audio_path
