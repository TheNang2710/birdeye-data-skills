# RUN · Birdeye Data Skills Hub (Terminal Commands)

> HTTP server: `birdeye_ui.py` (single-file stdlib — zero npm/pip install).
> Default UI: `http://127.0.0.1:8765/`
> 32 skills in catalog; **4 live implemented** today.
> Lean-UI default: chat widget hidden behind feature-flag comment blocks.

---

## Quick Start — one script (`server.sh`) · recommended

Quản lý **2 server** chạy song song:

| Tên | File | Port | Phục vụ |
|---|---|---|---|
| `hub` | `birdeye_ui.py` | **8765** | Hub Home (`/`) + Test lean (`/test`) |
| `public` | `deploy/server.py` | **8899** | Hub Home (`/`) + Test lean (`/test`) |

```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills

./server.sh start            # chạy CẢ HAI (nền) — mặc định
./server.sh start hub        # chỉ 8765
./server.sh start public     # chỉ 8899
./server.sh stop             # dừng cả hai
./server.sh restart          # dừng + chạy lại cả hai
./server.sh fg               # chạy hub foreground (Ctrl+C để dừng)
./server.sh fg public        # chạy public foreground
./server.sh watch            # watch file changes + auto-restart cả hai
./server.sh watch hub        # chỉ watch/restart 8765
./server.sh watch public     # chỉ watch/restart 8899
./server.sh status           # trạng thái cả hai

# đổi host/port
HOST=0.0.0.0 HUB_PORT=8765 PUB_PORT=8899 ./server.sh start

# dev loop: poll mỗi 2s rồi tự restart khi file đổi
WATCH_INTERVAL=2 ./server.sh watch
```

- Sau `start` → mở `http://127.0.0.1:8765/` và `http://127.0.0.1:8899/`
- Log nền: `tail -f /tmp/birdeye-hub.log` · `tail -f /tmp/birdeye-public.log`
- PID file: `/tmp/birdeye-hub.pid` · `/tmp/birdeye-public.pid`
- `watch` sẽ theo dõi các file `.py/.sh/.html/.css/.js/.md` trong `assets/`, `deploy/`, `birdeye-screener/scripts/`, `API/`, `docs/` và tự hard-restart server liên quan khi có thay đổi.

> `server.sh` tự kill instance cũ trên cùng port trước khi start, nên dùng được như hard-restart khi sửa Handler/code.

---

## 0. One-time Prep

```bash
# cd to the HUB root folder FIRST — all paths assume this CWD
cd /Users/nguyenthenang/nang/birdeye/app/skills

# --- Optional: verify file tree before first run ---
ls birdeye_ui.py                            # server file (should exist)
ls birdeye-screener/scripts/birdeye_cli.py  # CLI dispatcher
ls API/  | head -5                          # endpoint design docs
ls WORKFLOW-*.md                            # this session's 3 workflow docs

# --- Optional: install API key (skip if already done in UI paste panel) ---
python3 birdeye-screener/scripts/birdeye_cli.py config --apply YOUR_BIRDEYE_API_KEY_HERE
# writes to ~/.birdeye.env chmod 600 ; also supports 4 AI provider keys for future chat

# Verify key loaded (shows head2****tail2 mask — NEVER shows full key)
python3 birdeye-screener/scripts/birdeye_cli.py config --status
```

---

## 1. Start Server (Foreground — Easiest)

```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills

# Default — port 8765, localhost only (production-ish safe)
python3 birdeye_ui.py

# Dev mode — hot-reload inline HTML/CSS/JS literals (NOT Handler.do_GET/do_POST)
python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload

# LAN mode — expose to local network (0.0.0.0) + custom port
python3 birdeye_ui.py --host 0.0.0.0 --port 8888

# After boot → open this URL in browser:
#   http://127.0.0.1:8765/
```

### Boot banner (good health = OK)

