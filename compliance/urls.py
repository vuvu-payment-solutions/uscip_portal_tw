from django.urls import path
from . import views

urlpatterns = [
    # 首頁儀表板
    path('', views.compliance_dashboard, name='compliance_home'),
    
    # 93 項控制項清單
    path('controls/', views.control_list, name='compliance_controls'),
    
    # 匯出報告
    path('export/docx/', views.export_report_docx, name='compliance_export_docx'),
]