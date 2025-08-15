# Installation Notes for Enhanced Video Translator Module

## New Dependencies Added

Install these Python packages:

```bash
pip install openai
pip install google-cloud-translate  
pip install google-cloud-texttospeech
```

## System Dependencies

Ensure ffmpeg is installed:
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# CentOS/RHEL
sudo yum install ffmpeg
```

## Configuration Required

1. **OpenAI API Key**: Set system parameter `leonix_video_translator.openai_api_key`
2. **Google Cloud Credentials**: Set system parameter `leonix_video_translator.gcloud_credentials_json` with your service account JSON

## New Features Added

1. **Video Processing Utils**: Methods to get video info, file paths, and extract audio
2. **OpenAI Service**: Transcription using Whisper API  
3. **Google Cloud Service**: Translation and text-to-speech
4. **Portal UI**: Buttons for transcription, translation, and dubbing workflows
5. **Background Processing**: Async processing with status tracking using threading
6. **Complete Workflow**: One-click transcribe + translate + dub

## Usage Flow

1. Download video (existing functionality)
2. Select target language and voice
3. Click "Transcribe & Dub" or individual step buttons
4. Monitor progress via status badges
5. Download dubbed video when complete

## Note on Background Processing

The module uses Python threading for background processing instead of queue_job to avoid additional dependencies. Processing happens asynchronously without blocking the UI.

The module now provides a complete video dubbing solution integrated with the existing video download functionality.
