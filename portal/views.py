"""
portal/views.py
================
從 FastAPI office_portal 移植至 Django 的完整視圖集合。
涵蓋：登入/登出/忘記密碼/重設密碼、帳號申請簽核、服務申請簽核、公告管理、Dashboard。
"""
import json
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from .models import AccountRequest, Application, Notice, UserProfile
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

    # 驗證
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

    # 修改密碼
    request.user.set_password(new_password1)
    request.user.save()

    # 更新 session，避免登出
    from django.contrib.auth import update_session_auth_hash
    update_session_auth_hash(request, request.user)

    messages.success(request, "✅ 密碼已成功修改！")
    return render(request, "office_portal/change_password.html")


@login_required
def portal_dashboard(request):
    """儀表板：依角色顯示不同資料"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    context = {
        "role": role,
        "notices": Notice.objects.filter(is_active=True)[:5],
        # 所有人都能看到自己的帳號申請紀錄
        "my_account_requests": AccountRequest.objects.filter(
            username=request.user.username
        ).order_by("-created_at"),
        # 所有人都能看到自己的服務申請紀錄
        "my_applications": Application.objects.filter(
            a_name=request.user.username
        ).order_by("-created_at"),
    }

    if role in ("supervisor", "admin"):
        context["pending_accounts"] = AccountRequest.objects.filter(status="Pending Supervisor")
        context["pending_apps"]     = Application.objects.filter(status="Pending Supervisor")
    elif role == "cio":
        context["pending_accounts"] = AccountRequest.objects.filter(status="Pending CIO")
        context["pending_apps"]     = Application.objects.filter(status="Pending CIO")

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

    token = secrets.token_urlsafe(32)
    request.session["pw_reset_token"] = token
    request.session["pw_reset_email"] = email
    request.session["pw_reset_time"]  = timezone.now().isoformat()

    reset_link = f"{settings.APP_BASE_URL}/office-portal/reset/{token}/"
    email_password_reset(email, reset_link)

    messages.success(request, "若此信箱存在，重設連結已送出。")
    return redirect("portal_home")


def portal_reset(request, token: str):
    if request.session.get("pw_reset_token") != token:
        return render(request, "office_portal/reset_invalid.html")

    if request.method == "GET":
        return render(request, "office_portal/reset.html", {"token": token})

    new_password = request.POST.get("password") or ""
    if len(new_password) < 8:
        messages.error(request, "密碼至少需要 8 個字元。")
        return redirect("portal_reset", token=token)

    email = request.session.get("pw_reset_email")
    if not email:
        return render(request, "office_portal/reset_invalid.html")

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        return render(request, "office_portal/reset_invalid.html")

    user.set_password(new_password)
    user.save()

    for key in ("pw_reset_token", "pw_reset_email", "pw_reset_time"):
        request.session.pop(key, None)

    messages.success(request, "密碼重設成功，請重新登入。")
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
    """
    兩階簽核帳號申請：
      - Supervisor → Pending CIO
      - CIO        → Approved（自動建立 Django User）
    """
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if role not in ("supervisor", "cio", "admin"):
        return JsonResponse({"success": False, "detail": "權限不足"}, status=403)

    req = get_object_or_404(AccountRequest, pk=req_id)

    if role in ("supervisor", "admin") and req.status == "Pending Supervisor":
        req.status = "Pending CIO"
        req.save()
        teams_account_pending_cio(req.username, req.full_name)
        return JsonResponse({"success": True, "new_status": req.status})

    elif role in ("cio", "admin") and req.status == "Pending CIO":
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
            )
            print(f"[ACCOUNT CREATED] {req.username} / 初始密碼: {initial_password}")

        teams_account_approved(req.username, req.full_name)
        return JsonResponse({"success": True, "new_status": req.status})

    return JsonResponse({"success": False, "detail": f"目前狀態 {req.status} 不允許此操作"}, status=400)


@login_required
def reject_account(request, req_id: int):
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"
    if role not in ("supervisor", "cio", "admin"):
        return JsonResponse({"success": False, "detail": "權限不足"}, status=403)

    req = get_object_or_404(AccountRequest, pk=req_id)
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
# 4. 服務 / API 申請（含檔案上傳，兩階簽核）
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
    service_system = request.POST.get("service_system", "").strip()
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
    """兩階簽核服務申請"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if role not in ("supervisor", "cio", "admin"):
        return JsonResponse({"success": False, "detail": "權限不足"}, status=403)

    item = get_object_or_404(Application, pk=app_id)

    if role in ("supervisor", "admin") and item.status == "Pending Supervisor":
        item.status = "Pending CIO"
        item.save()
        teams_service_pending_cio(item.f_no, item.a_name, item.a_type, item.service_system)
        return JsonResponse({"success": True, "new_status": item.status})
    elif role in ("cio", "admin") and item.status == "Pending CIO":
        item.status = "Approved"
        item.save()
        teams_service_approved(item.f_no, item.a_name, item.a_type, item.service_system)
        return JsonResponse({"success": True, "new_status": item.status})
    else:
        return JsonResponse({"success": False, "detail": f"目前狀態 {item.status} 不允許此操作"}, status=400)


@login_required
def reject_application(request, app_id: int):
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"
    if role not in ("supervisor", "cio", "admin"):
        return JsonResponse({"success": False, "detail": "權限不足"}, status=403)

    item = get_object_or_404(Application, pk=app_id)
    item.status = "Rejected"
    item.save()
    teams_service_rejected(item.f_no, item.a_name)
    return JsonResponse({"success": True, "new_status": item.status})


@login_required
def application_list(request):
    """列出所有申請單（管理員/主管用）"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"

    if role in ("supervisor", "cio", "admin"):
        apps = Application.objects.all()
    else:
        # 一般使用者只看自己的（以 a_name 比對，實務上應改為 ForeignKey）
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
    """發布公告（CIO / Admin 限定）"""
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else "user"
    if role not in ("cio", "admin"):
        return JsonResponse({"success": False, "detail": "僅 CIO / Admin 可發布公告"}, status=403)

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