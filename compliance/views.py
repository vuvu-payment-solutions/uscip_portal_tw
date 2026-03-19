import io
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import render
from docx import Document
from .models import ControlDomain, ControlItem, ComplianceEvidence

# =================================================================
# ISMS 合規業務邏輯 (ISO 27001:2022)
# =================================================================

@login_required
def compliance_dashboard(request):
    """
    ISMS 合規儀表板：計算各控制域的合規率並渲染 Dashboard (您的截圖頁面)
    """
    # 使用 prefetch_related 優化查詢，避免 N+1 問題
    domains = ControlDomain.objects.prefetch_related('items__evidences').all()
    
    domain_stats = []
    total_compliant_count = 0
    
    for domain in domains:
        items = list(domain.items.all())
        total = len(items)
        # 檢查該控制項是否有證據，且最新狀態為 True (合規)
        compliant = sum(
            1 for item in items 
            if (ev := item.evidences.first()) and ev.status
        )
        total_compliant_count += compliant
        
        domain_stats.append({
            "domain": domain,
            "total": total,
            "compliant": compliant,
            "rate": round(compliant / total * 100, 1) if total else 0,
        })

    context = {
        "domain_stats": domain_stats,
        "total_domains": domains.count(),
        "total_controls": ControlItem.objects.count(),
        "total_compliant": total_compliant_count,
    }
    return render(request, "compliance/dashboard.html", context)

@login_required
def control_list(request):
    """
    列出所有 93 項控制項及其詳細狀態 (對應您的 control_list.html)
    """
    domains = ControlDomain.objects.prefetch_related('items__evidences').all()
    return render(request, "compliance/control_list.html", {"domains": domains})

@login_required
def export_report_docx(request):
    """
    匯出 ISO 27001 合規狀態 Word 報告
    """
    doc = Document()
    doc.add_heading('USCIP - ISO 27001:2022 Compliance Report', 0)

    table = doc.add_table(rows=1, cols=4)
    table.style = 'Table Grid'
    headers = ['控制項 ID', '標題', '風險等級', '合規狀態']
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h

    # 抓取所有控制項進行匯出
    for item in ControlItem.objects.select_related('domain').all():
        latest_ev = item.evidences.first()
        row = table.add_row().cells
        row[0].text = item.item_code
        row[1].text = item.title
        row[2].text = item.get_risk_level_display()
        row[3].text = "Compliant" if latest_ev and latest_ev.status else "Pending"

    f = io.BytesIO()
    doc.save(f)
    f.seek(0)

    response = HttpResponse(
        f.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = 'attachment; filename=USCIP_Compliance_Report.docx'
    return response