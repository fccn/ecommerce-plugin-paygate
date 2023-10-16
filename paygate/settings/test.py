"""
Settings for paygate
"""
from ecommerce.settings.test import *

# from __future__ import absolute_import, unicode_literals

# from .common import *  # pylint: disable=wildcard-import, unused-wildcard-import


# class SettingsClass:
#     """ dummy settings class """


# DEBUG = True
# SETTINGS = SettingsClass()
# # plugin_settings(SETTINGS)
# vars().update(SETTINGS.__dict__)


# ROOT_URLCONF = "paygate.urls"
# ALLOWED_HOSTS = ["*"]

# # This key needs to be defined so that the check_apps_ready passes and the
# # AppRegistry is loaded
# DATABASES = {
#     "default": {
#         "ENGINE": "django.db.backends.sqlite3",
#         "NAME": "db.sqlite3",
#     }
# }

# # This is to avoid "initialized translation infrastructure before the apps registry is ready" issue in tests.
# USE_I18N = False
