# Birdeye Skills Hub v3 — Implementation Plan & Tasks Queue

## Task 1: Unprofessional Copy Cleanup (Remove tutorial/amateur text) + Pro Polish
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None (coupled T5 after core, but can do first)
- **Description**:
  - Remove heroText lines L743-745: replace with polished copy per spec FR-3 (hero all view: "🛰 Birdeye Data Skills · 32 on-chain trading superpowers. Data-first. Agent-ready. Run anything in one click.").
  - Hero per category view short descriptor for all 8 categories (Discovery / Token DD / Wallet SM / Security / Chain / Charts / Alerts / Utils — 1 line each).
  - Remove all phrases containing "sidebar skills", "control panel", "run output", "Không tự động run", "click a category", "save CU khi đang test", "tutorial", "guide" across entire UI JS literal strings.
  - Replace WIP fallback generic panel "click to propose this skill" with: short 1 line `🛠 WIP · Design doc ready — implementation coming soon.` and one button "📖 Read design doc" that opens relevant file in API/ folder in new tab (if exists), else alert.
  - Update `<title>` tag and header h1: "Birdeye Data Skills Hub" (add "Data").
- **Acceptance Criteria Addressed**: AC-10
- **Test Requirements**:
  - `rule` TR-1.1: Full body.textContent concat forbidden keyword scan returns count=0 for all 8 words. Evidence: browser evaluate regex test loop 0 matches.
  - `rule` TR-1.2: Hero all view includes exact string "32 on-chain trading superpowers". Evidence: evaluate document.body.textContent includes substring.
  - `rubric` TR-1.3: Copy quality polish; scale 1-5; anchors 1=still tutorial phrases, 3=basic text no personality, 5=pro polished distinct per category; threshold≥4. Evidence: snapshot home+drill 2 screens review visual.
- **Notes**: Đọc kỹ L500-780 JS literal để tìm copy cần xóa. Xong py_compile birdeye_ui.py exit=0.

## Task 2: Skill Cards Default All 32 Grid (No group cards) + Birdeye Data Tags
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None (có thể làm song song T1 vì không overlap text string cùng exact lines, nhưng cùng file birdeye_ui.py block renderHome L640-790 nên làm tuần tự T1 xong rồi T2)
- **Description**:
  - Rewrite `renderHome()` conditional auto-switch L671: OLD = if (f==='all') → group cards else skill cards. NEW = LUÔN render skill cards grid (all 32 when f==all; filtered subset when f==cat). Group cards biến mất hoàn toàn.
  - Skill card badge tags (sBadges): (1) `🛰 Birdeye Data` (always, đổi từ GMGN tag cũ L713 /^Birdeye/i test = đổi tất cả = Birdeye Data), (2) `📂 <CategoryName>` (tên group), (3) `LIVE` (green) or `🛠 WIP` (amber) theo status field của catalog item.
  - Sửa `gFound` references hero title → thay = số skill count. Filter chips 9 vẫn giữ nguyên top (All/8 cat). No code group cards left (xóa hẳn block generate catCard HTML).
  - CSS: .skillCard grid gap 20px, 3 cols default desktop, 2 cols tablet <900px, 1 col <600px. Responsive (minmax auto-fit).
- **Acceptance Criteria Addressed**: AC-1, AC-2
- **Test Requirements**:
  - `rule` TR-2.1: Home filter=all → querySelectorAll('.catCard').length === 0, querySelectorAll('.skillCard').length === 32. Evidence: browser evaluate object matches.
  - `rule` TR-2.2: All 32 sBadges contain "Birdeye Data" substring; GMGN regex /GMGN/i count=0. Evidence: evaluate scanBadges.
  - `rule` TR-2.3: Filter Token DD → skillCards.length === 5; Discovery→3; Security→4. Evidence: evaluate 3 scans.
  - `rubric` TR-2.4: Responsive visual; scale 1-5; anchors 1=CSS breaks cols overlap, 3=OK desktop only, 5=perfect 3/2/1 cols breakpoints; threshold≥4. Evidence: 3 screenshot sizes.
