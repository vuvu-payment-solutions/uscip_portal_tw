"""
portal/views.py
================
USCIP Office Portal — 完整視圖集合

權限矩陣（SOD 職責分離）：
  Pending Team Leader       → Team Leader only
  Under-Preview (Team Leader) → Team Leader only (Resume)
  Pending Supervisor        → Supervisor only
  Under-Preview (Supervisor) → Supervisor only (Resume)
  Pending CIO               → CIO only
  Under-Preview (CIO)       → CIO only (Resume)
  Work-in-progress          → CIO / Hardware Supervisor complete execution tasks

Account 退件流程：
  Team Leader 可退件 → Returned（申請人透過 Email signed token link 修改後重新送出）
  Supervisor 可退件 → Returned（申請人透過 Email signed token link 修改後重新送出）
  CIO 可退件給申請人 → Returned（申請人透過 Email signed token link 修改後重新送出）
  CIO 可退件給 Supervisor → Pending Supervisor（附退件原因於 comment）
  申請人重新送出 Returned → Pending Team Leader（清除 return_reason / return_date，重新通知 ACReg）

Service / API Application 退件流程：
  Team Leader / Supervisor 可退件 → Returned
  CIO 可退件給申請人 → Returned
  CIO 可退件給 Supervisor → Pending Supervisor（附退件原因於 bookmark）
  申請人重新送出 Returned → Pending Team Leader

Hardware Application 退件流程：
  Team Leader / Supervisor / Hardware Supervisor 可退件 → Returned
  申請人重新送出 Returned → Pending Team Leader
"""
import json
import secrets

from compliance.models import ControlDomain
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core import signing
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import (
    AccountRequest,
    Application,
    Notice,
    UserProfile,
    PasswordResetToken,
    ApprovalHistory,
    HardwareRequest, 
    HardwareApprovalHistory,
)

from .services.notify import (
    teams_pending_approval,
    teams_new_account_request,
    teams_account_pending_cio,
    teams_account_approved,
    teams_account_rejected,
    teams_new_service_application,
    teams_service_pending_cio,
    teams_service_approved,
    teams_service_rejected,
    email_password_reset,
    email_account_password_setup,
    email_account_returned,
)

# ─────────────────────────────────────────────
# Helper：審核歷程紀錄
# ─────────────────────────────────────────────

def _log_history(application, action, from_status, to_status, user, role, comment=""):
    ApprovalHistory.objects.create(
        application=application,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor=user,
        actor_role=role,
        comment=comment,
    )
    
    
def _log_hardware_history(hardware_request, action, from_status, to_status, user, role, comment=""):
    HardwareApprovalHistory.objects.create(
        hardware_request=hardware_request,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor=user,
        actor_role=role,
        comment=comment,
    )


def _get_applicant_email(username: str) -> str:
    try:
        return User.objects.get(username=username).email or ""
    except User.DoesNotExist:
        return ""


# ─────────────────────────────────────────────
# Helper：Account Returned Resubmit Secure Token
# ─────────────────────────────────────────────

ACCOUNT_RESUBMIT_TOKEN_SALT = "office_portal.account_resubmit"
ACCOUNT_RESUBMIT_TOKEN_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _generate_account_resubmit_token(req: AccountRequest) -> str:
    """
    產生 Account Request 退件後重新送出的簽章 token。
    Token 不儲存在資料庫，透過 Django signing 驗證完整性與有效期限。
    """
    return signing.dumps(
        {
            "req_id": req.id,
            "username": req.username,
            "email": req.email,
        },
        salt=ACCOUNT_RESUBMIT_TOKEN_SALT,
    )


def _get_account_request_from_resubmit_token(token: str):
    """
    驗證 Account Request 重新送出 token：
    - token 不可被竄改
    - token 有效期限為 7 天
    - token 內容必須仍對應該筆申請
    """
    try:
        payload = signing.loads(
            token,
            salt=ACCOUNT_RESUBMIT_TOKEN_SALT,
            max_age=ACCOUNT_RESUBMIT_TOKEN_MAX_AGE,
        )
    except signing.SignatureExpired:
        return None, "此重新送出連結已逾期，請聯絡系統管理者重新提供連結。"
    except signing.BadSignature:
        return None, "此重新送出連結無效，請勿使用未經授權的連結。"

    req = AccountRequest.objects.filter(pk=payload.get("req_id")).first()
    if not req:
        return None, "找不到對應的帳號申請資料。"

    if req.username != payload.get("username") or req.email != payload.get("email"):
        return None, "此重新送出連結與申請資料不符，請聯絡系統管理者。"

    return req, ""


def _send_account_resubmit_link(req: AccountRequest, return_reason: str) -> None:
    """
    Account Request 退回申請人後，寄送帶有 signed token 的安全重新送出連結。
    """
    token = _generate_account_resubmit_token(req)
    resubmit_link = (
        f"{settings.APP_BASE_URL}/office-portal/resubmit-account/{token}/"
    )

    email_account_returned(
        to_email=req.email,
        resubmit_link=resubmit_link,
        username=req.username,
        return_reason=return_reason,
    )


# ─────────────────────────────────────────────
# 1. 入口 / 認證
# ─────────────────────────────────────────────

@ensure_csrf_cookie
def index(request):
    return render(request, 'index.html')


def portal_home(request):
    notices = Notice.objects.filter(is_active=True)[:5]
    return render(request, "office_portal/index.html", {"notices": notices})


@require_POST
def portal_login(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"success": False, "detail": "Bad request"}, status=400)

    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"success": False, "detail": "帳號或密碼錯誤"}, status=401)

    login(request, user)
    role = getattr(user, 'profile', None)
    role_str = role.role if role else "user"
    return JsonResponse({"success": True, "username": user.username, "role": role_str})


def portal_logout(request):
    logout(request)
    return redirect("portal_home")


@login_required
def change_password(request):
    if request.method == "GET":
        return render(request, "office_portal/change_password.html")

    old_password  = request.POST.get("old_password", "").strip()
    new_password1 = request.POST.get("new_password1", "").strip()
    new_password2 = request.POST.get("new_password2", "").strip()

    if not old_password or not new_password1 or not new_password2:
        messages.error(request, "所有欄位均為必填。")
        return render(request, "office_portal/change_password.html")

    if not request.user.check_password(old_password):
        messages.error(request, "目前密碼不正確。")
        return render(request, "office_portal/change_password.html")

    if new_password1 != new_password2:
        messages.error(request, "新密碼兩次輸入不一致。")
        return render(request, "office_portal/change_password.html")

    if len(new_password1) < 8:
        messages.error(request, "新密碼至少需要 8 個字元。")
        return render(request, "office_portal/change_password.html")

    if new_password1 == request.user.username:
        messages.error(request, "新密碼不能與帳號名稱相同。")
        return render(request, "office_portal/change_password.html")

    request.user.set_password(new_password1)
    request.user.save()

    from django.contrib.auth import update_session_auth_hash
    update_session_auth_hash(request, request.user)

    profile = getattr(request.user, 'profile', None)
    if profile and profile.must_change_pw:
        profile.must_change_pw = False
        profile.save()

    messages.success(request, "✅ 密碼已成功修改！")
    return render(request, "office_portal/change_password.html")


