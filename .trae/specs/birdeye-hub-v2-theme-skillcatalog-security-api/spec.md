# Spec: Birdeye Hub V2 (Theme Toggle + Skill Catalog + Security API Design + Server Ops + SMKT Explain)

> **Version:** 1.0
> **Date:** 2026-10-09
> **Ngôn ngữ:** Tiếng Việt (code terms giữ nguyên English)
> **Repository root:** `/Users/nguyenthenang/nang/birdeye/app/skills/`

---

## 1. Problem Statement (Vấn đề)

Hub Birdeye hiện tại mới hoàn thành view 2 tầng (Home 8 group cards → Drill sidebar). User yêu cầu 7 bổ sung lớn:

1. **UI Theme**: Thiếu toggle sáng/tối (default tối), user muốn icon button 1 click đổi theme, lưu preference.
2. **Skill Catalog CSV format GMGN**: Marketplace CSV tham khảo đã có 48 skill GMGN template. Cần cross-check với 31 skill hiện tại, tạo CSV mới "skills-export" để quản lý & revise sau, kèm logo Birdeye local.
3. **Home view 3-tiers**: Hiện tại chỉ có group-level cards. Cần thêm **filter chips theo category + drill-down tới từng skill-specific card/row với short desc chi tiết của từng skill** trước khi vào Drill sidebar control panel. Phải có back-path dễ dàng từ chi tiết → home filter ban đầu.
4. **Giải thích Scorecard**: User muốn hiểu rõ ý nghĩa từng điểm chấm 4 trụ SEC/SMKT/ACT/VOL, đặc biệt **SMKT = gì, cách tính**, weight tổng hợp FINAL.
5. **Server start/stop ops**: User cần lệnh Python command-line rõ ràng để open/close server (đóng terminal, kill PID đúng).
6. **RugCheck-style Security API design**: Demo từ rugcheck.xyz (7 risk cards + holders 48 + LP locked) → design module security API bổ sung cho Token DD, mapping các field Birdeye tương đương.
7. **Token DD API Requirement Spec**: Cần định vị tài liệu spec hiện có (param/endpoint/response field nào) + viết rõ tóm tắt ở phần Appendix để 1 glance nắm được.

## 2. Users & Stakeholders

| User | Mục tiêu chính |
|---|---|
| User (bản thân người yêu cầu) | Test sản phẩm, tiết kiệm CU, tìm skill nhanh, hiểu score rõ ràng, đóng/mở server tự chủ |
| Người khác clone repo | Chạy 1 lệnh Python để start Hub, hiểu command ops, import CSV skills vào GMGN format |

## 3. Goals (Mục tiêu MUST HAVE)

| ID | Mục tiêu | Độ ưu tiên |
|---|---|---|
| G1 | Theme dark/light toggle button, default dark, lưu preference (persist) | 🔴 P0 |
| G2 | Home: filter chips (All / 8 categories) → drill 2 level: group → skill cards (mỗi skill card có short desc, CU badge, status LIVE/WIP, Detail button) | 🔴 P0 |
| G3 | Back-path rõ: từ drill sidebar + skill detail → 🏠 Home filter ban đầu với state nguyên vẹn | 🟠 P1 |
| G4 | GMGN-format CSV export cross-check với marketplace-catalog.csv: 48 skills GMGN reference + 31 skills hiện có (map GMGN format: skill name, title, question, description, category, stage, difficulty, core_calls, core_capabilities, prompts) + lưu logo birdeye local | 🟠 P1 |
| G5 | Giải thích SMKT + SEC/ACT/VOL: doc + inline tooltip UI | 🟡 P2 |
| G6 | Python server start/stop ops: 1 dòng command start, 1 dòng stop, status check | 🔴 P0 |
| G7 | RugCheck-style Security API module design doc: endpoint, params, response 13 fields (overview + 7 risks) | 🟠 P1 |
| G8 | Token DD API Spec appendix: summary 10-step + param/response field map ở đầu doc + links 🔗 clickable | 🟡 P2 |

## 4. Non-Goals (KHÔNG làm trong spec này)

- ❌ Không implement thực tế các endpoint Birdeye holder-profile / liquidity-ohlc mới vào CLI (chỉ DESIGN RugCheck API module, code implementation留 cho phase sau sau approval user)
- ❌ Không thay đổi logic scoring 4 trụ hiện tại (chỉ EXPLAIN & document)
- ❌ Không implement FAST/STANDARD/DEEP depth switch MVP (để roadmap, doc thôi)
- ❌ Không implement real bot% detect native (giữ label BotProxy% như hiện tại)

