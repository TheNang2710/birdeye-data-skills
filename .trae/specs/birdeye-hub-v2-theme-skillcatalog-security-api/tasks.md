# Tasks: Birdeye Hub V2 Theme + Skill Catalog + Security API Design + Ops

> **Parent spec:** `spec.md` cùng folder
> **Kế hoạch tổng cộng:** 12 tasks (5 P0 high / 4 P1 medium / 3 P2 low). 3 vertical slices độc lập (Theme, Home+CSV, Doc+Ops).
> **Tổng thời gian ước tính:** 5-7 giờ thực thi code + test E2E.
> **Ngôn ngữ:** Tiếng Việt (English code terms)

---

## Task 1: Theme toggle sáng/tối (dark/light) CSS custom properties + icon button

| Field | Value |
|---|---|
| **ID** | T1-THEME |
| **Status** | pending |
| **Priority** | 🔴 P0 high |
| **Depends on** | Không (vertical slice 1 standalone) |
| **ACs covered** | AC-T1, AC-T2, AC-T3, AC-T4 (rubric) |
| **Files to change** | `birdeye_ui.py` (CSS block L305-397 → thêm :root variables; inline `<script>` trong `<head>` [TRƯỚC] paint để apply theme first; Header thêm icon button toggle; JS thêm function `applyTheme(t)` + `toggleTheme()`) |

### Implementation plan (chi tiết)

1. **Tạo CSS custom properties block NEW** ngay dưới `:root` hiện tại. Đổi 33 màu hiện tại (--bg, --fg, --panel, --mute, --line, --tag, --accent-blue, --accent-green, --accent-red, --accent-yellow, --score-sec, --score-smkt, --score-act, --score-vol, --score-final ...) TẤT CẢ thành `var(--X)`. Sau đó define 2 bộ:
   ```css
   :root[data-theme='dark'] { --bg:#0a0a11; --fg:#e7e7ea; ... } /* default exact old palette */
   :root[data-theme='light'] { --bg:#f7f7fb; --fg:#0a0a11; ... } /* light new spec values */
   ```

2. **Inline theme bootstrap TRƯỚC paint** (tránh white flash): Add 1 script block <u>NGAY SAU `<title>` TRƯỚC style sheet</u>:
   ```js
   (function(){
     var t=localStorage.getItem('be.theme') || 'dark';
     document.documentElement.setAttribute('data-theme', t);
   })();
   ```

3. **Header button toggle**: Thêm vào `<header>` (giữa `#docsBtn` và `#ver` hoặc cuối banner) — button `.btn ghost` với id=`themeToggleBtn` icon dynamic `☀️ / 🌙`. Click gọi `toggleTheme()`.

4. **JS function `applyTheme(t)` + `toggleTheme()`** cuối boot block trước khi boot():
   ```js
   function applyTheme(t){
     localStorage.setItem('be.theme', t);
     document.documentElement.setAttribute('data-theme', t);
     var btn = $('themeToggleBtn'); if(!btn) return;
     btn.textContent = (t==='dark') ? '☀️' : '🌙';  // dark mode → show sun để click sáng (và ngược lại)
     btn.title = (t==='dark') ? 'Chuyển nền sáng' : 'Chuyền nền tối';
   }
   function toggleTheme(){
     var cur = document.documentElement.getAttribute('data-theme') || 'dark';
     applyTheme( (cur==='dark') ? 'light' : 'dark' );
   }
   ```
   Gọi `applyTheme(localStorage.getItem('be.theme') || 'dark')` một lần trong `boot()` trước renderHome.

### TR (Test Requirements — Task-local)

| ID | Type | Test rule / rubric scale |
|---|---|---|
| TR-T1-1 | RULE | localStorage['be.theme'] undefined + browser hard refresh → data-theme='dark' (default). Scorebar cells render correctly dark-mode colors (không có blue cell của SEC bị ngả sáng). |
| TR-T1-2 | RULE | Click theme button (dark state, icon ☀️) → attribute đổi 'light', icon đổi sang 🌙, localStorage = 'light'. Refresh → giữ light. |
| TR-T1-3 | RULE | 2 visual elements critical existing tests: (a) Format buttons segmented `.bfmt.on` — on state border solid active color blue visible both modes; (b) History chip `.cu chip ⚡50 CU` — number bold visible both modes contrast ≥4.5:1. |
| TR-T1-4 | RUBRIC (0-2) | Flicker: 2 no flicker (inline script before paint + CSS vars), 1 flicker <50ms acceptable, 0 white flash >100ms. Threshold ≥1. |

