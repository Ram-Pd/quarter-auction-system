"""
All settings for the project, in this order:

    1. Secrets and security            (SECRET_KEY, DEBUG, hosts, https)
    2. Installed apps and middleware
    3. Templates, ASGI, WebSockets (channel layer), cache, logging
    4. Database
    5. Passwords, language and time zone, static files
    6. Email
    7. Login / logout
    8. PROJECT SETTINGS: the auction business values (bottom of the file)

Values that differ per machine, or that you may want to tune, are read from
the .env file (see .env.example). docs/HOW_TO_CHANGE.md lists every one.
Django reference: https://docs.djangoproject.com/en/5.2/ref/settings/
"""

import sys
from decimal import Decimal
from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Secrets and machine-specific values come from the .env file (never committed).
# The second value in each tuple is the type; the default (if any) is used
# when the variable is missing from .env.
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)
environ.Env.read_env(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
# No default on purpose: Django refuses to start if SECRET_KEY is missing.
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG')

ALLOWED_HOSTS = env('ALLOWED_HOSTS')
# Full origins (scheme + host) allowed to POST forms, e.g. https://auction.example.org
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

# -----------------------------------------------------------------------------
# Production security: switched on automatically whenever DEBUG is False.
# See docs/DEPLOYMENT.md.
# -----------------------------------------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)   # http -> https
    SESSION_COOKIE_SECURE = True    # session cookie only sent over https
    CSRF_COOKIE_SECURE = True
    # Browsers remember "this site is https-only". Start small; raise once https is stable.
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=60 * 60 * 24 * 30)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
    # Set when a reverse proxy (nginx, IIS) terminates https and forwards plain http.
    if env.bool('BEHIND_HTTPS_PROXY', default=False):
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_HTTPONLY = True     # JavaScript can't read the session cookie
SESSION_COOKIE_AGE = 60 * 60 * 8   # log out after 8 hours


# Application definition

INSTALLED_APPS = [
    'daphne',  # must be first: makes "runserver" serve WebSockets too (ASGI)
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',  # number formatting in templates (1,234)
    'channels',                 # WebSockets
    # Project apps
    'accounts',       # login accounts: email + password, sign-up OTP
    'applications',   # "Register for bidding", Aadhaar/PAN, URN, PDFs, offline verification
    'auctions',       # quarters, auctions, live bidding, closure
]

# Our own user model (accounts/models.py): logs in with EMAIL instead of a username.
AUTH_USER_MODEL = 'accounts.User'

MIDDLEWARE = [
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
        'DIRS': [BASE_DIR / 'templates'],  # project-wide templates (base.html, home.html)
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'config.context_processors.project_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'  # HTTP + WebSockets (Daphne)

# Channel layer: how WebSocket messages reach every process.
# No REDIS_URL -> in-memory layer: fine for ONE server process (development).
# Several processes (production) need Redis: set REDIS_URL=redis://localhost:6379/0
REDIS_URL = env('REDIS_URL', default='')
if REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [REDIS_URL]},
        },
    }
else:
    CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

# Cache: used for login/activation rate limiting. With Redis, all server
# processes share the counters; without it each process counts separately.
if REDIS_URL:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': REDIS_URL}}

# Logging: errors from our apps (e.g. failed emails, worker problems) go to the console.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'}},
    'loggers': {
        'accounts': {'handlers': ['console'], 'level': 'INFO'},
        'applications': {'handlers': ['console'], 'level': 'INFO'},
        'auctions': {'handlers': ['console'], 'level': 'INFO'},
    },
}


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

# SQLite for early milestones only. Milestone 4 switches to PostgreSQL by
# changing DATABASE_URL in .env (select_for_update() has no effect on SQLite).
DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}'),
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        # "Too similar to your email / name". Our User has full_name, not first/last name.
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
        'OPTIONS': {'user_attributes': ('email', 'full_name')},
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


# Automated tests only ("manage.py test"): a fast password hasher. Real hashing
# is deliberately slow (~0.5 s per password), which would make the test suite,
# which creates hundreds of users, take many minutes. Never used outside tests.
if len(sys.argv) > 1 and sys.argv[1] == 'test':
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Kolkata'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']   # project-wide CSS / JS
STATIC_ROOT = BASE_DIR / 'staticfiles'     # filled by "collectstatic" for production

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Email
# - EMAIL_HOST_PASSWORD set in .env -> real sending through SMTP (e.g. Gmail).
# - No password                     -> each email is saved as a .eml file in
#   sent_emails/ (double-click to open it, attachments included).
# Set the password easily with:  .\scripts\setup_email.ps1
# EMAIL_BACKEND in .env overrides this choice.
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='').replace(' ', '')  # Gmail shows it with spaces
EMAIL_BACKEND = env('EMAIL_BACKEND', default=(
    'django.core.mail.backends.smtp.EmailBackend' if EMAIL_HOST_PASSWORD
    else 'config.email_backends.EmlFileBackend'))
EMAIL_FILE_PATH = BASE_DIR / 'sent_emails'
EMAIL_HOST = env('EMAIL_HOST', default='localhost')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_TIMEOUT = 20  # seconds; don't hang the registration page if SMTP is down
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='auction-demo@localhost')


# Login / logout
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'auctions:listing'
LOGOUT_REDIRECT_URL = 'home'
PASSWORD_RESET_TIMEOUT = 60 * 60  # reset links expire after 1 hour (seconds)


