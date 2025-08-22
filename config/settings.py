import os
from pathlib import Path
import environ

# 환경 변수 설정
env = environ.Env()
environ.Env.read_env()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = env('DJANGO_SECRET_KEY', default='django-insecure-secret')
DEBUG = env.bool('DJANGO_DEBUG', default=True)
ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'stats',
    'django_apscheduler',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('MYSQL_DB'),
        'USER': env('MYSQL_USER'),
        'PASSWORD': env('MYSQL_PASSWORD'),
        'HOST': env('MYSQL_HOST'),
        'PORT': env('MYSQL_PORT'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    },
    'newspic': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'newspic',
        'USER': env('MYSQL_USER'),
        'PASSWORD': env('MYSQL_PASSWORD'),
        'HOST': env('MYSQL_HOST_NEWSPIC'),
        'PORT': env('MYSQL_PORT'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_L10N = True
USE_TZ = True

STATIC_URL = 'static/'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

FIELD_ENCRYPTION_KEY = 'KBjpQhY7oW/NX8eeubTH45vcA3rVqkTdzKP1AAcFXCE='

# 캐시 설정 - 파일 기반 캐시 (Worker 간 공유)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': '/tmp/django_cache',
        'TIMEOUT': 86400,  # 24시간 (초 단위)
        'OPTIONS': {
            'MAX_ENTRIES': 1000,  # 최대 캐시 항목 수
        }
    }
}

# 로깅 설정
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'adsense_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/adsense.log',
            'formatter': 'verbose',
        },
        'admanager_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/admanager.log',
            'formatter': 'verbose',
        },
        'coupang_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/coupang.log',
            'formatter': 'verbose',
        },
        'cozymamang_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/cozymamang.log',
            'formatter': 'verbose',
        },
        'mediamixer_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/mediamixer.log',
            'formatter': 'verbose',
        },
        'teads_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/teads.log',
            'formatter': 'verbose',
        },
        'aceplanet_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/aceplanet.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'stats.services.adsense_service': {
            'handlers': ['adsense_file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'stats.services.admanager_service': {
            'handlers': ['admanager_file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'stats.services.coupang_service': {
            'handlers': ['coupang_file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'stats.services.cozymamang_service': {
            'handlers': ['cozymamang_file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'stats.services.mediamixer_service': {
            'handlers': ['mediamixer_file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'stats.services.teads_service': {
            'handlers': ['teads_file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'stats.services.aceplanet_service': {
            'handlers': ['aceplanet_file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'stats.views.sales': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'stats.views.purchase': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
