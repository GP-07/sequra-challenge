import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "huey.contrib.djhuey",
    "core",
    "merchants",
    "orders",
    "disbursement_packages",
    "disbursements",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "disbursements"),
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

HUEY = {
    "huey_class": "huey.RedisHuey",
    "name": "disbursements",
    "immediate": env_bool("HUEY_IMMEDIATE", False),
    "connection": {
        "host": os.environ.get("REDIS_HOST", "localhost"),
        "port": int(os.environ.get("REDIS_PORT", "6379")),
    },
    "consumer": {"workers": int(os.environ.get("HUEY_WORKERS", "4")), "worker_type": "thread"},
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# Carpeta montada en Docker donde load_merchants y load_orders buscan los archivos.
IMPORT_DIR = Path(os.environ.get("IMPORT_DIR", BASE_DIR / "import_data"))

# Reglas de negocio configurables.
PACKAGE_MAX_ORDERS = int(os.environ.get("PACKAGE_MAX_ORDERS", "5000"))
PACKAGE_MAX_RETRIES = int(os.environ.get("PACKAGE_MAX_RETRIES", "1"))
PACKAGE_FAILURE_THRESHOLD_PERCENT = int(os.environ.get("PACKAGE_FAILURE_THRESHOLD_PERCENT", "80"))
CHECK_PACKAGES_HOURS = [2, 4, 6]