# =============================================================================
# PROJECT SETTINGS: the business values you are most likely to change.
# Each can be overridden in .env without touching code.
# =============================================================================

# Placeholders: NOT official SAIL values (see CLAUDE.md open questions).
AUCTION_TITLE = env('AUCTION_TITLE', default='Vacant Quarter Auction (Training Demo)')
AUCTION_REFERENCE = env('AUCTION_REFERENCE', default='DEMO/QA/2026/01')
# Shown on the Intimation Slip's SBI Collect instructions (placeholder text).
SBI_COLLECT_PAYEE = env('SBI_COLLECT_PAYEE', default='SAIL Bokaro Steel Plant - Quarter Auction EMD (DEMO)')

# Aadhaar / PAN encryption (applications/crypto.py). Secrets: .env only.
# FIELD_ENCRYPTION_KEYS: comma-separated Fernet keys, newest FIRST (rotation).
# IDENTITY_HASH_KEY: secret for the keyed hash that enforces "one application per Aadhaar/PAN".
# Generate both with:  python manage.py generate_secret_keys
FIELD_ENCRYPTION_KEYS = env.list('FIELD_ENCRYPTION_KEYS', default=[])
IDENTITY_HASH_KEY = env('IDENTITY_HASH_KEY', default='')

# Sign-up email OTP (accounts/otp.py).
OTP_LENGTH = 6
OTP_VALID_MINUTES = env.int('OTP_VALID_MINUTES', default=10)
OTP_MAX_ATTEMPTS = env.int('OTP_MAX_ATTEMPTS', default=5)            # wrong guesses per code
OTP_RESEND_COOLDOWN_SECONDS = env.int('OTP_RESEND_COOLDOWN_SECONDS', default=60)
OTP_SENDS_PER_EMAIL_PER_HOUR = env.int('OTP_SENDS_PER_EMAIL_PER_HOUR', default=5)
OTP_SENDS_PER_IP_PER_HOUR = env.int('OTP_SENDS_PER_IP_PER_HOUR', default=20)
# After the code is confirmed, the "choose a password" step must be finished within this time.
SIGNUP_VERIFIED_WINDOW_MINUTES = env.int('SIGNUP_VERIFIED_WINDOW_MINUTES', default=30)

# Brute-force protection for login (accounts/ratelimit.py).
# After this many failures within the window, further attempts are refused
# until the window has passed.
AUTH_RATE_LIMIT_ATTEMPTS = env.int('AUTH_RATE_LIMIT_ATTEMPTS', default=5)        # per email
AUTH_RATE_LIMIT_IP_ATTEMPTS = env.int('AUTH_RATE_LIMIT_IP_ATTEMPTS', default=50)  # per IP address
AUTH_RATE_LIMIT_WINDOW_SECONDS = env.int('AUTH_RATE_LIMIT_WINDOW_SECONDS', default=15 * 60)

# Register for bidding (applications/).
# An applicant may APPLY for any number of quarters but WIN at most this many.
MAX_QUARTERS_PER_APPLICANT = env.int('MAX_QUARTERS_PER_APPLICANT', default=2)
# A quarter can be selected (or added later) until this many hours before its
# auction starts, leaving time for offline EMD verification. Placeholder
# (CR #3 open question 4).
APPLICATION_CLOSES_HOURS_BEFORE_AUCTION = env.int('APPLICATION_CLOSES_HOURS_BEFORE_AUCTION', default=24)

# Auctions created by the Excel import (auctions/importers.py).
# Used when the "Duration (min)" cell is blank. Editable per auction in the admin.
DEFAULT_AUCTION_DURATION_MINUTES = env.int('DEFAULT_AUCTION_DURATION_MINUTES', default=5)
# Bid step = this percentage of the base rate (0.20 means 0.2 %). Editable per auction.
DEFAULT_INCREMENT_PERCENT = Decimal(env('DEFAULT_INCREMENT_PERCENT', default='0.20'))

# Bidding (auctions/bidding.py). Placeholders: NOT official SAIL rules.
QUICK_BID_STEPS = (1, 2, 5)  # the "+1 / +2 / +5 steps" buttons
# Anti-sniping is per auction (Auction.anti_snipe_seconds, 0 = off). When on, a
# deadline can be extended at most this many times, so an auction always ends.
AUCTION_MAX_EXTENSIONS = env.int('AUCTION_MAX_EXTENSIONS', default=5)
# Minimum gap between two bids from the same browser connection (anti-flooding).
AUCTION_BID_MIN_INTERVAL_SECONDS = env.float('AUCTION_BID_MIN_INTERVAL_SECONDS', default=1.0)
# How many recent bids the auction page shows.
AUCTION_RECENT_BIDS_SHOWN = env.int('AUCTION_RECENT_BIDS_SHOWN', default=20)

# Closure (auctions/closing.py) and notifications (auctions/emails.py).
# How often "python manage.py run_auction_worker" checks for finished auctions.
AUCTION_WORKER_INTERVAL_SECONDS = env.int('AUCTION_WORKER_INTERVAL_SECONDS', default=5)
# Email the bidders who did not win (off by default).
AUCTION_NOTIFY_LOSERS = env.bool('AUCTION_NOTIFY_LOSERS', default=False)
# How long closed auctions stay in the "Recently closed" list.
AUCTION_RECENTLY_CLOSED_DAYS = env.int('AUCTION_RECENTLY_CLOSED_DAYS', default=7)
