"""
portal/views.py
================
USCIP Office Portal — 完整視圖集合
涵蓋：登入/登出/忘記密碼/重設密碼、帳號申請簽核、服務申請簽核、公告管理、Dashboard。

權限矩陣（SOD 職責分離）：
  Pending Supervisor        → Supervisor only
  Under-Preview (Supervisor)→ Supervisor only (Resume)
  Pending CIO               → CIO only
  Under-Preview (CIO)       → CIO only (Resume)
  Work-in-progress          → CIO only (Complete)
  Admin 角色已移除，不參與簽核流程
"""
import json
import secrets

from compliance.models import ControlDomain
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import AccountRequest, Application, Notice, UserProfile, PasswordResetToken
from .services.notify import (
    teams_new_account_request,
    teams_account_pending_cio,
    teams_account_approved,
    teams_account_rejected,
    teams_new_service_application,
    teams_service_pending_cio,
    teams_service_approved,
    teams_service_rejected,
    email_password_reset,
)


# ─────────────────────────────────────────────
# 1. 入口 / 認證
# ─────────────────────────────────────────────

@ensure_csrf_cookie
def index(request):
    return render(request, 'index.html')


def portal_home(request):
    """首頁（登入頁）"""
    notices = Notice.objects.filter(is_active=True)[:5]
    return render(request, "office_portal/index.html", {"notices": notices})


@require_POST
def portal_login(request):
    """AJAX 登入，回傳 JSON"""
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
    return JsonResponse({
        "success": True,
        "username": user.username,
        "role": role_str,
    })


def portal_logout(request):
    logout(request)
    return redirect("portal_home")


@login_required
def change_password(request):
    """修改密碼"""
    if request.method == "GET":
        return render(request, "office_portal/change_password.html")

    old_password = request.POST.get("old_password", "").strip()
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
    """編輯個人資料"""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "GET":
        return render(request, "office_portal/edit_profile.html", {"profile": profile})

    full_name  = request.POST.get("full_name", "").strip()
    department = request.POST.get("department", "").strip()
    email      = request.POST.get("email", "").strip()

    if not full_name or not email:
        messages.error(request, "Name and email are required.")
        return render(request, "office_portal/edit_profile.html", {"profile": profile})

    profile.full_name = full_name
    profile.department = department
    profile.save()

    request.user.email = email
    request.user.first_name = full_name
    request.user.save()

    messages.success(request, "✅ Profile updated successfully!")
    return render(request, "office_portal/edit_profile.html", {"profile": profile})


@login_required
def portal_dashboard(request):
    """儀表板：依角色顯示不同資料"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    # ISMS domain stats
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

    # Force password change on first login
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
        "my_applications": Application.objects.filter(
            a_name=request.user.username
        ).order_by("-created_at"),
    }

    # ── SOD：每個角色只看到自己負責的申請 ──
    if role == "cio":
        context["pending_accounts"] = AccountRequest.objects.filter(status="Pending CIO")
        context["pending_apps"] = Application.objects.filter(
            Q(status="Pending CIO") |
            Q(status="Work-in-progress") |
            Q(status="Under-preview", preview_by="Pending CIO")
        )
    elif role == "supervisor":
        context["pending_accounts"] = AccountRequest.objects.filter(status="Pending Supervisor")
        context["pending_apps"] = Application.objects.filter(
            Q(status="Pending Supervisor") |
            Q(status="Under-preview", preview_by="Pending Supervisor")
        )
    # user / team_leader 不參與簽核，不顯示 pending 區塊

    return render(request, "office_portal/dashboard.html", context)


# ─────────────────────────────────────────────
# 2. 忘記密碼 / 重設密碼
# ─────────────────────────────────────────────

def portal_forgot(request):
    if request.method == "GET":
        return render(request, "office_portal/forgot.html")

    email = (request.POST.get("email") or "").strip().lower()
    if not email:
        messages.error(request, "請輸入電子信箱。")
        return redirect("portal_forgot")

    # 不論 email 是否存在都顯示相同訊息（防列舉攻擊）
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
    """重設密碼頁面 — 從 DB 驗證 token"""
    try:
        reset_obj = PasswordResetToken.objects.get(token=token)
    except PasswordResetToken.DoesNotExist:
        return render(request, "office_portal/reset_invalid.html")

    if not reset_obj.is_valid():
        return render(request, "office_portal/reset_invalid.html")

    if request.method == "GET":
        return render(request, "office_portal/reset.html", {"token": token})

    new_password = request.POST.get("password") or ""
    if len(new_password) < 8:
        messages.error(request, "密碼至少需要 8 個字元。")
        return redirect("portal_reset", token=token)

    user = reset_obj.user
    user.set_password(new_password)
    user.save()

    reset_obj.used = True
    reset_obj.save()

    messages.success(request, "✅ 密碼已重設成功，請用新密碼登入。")
    return redirect("portal_home")


# ─────────────────────────────────────────────
# 3. 帳號申請（自助註冊 → 兩階簽核 → 建立 Django User）
# ─────────────────────────────────────────────

def portal_register(request):
    """使用者自助申請帳號"""
    if request.method == "GET":
        return render(request, "office_portal/register.html")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"success": False, "detail": "Bad request"}, status=400)

    username       = (payload.get("username") or "").strip()
    full_name      = (payload.get("full_name") or "").strip()
    email          = (payload.get("email") or "").strip().lower()
    department     = (payload.get("department") or "").strip()
    requested_role = payload.get("requested_role", "user")

    if not all([username, full_name, email]):
        return JsonResponse({"success": False, "detail": "必填欄位不完整"}, status=400)

    if User.objects.filter(username=username).exists() or \
       AccountRequest.objects.filter(username=username).exists():
        return JsonResponse({"success": False, "detail": "帳號名稱已被使用或審核中"}, status=400)

    AccountRequest.objects.create(
        username=username,
        full_name=full_name,
        email=email,
        department=department,
        requested_role=requested_role,
        status="Pending Supervisor",
    )
    teams_new_account_request(username, full_name, department, requested_role)
    return JsonResponse({"success": True, "detail": "申請已送出，等待主管審核。"})


@login_required
def approve_account(request, req_id: int):
    """帳號申請簽核（SOD）"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if role not in ("supervisor", "cio"):
        return JsonResponse({"success": False, "detail": "權限不足"}, status=403)

    req = get_object_or_404(AccountRequest, pk=req_id)

    # Supervisor 只能操作 Pending Supervisor
    if role == "supervisor" and req.status == "Pending Supervisor":
        req.status = "Pending CIO"
        req.save()
        teams_account_pending_cio(req.username, req.full_name)
        return JsonResponse({"success": True, "new_status": req.status})

    # CIO 只能操作 Pending CIO
    elif role == "cio" and req.status == "Pending CIO":
        req.status = "Approved"
        req.save()

        if not User.objects.filter(username=req.username).exists():
            initial_password = f"{req.username}@Init2024"
            new_user = User.objects.create_user(
                username=req.username,
                email=req.email,
                password=initial_password,
                first_name=req.full_name,
            )
            UserProfile.objects.create(
                user=new_user,
                role=req.requested_role,
                full_name=req.full_name,
                department=req.department,
                must_change_pw=True,
            )
            print(f"[ACCOUNT CREATED] {req.username} / 初始密碼: {initial_password}")

        teams_account_approved(req.username, req.full_name)
        return JsonResponse({"success": True, "new_status": req.status})

    return JsonResponse({"success": False, "detail": f"權限不足或狀態 {req.status} 不允許此操作"}, status=403)


