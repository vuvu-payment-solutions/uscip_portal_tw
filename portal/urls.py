from django.urls import path
from . import views

urlpatterns = [

    # ── 認證 ───────────────────────────────────────
    path("",                                       views.portal_home,            name="portal_home"),
    path("login/",                                 views.portal_login,           name="portal_login"),
    path("logout/",                                views.portal_logout,          name="portal_logout"),
    path("dashboard/",                             views.portal_dashboard,       name="portal_dashboard"),
    path("forgot/",                                views.portal_forgot,          name="portal_forgot"),
    path("reset/<str:token>/",                     views.portal_reset,           name="portal_reset"),

    # ── 帳號設定 ───────────────────────────────────
    path("settings/",                              views.settings_home,          name="portal_settings"),
    path("change-password/",                       views.change_password,        name="portal_change_password"),
    path("edit-profile/",                          views.edit_profile,           name="portal_edit_profile"),

    # ── 帳號申請及審核 ─────────────────────────────
    path("register/",                              views.portal_register,        name="portal_register"),
    path("accounts/",                              views.account_list,           name="portal_account_list"),
    path("api/account/<int:req_id>/",              views.account_detail_api,   name="account_detail_api"),
    path("resubmit-account/<str:token>/", views.resubmit_account, name="portal_resubmit_account"),
    path("approve-account/<int:req_id>/",          views.approve_account,        name="portal_approve_account"),
    path("review-account/<int:req_id>/",           views.review_account,         name="portal_review_account"),
    path("resume-account/<int:req_id>/",           views.resume_account,         name="portal_resume_account"),
    path("reject-account/<int:req_id>/",           views.reject_account,         name="portal_reject_account"),

    # ── 服務申請 ───────────────────────────────────
    path("apply/",                                 views.submit_application,     name="portal_apply"),
    path("applications/",                          views.application_list,       name="portal_application_list"),
    path("api/application/<int:app_id>/",          views.application_detail_api, name="application_detail_api"),
    path("approve-application/<int:app_id>/",      views.approve_application,    name="portal_approve_application"),
    path("reject-application/<int:app_id>/",       views.reject_application,     name="portal_reject_application"),
    path("resubmit-application/<int:app_id>/",     views.resubmit_application,   name="portal_resubmit_application"),
    path("preview-application/<int:app_id>/",      views.preview_application,    name="preview_application"),
    path("resume-application/<int:app_id>/",       views.resume_application,     name="resume_application"),
    path("complete-application/<int:app_id>/",     views.complete_application,   name="complete_application"),
    path("bookmark-application/<int:app_id>/",     views.add_bookmark,           name="add_bookmark"),

    # ── 硬體申請 ───────────────────────────────────
    path("hardware/apply/", views.submit_hardware, name="hardware_apply"),
    path("hardware/list/", views.hardware_list, name="hardware_list"),
    path("hardware/detail/<int:req_id>/", views.hardware_detail_api, name="hardware_detail_api"),
    path("hardware/resubmit/<int:req_id>/", views.resubmit_hardware, name="resubmit_hardware"),
    path("hardware/action/<int:req_id>/", views.hardware_action, name="hardware_action"),
    
    # ── 公告 ───────────────────────────────────────
    path("notices/",                               views.notice_list,            name="portal_notices"),
    path("notices/create/",                        views.create_notice,          name="portal_create_notice"),
]