@login_required
def edit_profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "GET":
        return render(request, "office_portal/edit_profile.html", {"profile": profile})

    full_name  = request.POST.get("full_name", "").strip()
    department = request.POST.get("department", "").strip()
    email      = request.POST.get("email", "").strip()

    if not full_name or not email:
        messages.error(request, "Name and email are required.")
        return render(request, "office_portal/edit_profile.html", {"profile": profile})

    profile.full_name  = full_name
    profile.department = department
    profile.save()

    request.user.email      = email
    request.user.first_name = full_name
    request.user.save()

    messages.success(request, "✅ Profile updated successfully!")
    return render(request, "office_portal/edit_profile.html", {"profile": profile})


@login_required
def portal_dashboard(request):
    """儀表板：依角色顯示不同資料"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    domains = ControlDomain.objects.prefetch_related('items__evidences').all()
    domain_stats = []
    for domain in domains:
        items = list(domain.items.all())
        total = len(items)
        compliant = sum(1 for item in items if (ev := item.evidences.first()) and ev.status)
        domain_stats.append({
            "domain": domain, "total": total, "compliant": compliant,
            "rate": round(compliant / total * 100, 1) if total else 0,
        })

    if profile and profile.must_change_pw:
        messages.warning(request, "Please change your password before continuing.")
        return redirect("portal_change_password")

    context = {
        "role": role,
        "domain_stats": domain_stats,
        "notices": Notice.objects.filter(is_active=True)[:5],
        "my_account_requests": AccountRequest.objects.filter(
            username=request.user.username
        ).order_by("-created_at"),
        "my_hardware_requests": HardwareRequest.objects.filter(
            applicant=request.user
        ).order_by("-created_at")[:5],
        "my_applications": Application.objects.filter(
            a_name=request.user.username
        ).order_by("-created_at")[:5],
    }

    if role == "cio":
        context["pending_accounts"] = AccountRequest.objects.filter(status="Pending CIO")
        context["pending_apps"] = Application.objects.filter(
            Q(status="Pending CIO") |
            Q(status="Work-in-progress") |
            Q(status="Under-preview", preview_by="Pending CIO")
        )
    elif role == "hardware_supervisor":
        context["pending_hardware"] = HardwareRequest.objects.filter(
            Q(status="Pending Hardware Supervisor") |
            Q(status="Work-in-progress")
        )
    elif role == "supervisor":
        context["pending_accounts"] = AccountRequest.objects.filter(status="Pending Supervisor")
        context["pending_apps"] = Application.objects.filter(
            Q(status="Pending Supervisor") |
            Q(status="Under-preview", preview_by="Pending Supervisor")
        )
        context["pending_hardware"] = HardwareRequest.objects.filter(
            status="Pending Supervisor"
        )
    elif role == "team_leader":
        context["pending_accounts"] = AccountRequest.objects.filter(status="Pending Team Leader")
        context["pending_apps"] = Application.objects.filter(
            Q(status="Pending Team Leader") |
            Q(status="Under-preview", preview_by="Pending Team Leader")
        )
        context["pending_hardware"] = HardwareRequest.objects.filter(
            status="Pending Team Leader"
        )

    for req in context["my_account_requests"]:
        req.display_reason = req.return_reason or req.comment or ""

    for app in context["my_applications"]:
        app.display_reason = app.return_reason or app.bookmark or ""

    if "pending_accounts" in context:
        for req in context["pending_accounts"]:
            req.display_reason = req.return_reason or req.comment or ""

    if "pending_apps" in context:
        for app in context["pending_apps"]:
            app.display_reason = app.return_reason or app.bookmark or ""

    return render(request, "office_portal/dashboard.html", context)


# ─────────────────────────────────────────────
# 2. Account 帳號申請審核頁：
#    - 僅 Team Leader / Supervisor / CIO 可進入
#    - 依登入角色顯示目前待自己審核的帳號申請案件
# ─────────────────────────────────────────────

@login_required
def account_list(request):
    """
    Account 獨立頁籤：
    - 所有已登入使用者可查看自己的 Account Request
    - Team Leader / Supervisor / CIO 可查看目前待自己審核的案件
    """
    profile = getattr(request.user, "profile", None)
    role = profile.role if profile else "user"
    
    allowed_roles = ("team_leader", "supervisor", "cio")
    if role not in allowed_roles:
        messages.error(request, "You do not have permission to access Account Requests.")
        return redirect("portal_dashboard")
    
    if profile and profile.must_change_pw:
        messages.warning(request, "Please change your password before continuing.")
        return redirect("portal_change_password")

    pending_accounts = AccountRequest.objects.none()

    if role == "team_leader":
        pending_accounts = AccountRequest.objects.filter(
            Q(status="Pending Team Leader") |
            Q(status="Under-preview", preview_by="Pending Team Leader")
        ).order_by("-created_at")

    elif role == "supervisor":
        pending_accounts = AccountRequest.objects.filter(
            Q(status="Pending Supervisor") |
            Q(status="Under-preview", preview_by="Pending Supervisor")
        ).order_by("-created_at")

    elif role == "cio":
        pending_accounts = AccountRequest.objects.filter(
            Q(status="Pending CIO") |
            Q(status="Under-preview", preview_by="Pending CIO")
        ).order_by("-created_at")

    for req in pending_accounts:
        req.display_reason = req.return_reason or req.comment or ""

    context = {
        "role": role,
        "pending_accounts": pending_accounts,
    }

    return render(request, "office_portal/account_list.html", context)


# ─────────────────────────────────────────────
# 3. 忘記密碼 / 重設密碼
# ─────────────────────────────────────────────

def portal_forgot(request):
    if request.method == "GET":
        return render(request, "office_portal/forgot.html")

    email = (request.POST.get("email") or "").strip().lower()
    if not email:
        messages.error(request, "請輸入電子信箱。")
        return redirect("portal_forgot")

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        user = None

    if user:
        token = secrets.token_urlsafe(32)
        PasswordResetToken.objects.create(user=user, token=token)
        reset_link = f"{settings.APP_BASE_URL}/office-portal/reset/{token}/"
        email_password_reset(email, reset_link)

    messages.success(request, "若此信箱存在，重設連結已送出。")
    return redirect("portal_home")


def portal_reset(request, token: str):
    try:
        reset_obj = PasswordResetToken.objects.get(token=token)
    except PasswordResetToken.DoesNotExist:
        return render(request, "office_portal/reset_invalid.html")

    if not reset_obj.is_valid():
        return render(request, "office_portal/reset_invalid.html")

    if request.method == "GET":
        return render(request, "office_portal/reset.html", {"token": token})

    new_password = request.POST.get("password") or ""
    user = reset_obj.user

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
        return redirect("portal_reset", token=token)

    user.set_password(new_password)
    user.save()

    reset_obj.used = True
    reset_obj.save()

    messages.success(request, "✅ 密碼已重設成功，請用新密碼登入。")
    return redirect("portal_home")


# ─────────────────────────────────────────────
# 4. 帳號申請（自助註冊 → 兩階簽核 → 建立 Django User）
# ─────────────────────────────────────────────

def portal_register(request):
    """
    使用者自助申請帳號。
    支援 multipart/form-data（含附件），也相容 application/json（無附件）。
    """
    if request.method == "GET":
        return render(request, "office_portal/register.html")

    # ── 解析請求：支援 multipart 和 JSON ──────────────────────────
    content_type = request.content_type or ""
    if "multipart" in content_type or "form-data" in content_type:
        username       = request.POST.get("username", "").strip()
        full_name      = request.POST.get("full_name", "").strip()
        email          = request.POST.get("email", "").strip().lower()
        department     = request.POST.get("department", "").strip()
        requested_role = request.POST.get("requested_role", "user")
        description    = request.POST.get("description", "").strip()
        attachment     = request.FILES.get("attachment")
    else:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"success": False, "detail": "Bad request"}, status=400)
        username       = (payload.get("username") or "").strip()
        full_name      = (payload.get("full_name") or "").strip()
        email          = (payload.get("email") or "").strip().lower()
        department     = (payload.get("department") or "").strip()
        requested_role = payload.get("requested_role", "user")
        description    = (payload.get("description") or "").strip()
        attachment     = None
    # ─────────────────────────────────────────────────────────────

    if not all([username, full_name, email]):
        return JsonResponse({"success": False, "detail": "必填欄位不完整"}, status=400)

    if User.objects.filter(username=username).exists() or \
       AccountRequest.objects.filter(username=username).exclude(status="Returned").exists():
        return JsonResponse({"success": False, "detail": "帳號名稱已被使用或審核中"}, status=400)

    req = AccountRequest.objects.create(
        username=username,
        full_name=full_name,
        email=email,
        department=department,
        requested_role=requested_role,
        description=description,
        attachment=attachment,
        status="Pending Team Leader",
    )

    teams_pending_approval(
        request_type="Account Request",
        request_no=f"ACC-{req.id:04d}",
        applicant=req.username,
        required_role="Team Leader",
        current_status=req.status,
        action_path="/office-portal/accounts/",
        detail=f"{req.full_name} / {req.department} / Requested Role: {req.requested_role}",
    )

    return JsonResponse({"success": True, "detail": "申請已送出，等待 Team Leader 審核。"})


@login_required
@require_POST
def approve_account(request, req_id: int):
    """帳號申請簽核（SOD + Team Leader）"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    #  加入 team_leader 權限
    if role not in ("team_leader", "supervisor", "cio"):
        return JsonResponse({"success": False, "detail": "權限不足"}, status=403)

    req = get_object_or_404(AccountRequest, pk=req_id)

    # Team Leader Forward：轉交 Supervisor 審核
    if role == "team_leader" and req.status == "Pending Team Leader":
        req.status = "Pending Supervisor"
        req.team_leader = request.user
        req.save()

        teams_pending_approval(
            request_type="Account Request",
            request_no=f"ACC-{req.id:04d}",
            applicant=req.username,
            required_role="Supervisor",
            current_status=req.status,
            action_path="/office-portal/accounts/",
            detail=f"{req.full_name} / {req.department} / Requested Role: {req.requested_role}",
        )

        return JsonResponse({"success": True, "new_status": req.status})
        
    # Supervisor Forward：轉交 CIO 審核
    elif role == "supervisor" and req.status == "Pending Supervisor":
        req.status = "Pending CIO"
        req.save()

        teams_pending_approval(
            request_type="Account Request",
            request_no=f"ACC-{req.id:04d}",
            applicant=req.username,
            required_role="CIO",
            current_status=req.status,
            action_path="/office-portal/accounts/",
            detail=f"{req.full_name} / {req.department} / Requested Role: {req.requested_role}",
        )

        return JsonResponse({"success": True, "new_status": req.status})

    #  CIO 最終核准：建立尚未設定密碼的帳號，寄送一次性密碼設定連結
    elif role == "cio" and req.status == "Pending CIO":

        if User.objects.filter(username=req.username).exists():
            return JsonResponse({
                "success": False,
                "detail": "此帳號名稱已存在，無法重複建立帳號"
            }, status=400)

        new_user = User.objects.create_user(
            username=req.username,
            email=req.email,
            first_name=req.full_name,
        )
        new_user.set_unusable_password()
        new_user.save(update_fields=["password"])

        UserProfile.objects.create(
            user=new_user,
            role=req.requested_role,
            full_name=req.full_name,
            department=req.department,
            must_change_pw=False,
        )

        token = secrets.token_urlsafe(32)
        PasswordResetToken.objects.create(user=new_user, token=token)
        setup_link = f"{settings.APP_BASE_URL}/office-portal/reset/{token}/"

        req.status = "Approved"
        req.save()

        email_account_password_setup(req.email, setup_link, req.username)
        teams_account_approved(req.username, req.full_name, applicant_email=req.email)

        return JsonResponse({"success": True, "new_status": req.status})

    return JsonResponse({"success": False,
                         "detail": f"權限不足或狀態 {req.status} 不允許此操作"}, status=403)