### Completion Evidence

> Screenshot dark/light side by side, localStorage dump, 4x contrast ratio values (theme toggle + scorebar + buttons + chip). Browser evaluate theme toggle back/forth 3 cycles.

---

## Task 2: Home Filter chips bar (All + 8 categories chips) + STATE.homeFilter state + renderHome refactor

| Field | Value |
|---|---|
| **ID** | T2-HOMEFILTER |
| **Status** | pending |
| **Priority** | 🔴 P0 high |
| **Depends on** | Không (vertical slice 2 home layer 1) |
| **ACs covered** | AC-H1, AC-H3 (partial filter nav) |
| **Files to change** | `birdeye_ui.py` STATE → add `homeFilter: 'all'`; renderHome compose `.filterBar` div 9 buttons (All + 8 cat); renderHome filter logic for skill cards (task T3 will build) — at minimum filter for 8 existing cat cards now to show only matching cat (first user req: "click vào nhóm skill thì chỉ ra skills trong nhóm đó"). |

### Implementation

1. `STATE.homeFilter = 'all'` (string `'all'` or `catId`).
2. renderHome L527 area — THÊM new row `.filterBar` NGAY TRÊN `.homeTopBar` hero text:
   - 9 buttons chips: All (class active default) · 🔥 Discovery · 🛡 Token DD · 🧠 Smart Money · 🔐 Security · ⛓ Chain · 📈 Charts · 🤖 Alerts · ⚙ Utils
   - Click 1 chip → set `STATE.homeFilter = idOrAll; renderHome();`
3. **Existing 8 cat cards (current group-level cards)** → when `STATE.homeFilter != 'all'`: HIDE all cards EXCEPT matching catId. When id='all': show 8 cards ALL (current behavior). → **đáp ứng ngay user req: "click nhóm skill thì chỉ ra nhóm đó" cho lớp group cards.**
4. Back-path breadcrumb click Category segment → set homeFilter=catId before calling `goHome(); renderHome();`.

### TR (Local)

| ID | Type | Test |
|---|---|---|
| TR-T2-1 | RULE | Click chip `🛡 Token DD` → homeView còn LẠI 1 card (Token DD). Click chip `All` → 8 cards trở lại. STATE.homeFilter = 'token-dd' / 'all' đúng. |
| TR-T2-2 | RULE | Chip `All` active class CSS highlight đúng khi state==='all'; category chip active đúng khi state==catId. |
| TR-T2-3 | RULE | Breadcrumb Category segment clickable (pointer cursor, underline hover), navigate back home filter=category, STATE restored. |

### Completion Evidence

> Browser evaluate: 3 scenarios click chips → count `.catCard:visible` = (1, 8, 1). Breadcrumb category click redirects home with filter state.

---

## Task 3: Skill-level cards (31 skills) — 6 fields per card + marketplace CSV fallback desc + Detail button + 3-col card grid

| Field | Value |
|---|---|
| **ID** | T3-SKILLCARDS |
| **Status** | pending |
| **Priority** | 🔴 P0 high |
| **Depends on** | T2-HOMEFILTER (đã có STATE.homeFilter). Also cần đọc marketplace CSV (48 rows) trong Python `_30_SKILLS_CATALOG` builder + pass per-skill GMGN fallback desc vào data. |
| **ACs covered** | AC-H2, AC-H4 (rubric fidelity GMGN layout), AC-H3 (Detail → drill) |
| **Files to change** | `birdeye_ui.py`: (A) Python `_build_ui_html`: thêm JS object literal `MARKETPLACE_SKILL_FALLBACK` — mapping skill key → desc + question + category GMGN (load 48 rows CSV inline or JS const). (B) JS: renderHome thêm toggle "Level" (2-state: 📁 Group / 🎯 Skill) switch show group cards or skill-level cards? Or better show BOTH depending on STATE.homeFilter level? Per user verbatim requirement "chọn list hay card thì vẫn phải có filter kiểu tôi click vào nhóm skill thì chỉ ra skills trong nhóm đó đó, thì lúc đó click thẳng được vào skill cụ thể, mà skill cụ thể đó mới chính là cái card/list có mô tả short skill đó để làm gì nữa thì mới hiểu được" → correct behavior: filter All = hiện 8 group-level cards (overview). Filter 1 group (e.g. Discovery) = AUTOMATICALLY SWITCH RENDER TỪ group cards → skill-level cards của nhóm đó (không cần thêm toggle). → Exactly matches user text! |

