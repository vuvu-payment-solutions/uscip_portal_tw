from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('user',       'User'),
        ('team_leader', 'Team Leader'),
        ('supervisor', 'Supervisor'),
        ('hardware_supervisor', 'Hardware Supervisor'),
        ('cio',        'CIO'),
    ]
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role       = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')
    full_name  = models.CharField(max_length=50, blank=True)
    department = models.CharField(max_length=50, blank=True)
    must_change_pw = models.BooleanField(default=True, verbose_name='Must change password')

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class AccountRequest(models.Model):
    """
    帳號申請單：
    Pending Team Leader → Pending Supervisor → Pending CIO → Approved
    Under-preview = 目前審核階段待討論，完成討論後可 Resume 回原階段
    Returned = 退件給申請人修改後重新上呈
    Rejected = 終止申請流程
    """
    
    STATUS_CHOICES = [
        ('Pending Team Leader', 'Pending Team Leader'),
        ('Pending Supervisor', 'Pending Supervisor'),
        ('Pending CIO',        'Pending CIO'),
        ('Under-preview',       'Under-preview'),        
        ('Approved',           'Approved'),
        ('Rejected',           'Rejected'),
        ('Returned',           'Returned'),
    ]
    ROLE_CHOICES = [
        ('user',       'User'),
        ('team_leader', 'Team Leader'),
        ('supervisor', 'Supervisor'),
        ('cio',        'CIO'),
    ]

    username       = models.CharField(max_length=50, unique=True)
    full_name      = models.CharField(max_length=50)
    email          = models.EmailField(max_length=100)
    department     = models.CharField(max_length=50, blank=True)
    requested_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')
    
    team_leader    = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tl_requests'
    )
    
    # ── 新增欄位 ─────────────────────────────────────────
    description    = models.TextField(blank=True, verbose_name='申請說明')
    attachment     = models.FileField(upload_to='account_requests/', blank=True, null=True,
                                      verbose_name='附件')
    return_reason  = models.TextField(blank=True, verbose_name='退件原因')
    return_date    = models.DateTimeField(null=True, blank=True, verbose_name='退件日期')
    preview_by     = models.CharField(
        max_length=30,
        blank=True,
        default='',
        verbose_name='Under-preview 設定者角色'
    )
    
    # ────────────────────────────────────────────────────
    status         = models.CharField(max_length=30, choices=STATUS_CHOICES,
                                      default='Pending Team Leader')
    comment        = models.CharField(max_length=255, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '帳號申請'
        verbose_name_plural = '帳號申請列表'

    def __str__(self):
        return f"{self.username} [{self.status}]"

class HardwareRequest(models.Model):

    STATUS_CHOICES = [
        ('Pending Team Leader', 'Pending Team Leader'),
        ('Pending Supervisor', 'Pending Supervisor'),
        ('Pending Hardware Supervisor', 'Pending Hardware Supervisor'),
        ('Under-preview', 'Under-preview'),
        ('Work-in-progress', 'Work-in-progress'),
        ('Request Completed', 'Request Completed'),
        ('Rejected', 'Rejected'),
        ('Returned', 'Returned'),
    ]

    applicant = models.ForeignKey(User, on_delete=models.CASCADE)

    device_type = models.CharField(max_length=100)
    device_name = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=1)

    purpose = models.TextField()
    description = models.TextField(blank=True)
    attachment = models.FileField(upload_to='hardware/', null=True, blank=True)

    team_leader = models.ForeignKey(User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='hw_tl')

    supervisor = models.ForeignKey(User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='hw_sp')

    hardware_supervisor = models.ForeignKey(User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='hw_hs')

    preview_by = models.CharField(max_length=50, blank=True)

    return_reason = models.TextField(blank=True)
    
    return_date = models.DateTimeField(null=True, blank=True, verbose_name='退件日期')

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default='Pending Team Leader'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.applicant} - {self.device_type} [{self.status}]"

class HardwareApprovalHistory(models.Model):
    ACTION_CHOICES = [
        ('submit', 'Submit'),
        ('approve', 'Approve'),
        ('reject', 'Reject'),
        ('return', 'Return'),
        ('resubmit', 'Resubmit'),
        ('preview', 'Under-Preview'),
        ('resume', 'Resume'),
        ('complete', 'Complete'),
    ]

    hardware_request = models.ForeignKey(
        HardwareRequest,
        on_delete=models.CASCADE,
        related_name='approval_history'
    )

    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    from_status = models.CharField(max_length=50, blank=True, default='')
    to_status = models.CharField(max_length=50, blank=True, default='')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    actor_role = models.CharField(max_length=30, blank=True, default='')
    comment = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '硬體申請審核歷程'
        verbose_name_plural = '硬體申請審核歷程列表'

    def __str__(self):
        return (
            f"HW-{self.hardware_request.id} | {self.action} "
            f"by {self.actor} ({self.from_status} → {self.to_status})"
        )

