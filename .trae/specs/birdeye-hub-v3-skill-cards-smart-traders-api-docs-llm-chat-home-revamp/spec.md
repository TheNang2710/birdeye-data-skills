# Birdeye Skills Hub v3 — Per-Skill Cards, Smart Traders v9, Modular API Docs, LLM Chat, Home 4-Section Redesign

## Overview
- **Summary**: Redesign lại Birdeye Skills Hub toàn diện: (1) toàn bộ home mặc định là grid 32 skill-cards (mỗi skill 1 card kiểu GMGN Skills Market; nhóm chỉ dùng làm filter chips top); (2) design đầy đủ Skill #9 "Top Smart Money Wallets" với matrix tiêu chí smart trader động (cho user điều chỉnh threshold sliders) + blueprint gọi API Birdeye; (3) dọn dẹp copy amateur/tutorial → polished pro deploy; (4) thêm pre-flight format validation (regex Sol address, ranges) trước khi gọi API thật (giảm 0 CU cho case lỗi format); (5) che API key chặt hơn (input masked, /api/key-info chỉ trả về head/tail che ****, sau paste blur tự mask); (6) tạo folder `API/` modular docs cho 10+ module Token Due Diligence + Smart Traders + RugCheck; (7) thiết kế hệ thống chat với LLM của chính user (họ tự nhập OpenAI/Anthropic/OpenRouter API key); (8) revamp màn home theo concept GMGN (4 sections: Hero → Setup (2 keys + install) → Showcase staff picks → Skills Hub grid per-skill).
- **Purpose**: Chuyển từ "prototype scaffold" sang "app production-ready có thể share/demo được cho user bên ngoài". Tư duy per-skill cards đúng GMGN, cho phép user không biết nhóm skill vẫn có thể scroll tất cả skill và dùng category chip top làm lọc. Giải thích rõ Smart Trader criteria matrix + động API recipe. Bổ sung modular API docs folder dễ reference sau này.
- **Target Users**: Crypto traders muốn dùng AI/Birdeye data một cách low-friction; dev muốn extend skills với spec API rõ ràng per module; demo cho stakeholder nên UI sạch professional.

## Goals
- Mặc định home = full grid tất cả skill-cards (mỗi skill 1 card đúng GMGN style), không có group cards trung gian. 8 nhóm skill chỉ dùng làm filter chips (All / 8 cats).
- Skill #9 có tiêu chí Smart Trader hoàn chỉnh (cân win_rate, pnl_mult, trade_count, tag SM, hold_count) và cho user tùy chỉnh thresholds dynamic.
- Toàn bộ copy tutorial/guide amateur (heroText, drill intro text "click a category...", "không tự động run...") bị xóa hoàn toàn, thay bằng marketing copy chuyên nghiệp.
- Pre-flight validation client-side (Sol address regex base58 32-44 chars, numeric min/max) bắt lỗi inline không gọi /api/run.
- API key không bao giờ lộ plaintext: input field type=password + toggle show-eye; /api/key-info chỉ trả head(6) + tail(4) giữa là `***`; sau Apply Session xong khi blur textarea thì tự thay = `••••••••••` (RAM giữ OK).
- Folder `API/` mới gốc hub, 12+ modular markdown files thiết kế endpoint CU/params/response per module Token DD.
- User có thể tự save AI Provider key (OpenAI / Anthropic / OpenRouter / Gemini), widget chat panel float bên trái/phải. System prompt gắn skill catalog. LLM đề xuất skill phù hợp + tự navigate (go drillMode + set inputs).

## Non-Goals
- Không implement thực API server-side cho các skill WIP (chỉ UI scaffold + docs).
- Không thay đổi skill LIVE (tl/tl_v3/dd/key/about) core call chain CLI (chỉ thêm pre-flight validate trước khi run).
- Không dùng 3rd party SDK cho LLM chat (dùng native fetch + SDK-free HTTPS POST với headers API key user cung cấp).
- Không implement streaming chat (non-stream JSON mode đủ cho v1).
- Không thay đổi theme toggle / localStorage theme / localStorage view counter / run counter (giữ nguyên từ v2).