- **Notes**: Group cards cũ có thể comment out nếu cần revert sau; user yêu cầu "nhóm chỉ để filter" nên xóa hẳn cũng OK.

## Task 3: Pre-Flight Format Validation Client (Sol regex / EVM / numeric / key-set)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: T2 (không overlap line; có thể làm song song nếu đảm bảo L runCLI là những gì, nhưng an toàn tuần tự)
- **Description**:
  - New JS helpers top level: `validateSolanaAddr(a)`, `validateEVNAddr(a,chain)`, `validateRange(val, min, max, label)`, `validateSkillInputs(skillId)` = return array `[{ok:bool, field:'dd_address', message:'...'}]`.
  - Wrap the very TOP of `runCLI(side)` function FIRST 10 lines: call `validateSkillInputs(side)` → if any !ok → append red alert box inline under input field that failed, class='bad' big border-left red, text message. RETURN EARLY no fetch.
  - Skill address required: `dd` (Token DD), `security`, `holders`, `rugcheck_risk_audit`, `wallet_portfolio`, `wallet_trades`, `copy_trade`.
  - Range required: `tl` / `tl_v3` → min_volume ≥ 0, limit 1-500, interval in allowed set.
  - Key-set check: `/api/key-info` call cached 30s in STATE._cachedKeyInfo; if !STATE._cachedKeyInfo?.key_set → stop, show error "🔑 Apply your Birdeye API key first (Skill #28)."
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-3.1: Paste invalid Solana "abc123xyz" (24 chars) in DD address → click Run → 0 network POSTs to /api/run, inline error with "Invalid Solana address". Evidence: Network requests spy via browser_network_requests count; evaluate error element text.
  - `rule` TR-3.2: Valid address format but empty key → Run → stop, error "Apply your Birdeye API key first" substring, no /api/run. Evidence: evaluate response.
  - `rule` TR-3.3: Valid address + valid key set → normal run continues (fetch runs, 0 preflight fail). Evidence: lastRun gets populated runId.
- **Notes**: Fetch interceptor global không cần thiết (dùng return early đủ). Alert box appends vào đầu #skillCtrl. Auto dismiss 6s or input oninput event.

## Task 4: API Key Hardened Masking (input + server response)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: T3 (tuần tự, không overlap Python nhưng cùng UI key panel)
- **Description**:
  - Server Python side: /api/key-info response (L1893-1895):
    - OLD: `head6 = k[:6]`. NEW: `head2 = k[:2] if k else ""; tail2 = k[-2:] if k else ""`. Return object: `{"key_set": bool, "source": src, "head": head2, "tail": tail2, "mask": head2 + "****" + tail2 if k else "", "hot": ...}`. **Never return >2 chars head + 2 chars tail = max 4 real chars.**
    - /api/set-key apply success message (L1973): OLD `headTail(val,6,4)` → NEW `headTail(val,2,2)` — cắt 2-2.
    - Save success (L1991): same `headTail(val,2,2)` — never 6+4.
  - Client UI side: `#pasteKey2` textarea wrapper add toggle eye button side right. Default: `textarea.type = 'password'` + style dots. After success `doKeyAction('apply', val)` callback: set textarea.value = '••••••••••••••••' (16 bullet chars) + blur textarea. Eye toggle click: prompt user "If you want to see / edit paste a new key." → no reveal old value.
  - localStorage `LSKEY_SESSION_PASTE` cũ L1170: BỎ lưu raw key. Chỉ lưu boolean "key_set": true/false. Never persist key plain in localStorage.
- **Acceptance Criteria Addressed**: AC-5, AC-6
- **Test Requirements**:
  - `rule` TR-4.1: curl /api/key-info after apply key dc9909a... → response `head` length ≤2, `tail` length ≤2. No substring match of original key longer than 2 chars anywhere in response JSON. Evidence: shell python3 json check script output.
  - `rule` TR-4.2: Evaluate pasteKey2.value after Apply callback → only bullet chars; type attribute = password. Evidence: browser evaluate.
  - `rule` TR-4.3: localStorage.getItem(any LSKEY_*_SESSION_*) does not contain substring of real applied key. Evidence: evaluate localStorage dump + regex scan for key.
