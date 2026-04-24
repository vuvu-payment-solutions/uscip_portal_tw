"""
Migration: Add description, attachment, return_reason to AccountRequest & Application;
           Add Returned status; Add return/resubmit to ApprovalHistory ACTION_CHOICES.

Place this file in portal/migrations/ as the next sequential migration.
Filename example: 0004_return_fields.py  (adjust prefix to match your current latest)

Run:
    python manage.py migrate
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    # ⚠ 請將 dependencies 的 '0003_...' 改成你目前最新的 migration 名稱
    dependencies = [
        ('portal', '0006_alter_userprofile_role'),
    ]

    operations = [

        # ── AccountRequest 新增欄位 ──────────────────────────────────
        migrations.AddField(
            model_name='accountrequest',
            name='description',
            field=models.TextField(blank=True, verbose_name='申請說明'),
        ),
        migrations.AddField(
            model_name='accountrequest',
            name='attachment',
            field=models.FileField(
                blank=True, null=True,
                upload_to='account_requests/',
                verbose_name='附件',
            ),
        ),
        migrations.AddField(
            model_name='accountrequest',
            name='return_reason',
            field=models.TextField(blank=True, verbose_name='退件原因'),
        ),
        # STATUS_CHOICES 是純 Python list，Django 不需要 migration 來新增選項值，
        # 但欄位 max_length 已有足夠空間（30），無需更改。

        # ── Application 新增欄位 ────────────────────────────────────
        migrations.AddField(
            model_name='application',
            name='description',
            field=models.TextField(blank=True, verbose_name='申請說明'),
        ),
        migrations.AddField(
            model_name='application',
            name='return_reason',
            field=models.TextField(blank=True, verbose_name='退件原因'),
        ),
        # ApprovalHistory.action CharField max_length=20 已足夠容納 'resubmit'，無需更改。
    ]
