from django.db import models
from django.contrib.auth.models import User

class ControlDomain(models.Model):
    """ISO 27001 控制域 (例如: A.5 資訊安全政策, A.9 存取控制)"""
    code = models.CharField(max_length=10, unique=True) # 例如: A.9
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

class ControlItem(models.Model):
    """具體控制項 (例如: A.9.1.1 存取控制政策)"""
    domain = models.ForeignKey(ControlDomain, on_delete=models.CASCADE, related_name='items')
    item_code = models.CharField(max_length=20, unique=True) # 例如: A.9.1.1
    title = models.CharField(max_length=255)
    specification = models.TextField(help_text="ISO 條文規範要求")
    implementation_guidance = models.TextField(help_text="公司內部實作指南")
    
    # 風險等級，用於威脅建模權重
    RISK_CHOICES = [('H', 'High'), ('M', 'Medium'), ('L', 'Low')]
    risk_level = models.CharField(max_length=1, choices=RISK_CHOICES, default='M')

    def __str__(self):
        return f"{self.item_code} {self.title}"

class ComplianceEvidence(models.Model):
    """
    證據收集 (這部分是自動化的核心)
    初期可以手動錄入，後期串接 AWS API 自動產生
    """
    control_item = models.ForeignKey(ControlItem, on_delete=models.CASCADE, related_name='evidences')
    collected_at = models.DateTimeField(auto_now_add=True)
    provider = models.CharField(max_length=100, help_text="來源: 如 AWS Config, IAM Script, 或 Manual")
    
    # 存儲證據內容 (JSON 格式最彈性，方便存儲 AWS API 回傳結果)
    evidence_data = models.JSONField() 
    
    status = models.BooleanField(default=False, help_text="是否合規")
    remark = models.TextField(blank=True)

    class Meta:
        ordering = ['-collected_at']

class AuditReport(models.Model):
    """自動生成的稽核報告紀錄"""
    report_title = models.CharField(max_length=255)
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    pdf_file = models.FileField(upload_to='compliance_reports/', blank=True, null=True)
    
    # 紀錄產出時的統計數據
    total_controls = models.IntegerField()
    passed_controls = models.IntegerField()

    def __str__(self):
        return f"Report {self.report_title} - {self.generated_at.date()}"