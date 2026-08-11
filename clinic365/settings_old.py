
# from pathlib import Path
# import os

# # Build paths inside the project like this: BASE_DIR / 'subdir'.
# BASE_DIR = Path(__file__).resolve().parent.parent

# # Quick-start development settings - unsuitable for production
# # See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# # SECURITY WARNING: keep the secret key used in production secret!
# SECRET_KEY = 'django-insecure-)qbr6%lw!cin=g(^p-v1la0y+^3c=*2^k7_m228=vzyj3-y@@7'

# # SECURITY WARNING: don't run with debug turned on in production!
# DEBUG = True

# ALLOWED_HOSTS = ['localhost', '127.0.0.1']


# # Application definition

# INSTALLED_APPS = [
#     'django.contrib.admin',
#     'django.contrib.auth',
#     'django.contrib.contenttypes',
#     'django.contrib.sessions',
#     'django.contrib.messages',
#     'django.contrib.staticfiles',
#     'users.apps.UsersConfig',
#     'patients.apps.PatientsConfig',
#     'queue_operations.apps.QueueOperationsConfig',
#     'inventory.apps.InventoryConfig',
#     'radio_lab.apps.RadioLabConfig',
#     'IPD_pharm.apps.IpdPharmConfig',
#     'IPD_pharm2.apps.IpdPharm2Config',
#     'IPD_pharm3.apps.IpdPharm3Config',
#     'OPD_pharm.apps.OpdPharmConfig',
#     'OPD_pharm2.apps.OpdPharm2Config',
#     'IPD.apps.IpdConfig',
#     'ANC.apps.AncConfig',
#     'Billings.apps.BillingsConfig',
#     # ck editor
#     # 'ckeditor',
#     # 'ckeditor_uploader',
# ]

# AUTH_USER_MODEL = 'users.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'myAdmins.middleware.OnlineUsersMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    ]

    AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',  
    ]

    ROOT_URLCONF = 'clinic365.urls'

    TEMPLATES = [
    {
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [
    BASE_DIR / 'templates'
    ],
    'APP_DIRS': True,
    'OPTIONS': {
    'context_processors': [
    'django.template.context_processors.debug',
    'django.template.context_processors.request',
    'django.contrib.auth.context_processors.auth',
    'django.contrib.messages.context_processors.messages',
    ],
    },
    },
    ]

    WSGI_APPLICATION = 'clinic365.wsgi.application'


    DATABASES = {
    'default': {
    'ENGINE': 'django.db.backends.mysql',
    'NAME': 'clinic365',
    'USER': 'django_user',
    'PASSWORD': 'javalinas100',
    'HOST': '127.0.0.1',
    'PORT': '3307',
    'CONN_MAX_AGE': 3600, 
    'OPTIONS': {
    'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
    'charset': 'utf8mb4',
    'connect_timeout': 10,
    'read_timeout': 30,
    'write_timeout': 30,
    'autocommit': True,
    },
    }
    }


    AUTH_PASSWORD_VALIDATORS = [
    {
    'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
    'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
    'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
    'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
    ]


    LANGUAGE_CODE = 'en-us'

    TIME_ZONE = "Africa/Lagos"

    USE_I18N = True

    USE_TZ = True


    Static files (CSS, JavaScript, Images)
    https://docs.djangoproject.com/en/5.1/howto/static-files/

    STATIC_URL = 'static/'
    STATICFILES_DIRS = [
    BASE_DIR / 'static'
    ]

    STATIC_ROOT = BASE_DIR / 'static'

    MEDIA_URL = 'media/'
    MEDIA_ROOT = BASE_DIR / 'media'
    CKEDITOR_UPLOAD_PATH = "uploads/"
    STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

    Default primary key field type
    https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

    DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

    LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
    'console': {
    'class': 'logging.StreamHandler',
    },
    },
    'loggers': {
    'django': {
    'handlers': ['console'],
    'level': 'INFO', # Or 'DEBUG' if you want more verbose Django internal logs
    },
    'IPD': { # Replace 'your_app_name' with the actual name of your app (e.g., 'IPD')
    'handlers': ['console'],
    'level': 'DEBUG', # Set to DEBUG to see all your specific prints
    'propagate': False,
    },
    },
    }


    ADMINS = [('Admin', 'admin@example.com')]
    DEFAULT_FROM_EMAIL = 'noreply@example.com'


    For local development (HTTP)
    SESSION_COOKIE_SECURE = False  
    CSRF_COOKIE_SECURE = False 


    CACHES = {
    'default': {
    'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
    'LOCATION': '127.0.0.1:11211',
    'TIMEOUT': 300,  # 5 minutes
    'OPTIONS': {
    'no_delay': True,
    'ignore_exc': True,
    'max_pool_size': 4,
    'use_pooling': True,
    }
    }
    }


    Haystack
INSTALLED_APPS += ['haystack']
# Whoosh configuration
HAYSTACK_CONNECTIONS = {
    'default': {
        'ENGINE': 'haystack.backends.whoosh_backend.WhooshEngine',
        'PATH': os.path.join(BASE_DIR, 'whoosh_index'),
        'INCLUDE_SPELLING': False,  # DISABLING spelling for speed boost!
        'BATCH_SIZE': 1000,          # Increase batch size for indexing
        'STORAGE': 'file',
        'POST_LIMIT': 256 * 1024 * 1024,  # 256MB for large index
    },
}

# Whoosh cache config
WHOOSH_INDEX_OPTIONS = {
    'cache': {
        'size': 1000,  # Number of queries to cache
        'expiry': 3600,  # Cache expiry in seconds (1 hour)
    }
}
# Autoupdate the index on save/delete
HAYSTACK_SIGNAL_PROCESSOR = 'haystack.signals.RealtimeSignalProcessor'


# Add connection pooling
HAYSTACK_CUSTOM_BACKEND = {
    'default': {
        'CONNECTION_POOL_SIZE': 10,  # Handle concurrent searches
    }
}

# # Celery settings for signals
# CELERY_BROKER_URL = 'redis://localhost:6379/0'
# CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
# CELERY_TASK_SOFT_TIME_LIMIT = 600  # 10 minutes timeout


# # session handling
# SESSION_COOKIE_AGE = 7200  # 2 hour timeout
# SESSION_SAVE_EVERY_REQUEST = True  
# SESSION_EXPIRE_AT_BROWSER_CLOSE = True  

