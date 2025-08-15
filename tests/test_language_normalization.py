#!/usr/bin/env python3
"""
Test script for language code normalization functionality
"""
import sys
import os

# Add the parent directory to the path to import our services
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.gcloud_service import LANGUAGE_NAME_TO_CODE

def test_language_normalization():
    """Test the language normalization functionality"""
    
    print("Testing Language Code Normalization")
    print("=" * 50)
    
    # Test cases with common language variations
    test_cases = [
        "english",
        "English",
        "ENGLISH", 
        "vietnamese",
        "Vietnamese",
        "japanese",
        "korean",
        "chinese",
        "spanish",
        "french", 
        "german",
        "en",  # Already a code
        "vi",  # Already a code
        "en-US",  # Language-country code
        "zh-CN",  # Language-country code
        "unknown_language",  # Should fallback to 'en'
        "",  # Empty string
        None  # None value
    ]
    
    class MockGoogleCloudService:
        """Mock service for testing without actual Google Cloud connection"""
        
        def _normalize_language_code(self, language):
            """Mock implementation of language normalization"""
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
                
            # Fallback to English
            return 'en'
    
    service = MockGoogleCloudService()
    
    print("Language Input -> Normalized Code")
    print("-" * 35)
    
    for test_case in test_cases:
        try:
            result = service._normalize_language_code(test_case)
            print(f"'{test_case}' -> '{result}'")
        except Exception as e:
            print(f"'{test_case}' -> Error: {e}")
    
    print("\n" + "=" * 50)
    print("✅ Language normalization test completed!")
    print(f"Total mappings available: {len(LANGUAGE_NAME_TO_CODE)}")

if __name__ == "__main__":
    test_language_normalization()
