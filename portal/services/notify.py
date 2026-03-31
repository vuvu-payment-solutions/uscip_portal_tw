"""
portal/services/notify.py
==========================
統一透過 Power Automate HTTP 觸發器發送通知。
Django 只負責 POST JSON，寄信和 Teams 訊息都由 Power Automate 處理。
"""
import json
import logging
import urllib.request
import urllib.error

from django.conf import settings

logger = logging.getLogger(__name__)


# ── 部門 → Supervisor 查詢 ────────────────────────────────────────────────────

def _get_supervisor_email(department: str) -> str:
    """根據部門查出 Supervisor Email，找不到就用預設值"""
    dept_map = getattr(settings, "DEPT_SUPERVISOR_MAP", {})
    default = getattr(settings, "DEFAULT_SUPERVISOR_EMAIL", "stanford.lee@quilter.net")
    return dept_map.get(department, default)


# ── 共用 HTTP POST ────────────────────────────────────────────────────────────

def _post(url_setting: str, payload: dict) -> bool:
    """共用 HTTP POST 方法"""
    url = getattr(settings, url_setting, "")
    if not url:
        logger.warning(f"[Notify] {url_setting} 未設定，跳過通知。")
        return False

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req  = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 202)
    except urllib.error.URLError as e:
        logger.error(f"[Notify] POST 失敗 ({url_setting})：{e}")
        return False


# ── Teams 通知：帳號申請 ──────────────────────────────────────────────────────

def teams_new_account_request(username: str, full_name: str, department: str, requested_role: str):
    """新帳號申請 → Teams 通知該部門的 Supervisor"""
    return _post("PA_TEAMS_WEBHOOK", {
        "event":            "new_account_request",
        "notify_to":        "supervisor",
        "supervisor_email": _get_supervisor_email(department),
        "applicant_email":  "",
        "username":         username,
        "full_name":        full_name,
        "department":       department or "-",
        "requested_role":   requested_role,
        "message":          f"📋 新帳號申請待審核\n申請人：{full_name}（{username}）\n部門：{department or '-'}\n角色：{requested_role}",
        "action_url":       f"{getattr(settings, 'APP_BASE_URL', '')}/office-portal/dashboard/",
    })


def teams_account_pending_cio(username: str, full_name: str):
    """主管審核通過 → Teams 通知 CIO"""
    return _post("PA_TEAMS_WEBHOOK", {
        "event":            "account_pending_cio",
        "notify_to":        "cio",
        "supervisor_email": "",
        "applicant_email":  "",
        "username":         username,
        "full_name":        full_name,
        "message":          f"🔔 帳號申請已通過主管審核，待 CIO 確認\n帳號：{username}（{full_name}）",
        "action_url":       f"{getattr(settings, 'APP_BASE_URL', '')}/office-portal/dashboard/",
    })


def teams_account_approved(username: str, full_name: str, applicant_email: str = ""):
    """CIO 審核通過 → Teams 通知申請人"""
    return _post("PA_TEAMS_WEBHOOK", {
        "event":            "account_approved",
        "notify_to":        "applicant",
        "supervisor_email": "",
        "applicant_email":  applicant_email,
        "username":         username,
        "full_name":        full_name,
        "message":          f"✅ 帳號已核准建立\n帳號：{username}（{full_name}）\n初始密碼：{username}@Init2024",
        "action_url":       f"{getattr(settings, 'APP_BASE_URL', '')}/office-portal/dashboard/",
    })


def teams_account_rejected(username: str, full_name: str, comment: str = "", applicant_email: str = ""):
    """申請被拒絕 → Teams 通知申請人"""
    return _post("PA_TEAMS_WEBHOOK", {
        "event":            "account_rejected",
        "notify_to":        "applicant",
        "supervisor_email": "",
        "applicant_email":  applicant_email,
        "username":         username,
        "full_name":        full_name,
        "comment":          comment or "-",
        "message":          f"❌ 帳號申請已拒絕\n帳號：{username}（{full_name}）\n原因：{comment or '-'}",
    })


# ── Teams 通知：服務申請 ──────────────────────────────────────────────────────

def teams_new_service_application(f_no: str, a_name: str, a_type: str, service_system: str, department: str = ""):
    """新服務申請 → Teams 通知該部門的 Supervisor"""
    return _post("PA_TEAMS_WEBHOOK", {
        "event":            "new_service_application",
        "notify_to":        "supervisor",
        "supervisor_email": _get_supervisor_email(department),
        "applicant_email":  "",
        "f_no":             f_no,
        "a_name":           a_name,
        "a_type":           a_type,
        "service_system":   service_system or "-",
        "message":          f"📝 新服務申請待審核\n申請單：{f_no}\n申請人：{a_name}\n類型：{a_type}\n系統：{service_system or '-'}",
        "action_url":       f"{getattr(settings, 'APP_BASE_URL', '')}/office-portal/dashboard/",
    })


def teams_service_pending_cio(f_no: str, a_name: str, a_type: str, service_system: str):
    """主管審核通過 → Teams 通知 CIO"""
    return _post("PA_TEAMS_WEBHOOK", {
        "event":            "service_pending_cio",
        "notify_to":        "cio",
        "supervisor_email": "",
        "applicant_email":  "",
        "f_no":             f_no,
        "a_name":           a_name,
        "a_type":           a_type,
        "service_system":   service_system or "-",
        "message":          f"🔔 服務申請已通過主管審核，待 CIO 確認\n申請單：{f_no}\n申請人：{a_name}\n類型：{a_type}\n系統：{service_system or '-'}",
        "action_url":       f"{getattr(settings, 'APP_BASE_URL', '')}/office-portal/dashboard/",
    })


def teams_service_approved(f_no: str, a_name: str, a_type: str, service_system: str, applicant_email: str = ""):
    """CIO 審核通過 → Teams 通知申請人"""
    return _post("PA_TEAMS_WEBHOOK", {
        "event":            "service_approved",
        "notify_to":        "applicant",
        "supervisor_email": "",
        "applicant_email":  applicant_email,
        "f_no":             f_no,
        "a_name":           a_name,
        "a_type":           a_type,
        "service_system":   service_system or "-",
        "message":          f"✅ 服務申請已核准\n申請單：{f_no}\n申請人：{a_name}\n類型：{a_type}\n系統：{service_system or '-'}",
    })


def teams_service_rejected(f_no: str, a_name: str, comment: str = "", applicant_email: str = ""):
    """服務申請被拒絕 → Teams 通知申請人"""
    return _post("PA_TEAMS_WEBHOOK", {
        "event":            "service_rejected",
        "notify_to":        "applicant",
        "supervisor_email": "",
        "applicant_email":  applicant_email,
        "f_no":             f_no,
        "a_name":           a_name,
        "comment":          comment or "-",
        "message":          f"❌ 服務申請已拒絕\n申請單：{f_no}\n申請人：{a_name}\n原因：{comment or '-'}",
    })


# ── Email 通知（忘記密碼）────────────────────────────────────────────────────

def email_password_reset(to_email: str, reset_link: str):
    """寄送密碼重設信"""
    return _post("PA_EMAIL_WEBHOOK", {
        "event":      "password_reset",
        "to":         to_email,
        "subject":    "【USCIP】密碼重設請求",
        "body":       (
            f"您好，\n\n"
            f"我們收到了您的密碼重設請求。\n\n"
            f"請點擊以下連結重設密碼（連結 30 分鐘內有效）：\n\n"
            f"{reset_link}\n\n"
            f"若您沒有申請重設密碼，請忽略此信。\n\n"
            f"USCIP 系統管理團隊"
        ),
        "reset_link": reset_link,
    })