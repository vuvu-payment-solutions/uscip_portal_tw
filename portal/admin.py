from django.contrib import admin
from .models import AccountRequest, Application, Notice, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ("user", "role", "department", "full_name")
    list_filter   = ("role",)
    search_fields = ("user__username", "full_name", "department")


@admin.register(AccountRequest)
class AccountRequestAdmin(admin.ModelAdmin):
    list_display  = ("username", "full_name", "email", "department", "requested_role", "status", "created_at")
    list_filter   = ("status", "requested_role")
    search_fields = ("username", "full_name", "email")
    readonly_fields = ("created_at", "updated_at")
    actions       = ["mark_pending_cio", "mark_approved", "mark_rejected"]

    @admin.action(description="送交 CIO 審核")
    def mark_pending_cio(self, request, queryset):
        queryset.filter(status="Pending Supervisor").update(status="Pending CIO")

    @admin.action(description="批准選取申請")
    def mark_approved(self, request, queryset):
        queryset.update(status="Approved")

    @admin.action(description="拒絕選取申請")
    def mark_rejected(self, request, queryset):
        queryset.update(status="Rejected")


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display  = ("f_no", "a_name", "department", "a_type", "service_system", "status", "created_at")
    list_filter   = ("status", "a_type")
    search_fields = ("f_no", "a_name", "department", "service_system")
    readonly_fields = ("f_no", "created_at", "updated_at")


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display  = ("title", "author", "is_active", "created_at")
    list_filter   = ("is_active",)
    search_fields = ("title", "content")