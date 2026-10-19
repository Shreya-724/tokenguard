from django.apps import AppConfig


class TokenGuardConfig(AppConfig):
    """Add "tokenguard.django" to INSTALLED_APPS to get `manage.py tokenguard_feed`."""

    name = "tokenguard.django"
    label = "tokenguard"
    verbose_name = "tokenguard"