---

## 5. Functional Requirements (FR)

### FR-THEME · Theme toggle sáng/tối

| Field | Nội dung |
|---|---|
| **Default theme** | Dark (nền tối) — match user preference (user style: high contrast black text bold, màu nhận diện nhất quán) |
| **Trigger UI** | Single icon button trên header: `🌙` (khi theme=light → click đổi dark) / `☀️` (khi theme=dark → click đổi light). Click = toggle. |
| **Preference store** | `localStorage['be.theme']` = `'dark' | 'light'` — đọc + apply trước khi paint first render tránh white flash. |
| **Implementation** | CSS custom properties (`:root` vs `[data-theme="light"] :root`). Tất cả các màu (`--bg`, `--fg`, `--mute`, `--line`, `--tag`, `--panel`, `--accent-blue`) đều là CSS variables. **KHÔNG duplicate 2 bộ styles hoàn toàn.** Đổi giá trị variables duy nhất. |
| **Dark palette (giữ nguyên cũ)** | `--bg=#0a0a11`, `--fg=#e7e7ea`, `--panel=#14141e`, `--line=#22222c`, `--mute=#6a6a72`, `--accent-blue=#4a9eff`, `--accent-green=#36d399`, `--accent-red=#f87171`, `--accent-yellow=#fbbf24` |
| **Light palette (new)** | `--bg=#f7f7fb`, `--fg=#0a0a11`, `--panel=#ffffff`, `--line=#e2e2ea`, `--mute=#5a5a62`, `--accent-blue=#0a6ed1`, `--accent-green=#038859`, `--accent-red=#d02a2a`, `--accent-yellow=#b8860b` |
| **Badge/chip colors**: | Màu xanh xanh/yellow/red badge giữ hue tương tự (high contrast) thay đổi độ sáng. Format switch segmented button (Scorecard/Plain/Telegram/JSON) vẫn đúng border/on-state. |
| **Accessibility**: | Contrast ratio text/background ≥ 4.5:1 (WCAG AA). Card shadow nhẹ thay border trong light mode. |

### FR-HOME · 3-Tier Home (Filter chips → Group/Skill cards → Drill)

> **Current state**: Home hiện tại chỉ show 8 group-level cards. Click 1 card → đi thẳng vào Drill sidebar. Missing: (a) Filter All / 1 nhóm, (b) Skill-level cards (mỗi skill 1 card short desc). User yêu cầu cả 2.

#### 5.2.1 Filter bar (Category chips)

- Vị trí: Ngay trên hero text, sau homeTopBar.
- Nút `All` active default + 8 category pills buttons có icon: `🔥 Discovery` / `🛡 Token DD` / `🧠 Smart Money` / `🔐 Security` / `⛓ Chain` / `📈 Charts` / `🤖 Alerts` / `⚙ Utils`.
- Click 1 chip → filter (nếu All: hiện 31 skill cards tổng. Nếu 1 nhóm: chỉ hiện skills trong nhóm đó).
- State `STATE.homeFilter = 'all' | catId`.

#### 5.2.2 Skill card (từng skill 1 card) — reference GMGN Skills Market (screenshot user gửi)

Mỗi skill card (3 columns grid responsive) bao gồm các field theo format GMGN reference:
| Field | Nguồn | Mô tả |
|---|---|---|
| **Icon trái trên** | catIcon(cat) + custom per-skill emoji (nếu có) | Ví dụ 🔥 cho 5-Min Trending, 🏆 cho Pump.fun, 🛡 cho Token DD, v.v. |
| **Tên skill (Title)** | `catalog[i].items[j].title` | Bold, size 15px. Cắt "Skill #N · " prefix. |
| **2 Tag pills** | `GMGN` (badge mặc định platform) + Category (VD: Discovery / Data Analytics). Ngang hàng dưới Title. | `birdeye-skills` catalog map category theo CSV marketplace: 8 nhóm hiện tại → map vào 4 nhóm GMGN (Trading / Data Analytics / Monitor / Utils) theo matrix ở G4. |
| **Short Description** | `catalog[i].items[j].desc` (nếu có) hoặc **fallback từ CSV marketplace 48 skill GMGN** (cross-check theo skill name) | 2–3 dòng text giải thích rõ skill này làm gì. |
| **2 Metrics row dưới** | (Left) `👀 views_count` (placeholder = số lần user click run skill trong history, ví dụ `👁 1.2K`) + (Right) `↓ usage` (placeholder = tổng số run CU tiêu tốn / 1000, ví dụ `↓ 442`). | 2 con số này khởi tạo 0 ban đầu (mock), increment theo lịch sử run thực tế của user. |
| **Detail button right dưới** | Label `Detail` hoặc `▶ Run` (nếu LIVE). | Click `Detail` → đi vào Drill sidebar **chọn skill đó** (không auto-run, giống cũ). Nếu `WIP` → Detail hiển thị "WIP · Coming soon" state. |

