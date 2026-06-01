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


# ── Teams 通知：ACReg Group 共用待審提醒 ───────────────────────────────────────

def teams_pending_approval(
    request_type: str,
    request_no: str,
    applicant: str,
    required_role: str,
    current_status: str,
    action_path: str,
    detail: str = "",
):
    """
    統一通知 ACReg Group：
    - ACReg Group 只負責接收待審提醒
    - required_role 指示目前應由哪一種角色處理
    - 實際操作權限仍由 Portal 後端 RBAC 與狀態檢查控管
    """
    base_url = getattr(settings, "APP_BASE_URL", "")
    action_url = f"{base_url}{action_path}"

    message_lines = [
        "🔔 [Office Portal] Pending Approval Reminder",
        f"申請類型：{request_type}",
        f"申請編號：{request_no}",
        f"申請人：{applicant}",
        f"目前狀態：{current_status}",
        f"待處理角色：{required_role}",
    ]

    if detail:
        message_lines.append(f"申請內容：{detail}")

    message_lines.append("請登入 Office Portal 進行審核。")

    return _post("PA_TEAMS_WEBHOOK", {
        "event": "pending_approval",
        "notify_to": "pending_approval",
        "notify_group": "ACReg Group",
        "request_type": request_type,
        "request_no": request_no,
        "applicant": applicant,
        "required_role": required_role,
        "current_status": current_status,
        "detail": detail or "-",
        "message": "\n".join(message_lines),
        "action_url": action_url,
    })


# ── Teams 通知：帳號申請 ──────────────────────────────────────────────────────

def teams_new_account_request(username: str, full_name: str, department: str, requested_role: str):
    """新帳號申請 → Teams 共用待審頻道通知 Team Leader"""
    return _post("PA_TEAMS_WEBHOOK", {
        "event":            "new_account_request",
        "notify_to":        "team_leader",
        "supervisor_email": "",
        "applicant_email":  "",
        "username":         username,
        "full_name":        full_name,
        "department":       department or "-",
        "requested_role":   requested_role,
        "message":          (
            f"📋 新帳號申請待 Team Leader 審核\n"
            f"申請人：{full_name}（{username}）\n"
            f"部門：{department or '-'}\n"
            f"申請角色：{requested_role}\n"
            f"目前階段：Pending Team Leader"
        ),
        "action_url":       f"{getattr(settings, 'APP_BASE_URL', '')}/office-portal/accounts/",
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
    """CIO 審核通過 → Teams 通知申請人；密碼由安全設定連結建立"""
    return _post("PA_TEAMS_WEBHOOK", {
        "event":            "account_approved",
        "notify_to":        "applicant",
        "supervisor_email": "",
        "applicant_email":  applicant_email,
        "username":         username,
        "full_name":        full_name,
        "message":          (
            f"✅ 帳號申請已核准\n"
            f"帳號：{username}（{full_name}）\n"
            f"請依系統寄送的安全設定密碼連結完成帳號啟用。"
        ),
        "action_url":       f"{getattr(settings, 'APP_BASE_URL', '')}/office-portal/",
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
        "subject":    "【Office Portal】密碼重設請求",
        "body":       (
            f"您好，\n\n"
            f"我們收到了您的密碼重設請求。\n\n"
            f"請點擊以下連結重設密碼（連結 30 分鐘內有效）：\n\n"
            f"{reset_link}\n\n"
            f"若您沒有申請重設密碼，請忽略此信。\n\n"
            f"Office Portal 系統管理團隊"
        ),
        "reset_link": reset_link,
    })
    
    
def email_account_password_setup(to_email: str, setup_link: str, username: str):
    """寄送新帳號首次設定密碼信"""
    return _post("PA_EMAIL_WEBHOOK", {
        "event":      "account_password_setup",
        "to":         to_email,
        "subject":    "【Office Portal】帳號已核准，請設定您的登入密碼",
        "body":       (
            f"您好，\n\n"
            f"您的 Office Portal 帳號申請已核准。\n\n"
            f"帳號：{username}\n\n"
            f"請點擊以下一次性連結設定登入密碼"
            f"（連結 30 分鐘內有效）：\n\n"
            f"{setup_link}\n\n"
            f"若您未提出此帳號申請，請聯絡資訊安全或系統管理人員。\n\n"
            f"Office Portal 系統管理團隊"
        ),
        "setup_link": setup_link,
    })
    

def email_account_returned(
    to_email: str,
    resubmit_link: str,
    username: str,
    return_reason: str,
):
    """寄送帳號申請退件修改通知與安全重新送出連結"""
    return _post("PA_EMAIL_WEBHOOK", {
        "event": "account_returned",
        "to": to_email,
        "subject": "【Office Portal】帳號申請已退回，請修改後重新送出",
        "body": (
            f"您好，\n\n"
            f"您的 Office Portal 帳號申請已退回修改。\n\n"
            f"帳號：{username}\n"
            f"退回原因：{return_reason or '-'}\n\n"
            f"請點擊以下安全連結修改並重新送出申請"
            f"（連結 7 天內有效）：\n\n"
            f"{resubmit_link}\n\n"
            f"若您未提出此帳號申請，請聯絡資訊安全或系統管理人員。\n\n"
            f"Office Portal 系統管理團隊"
        ),
        "resubmit_link": resubmit_link,
        "return_reason": return_reason or "-",
    })