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
    "fees",
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
    "formatters": {"default": {"format": "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    # The huey consumer adds its own handler: without this, every line would be logged twice.
    "loggers": {"huey": {"propagate": False}},
}

# Folder mounted in Docker where load_merchants and load_orders look for the files.
IMPORT_DIR = Path(os.environ.get("IMPORT_DIR", BASE_DIR / "import_data"))

# Configurable business rules.
PACKAGE_MAX_ORDERS = int(os.environ.get("PACKAGE_MAX_ORDERS", "5000"))
# Automatic retries of a package: one per check that is not the last one.
PACKAGE_MAX_RETRIES = int(os.environ.get("PACKAGE_MAX_RETRIES", "2"))
# Limit per query while processing a package: cuts a hung query (measured: the slowest, ~0.2 s).
PACKAGE_STATEMENT_TIMEOUT_SECONDS = int(os.environ.get("PACKAGE_STATEMENT_TIMEOUT_SECONDS", "5"))
# A package in PROCESSING without a lock and older than these minutes is considered stuck (measured: ~0.3 s the slowest).
PACKAGE_STUCK_AFTER_MINUTES = int(os.environ.get("PACKAGE_STUCK_AFTER_MINUTES", "5"))
# Hours (UTC) of the check of the day's packages. The last one only alerts and leaves 2 h before 08:00.
CHECK_PACKAGES_HOURS = [2, 4, 6]