@login_required
@require_POST
def reject_account(request, req_id: int):
    """
    帳號申請退件（SOD）
    POST JSON：
      {
        "comment":   "退件原因（必填）",
        "action":    "return"  → 退件給申請人修改（預設）
                     "reject"  → 永久拒絕
        "return_to": "applicant"  → 退給申請人（Returned）
                     "supervisor" → 退給 Supervisor 重審（僅 CIO 可用）
      }
    """
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if role not in ("team_leader","supervisor", "cio"):
        return JsonResponse({"success": False, "detail": "權限不足"}, status=403)

    req = get_object_or_404(AccountRequest, pk=req_id)

    if role == "team_leader" and req.status != "Pending Team Leader":
        return JsonResponse({"success": False,
                             "detail": "Team Leader 只能退件 Pending Team Leader 狀態"}, status=403)
    elif role == "supervisor" and req.status != "Pending Supervisor":
        return JsonResponse({"success": False,
                             "detail": "Supervisor 只能退件 Pending Supervisor 狀態"}, status=403)
    elif role == "cio" and req.status != "Pending CIO":
        return JsonResponse({"success": False,
                             "detail": "CIO 只能退件 Pending CIO 狀態"}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"success": False, "detail": "Bad request"}, status=400)

    comment   = (payload.get("comment") or "").strip()
    action    = payload.get("action", "return")      # "return" | "reject"
    return_to = payload.get("return_to", "applicant") # "applicant" | "supervisor"

    if not comment:
        return JsonResponse({"success": False, "detail": "退件原因不可空白"}, status=400)
    
    if action not in ("return", "reject"):
        return JsonResponse({
            "success": False,
            "detail": "不支援的帳號申請操作"
    }, status=400)
    
    # Team Leader 可退回申請人修改，但不可永久拒絕
    if role == "team_leader":
        if action == "reject":
            return JsonResponse({
                "success": False,
                "detail": "Team Leader 不可永久拒絕申請，只能退回申請人修改"
            }, status=403)

        req.status = "Returned"
        req.return_reason = comment
        req.return_date = timezone.now()
        req.save()
        
        _send_account_resubmit_link(req, comment)        

        return JsonResponse({"success": True, "new_status": req.status})

    if action == "reject":
        # 永久拒絕
        req.status  = "Rejected"
        req.comment = comment
        req.save()
        teams_account_rejected(req.username, req.full_name, comment, applicant_email=req.email)
        return JsonResponse({"success": True, "new_status": req.status})

    # action == "return"（退件讓申請人修改）
    if role == "supervisor":
        # Supervisor 只能退給申請人
        req.status        = "Returned"
        req.return_reason = comment
        req.return_date   = timezone.now()
        req.save()
        
        _send_account_resubmit_link(req, comment)        

        
        return JsonResponse({"success": True, "new_status": req.status})

    elif role == "cio":
        if return_to == "supervisor":
            # CIO 退給 Supervisor 重審：回到 Pending Supervisor，reason 寫入 comment
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
            req.status  = "Pending Supervisor"
            req.comment = f"[{timestamp} Returned by CIO] {comment}"
            req.save()

            teams_pending_approval(
                request_type="Account Request",
                request_no=f"ACC-{req.id:04d}",
                applicant=req.username,
                required_role="Supervisor",
                current_status=req.status,
                action_path="/office-portal/accounts/",
                detail=f"Returned by CIO: {comment}",
            )

            return JsonResponse({"success": True, "new_status": req.status})
        else:
            # CIO 退給申請人
            req.status        = "Returned"
            req.return_reason = comment
            req.return_date = timezone.now()
            req.save()
            
            _send_account_resubmit_link(req, comment)        
            
            return JsonResponse({"success": True, "new_status": req.status})