#### 5.2.3 View toggle (giữ nguyên)

Giữ `🃏 Card` / `☰ List` segmented toggle. Skill cards hiển thị đúng layout.

#### 5.2.4 Back-path navigation

Breadcrumb hiện tại `🏠 Hub / Category / Skill` cần **clickable từng segment**:
- Click `🏠 Hub` → back home (state filter=all nguyên vẹn như cũ).
- Click **Category segment** (VD: `🔥 Discovery`) → về home với filter chip = category đó (chỉ hiện skills trong nhóm).
- Skill segment không click (trang hiện tại).

### FR-CSV · GMGN-format CSV catalog export & cross-check

#### 5.3.1 Output file 1: CSV mới (lưu tại thư mục cùng marketplace)

Tạo file mới: `/Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/Birdeye Data Skills - skills-builtin-revised.csv`.

Columns **EXACT match marketplace-catalog.csv** (9 columns, headers preserved tiếng Anh, để import vào GMGN format trực tiếp):
```
skill name, display title, trader question, description, category, stage, difficulty, core_calls, core_capabilities, example_prompts
```

Dữ liệu rows:
- **Rows 1–31**: Export 31 skill hiện tại từ `_30_SKILLS_CATALOG` literal (chuyển sang CSV format). Map:
  - `category` (marketplace có 5 values GMGN gốc: Discovery / Token Analysis / Wallet Intelligence / Monitor / + các nhóm Trading/Data Analytics/Monitor/News/Cooking): **31 skill map theo matrix**: Discovery→Discovery, Token DD→Token Analysis, Smart Money→Wallet Intelligence, Security→Token Analysis, Chain→Data Analytics, Charts→Data Analytics, Alerts→Monitor, Utils→Utils.
  - `stage` = DISCOVER/RESEARCH/DECIDE/MONITOR (từ DD workflow step 10).
  - `difficulty` = Basic/Intermediate/Advanced.
  - `core_calls` = danh sách endpoint Birdeye cách dấu phẩy (VD: `market trending-5m, token_security, token_overview?includes=money_flow`).
  - `core_capabilities` = summary 1–2 capabilities (dùng `desc` hiện tại).
  - `example_prompts` = 2 example prompts tiếng Anh ngắn.
- **Rows 32–48**: "Reference rows from GMGN marketplace" 17 skills chưa implement được đánh dấu stage="BACKLOG" (để user revise, chuyển thành Birdeye native skill sau). 2 dòng đầu tiên của block này đánh dấu cột đầu tiên `## GMGN marketplace — BACKLOG REFERENCE` để phân biệt.

#### 5.3.2 Cross-check report (inline trong CSV bằng comments)

- Top 2 hàng CSV (bắt đầu bằng `#`): 
  ```
  # Total skills: 31 BUILTIN (5 LIVE) + 17 BACKLOG (from marketplace 48 GMGN reference) = 48 rows
  # Coverage LIVE = 5 / 48 = 10.4%  ·  Source builtin: birdeye_ui.py _30_SKILLS_CATALOG JSON  ·  Source ref: marketplace-catalog.csv
  ```

#### 5.3.3 Logo Birdeye local

- Lưu logo Birdeye Data (SVG hoặc PNG nhỏ 32x32 default icon cho skill nếu chưa có custom icon) vào local file: `/Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/assets/birdeye-logo.svg`
- Nếu user không cung cấp PNG, tạo SVG placeholder inline: đường tròn xanh dương + chữ "BE" trắng (minimal, dùng data URI trong CSS if needed).

### FR-OPS · Python server start/stop/command ops