## Background & Context
- Server entry `birdeye_ui.py` PID 30249 running port 8765 hot-reload.
- Catalog hiện tại 8 nhóm × 32 skills (Security count =4 vì có rugcheck_risk_audit #17b). 5 skills LIVE, 27 WIP.
- Hiện tại heroText L743-745 có 2 câu amateur guide copy cần xóa. Skill card badge `GMGN` hiện tại lấy từ `!birdeye/i.test(it.source)` → cần đổi tất = `Birdeye Data` (user yêu cầu bỏ GMGN tag).
- Skill 9 `sm_wallets` WIP hiện fallthrough = generic WIP panel. Chưa có design criteria matrix. Cần define rõ.
- Modular docs T8 cũ chỉ là prepend 10-row table trong workflow doc. Cần tách riêng folder files cho dễ reference khi implement per-skill API.
- GMGN home concept vừa fetch: https://gmgn.ai/ai?chain=sol&tab=skills_market — 4 sections (Hero intro → Install skill widget → Skills grid). Bản thiết kế của home ta mở rộng thêm Setup keys card + Showcase.

## Functional Requirements

### FR-1: Per-Skill Cards Mặc Định (Không còn Group Cards trung gian)
- RENDER RULE: `STATE.homeFilter==='all'` → full grid **tất cả 32 skill-cards** (từng SKILL 1 card, đúng GMGN Skills Market style). `STATE.homeFilter==catId` → lọc còn skill-cards thuộc nhóm đó (0 group cards hiển thị ở mọi filter value).
- FILTER CHIPS: giữ 9 chips trên cùng (All / 8 category). Click chip = set STATE.homeFilter → rerender grid. Click vào card (hoặc nút Detail/Run) = drill sidebar.
- BADGE rule: tất cả skill cards tag `🛰 Birdeye Data` (đổi 100% từ old GMGN tag). Thêm badge thứ 2 = `📂 Category Name` (tên nhóm skill card đang thuộc). Thêm badge thứ 3 = `LIVE / WIP` với màu green/amber.

### FR-2: Smart Traders Criteria Matrix (Skill #9)
- **Criteria layers**: Wallet phải thỏa mãn ALL required rules + đạt MIN weighted score.
  1. **RULE-REQUIRED (fail = loại)**
     - Trade count 30d ≥ MIN_TRADES (user slider 5-50, default 15).
     - Total unique tokens traded 30d ≥ MIN_UNIQUE (slider 3-30, default 8).
     - Wallet tag list có chứa ít nhất 1 trong các tag smart (SM_OWNED | KOL_WHALE | PRO_TRADER | COPY_TARGET) — hoăc nếu không có tag thì Win Rate 30d ≥ 50%.
     - Không nằm trong BLACKLIST (user có thể paste 1 danh sách cách dấu phẩy).
  2. **WEIGHTED SCORE (tổng ≥ 70/100 = PASS)**
     - `WIN_RATE_30D` (0-40 điểm): <30%=0, 30-40%=10, 40-48%=20, 48-55%=30, >55%=40.
     - `PNL_MULT_30D` (0-25 điểm): <1.0×=0, 1.0-1.5×=8, 1.5-2.5×=15, 2.5-4×=20, >4×=25.
     - `SM_RANK_GLOBAL` (0-20 điểm): không có rank=6, top ≤#1000=10, ≤#500=14, ≤#200=17, ≤#50=20.
     - `UNREALIZED_DRAWDAWN_30D_MAX` (0-15 điểm): >50%=0, 35-50%=4, 20-35%=8, 10-20%=12, <10%=15.
- **ENDPOINT RECIPE** (Birdeye API):
  - Step A (20 CU): `/smart-money/v1/token/list` chain=sol time=24h, top=50. Lấy danh sách token có SM flow mạnh nhất.
  - Step B (loop token A list, 10 CU / token): `/defi/v2/tokens/top-traders` address=X chain=sol limit=50. Lấy 50 top trader mỗi token (win_rate, pnl_mult, realized_pnl, trade_count, tags).
  - Step C (Dedup + Score): aggregate wallet dedup across tokens. Calc score matrix above, filter required rules, sort by composite score desc.
  - Step D (10 CU / wallet, optional enrich top 20 ranked): `/wallet/v1/token/list` owner=wallet chain=sol limit=20, enrich last tokens held.
  - Total CU estimate: **MIN 30 CU (chỉ step A + C local) → 500+ CU (step B full loop)**. Cho user chọn FAST (30 CU, heuristic rank SM list only) / STANDARD (150 CU, top 13 tokens) / DEEP (500 CU, top 50 tokens).
- **CONTROL PANEL UI**: 5 sliders + 1 number inputs + 3 segmented buttons (FAST/STANDARD/DEEP) + chips toggle required rules (bật/tắt từng rule-required).

### FR-3: Clean Pro Text (Xóa toàn bộ copy amateur/tutorial)
- Xóa 100% các dòng sau (không còn hiển thị trên UI ANYWHERE):
  - heroText All view: "Click a category card... để xem danh sách skills trong nhóm. Không tự động run skill nào — click ▶ Run mới gọi API" → thay = copy polished.
  - heroText filter view: "Filter: X — click một skill card bên dưới để vào drill sidebar + control panel" → thay = copy short category descriptor.
  - Các WIP fallback panel "click to propose this skill" → text short: "🛠 WIP · Skill design doc ready — implementation coming soon."
  - Các text "sidebar skills", "control panel", "run output", "save CU khi đang test", "tutorial", "guide" → xoá hoàn toàn không còn xuất hiện.
- NEW HERO ALL VIEW COPY (pro marketing): "🛰 Birdeye Data Skills · 32 on-chain trading superpowers. Data-first. Agent-ready. Run anything in one click."
- NEW HERO FILTER VIEW COPY: Category-specific short 1 line. VD: Discovery = "🔥 Scan the market — new tokens, 5-min movers, and fast trending lists."; Token DD = "🛡 Should I buy this token? 10-step risk, security & smart-money verdict."; etc.

### FR-4: Pre-Flight Format Validation Client-Side
- Quy tắc applies cho MỌI gọi `runCLI()` (tl, tl_v3, dd, và mọi future skills khi link).
- CHECKLIST (bắt buộc pass hết mới POST /api/run):
  1. **Address validation** (nếu skill yêu cầu token/wallet address):
     - Solana: regex `^[1-9A-HJ-NP-Za-km-z]{32,44}$` (base58 no lI0O). Fail inline text đỏ "Invalid Solana address format — 32-44 base58 chars expected.".
     - BSC/ETH/EVM: regex `^0x[a-fA-F0-9]{40}$`. Fail tương ứng.
  2. **Numeric range**: min_volume ≥ 0, limit 1-500, interval in enum {5m,15m,1h,4h,24h}. Fail inline.
  3. **Key set check**: (/api/key-info head6 empty → fail "Apply your Birdeye API key first (Skill #28).".
- FAIL BEHAVIOR: Inline red alert box dưới input field. KHÔNG gọi fetch('/api/run'). Không ghi history. Không consume CU. Counter `STATE.run_errors++` tăng (debug).
- PASS BEHAVIOR: Tiếp tục gọi /api/run như cũ (không thay đổi logic sau pre-check pass).

### FR-5: API Key Hardened Masking
- UI: `#pasteKey2` textarea = mặc định `type=password` (che dots) + small icon 👁/🙈 toggle bên phải (onclick swap to text 2s rồi auto quay password).
- API RESPONSE: /api/key-info → BỎ `head` field (hoặc nếu giữ thì chỉ trả 2 ký tự đầu + 2 cuối, giữa = `***`, VD `dc**..**032f`). Mọi error message, saved to path message trả về `Head=**..**` không return 6+4 cũ.
- AFTER APPLY SESSION: Khi click Apply → success callback → set `$('pasteKey2').value = '••••••••••••••••'` (16 dots). Key thực vẫn nằm trong _SESSION_KEY["key"] RAM server-side (OK). User toggle show không bao giờ show real key được nữa; nếu muốn re-paste họ phải xóa dots và dán lại.
- SAVE PERMANENT confirmation: Trước khi click Save persist → confirm alert "This writes your key to ~/.birdeye.env chmod 600. Are you sure?". Cancel = stop.

### FR-6: API/ Modular Docs Folder (Token Due Diligence Modules)
- TẠO FOLDER MỚI: `/Users/nguyenthenang/nang/birdeye/app/skills/API/` (gốc hub).
- File matrix 12 markdown files (tên ngắn, kebab-case):
  1. `01-token-overview.md` — 21 CU. /defi/v2/tokens/overview + /token_security basic subset. Fields: price/MC/liquidity/holders/24hChange/V$...
  2. `02-chart-ohlcv-liquidity.md` — 15+10 CU. /v3/ohlcv & /v3/liquidity-ohlc-token. Response candles[].ohclv + liquidity min/max/drawdown%.
  3. `03-token-security.md` — 30 CU. /token_security v2 (full). Renounce/auth/honeypot/mintable/transfer_fee/max_fee / top10% creator% dev%.
  4. `04-holder-distribution.md` — 10 CU. /holder/v1/distribution. Top10/T20/T50/top100 concentration% + BotProxy% heuristic.
  5. `05-holder-profile-top20.md` — 30 CU. /holder/v1/profile. 20 rows rank/owner/amount/$/pnl/wallet_tags.
  6. `06-top-traders-profile.md` — 20 CU. /defi/v2/tokens/top-traders. wallet tags (SM_OWNED/KOL/PRO/BOT/COPY_TAG), realized_pnl_30d, win_rate%.
  7. `07-smart-money-token-list.md` — 20 CU. /smart-money/v1/token/list. Flow in/out$ net 24h, sm_buy_count, sm_holders_ratio%.
  8. `08-trade-data-aggregates.md` — 10 CU. /defi/v2/tokens/trade-data (buy_ratio, buys/sells counts, V$24h, V$5m, unique_buyers, unique_sellers, new_buyers%).
  9. `09-fee-mint-burn-events.md` — 5 CU. /txs/fee-extractor + /txs/mint_burn (nếu có). trade fee$/txn, mint events count (last 24h).
  10. `10-composite-dd-10step.md` — 71/155/266 CU. FAST/STANDARD/DEEP mode (subset above) + FINAL weighted SEC·30 + SMKT·25 + ACT·25 + VOL·20 → A-F rating.
  11. `11-smart-traders-criteria-skill9.md` — 30-500 CU. Nội dung FR-2 criteria + endpoint recipe.
  12. `12-rugcheck-risk-audit-skill17b.md` — 90 CU. Nội dung design Section 6 cũ (13 overview + 7 risk cards + holders table).
- Mỗi file format consistent (template):
  - H1: Module name + skill id
  - Table summary: CU estimate | Endpoint URL(s) | Chain support | Skill Step(s) used
  - ## Params (table: Name | Required | Type | Default | Enum / Range | Notes)
  - ## Response Fields (table: Field | Type | Nullable | Description)
  - ## Sample Request (curl + /api/run Birdeye-equivalent)
  - ## Integrate Notes (nơi module này nằm trong overall skill nào)

### FR-7: LLM Chat — Bring Your Own Key
- **AI Provider Key Mgmt**:
  - Add section to Skill #28 (API Key) 2 sub-tabs: (a) Birdeye Data (existing), (b) AI Chat Provider (new).
  - 4 radio AI Provider: `🔘 OpenAI | 🔘 Anthropic | 🔘 OpenRouter | 🔘 Gemini Google`.
  - Key textarea + Apply (session only) | Save (persist ~/.birdeye.env with `OPENAI_API_KEY=` / `ANTHROPIC_API_KEY=` / `OPENROUTER_API_KEY=` / `GOOGLE_API_KEY=`). Masking behavior identical FR-5.
  - Default model per provider (gpt-4o-mini / claude-3-5-sonnet / openrouter/auto / gemini-1.5-flash). Model input field cho override advanced.
- **Chat Widget UI**:
  - Floating fixed bottom-right panel 360×540. Collapsed = button 💬 "Ask AI about skills". Expand = 360w × 540h panel.
  - Top bar: Provider status badge (🟢 Ready / 🔴 Need Key). Close ✕ = collapse.
  - Middle: chat messages (max 20). System message ẩn khỏi UI (chỉ khi enable debug = show).
  - Bottom: textarea + ➤ Send button.
- **SYSTEM PROMPT (injected vào mỗi chat request, đầu tiên)**:
  ```
  Bạn là AI Assistant nội bộ của Birdeye Skills Hub. Công việc của bạn: (1) hiểu mục tiêu trading / phân tích user mô tả; (2) dựa trên CATALOG SKILLS sau, đề xuất 2-3 skill THÍCH HỢP NHẤT để đạt goal; (3) nếu user đồng ý run 1 skill -> trả về JSON format: {"action":"run_skill","skillId":"<id>","inputs":{"<key>":"<value>"}}.
  ---
  CATALOG SKILLS: [{id,title,category,desc,status,cu}, ... ] (32 items inject động render catalog current)
  ---
  Response rules: LUÔN nói tự nhiên 1-2 câu rồi list skills bằng bullet. Nếu run_skill → prefix JSON block.
  ```
- **AI → UI ACTION ROUTING**: Khi parse được JSON action=run_skill:
  - Gọi `drillMode(parsed.skillId)` (auto-nav).
  - Sau 300ms delay (để panel render xong), cố set các inputs common (`dd_address` / `tl_interval` / etc nếu có trong parsed.inputs). Có thông báo inline "AI pre-filled address X — click ▶ Run when ready.". Không tự động run (no CU consume).

### FR-8: Home Redesign 4 Sections (GMGN Concept)
Thứ tự top→bottom trong `renderHome()` (filter chips VẪN nằm dưới section B, trên skills grid):
1. **SECTION A · HERO** (top, full width):
   - Left: Big title "🛰 Birdeye Data Skills Hub". Tagline: "32 on-chain trading superpowers. Built for agents. Built for you.".
   - Right: Logo birdeye data (official 64×64 — từ task logo fetch). Stats chips: ⚡32 Skills · 🛰 5 LIVE · 👤 Agent-ready
2. **SECTION B · SETUP PANEL** (3 cards row 1/3 width each):
   - Card B1 · 🔑 Set Up Birdeye Data API: Short copy "Get your free key → Paste → Run anything". Mini key input (tiny textarea) + micro Apply button (link tắt tới Skill #28 full panel nếu muốn save). Quick status: 🔴 No key / 🟡 Session / 🟢 Saved
   - Card B2 · 🤖 Chat with your AI: Short copy "Bring your own LLM key. Ask AI to find & run skills for you.". Mini provider selector + micro Apply. Status badge.
   - Card B3 · 📦 Quick Install Guide: Short copy "Run the hub. Paste a key. Trade.". 3 tiny steps 1→2→3 (cd hub root / python3 birdeye_ui.py --reload / open localhost:8765). Link "Full Ops Guide" pop-up.
3. **SECTION C · SHOWCASE — Staff Picks** (3 cards row, 1/3 each, bigger box-shadow, "⭐ Staff Pick" tag):
   - Showcase Card 1: Skill #3 Token DD (Should I Buy?) — title, desc short, 🔥 Most Used tag, Run button.
   - Showcase Card 2: Skill #1b V3 Token List — 👑 Best Signal tag, Run button.
   - Showcase Card 3: Skill #9 Top Smart Money Wallets — 🧠 AI-Curated tag, Detail button.
4. **SECTION D · SKILLS HUB GRID** (default expanded):
   - Subheading + filter chips 9 tab style (All + 8 cats).
   - Grid masonry 3 col 32 skill-cards (FR-1 rule per-skill: icon title badges desc metrics Detail/Run btn cu).

## Non-Functional Requirements
- **NFR-1**: 0 duplicate selector CSS. All new selectors follow BEM-ish convention. Light theme CSS vars phải được sync với ALL changes (không break theme toggle).
- **NFR-2**: py_compile birdeye_ui.py exit code 0 (100% syntax valid Python) sau mọi edit.
- **NFR-3**: Format switch (scorecard/plain/telegram/json) phải 0 CU (giữ nguyên behavior v2).
- **NFR-4**: No auto-run ANYWHERE default (keep policy v2: skill tl auto-run L1176 loại bỏ nếu user đang ở skill 28 key chat etc, nhưng giữ nếu vào skill=tl trực tiếp từ banner tl/spcx — đó là explicit click.
- **NFR-5**: /api/set-key /api/key-info /api/run endpoint response sizes < 1MB each (chunked không cần).

## Constraints
- **Technical**: Không thêm pip/npm packages. Pure stdlib HTTP Python backend + vanilla JS. Chat LLM: native fetch only (fetch(api.openai.com / anthropic / etc) user key in Authorization Bearer header).
- **Business**: Không hardcode LLM key của dev / bất kỳ key nào vào code repo. 100% user provides.
- **Dependencies**: Birdeye public docs (https://data.birdeye.so/docs/llms.txt & data-api/price-ohlcv) — logo fetch allowed.
- **Filesystem**: ~/.birdeye.env allowed write (chmod 600 enforce). Folder `API/` mới + `assets/` giữ nguyên. Không touch CLI `birdeye_cli.py` core scoring (chỉ reference specs).

## Assumptions
- Asm1: Birdeye docs page (data.birdeye.so/docs/data-api/price-ohlcv) có logo SVG/PNG extract được bằng cách inspect HTML via integrated browser. Nếu không có = fallback high-quality SVG handmade (không giữ placeholder cũ).
- Asm2: OpenAI/Anthropic/OpenRouter/Gemini non-stream chat completion endpoint JSON mode hoạt động với Bearer header + standard body. Nếu 1 provider có format khác = adjust body per provider nhưng giữ interface chung.
- Asm3: User truy cập từ máy có internet (call LLM provider external). Nếu offline = chat trả lỗi inline gracefully.
- Asm4: Solana mainnet-beta là chain primary; EVM chains kept option trong skill9 (fast mode chỉ sol).

## Open Questions
- [ ] Q1: Skill #9 control panel runCLI gọi thực backend CLI (cần thêm subcommand mới) CHỈ UI scaffold + design doc? (Assumption: v3 này = UI scaffold ONLY + recipe docs; CLI subcommand add v4 cycle sau nếu user approve).
- [ ] Q2: Chat widget có default open khi user có AI key set hay luôn collapsed? (Assumption: collapsed default. Nếu user đã Apply key thì badge 🟢 "AI Ready" góc. Click mở.)
- [ ] Q3: Section C Staff Picks có đổi thứ tự showcase theo user's most-run (localStorage counter) hay cố định 3 cards #3 / #1b / #9? (Assumption: v3 cố định 3 cards. V4 = dynamic top3 most run.)

## Acceptance Criteria

### AC-1: Default home = all 32 per-skill cards
- **Type**: `rule`
- **Given**: Server fresh start, browser nav localhost, mode=home, STATE.homeFilter='all'
- **When**: Query `document.querySelectorAll('.skillCard').length && document.querySelectorAll('.catCard').length`
- **Then**: `.skillCard` length EXACT 32. `.catCard` length EXACT 0.
- **Pass Condition**: Skill cards count = 32, group cards = 0.
- **Evidence**: Browser evaluate output object {skillCards:32, catCards:0, filter:'all'}

### AC-2: Skill card badge = Birdeye Data (100% no GMGN tag)
- **Type**: `rule`
- **Given**: Home filter=all rendered, all cards mounted
- **When**: textContent concat of all `.skillCard .sBadges span.pillr` nodes; test /GMGN/i.test(all)
- **Then**: Zero matches for /GMGN/i. All cards contain string "Birdeye Data" or "🛰 Birdeye Data" at least once.
- **Pass Condition**: No GMGN substring in badges; Birdeye Data present per card.
- **Evidence**: Evaluate countBadgesByText() returns {gmgn:0, birdeyeData:32}

### AC-3: Smart Traders criteria weights pass matrix
- **Type**: `rubric`
- **Dimension**: Completeness of Skill #9 design scaffold + UI control panel dynamic inputs
- **Scale**: 1-5
- **Anchors**: 1 = chỉ có title WIP panel cũ; 3 = có criteria text nhưng không có sliders; 4 = đủ 5 sliders + 3 mode buttons + endpoint recipe copy show; 5 = đủ sliders + modes + khi run FAST mode thì tạo CLI argv dummy success (no CU consume, chỉ mock + docs link)
- **Pass Threshold**: >= 4
- **Evidence**: Snapshot drillMode sm_wallets shows sliders, segmented buttons FAST/STANDARD/DEEP visible; evaluate typeof showRecipeBtn.click() works shows recipe text.

### AC-4: Pre-flight validation blocks network call on invalid format
- **Type**: `rule`
- **Given**: Drill mode Skill #3 Token DD, paste invalid addr = "abc123xyz" (24 chars), key set
- **When**: User clicks ▶ Run button, /api/run POST count checked (global fetch spy)
- **Then**: Inline red error box visible under input; fetch POST count to /api/run = 0; history no new run added; key_info unchanged.
- **Pass Condition**: No /api/run network call, error box text = "Invalid Solana address format..." substring present
- **Evidence**: Network requests count (0) + browser evaluate error.textContent includes invalid substring.

### AC-5: API key masking — head 2 chars only in key-info
- **Type**: `rule`
- **Given**: User applied key = "dc9909a243924571b64f7c65fa2c032f" (session)
- **When**: Call GET /api/key-info → response json.head + response json.tail (if present)
- **Then**: head length ≤ 2 chars. tail length ≤ 2 chars. Middle masked = `****`. All message response strings never expose more than 4 chars total.
- **Pass Condition**: key-info response never returns more 4 real chars combined.
- **Evidence**: curl -s http://127.0.0.1:8765/api/key-info | python3 -c "import json,sys;d=json.load(sys.stdin);print(len(d.get('head','')),len(d.get('tail','')),d.get('head',''))" → head≤2, tail≤2

### AC-6: Paste key textarea masked with dots after apply session blur
- **Type**: `rule`
- **Given**: Skill #28 panel rendered; pasteKey2 has real key; user clicks [Apply session]
- **When**: Callback success fires → query pasteKey2.value + input type attribute
- **Then**: pasteKey2.value matches regex /^[•*·]{8,}$/ (dots only). Type = password or masked visually. Click eye toggle → value dots remain (no reveal real chars).
- **Pass Condition**: After apply: pasteKey2 contains only mask characters; no substring of real key present client-side value.
- **Evidence**: evaluate pasteKey2 after apply = "••••••••••" (dots 16 chars); confirm type is password.

### AC-7: API folder created with 12 markdown files
- **Type**: `rule`
- **Given**: Script runs create folder API/ + 12 md files
- **When**: ls -1 API/*.md | wc -l && head -3 API/10-composite-dd-10step.md
- **Then**: Count = 12 (exact). Composite file has H1 "10 Composite..." + "CU" table summary row.
- **Pass Condition**: 12 markdown files present in hub/API/ folder.
- **Evidence**: shell ls count returns 12; grep -l "## Params" API/*.md | wc -l ≥ 10.

### AC-8: LLM chat widget routes suggested skill
- **Type**: `rubric`
- **Dimension**: AI chat integration completeness (key mgmt + widget + routing drillMode)
- **Scale**: 1-5
- **Anchors**: 1 = không có gì; 3 = có key tab + widget không call network; 4 = có widget call real provider + trả skills list; 5 = parse được JSON run_skill → auto drillMode set skillId; inputs pre-fill hoạt động.
- **Pass Threshold**: >= 4
- **Evidence**: Widget render OK; evaluate document.querySelector('#chatWidget') != null; on mock response {"action":"run_skill","skillId":"dd"} → STATE.skill === 'dd' && STATE.mode === 'drill'

### AC-9: 4 Sections Home order + content
- **Type**: `rule`
- **Given**: Fresh page load home filter=all
- **When**: Query section ids order: `#homeHero`, `#homeSetup`, `#homeShowcase`, `#homeSkillsHub`
- **Then**: All 4 id exists, order top→bottom. Setup card count = 3; Showcase count = 3.
- **Pass Condition**: 4 section ids, setup=3 cards, showcase=3 staff-picks.
- **Evidence**: evaluate {sections: 4, setupCards: 3, showcaseCards: 3, order: ['hero','setup','showcase','skills']}

### AC-10: Unprofessional tutorial text NOT present
- **Type**: `rule`
- **Given**: Page full rendered home + drill DD + drill key
- **When**: Full document.body.textContent concat; check forbidden list keywords
- **Forbidden list keywords check**: `sidebar skills`, `control panel`, `run output`, `Không tự động run skill nào`, `click a category`, `save CU khi đang test`, `tutorial`, `guide` (case-insensitive multi match)
- **Then**: 0 forbidden matches substring ANYWHERE (hero, footer, WIP panel, drill intro).
- **Pass Condition**: RegExp test all forbidden → false/0 count
- **Evidence**: evaluate forbiddenMatches() returns count=0 for all keywords.