- **Notes**: Server `_SESSION_KEY["key"]` trong RAM vẫn giữ nguyên full key để call CLI — đúng mục đích. Only che client side + API response (không leak cho mạng khi inspect).

## Task 5: Official Birdeye Logo Fetch from Docs + Wire Header / Home Hero / Footer
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: None (tách file + browser MCP fetch, không conflict T1-T4 UI JS)
- **Description**:
  - Mở tab integrated browser tới `https://data.birdeye.so/docs/data-api/price-ohlcv` → browser_snapshot / evaluate DOM to extract logo URL. Candidates: `<img src>`, `<link rel=icon>`, inline SVG `<header>` brand.
  - Save logo locally (prefer SVG): `birdeye-screener/assets/birdeye-logo-official.svg` or `.png` if only raster. Overwrite old placeholder birdeye-logo.svg ONLY if new one is official; giữ 2 file cho backup nhưng UI dùng official.
  - Wire logo vào 3 vị trí: (a) Header góc trái (size 28×28, trước text "Birdeye Skills Hub"), (b) Home Section A Hero right column (64×64), (c) Footer bottom right tiny 16×16.
  - Add CSS class `.bdLogo { width:28px; height:28px; display:inline-block; vertical-align:middle; margin-right:6px; border-radius:6px; }` + 2 variants big 64px & tiny 16px.
- **Acceptance Criteria Addressed**: (Not a numbered AC chính thức trong spec — nhưng là FR user yêu cầu. Cover bằng rubric T5.2.)
- **Test Requirements**:
  - `rule` TR-5.1: File tồn tại: assets/birdeye-logo-official.svg or .png size ≥500 bytes. Evidence: ls -la file.
  - `rubric` TR-5.2: Logo fidelity; scale 1-5; anchors 1=placeholder cũ, 3=SVG crude drawn official OK, 5=fetch được official logo real from birdeye doc header brand; threshold≥4. Evidence: logo screenshot side-by-side vs doc site.
  - `rule` TR-5.3: Header + Hero + Footer 3 vị trí logo khác null rendered. Evidence: evaluate querySelectorAll('img.bdLogo, svg.bdLogo').length ≥ 2.