@login_required
@require_POST
def review_account(request, req_id: int):
    """
    Account Review：
    目前審核者將案件暫時設為 Under-preview，待討論後可 Resume。
    """
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    req = get_object_or_404(AccountRequest, pk=req_id)

    if role == "team_leader" and req.status == "Pending Team Leader":
        req.preview_by = "Pending Team Leader"

    elif role == "supervisor" and req.status == "Pending Supervisor":
        req.preview_by = "Pending Supervisor"

    elif role == "cio" and req.status == "Pending CIO":
        req.preview_by = "Pending CIO"

    else:
        return JsonResponse({
            "success": False,
            "detail": "權限不足或目前狀態無法設為 Review"
        }, status=403)

    req.status = "Under-preview"
    req.save()

    return JsonResponse({
        "success": True,
        "new_status": req.status
    })


@login_required
@require_POST
def resume_account(request, req_id: int):
    """
    Account Resume：
    將 Under-preview 案件恢復到原本的審核階段。
    """
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    req = get_object_or_404(AccountRequest, pk=req_id)

    if req.status != "Under-preview":
        return JsonResponse({
            "success": False,
            "detail": "只有 Under-preview 狀態才能 Resume"
        }, status=400)

    if req.preview_by == "Pending Team Leader":
        if role != "team_leader":
            return JsonResponse({
                "success": False,
                "detail": "此案件應由 Team Leader 恢復審核"
            }, status=403)
        req.status = "Pending Team Leader"

    elif req.preview_by == "Pending Supervisor":
        if role != "supervisor":
            return JsonResponse({
                "success": False,
                "detail": "此案件應由 Supervisor 恢復審核"
            }, status=403)
        req.status = "Pending Supervisor"

    elif req.preview_by == "Pending CIO":
        if role != "cio":
            return JsonResponse({
                "success": False,
                "detail": "此案件應由 CIO 恢復審核"
            }, status=403)
        req.status = "Pending CIO"

    else:
        return JsonResponse({
            "success": False,
            "detail": "找不到此案件原本的審核階段"
        }, status=400)

    req.preview_by = ""
    req.save()

    return JsonResponse({
        "success": True,
        "new_status": req.status
    })


def resubmit_account(request, token: str):
    """
    申請人透過安全 token 重新修改並送出已被退件的帳號申請（不需登入）。
    GET：驗證 token 後顯示預填表單（含退件原因）
    POST：驗證 token 後更新申請資料，狀態重置為 Pending Team Leader
    """
    req, token_error = _get_account_request_from_resubmit_token(token)

    if token_error:
        return render(request, "office_portal/register.html", {
            "error": token_error,
        })

    if req.status != "Returned":
        return render(request, "office_portal/register.html", {
            "error": f"此申請目前狀態為「{req.status}」，無法重新送出。",
        })

    if request.method == "GET":
        return render(request, "office_portal/register.html", {
            "resubmit_req": req,
            "resubmit_token": token,
        })

    # ── POST：更新申請 ──────────────────────────────────────────
    content_type = request.content_type or ""
    if "multipart" in content_type or "form-data" in content_type:
        full_name      = request.POST.get("full_name", req.full_name).strip()
        email          = request.POST.get("email", req.email).strip().lower()
        department     = request.POST.get("department", req.department).strip()
        requested_role = request.POST.get("requested_role", req.requested_role)
        description    = request.POST.get("description", "").strip()
        new_attachment = request.FILES.get("attachment")
    else:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"success": False, "detail": "Bad request"}, status=400)

        full_name      = (payload.get("full_name") or req.full_name).strip()
        email          = (payload.get("email") or req.email).strip().lower()
        department     = (payload.get("department") or req.department).strip()
        requested_role = payload.get("requested_role", req.requested_role)
        description    = (payload.get("description") or "").strip()
        new_attachment = None

    if not full_name or not email:
        return JsonResponse({
            "success": False,
            "detail": "必填欄位不完整"
        }, status=400)

    req.full_name      = full_name
    req.email          = email
    req.department     = department
    req.requested_role = requested_role
    req.description    = description
    req.status         = "Pending Team Leader"
    req.return_reason  = ""
    req.return_date    = None

    if new_attachment:
        req.attachment = new_attachment

    req.save()

    teams_pending_approval(
        request_type="Account Request",
        request_no=f"ACC-{req.id:04d}",
        applicant=req.username,
        required_role="Team Leader",
        current_status=req.status,
        action_path="/office-portal/accounts/",
        detail=f"{req.full_name} / {req.department} / Requested Role: {req.requested_role}",
    )

    return JsonResponse({
        "success": True,
        "detail": "申請已重新送出，等待 Team Leader 審核。"
    })


# ─────────────────────────────────────────────
# 5. 服務 / API / Hardware 申請（含檔案上傳，多階簽核）
# ─────────────────────────────────────────────

@login_required
def submit_application(request):
    """提交服務申請單（Form Data + 檔案）"""
    if request.method == "GET":
        return render(request, "office_portal/apply.html")

    a_name         = request.POST.get("a_name", "").strip()
    department     = request.POST.get("department", "").strip()
    a_purpose      = request.POST.get("a_purpose", "").strip()
    a_type         = request.POST.get("a_type", "").strip()
    service_system = ", ".join(request.POST.getlist("service_system"))
    description    = request.POST.get("description", "").strip()   # ← 新增
    attachment     = request.FILES.get("file")

    if not all([a_name, department, a_purpose, a_type]):
        messages.error(request, "請填寫所有必填欄位。")
        return redirect("portal_apply")

    app = Application.objects.create(
        a_name=a_name,
        department=department,
        a_purpose=a_purpose,
        a_type=a_type,
        service_system=service_system,
        description=description,
        attachment=attachment,
        status="Pending Team Leader",
    )
    
    _log_history(
    app,
    'submit',
    '',
    app.status,
    request.user,
    getattr(request.user, 'profile', None).role if getattr(request.user, 'profile', None) else 'user',
    'Applicant submitted service application'
    )
    
    teams_pending_approval(
        request_type="Service / API Application",
        request_no=app.f_no,
        applicant=app.a_name,
        required_role="Team Leader",
        current_status=app.status,
        action_path="/office-portal/applications/",
        detail=f"{app.a_type} / {app.department} / System: {app.service_system}",
    )

    messages.success(request, "申請已送出，等待 Team Leader 審核。")
    return redirect("portal_dashboard")