#### 5.4.1 Start command

```bash
cd /Users/nguyenthenang/nang/birdeye/app/skills
python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload
```

| Flag | Mô tả |
|---|---|
| `--host` | Default `127.0.0.1`. Mở cho LAN/WiFi → dùng `0.0.0.0`. |
| `--port` | Default `8765`. Đổi nếu bị chiếm. |
| `--reload` | **Hot code edit**: Mỗi request đọc lại `UI_HTML` từ disk → chỉnh sửa JS/CSS inline không cần restart server. **Lưu ý: KHÔNG áp dụng cho `Handler.do_GET/do_POST` code bên ngoài `_build_ui_html()` (cần restart).** |

#### 5.4.2 Stop command (2 options)

- **Option A (interactive, terminal đang foreground)**: Nhấn `Ctrl+C`.
- **Option B (tách terminal, kill bằng PID)**:
  ```bash
  # Tìm PID (cột 2)
  lsof -ti:8765
  # Kill PID đó
  lsof -ti:8765 | xargs kill -9
  # Hoặc kill tất cả process có tên birdeye_ui
  pkill -9 -f "birdeye_ui"
  # Verify port đã free
  lsof -i :8765   # (nếu không trả gì = OK)
  ```

#### 5.4.3 Background run (tmux/screen) + log

```bash
# Nền, log ra file
cd /Users/nguyenthenang/nang/birdeye/app/skills
nohup python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload > /tmp/birdeye-hub.log 2>&1 &
echo $! > /tmp/birdeye-hub.pid   # Lưu PID
# Đọc log live
tail -f /tmp/birdeye-hub.log
```

### FR-SECURITY-API · RugCheck-style Security API module design (NEW)

> **Mục tiêu**: Add module "Skill #4 · RugCheck-style Risk Audit" = 1 endpoint wrapper trả về cấu trúc **giống rugcheck.xyz** (7 risk cards + Overview 13 fields) **100% sử dụng Birdeye API native** (không crawl rugcheck web).

#### 5.5.1 Endpoint design

```
GET /defi/v3/token/rugcheck?address=<TOKEN_ADDRESS>&chain=<sol|bsc|base|eth>
→ Authorization: X-API-Key (Birdeye)
→ CU estimate: 90 CU (overview 18 + security 30 + holder-distribution 30 + liquidity-ohlc 10 + fee flow 2 = ~90)
```

#### 5.5.2 Response JSON (mapping 13 fields Overview)

Sử dụng Birdeye API đã có (section 0 map DD workflow):

| RugCheck UI field (13 overview fields) ↓ | Birdeye native source ↓ | CU ↓ | Status ↓ | Response key ↓ |
|---|---|---|---|---|
| Supply | `/defi/token_overview.supply` | 18 (incl overview) | ✅ Có | `supply` |
| Creator | `/defi/token_security.ownerAddress` or `creator` field | +30 | ✅ Có | `creator` |
| Creator Balance % | Holder step 4 top-holders + match creator | +30 | 🔧 Proxy join | `creator_holding_pct` |
| Market Cap | `/overview.marketCap` | overview | ✅ Có | `market_cap_usd` |
| Holders | `/overview.holder` | overview | ✅ Có | `holder_count` |
| Mint Authority (renounced?) | `/security.ownerAddress = null` | security | ✅ Có (Solana) | `mint_authority_renounced` bool |
| Metadata Authority | `/security.ownerAddress` OR `/security.mutableMetadata` | security | ✅ Có | `metadata_authority_renounced` bool |
| Transfer Fee | Birdeye `/token_security.transferFee` (một số chains) | security | 🔧 Premium | `transfer_fee_bp` (basis points) |
| Max Fee | — | — | ❌ Missing → proxy max(TransferFee observed) | `max_fee_bp` |
| Fee Authority | `/security.ownerAddress` | security | 🔧 Proxy | `fee_authority_live` bool |
| Withheld Fee Authority | — | — | ❌ Not in Birdeye → N/A | `withheld_fee_authority_live` or `null` |
| LP Locked % | `/security.lpLocked` + OHLC liquidity min vs current | security +10 | ✅ Có | `lp_locked_pct` |
| Liquidity ($) | `/overview.liquidity` | overview | ✅ Có | `liquidity_usd` |

#### 5.5.3 Response JSON 7 Risk Cards (mỗi card có: id, label, severity, passed boolean, details string)

