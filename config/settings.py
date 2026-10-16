"""Django settings for the meeting recorder app (dev/staging defaults).

SQLite by default; Postgres via DATABASE_URL env. Dev server binds Tailscale IP only.
"""
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECRET_KEY comes from the environment (production: EnvironmentFile with mode 0600).
# The fallback is a deliberately non-secret development placeholder.
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-set-SECRET_KEY-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = ["meeting.acts19.us", "pop-os.tail5f2bd.ts.net", "100.113.186.11", "127.0.0.1", "localhost", "testserver"]  # dev: server binds the Tailscale IP only
CSRF_TRUSTED_ORIGINS = ["https://meeting.acts19.us", "https://pop-os.tail5f2bd.ts.net:8444", "http://100.113.186.11:18780"]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'meetings',
]

MIDDLEWARE = [
    "meetings.middleware.NoIndexMiddleware",
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

if os.environ.get("DATABASE_URL"):
    m = re.match(
        r"postgres(?:ql)?://(?P<user>[^:]+):(?P<password>[^@]*)@(?P<host>[^:]+):(?P<port>\d+)/(?P<name>.+)",
        os.environ["DATABASE_URL"])
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": m["name"], "USER": m["user"], "PASSWORD": m["password"],
        "HOST": m["host"], "PORT": m["port"],
    }}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Chicago'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"

# --- app services ---
PARAKEET_URL = os.environ.get("PARAKEET_URL", "http://127.0.0.1:18771/api/transcribe")
LLM_URL = os.environ.get("LLM_URL", "http://100.113.186.11:8096/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3.8-flash-next-iq3s")
LLM_FALLBACK_URL = os.environ.get("LLM_FALLBACK_URL", "http://127.0.0.1:8080/v1")
LLM_FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "qwen3.8-27b-awq")

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6390/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6390/1")
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"

GOG_BIN = os.environ.get("GOG_BIN", str(Path.home() / ".local/bin/gog-ken"))

DATA_UPLOAD_MAX_MEMORY_SIZE = 512 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
