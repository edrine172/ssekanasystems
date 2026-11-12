from pathlib import Path
import os
from datetime import timedelta
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
DEBUG = os.environ.get('DEBUG', 'false' if os.environ.get('RENDER') else 'true').lower() in {'1', 'true', 'yes'}
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('SECRET_KEY must be set when DEBUG is disabled.')
    SECRET_KEY = 'django-insecure-local-development-key-change-before-deployment'
def env_list(name, default):
    value = os.environ.get(name)
    if value is None:
        return [item.strip() for item in default.split(',') if item.strip()]
    return [item.strip() for item in value.split(',') if item.strip()]


ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'ssekanasystems.onrender.com,127.0.0.1,localhost')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'inventory',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',

]

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

POSTGRES_DB = os.environ.get('POSTGRES_DB')
DATABASE_URL = os.environ.get('DATABASE_URL')
DATABASE_ENGINE = os.environ.get('DATABASE_ENGINE', '').lower()
if not DATABASE_ENGINE:
    DATABASE_ENGINE = 'postgresql' if POSTGRES_DB or DATABASE_URL else 'sqlite'

if DATABASE_ENGINE == 'postgresql':
    if DATABASE_URL:
        DATABASES = {
            'default': dj_database_url.config(default=DATABASE_URL, conn_max_age=600)
        }
    elif not POSTGRES_DB:
        raise ImproperlyConfigured('POSTGRES_DB is required when DATABASE_ENGINE is postgresql.')
    else:
        POSTGRES_USER = os.environ.get('POSTGRES_USER')
        POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD')
        if not POSTGRES_USER or not POSTGRES_PASSWORD:
            raise ImproperlyConfigured('POSTGRES_USER and POSTGRES_PASSWORD are required when DATABASE_ENGINE is postgresql.')
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': POSTGRES_DB,
                'USER': POSTGRES_USER,
                'PASSWORD': POSTGRES_PASSWORD,
                'HOST': os.environ.get('POSTGRES_HOST', '127.0.0.1'),
                'PORT': os.environ.get('POSTGRES_PORT', '5432'),
                'CONN_MAX_AGE': 60,
            },
        }
elif DATABASE_ENGINE == 'sqlite':
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
else:
    raise ImproperlyConfigured('DATABASE_ENGINE must be either postgresql or sqlite.')

CACHE_URL = os.environ.get('CACHE_URL')
if not DEBUG and not CACHE_URL:
    raise ImproperlyConfigured('CACHE_URL must be set to the shared Redis/Valkey service when DEBUG is disabled.')
if CACHE_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': CACHE_URL,
            'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
            'KEY_PREFIX': 'stockpulse',
        },
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'stockpulse-local',
        },
    }

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

default_cors_origins = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'https://ssekanasystems.vercel.app',
]
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS', ','.join(default_cors_origins))
CORS_ALLOWED_ORIGIN_REGEXES = env_list('CORS_ALLOWED_ORIGIN_REGEXES', r'^https://.*\.vercel\.app$')
CORS_EXPOSE_HEADERS = ['Content-Disposition', 'X-Restored-Record-Count']
CORS_ALLOW_CREDENTIALS = True
CSRF_COOKIE_SAMESITE = 'Lax' if DEBUG else 'None'
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = 'Lax' if DEBUG else 'None'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS', ','.join([
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'https://*.vercel.app',
    'https://ssekanasystems.vercel.app',
]))
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['inventory.permissions.RoleModelPermissions'],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'inventory.throttling.AtomicAnonRateThrottle',
        'inventory.throttling.AtomicUserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/minute',
        'user': '600/minute',
        'auth_login': '20/minute',
    },
    'NUM_PROXIES': 1,
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'] if not DEBUG else [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=10),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'AUTH_HEADER_TYPES': ('Bearer',),
}
