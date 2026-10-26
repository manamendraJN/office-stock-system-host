"""Settings for the Office Stock System (Django edition)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, str(default))).strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=''):
    return [v.strip() for v in str(env(name, default)).split(',') if v.strip()]


def _load_dotenv():
    """Tiny .env reader so no extra package is needed. Real environment variables win."""
    path = BASE_DIR / '.env'
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

DEBUG = env_bool('DJANGO_DEBUG', False)

SECRET_KEY = env('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'insecure-dev-key-not-for-production'
    else:
        raise RuntimeError('Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=true for local development).')
if not DEBUG and (len(SECRET_KEY) < 50 or SECRET_KEY == 'insecure-dev-key-not-for-production'):
    raise RuntimeError('DJANGO_SECRET_KEY must be a unique, randomly generated value of at least 50 characters in production.')

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'accounts',
    'catalog',
    'inventory',
    'branchops',
    'pettycash',
    'reports',
]

MIDDLEWARE = [
    'core.middleware.DatabaseUnavailableMiddleware',
    'core.middleware.RequestSettingCacheMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.ContentSecurityPolicyMiddleware',
    # Creates the default roles once, then makes sure the signed-in account is still allowed in.
    'core.middleware.CurrentUserMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'core.context_processors.app',
    ]},
}]

DB_ENGINE = env('DB_ENGINE', 'sqlite').strip().lower()
if DB_ENGINE == 'postgres':
    db_options = {
        'sslmode': env('DB_SSLMODE', 'prefer' if DEBUG else 'require'),
        # Fail fast instead of hanging a web worker when the database is unreachable.
        'connect_timeout': int(env('DB_CONNECT_TIMEOUT', '10')),
        # Keep long-lived connections healthy through home/office routers and NAT, which silently drop idle connections.
        'keepalives': 1, 'keepalives_idle': 30, 'keepalives_interval': 10, 'keepalives_count': 3,
    }
    if env('DB_SSLROOTCERT'):
        db_options['sslrootcert'] = env('DB_SSLROOTCERT')
    if not DEBUG:
        if not env('DB_USER') or not env('DB_PASSWORD'):
            raise RuntimeError('Set DB_USER and DB_PASSWORD for the production PostgreSQL connection.')
        # A typo such as "disable"/"allow"/"prefer" would silently send the database password and every row
        # over an unencrypted or downgradable connection, so refuse to start.
        if db_options['sslmode'] not in ('require', 'verify-ca', 'verify-full'):
            raise RuntimeError('DB_SSLMODE must be require, verify-ca or verify-full in production.')
    _db_port = str(env('DB_PORT', '5432'))
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DB_NAME', 'office_stock'),
        'USER': env('DB_USER', ''),
        'PASSWORD': env('DB_PASSWORD', ''),
        'HOST': env('DB_HOST', 'localhost'),
        'PORT': _db_port,
        'OPTIONS': db_options,
        # Reuse connections for a while, but check they are still alive before use (pooler restarts, idle drops).
        'CONN_MAX_AGE': int(env('DB_CONN_MAX_AGE', '60')),
        'CONN_HEALTH_CHECKS': True,
        # Supabase's transaction pooler (port 6543) does not support server-side cursors.
        'DISABLE_SERVER_SIDE_CURSORS': _db_port == '6543',
    }}
else:
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': Path(env('DB_PATH', str(BASE_DIR / 'db.sqlite3'))),
        'OPTIONS': {'timeout': 20},
    }}

CACHE_BACKEND = env('DJANGO_CACHE_BACKEND', 'locmem').strip().lower()
if CACHE_BACKEND == 'database':
    CACHES = {'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': env('DJANGO_CACHE_TABLE', 'django_cache'),
    }}
elif CACHE_BACKEND == 'locmem':
    CACHES = {'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'office-stock-login-throttle',
    }}
else:
    raise RuntimeError('DJANGO_CACHE_BACKEND must be locmem or database.')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.User'
AUTHENTICATION_BACKENDS = ['accounts.backends.EmailBackend']
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'core:dashboard'
LOGOUT_REDIRECT_URL = 'accounts:login'

# Same 8 hours as the original sign-in token.
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = env_bool('DJANGO_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = env_bool('DJANGO_COOKIE_SECURE', not DEBUG)

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-gb'
TIME_ZONE = env('TIME_ZONE', 'Asia/Colombo')
USE_I18N = False
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'
                    if not DEBUG else 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

CRON_SECRET = env('CRON_SECRET', '')

# Number of reverse proxies / load balancers in front of the app that APPEND to X-Forwarded-For (0 = none, e.g.
# local runs). Needed so the sign-in throttle and audit log see each user's own address. See core.services.audit.
TRUSTED_PROXY_COUNT = int(env('TRUSTED_PROXY_COUNT', '0'))

# After every `migrate`, switch on Row Level Security and revoke the anon/authenticated grants on this app's tables
# (PostgreSQL/Supabase only). The app talks to Postgres directly and never through Supabase's Data API.
SUPABASE_LOCKDOWN_DATA_API = env_bool('SUPABASE_LOCKDOWN_DATA_API', True)

SECURE_SSL_REDIRECT = env_bool('DJANGO_SSL_REDIRECT', not DEBUG)
# Platform health probes usually arrive over plain HTTP inside the private network. /health/ reveals no secrets.
SECURE_REDIRECT_EXEMPT = [r'^health/$']
SECURE_HSTS_SECONDS = int(env('DJANGO_HSTS_SECONDS', '0')) if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_HSTS_INCLUDE_SUBDOMAINS', False)
SECURE_HSTS_PRELOAD = env_bool('DJANGO_HSTS_PRELOAD', False)
if not DEBUG and env_bool('DJANGO_TRUST_X_FORWARDED_PROTO', False):
    # Enable only when the trusted reverse proxy strips client-supplied copies of this header.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

CSP_POLICY = (
    "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
    "form-action 'self'; img-src 'self' data:; font-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'"
)

MESSAGE_TAGS = {40: 'error'}