Terminal should print something like:
```
🛰 Birdeye Data Skills Hub (32 skills)
   http://127.0.0.1:8765/
   --host=127.0.0.1  --port=8765  --reload=False
   PID=19XXX    cache_dir=~/.cache/birdeye-skills-runs/
```

If you see **32 skills** count on the banner = v3 code is running. If it says **30 or less** → you have an old PID still on port 8765, go to Section 3 first.

### `argparse` CLI flags reference

| Flag | Default | Purpose |
|---|---|---|
| `--host` | `127.0.0.1` | Bind IP. Use `0.0.0.0` for LAN access. |
| `--port` | `8765` | TCP port. Pick 8888 / 9000 / etc. if 8765 occupied. |
| `--reload` | **off** | Pass flag to turn on: reads `_build_ui_html()` from file on every GET so edits show instantly. ⚠ Does NOT reload Handler logic — see HOT-RELOAD CAVEAT below. |

To stop the **foreground** server: press `Ctrl+C` in that terminal.

---

## 2. Start Server (Background · Survives Terminal Close)

```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills

# Launch in background with log file + PID file
nohup python3 birdeye_ui.py \
      --host 127.0.0.1 --port 8765 --reload \
      > /tmp/birdeye-hub.log 2>&1 &
echo $! > /tmp/birdeye-hub.pid

# Confirm PID & port
cat /tmp/birdeye-hub.pid
lsof -i :8765

# Stream logs (Ctrl+C exits viewer; server keeps running)
tail -f /tmp/birdeye-hub.log
```

Stop the background server:
```bash
kill $(cat /tmp/birdeye-hub.pid)
# Then verify port released (no output = success)
sleep 1
lsof -i :8765
```

---

## 3. Stop / Kill Server (Hard Reset for Code Changes)

### ⚠ IMPORTANT HOT-RELOAD CAVEAT

`--reload` ONLY re-reads inline HTML/CSS/JS strings inside `_build_ui_html()`. It **never re-runs**:
- `Handler.do_GET` (new endpoints added / changed / cached response logic)
- `Handler.do_POST` (run / set-key / set-ai-key endpoints)
- top-level dicts, argparse, or any Python function outside the UI HTML literal

**Whenever you edit those → FULL restart is mandatory.**

### Kill recipes (use any one — safest = `pkill` then verify)

```bash
# --- Option A — kill by port owner (good when you don't know PID) ---
lsof -i :8765                          # column 2 = PID
kill -9 <PID>

# --- Option B — one-liner force-kill port owner ---
lsof -ti:8765 | xargs kill -9          # silent on empty (= already free)

# --- Option C — kill ALL birdeye_ui processes (use when multiple copies) ---
pkill -9 -f "birdeye_ui"

# --- ALWAYS VERIFY port released (NO output = SUCCESS) ---
sleep 1
lsof -i :8765
```

If `lsof` still shows a PID after 2s → try Option C then recheck.

### Standard restart loop (during UI dev iteration)

```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills

# 1. Kill old server hard
pkill -9 -f birdeye_ui 2>/dev/null ; sleep 1 ; lsof -i :8765 | wc -l

# 2. Syntax-check Python before starting (catching 99% bugs before server boots)
python3 -m py_compile birdeye_ui.py && echo "✓ py_compile OK"

# 3. Re-launch (dev mode)
python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload
```

---

## 4. Standalone CLI (Layer C — Bot-friendly / Telegram)

These are the 2 LIVE implemented subcommands — **work without UI, anywhere**.
Perfect for scheduling via `cron`, pasting into Telegram, or piping into jq for bots.

### 4a. Trending List (Discovery)

