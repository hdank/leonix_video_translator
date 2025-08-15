{
    'name': 'Leonix Video Translator',
    'version': '18.0',
    'category': 'Website/Website',
    'summary': 'Video Translation Management',
    'description': """
        Module for managing video translation services through the portal.
    """,
    'depends': ['base', 'portal', 'website', 'mail'],
    'data': [
        'views/assets.xml',
        'security/ir.model.access.csv',
        'data/config_parameters.xml',
        'views/video_views.xml',
        'views/video_download_queue_views.xml',
        'views/config_settings_views.xml',
        'views/portal_templates.xml',
        'views/portal_create_video.xml',
        'views/menu_views.xml',
        'data/cron.xml',
    ],
    #'demo': [
    #    'data/demo_data.xml',
    #],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
