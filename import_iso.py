import os
import django
import json

# 1. 告訴 Python 你的 Django 設定在哪裡
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'uscip_project.settings')
django.setup()

from compliance.models import ControlDomain, ControlItem

def seed_data_from_json():
    json_path = 'iso27001_2022_controls.json'
    
    if not os.path.exists(json_path):
        print(f"❌ 找不到檔案: {json_path}")
        return

    print(f"🚀 開始從 {json_path} 匯入 93 項 ISO 27001:2022 核心條文...")

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    iso_data = data.get('iso_27001_2022', {})

    for domain_code, info in iso_data.items():
        # A. 建立或更新領域 (Domain)
        domain, created = ControlDomain.objects.update_or_create(
            code=domain_code,
            defaults={'name': info['domain']}
        )
        status = "新增" if created else "更新"
        print(f"  - {status} 領域: {domain_code} {info['domain']}")

        # B. 建立或更新該領域下的所有控制項 (Items)
        for ctrl in info['controls']:
            item, it_created = ControlItem.objects.update_or_create(
                item_code=ctrl['id'],
                defaults={
                    'domain': domain,
                    'title': ctrl['title'],
                    'specification': ctrl['description'],
                    'risk_level': 'M' # 預設為中風險
                }
            )
    
    print("\n✅ 全數 93 項控制項已同步至 Django 總部資料庫！")

if __name__ == '__main__':
    seed_data_from_json()