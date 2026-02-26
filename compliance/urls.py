from django.urls import path
from . import views

urlpatterns = [
    path("",              views.compliance_dashboard, name="compliance_dashboard"),
    path("controls/",     views.control_item_list,    name="compliance_controls"),
    path("export/docx/",  views.export_report_docx,   name="compliance_export_docx"),
]