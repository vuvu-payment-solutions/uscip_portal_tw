"""
compliance/views.py
====================
ISMS 合規業務邏輯：
  - 控制項清單
  - 合規狀態查詢
  - DOCX 報告匯出
注意：登入/登出/Portal 相關 views 已移至 portal/views.py
"""
import io

from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import render
from docx import Document

from .models import ControlDomain, ControlItem, ComplianceEvidence


@login_required
def compliance_dashboard(request):
    """ISMS 合規儀表板：各控制域合規狀態概覽"""
    domains = ControlDomain.objects.prefetch_related('items__evidences').all()

    domain_stats = []
    for domain in domains:
        items     = list(domain.items.all())
        total     = len(items)
        compliant = sum(
            1 for item in items
            if (ev := item.evidences.first()) and ev.status
        )
        domain_stats.append({
            "domain":    domain,
            "total":     total,
            "compliant": compliant,
            "rate":      round(compliant / total * 100, 1) if total else 0,
        })

    return render(request, "compliance/dashboard.html", {
        "domain_stats": domain_stats,
    })


@login_required
def control_item_list(request):
    """列出所有控制項及其最新合規狀態"""
    domains = ControlDomain.objects.prefetch_related('items__evidences').all()
    return render(request, "compliance/control_list.html", {"domains": domains})


@login_required
@permission_required('compliance.view_controlitem', raise_exception=True)
def export_report_docx(request):
    """匯出 ISO 27001 合規狀態 Word 報告"""
    doc = Document()
    doc.add_heading('USCIP - ISO 27001:2022 Compliance Report', 0)

    table      = doc.add_table(rows=1, cols=4)
    table.style = 'Table Grid'
    headers    = ['控制項 ID', 'Title', '風險等級', '合規狀態']
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h

    for item in ControlItem.objects.select_related('domain').all():
        latest_ev = item.evidences.first()
        row = table.add_row().cells
        row[0].text = item.item_code
        row[1].text = item.title
        row[2].text = item.get_risk_level_display()
        row[3].text = "Compliant" if latest_ev and latest_ev.status else "Non-Compliant / Pending"

    f = io.BytesIO()
    doc.save(f)
    f.seek(0)

    response = HttpResponse(
        f.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = 'attachment; filename=USCIP_Compliance_Report.docx'
    return response