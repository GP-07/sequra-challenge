from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Lo que comparten las apps de dominio. No tiene modelos."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