```
risk_cards: [
  { id: "lp_unlocked",    label: "Large Amount of LP Unlocked", severity: "CRITICAL", passed: bool, detail: f"{lp_unlocked_pct}% unlocked, threshold <10%" },
  { id: "top10_conc",     label: "Top 10 Holders High Ownership", severity: "HIGH",     passed: (top10_pct<40), detail: f"{top10_pct}% held by top 10 holders" },
  { id: "low_liquidity",  label: "Low Liquidity",                severity: "MEDIUM",   passed: (liq_usd >= 10_000), detail: f"${liq_usd} vs min $10k" },
  { id: "mc_per_holder",  label: "High MC per Holder",           severity: "MEDIUM",   passed: (holders>100 || mc_usd < 500_000), detail: f"${mc_usd/holders} per holder" },
  { id: "few_lp_provider",label: "Few LP Providers",             severity: "LOW",      passed: (lp_provider_count>=5), detail: f"{lp_provider_count} unique LPs observed" },
  { id: "transfer_fee",   label: "Fee Config Enabled",           severity: "LOW",      passed: (transfer_fee_bp<=100), detail: f"{transfer_fee_bp} bps fee ≤ 1%" },
  { id: "mutable_meta",   label: "Mutable Metadata",             severity: "LOW",      passed: not metadata_mutable, detail: "Immutable if authority renounced" }
]
```

#### 5.5.4 Holders tab (#holders anchor)

```
GET /defi/v3/token/rugcheck/holders?address=<T>&chain=<C>&top_n=20
→ holder table 20 rows: [owner_address, balance_tokens, balance_usd, pct_of_supply, tag_guess (dev/sniper/bundler/smart/none)]
→ Source: holder/v1/distribution (CU 30) join top_traders tags.
```

### FR-SCORE-EXPLAIN · SMKT và SEC/ACT/VOL Scorecard Explain

Document score component inline UI (tooltip hover) + doc file:

| Score | Tên đầy đủ | Weight | Base | Logic chấm điểm (CLI source L776-878 birdeye_cli.py) |
|---|---|---|---|---|
| **SEC** | **Security** (Contract & Holder Concentration) | **30%** (cao nhất) | 5.0 | +3 nếu dev% <2; +2 nếu dev% 2–5; +1 nếu 5–10; -2 nếu dev>10%; +2 top10 holder <20%; +1 top10 20–40%; -2 nếu top10>40%; `=0` nếu honeypot=true; +1 nếu lpLocked; clamp 0–10. |
| **SMKT** | **Smart Market Fit** (Độ quan tâm của Smart Money + xếp hạng SM global) | **25%** | 5.0 | ✏ **Giải thích SMKT = gì**: Đo lường token có nằm trong radar **Smart Money (SM) global top 100 hay không** (dữ liệu từ endpoint `/smart-money/v1/token/list` của Birdeye). Chấm theo 2 dimensions: (1) rank trong SM top 100 (`sm_rank`): nếu rank ≤10 → +4 cực mạnh, rank 11–30 → +3 mạnh, 31–60 → +2 khá, còn lại +1 có; (2) **nếu không có rank (chưa vào top) nhưng có sm_no (số lượng SM wallets holding) ≥ 20 wallets** → +2 (đủ tổ chức theo dõi). Clamp 0–10. |
| **ACT** | **Activity (Dòng tiền + Buy/Sell ratio + Momentum)** | **25%** | 5.0 | Buy ratio interval cuối cùng (0–1): ≥0.62 mua mạnh +3; 0.55–0.61 +2; 0.51–0.54 +1; ≤0.38 bán tháo -3; 0.39–0.45 -2. **SM wallet count (sm_no)**: ≥30 +3; 10–29 +2; 3–9 +1. Trend slope (Δ 4h − Δ5m): >+30 bứt phá +1; <−30 sụp đổ -1. Clamp 0–10. |
| **VOL** | **Volume Acceleration (Tăng trưởng Volume qua các cửa sổ thời gian)** | **20%** | 5.0 | Với chuỗi volume windows (5m→1h→4h→24h): +1 điểm mỗi khi volume window sau > window trước (count ups). Nếu không có window nào tăng (=0 ups) → −2. Clamp 0–10. |
| **⭐ FINAL** | Composite weighted tổng | 100% | — | `FINAL = SEC·0.30 + SMKT·0.25 + ACT·0.25 + VOL·0.20`. Clamp 0–10. **Verdict**: ≥7.5 STRONG BUY / ≥6.2 BUY / ≥5.0 HOLD·WATCH / ≥3.5 AVOID / <3.5 SELL·RED FLAG. **Roadmap penalties (áp dụng sau depth STANDARD)**: −1.5 nếu LP Drawdown 24h >30%, −1 nếu BotVolProxy>40%, −0.5/tag nếu tag%supply>25% mỗi tag. → Rating letter S/A/B/C/D/F/NG theo birdeye-dd-workflow.md L86-L94. |

