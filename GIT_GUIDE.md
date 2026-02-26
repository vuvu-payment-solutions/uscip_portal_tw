# USCIP Portal Git 操作手冊

## 分支架構

```
main        ← 正式環境（穩定版本，不直接 commit）
develop     ← 開發整合（日常開發在這裡）
release     ← 準備上線前的測試版本
hotfix/xxx  ← 緊急修復正式環境的 bug
feature/xxx ← 新功能開發
```

---

## 日常開發流程

### 1. 開始新功能

```bash
# 確保 develop 是最新的
git checkout develop
git pull origin develop

# 建立新功能分支
git checkout -b feature/功能名稱
# 例如：git checkout -b feature/change-password
```

### 2. 開發中儲存進度

```bash
git add .
git commit -m "feat: 新增修改密碼功能"
```

### 3. 功能完成，合併回 develop

```bash
git checkout develop
git merge feature/功能名稱
git push origin develop

# 刪除已完成的 feature 分支（選擇性）
git branch -d feature/功能名稱
```

---

## 準備上線流程

```bash
# 從 develop 建立 release 分支
git checkout develop
git checkout -b release/v1.0.0

# 測試沒問題後合併到 main
git checkout main
git merge release/v1.0.0
git tag -a v1.0.0 -m "版本 1.0.0 正式上線"
git push origin main --tags

# 同步回 develop
git checkout develop
git merge release/v1.0.0
git push origin develop
```

---

## 緊急修復流程（Hotfix）

```bash
# 從 main 建立 hotfix 分支
git checkout main
git checkout -b hotfix/修復說明
# 例如：git checkout -b hotfix/login-bug

# 修復完成後合併到 main 和 develop
git checkout main
git merge hotfix/修復說明
git push origin main

git checkout develop
git merge hotfix/修復說明
git push origin develop

# 刪除 hotfix 分支
git branch -d hotfix/修復說明
```

---

## 常用指令速查

| 指令 | 說明 |
|------|------|
| `git status` | 查看目前狀態 |
| `git log --oneline` | 查看 commit 歷史 |
| `git branch` | 查看本地分支 |
| `git branch -a` | 查看所有分支（含遠端） |
| `git checkout 分支名` | 切換分支 |
| `git pull origin develop` | 拉取最新程式碼 |
| `git push origin develop` | 推送到遠端 |
| `git diff` | 查看未暫存的變更 |
| `git stash` | 暫存目前變更（切換分支用） |
| `git stash pop` | 還原暫存的變更 |

---

## Commit 訊息規範

```
feat:     新功能
fix:      修復 bug
docs:     文件更新
style:    格式調整（不影響功能）
refactor: 重構程式碼
test:     測試相關
chore:    雜項（套件更新等）
```

範例：
```bash
git commit -m "feat: 新增服務申請 Teams 通知"
git commit -m "fix: 修復 dashboard 申請單不消失問題"
git commit -m "docs: 更新 README"
```

---

## 遠端 Repository

```
GitHub: https://github.com/Quilterintl/uscip_portal
```

---

## 下一步：換 MySQL 資料庫

目前使用 SQLite（開發用），正式部署前需換成 MySQL：

1. 建立新分支：`git checkout -b feature/mysql-migration`
2. 修改 `settings.py` 和 `.env`
3. 測試完成後合併回 `develop`