@login_required
@require_POST
def approve_application(request, app_id: int):
    """
    SOD 簽核（升級版）：
      Team Leader → Pending Team Leader → Pending Supervisor
      Supervisor  → Pending Supervisor  → Pending CIO
      CIO         → Pending CIO         → Work-in-progress
    """
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    item = get_object_or_404(Application, pk=app_id)

    # Team Leader Forward：轉交 Supervisor 審核
    if role == "team_leader" and item.status == "Pending Team Leader":
        old_status = item.status
        item.status = "Pending Supervisor"
        item.team_leader = request.user
        item.save()

        _log_history(item, 'approve', old_status, item.status, request.user, role)

        teams_pending_approval(
            request_type="Service / API Application",
            request_no=item.f_no,
            applicant=item.a_name,
            required_role="Supervisor",
            current_status=item.status,
            action_path="/office-portal/applications/",
            detail=f"{item.a_type} / {item.department} / System: {item.service_system}",
        )

        return JsonResponse({
            "success": True,
            "new_status": item.status,
            "progress": item.progress
        })

    elif role == "supervisor" and item.status == "Pending Supervisor":
        old_status = item.status
        item.status = "Pending CIO"
        item.save()

        _log_history(item, 'approve', old_status, item.status, request.user, role)

        teams_pending_approval(
            request_type="Service / API Application",
            request_no=item.f_no,
            applicant=item.a_name,
            required_role="CIO",
            current_status=item.status,
            action_path="/office-portal/applications/",
            detail=f"{item.a_type} / {item.department} / System: {item.service_system}",
        )

        return JsonResponse({
            "success": True,
            "new_status": item.status,
            "progress": item.progress
        })

    elif role == "cio" and item.status == "Pending CIO":
        old_status = item.status
        item.status = "Work-in-progress"
        item.save()

        _log_history(item, 'approve', old_status, item.status, request.user, role)

        teams_service_approved(
            item.f_no,
            item.a_name,
            item.a_type,
            item.service_system,
            applicant_email=_get_applicant_email(item.a_name)
        )

        teams_pending_approval(
            request_type="Service / API Application",
            request_no=item.f_no,
            applicant=item.a_name,
            required_role="CIO",
            current_status=item.status,
            action_path="/office-portal/applications/",
            detail="Approved. Pending service/account provisioning completion.",
        )

        return JsonResponse({
            "success": True,
            "new_status": item.status,
            "progress": item.progress
        })

    return JsonResponse({"success": False,
                         "detail": f"權限不足或狀態 {item.status} 不允許此操作"}, status=403)


@login_required
@require_POST
def reject_application(request, app_id: int):
    """
    SOD 退件：
    POST JSON：
      {
        "comment":   "退件原因（必填）",
        "action":    "return"  → 退件給申請人修改（預設）
                     "reject"  → 永久拒絕
        "return_to": "applicant"  → 退給申請人（status = Returned）
                     "supervisor" → 退給 Supervisor 重審（僅 CIO 可用）
      }
    """
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    item = get_object_or_404(Application, pk=app_id)

    if role == "team_leader" and item.status != "Pending Team Leader":
        return JsonResponse({
            "success": False,
            "detail": "Team Leader 只能退件 Pending Team Leader 狀態的申請"
        }, status=403)

    elif role == "supervisor" and item.status != "Pending Supervisor":
        return JsonResponse({
            "success": False,
            "detail": "Supervisor 只能退件 Pending Supervisor 狀態的申請"
        }, status=403)

    elif role == "cio" and item.status != "Pending CIO":
        return JsonResponse({
            "success": False,
            "detail": "CIO 只能退件 Pending CIO 狀態的申請"
        }, status=403)

    elif role not in ("team_leader", "supervisor", "cio"):
        return JsonResponse({
            "success": False,
            "detail": "權限不足"
        }, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"success": False, "detail": "Bad request"}, status=400)

    comment   = (payload.get("comment") or "").strip()
    action    = payload.get("action", "return")
    return_to = payload.get("return_to", "applicant")

    if not comment:
        return JsonResponse({"success": False, "detail": "退件原因不可空白"}, status=400)

    old_status = item.status

    # Team Leader 只能退件給申請人，不能永久拒絕
    if role == "team_leader":
        if action == "reject":
            return JsonResponse({
                "success": False,
                "detail": "Team Leader 不可永久拒絕申請，只能退件給申請人修改"
            }, status=403)

        item.status = "Returned"
        item.return_reason = comment
        item.return_date = timezone.now()
        item.save()

        _log_history(item, 'return', old_status, item.status, request.user, role, comment)

        return JsonResponse({
            "success": True,
            "new_status": item.status,
            "progress": item.progress
        })

    if action == "reject":
        # 永久拒絕
        item.status = "Rejected"
        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
        item.bookmark = (
            f"[{timestamp} Rejected by {role}] {comment}\n" + item.bookmark
        )
        item.save()
        _log_history(item, 'reject', old_status, item.status, request.user, role, comment)
        teams_service_rejected(item.f_no, item.a_name,
                               applicant_email=_get_applicant_email(item.a_name))
        return JsonResponse({"success": True, "new_status": item.status,
                             "progress": item.progress})

    # action == "return"
    if role == "supervisor":
        # Supervisor 只能退給申請人
        item.status        = "Returned"
        item.return_reason = comment
        item.return_date = timezone.now()
        item.save()
        _log_history(item, 'return', old_status, item.status, request.user, role, comment)
        return JsonResponse({"success": True, "new_status": item.status,
                             "progress": item.progress})

    elif role == "cio":
        if return_to == "supervisor":
            # CIO 退給 Supervisor：回到 Pending Supervisor，reason 寫入 bookmark
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
            item.status   = "Pending Supervisor"
            item.bookmark = (
                f"[{timestamp} Returned to Supervisor by CIO] {comment}\n" + item.bookmark
            )
            item.save()

            _log_history(item, 'return', old_status, item.status, request.user, role, comment)

            teams_pending_approval(
                request_type="Service / API Application",
                request_no=item.f_no,
                applicant=item.a_name,
                required_role="Supervisor",
                current_status=item.status,
                action_path="/office-portal/applications/",
                detail=f"Returned by CIO: {comment}",
            )

            return JsonResponse({
                "success": True,
                "new_status": item.status,
                "progress": item.progress
            })
        else:
            # CIO 退給申請人
            item.status        = "Returned"
            item.return_reason = comment
            item.return_date   = timezone.now()
            item.save()
            _log_history(item, 'return', old_status, item.status, request.user, role, comment)
            return JsonResponse({"success": True, "new_status": item.status,
                                 "progress": item.progress})


