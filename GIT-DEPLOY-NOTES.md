# Git & Deploy Workflow (Internal Notes)

> File này là note nội bộ (runbook): update UI → commit/push (repo thống nhất) → deploy Vercel.

---

## 0. Tổng quan

| Đích | Thư mục / File | Chạy ở đâu |
|---|---|---|
| **Local hub** | `birdeye_ui.py` (+ `server.sh`) | `http://127.0.0.1:8765/` (landing) & `/test` (console) |
| **Vercel** | `deploy-vercel/` | `https://birdeye-data-skills.vercel.app` |

**UI dùng chung 1 nguồn duy nhất:** `deploy-vercel/public/`
- `birdeye_ui.py` serve thư mục này cho local (landing `/`, console `/test`).
- Vercel serve cùng thư mục này khi deploy (static + serverless `deploy-vercel/api/`).
- → Không còn bước copy/sync giữa 2 bên. Sửa 1 lần là cả local lẫn Vercel đổi theo.

Routes:
- `/` → `deploy-vercel/public/index.html` (landing page: skill cards + setup guide)
- `/test` → `deploy-vercel/public/test.html` (test console / "deploy screen")
- `/detail` → `deploy-vercel/public/detail.html` (per-skill drill view)
- Vercel dùng `cleanUrls: true` để `/test` phục vụ `test.html` và `/detail` phục vụ `detail.html`.

---

## 1. Git — chuẩn bị 1 lần

**Account / identity để commit:**
- GitHub account: `TheNang2710`
- Author name: `nguyenthenang` · Email commit: `nguyenthenang89@gmail.com` → phải verify trong GitHub → *Settings → Emails*.

**Set identity cho repo (1 lần):**
```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills
git config user.name  "nguyenthenang"
git config user.email "nguyenthenang89@gmail.com"
```

**Cấu trúc repo:**
- **Git repo root**: `/Users/nguyenthenang/nang/birdeye/app/skills/` (MỘT project thống nhất)
- **Remote**: `https://github.com/TheNang2710/birdeye-data-skills.git` (branch `main`)
- **Tracked files** (được commit lên GitHub):
  - `deploy-vercel/` ← Vercel app + UI dùng chung (`public/`, `api/`, `vercel.json`) — mục tiêu chính
  - `birdeye_ui.py`, `server.sh` ← local server + control script
  - `birdeye-screener/` ← CLI engine
  - `docs/`, `API/`, `workflow/` ← docs
  - `README.md`, `.gitignore`

**Credential GitHub:** dùng **Personal Access Token (classic)**, scope `repo` (tạo tại https://github.com/settings/tokens). Khi `git push` hỏi: username = `TheNang2710`, password = dán token `ghp_...`. (macOS lưu sẵn qua `osxkeychain` → thường không hỏi lại.)

---

## 2. Bảo mật & file không commit

`.git/info/exclude` **đã reset** (KHÔNG còn pattern `*`) → mọi file trong workspace đều track được.
Chỉ chặn secrets qua `.gitignore`:
```
.env
node_modules/
__pycache__/
.vercel/
.DS_Store
```
> `lr_params.json` (tham số ML đã train) **ĐƯỢC push** lên repo public theo yêu cầu.
> `.git/info/exclude` là file local, KHÔNG được track → không push lên GitHub.

---

## 3. Update UI / code

UI là 1 nguồn duy nhất: **sửa trực tiếp trong `deploy-vercel/public/`** (không cần copy sang đâu).

```bash
# 1. sửa deploy-vercel/public/<file> (index.html / test.html / hub.js / hub.css ...)
# 2. preview local (tự restart khi file đổi)
./server.sh watch            # → http://127.0.0.1:8765/  (landing) và /test (console)
# hoặc: ./server.sh restart  |  ./server.sh status
```

> Port **8765** = server duy nhất (`birdeye_ui.py`). Không còn 8899.
> `birdeye_ui.py` serve UI từ `deploy-vercel/public/` cho cả `/` và `/test`.

> ⚠️ Bump `?v=N` khi sửa `hub.js`/`hub.css` để vượt cache trình duyệt.

---

## 4. Commit + push (repo thống nhất)

```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills
git status                       # xem thay đổi
git add -A
git commit -m "<scope>: <mô tả>"
git push origin main
```

---

## 5. Deploy Vercel

```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills/deploy-vercel
npx vercel --prod          # deploy production
```
**Kiểm tra sau deploy:**
```bash
npx vercel curl /api/meta --deployment https://birdeye-data-skills.vercel.app
# mong đợi: "ml_ready": true, "cli_ready": true
```

**Cấu hình Vercel app:**
- **Project:** `birdeye-data-skills` · **Team:** `the-nang` · alias `https://birdeye-data-skills.vercel.app`
- Link qua `deploy-vercel/.vercel/project.json`.
- `vercel.json` **BẮT BUỘC** có `"framework": null` (preset "Other"); nếu không, build fail `PYTHON_ENTRYPOINT_NOT_FOUND` vì có nhiều function (`api/run.py`, `api/meta.py`).
- `"cleanUrls": true` để `/test` phục vụ `test.html`.
- Static output dir = `public/`. ML runtime ở `api/_ml/` (prefix `_` = không bị route); `includeFiles: "api/**"`.
- Key: local dùng env server; Vercel dùng **BYOK** (nhập key trên UI, lưu `localStorage`), ghi cache vào `/tmp/birdeye`.

### (Tùy chọn) Vercel auto-deploy qua GitHub
Vercel → project `birdeye-data-skills` → **Git → Connect** → account `TheNang2710` → repo `birdeye-data-skills`.
> **Root Directory = `deploy-vercel/`** (bắt buộc khi connect GitHub).

---

## 6. Checklist nhanh mỗi lần update
```bash
# 1) sửa UI trong deploy-vercel/public/
# 2) preview local
./server.sh restart          # http://127.0.0.1:8765/  và  /test
# 3) push (repo thống nhất)
git add -A && git commit -m "..." && git push origin main
# 4) redeploy Vercel
cd deploy-vercel && npx vercel --prod
```

---

## 7. Troubleshooting

- **Sửa author của commit đã push**: `git commit --amend --author="nguyenthenang <nguyenthenang89@gmail.com>"` → cần `git push --force-with-lease origin main` (force-push ghi đè lịch sử — chỉ làm khi remote không có commit khác của người khác).
- **`git push` bị reject (non-fast-forward)**: remote có commit mới → `git pull --rebase origin main` rồi push lại. Nếu working tree có thay đổi chưa commit, `git stash push -m wip -- <paths>` trước, xong `git stash pop`.
- **Build Vercel fail `PYTHON_ENTRYPOINT_NOT_FOUND`**: thiếu `"framework": null` trong `deploy-vercel/vercel.json`.
- **`/test` trả 404 trên Vercel**: thiếu `"cleanUrls": true` trong `vercel.json`, hoặc file `public/test.html` chưa được deploy.
- **Deployment Protection chặn curl**: dùng `npx vercel curl /path --deployment <url>` (qua CLI, có auth).
