"""Calendars Core application"""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configuration class for the calendars core app."""

    name = "core"
    app_label = "core"
    verbose_name = "calendars core application"

    def ready(self):
        """
        Import signals when the app is ready.
        """
        # pylint: disable=import-outside-toplevel, unused-import
        from . import signals  # noqa: PLC0415
