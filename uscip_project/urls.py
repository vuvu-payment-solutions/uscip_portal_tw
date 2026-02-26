"""
uscip_project/urls.py  ─  合併版主路由
==========================================
  /admin/              → Django Admin
  /office-portal/      → portal app（登入、帳號申請、服務申請、公告）
  /compliance/         → compliance app（ISMS 控制項、合規報告）
  /api/                → DRF API（Token 認證）
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# ── Admin 介面品牌化 ──────────────────────────────────────────────────────────
admin.site.site_header  = "USCIP Compliance Management System"
admin.site.site_title   = "USCIP Admin Portal"
admin.site.index_title  = "ISMS Operations Control Center"

urlpatterns = [
    # Django 後台
    path('admin/', admin.site.urls),

    # Office Portal（登入 / 帳號申請 / 服務申請 / 公告）
    path('office-portal/', include('portal.urls')),

    # ISMS Compliance（控制項、合規報告）
    path('compliance/', include('compliance.urls')),

    # DRF 內建 Token Auth
    path('api/auth/', include('rest_framework.urls')),
]

# 開發環境：Django 自行 serve 媒體檔案
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)