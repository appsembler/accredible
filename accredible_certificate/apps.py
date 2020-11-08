"""
Provides application configuration for Accredible.
As well as default values for running Accredible along with functions to
add entries to the Django conf settings needed to run Accredible.
"""

from django.apps import AppConfig
from openedx.core.djangoapps.plugins.constants import (
    ProjectType, SettingsType, PluginURLs, PluginSettings
)


class AccredibleConfig(AppConfig):
    """
    Provides application configuration for Accredible.
    """

    name = 'accredible_certificate'
    verbose_name = 'accredible_certificate'

    plugin_app = {
        PluginURLs.CONFIG: {
            ProjectType.LMS: {
                PluginURLs.NAMESPACE: u'accredible_certificate',
                PluginURLs.REGEX: u'^accredible/',
                PluginURLs.RELATIVE_PATH: u'urls',
            }
        },
        PluginSettings.CONFIG: {
            ProjectType.LMS: {
                SettingsType.COMMON: {
                    PluginSettings.RELATIVE_PATH: u'settings.common'
                },
            }
        }
    }