### Implementation (critical detail, follow EXACT user requirement)

> User requirement bản dịch kỹ thuật: "Khi filter = All → hiện 8 group cards. Khi filter = 1 nhóm cụ thể → thay thế 8 group cards area = render skill cards của nhóm đó, mỗi skill = 1 card có short desc chi tiết skill làm gì + Detail button. Không cần toggle level bổ sung (auto-level theo filter state)."

1. **renderHome refactor L527 `.cats <div>` area**: 
   - If `STATE.homeFilter === 'all'`: hiện **8 group cards** (current code, làm việc cũ).
   - If `STATE.homeFilter` là 1 catId: tìm nhóm đó trong `CATALOG[CATALOG.findIndex(g=>catIdOf(g)===STATE.homeFilter)]`; render **`<skill cards>` = các items của nhóm đó với 6 fields theo GMGN spec** (icon + title + 2 tag pills + short desc (use `item.desc` if exists; else fallback `MARKETPLACE_SKILL_FALLBACK[item.id]?.description;`) + 2 metrics row `👁 run_count` + `↓ CU_spent` (tính từ actual `/api/history/list` cache hoặc `0`) + `▶ Run / Detail` button).
   - Skill card HTML structure class `.skillCard` (width min-max 280-360px, grid 3-col): same responsive grid as `.cats` cards.
2. **Detail button click**: on skill card button click → `drillMode(catId, idx)` → auto-select skill id, renderCatalog/skillCtrl (không auto-run, keep no-auto-run policy). If LIVE status → button label green `▶ Run (XX CU)`. If WIP → button label gray `Detail WIP` (disabled click → toast "Coming soon").
3. **2 metrics**: `👁 run_count` = số cache files trong `~/.cache` có `kind===this skill` (từ `/api/history/list` nếu đã gọi; nếu chưa = mock 0 or đọc từ localStorage counter). `↓ CU_total` = sum `cu_used_total` trong cache same skill kind. Nếu không có = 0. Làm **tốt nhất effort**: dùng local counter 1 click 1 increment đơn giản = đủ MVP.

### TR

| ID | Type | Test |
|---|---|---|
| TR-T3-1 | RULE | Filter=All → visible 8 group cards. Click filter `🔥 Discovery` → visible 3 skill cards (Trending List / V3 Token List / Trending Simple). Each card = "icon + title + 2 tag pills GMGN category + 2-line desc + metrics row + Detail button". |
| TR-T3-2 | RULE | Click skill card "🛡 Token Due Diligence (Should I Buy?)" Detail button (LIVE status) → STATE.mode drill, STATE.skill='dd', out area empty (no auto-run). Breadcrumb = "🏠 Hub / 🛡 Token Due Diligence / Skill #3 · Token DD". |
| TR-T3-3 | RULE | Skill cards có WIP status (Wallet & Smart Money 7 skills) → button gray "WIP · Detail" nhưng không gọi API/CLI (keep 0 CU no-auto-run). |
| TR-T3-4 | RUBRIC (0-3) | Marketplace visual fidelity: 3=pixel gần giống (cards 3-col, icon left, 2 pills, 2-line desc, 2 metrics bottom-right, green Detail). Threshold ≥2. |

### Completion Evidence

> Screenshot filter All (8 group cards) vs filter Discovery (3 skill cards). Skill Token DD click → STATE dump drill mode correct. No POST /api/run after 10 filter navigation clicks.

---

## Task 4: Breadcrumb clickable 2 segments + back flow preserve home state

| Field | Value |
|---|---|
| **ID** | T4-BREADCRUMB |
| **Status** | pending |
| **Priority** | 🟠 P1 medium |
| **Depends on** | T2 (filter state) + T3 (skill-level nav) |
| **ACs covered** | AC-H3 |
| **Files to change** | `birdeye_ui.py` drillMode L602 breadcrumb HTML compose → wrap segments với `<span class="bcSeg" data-action="home|cat">` clickable; onclicks goHome() / goHome()+homeFilter+renderHome() |

### Implementation

1. Rewrite 3 locations breadcrumb HTML:
   - L602 drillMode (primary)
   - L650 renderCatalog item click (secondary)