### FR-DD-SPEC · Token DD API requirement spec (Appendix links 🔗)

Vị trí tài liệu tham khảo chính (đã có, KHÔNG tạo file mới):

1. **[birdeye-dd-workflow.md](file:///Users/nguyenthenang/nang/birdeye/app/skills/birdeye-dd-workflow.md)** (3600+ lines, đã có)
   - Section 0: Inventory field → source → CU → status ✅/🔧/❌
   - Section 1: 10-step flowchart + CU breakdown worst-case 266 CU
   - Section 2: Rating table S→NG (FINAL 0–10)
   - Section 3: 10 user-fields → endpoint mapping table
   - Section 4: 4-phase roadmap codebase, 5 bugs pitfall
2. **[birdeye_cli.py `cmd_dd` + scoring block L776-880](file:///Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_cli.py#L760-L880)** — actual implementation (MVP FAST mode 71 CU = steps 1+3+8 + money_flow inside overview)
3. **[birdeye_ui.py `makeDDRenderFromPayload` L944-L1068](file:///Users/nguyenthenang/nang/birdeye/app/skills/birdeye_ui.py#L944-L1068)** — render scorecard HTML (SEC/SMKT/ACT/VOL/FINAL cell, SM txt, risk pills, 5 BS rows, invariants).

**Summary API spec (appendix, được thêm vào HEAD birdeye-dd-workflow.md)**:

> **Quick API Summary (Token DD)**:
> | Layer | Endpoint Birdeye | Method | Params | Response field (sample) | CU |
> |---|---|---|---|---|---:|
> | 1. Core | `/defi/token_overview` | GET | address, chain, includes=money_flow | price,marketCap,fdv,liquidity,holder,priceChangeXhPercent,moneyFlow[] | 21 |
> | 2. Liq Min/Max/Drawdown | `/defi/v3/liquidity-ohlc-token` | GET | address,type,time_from,time_to | tvlH,tvlL,tvlO,tvlC | 10–20 |
> | 3. Security | `/defi/token_security` | GET | address | honeypot,lpLocked,creatorPct,top10HolderPct,ownerAddress,freezeAuthority | 30 |
> | 4. Top20 Holders | `/holder/v1/distribution` | GET | token_address,mode=top,top_n=20,include_list | holders[{owner,amount,pct,usd_value}] | 30 |
> | 5. Tag% hold | `/token/v1/holder-profile` | GET | token_address | tags[{tag, percent_of_supply, holder_count, avg_buy, pnl}] | 30 |
> | 6. Top10 Traders/PnL | `/defi/v2/tokens/top_traders` | GET | address,time_frame,sort_by,limit | traders[{wallet, volumeUsd, realizedPnl, tags[]}] | 30 |
> | 7. Fee flow venue | `/defi/v3/token/fee/single` | GET | address, interval | feeByDex[], feeByTip[], feeByStable[] | 10–20 |
> | 8. Smart Money global | `/smart-money/v1/token/list` | GET | limit≤20,time_range,sort_by | tokenList[{addr, smart_traders_no, rank_in_sm_top100}] | 20 |
> | 9. Mint/Burn Integrity | `/defi/v3/token/mint-burn-txs` | GET | address, limit | txs[{type, amount, ts, owner}] | 10–15 |
> | 10. Rating A..F/NG | Client-side compute | N/A | SEC·30 + SMKT·25 + ACT·25 + VOL·20 − 3 penalties | 0 |

---

## 6. Non-functional Requirements (NFR)

| ID | Rule | Evidence |
|---|---|---|
| NFR1 | **CU neutral**: Theme toggle + skill cards filter navigation = 0 CU (local JS state, không gọi API). | Browser network tab 0 POST /api/run sau 10 navigations category/skills. |
| NFR2 | **Theme switch 0 flicker**: CSS variables apply trong `<head>` inline script trước paint. | Screenshot 10 navigations dark→light ko thấy white frame. |
| NFR3 | **Server hot reload apply theme + home nav edit on next page load** (không cần kill server). | Make edit in `_build_ui_html` literal → refresh page → UI reflects. |
| NFR4 | **CSV UTF-8**: BOM-free, encoding UTF-8, open được trong Numbers/Excel/Google Sheets. | `file -I` returns utf-8; `head -5` parse OK 9 columns. |
| NFR5 | **Score explain renders 600ms** click hover tooltip trên scorebar cells. | Timeit JS: open 5 tooltip avg <600ms. |
| NFR6 | **Back path preserve state**: từ drill → back home → filter state + view state (card/list) nguyên vẹn. | STATE.homeFilter + STATE.homeView preserved. |

## 7. Constraints / Assumptions

- **Constraint 1**: Logo birdeye local được tạo placeholder SVG nếu user không cung cấp PNG artwork.
- **Constraint 2**: RugCheck API module design là document spec + UI scaffold ONLY, implementation calls thực tế (holder-profile, fee flow, mint-burn)留 cho phase sau.
- **Constraint 3**: API Key load order preserved (1. paste UI 2. env 3. ~/.birdeye.env).
- **Assumption 1**: Score weights 30/25/25/20 user OK, không muốn thay đổi (chỉ explain).
- **Assumption 2**: Category map 31 skills → 4 GMGN groups (Trading/Data Analytics/Monitor/Utils) OK cho CSV.

## 8. Open Questions (TBD — user cần clarify trước Implement phase)

| OQ | Câu hỏi | Giả định default | Impact nếu sai |
|---|---|---|---|
| **OQ1** | Skill card metrics `👁 views` / `↓ usage`: muốn dùng **mock giá trị từ CSV marketplace** (13.9K, 4.42K v.v.) hay **tính từ lịch sử chạy thực của user trong cache runs `/~/.cache`** (tổng count run actual + CU spent)? | Giả định **actual history-based** (tổng số lần click run + CU từ last 30 days cache). Nếu muốn mock theo CSV thì dễ hơn (data cứng). | Xác định code path duyệt cache |
| **OQ2** | RugCheck Security API design: muốn implement CLI command thực tế (tên `rugcheck <addr>`) ngay trong cycle này hay chỉ dừng ở **doc scaffold only**? | Giả định **doc + UI scaffold only** (WIP skill, không gọi thật, save CU). | Nếu implement = +200 lines CLI code, cần thực tế call 5 endpoints. |
| **OQ3** | Theme light mode: có muốn option "Follow System" (auto theo macOS appearance) làm thêm mode thứ 3 `🌓`? | Giả định **chỉ 2 modes dark/light toggle** (button duy nhất). | Nếu thêm system mode → thêm 1 detect media query prefers-color-scheme. |
| **OQ4** | CSV export: cần định dạng theo `Birdeye-LLMS` skill format (SKILL.md + metadata routing) hay **chỉ CSV 9 cột như marketplace reference** là đủ? | Giả định chỉ CSV 9 cột như user nhắc "giống format của gmgn cho đủ mọi option command và steps". | Nếu cần SKILL.md per skill = 48 file SKILL.md. |

---

## 9. Acceptance Criteria (RULE hoặc RUBRIC)

### THEME acceptance

| # | Type | Criterion |
|---|---|---|
| AC-T1 | RULE | On boot, theme default = dark. localStorage['be.theme'] chưa set → render dark palette. |
| AC-T2 | RULE | Click sun icon (theme=dark) → toàn bộ palette biến đổi sang light, button đổi sang moon icon. localStorage ghi 'light'. Refresh page → vẫn light. |
| AC-T3 | RULE | All existing UI elements (scorebar cells, chips, badges, format segmented buttons, sidebar groupHeaders, breadcrumb, input/textareas) **render OK both themes** — không có text trắng trên nền trắng hoặc vi phạm contrast <3:1. |
| AC-T4 | RUBRIC (0-2) | Fidelity theme switch: 2 no flicker+CSS vars only, 1 flicker <30ms acceptable, 0 white-flash>100ms or broken elements. ≥1 pass. |

### HOME-NAV acceptance

| # | Type | Criterion |
|---|---|---|
| AC-H1 | RULE | Home top: filter chips bar All + 8 categories visible. Click `Discovery` → chỉ hiện skill cards trong nhóm Discovery (3 cards). |
| AC-H2 | RULE | Skill card mỗi skill hiển thị đủ 6 thành phần: icon, title, 2 tag pills (GMGN + category), short desc, 2 metrics, Detail/Run button. |
| AC-H3 | RULE | Click `Detail` button trên skill "🛡 Token Due Diligence" → vào Drill sidebar với STATE.skill='dd', breadcrumb "🏠 Hub / 🛡 Token Due Diligence / Skill #3 · Token DD". Click 🏠 Hub breadcrumb segment (🏠 Hub) → back về home filter state = `all` (hoặc category nếu từ group chip). |
| AC-H4 | RUBRIC (0-3) | GMGN Marketplace fidelity skill card layout: 3 exactly 1:1, 2 close enough minor diff, 1 readable but major diff, 0 unusable. ≥2 pass. |

### CSV + LOGO acceptance

| # | Type | Criterion |
|---|---|---|
| AC-C1 | RULE | New file `Birdeye Data Skills - skills-builtin-revised.csv` tồn tại ở đúng folder. Header row = marketplace 9 columns + 2 comment rows đầu tiên start với `#`. Tổng 48 rows data (31 BUILTIN + 17 BACKLOG). |
| AC-C2 | RULE | 31 builtin skill rows có `skill name` prefix "birdeye-", display title đúng từ catalog 30 literal. category value khớp với mapping matrix 8→4 GMGN groups. |
| AC-C3 | RULE | File logo birdeye-logo.svg (placeholder OK) tồn tại tại assets/ folder. |
| AC-C4 | RUBRIC (0-2) | Cross-check coverage: 2 all 48 CSV rows validated unique skill name + non-empty title/desc/category; 1 missing <2; 0 broken structure. ≥1 pass. |

### SERVER OPS acceptance

| # | Type | Criterion |
|---|---|---|
| AC-O1 | RULE | Chạy start command `python3 birdeye_ui.py --port 8765 --host 127.0.0.1 --reload` trong folder skills → server prints "[UI] 🐦 Birdeye Skills Hub... URL 127.0.0.1:8765". `curl -s http://127.0.0.1:8765/ | head -5` trả về HTML. |
| AC-O2 | RULE | Chạy stop command `lsof -ti:8765 \| xargs kill -9`. Sau 2s lệnh `lsof -i :8765` → không có output (port đã giải phóng). |
| AC-O3 | RULE | Nohup background mode: start với nohup lưu PID → log file growing. Kill với `kill $(cat /tmp/birdeye-hub.pid)` → process exit code 0, PID file tồn tại không process zombie. |

### SCORE EXPLAIN + DD SPEC acceptance

| # | Type | Criterion |
|---|---|---|
| AC-S1 | RULE | Hover mỗi score cell SEC/SMKT/ACT/VOL/FINAL trong scorebar của any DD result → tooltip render giải thích đúng weight, base, logic chấm điểm (match table FR-SCORE-EXPLAIN). SMKT tooltip phải có dòng "SMKT = Smart Money global ranking + wallet count fit, weight 25%". |
| AC-S2 | RULE | Appendix đầu file birdeye-dd-workflow.md có section "Quick API Summary (Token DD)" 10-row table đúng spec. |
| AC-S3 | RUBRIC (0-2) | Score explain clarity: 2 cho đủ base/logic/threshold + ví dụ numerical; 1 thiếu ví dụ; 0 chỉ có tên gọi không đủ. ≥1 pass. |

### RUGCHECK API DESIGN acceptance

| # | Type | Criterion |
|---|---|---|
| AC-R1 | RULE | Design doc exists (section 5.5 spec này apply vào doc). Response 13 overview fields + 7 risk card objects + holders struct đều có type/key/source rõ ràng. |
| AC-R2 | RULE | CU breakdown tổng ≤ 90 CU per call được ghi rõ. Mỗi field có status ✅ (có sẵn)/🔧 (proxy)/❌ (missing) đúng với inventory. |
| AC-R3 | RUBRIC (0-3) | Implementability: 3 design rõ ràng tốn ≤4h dev, 2 unclear <1 day, 1 major gaps, 0 unimplementable. ≥2 pass. |