@login_required
def resubmit_application(request, app_id: int):
    """
    申請人將退件（Returned）的服務申請重新修改後送出。
    GET：顯示預填表單（含退件原因）
    POST：更新申請內容，狀態重置為 Pending Supervisor，清除 return_reason
    """
    item = get_object_or_404(Application, pk=app_id)

    if item.a_name != request.user.username:
        return JsonResponse({"success": False, "detail": "無法操作他人的申請"}, status=403)

    if item.status != "Returned":
        return JsonResponse({"success": False,
                             "detail": f"目前狀態 {item.status} 無法重新送出"}, status=400)

    if request.method == "GET":
        return render(request, "office_portal/apply.html", {
            "resubmit_app": item,
        })

    # ── POST：更新後重新送出 ──────────────────────────────────
    a_purpose      = request.POST.get("a_purpose", item.a_purpose).strip()
    a_type         = request.POST.get("a_type", item.a_type).strip()
    service_system = ", ".join(request.POST.getlist("service_system")) or item.service_system
    description    = request.POST.get("description", "").strip()
    new_attachment = request.FILES.get("file")

    old_status = item.status
    item.a_purpose      = a_purpose
    item.a_type         = a_type
    item.service_system = service_system
    item.description    = description
    item.status         = "Pending Team Leader"
    item.return_reason  = ""   # 清除退件原因
    item.return_date = None    # 清除退件時間
    
    if new_attachment:
        item.attachment = new_attachment
    item.save()

    _log_history(item, 'resubmit', old_status, item.status, request.user,
                 getattr(request.user, 'profile', None) and request.user.profile.role or 'user',
                 "Applicant resubmitted after revision")
    teams_pending_approval(
        request_type="Service / API Application",
        request_no=item.f_no,
        applicant=item.a_name,
        required_role="Team Leader",
        current_status=item.status,
        action_path="/office-portal/applications/",
        detail=f"{item.a_type} / {item.department} / System: {item.service_system}",
    )

    messages.success(request, "申請已重新送出，等待 Team Leader 審核。")
    return redirect("portal_dashboard")


@login_required
@require_POST
def preview_application(request, app_id: int):
    """Under-Preview：暫停審核，進入討論"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    item = get_object_or_404(Application, pk=app_id)

    if role == "team_leader" and item.status == "Pending Team Leader":
        item.preview_by = "Pending Team Leader"
    elif role == "supervisor" and item.status == "Pending Supervisor":
        item.preview_by = "Pending Supervisor"
    elif role == "cio" and item.status == "Pending CIO":
        item.preview_by = "Pending CIO"
    else:
        return JsonResponse({"success": False,
                             "detail": "權限不足或目前狀態無法設為 Under-Preview"}, status=403)

    old_status = item.status
    item.status = "Under-preview"

    comment = ""
    try:
        payload = json.loads(request.body.decode("utf-8"))
        comment = payload.get("comment", "")
    except Exception:
        pass

    if comment:
        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
        item.bookmark = (
            f"[{timestamp} {request.user.username}/{role}] {comment}\n" + item.bookmark
        )

    item.save()
    _log_history(item, 'preview', old_status, item.status, request.user, role, comment)
    return JsonResponse({
        "success": True,
        "new_status": f"Under-Preview ({role.title()})",
        "progress": item.progress,
    })


@login_required
@require_POST
def resume_application(request, app_id: int):
    """從 Under-Preview 恢復到原本的 Pending 狀態"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    item = get_object_or_404(Application, pk=app_id)

    if item.status != "Under-preview":
        return JsonResponse({"success": False,
                             "detail": "只有 Under-Preview 狀態才能 Resume"}, status=400)

    if item.preview_by == "Pending Team Leader" and role != "team_leader":
        return JsonResponse({
            "success": False,
            "detail": "此申請由 Team Leader 設為 Under-Preview"
        }, status=403)
    elif item.preview_by == "Pending Supervisor" and role != "supervisor":
        return JsonResponse({"success": False,
                             "detail": "此申請由 Supervisor 設為 Under-Preview"}, status=403)
    elif item.preview_by == "Pending CIO" and role != "cio":
        return JsonResponse({"success": False,
                             "detail": "此申請由 CIO 設為 Under-Preview"}, status=403)

    old_status = item.status
    item.status    = item.preview_by if item.preview_by else "Pending Supervisor"
    item.preview_by = ""
    item.save()
    _log_history(item, 'resume', old_status, item.status, request.user, role)
    return JsonResponse({"success": True, "new_status": item.status, "progress": item.progress})


@login_required
@require_POST
def complete_application(request, app_id: int):
    """CIO 確認外部系統帳號已開通，標記為 Request Completed"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if role != "cio":
        return JsonResponse({"success": False, "detail": "僅 CIO 可標記完成"}, status=403)

    item = get_object_or_404(Application, pk=app_id)

    if item.status != "Work-in-progress":
        return JsonResponse({"success": False,
                             "detail": f"目前狀態 {item.status} 無法標記完成"}, status=400)

    old_status = item.status
    item.status = "Request Completed"
    item.save()
    _log_history(item, 'complete', old_status, item.status, request.user, role)
    return JsonResponse({"success": True, "new_status": item.status, "progress": item.progress})


@login_required
@require_POST
def add_bookmark(request, app_id: int):
    """為申請單新增備註（Supervisor / CIO 可用）"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if role not in ("supervisor", "cio"):
        return JsonResponse({"success": False, "detail": "權限不足"}, status=403)

    item = get_object_or_404(Application, pk=app_id)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        comment = payload.get("comment", "").strip()
    except Exception:
        return JsonResponse({"success": False, "detail": "Bad request"}, status=400)

    if not comment:
        return JsonResponse({"success": False, "detail": "備註不可空白"}, status=400)

    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
    new_entry = f"[{timestamp} {request.user.username}/{role}] {comment}"
    item.bookmark = new_entry + "\n" + item.bookmark if item.bookmark else new_entry
    item.save()

    return JsonResponse({"success": True, "bookmark": item.bookmark})

@login_required
def application_list(request):
    """列出所有申請單"""

    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    # 🔍 Search keyword
    search = request.GET.get("search", "").strip()

    if role == "team_leader":
        apps = Application.objects.filter(
            Q(status="Pending Team Leader") |
            Q(status="Under-preview", preview_by="Pending Team Leader")
        )

    elif role == "supervisor":
        apps = Application.objects.filter(
            Q(status="Pending Supervisor") |
            Q(status="Under-preview", preview_by="Pending Supervisor")
        )

    elif role == "cio":
        apps = Application.objects.filter(
            Q(status="Pending CIO") |
            Q(status="Under-preview", preview_by="Pending CIO") |
            Q(status="Work-in-progress")
        )

    else:
        apps = Application.objects.filter(
            a_name=request.user.username
        )

    # 🔍 Search by Application Number
    if search:
        apps = apps.filter(
            f_no__icontains=search
        )

    # 📄 Pagination (20 per page)
    paginator = Paginator(
        apps.order_by("-created_at"),
        20
    )

    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "office_portal/application_list.html", {
        "applications": page_obj,
        "page_obj": page_obj,
        "search": search,
        "role": role,
    })

