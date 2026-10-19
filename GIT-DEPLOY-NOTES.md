# Git & Deploy Workflow (Internal Notes)

> File này là note nội bộ, NẰM NGOÀI `deploy/` → **không bao giờ bị commit** lên GitHub public repo.
> Tổng quan runbook: update code → commit/push (app tĩnh) → deploy Vercel.

---

## 0. Tổng quan 2 đích deploy

| Đích | Thư mục | Server / Host | Git |
|---|---|---|---|
| **App tĩnh** | `deploy/` | `deploy/server.py` @ `127.0.0.1:8899` | ROOT repo `birdeye-data-skills` |
| **Vercel** | `deploy-vercel/` | `https://skills-olive-rho.vercel.app` | repo riêng (chưa có remote) |

UI dùng chung: `deploy/index.html` ↔ `deploy-vercel/public/index.html` (giữ nội dung giống nhau).

---

## 1. Git — chuẩn bị 1 lần

**Account / identity để commit:**
- GitHub account: `TheNang2710`
- Email commit: `nguyenthenang89@gmail.com` → phải verify trong GitHub → *Settings → Emails*.

**Set identity cho repo (nên làm, 1 lần):**
```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills
git config user.name  "nguyenthenang"
git config user.email "nguyenthenang89@gmail.com"
```
> Không muốn đổi config? Commit bằng cờ tạm:
> `git -c user.name=nguyenthenang -c user.email=nguyenthenang89@gmail.com commit -m "..."`

**Cấu trúc repo:**
- **Git repo root**: `/Users/nguyenthenang/nang/birdeye/app/skills/`
- **Remote**: `https://github.com/TheNang2710/birdeye-data-skills.git` (branch `main`)
- **Public tracked files** (được commit lên GitHub):
  - `deploy/` ← app test console (port 8899) — mục tiêu chính để commit
  - `birdeye-screener/` ← CLI engine
  - `docs/` ← workflow docs
  - `README.md`, `.gitignore`

**Credential GitHub:** dùng **Personal Access Token (classic)**, scope `repo` (tạo tại https://github.com/settings/tokens). Khi `git push` hỏi: username = `TheNang2710`, password = dán token `ghp_...`. (macOS lưu sẵn qua `osxkeychain` → thường không hỏi lại.)

---

## 2. Cách ẩn file workspace thừa

`.git/info/exclude` chứa:
```
# Local workspace isolation
*
!.gitignore
```
→ Chỉ các file **đã tracked** (`deploy/`, `birdeye-screener/`, `docs/`, `README.md`) mới hiện trong `git status`. Mọi file khác (assets, workflow, `*.md` thừa, file note này, `deploy-vercel/`) đều bị ẩn.

> **Lưu ý**: `.git/info/exclude` là file local, KHÔNG được track → không push lên GitHub.

---

## 3. Update code

**Sửa UI console** — chỉ sửa 1 file gốc rồi đồng bộ sang Vercel (bắt buộc để 2 bên giống nhau):
```bash
# 1. sửa deploy/index.html
# 2. đồng bộ sang Vercel console
cp deploy/index.html deploy-vercel/public/index.html
```

**Preview local (port 8899)** — tự restart khi file đổi:
```bash
./server.sh watch public        # → http://127.0.0.1:8899
# hoặc: ./server.sh restart public   |   ./server.sh status
```
> Port **8765** = hub nội bộ (`birdeye_ui.py`, `/test`), port **8899** = public (`deploy/server.py`).
> `deploy/server.py` (working tree) serve `assets/`; bản **đã commit** serve `deploy/index.html`.

---

## 4. Commit + push app tĩnh (repo ROOT)

Chỉ commit `deploy/` (đúng scope, tránh lẫn file rác):
```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills
git status                       # chỉ nên thấy deploy/ thay đổi
git add deploy/
git commit -m "deploy: <mô tả thay đổi>"
git push origin main
```

### Commit cả birdeye-screener hoặc docs (nếu cần)
```bash
git add birdeye-screener/ docs/
git commit -m "<scope>: <mô tả>"
git push origin main
```

---

## 5. Deploy Vercel

`deploy-vercel/` là **git repo riêng, chưa có remote** → deploy bằng CLI (không qua git):
```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills/deploy-vercel
npx vercel --prod          # deploy production
```
**Kiểm tra sau deploy:**
```bash
npx vercel curl /api/meta --deployment https://skills-olive-rho.vercel.app
# mong đợi: "ml_ready": true, "cli_ready": true
```

**Cấu hình Vercel app (giữ nguyên):**
- **Project:** `skills` · **Team:** `the-nang` · link qua `deploy-vercel/.vercel/project.json`
- `vercel.json` **BẮT BUỘC** có `"framework": null` (preset "Other"); nếu không, build fail `PYTHON_ENTRYPOINT_NOT_FOUND` vì có nhiều function (`api/run.py`, `api/meta.py`). Static output dir = `public/`.
- Key: local dùng env server; Vercel dùng **BYOK** (nhập key trên UI, lưu `localStorage`), ghi cache vào `/tmp/birdeye`.
- ML runtime nằm ở `api/_ml/` (prefix `_` = không bị route); `vercel.json` dùng `includeFiles: "api/**"`.

### (Tùy chọn) Vercel auto-deploy qua GitHub
Cần tạo 1 repo GitHub riêng cho `deploy-vercel/` rồi connect:
```bash
cd deploy-vercel
git remote add origin https://github.com/TheNang2710/birdeye-skills-vercel.git
git push -u origin main
```
Sau đó Vercel → project `skills` → **Git → Connect** → chọn account `TheNang2710` → chọn repo vừa tạo.

---

## 6. Checklist nhanh mỗi lần update
```bash
# 1) sửa UI + đồng bộ
cp deploy/index.html deploy-vercel/public/index.html
# 2) preview
./server.sh restart public          # http://127.0.0.1:8899
# 3) push app tĩnh
git add deploy/ && git commit -m "deploy: ..." && git push origin main
# 4) redeploy Vercel
cd deploy-vercel && npx vercel --prod
```

---

## 7. Troubleshooting

- **Sửa author của commit đã push**: `git commit --amend --author="nguyenthenang <nguyenthenang89@gmail.com>"` → cần `git push --force-with-lease origin main` (force-push ghi đè lịch sử — chỉ làm khi remote không có commit khác của người khác).
- **`git push` bị reject (non-fast-forward)**: remote có commit mới → `git pull --rebase origin main` rồi push lại. Nếu working tree có thay đổi chưa commit, `git stash push -m wip -- <paths>` trước, xong `git stash pop`.
- **Build Vercel fail `PYTHON_ENTRYPOINT_NOT_FOUND`**: thiếu `"framework": null` trong `deploy-vercel/vercel.json`.
- **Deployment Protection chặn curl**: dùng `npx vercel curl /path --deployment <url>` (qua CLI, có auth).