2. Dạng: `<span class="bcSeg" data-act="home">🏠 Hub</span> <span class="sep">/</span> <span class="bcSeg" data-act="cat" data-cat="${catId}"><b>${catIcon(gInfo)} ${title}</b></span> <span class="sep">/</span> <span>${curSkillObj.title}</span>`
3. CSS class `.bcSeg { cursor:pointer; text-decoration:none; } .bcSeg:hover { text-decoration:underline; }`
4. Wire onclicks: `onclick="goHome()"` cho act=home; `onclick="window.STATE.homeFilter='${catId}'; goHome();"` cho act=cat.

### TR

| ID | Type | Test |
|---|---|---|
| TR-T4-1 | RULE | Hover "🏠 Hub" = cursor pointer underline → click → STATE.mode=home hv_display='', state.homeFilter='all' preserved (original default). |
| TR-T4-2 | RULE | Hover Category segment = pointer underline → click → back home filter state = catId, renderHome visible skill-level cards của nhóm đó (hoặc group card nếu All). Correct STATE. |

### Completion Evidence

> Browser E2E: (Start home filter All) → click Discovery group card → drill → breadcrumb "🏠 Hub / 🔥 Discovery / Skill…" → click Discovery segment → back home filter=Discovery visible skill cards. Click 🏠 Hub segment → back home filter=All 8 group cards. STATE dumps all match.

---

## Task 5: CSV export builtin + marketplace GMGN cross-check (48 rows, 9 cols)

| Field | Value |
|---|---|
| **ID** | T5-CSV |
| **Status** | pending |
| **Priority** | 🟠 P1 medium |
| **Depends on** | Không (standalone file IO task, independent) |
| **ACs covered** | AC-C1, AC-C2, AC-C4 |
| **Files** | Tạo file NEW `/Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/Birdeye Data Skills - skills-builtin-revised.csv`. Optionally viết 1 Python script helper 50 lines `scripts/build_skill_catalog_csv.py` để regenerate in future (từ _30_SKILLS_CATALOG JSON nếu extract được từ birdeye_ui.py; hoặc viết hardcoded export 31 skills với mapping). |

### Implementation (recommended 2-file approach, durable)

