"""
Production settings for the on-prem Linux server.

Everything is inherited from settings.py, so apps, middleware, REST framework, time zone etc. can
never drift apart again. This file only overrides what must differ in production, and every
secret or server-specific value comes from environment variables. See deploy/README.md and
deploy/clinic365.env.example.

Use it with:  DJANGO_SETTINGS_MODULE=clinic365.settings_production
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F401,F403  (inherit the full app configuration)
from .settings import BASE_DIR


# --------------------------------------------------------------------------- helpers
def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and (value is None or str(value).strip() == ''):
        raise ImproperlyConfigured(f'Environment variable {name} is required in production (see deploy/clinic365.env.example).')
    return value


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or value.strip() == '':
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default='', required=False):
    raw = env(name, default, required=required) or ''
    return [item.strip() for item in raw.split(',') if item.strip()]


# --------------------------------------------------------------------------- core
DEBUG = env_bool('DJANGO_DEBUG', False)

SECRET_KEY = env('DJANGO_SECRET_KEY', required=True)
if SECRET_KEY.startswith('django-insecure') or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        'DJANGO_SECRET_KEY must be a long random value (50+ characters), not the development key. Generate one with:\n'
        '  python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"'
    )

# Host names / IPs the server answers to, e.g. "emr.isaluhospitals.local,192.168.2.14"
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', required=True)
# Full origins (scheme + host + port) the browser uses, e.g. "http://192.168.2.14,http://emr.isaluhospitals.local"
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', required=True)

# The React app is served from the same origin as /api (nginx), so cross-origin access is off by
# default. Only list extra origins if another site genuinely needs to call the API.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env_list('DJANGO_CORS_ALLOWED_ORIGINS')
CORS_ALLOW_CREDENTIALS = True

# --------------------------------------------------------------------------- database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DB_NAME', 'clinic365'),
        'USER': env('DB_USER', 'clinic365'),
        'PASSWORD': env('DB_PASSWORD', required=True),
        'HOST': env('DB_HOST', '127.0.0.1'),
        'PORT': env('DB_PORT', '5432'),
        'CONN_MAX_AGE': int(env('DB_CONN_MAX_AGE', '60')),   # reuse connections between requests
        'CONN_HEALTH_CHECKS': True,                          # ...but drop dead ones (DB restart)
    }
}

# --------------------------------------------------------------------------- files
STATIC_ROOT = env('DJANGO_STATIC_ROOT', '/opt/clinic365/staticfiles')
MEDIA_ROOT = env('DJANGO_MEDIA_ROOT', '/opt/clinic365/media')
# Django checks the login for /media/..., then nginx sends the file from this internal location
# (deploy/nginx/clinic365.conf). Set DJANGO_MEDIA_ACCEL=0 only if Django runs without nginx.
MEDIA_ACCEL_REDIRECT = env_bool('DJANGO_MEDIA_ACCEL', True)
MEDIA_ACCEL_PREFIX = '/protected-media/'
HAYSTACK_CONNECTIONS = {
    'default': {
        'ENGINE': 'haystack.backends.whoosh_backend.WhooshEngine',
        'PATH': env('DJANGO_SEARCH_INDEX', str(BASE_DIR / 'whoosh_index')),
    },
}
# Uploads (patient documents, Excel imports): keep in step with nginx client_max_body_size.
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# --------------------------------------------------------------------------- security
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# Turn on once the site is served over HTTPS (nginx terminates TLS and sets X-Forwarded-Proto).
# On a plain-HTTP hospital LAN leave it off, or logins will stop working (cookies need HTTPS).
USE_HTTPS = env_bool('DJANGO_HTTPS', False)
if USE_HTTPS:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env('DJANGO_HSTS_SECONDS', '3600'))   # raise to 31536000 once HTTPS is stable
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SSL_REDIRECT', False)    # usually nginx does the redirect

# --------------------------------------------------------------------------- email
# Used by the nightly day-book report (manage.py send_daily_day_book). Without EMAIL_HOST,
# mail is written to the log instead of being sent, so nothing fails silently.
EMAIL_HOST = env('EMAIL_HOST', '')
if EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_PORT = int(env('EMAIL_PORT', '587'))
    EMAIL_HOST_USER = env('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', '')
    EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
    EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', False)
    EMAIL_TIMEOUT = 30
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', 'Clinic365 EMR <no-reply@localhost>')
SERVER_EMAIL = DEFAULT_FROM_EMAIL
DAY_BOOK_EMAIL = env('DAY_BOOK_EMAIL', '')   # who receives the nightly day book (comma-free, one address)

# --------------------------------------------------------------------------- logging
LOG_DIR = env('DJANGO_LOG_DIR', '/var/log/clinic365')
LOG_LEVEL = env('DJANGO_LOG_LEVEL', 'INFO')
_log_handlers = {
    'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'},
}
if os.path.isdir(LOG_DIR) and os.access(LOG_DIR, os.W_OK):
    _log_handlers['file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': os.path.join(LOG_DIR, 'django.log'),
        'maxBytes': 10 * 1024 * 1024,
        'backupCount': 10,
        'formatter': 'plain',
    }
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'plain': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': _log_handlers,
    'root': {'handlers': list(_log_handlers), 'level': LOG_LEVEL},
    'loggers': {
        'django': {'handlers': list(_log_handlers), 'level': LOG_LEVEL, 'propagate': False},
        # 4xx noise (expired tokens, refused requests) stays at WARNING; real errors are ERROR.
        'django.request': {'handlers': list(_log_handlers), 'level': 'WARNING', 'propagate': False},
    },
}
