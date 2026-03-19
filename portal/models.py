from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    """
    擴充 Django 內建 User，加入 role / department 欄位
    （對應 FastAPI office_portal 的 User model）
    """
    ROLE_CHOICES = [
        ('user',       'User'),
        ('supervisor', 'Supervisor'),
        ('cio',        'CIO'),
        ('admin',      'Admin'),
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
    帳號申請單：Pending Supervisor → Pending CIO → Approved / Rejected
    """
    STATUS_CHOICES = [
        ('Pending Supervisor', 'Pending Supervisor'),
        ('Pending CIO',        'Pending CIO'),
        ('Approved',           'Approved'),
        ('Rejected',           'Rejected'),
    ]
    ROLE_CHOICES = [
        ('user',       'User'),
        ('supervisor', 'Supervisor'),
        ('cio',        'CIO'),
    ]

    username       = models.CharField(max_length=50, unique=True)
    full_name      = models.CharField(max_length=50)
    email          = models.EmailField(max_length=100)
    department     = models.CharField(max_length=50, blank=True)
    requested_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')
    status         = models.CharField(max_length=30, choices=STATUS_CHOICES, default='Pending Supervisor')
    comment        = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '帳號申請'
        verbose_name_plural = '帳號申請列表'

    def __str__(self):
        return f"{self.username} [{self.status}]"


class Application(models.Model):
    """
    服務/API 申請單（含檔案上傳），兩階簽核流程
    """
    STATUS_CHOICES = [
        ('Pending Supervisor', 'Pending Supervisor'),
        ('Pending CIO',        'Pending CIO'),
        ('Approved',           'Approved'),
        ('Rejected',           'Rejected'),
    ]

    f_no           = models.CharField(max_length=50, unique=True, blank=True)
    a_name         = models.CharField(max_length=50, verbose_name='申請人')
    department     = models.CharField(max_length=50, verbose_name='部門')
    a_purpose      = models.TextField(verbose_name='申請目的')
    a_type         = models.CharField(max_length=50, verbose_name='申請類型')
    service_system = models.CharField(max_length=100, blank=True, verbose_name='服務系統')
    status         = models.CharField(max_length=30, choices=STATUS_CHOICES, default='Pending Supervisor')
    attachment     = models.FileField(upload_to='applications/', blank=True, null=True, verbose_name='附件')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '服務申請'
        verbose_name_plural = '服務申請列表'

    def save(self, *args, **kwargs):
        """自動產生 f_no，格式：APP-0001"""
        if not self.f_no:
            last = Application.objects.order_by('-id').first()
            next_id = (last.id + 1) if last else 1
            self.f_no = f"APP-{str(next_id).zfill(4)}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.f_no} - {self.a_name} [{self.status}]"


class Notice(models.Model):
    """公告（對應 FastAPI notice model）"""
    title      = models.CharField(max_length=200, verbose_name='標題')
    content    = models.TextField(verbose_name='內容')
    author     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='發布人')
    is_active  = models.BooleanField(default=True, verbose_name='顯示中')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '公告'
        verbose_name_plural = '公告列表'

    def __str__(self):
        return self.title