class Application(models.Model):
    """
    服務/API 申請單（含檔案上傳），多階簽核流程
    Returned = 退件給申請人修改後重新上呈
    """
    STATUS_CHOICES = [
        ('Under-preview',     'Under-preview'),
        ('Pending Team Leader', 'Pending Team Leader'),
        ('Pending Supervisor', 'Pending Supervisor'),
        ('Pending CIO',        'Pending CIO'),
        ('Work-in-progress',   'Work-in-progress'),
        ('Request Completed',  'Request Completed'),
        ('Rejected',           'Rejected'),
        ('Returned',           'Returned'),   # ← 新增
    ]

    TYPE_CHOICES = [
        ('API access',    'API Access'),
        ('System access', 'System Access'),
        ('Data access',   'Data Access'),
        ('Other',         'Other (System Function / Process Change)'),
    ]

    f_no           = models.CharField(max_length=50, unique=True, blank=True)
    a_name         = models.CharField(max_length=50, verbose_name='申請人')
    department     = models.CharField(max_length=50, verbose_name='部門')
    a_purpose      = models.TextField(verbose_name='申請目的')
    a_type         = models.CharField(max_length=50, choices=TYPE_CHOICES, verbose_name='申請類型')
    service_system = models.CharField(max_length=100, blank=True, verbose_name='服務系統')
    status         = models.CharField(max_length=30, choices=STATUS_CHOICES,
                                      default='Pending Team Leader')
    attachment     = models.FileField(upload_to='applications/', blank=True, null=True,
                                      verbose_name='附件')
    
    team_leader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="application_tl_requests"
    )
    
    # ── 新增欄位 ─────────────────────────────────────────
    description    = models.TextField(blank=True, verbose_name='申請說明')
    return_reason  = models.TextField(blank=True, verbose_name='退件原因')
    return_date = models.DateTimeField(null=True, blank=True, verbose_name='退件日期')
    
    # ────────────────────────────────────────────────────
    bookmark       = models.TextField(blank=True, default='', verbose_name='Bookmark (審核備註)')
    preview_by     = models.CharField(max_length=30, blank=True, default='',
                                      verbose_name='Under-preview 設定者角色')
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '服務申請'
        verbose_name_plural = '服務申請列表'

    def save(self, *args, **kwargs):
        if not self.f_no:
            last = Application.objects.order_by('-id').first()
            next_id = (last.id + 1) if last else 1
            self.f_no = f"APP-{str(next_id).zfill(4)}"
        super().save(*args, **kwargs)

    @property
    def progress(self):
        mapping = {
            'Pending Team Leader': 10,
            'Under-preview':      15,
            'Pending Supervisor':  25,
            'Pending CIO':         50,
            'Work-in-progress':    75,
            'Request Completed':  100,
            'Rejected':             0,
            'Returned':            10,   # 退件等修改中
            'Approved':           100,
        }
        return mapping.get(self.status, 0)

    @property
    def progress_color(self):
        mapping = {
            'Pending Team Leader': 'bg-yellow-300',
            'Under-preview':      'bg-yellow-400',
            'Pending Supervisor':  'bg-blue-400',
            'Pending CIO':         'bg-blue-500',
            'Work-in-progress':    'bg-indigo-500',
            'Request Completed':   'bg-emerald-500',
            'Rejected':            'bg-red-500',
            'Returned':            'bg-orange-400',
            'Approved':            'bg-emerald-500',
        }
        return mapping.get(self.status, 'bg-gray-400')

    def __str__(self):
        return f"{self.f_no} - {self.a_name} [{self.status}]"


class ApprovalHistory(models.Model):
    """審核歷程紀錄：每次狀態變更自動寫入一筆"""
    ACTION_CHOICES = [
        ('submit',   'Submit'),
        ('approve',  'Approve'),
        ('reject',   'Reject'),
        ('return',   'Return'),    # ← 新增：退件給申請人
        ('resubmit', 'Resubmit'), # ← 新增：申請人重新送出
        ('preview',  'Under-Preview'),
        ('resume',   'Resume'),
        ('complete', 'Complete'),
        ('bookmark', 'Bookmark'),
    ]

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='approval_history'
    )
    action      = models.CharField(max_length=20, choices=ACTION_CHOICES)
    from_status = models.CharField(max_length=30, blank=True, default='')
    to_status   = models.CharField(max_length=30, blank=True, default='')
    actor       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    actor_role  = models.CharField(max_length=20, blank=True, default='')
    comment     = models.TextField(blank=True, default='')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '審核歷程'
        verbose_name_plural = '審核歷程列表'

    def __str__(self):
        return (
            f"{self.application.f_no} | {self.action} "
            f"by {self.actor} ({self.from_status} → {self.to_status})"
        )

class Notice(models.Model):
    title      = models.CharField(max_length=200, verbose_name='標題')
    content    = models.TextField(verbose_name='內容')
    author     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name='發布人')
    is_active  = models.BooleanField(default=True, verbose_name='顯示中')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '公告'
        verbose_name_plural = '公告列表'

    def __str__(self):
        return self.title


class PasswordResetToken(models.Model):
    user    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reset_tokens')
    token   = models.CharField(max_length=128, unique=True, db_index=True)
    created = models.DateTimeField(auto_now_add=True)
    used    = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created']

    def is_valid(self):
        from django.utils import timezone
        import datetime
        return (
            not self.used
            and (timezone.now() - self.created) < datetime.timedelta(minutes=30)
        )

    def __str__(self):
        return f"Reset for {self.user.username} ({'used' if self.used else 'active'})"