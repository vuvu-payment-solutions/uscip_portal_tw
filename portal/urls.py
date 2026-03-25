from django.urls import path, include  # 修正：補上 include
from . import views


urlpatterns = [
    
    # ── 認證 ───────────────────────────────────────
    path("",              views.portal_home,     name="portal_home"),
    path("login/",        views.portal_login,    name="portal_login"),
    path("logout/",       views.portal_logout,   name="portal_logout"),
    path("dashboard/",    views.portal_dashboard, name="portal_dashboard"),
    path("forgot/",       views.portal_forgot,   name="portal_forgot"),
    path("reset/<str:token>/", views.portal_reset, name="portal_reset"),
    
    # 帳號設定的核心
    path('settings/', views.settings_home, name='portal_settings'),
    path("change-password/", views.change_password, name="portal_change_password"),
    path('edit-profile/', views.edit_profile, name='portal_edit_profile'),
    
    # ── 帳號申請及審核 ────────────────────────────────────
    path("register/",                             views.portal_register,   name="portal_register"),
    path("approve-account/<int:req_id>/",         views.approve_account,   name="portal_approve_account"),
    path("reject-account/<int:req_id>/",          views.reject_account,    name="portal_reject_account"),

    # ── 服務申請 ────────────────────────────────────
    path("apply/",                                views.submit_application, name="portal_apply"),
    path("applications/",                         views.application_list,   name="portal_application_list"),
    path("approve-application/<int:app_id>/",     views.approve_application, name="portal_approve_application"),
    path("reject-application/<int:app_id>/",      views.reject_application,  name="portal_reject_application"),

    # ── 公告 ────────────────────────────────────────
    path("notices/",   views.notice_list,   name="portal_notices"),
    path("notices/create/", views.create_notice, name="portal_create_notice"),
]