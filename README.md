# Leonix Video Translator Module

## Prerequisites

### 1. Install Required Dependencies
```bash
# Install required packages
pip install yt-dlp psutil
```

### 2. System Requirements
- Python 3.8+
- Odoo 18.0
- Sufficient storage space for video files
- Internet connection for downloading videos

## Installation Steps

1. Copy the module to your Odoo addons directory:
   ```bash
   cp -r leonix_video_translator /path/to/odoo/addons/
   ```

2. Update the module list in Odoo
3. Install the "Leonix Video Translator" module

## Features

### Optimized Video Storage
- Automatic file deduplication based on URL hash
- Structured storage organization by platform
- Configurable quality settings to balance file size vs quality

### Real-time Progress Tracking
- Live download progress with speed and ETA
- JavaScript-based progress updates without page refresh
- Visual progress bars and notifications

### Video Playback
- Built-in HTML5 video player
- Direct download links for video files
- Video metadata display (duration, file size, format)

### Portal Integration
- User-friendly portal interface
- Automatic page refresh on completion
- Error handling and retry functionality

## Usage

1. **Create Video Translation Request**
   - Go to Portal → Video Translations
   - Click "Create New"
   - Enter video name, URL (YouTube/TikTok), and description

2. **Download Video**
   - Click "Start Download" button
   - Monitor real-time progress
   - Page automatically refreshes when complete

3. **Watch Video**
   - Video player appears when download is complete
   - Use download link for offline viewing

## Configuration

### Video Quality Settings
The system automatically optimizes video quality based on:
- Video duration (longer videos use lower quality)
- File size limits (prevents extremely large files)
- Platform-specific settings

### Storage Management
- Videos are organized by platform (YouTube, TikTok, etc.)
- Duplicate videos are automatically detected and reused
- Built-in cleanup utilities for old files

## Troubleshooting

### Common Issues

1. **yt-dlp not found**
   - Install yt-dlp: `pip install yt-dlp`
   - Ensure it's in the system PATH

2. **Download fails**
   - Check video URL is valid
   - Ensure internet connectivity
   - Some videos may be region-restricted

3. **Progress not updating**
   - Check browser console for JavaScript errors
   - Ensure JSON-RPC endpoint is accessible

### Log Files
Check Odoo logs for detailed error information:
```bash
grep -i "video" /var/log/odoo/odoo.log
```

## API Endpoints

### Portal Endpoints
- `/my/video-translations` - List videos
- `/my/video-translations/<id>` - Video details
- `/my/video-translations/<id>/download` - Start download
- `/my/video-translations/<id>/progress` - Get progress (AJAX)

### File Access
- `/web/content/<attachment_id>` - Stream video
- `/web/content/<attachment_id>?download=true` - Download video

## Security Considerations

- Only authenticated portal users can access videos
- Video files are stored as Odoo attachments with proper access controls
- URL validation prevents malicious inputs
- CSRF protection on all forms

## Performance Tips

1. **Regular Cleanup**
   - Implement scheduled cleanup of old videos
   - Monitor storage usage

2. **Quality Optimization**
   - Use lower quality for longer videos
   - Set reasonable file size limits

3. **Cron Job Frequency**
   - Adjust download processing frequency based on usage
   - Consider peak usage times