- **Notes**: Nếu logo không extract được do lazy load JS site → dùng browser screenshot rồi trim visual; hoặc fallback high-quality SVG với màu sắc chính xác (blue #0ea5e9 gradient official docs màu). Có thể dùng màu theme của docs UI nếu không lấy được file.

## Task 6: Skill #9 Top Smart Money Wallets — Criteria Matrix Control Panel + API Recipe Scaffold
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: T1 (tùng section text) / T2 (catalog items list đổi filter)
- **Description**:
  - Thay thế entry SKILL_CTRLS.sm_wallets hiện tại (đang fallthrough WIP) = control panel FUNCTIONAL DESIGN đầy đủ FR-2:
    - 4 REQUIRED RULE checkbox/toggles (user bật/tắt): MIN_TRADES slider (5..50, default 15), MIN_UNIQUE slider (3..30, default 8), TAGS_SM_OWNED checkbox (default on), BLACKLIST textarea (comma separated addresses, default empty).
    - 4 WEIGHTED SCORE sliders user có thể chỉnh min threshold (WinRate min %, PnlMult min ×, SmRank min rank, MaxDrawdownMax %).
    - 3 FAST/STANDARD/DEEP segmented buttons (FAST 30 CU / STANDARD 150 CU / DEEP 500 CU). Hiển thị CU estimate inline theo selection bằng badge ⚡X CU color.
    - Endpoint recipe button "📖 View API Recipe": onclick toggle panel dưới, show markdown-like 4 steps A→D của FR-2 endpoint list. Link tệp `API/11-smart-traders-criteria-skill9.md`.
    - Run button "▶ Scan Smart Traders (Mode)". FAST mode = tạo một CLI argv dummy (gọi step A /smart-money/v1/token/list nếu CLI hỗ trợ; không thì hiển thị "Scaffold: Fast mode would call /smart-money/v1/token/list (20 CU) + score local aggregation." — Không tự implement gọi thật cho STANDARD/DEEP cho v3 này).
  - Update skill #9 desc catalog L173 thành "Dynamic smart-money wallet scoring with adjustable win-rate / pnl-mult / drawdown thresholds — find copy-trade targets."
- **Acceptance Criteria Addressed**: AC-3
- **Test Requirements**:
  - `rule` TR-6.1: Drill sm_wallets → rendered 4 sliders + 3 segmented FAST/STANDARD/DEEP visible. Evidence: evaluate querySelectorAll('input[type=range]').length ≥ 4.
  - `rubric` TR-6.2: Criteria design completeness; scale 1-5; anchors 1=still generic WIP, 3=has text desc sliders no actions, 5=sliders + segmented modes toggle + recipe panel opens/shows endpoint list; threshold≥4. Evidence: screenshot drill sm9 + evaluate typeof showRecipeBtn.onclick === function.
  - `rule` TR-6.3: Changing segmented mode FAST→STANDARD→DEEP → inline CU badge updates (⚡30, ⚡150, ⚡500). Evidence: evaluate 3 mode checks.
- **Notes**: Đây là skill user highlight trong batch này ("1 số tiêu chí động cho user input chính là cái skill 9 cần thiết kế"). Không implement gọi thật cho các step B/C/D tốn >150 CU cho v3 này. Giữ UI design + recipe docs. V4 CLI có subcommand sm-wallets thì link runCLI sau.

## Task 7: API/ Modular Docs Folder (12 .md files)
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: None (pure new markdown files, không conflict bất kỳ task nào; làm earliest possible)
- **Description**:
  - Tạo thư mục `/Users/nguyenthenang/nang/birdeye/app/skills/API/` bằng mkdir.
  - Tạo 12 files (kebab-case numbered 01-12):
    01-token-overview.md, 02-chart-ohlcv-liquidity.md, 03-token-security.md, 04-holder-distribution.md, 05-holder-profile-top20.md, 06-top-traders-profile.md, 07-smart-money-token-list.md, 08-trade-data-aggregates.md, 09-fee-mint-burn-events.md, 10-composite-dd-10step.md, 11-smart-traders-criteria-skill9.md, 12-rugcheck-risk-audit-skill17b.md.
  - Mỗi file theo TEMPLATE consisten:
    - H1 Module Name + Skill ID.
    - SUMMARY TABLE: | CU Estimate | Endpoint URLs | Chains | Skill Step |
    - ## Params: Table Name | Req? | Type | Default | Enum/Range | Notes.
    - ## Response Fields: Field | Type | Nullable | Description. Include nested if array.
    - ## Sample Request: curl GET/POST với X-API-KEY placeholder.
    - ## Integration Notes: Module này nằm ở step nào trong 10-step DD, skill nào reference.
  - Fill nội dung thực tế từ birdeye-dd-workflow.md (Quick API Summary L7-25 + Section 6 RugCheck L167-301) + SM Criteria từ FR-2 của spec này.
- **Acceptance Criteria Addressed**: AC-7
- **Test Requirements**:
  - `rule` TR-7.1: ls API/*.md | wc -l → exact 12. Evidence: shell output.
  - `rule` TR-7.2: grep -l "^## Params" API/*.md | wc -l ≥ 10. Evidence: shell output.
  - `rubric` TR-7.3: Doc completeness across response fields; scale 1-5; anchors 1=stubs only headers, 3=half fields filled, 5=all 12 files have all 5 required sections + sample curl filled; threshold≥4. Evidence: ls + grep counts + head file API/10-composite-dd-10step.md verified.
- **Notes**: Đây là docs reference cho tương lai, nên viết thật chi tiết. Không cần perfect 100% field types, nhưng phải đúng response field names từ llms.txt.

## Task 8: Home Section A/B/C/D 4 Sections Redesign (GMGN concept)
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: T1 (copy pro), T2 (skill cards grid ở Section D), T4 (key status badge), T5 (logo assets)
- **Description**:
  - Refactor `renderHome()` top→bottom HTML wrapper với 4 sections ids: `#homeHero`, `#homeSetup`, `#homeShowcase`, `#homeSkillsHub`.
  - SECTION A HERO:
    - Flex row 2 cols (left 60% / right 40%). Left: h1 big 28px "🛰 Birdeye Data Skills Hub"; tagline paragraph 14px "32 on-chain trading superpowers. Built for agents. Built for you."; 3 stats pill chips inline `⚡32 Skills · 🛰 5 LIVE · 👤 Agent-ready`. Right: logo 64×64 (class bdLogo big) + short brand copy "Powered by Birdeye Data · Solana & EVM".
  - SECTION B SETUP 3 CARDS ROW (33% width each col-3 grid):
    - B1 🔑 "Birdeye API Key": micro status badge circle green/yellow/red (từ STATE._cachedKeyInfo). Mini input row "Paste key..." (khi user paste micro + click micro Apply = gọi doKeyAction('apply', value) mà không cần drill Skill #28. Bottom link "Advanced: Save persist →" → onclick drillMode('key').
    - B2 🤖 "Chat with your AI": micro provider selector (4 radio inline: OpenAI/Anthropic/OpenRouter/Gemini), mini key field, micro Apply AI button. Status badge. Bottom link "Manage →" → onclick go drill tab AI provider in Skill #28.
    - B3 📦 "Quick Install": 3 steps tiny numbered pills ① ② ③. Step text: cd hub root, run command, open URL. "Copy command" button (copy `python3 birdeye_ui.py --reload` to clipboard).
  - SECTION C SHOWCASE "⭐ Staff Picks" (3 cards 33% same grid):
    - Card C1: Skill #3 Token DD. Biggest badge 🔥 Most Used. Run button.
    - Card C2: Skill #1b V3 Token List. Badge 👑 Best Signal. Run button.
    - Card C3: Skill #9 Top Smart Money Wallets. Badge 🧠 AI-Curated. Detail button.
    - Each showcase card = larger padding + elevated shadow (box-shadow: 0 8px 30px rgba(var(--accent-shadow),.25)).
  - SECTION D SKILLS HUB: Filter chips 9 + heading "🛰 Skills Hub" then skill cards grid (32 default / filtered by chip).
- **Acceptance Criteria Addressed**: AC-9
- **Test Requirements**:
  - `rule` TR-8.1: Section ids in DOM order: #homeHero, #homeSetup, #homeShowcase, #homeSkillsHub → querySelectorAll section count = 4, correct order. Evidence: evaluate ids sorted list.
  - `rule` TR-8.2: Setup row = 3 cards; Showcase = 3 staff-pick cards. Evidence: evaluate .setupCard.length=3, .showcaseCard.length=3.
  - `rubric` TR-8.3: Home GMGN visual match feel; scale 1-5; anchors 1=old home looks same, 3=4 sections present but bland, 5=big hero + 3 setup + 3 showcase color distinct clean flow; threshold≥4. Evidence: full home page screenshot review.
- **Notes**: Section B micro buttons key apply cần có format validation quick giống T3 (empty key = stop no call). Do not duplicate code — reuse same helper apply/save.

## Task 9: AI LLM Chat Widget Floating — BYO Key + System Prompt Skills Catalog + Route DrillMode
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: T4 (masking consistent), T6 (skill9 catalog), T7 (docs reference)
- **Description**:
  - Step A: Extend Skill #28 Key control panel = 2 tabs HTML (Birdeye / AI Chat Provider). UI cho AI Chat Provider: 4 radio buttons provider names. API key field input masked password + toggle eye. Model textfield override (default gpt-4o-mini etc). Apply session / Save persist / Clear buttons (same UX Birdeye). Save to ~/.birdeye.env keys: `OPENAI_API_KEY=`, `ANTHROPIC_API_KEY=`, `OPENROUTER_API_KEY=`, `GOOGLE_API_KEY=`. Server side add /api/ai-key-info & /api/set-ai-key endpoints.
  - Step B: Server Python do_POST L1968 extend: path `/api/set-ai-key` (action provider string + save/apply/clear) + `/api/ai-chat` (proxy forward user LLM call — vì CORS từ client gọi trực tiếp có thể bị block). Hoặc pure client fetch (thử trước; nếu CORS error thì dùng server proxy — nhưng BYO key nên lưu ở client nếu có thể qua CORS). Policy: **client-side fetch first with BYO key only in memory (never localStorage raw)**, save persist = server file.
  - Step C: Chat widget UI fixed bottom-right (absolute/fixed). 360×540 expand. Floating collapsed state = circular button 💬 "Ask AI" with badge 🟢 if AI key set / 🔴 otherwise. Expanded: top bar title + provider status + close. Chat scroll messages (max 20). Bottom textarea + send arrow button.
  - Step D: System prompt inject (FR-7). Khi send, first system message with CATALOG serialized (array 32 skills {id,title,category,desc,status,cu}). Khi response parse JSON `{"action":"run_skill","skillId":"...","inputs":{...}}` nếu có → auto call `drillMode(parsed.skillId)` + after 300ms delay fill input fields if address/token inputs match keys. Alert: "🤖 AI pre-filled inputs. Review then click ▶ Run." (NO auto-run).
- **Acceptance Criteria Addressed**: AC-8
- **Test Requirements**:
  - `rule` TR-9.1: Widget exists on all pages (home/drill). evaluate document.getElementById('chatFloatBtn') !== null. Evidence: yes.
  - `rubric` TR-9.2: Chat full flow; scale 1-5; anchors 1=no widget, 3=widget open/close OK no network, 5=real BYO key testable mock routing success; threshold≥4. Evidence: chat send mock → on mock JSON response STATE.skill === expected skillId.
  - `rule` TR-9.3: Skill #28 tab 2 AI provider keys save round-trip: save→reload→/api/ai-key-info shows key_set=true head≤2 chars tail≤2, mask head****tail. Evidence: curl response check.
- **Notes**: Chỉ test routing via mock response. Để test thật user tự có key của họ (chúng ta không có key AI test).

## Task 10: Build Script Refresh (add new catalog items 32 count, tags "Birdeye Data" rewrite)
- **Status**: `pending`
- **Priority**: low
- **Depends On**: T2 (catalog count 32 → 32 builtin + rugcheck skill new now count script needs update)
- **Description**:
  - Update `birdeye-screener/scripts/build_skill_catalog_csv.py` literal `_31_BUILTIN_CATALOG_LITERAL` -> thêm 32nd item là rugcheck_risk_audit.
  - Update mapping `source_tag = 'Birdeye Data'` (thay vì old GMGN template tag logic per row, set hardcode for builtin rows).
  - Re-run script, regenerate `Birdeye Data Skills - skills-builtin-revised.csv` → rows count 32 builtin LIVE=5 WIP=27 + 33 backlog unchanged (khớp marketplace cũ 48-15dedup=33).
- **Acceptance Criteria Addressed**: (AC-2 Birdeye Data tag consistency reflected in CSV)
- **Test Requirements**:
  - `rule` TR-10.1: Shell `python3 build_skill_catalog_csv.py` exit 0. CSV output builtin rows = 32. Evidence: stdout summary stats line.
  - `rule` TR-10.2: grep -c "Birdeye Data" csv ≥ 32. GMGN grep builtin section = 0. Evidence: shell grep.
- **Notes**: User yêu cầu CSV revised theo định dạng GMGN. Cập nhật để reflect UI tag change (không còn GMGN builtin). Không liên quan runtime server; có thể làm bất cứ lúc nào.

## Task 11: py_compile Syntax Check Pass (After All T1-T9 edits)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: T1-T9 (không làm trước)
- **Description**:
  - Chạy `python3 -m py_compile birdeye_ui.py` 3 lần. Edit cho đến khi exit code 0 hoàn toàn. Không có lỗi SyntaxError, IndentationError.
- **Acceptance Criteria Addressed**: NFR-2
- **Test Requirements**:
  - `rule` TR-11.1: py_compile exit code = 0, stderr empty. Evidence: shell RunCommand exit 0.
- **Notes**: Required trước khi restart server (nếu py_compile fail server không boot). Luôn làm bước này first after code changes.

## Task 12: Server Full Restart (Fresh Process)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: T11 (compile pass trước)
- **Description**:
  - StopCommand kill PID 30249 (server đang chạy code cũ v2).
  - Run new background process: `python3 birdeye_ui.py --port 8765 --host 127.0.0.1 --reload 2>&1 | tee -a /tmp/birdeye_ui_v3.log`.
  - Wait boot banner `[UI] 🐦 Birdeye Skills Hub (32 skills)` → confirm loaded catalog 32 items (sau khi T2 skill 9 text desc đổi + rugcheck count 32). If banner still says "(30 skills)" → update string literal (minor).
- **Acceptance Criteria Addressed**: NFR-2
- **Test Requirements**:
  - `rule` TR-12.1: Server running banner hot reload ON, PID mới, curl /health status 200. Evidence: curl -s /health json ok=true.
- **Notes**: Policy hard constraint từ cycle v2: mỗi khi thay đổi literal string JS/CSS trong Python triple quote = MẤT full restart (hot reload handler đọc lại text nhưng không re-exec hàm _build_ui_html, đã chứng minh bằng test v2 trước đó).

## Task 13: Browser E2E Integration Test Suite (6 Flows)
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: T12 (server running v3)
- **Description**: Mở integrated browser tab, navigate http://127.0.0.1:8765, tuần tự verify 6 flows:
  - Flow A: Home default → verify AC-1 (32 skill cards, 0 group cards, birdeyeData:32, gmgn:0 badges).
  - Flow B: Token DD drill → invalid address "abc123" → click Run → AC-4 (0 /api/run POST network call, inline error red box "Invalid Solana address" substring present).
  - Flow C: Apply API key → /api/key-info curl head 2 chars; pasteKey2.value after apply = only bullet dots (AC-5/AC-6).
  - Flow D: Drill sm_wallets Skill #9 → sliders count ≥ 4, segmented modes FAST/STANDARD/DEEP change CU badge ⚡30/⚡150/⚡500 (AC-3).
  - Flow E: AI Chat widget mock JSON → drill DD routing (AC-8).
  - Flow F: 4 sections order + stats (AC-9). + Forbidden keyword scan AC-10 count=0.
  - Console messages check = 0 errors. Format switch Scorecard/Plain/Telegram = 0 CU chip (NFR-3 regression).
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-8, AC-9, AC-10, NFR-3
- **Test Requirements**:
  - 6 flows each with rule TR result pass evidence (browser evaluate outputs saved).
  - `rubric` TR-13.7: Flow pass rate; scale 1-5; anchors 1=<3 flows pass, 3=4/6, 5=6/6 all pass console 0 errors; threshold≥4.
- **Notes**: Nếu flow nào fail → quay Implement fix, add issue, restart cycle cho đến khi pass hết 6/6.

## Task 14: Independent Review Gate (Phase Review)
- **Status**: `pending`
- **Priority**: low
- **Depends On**: T13 (all E2E pass)
- **Description**: Create review.md, list 5 Check Points (CP) covering all ACs, run independent review pass (re-verify key evidence).
- **Acceptance Criteria Addressed**: (Gate tất cả AC)
- **Test Requirements**:
  - CP-R1: AC-1 (cards 32/0) + AC-2 (no GMGN) → `rule`
  - CP-R2: AC-4 (preflight) + AC-5/6 (key mask) → `rule`
  - CP-U3: Home 4 sections visual polish + criteria skill9 UI → `rubric` (0-5 ≥4)
  - CP-U4: API docs 12 files quality → `rubric` (0-5 ≥4)
  - CP-U5: Forbidden copy 0 matches + no errors console → `rule`
- **Notes**: Review result pass → complete. Fail/Blocked → remediation issues list back Implement.