@login_required
def submit_hardware(request):
    if request.method == "GET":
        return render(request, "office_portal/hardware_apply.html")

    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if role == "user":
        initial_status = "Pending Team Leader"
    elif role == "team_leader":
        initial_status = "Pending Supervisor"
    elif role == "supervisor":
        initial_status = "Pending Hardware Supervisor"
    elif role == "hardware_supervisor":
        initial_status = "Work-in-progress"
    else:
        initial_status = "Pending Team Leader"

    req = HardwareRequest.objects.create(
        applicant=request.user,
        device_type=request.POST.get("device_type"),
        device_name=request.POST.get("device_name"),
        quantity=request.POST.get("quantity") or 1,
        purpose=request.POST.get("purpose"),
        description=request.POST.get("description"),
        attachment=request.FILES.get("file"),
        status=initial_status,
    )

    _log_hardware_history(
        req,
        'submit',
        '',
        req.status,
        request.user,
        role,
        'Applicant submitted hardware request'
    )

    if req.status == "Pending Team Leader":
        required_role = "Team Leader"
    elif req.status == "Pending Supervisor":
        required_role = "Supervisor"
    elif req.status == "Pending Hardware Supervisor":
        required_role = "Hardware Supervisor"
    else:
        required_role = "Hardware Supervisor"

    teams_pending_approval(
        request_type="Hardware Application",
        request_no=f"HW-{req.id:04d}",
        applicant=request.user.username,
        required_role=required_role,
        current_status=req.status,
        action_path="/office-portal/hardware/",
        detail=f"{req.device_type} / {req.device_name} / Quantity: {req.quantity}",
    )

    return redirect("hardware_list")


@login_required
def resubmit_hardware(request, req_id):
    """
    申請人將退件（Returned）的硬體申請重新修改後送出。
    GET：顯示預填表單（含退件原因）
    POST：更新申請內容，狀態重置為 Pending Team Leader，清除 return_reason / return_date
    """
    item = get_object_or_404(HardwareRequest, pk=req_id)

    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if item.applicant != request.user:
        return JsonResponse({
            "success": False,
            "detail": "無法操作他人的硬體申請"
        }, status=403)

    if item.status != "Returned":
        return JsonResponse({
            "success": False,
            "detail": f"目前狀態 {item.status} 無法重新送出"
        }, status=400)

    if request.method == "GET":
        return render(request, "office_portal/hardware_apply.html", {
            "resubmit_hw": item,
        })

    old_status = item.status

    item.device_type = request.POST.get("device_type", item.device_type)
    item.device_name = request.POST.get("device_name", item.device_name)
    item.quantity = request.POST.get("quantity") or item.quantity
    item.purpose = request.POST.get("purpose", item.purpose)
    item.description = request.POST.get("description", item.description)

    new_attachment = request.FILES.get("file")
    if new_attachment:
        item.attachment = new_attachment

    item.status = "Pending Team Leader"
    item.return_reason = ""
    item.return_date = None
    item.save()

    _log_hardware_history(
        item,
        'resubmit',
        old_status,
        item.status,
        request.user,
        role,
        'Applicant resubmitted hardware request after revision'
    )

    teams_pending_approval(
        request_type="Hardware Application",
        request_no=f"HW-{item.id:04d}",
        applicant=request.user.username,
        required_role="Team Leader",
        current_status=item.status,
        action_path="/office-portal/hardware/",
        detail=f"{item.device_type} / {item.device_name} / Quantity: {item.quantity}",
    )

    messages.success(request, "硬體申請已重新送出，等待 Team Leader 審核。")
    return redirect("hardware_list")


@login_required
@require_POST
def hardware_action(request, req_id):
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    item = get_object_or_404(HardwareRequest, pk=req_id)
    action = request.POST.get("action")

    old_status = item.status

    # ------------------------
    # Approve
    # ------------------------
    if action == "approve":

        if role == "team_leader" and item.status == "Pending Team Leader":
            item.status = "Pending Supervisor"

        elif role == "supervisor" and item.status == "Pending Supervisor":
            item.status = "Pending Hardware Supervisor"

        elif role == "hardware_supervisor" and item.status == "Pending Hardware Supervisor":
            item.status = "Work-in-progress"

        else:
            return JsonResponse({"success": False, "detail": "權限或狀態錯誤"}, status=403)

    # ------------------------
    # Review（進入 Under-preview）
    # ------------------------
    elif action == "preview":

        if role == "team_leader" and item.status == "Pending Team Leader":
            item.preview_by = "Pending Team Leader"

        elif role == "supervisor" and item.status == "Pending Supervisor":
            item.preview_by = "Pending Supervisor"

        elif role == "hardware_supervisor" and item.status == "Pending Hardware Supervisor":
            item.preview_by = "Pending Hardware Supervisor"

        else:
            return JsonResponse({"success": False, "detail": "權限錯誤"}, status=403)

        item.status = "Under-preview"

    # ------------------------
    # Resume（離開 preview）
    # ------------------------
    elif action == "resume":

        if item.preview_by == "Pending Team Leader" and role == "team_leader":
            item.status = "Pending Team Leader"

        elif item.preview_by == "Pending Supervisor" and role == "supervisor":
            item.status = "Pending Supervisor"

        elif item.preview_by == "Pending Hardware Supervisor" and role == "hardware_supervisor":
            item.status = "Pending Hardware Supervisor"

        else:
            return JsonResponse({"success": False, "detail": "不可 Resume"}, status=403)

        item.preview_by = ""

    # ------------------------
    # Return（退件）
    # ------------------------
    elif action == "return":

        if not (
            (role == "team_leader" and item.status == "Pending Team Leader") or
            (role == "supervisor" and item.status == "Pending Supervisor") or
            (role == "hardware_supervisor" and item.status == "Pending Hardware Supervisor")
        ):
            return JsonResponse({"success": False, "detail": "不可退件"}, status=403)

        item.status = "Returned"
        item.return_reason = request.POST.get("reason", "")
        item.return_date = timezone.now()

    # ------------------------
    # Reject（駁回）
    # ------------------------
    elif action == "reject":

        if not (
            (role == "supervisor" and item.status == "Pending Supervisor") or
            (role == "hardware_supervisor" and item.status == "Pending Hardware Supervisor")
        ):
            return JsonResponse({"success": False, "detail": "不可拒絕"}, status=403)

        reason = request.POST.get("reason", "").strip()
        if not reason:
            return JsonResponse({
                "success": False,
                "detail": "駁回原因不可空白"
            }, status=400)

        item.status = "Rejected"
        item.return_reason = request.POST.get("reason", "")

    # ------------------------
    # Complete（完成）
    # ------------------------
    elif action == "complete":

        if role == "hardware_supervisor" and item.status == "Work-in-progress":
            item.status = "Request Completed"
        else:
            return JsonResponse({"success": False, "detail": "不可完成"}, status=403)

    else:
        return JsonResponse({"success": False, "detail": "未知動作"}, status=400)

    item.save()

    comment = request.POST.get("reason", "") or request.POST.get("comment", "")

    _log_hardware_history(
        item,
        action,
        old_status,
        item.status,
        request.user,
        role,
        comment
    )

    # Hardware 轉交下一處理階段後，通知 ACReg Group
    if action == "approve":
        if item.status == "Pending Supervisor":
            required_role = "Supervisor"
        elif item.status == "Pending Hardware Supervisor":
            required_role = "Hardware Supervisor"
        elif item.status == "Work-in-progress":
            required_role = "Hardware Supervisor"
        else:
            required_role = ""

        if required_role:
            teams_pending_approval(
                request_type="Hardware Application",
                request_no=f"HW-{item.id:04d}",
                applicant=item.applicant.username,
                required_role=required_role,
                current_status=item.status,
                action_path="/office-portal/hardware/",
                detail=f"{item.device_type} / {item.device_name} / Quantity: {item.quantity}",
            )

    return JsonResponse({
        "success": True,
        "new_status": item.status
    })

