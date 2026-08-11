from django.contrib import admin
from .models import AccountRequest, Application, Notice, UserProfile, BYODRequest, SoftwareRequest, SoftwareApprovalHistory


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ("user", "role", "is_hardware_supervisor", "department", "full_name")
    list_filter   = ("role", "is_hardware_supervisor")
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
    
    
@admin.register(BYODRequest)
class BYODRequestAdmin(admin.ModelAdmin):
    list_display = (
        "request_no",
        "applicant",
        "department",
        "device_type",
        "device_name",
        "storage_capability",
        "status",
        "created_at",
    )
    list_filter = (
        "status",
        "device_type",
        "storage_capability",
        "created_at",
    )
    search_fields = (
        "request_no",
        "applicant__username",
        "department",
        "device_name",
        "brand",
        "model",
        "serial_number",
        "mac_address",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "approved_at",
        "retired_at",
    )
    

@admin.register(SoftwareRequest)
class SoftwareRequestAdmin(admin.ModelAdmin):
    list_display = (
        "request_no",
        "software_name",
        "software_version",
        "vendor",
        "applicant",
        "department",
        "request_type",
        "license_type",
        "data_level",
        "status",
        "created_at",
    )
    list_filter = (
        "status",
        "request_type",
        "license_type",
        "data_level",
        "internet_access_required",
        "admin_privilege_required",
    )
    search_fields = (
        "request_no",
        "software_name",
        "software_version",
        "vendor",
        "applicant__username",
        "department",
        "business_purpose",
    )
    readonly_fields = (
        "request_no",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)
    list_per_page = 50


@admin.register(SoftwareApprovalHistory)
class SoftwareApprovalHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "software_request",
        "action",
        "from_status",
        "to_status",
        "actor",
        "actor_role",
        "created_at",
    )
    list_filter = (
        "action",
        "actor_role",
        "created_at",
    )
    search_fields = (
        "software_request__request_no",
        "software_request__software_name",
        "actor__username",
        "comment",
    )
    readonly_fields = (
        "created_at",
    )
    ordering = ("-created_at",)
    list_per_page = 50