```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills

# Solana · 1h · v3-list · 10 rows · plain ASCII
python3 birdeye-screener/scripts/birdeye_cli.py trending-list \
  --chain sol --interval 1h --source v3-list --limit 10 --format plain

# Pump.fun platform only · telegram markdown
python3 birdeye-screener/scripts/birdeye_cli.py trending-list \
  --chain sol --platform pump.fun --limit 15 --format telegram

# BSC · raw JSON to jq
python3 birdeye-screener/scripts/birdeye_cli.py trending-list \
  --chain bsc --interval 24h --limit 30 --format raw-json \
  | jq '.payload.rows | map({symbol, price_usd, marketcap_usd})[:5]'
```

### 4b. Token DD (Should I Buy?)

```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills

# Demo token (RugCheck reference · Sol) · 71 CU
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --format plain

# Ethereum 0x address · telegram
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain eth --address 0x8888889293c46393717B76bE2Ac21c1f0F05c8cA \
  --format telegram

# Extract only the scorecard (SEC / SMKT / ACT / VOL / FINAL + rating) via grep
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --format plain | grep -E "SCORECARD|SEC |VERDICT|RATING|Final"
```

### 4c. Cache Helpers (0 CU — no API calls)

```bash
# List last 25 run_ids in cache (with timestamp)
python3 birdeye-screener/scripts/birdeye_cli.py history --limit 25 --format plain

# Re-render a PAST run_id in a DIFFERENT format (0 CU — same snapshot data)
python3 birdeye-screener/scripts/birdeye_cli.py replay-run \
  --run-id trending-list_sol_1h_v3_1760000000 \
  --format telegram
```

### Exit codes (CLI & UI `/api/run` endpoint)

| Exit | Meaning | CU spent? |
|---:|---|---|
| 0 | Success | ✅ Actual CU (not 0) |
| 2 | Invalid args / address / key (argparse / preflight) | ❌ 0 CU |
| 3 | API key missing | ❌ 0 CU |
| 4 | Birdeye upstream HTTP error | ⚠ Partial possible on 429 upstream |
| 5 | Post-response invariant failed (e.g. buy$+sell$ ≠ volume by >15%) | ✅ CU (already called) — pipeline_gap badge added |

---

## 5. Quick Health Check (after any restart)

Run these after `python3 birdeye_ui.py` boots to confirm v3 is healthy:

```bash
# A. HTTP 200 on root
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8765/

# B. Banner shows expected count 32 skills
curl -s http://127.0.0.1:8765/ | grep -o "Birdeye Data Skills Hub ([0-9]\+ skills)" | head -1

# C. API endpoint returns masked key (paste/set key in UI first for non-MISSING source)
curl -s http://127.0.0.1:8765/api/key-info | python3 -m json.tool | head -8

# D. Expected files present
ls WORKFLOW-0{1,2,3}-*.md   CSV-IMPLEMENTATION-STATUS.md  RUN.md   birdeye_ui.py
ls API/0{1,2,3,4,5,6,7,8,9}-*.md API/1{0,1,2}-*.md
```

Expected result: **HTTP 200**, banner shows `Birdeye Data Skills Hub (32 skills)`, 3 workflow docs + 12 API docs all present.

---

## Appendix: Feature Flags

| Feature | Flag state today | How to enable if needed |
|---|---|---|
| 💬 Floating chat widget (LLM BYO 4-provider skill routing) | **OFF (lean UI)** | 2 blocks in `birdeye_ui.py` are HTML/JS `<!-- comment -->` / `// JS block comment`. Uncomment both (around L612 div#chatFloatingRoot + around L2512 boot IIFE). Full restart required. |
| Default auto-run on load | **OFF (policy)** | 100% enforced. No skill ever runs on page load; user must click ▶ Run. |
| External third-party links on Next-Actions panel (legacy) | **REMOVED** | Badge 100% 🛰 Birdeye Data; external links = Birdeye only. |
| STANDARD / DEEP DD modes (155 CU / 266 CU) | **WIP (FAST 71 CU only)** | Placeholder `<select id="dd_depth">` not yet added to renderSkillCtrl block; CLI argparse `--depth` pending. |
