# USCIP 合併專案 — 快速啟動指南

## 目錄結構

```
uscip_project/          ← Django 主設定
portal/                 ← Office Portal（帳號申請、服務申請、公告）★新增
compliance/             ← ISMS（ISO 27001 控制項、合規報告）★已清理
templates/
  office_portal/        ← Portal 前端模板（原位不動）
  compliance/           ← ISMS 前端模板
media/                  ← 上傳檔案（application 附件）
```

---

## 首次啟動步驟

```bash
# 1. 安裝相依套件
pip install django djangorestframework python-docx Pillow

# 2. 執行 migrations（portal app 是新的，需建立表）
python manage.py makemigrations portal
python manage.py makemigrations compliance
python manage.py migrate

# 3. 匯入 ISO 27001 條文
python import_iso.py

# 4. 建立超級管理員
python manage.py createsuperuser

# 5. 啟動開發伺服器
python manage.py runserver
```

---

## URL 路由總覽

| 路徑 | 功能 |
|------|------|
| `/admin/` | Django 後台 |
| `/office-portal/` | 員工入口首頁（登入頁） |
| `/office-portal/dashboard/` | 儀表板（依角色顯示） |
| `/office-portal/register/` | 帳號申請（自助） |
| `/office-portal/apply/` | 服務申請（需登入） |
| `/office-portal/applications/` | 申請單列表 |
| `/office-portal/notices/` | 公告 JSON API |
| `/office-portal/approve-account/<id>/` | 帳號簽核（POST） |
| `/office-portal/approve-application/<id>/` | 服務簽核（POST） |
| `/compliance/` | ISMS 儀表板 |
| `/compliance/controls/` | 控制項清單 |
| `/compliance/export/docx/` | 下載合規報告 |

---

## 移植說明（FastAPI → Django）

| FastAPI | Django 對應 |
|---------|------------|
| SQLAlchemy `AccountRequest` | `portal.models.AccountRequest` |
| SQLAlchemy `Application` | `portal.models.Application` |
| SQLAlchemy `Notice` | `portal.models.Notice` |
| SQLAlchemy `User` + `role` | Django `User` + `portal.models.UserProfile` |
| `POST /register` | `portal_register` view |
| `POST /approve-account/{id}` | `approve_account` view |
| `POST /approve-service/{id}` | `approve_application` view |
| `GET /notices` | `notice_list` view (JSON) |
| `POST /notices` | `create_notice` view |
| `POST /apply` (multipart) | `submit_application` view |

---

## 角色對應

| 角色 | 可執行操作 |
|------|-----------|
| `user` | 申請帳號、提交服務申請、查看公告 |
| `supervisor` | 第一關簽核（Pending Supervisor → Pending CIO） |
| `cio` | 第二關簽核（Pending CIO → Approved，自動建立 User） |
| `admin` | 等同 supervisor + cio，全權操作 |

---

## 待辦事項

- [ ] 實作真實寄信功能（替換 `portal_forgot` 的 `print` 語句）
- [ ] 建立 `templates/office_portal/register.html`（帳號申請表單）
- [ ] 建立 `templates/office_portal/apply.html`（服務申請表單）
- [ ] 建立 `templates/office_portal/application_list.html`（申請單列表）
- [ ] 建立 `templates/compliance/dashboard.html`（ISMS 儀表板）
- [ ] 生產環境：切換 DB 為 MySQL / PostgreSQL（透過環境變數）
- [ ] 生產環境：設定 `SECRET_KEY` 環境變數