@login_required
def reject_account(request, req_id: int):
    """帳號申請退件（SOD）"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if role not in ("supervisor", "cio"):
        return JsonResponse({"success": False, "detail": "權限不足"}, status=403)

    req = get_object_or_404(AccountRequest, pk=req_id)

    if role == "supervisor" and req.status != "Pending Supervisor":
        return JsonResponse({"success": False, "detail": "Supervisor 只能退件 Pending Supervisor 狀態"}, status=403)
    elif role == "cio" and req.status != "Pending CIO":
        return JsonResponse({"success": False, "detail": "CIO 只能退件 Pending CIO 狀態"}, status=403)

    comment = ""
    try:
        payload = json.loads(request.body.decode("utf-8"))
        comment = payload.get("comment", "")
    except Exception:
        pass

    req.status  = "Rejected"
    req.comment = comment
    req.save()
    teams_account_rejected(req.username, req.full_name, comment)
    return JsonResponse({"success": True, "new_status": req.status})


# ─────────────────────────────────────────────
# 4. 服務 / API 申請（含檔案上傳，多階簽核）
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
        attachment=attachment,
        status="Pending Supervisor",
    )
    teams_new_service_application(app.f_no, a_name, a_type, service_system)
    messages.success(request, "申請已送出，等待主管審核。")
    return redirect("portal_dashboard")


@login_required
def approve_application(request, app_id: int):
    """
    SOD 簽核：
      Supervisor → Pending Supervisor → Pending CIO
      CIO       → Pending CIO       → Work-in-progress
    """
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    item = get_object_or_404(Application, pk=app_id)

    if role == "supervisor" and item.status == "Pending Supervisor":
        item.status = "Pending CIO"
        item.save()
        teams_service_pending_cio(item.f_no, item.a_name, item.a_type, item.service_system)
        return JsonResponse({"success": True, "new_status": item.status, "progress": item.progress})

    elif role == "cio" and item.status == "Pending CIO":
        item.status = "Work-in-progress"
        item.save()
        teams_service_approved(item.f_no, item.a_name, item.a_type, item.service_system)
        return JsonResponse({"success": True, "new_status": item.status, "progress": item.progress})

    else:
        return JsonResponse({"success": False, "detail": f"權限不足或狀態 {item.status} 不允許此操作"}, status=403)


@login_required
def reject_application(request, app_id: int):
    """
    SOD 退件：
      Supervisor 只能退 Pending Supervisor
      CIO 只能退 Pending CIO
    """
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    item = get_object_or_404(Application, pk=app_id)

    if role == "supervisor" and item.status != "Pending Supervisor":
        return JsonResponse({"success": False, "detail": "Supervisor 只能退件 Pending Supervisor 狀態的申請"}, status=403)
    elif role == "cio" and item.status != "Pending CIO":
        return JsonResponse({"success": False, "detail": "CIO 只能退件 Pending CIO 狀態的申請"}, status=403)
    elif role not in ("supervisor", "cio"):
        return JsonResponse({"success": False, "detail": "權限不足"}, status=403)

    comment = ""
    try:
        payload = json.loads(request.body.decode("utf-8"))
        comment = payload.get("comment", "")
    except Exception:
        pass

    item.status = "Rejected"
    if comment:
        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
        item.bookmark = f"[{timestamp} Rejected by {role}] {comment}\n" + item.bookmark
    item.save()
    teams_service_rejected(item.f_no, item.a_name)
    return JsonResponse({"success": True, "new_status": item.status, "progress": item.progress})


@login_required
def preview_application(request, app_id: int):
    """
    Under-Preview：暫停審核，進入討論
    SOD：Supervisor 只能操作 Pending Supervisor，CIO 只能操作 Pending CIO
    """
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    item = get_object_or_404(Application, pk=app_id)

    if role == "supervisor" and item.status == "Pending Supervisor":
        item.preview_by = "Pending Supervisor"
    elif role == "cio" and item.status == "Pending CIO":
        item.preview_by = "Pending CIO"
    else:
        return JsonResponse({"success": False, "detail": "權限不足或目前狀態無法設為 Under-Preview"}, status=403)

    item.status = "Under-preview"

    comment = ""
    try:
        payload = json.loads(request.body.decode("utf-8"))
        comment = payload.get("comment", "")
    except Exception:
        pass

    if comment:
        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
        item.bookmark = f"[{timestamp} {request.user.username}/{role}] {comment}\n" + item.bookmark

    item.save()
    return JsonResponse({
        "success": True,
        "new_status": f"Under-Preview ({role.title()})",
        "progress": item.progress,
    })


@login_required
def resume_application(request, app_id: int):
    """
    從 Under-Preview 恢復到原本的 Pending 狀態
    只有原本設定 Under-Preview 的角色可以 Resume
    """
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    item = get_object_or_404(Application, pk=app_id)

    if item.status != "Under-preview":
        return JsonResponse({"success": False, "detail": "只有 Under-Preview 狀態才能 Resume"}, status=400)

    if item.preview_by == "Pending Supervisor" and role != "supervisor":
        return JsonResponse({"success": False, "detail": "此申請由 Supervisor 設為 Under-Preview，只有 Supervisor 可以 Resume"}, status=403)
    elif item.preview_by == "Pending CIO" and role != "cio":
        return JsonResponse({"success": False, "detail": "此申請由 CIO 設為 Under-Preview，只有 CIO 可以 Resume"}, status=403)

    item.status = item.preview_by if item.preview_by else "Pending Supervisor"
    item.preview_by = ""
    item.save()
    return JsonResponse({
        "success": True,
        "new_status": item.status,
        "progress": item.progress,
    })


@login_required
def complete_application(request, app_id: int):
    """CIO 確認外部系統帳號已開通，標記為 Request Completed"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if role != "cio":
        return JsonResponse({"success": False, "detail": "僅 CIO 可標記完成"}, status=403)

    item = get_object_or_404(Application, pk=app_id)

    if item.status != "Work-in-progress":
        return JsonResponse({"success": False, "detail": f"目前狀態 {item.status} 無法標記完成"}, status=400)

    item.status = "Request Completed"
    item.save()
    return JsonResponse({
        "success": True,
        "new_status": item.status,
        "progress": item.progress,
    })