@login_required
def hardware_list(request):
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    search = request.GET.get("search", "").strip()

    if role in ("team_leader", "supervisor", "hardware_supervisor"):
        items = HardwareRequest.objects.filter(
            Q(status="Pending Team Leader") |
            Q(status="Pending Supervisor") |
            Q(status="Pending Hardware Supervisor") |
            Q(status="Under-preview") |
            Q(status="Work-in-progress") |
            Q(status="Request Completed") |
            Q(status="Returned") |
            Q(status="Rejected")
        )
    else:
        items = HardwareRequest.objects.filter(
            applicant=request.user
        )

    if search:
        items = items.filter(
            Q(device_type__icontains=search) |
            Q(device_name__icontains=search) |
            Q(purpose__icontains=search) |
            Q(description__icontains=search) |
            Q(status__icontains=search)
        )

    paginator = Paginator(
        items.order_by("-created_at"),
        20
    )

    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "office_portal/hardware_list.html", {
        "items": page_obj,
        "page_obj": page_obj,
        "search": search,
        "role": role,
    })

# ─────────────────────────────────────────────
# 6. 公告管理
# ─────────────────────────────────────────────

@require_GET
def notice_list(request):
    notices = list(Notice.objects.filter(is_active=True).values(
        "id", "title", "content", "created_at"
    ))
    return JsonResponse({"notices": notices})


@login_required
def create_notice(request):
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"
    if role != "cio":
        return JsonResponse({"success": False, "detail": "僅 CIO 可發布公告"}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"success": False, "detail": "Bad request"}, status=400)

    title   = (payload.get("title") or "").strip()
    content = (payload.get("content") or "").strip()

    if not title or not content:
        return JsonResponse({"success": False, "detail": "標題與內容不可空白"}, status=400)

    Notice.objects.create(title=title, content=content, author=request.user)
    return JsonResponse({"success": True, "detail": "公告已發布"})


# ─────────────────────────────────────────────
# 7. 帳號設定
# ─────────────────────────────────────────────

@login_required
def settings_home(request):
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"
    return render(request, 'office_portal/settings.html', {"role": role, "profile": profile})


# ─────────────────────────────────────────────
# 8. ISMS 合規管理
# ─────────────────────────────────────────────

@login_required
def control_list(request):
    from .models import Domain
    domains = Domain.objects.prefetch_related('items').all()
    return render(request, 'compliance/control_list.html', {'domains': domains})


@login_required
def compliance_dashboard(request):
    return render(request, 'compliance/dashboard.html')


# ─────────────────────────────────────────────
# 9. Application Detail API（Modal 用）
# ─────────────────────────────────────────────

from django.http import JsonResponse

@login_required
def application_detail_api(request, app_id):
    """回傳單筆申請的完整資料 + 審核歷程（JSON）供 modal 顯示"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    app = get_object_or_404(Application, pk=app_id)
    
    # 申請人可看自己的；審核角色可看申請明細
    if app.a_name != request.user.username and role not in (
        "team_leader",
        "supervisor",
        "cio",
        "admin",
    ):
        return JsonResponse({"error": "Permission denied"}, status=403)

    history = []
    for h in app.approval_history.order_by('created_at'):
        history.append({
            "action":      h.get_action_display(),
            "from_status": h.from_status,
            "to_status":   h.to_status,
            "actor":       h.actor.username if h.actor else "—",
            "actor_role":  h.actor_role.title() if h.actor_role else "",
            "comment":     h.comment or "",
            "created_at":  h.created_at.strftime("%Y/%m/%d %H:%M") if h.created_at else "",
        })

    return JsonResponse({
        "id":            app.id,
        "f_no":          app.f_no,
        "a_name":        app.a_name,
        "department":    app.department,
        "a_type":        app.a_type,
        "service_system": app.service_system or "",
        "a_purpose":     app.a_purpose or "",
        "description":   app.description or "",
        "return_reason": app.return_reason or "",
        "attachment":    app.attachment.url if app.attachment else None,
        "status":        app.status,
        "created_at":    app.created_at.strftime("%Y/%m/%d %H:%M") if app.created_at else "",
        "history":       history,
    })
    
    
# ─────────────────────────────────────────────
# 10. Hardware Detail API（Modal 用）
# ─────────────────────────────────────────────

@login_required
def hardware_detail_api(request, req_id):
    """回傳單筆硬體申請完整資料 + 審核歷程，供 Hardware Detail Modal 使用。"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    item = get_object_or_404(HardwareRequest, pk=req_id)

    # 申請人可看自己的；審核角色可看硬體申請清單中的案件。
    if item.applicant != request.user and role not in (
        "team_leader",
        "supervisor",
        "hardware_supervisor",
        "cio",
        "admin",
    ):
        return JsonResponse({"error": "Permission denied"}, status=403)

    histories = HardwareApprovalHistory.objects.filter(
        hardware_request=item
    ).order_by("created_at")

    history_data = []
    for h in histories:
        history_data.append({
            "action": h.action or "",
            "from_status": h.from_status or "",
            "to_status": h.to_status or "",
            "actor": h.actor.username if h.actor else "—",
            "actor_role": h.actor_role or "",
            "comment": h.comment or "",
            "created_at": h.created_at.strftime("%Y/%m/%d %H:%M") if h.created_at else "",
        })

    return JsonResponse({
        "id": item.id,
        "device_type": item.device_type or "",
        "device_name": item.device_name or "",
        "quantity": item.quantity,
        "purpose": item.purpose or "",
        "description": item.description or "",
        "attachment": item.attachment.url if item.attachment else None,
        "status": item.status or "",
        "return_reason": item.return_reason or "",
        "return_date": item.return_date.strftime("%Y/%m/%d %H:%M") if item.return_date else "",
        "created_at": item.created_at.strftime("%Y/%m/%d %H:%M") if item.created_at else "",
        "updated_at": item.updated_at.strftime("%Y/%m/%d %H:%M") if getattr(item, "updated_at", None) else "",
        "applicant": item.applicant.username if item.applicant else "—",
        "history": history_data,
    })