"""
Django settings for uscip_project (合併版：ISMS_Platform + Office Portal)
"""
import os
from pathlib import Path

# 自動載入 .env 檔案
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
except ImportError:
    pass  # python-dotenv 未安裝時靜默跳過，改用系統環境變數

BASE_DIR = Path(__file__).resolve().parent.parent

# ── 安全 ──────────────────────────────────────────────────────────────────────
# 生產環境：從環境變數讀取，不要 hardcode
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-52%+fig%=*bu%)pc$x^3rta*v8k%eqndp^wt#ar$6()hz64hl!'
)
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'
ALLOWED_HOSTS = ['office.quilter.net','13.230.190.23','127.0.0.1']

CSRF_TRUSTED_ORIGINS = [
    'http://office.quilter.net',
    'https://office.quilter.net',
    'http://13.230.190.23',
]

# ── 前端重設密碼連結用（views.py 的 portal_forgot 需要）─────────────────────
APP_BASE_URL = os.environ.get('APP_BASE_URL', 'http://localhost:8000')

# ── 應用程式 ──────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # 第三方
    'rest_framework',
    'rest_framework.authtoken',

    # 本專案 Apps
    'compliance',   # ISMS：ISO 27001 控制項 / 合規證據 / 稽核報告
    'portal',       # Office Portal：帳號申請、服務申請、公告
    'tailwind',
    'theme',        # Tailwind CSS 主題（必須在 tailwind app 之後）
]

TAILWIND_APP_NAME = 'theme' 

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'uscip_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],   # 全局 templates 目錄
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

WSGI_APPLICATION = 'uscip_project.wsgi.application'

# ── 資料庫 ────────────────────────────────────────────────────────────────────
# 預設 SQLite（開發）；生產環境改用 MySQL/PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.sqlite3'),
        'NAME':   os.environ.get('DB_NAME',   str(BASE_DIR / 'db.sqlite3')),
        'USER':     os.environ.get('DB_USER',     ''),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST':     os.environ.get('DB_HOST',     ''),
        'PORT':     os.environ.get('DB_PORT',     '3306'),
    }
}

# ── 密碼驗證 ──────────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── 國際化 ────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Asia/Taipei'
USE_I18N      = False
USE_TZ        = True

# ── 靜態 / 媒體檔案 ───────────────────────────────────────────────────────────
STATIC_URL  = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── DRF 設定 ──────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── 登入導向 ──────────────────────────────────────────────────────────────────
LOGIN_URL          = '/office-portal/'
LOGIN_REDIRECT_URL = '/office-portal/dashboard/'

# ── Power Automate Webhook URLs ───────────────────────────────────────────────
# 兩個流程都用「當 HTTP 要求收到時」觸發
# 建好流程後把 URL 填在這裡（或用環境變數）
PA_TEAMS_WEBHOOK = 'https://defaultb09d388534804b4d9bf9386663232c.47.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/6e47eb3dce7f446c8a3ec5ea6c3eeabe/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=Nk6om5pGviasUjfeXkGAFgrG_WVEaTMFxG_8IHZFrx8' # Teams 通知流程
PA_EMAIL_WEBHOOK = 'https://defaultb09d388534804b4d9bf9386663232c.47.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/66149d96ddab44709e8987afe56b917e/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=kIm6qAN97PRxbJDDje_BYPgoLZaEx7UpyFuYBGN_Sao'  # 寄信流程
import os
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')  # collectstatic 的輸出目錄

# File upload limit: 5MB，指定在 views.py 的 portal_upload_attachment 也要一併修改
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024