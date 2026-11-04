from django.apps import AppConfig


class CoreConfig(AppConfig):
    """What the domain apps share. It has no models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
