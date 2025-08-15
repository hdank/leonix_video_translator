from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    # OpenAI Configuration
    openai_api_key = fields.Char(
        string='OpenAI API Key',
        config_parameter='leonix_video_translator.openai_api_key',
        help='API Key for OpenAI Whisper transcription service'
    )
    
    # Google Cloud Configuration
    gcloud_credentials_json = fields.Char(
        string='Google Cloud Credentials JSON',
        config_parameter='leonix_video_translator.gcloud_credentials_json',
        help='JSON credentials file content for Google Cloud Translation and TTS services',
        size=10000  # Large size to accommodate JSON content
    )
    
    gcloud_project_id = fields.Char(
        string='Google Cloud Project ID',
        config_parameter='leonix_video_translator.gcloud_project_id',
        help='Google Cloud Project ID'
    )