@login_required
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

    if role in ("supervisor", "cio"):
        apps = Application.objects.all()
    else:
        apps = Application.objects.filter(a_name=request.user.username)

    return render(request, "office_portal/application_list.html", {
        "applications": apps,
        "role": role,
    })


# ─────────────────────────────────────────────
# 5. 公告管理
# ─────────────────────────────────────────────

@require_GET
def notice_list(request):
    """公告列表（JSON API，供前端 fetch）"""
    notices = list(Notice.objects.filter(is_active=True).values(
        "id", "title", "content", "created_at"
    ))
    return JsonResponse({"notices": notices})


@login_required
def create_notice(request):
    """發布公告（僅 CIO）"""
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
# 6. 帳號設定
# ─────────────────────────────────────────────

@login_required
def settings_home(request):
    """帳號設定首頁"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    context = {
        "role": role,
        "profile": profile,
    }
    return render(request, 'office_portal/settings.html', context)


# ─────────────────────────────────────────────
# 7. ISMS 合規管理
# ─────────────────────────────────────────────

@login_required
def control_list(request):
    """顯示 ISO 27001:2022 控制項清單"""
    from .models import Domain
    domains = Domain.objects.prefetch_related('items').all()

    return render(request, 'compliance/control_list.html', {
        'domains': domains,
    })


@login_required
def compliance_dashboard(request):
    """渲染 ISMS Compliance Dashboard"""
    return render(request, 'compliance/dashboard.html')