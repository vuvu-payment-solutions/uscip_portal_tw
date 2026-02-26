from django.contrib import admin
# 從當前目錄的 models.py 匯入你寫的類別
from .models import ControlDomain, ControlItem, ComplianceEvidence

# 將它們註冊到後台
admin.site.register(ControlDomain)
admin.site.register(ControlItem)
admin.site.register(ComplianceEvidence)