1. **Hardcode export 31 skills** (không cần parse Python AST birdeye_ui.py literal JSON, dễ hơn, đủ ổn định vì catalog không đổi thường xuyên). Map 8 nhóm hiện tại → 5 GMGN categories reference (Discovery / Token Analysis / Wallet Intelligence / Monitor / Data Analytics + Utils). Difficulty Basic/Intermediate/Advanced. Stage: DISCOVER (Discovery nhóm) / RESEARCH (Token DD, Smart Money info) / DECIDE (score) / MONITOR (Alerts) / UTILS (Settings).
2. **Rows 32–48**: Read marketplace 48 skill rows, filter những skill chưa có trong builtin list → điền vào với stage="BACKLOG" (diff).
3. **File CSV rules**: UTF-8 BOM-free; fields chứa dấu phẩy (desc, question, capability, prompts) wrap double-quote; escapes chuẩn CSV (double quote inside field → 2x ").
4. **Đề xuất category mapping matrix 8→5 GMGN**:
   - 🔥 Discovery → `Discovery` (GMGN)
   - 🛡 Token Due Diligence / 🔐 Security → `Token Analysis` (GMGN)
   - 🧠 Smart Money (Wallet) → `Wallet Intelligence` (GMGN)
   - ⛓ Chain / 📈 Charts → `Data Analytics` (GMGN)
   - 🤖 Alerts → `Monitor` (GMGN)
   - ⚙ Utils → `Utils & Settings` (GMGN)

### TR

| ID | Type | Test |
|---|---|---|
| TR-T5-1 | RULE | `wc -l csv` ≥ 50 lines (2 comments + 1 header + 48 data rows). Python `csv.DictReader(f, strict=False)` parse OK without Error, 9 keys = headers đúng. |
| TR-T5-2 | RULE | Row 2 (first builtin skill "birdeye-trending-list"): category='Discovery', stage='DISCOVER', difficulty='Basic'. All 31 builtin rows `skill name` start với "birdeye-". |
| TR-T5-3 | RULE | Row 33+ (BACKLOG block đầu tiên) trường stage = 'BACKLOG' distinguish. 2 comment lines đầu hàng 1-2 bắt đầu với '#'. |
| TR-T5-4 | RUBRIC (0-2) | Cross-check coverage: 2 both 31 builtin non-empty desc + 17 backlog non-empty title desc category; 1 missing ≤2 rows; 0 >2 broken. ≥1 ok. |

### Completion Evidence

> File list ls -la, Python csv.reader parse 48 rows OK, sample rows (discovery first / backlog first). `file -I csv` = charset=utf-8.

---

## Task 6: Birdeye logo SVG local placeholder

| Field | Value |
|---|---|
| **ID** | T6-LOGO |
| **Status** | pending |
| **Priority** | 🟡 P2 low |
| **Depends on** | Không |
| **ACs covered** | AC-C3 |
| **Files** | Tạo file NEW `/Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/assets/birdeye-logo.svg`. Folder `/assets/` auto-created. |

### Implementation

SVG minimal 32×32 viewBox 0 0 100 100: background ellipse `#0ea5e9` (sky-500 birdeye blue), bird shape silhouette simple polyline trắng bên trong, chữ "BE" trắng bên dưới. Hoặc nếu không muốn draw silhouette → đơn giản round-corner blue square "BE" white bold text 14px (đủ branding placeholder). Size file ≤5KB.

### TR
| ID | Type | Test |
|---|---|---|
| TR-T6-1 | RULE | File tồn tại, size ≤20KB, open trong browser renders hợp lệ (không corrupted XML). |
| TR-T6-2 | RULE | Src URL reference dùng được data URIs hoặc relative path từ server. Add 1 route handler simple? Không add route, file CSV only. Chỉ cần file exists physically (placeholder OK per user spec "lưu local"). → PASS đơn giản. |

### Completion Evidence
> `file assets/birdeye-logo.svg` type SVG; open with `qlmanage -p` (macOS quick look) → visual OK.

---

## Task 7: Score SEC/SMKT/ACT/VOL tooltip explain + FINAL weighted breakdown inline UI

| Field | Value |
|---|---|
| **ID** | T7-SCORETOOLTIP |
| **Status** | pending |
| **Priority** | 🟠 P1 medium |
| **Depends on** | Không (standalone JS/CSS for existing scorebar cells, after render) |
| **ACs covered** | AC-S1, AC-S3 |
| **Files** | `birdeye_ui.py` scorebar render (2 places: L1156 rendered CLI parse, L1260 makeDDRenderFromPayload) + CSS `.tooltip` new class + JS helper `openScoreTooltip(cell, scoreKey)` onclick or hover attach. |

### Implementation

1. Thêm 100 rows CSS tooltip mới `.scoreCell .tooltip` + `.scoreCell:hover .tooltip` auto show. Tooltip nội dung 4 sections:
   - **Header**: `SEC / 10` + Weight 30%
   - **Base**: Score base 5.0
   - **Component list**: dev% thresholds (±), top10% thresholds (±), lpLocked +1, honeypot → 0.
   - **Clamp**: 0–10 note.
   
   (Nội dung chính xác = spec FR-SCORE-EXPLAIN table section 5.6 — SMKT cần dòng giải thích "SMKT = Smart Market Fit = ranking top 100 SM global + SM wallet count holding, weight 25%).
2. Attaching tooltips: Dùng function helper `addScoreTooltips(rootEl)` gọi ở cuối `renderFormat()` (L900s area) sau khi insert HTML vào out area. Loop `rootEl.querySelectorAll('.scoreCell, [data-score]')` → wrap hoặc add data attribute.
3. Riêng cell FINAL = tooltip content: "FINAL = SEC·30% + SMKT·25% + ACT·25% + VOL·20%. Verdict mapping ≥7.5 STRONG BUY, >6.2 BUY, >5 HOLD, >3.5 AVOID, else RED FLAG. Roadmap STANDARD mode +3 penalty classes (LP drawdown -1.5, BotProxy -1, TagConc -0.5/tag)."

### TR
| ID | Type | Test |
|---|---|---|
| TR-T7-1 | RULE | Sau khi run 1 token DD (HeeHaw address) → hover score cell SEC → tooltip visible, chứa text "Weight 30%" + "dev% < 2 +3". |
| TR-T7-2 | RULE | SMKT cell hover → tooltip chứa sentence: "SMKT là Smart Market Fit: độ phủ Smart Money global ranking top100 + wallet count holding, weight 25%". |
| TR-T7-3 | RULE | FINAL cell hover → weighted formula 4 terms visible + mapping thresholds verdicts. |
| TR-T7-4 | RUBRIC (0-2) | Clarity + numerical example. 2=có ví dụ spec (dev=1.5% nên +3, top10=15% nên +2, lpLocked=yes +1, total=5+3+2+1=11 clamp 10 → SEC score=10). 1=missing numerical. Threshold ≥1. |

### Completion Evidence

> Screenshot 5 tooltips SEC/SMKT/ACT/VOL/FINAL side-by-side. Extract innerText tooltips contain weight + logic lines.

---

## Task 8: Appendix Quick API Summary table into birdeye-dd-workflow.md HEAD

| Field | Value |
|---|---|
| **ID** | T8-DD-APPENDIX |
| **Status** | pending |
| **Priority** | 🟡 P2 low |
| **Depends on** | Không (standalone doc edit, independent of code) |
| **ACs covered** | AC-S2 |
| **Files** | `/Users/nguyenthenang/nang/birdeye/app/skills/birdeye-dd-workflow.md` (insert new section trước section 0, tiêu đề "## Quick API Summary (Token DD — 10 endpoints)") |

### Implementation

Copy table "Quick API Summary (Token DD)" từ spec.md FR-DD-SPEC section vào đầu file birdeye-dd-workflow.md NGAY TRÊN section 0 inventory. Formatted đúng Markdown table (endpoint, method, params, sample response field, CU). Ghi chú links 🔗 clickable tới:
- [birdeye_cli.py cmd_dd + scoring](file:///Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_cli.py#L760-L880)
- [birdeye_ui.py makeDDRenderFromPayload](file:///Users/nguyenthenang/nang/birdeye/app/skills/birdeye_ui.py#L944-L1068)

### TR
| ID | Type | Test |
|---|---|---|
| TR-T8-1 | RULE | File birdeye-dd-workflow.md: head -50 lines → new section "Quick API Summary" tồn tại với heading level 2 và markdown table 10 rows. |
| TR-T8-2 | RULE | Step 10 table cell rating "A..F/NG" link đúng đến section 2 rating mapping existing. |

### Completion Evidence
> `head -80 birdeye-dd-workflow.md` text contains Quick API Summary + 10 endpoints.

---

## Task 9: RugCheck-style Security API design doc section appended to workflow + UI scaffold

| Field | Value |
|---|---|
| **ID** | T9-RUGCHECK-DESIGN |
| **Status** | pending |
| **Priority** | 🟠 P1 medium |
| **Depends on** | T8 (doc file flow location) → append sau section 4 roadmap của workflow, new section 5 "RugCheck-style Security API (Module Spec)" |
| **ACs covered** | AC-R1, AC-R2, AC-R3 (rubric implementability) |
| **Files** | Doc: `birdeye-dd-workflow.md` (add section 5). UI: `birdeye_ui.py` `_30_SKILLS_CATALOG` add 1 new skill "Skill #4 · RugCheck Risk Audit" = WIP placeholder status với desc="Demo rugcheck.xyz-style 7 risk card + 13 field overview security audit" với cu=~90. Không implement CLI cmd (doc-only + UI scaffold). |

### Implementation

1. **Section 5 birdeye-dd-workflow.md RugCheck API Module**: Full spec FR-SECURITY-API tables (endpoint path, CU 90 breakdown, 13 overview fields map birdeye source + status ✅/🔧/❌, 7 risk cards severity/passed/threshold/detail structure, holders tab struct).
2. **UI catalog new skill #4 WIP**: Add vào group 🔐 Security 3 item → thành 4 (item rugcheck-risk-audit status=wip, cu=90CU estimate). Click item = WIP placeholder control panel message "Skill #4 đang trong giai đoạn design spec — xem chi tiết birdeye-dd-workflow.md Section 5".

### TR
| ID | Type | Test |
|---|---|---|
| TR-T9-1 | RULE | workflow.md Section 5 exists, 3 subsections: Endpoint/CU, Overview 13 fields, 7 Risk Cards struct, Holders tab struct. 13 field status column icons filled (13 total counts). |
| TR-T9-2 | RULE | Catalog group Security items.len = 4 new skill added. Click skill = control panel hiển thị text WIP design doc reference (không gọi runCLI). |
| TR-T9-3 | RUBRIC (0-3) | Implementability. 3=≤4h dev implement steps rõ endpoint to endpoint, CU khớp với inventory 90; 2 unclear 1-2 ngày; threshold ≥2. |

### Completion Evidence
> Doc snippet section 5, catalog evaluate items[security].len === 4, WIP panel text snapshot.

---

## Task 10: Server ops command + start/stop/nohup doc header comment birdeye_ui.py

| Field | Value |
|---|---|
| **ID** | T10-OPS |
| **Status** | pending |
| **Priority** | 🔴 P0 high (user yêu cầu explicit Python start + close command) |
| **Depends on** | Không (standalone header doc) |
| **ACs covered** | AC-O1, AC-O2, AC-O3 |
| **Files** | `birdeye_ui.py` comment block NGAY ĐẦU FILE (dưới shebang, trên import list, current lines L1-L28 area) thêm new comment block 35 lines titled "## Quick Start · Server Ops Commands (Việt - Anh)". |

### Implementation

Header block: Làm rõ ràng 3 phần (Start / Stop / Background + log). Format:

```
## =========================================================================
## QUICK START · SERVER OPS COMMANDS (Việt + Anh)
## cd vào thư mục root skills chứa birdeye_ui.py FIRST:
##   $ cd /Users/nguyenthenang/nang/birdeye/app/skills
##
## [A] START FOREGROUND (nhấn Ctrl+C để STOP - easiest)
##   $ python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload
##      --host  127.0.0.1 = chỉ local machine  [def] | 0.0.0.0 = mở LAN
##      --port  8765      = port mặc định          [def]
##      --reload          = hot-reload inline HTML/CSS/JS (không restart khi edit _build_ui_html)
##      Sau khi chạy → mở http://127.0.0.1:8765/
##
## [B] STOP (khi server chạy background / terminal khác)
##   $ lsof -i :8765          # Tìm PID process đang chiếm port (cột 2)
##   $ lsof -ti:8765 | xargs kill -9     # Hoặc kill 1 dòng
##   $ pkill -9 -f "birdeye_ui"          # Kill tất cả birdeye_ui process
##   $ lsof -i :8765          # Nếu không trả gì = port đã free (SUCCESS)
##
## [C] BACKGROUND RUN (nohup, log file, PID file, close terminal vẫn chạy)
##   $ nohup python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload \
##         > /tmp/birdeye-hub.log 2>&1 &
##   $ echo $! > /tmp/birdeye-hub.pid     # Save PID
##   $ tail -f /tmp/birdeye-hub.log        # Xem log realtime
##   $ kill $(cat /tmp/birdeye-hub.pid)    # Stop background
##
## NOTE (QUAN TRỌNG VỀ HOT RELOAD): --reload CHỈ refresh CSS/JS trong _build_ui_html()
## Nếu bạn chỉnh sửa Handler.do_GET / do_POST / main / argparse → PHẢI restart lại server
## (kill PID rồi start lại bằng lệnh [A] hoặc [C])
## =========================================================================
```

### TR
| ID | Type | Test |
|---|---|---|
| TR-T10-1 | RULE | Thực thi lệnh START foreground: log xuất "[UI] 🐦 Birdeye Skills Hub → http://127.0.0.1:8765". curl -sI http://127.0.0.1:8765 trả về HTTP 200 Content-Type text/html. Nhấn Ctrl+C → process exit clean (exit code 0). |
| TR-T10-2 | RULE | Background nohup start with PID file → process alive >2s after close shell; log file growing >0 bytes; kill `$(cat PID)` → process gone (ps không thấy birdeye_ui anymore). |
| TR-T10-3 | RULE | Stop flow lsof/kill works: start → lsof port 8765=1 row → run stop command → lsof 0 rows (port released). |

### Completion Evidence

> Header comment block visible first 40 lines birdeye_ui.py. Start/stop/background 3 scenarios shell session transcript (exit codes + output). Shell script test all 3 ops passes.

---

## Task 11: Integration test 1 — Theme 5 cycles flicker + scorecard SMKT tooltip text

| Field | Value |
|---|---|
| **ID** | T11-INTTEST1 |
| **Status** | pending |
| **Priority** | 🟡 P2 low (verify dependent tasks) |
| **Depends on** | T1-THEME, T7-SCORETOOLTIP (both implemented) |
| **ACs covered** | AC-T4 (rubric), AC-S3 (rubric), plus cross-check regression existing work (format switch 0 CU + history panel still work) |
| **Files** | Không chỉnh file (verification task only). Chạy birdeye_ui.py server + browser E2E 15 minutes manual testing. |

### Checklist
1. Theme 5 back/forth cycles dark/light → check no JS exception console, buttons states OK, localStorage value consistent
2. Scorecard DD run → 5 tooltips show up; SMKT tooltip contains exact string "weight 25%" + "ranking top 100 Smart Money global"
3. Regression format toggle Scorecard → Plain → Telegram → JSON = cu chip ⚡0 (no extra API call)
4. History panel right column 8 cards visible after 2 runs → click card = restore render 0 CU
5. RugCheck WIP skill #4 click open → not trigger 404 or error (WIP text shows)
6. No console errors, no invariant violations in 2 runs.

### TRs (test rules)
| ID | Type | Test |
|---|---|---|
| TR-T11-1 | RULE | 5 theme toggles + 2 token DD runs = 0 console errors (browser console_messages list empty). |
| TR-T11-2 | RULE | Format switch 4 formats → CU chip = 0 (parse DOM chip text). History click restore correct run format. |
| TR-T11-3 | RUBRIC | Overall stability (0-2) 2 zero issues + score tooltip contains sample numerical example; 1 minor 1 visual glitch acceptable; 0 crash. ≥1 pass. |

### Completion Evidence
> Browser network 0 extra POST after 5 toggles + 2 format switches. Console messages empty. SMKT tooltip innerText snippet.

---

## Task 12: Integration test 2 — Home filter flow (All → Discovery → skill card → drill → breadcrumb back)

| Field | Value |
|---|---|
| **ID** | T12-INTTEST2 |
| **Status** | pending |
| **Priority** | 🟡 P2 low |
| **Depends on** | T2+T3+T4 (home nav stack) |
| **ACs covered** | AC-H1/H2/H3/H4 rubric |
| **Files** | Verification task. |

### Checklist
1. Home filter=All → 8 group cards visible (snapshot)
2. Click Discovery chip → auto-switch to skill-level cards 3 (Trending List / V3 Token List / Trending Simple) — correct cards 6 fields
3. Click V3 Token List skill card "▶ Run 50 CU" button → drill mode state: skill=tl_v3 active, ctrl panel V3 selector, button run visible (NO auto-run, verify network 0 POST)
4. Click breadcrumb "Discovery" segment → back home filter=Discovery + 3 skill cards visible (state preserved)
5. Click breadcrumb "🏠 Hub" → back home filter=All 8 group cards visible
6. Card/List toggle works in BOTH levels (group level all + skill level inside 1 group) — 4 checks
7. GMGN visual fidelity scorecard ≥2/3 (rubric T3-4)

### TRs
| ID | Type | Test |
|---|---|---|
| TR-T12-1 | RULE | 6 navigations above = 0 POST /api/run (strict no-auto-run preserved everywhere). STATE dumps correct. |
| TR-T12-2 | RULE | Card/List view toggle 4 combos = correct DOM class listView apply, no console errors. |
| TR-T12-3 | RUBRIC (0-3) Marketplace visual fidelity (skill card). Threshold ≥2. |

### Completion Evidence
> Browser snapshots each step. STATE dump 6 transitions correct. Network 0 POST verify.

---

## Overall Implementation Order (dependency graph)

```
 PHASE A (independent, parallel 3 tracks)
   ├─ T1-THEME (standalone CSS vars + button)
   ├─ T5-CSV + T6-LOGO (standalone file IO tasks)
   └─ T10-OPS (header doc standalone)

 PHASE B (home nav — vertical slice 2, depends on NOTHING except reading state)
   ├─ T2-HOMEFILTER
   ├─ T3-SKILLCARDS (T2 completed first)
   └─ T4-BREADCRUMB (T2+T3 done)

 PHASE C (doc tasks / polish / WIP scaffold)
   ├─ T8-DD-APPENDIX
   ├─ T9-RUGCHECK-DESIGN
   └─ T7-SCORETOOLTIP

 PHASE D (integration verification, requires all phases A/B/C done)
   ├─ T11-INTTEST1
   └─ T12-INTTEST2
```

## Task Priority Summary (P0 first)

1. 🔴 P0: T1 (Theme) · T2 (Filter) · T3 (Skill Cards) · T10 (Server Ops) = MUST DO trước
2. 🟠 P1: T4 (Breadcrumb) · T5 (CSV) · T7 (Tooltips) · T9 (RugCheck design) = SHOULD DO sau P0
3. 🟡 P2: T6 (Logo) · T8 (Appendix) · T11/T12 (Integ Tests) = NICE TO HAVE cuối

Cancel/Approval note: Khi có task user muốn bỏ (ví dụ logo SVG hand-draw), cần explicit user approval thì mark status=cancelled + lý do, không tự skip. Không có task nào được cancelled trước khi user confirm.

## Cancelled Tasks

(none yet — add entries below nếu user approve bỏ 1 task nào đó theo OQ open questions answer)
