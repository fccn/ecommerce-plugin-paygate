"""
Paygate payment processor Django application initialization.
"""
from django.apps import AppConfig


class PayGateConfig(AppConfig):
    """
    Configuration for the PayGate payment processor Django application.
    """
    name = 'paygate'
    plugin_app = {
        'url_config': {
            'ecommerce': {
                'namespace': 'paygate',
            }
        },
    }
