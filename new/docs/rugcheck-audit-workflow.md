# Workflow · Skill #17b · RugCheck Risk Audit (Security)

## Overview

A live audit that mirrors the **rugcheck.xyz** format: 7 risk cards + liquidity min/max/drawdown + holder top-20 + insider/dev/sniper/bundle cohort analysis. Returns a risk score and a detailed breakdown.

- **Inputs:** `chain` (`sol`/`bsc`/`base`/`eth`) · `address` (token contract) · `--holders` (include the top-20 holder list)
- **Risk cards:** mint authority · freeze authority · LP lock · top-10 concentration · insider/dev holdings · sniper/bundle activity · buy/sell tax

> **Inspired by:** RugCheck.xyz token page (`/tokens/<ADDR>#holders`) 13-field summary + 7-card risk layout + top-holders table with tags. This is the **Birdeye-equivalent workflow**: it maps every RugCheck card to the exact Birdeye endpoint that powers it, lists the validation gates at each step, all CLI invocations (WIP subcommand `rugcheck`), and CU breakdown.
>
> **Demo reference token (Solana):** `BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK`

---

## 0. Skill Header & Equivalent Birdeye APIs

| Field | Value |
|---|---|
| **Skill id** | `rugcheck_risk_audit` |
| **Skill title** | Skill #17b · RugCheck Risk Audit |
| **Category** | 🔐 Security & Risk (Group 4/8) |
| **Architecture note** | **Same payload bytes as Skill #3 Token DD with `--include list,advanced_security` (STANDARD tier = 122 CU)**. Only renderer differs (7 cards vs scorecard). This guarantees `0 CU` format-switching between the two skills. |
| **CU cost (worst case FULL)** | **152 CU** = BASE(71) + list(30) + advanced_security(21) + risk_history_30d(30). Equivalent to Skill #3 DEEP tier. |
| **CU cost — 7-card lite / RugCheck default UI landing** | **122 CU** = `include=list,advanced_security` exactly (STANDARD tier). |
| **CU cost — minimal 90 CU legacy recipe (3 endpoints only, no tags/no drawdown)** | **90 CU** = overview+mf(21) + security(30) + holder-list(30) + 9 buffer. For users on a tight budget. |
| **CLI subcommand** | `rugcheck` (today implemented as an alias for `token-dd --include list,advanced_security` + renderer). |
| **UI status** | ✅ LIVE via Skill #3 payload rehydrate. |

### Reference UI equivalent vs RugCheck.xyz (`/tokens/<ADDR>#holders`)

For demo token `BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK`:

| What you see on RugCheck.xyz | Exact block (from /API/13.md) in our payload | CU adder |
|---|---|---:|
| Holder & User count + top10% (platform & user) | `BASE.price_mc_liq.holders_total` + `list.lp_concentration_pct.top_10_holders_pct_sum` + BASE security top10User% | 71 base + 30 list |
| Holder 24h change, Trader 24h change | `advanced_security.holder_deltas.{abs,pct}` + `trader_24h_delta_*` | 21 advsec |
| Liquidity Current / Min / Max / Drawdown 24h rolling | `advanced_security.liq_stats_24h_rolling.{curr,min,max,drawdown_24h_pct}` | 21 advsec |
| Liquidity Concentration % LP holder | `list.lp_concentration_pct.{top_2,cex_or_burn_pct}` | 30 list |
| Tags (Sniper/Bundler/Smart/KOL/Dev): % hold + (interpolated USD holding$) | `advanced_security.tag_cohorts_pct_holding_usd_interpolated[] {tag,pct_of_supply,holder_count,holding_usd_interp}` | 21 advsec |
| Volume 24h / 24 trades | BASE `volume_24h.v24h_usd` + `buys_count_24h + sells_count_24h` | 71 base |
| Bot Volume% and Bot Trade% of total | `advanced_security.volume_24h_bot_proxy.{bot_volume_usd_proxy_pct_of_total,bot_trade_count_proxy_pct_of_total}` | 21 advsec |
| Contract security (mint/honeypot/LP lock/etc.) | BASE `security.*` block (100% match) | 71 base |
| Risk score + Rating A–F/NG | BASE `score_final_0_10` + `rating` + adjusted by advsec penalties | 71 base + 21 advsec (adjusted) |
| **Include list** Top-20 holders detail | `holder_list[] {rank,owner,amount,pct,holding_usd_interp,tag_label}` | 30 list |
| **Include history** 30 daily risk score | `risk_score_daily[30] {ts_iso,final_score,rating,pillars}` (source: Đức) | 30 risk_history |

### CU 90 recipe (legacy — tight budget users, no tags/no drawdown detail)
```
  /defi/token_overview + includes=money_flow  = 21 CU   (price / MC / liq / holder / net flow)
  /defi/token_security                         = 30 CU   (creator% · top10% · honeypot · LP lock
                                                           mint/meta auth · freeze authority)
  /holder/v1/distribution  top_n=20            = 30 CU   (top-holders rows for the table)
  -----------------------------------------------------
  Real subtotal                                   81 CU
  Buffer (rounding, 429 retry, enrichments)        9 CU
  -----------------------------------------------------
  Labelled total                                  90 CU (shown in UI card, sidebar tag)
```

### 7-Card ↔ Birdeye Endpoint Mapping (LIVE 2026 schemaVersion 1 · exact paths)

| RugCheck UI Card | Exact Birdeye Endpoint(s) | Required include flag |
|---|---|---|
| **Card 1 — Mint / Supply integrity** (Mintable? Renounced? Freeze auth? + mint events count) | `/defi/token_security` (30 CU) + mint events WIP | BASE (always) |
| **Card 2 — Liquidity (Locked? Amount? Drawdown 24h%?)** | `/defi/token_overview?includes=money_flow` (21 CU) liq current + `/defi/token_security` lpLocked + `⚠ RC1 GAP: /defi/v3/liquidity-ohlc-token 404 all 6 paths tried` | BASE + list |
| **Card 3 — Honeypot Test** (sellable?) | `/defi/token_security` isHoneypot (EVM native; Sol = 3-flag proxy) | BASE (always) |
| **Card 4 — Creator / Dev holdings % + sell history (dev PnL)** | `/defi/token_security` creator% + **`/token/v1/holder-profile` (21 CU · param=`token_address=` NOT `address`)** tag=dev + 5 cohort tags | advsec (rug_advanced_security) |
| **Card 5 — Top-10 Holder concentration** (whale dump risk) | `/defi/token_security` top10Holder% + **`/holder/v1/distribution` (30 CU · mode=top, top_n=20, include_list=true, param=`token_address=`)** rows[0:10] sum cross-check | list (rug_holder_list) |
| **Card 6 — Tag cohort% (Sniper/Bundler/SmartMoney/Whale/Dev + Insider 6th)** | **`/token/v1/holder-profile` (21 CU · param=`token_address=` NOT `address`)** 5 tags: bundler→Bundle, sniper→Sniper, insider→Insider, smart_trader→SmartMoney, kol→Whale | advsec (rug_advanced_security) |
| **Card 7 — Bot-wash% proxy + Fee/Vol ratio (real vs wash volume)** | Money Flow (base 21 CU) volume$ + trades + cohort% proxy BotVol/BotTrade | BASE overview+mf |

---

> ## 🔴 CRITICAL ENDPOINT PARAM NAME — NEVER MISS THIS
> ### `/token/v1/holder-profile` REQUIRED param name = `token_address=`
> - **DO NOT USE plain `address` param** → Birdeye returns **HTTP 400 Bad Request** with `{"success":false,"message":"Missing required field: token_address"}`
> - This applies to BOTH:
>   1. RC2 `/holder/v1/distribution` (holder list topN) — use `token_address=<addr>`
>   2. RC3 `/token/v1/holder-profile` (cohort tags) — use `token_address=<addr>`
> - Reference docs (user supplied):
>   - Holder list top20: `https://data.birdeye.so/docs/data-api/holder/get-defi-v3-token-holder`
>   - Cohort tags 5 types: `https://data.birdeye.so/docs/data-api/holder/get-token-v1-holder-profile`

---

## 0b. RugCheck-Audit 5-Step Real Endpoint Call Checklist (122 CU TOTAL)

> This is the EXACT ordered call stack used by `cmd_rugcheck_audit` subcommand with `enable_rugcheck_extra=True`.
> Each call happens MAX 1 TIME — no duplicate fetches. CU tally = Σ per-step.

| Step # | Endpoint Path | Required Params | CU | What it powers | Cross-check Invariant |
|---:|---|---|---:|---|---|
| **1** | `GET /defi/token_overview?includes=money_flow` | `address=<addr>`, `chain=<chain>` | **21** | Hero header: price / MC / FDV / LIQ / holder count / 5 price-changes (5m/30m/1h/4h/24h) + Money Flow rows + Buy/Sell rows | `payload.price_usd × payload.supply ≈ payload.marketcap_usd` (±5%) |
| **2** | `GET /defi/token_security` | `address=<addr>`, `chain=<chain>` | **30** | Cards 1/3: mint / freeze / honeypot / creator% / **top10Holder%** / lpLocked heuristics | INVARIANT MAIN CHECK → `|payload.security.top10_holder_pct − sum(rugcheck.holders_raw[0:9].pct)| > 5%` → ⚠ `signal_gap` pill on Card 5 + exit code 5 |
| **3** | `GET /defi/v2/tokens/smart-traders-batch` (sm_batch) | `address=<addr>`, `limit=50`, `timeframe=30d` | **20** | Smart Money pillar (used for Score + cohort cross-ref) | Optional |
| **4** | `GET /holder/v1/distribution` (RC2 holder list) | **`token_address=<addr>`** (NOT `address`), `mode=top`, `top_n=20`, `include_list=true` | **30** | Card 5 (Top-10 %) + Holders Tab 20 rows (rank/owner/pct/usd$/tag label JOIN step 5) | `len(rugcheck.holders_raw) ≤ top_n (20)`; sum rank 1–10 → cross-check step 2 |
| **5** | `GET /token/v1/holder-profile` (RC3 cohort tags) | **`token_address=<addr>`** (NOT `address`), `limit=50` | **21** | Card 6 Cohort Breakdown 5 badges (Bundle/Sniper/Insider/SmartMoney/Whale) + tag JOIN → label each holder row in Tab Holders | Tag Σ% ≤ 105 (sanity clamp; >105% → pipeline_gap + clamp at 100%) |
| **6 (WIP 404)** | `GET /defi/v3/liquidity-ohlc-token` (RC1 liq drawdown) | `address=<addr>`, `time_from=<ts-24h>`, `time_to=<ts_now>`, `interval=1h` | **0 (gap)** | Card 2: liq_min / liq_max / drawdown% 24h | CURRENTLY **404 across 6 path combos** → gap `rug_liq_hist_all_paths_failed` added to gaps[]; fields NULL; NO scoring impact |
| | | **Σ TOTAL CU** | **122** | Full 5-tab RugCheck render (Overview / Markets / Insiders / Holders / Lockers & LP) | `sum(step1…step5) === 21+30+20+30+21 === 122` footer ⚡CU must match |

### CU Breakdown String Format (CLI `cu_breakdown` field — today STRING type)
```
overview_+mf=21 + security=30 + sm_batch=20 + rug_holder_list=30 + rug_advanced_security=21 = 122 CU
```

### Cross-Check Invariants (non-negotiable — fail = ⚠ pill + exit code 5)
| Invariant Formula | Tolerance | Fail behavior |
|---|---:|---|
| `| payload.security.top10_holder_pct  −  Σ rugcheck.holders_raw[0:9].pct |` | ±5 pct pts | ⚠ `signal_gap` pill on Card 5 + footer `signal_gap_count++` + exit code 5 |
| `Σ all 5 cohort tags .percent_of_supply` | ≤105% total | >105% → clamp 100% + `pipeline_gap_count++` |
| `payload.marketcap_usd` (from overview) vs `payload.security.mcap` cross-source diff | ±20% | Diff>20% → `pipeline_gap` pill Hero MC |
| `payload.liquidity_usd` (overview) vs `rugcheck.liq_current_usd` (if endpoint returns it) | exact (same source) | Mismatch → `pipeline_gap` footer +1 |

### Cross-links
- Modular include concept design source → `/API/13-modular-token-dd-include-api.md` (same include=list + advanced_security + risk_history selector paradigm)
- Low-level endpoint recipes → `/API/12-rugcheck-risk-audit-skill17b.md` (tier tables per card)
- Tag / holder endpoints → `/API/04-holder-distribution.md`, `/API/05-holder-profile-top20.md`
- Security + mint → `/API/03-token-security.md`
- Parent 10-step DD workflow (BASE 71 CU) → [`token-dd-score-workflow.md`](./token-dd-score-workflow.md)

---

## 1. Prerequisites (Preflight · 0 CU)

Same address / chain / key gates as Token DD:

| # | Check | Example |
|---|---|---|
| 1 | API key present | session / env / ~/.birdeye.env → head2****tail2 non-empty |
| 2 | Address valid for chain (see regex in [`token-dd-score-workflow.md`](./token-dd-score-workflow.md)) | Sol: `^[1-9A-HJ-NP-Za-km-z]{32,44}$` · EVM: `^0x[a-fA-F0-9]{40}$` |
| 3 | Chain ∈ {sol,bsc,base,eth} | Default = sol |

---

## 2. Step-by-Step 7-Card Checking Workflow (90 CU)

```
START: Input (address, chain)  ── preflight 0 CU ──▶ PASS/FAIL
  │
  ▼
CALL 3 ENDPOINTS IN PARALLEL (fan-out — saves wall-clock):
  │  ┌─ A: /defi/token_overview?includes=money_flow      (21 CU)
  │  ├─ B: /defi/token_security                          (30 CU)
  │  └─ C: /holder/v1/distribution  top_n=20  (⚠ param = token_address) (30 CU)
  │
  ▼
CARD 1 · MINT / SUPPLY INTEGRITY  ← payload B + (optional D: mint-burn events)
  ├─ Solana:
  │    mint_authority_renounced = (B.ownerAddress === null)
  │    freeze_auth_live         = B.freezeAuthority === true
  │    mutable_metadata         = B.mutableMetadata === true
  │    mint_events_24h          = D (WIP) count from /defi/v3/token/mint-burn-txs limit=10
  │    TIER:
  │     CRIT 🔴 → mint NOT renounced + ≥3 mint events 24h        → forces RUG SCORE = 10
  │     HIGH 🟠 → mint NOT renounced, 0 mint events
  │     MED  🟡 → mint renounced  ✓  but freeze auth still live
  │     LOW  🟢 → mint renounced  ✓ + freeze disabled ✓ + meta immutable ✓
  └─ EVM:
       isHoneypot = B.isHoneypot; mintable = proxy via fields
       (native honeypot flag for EVM makes CARD 3 redundant for EVM)
  │
  ▼
CARD 2 · LIQUIDITY + LOCK + DRAWDOWN  ← payloads A (liq curr) + B (lpLocked) + E (drawdown WIP)
  ├─ liquidity_usd = A.liquidity
  ├─ lp_locked      = B.lpLocked  (boolean; Sol = heuristic)
  ├─ lp_drawdown_24h_pct = (liquidity_high_24h − liquidity_low_24h)/liquidity_high_24h × 100
  ├─ TIER:
  │    CRIT 🔴 → liquidity < $5,000   OR   drawdown > 60%
  │    HIGH 🟠 → liquidity $5k – $25k  OR  drawdown 30–60%
  │    MED  🟡 → lpLocked = false  (regardless of amount)
  │    LOW  🟢 → lpLocked = true   AND  liquidity ≥ $100k AND drawdown < 15%
  └─ Always show: "LP Locked: YES/NO" badge; if NO → 🟡 MED minimum tier
  │
  ▼
CARD 3 · HONEYPOT (sellability test)
  ├─ EVM: isHoneypot = B.isHoneypot  (native Birdeye — GOLD TRUTH)
  │    CRIT 🔴 → true  (forces RUG SCORE = 10 — NO-GO)
  │    LOW  🟢 → false
  └─ Solana (proxy, no native flag):
       CRIT 🔴 → ownerAddress != null AND top2 hold > 50% combined AND net flow sell-ratio 4 frames > 70%
       HIGH 🟠 → top2 hold > 40%
       LOW  🟢 → none of above (sellability assumed OK — label "🔎 proxy only, not a guarantee")
  │
  ▼
CARD 4 · CREATOR / DEV HOLDINGS + EXIT BEHAVIOUR
  ├─ creator_pct = B.creatorPercentage × 100   (raw is usually 0…1 float)
  ├─ dev_tag_pct = F (WIP) /token/v1/holder-profile → tag:dev percent_of_supply
  ├─ TIER:
  │    CRIT 🔴 → creator% > 10%   OR   dev_tag still hold > 10% after > 7 days since launch
  │    HIGH 🟠 → creator% 5–10%
  │    MED  🟡 → creator% 2–5%
  │    LOW  🟢 → creator% < 2% AND dev tag exited or < 1%
  └─ Extra: show dev PnL (unrealized) from tag join; big profit + high hold = 🟠
  │
  ▼
CARD 5 · TOP-10 HOLDER CONCENTRATION (whale dump risk)
  ├─ top10HolderPct = B.top10HolderPercent × 100
  ├─ whale_sum = sum(C.rows[0..9].percent_of_supply)  (cross-check vs B value; diff > 5% → ⚠ signal_gap)
  ├─ TIER:
  │    CRIT 🔴 → top10 > 70%
  │    HIGH 🟠 → top10 50–70%
  │    MED  🟡 → top10 40–50%
  │    LOW  🟢 → top10 < 40%
  └─ Bonus for UI: show top-2 CEX (known addresses) separately to avoid penalizing cold-wallet CEX burns
  │
  ▼
CARD 6 · TAG COHORT % HOLDING DISTRIBUTION (5 tags + KOL proxy)
  ├─ F (WIP) /token/v1/holder-profile 5 tags native for Sol:
  │    dev / bundler / sniper / insider / smart_trader
  │    each → percent_of_supply, holder_count, avg_buy_price, pnl_usd
  ├─ KOL% = G (WIP) /defi/v2/tokens/top_traders top-10 PnL > $100k AND tags not in set → proxy KOL
  ├─ TIER:
  │    CRIT 🔴 → bundler% > 20% (launch pump&dump left bags with no retail)
  │    HIGH 🟠 → sniper% > 30% OR tag single > 30% (heavy concentration)
  │    MED  🟡 → insider% + bundler% > 20%
  │    LOW  🟢 → 5-tag sum < 20% AND no tag > 10%
  └─ Holding $ interpolated = tag.percent_of_supply / 100 × circulatingSupply × price (client calc, 0 CU)
  │
  ▼
CARD 7 · BOT-WASH% PROXY + FEE/VOL RATIO (is volume real or wash?)
  ├─ H (WIP) /defi/v3/token/fee/single  → totalFeeUsd_24h
  ├─ fee_vol_ratio = totalFeeUsd / A.v24hUSD × 100
  ├─ BotVolProxy  = F (tag step) insider% + bundler%
  ├─ BotTradeProxy = clamp(A.trade24h / A.uniqueWallet24h, 1, 100)
       → normal user churn ≈ 3..10; ratio > 30 = heavy wash likely
  ├─ TIER:
  │    CRIT 🔴 → fee_vol_ratio < 0.1%  (swaps don't pay real fee → wash)
  │    HIGH 🟠 → BotVolProxy > 40%  OR  BotTradeProxy > 50
  │    MED  🟡 → fee_vol_ratio 0.1–0.2%
  │    LOW  🟢 → fee_vol_ratio > 0.4% AND BotVolProxy < 20% AND BotTradeProxy < 20
  └─ UI MUST always label this `Bot Proxy%` — never assert Birdeye has native bot detection
  │
  ▼
COMPUTE · RUG SCORE 0–10 (0 = safest, 10 = rug confirmed)
  ┌─────────────────────────────────────────────────────────┐
  │  rug_score = 0 (start)                                    │
  │  For each 7 cards: add its tier weight                      │
  │    CRIT 🔴 → +3.0        HIGH 🟠 → +1.5                     │
  │    MED  🟡 → +0.75       LOW  🟢 → +0                       │
  │  clamp [0, 10]                                               │
  │                                                              │
  │  OVERRIDES (short-circuit):                                  │
  │   · CARD 1 (mint):  mint not renounced + ≥3 mint/24h → SET 10│
  │   · CARD 3 (honeypot EVM native = true)           → SET 10  │
  │   · CARD 5 top10 > 70% AND liq < $25k             → min = 8 │
  └─────────────────────────────────────────────────────────┘
  │
  ▼
MAP · RUG TIER 0–10 → user-facing label

  RUG SCORE    LABEL        ACTIONABLE RECOMMENDATION
  ──────────────────────────────────────────────────────────
    0.0 – 1.9  🟢 LOW       "Looks clean. DYOR with DD Skill #3."
    2.0 – 3.9  🟡 CAUTION   "Minor flags. Deep dive DD before entering."
    4.0 – 5.9  🟠 ELEVATED  "Multiple red flags. Avoid size > 0.5% portf."
    6.0 – 7.9  🔴 HIGH      "HIGH RISK. No position > $100 unless degens play."
    8.0 – 9.4  ⛔ VERY HIGH "VERY HIGH RISK. Avoid or trivial size only."
    9.5 – 10   ❌ RUG / NG  "NO-GO. Honeypot / live mint auth / confirmed rug."
  │
  ▼
RENDER · 3 SECTIONS (RugCheck mirror):
  (1) 13-field OVERVIEW SUMMARY row  (address/symbol/price/MC/LIQ/holder/v24h/
      rug_score / tier / mint_status / lp_locked / honeypot / top10%)
  (2) 7 RISK CARDS CRIT/HIGH/MED/LOW  (the 7 cards above, color-coded)
  (3) TOP-HOLDERS TABLE  (holder/v1/distribution rows + wallet tag JOIN step 6)
  │
  ▼
CACHE + FOOTER
  ├─ run_id = rugcheck_BFgvTe3p…_<ts>.json
  ├─ footer: ⚡90 CU · ΔT ms · pipeline_gap count · signal_gap count
  └─ 0-CU re-render: user switches plain / telegram / render = payload rehydrate only
```

---

## 3. All CLI Commands (alias token-dd include-based + 90 CU legacy + native subcommand syntax)

```bash
# ============================================================
#  WORKDIR:  cd /Users/nguyenthenang/nang/birdeye/app/skills
#  CLI PATH: birdeye-screener/scripts/birdeye_cli.py
#
#  ARCHITECTURE (per Section 0):
#   rugcheck output = SAME PAYLOAD BYTES as Skill #3 token-dd with
#     --include list,advanced_security  (STANDARD 122 CU)
#   Only the renderer changes (7 cards vs scorecard). This means:
#     → 0 CU format switch between the two
#     → replay of any token-dd payload renders rugcheck instantly
#  CU options today:
#     TIGHT BUDGET  (3 legacy endpoints, no tag% no drawdown) =  90 CU
#     DEFAULT 7CRD  (list + advanced_security)                 = 122 CU
#     FULL + HIST30  (+ 30d risk daily snapshots, Đức source)   = 152 CU
# ============================================================

# ------------------------------------------------------------
#  [A] DEFAULT · 7-Card RugCheck Style  (include list + advsec · 122 CU)
# ------------------------------------------------------------
#  This is the canonical RugCheck-equivalent invocation. It
#  powers cards 1–7, tag cohort %, liq drawdown, holder table.
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list,advanced_security \
  --list-top-n 20 \
  --format rugcheck

# Telegram markdown (7 cards rendered inside markdown table cells):
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list,advanced_security \
  --format telegram-rugcheck > /tmp/tg-rugcheck-BFgv.md

# ------------------------------------------------------------
#  [B] TIGHT BUDGET · 90 CU Legacy 3-Endpoints Only (no tags, no drawdown)
# ------------------------------------------------------------
#  Mint / honeypot / top-10 concentration cards only. Use on
#  bulk sweeps of 50+ tokens (90 × N is much cheaper).
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list \
  --format rugcheck-lite

# ------------------------------------------------------------
#  [C] FULL · + 30 Day Risk History (source: Đức) · 152 CU
# ------------------------------------------------------------
#  Same as A + risk_score_daily[30] = 30 snapshots each with
#  { day_iso, final_score, rating, 4 pillars }. UI can render
#  1 final line chart or 4 pillars as stacked area chart.
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list,advanced_security,risk_history \
  --history-points 30 \
  --format rugcheck-full

# Quick check billed CU + rug tier + history count (jq one-liner):
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list,advanced_security,risk_history \
  --format raw-json | jq '
  {
    billed_cu:       .meta.cu_billed_total,
    cu_breakdown:    .meta.cu_breakdown,
    flags:           .meta.include_flags,
    rug_score_0_10:  .final_score,
    rating_letter:   .rating,
    tier_label:      (if      .final_score >= 8.0 then "🟢 LOW"
                      elif    .final_score >= 6.0 then "🟡 CAUTION"
                      elif    .final_score >= 4.0 then "🟠 ELEVATED"
                      elif    .final_score >= 2.0 then "🔴 HIGH"
                      elif    .final_score >= 0.5 then "⛔ VERY HIGH"
                      else                         "❌ RUG / NG" end),
    tag_cohorts_USD: [(.advanced_security // empty
                         | .tag_cohorts_pct_holding_usd_interpolated[]
                         | {tag, pct_of_supply, holding_usd_interp})],
    daily_points:    ([.risk_score_daily[]] | length)
  }'

# ------------------------------------------------------------
#  [D] 0 CU · Replay Existing Payload (format switch)
# ------------------------------------------------------------
#  Any token-dd run cached locally with list+advsec (or deeper)
#  can re-render as RugCheck cards without hitting Birdeye
#  again: 0 CU.
python3 birdeye-screener/scripts/birdeye_cli.py history --limit 10
# → pick a run_id that has include_flags containing list + advsec
python3 birdeye-screener/scripts/birdeye_cli.py replay-run \
  --run-id token-dd_BFgvTe3p_1760001234 \
  --format rugcheck

# ------------------------------------------------------------
#  [E] BATCH · Sweep Top 10 Trending → RugCheck for each
# ------------------------------------------------------------
#  Step 1: V3 TL (50 CU, 10 rows) → addr list
python3 birdeye-screener/scripts/birdeye_cli.py trending-list \
  --chain sol --limit 10 --mode v3 --format raw-json \
  | jq -r '.payload.rows[].address' > /tmp/tl10.txt
#  Step 2: 122 CU default 7-card rug × 10 = 1,220 CU sweep
while read a; do
  echo "=============================================="
  echo "TOKEN: $a"
  python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
    --chain sol --address "$a" \
    --include list,advanced_security --format rugcheck-lite \
    | head -30
done < /tmp/tl10.txt

# ------------------------------------------------------------
#  [F] COMPARE · Side-by-side with live RugCheck.xyz URL
#      (open in browser next to our output to tune heuristics)
# ------------------------------------------------------------
#  Reference demo token:
#    https://rugcheck.xyz/tokens/BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK
#  UI Next-Actions panel also exposes the 🌐 Open in Birdeye +
#  bookmark RugCheck row.
```

### Exit codes

| Exit | Meaning |
|---:|---|
| 0 | 7 cards rendered, rug_score computed |
| 2 | Arg/addr/key invalid (**0 CU**) |
| 4 | Birdeye upstream non-200 — partial CU possible on partial responses |
| 5 | Cross-check invariant failed: `B.top10HolderPct − sum(C.rows[:10].pct) > 5%` → render ⚠ signal_gap pill on CARD 5 + `tag_cohort_sum_over_105` if >105% |

---

## 4. Response Output (Demo ASCII 13-field summary + 7 cards)

### 13-field OVERVIEW SUMMARY (first row on page · 1-line scannable · matches RugCheck.xyz)

| # | Field | Source endpoint / include flag | Example value (BFgvTe3p demo) |
|---|---|---|---|
| 1 | Address (short) | input | `BFgvTe3p…g8UK` |
| 2 | Symbol / Name | BASE step1 overview | `RUGK · RugCheck Demo` |
| 3 | Price USD | BASE step1 | `$0.003421` |
| 4 | Market Cap | BASE step1 | `$3.42M` |
| 5 | Liquidity | BASE step1 | `$180K` |
| 6 | Holders | BASE step1 + `list` (top10% row) | `3,241 · top10%=28%` |
| 7 | Volume 24h | BASE step1 + advsec Bot proxy% | `$1.2M · Bot 28.4%$ / 31.1% trades` |
| 8 | Holder Δ 24h / Trader Δ 24h | `advanced_security` deltas | `+135 / +7.42% · +102 / +24.88%` |
| 9 | Liquidity roll 24h (curr/min/max/DD%) | `advanced_security` liq_stats_24h | `$180K / $98K / $195K · DD 49.7% 🟠` |
| 10 | Rug Score 0–10 | Client scorecard + advsec penalties | `5.8` |
| 11 | Tier label | 6-band tier map | `🟠 ELEVATED` |
| 12 | Mint auth / LP locked / Honeypot | BASE step3 security | `✅ RENOUNCED / ⚠ NO / 🟢 NO` |
| 13 | Top 10 Holder % (cross-checked vs list) | BASE step3 + `list` sum rank≤10 | `28% · diff vs list=1.2% OK` |

### Demo 7-card Render (format `rugcheck` · color-coded tier pills)

```
#RUN_ID  rugcheck_BFgvTe3p_1760001234    billed=122 CU  flags=list,advanced_security
────────────────────────────────────────────────────────────────────────────────────
 BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK   RUGK  Solana
 PRICE $0.003421  MC $3.42M  LIQ $180K  HOLDERS 3,241 (Δ24h +7.42%)
 V24H $1.2M  BOT: 28.4% VOL · 31.1% TRADES   TRADERS Δ24h +24.88%
 LIQ 24h: curr $180K / min $98K / max $195K → DRAWDOWN 49.7%
────────────────────────────────────────────────────────────────────────────────────
 RUG SCORE:  5.8 / 10   →   🟠 ELEVATED
 (0–1.9🟢LOW / 2–3.9🟡CAUTION / 4–5.9🟠ELEVATED / 6–7.9🔴HIGH / 8–9.4⛔VHIGH / 9.5+❌RUG)
────────────────────────────────────────────────────────────────────────────────────
 ┌─CARD 1──────────────────────────────┬─CARD 4────────────────────────────────────┐
 │ 🟡 MED  Mint / Supply Integrity     │ 🟠 HIGH Creator / Dev Holdings + Exit    │
 │                                      │                                          │
 │  Mint auth : RENOUNCED ✅ (owner=null)│  Creator%   : 1.2%         [SAFE <2%]   │
 │  Freeze    : DISABLED ✅              │  Dev tag %  : 0.8% (interp $8K)          │
 │  Mutable Md: YES (⚠ consider)         │  Dev PnL    : -$1.2K (mostly exited)     │
 │  Mint24h   : 0 events                │  Rating→    : HIGH 🟠 (>50% supply launch│
 └──────────────────────────────────────┴──────────────────────────────────────────┘
 ┌─CARD 2──────────────────────────────┬─CARD 5────────────────────────────────────┐
 │ 🟠 HIGH Liquidity / Lock / DD24h    │ 🟡 MED  Top-10 Holder Concentration      │
 │                                      │                                          │
 │  Liquidity  : $180,000               │  top10% B.SEC: 28.0%   list sum: 26.8%   │
 │  LP Locked  : ⚠ NO  (min MED tier)  │  diff 1.2% OK   ⚠ no signal_gap           │
 │  DD% 24h    : 49.7% 🟠               │  top20 sum  : 85.4%                      │
 │  Current / 24hmin / 24hmax           │  Top-2 sum  : 54.1% (whale dump risk)     │
 │   $180K / $98K / $195K               │  CEX/burn %: 8.2% (excluded from calc)   │
 └──────────────────────────────────────┴──────────────────────────────────────────┘
 ┌─CARD 3──────────────────────────────┬─CARD 6────────────────────────────────────┐
 │ 🟢 LOW  Honeypot (sellability)      │ 🟡 MED  Tag Cohort % Holding (6 tags)    │
 │                                      │                                          │
 │  EVM native : n/a (Solana)           │  #  TAG        %supply  count   $USD int │
 │  Sol proxy  : 3-flag rule PASS       │  1  sniper      4.8%     42   $48,000   │
 │     owner!=null+top2>50%+sell70%×4fr│  2  smart       3.3%     28   $33,000   │
 │                 → 0 TRUES → OK       │  3  kol_proxy   2.1%      6   $21,000   │
 │  WARNING    : 🔎 proxy only          │  4  dev         1.2%      1   $12,000   │
 │                                      │  5  bundler     0.6%      3    $6,000   │
 │                                      │  6  insider     0.4%      2    $4,000   │
 │                                      │     Σ 6 tags = 12.4%  (� <20%  ok)      │
 └──────────────────────────────────────┴──────────────────────────────────────────┘
 ┌─CARD 7──────────────────────────────────────────────────────────────────────────┐
 │ 🟡 MED  Bot-Wash % Proxy + Fee/Vol Ratio (Real volume?)                        │
 │                                                                                  │
 │  Fee USD 24h     : $4,200                                                        │
 │  Fee/Vol ratio   : 0.42%  (🟡 0.1–0.2%=MED; >0.4%=GREEN)                        │
 │  Bot Vol% proxy  : 28.4%  (threshold >40% → � HIGH)                             │
 │  Bot Trade% proxy: 31.1%  (threshold >50% churn → 🔴 HIGH)                       │
 │  WARNING         : Bot Proxy% always client calc — NEVER native Birdeye          │
 └──────────────────────────────────────────────────────────────────────────────────┘
────────────────────────────────────────────────────────────────────────────────────
 TOP-HOLDERS TABLE  (20 rows  ·  list include + tag label JOIN advsec)
  #  OWNER (short)          TAG      AMOUNT TOKENS      %SUPPLY    USD INTERP
  1  5xoEnd2Q...sFgT        kol_proxy  142,000,000        14.2%    $485,682
  2  9WzicdK8...Pd3m        smart       98,210,000         9.8%    $335,992
  3  ...                                                                   ...
 20  ApQxkF9c...2jRq        bundler      4,120,000         0.4%     $14,097
────────────────────────────────────────────────────────────────────────────────────
 ⚡122 CU (base 71 + list 30 + advsec 21) · ΔT 910 ms · snapshot 1760001234
 INVARIANTS: priceCalc OK · buySellSum OK · top10 diff=1.2% <5% (no signal_gap)
 Tag Σ%=12.4 <100 OK · drawdown formula verify OK · bot clamp not needed
 💾 re-render this exact output in telegram/rugcheck-full/scorecard = 0 CU
```

### Raw JSON top-level skeleton (matches `/API/13.md` payload shape — reuse Skill #3 bytes)

```jsonc
{
  "runId": "rugcheck_BFgvTe3p_1760001234",
  "kind": "rugcheck_risk_audit",
  "schemaVersion": 1,
  "meta": {
    "address": "BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK",
    "chain": "sol",
    "include_flags": ["list", "advanced_security"],
    "cu_billed_total": 122,
    "cu_breakdown": {"base_fast_71":71,"adder_list":30,"adder_advanced_security":21,"adder_risk_history_30d":0}
  },
  "score_pillars": { "sec": 6.2, "smkt": 5.8, "act": 7.1, "vol": 6.5 },
  "score_final": 5.8,
  "tier_label": "🟠 ELEVATED",
  "summary_13_fields": {
    "address_short": "BFgvTe3p…g8UK", "symbol": "RUGK", "name": "RugCheck Demo",
    "price": 0.003421, "mc_usd": 3420000, "liquidity_usd": 180000,
    "holders_total": 3241, "holders_top10_pct": 28.0,
    "v24h_usd": 1200000, "bot_vol_pct_proxy": 28.4, "bot_trade_pct_proxy": 31.1,
    "holder_24h_delta_pct": +7.42, "trader_24h_delta_pct": +24.88,
    "liq_dd_24h_pct": 49.7,
    "mint_renounced": true, "lp_locked": false, "honeypot": false
  },
  "risk_cards": [
    { "card": 1, "name": "Mint / Supply Integrity",  "tier": "MED",  "tier_emoji": "🟡",
      "fields": { "mint_renounced": true, "freeze": false, "mutable_meta": true, "mint_events_24h": 0 } },
    { "card": 2, "name": "Liquidity + Drawdown 24h", "tier": "HIGH", "tier_emoji": "🟠",
      "fields": { "liq_curr": 180000, "liq_locked": false, "drawdown_24h_pct": 49.7, "liq_min": 98000, "liq_max": 195000 } },
    { "card": 3, "name": "Honeypot Test",            "tier": "LOW",  "tier_emoji": "🟢",
      "fields": { "is_honeypot_evm": null, "sol_proxy_pass": true, "warning": "proxy only" } },
    { "card": 4, "name": "Creator / Dev Holdings",   "tier": "HIGH", "tier_emoji": "🟠",
      "fields": { "creator_pct": 1.2, "dev_tag_pct": 0.8, "dev_pnl_usd": -1200 } },
    { "card": 5, "name": "Top-10 Concentration",     "tier": "MED",  "tier_emoji": "🟡",
      "fields": { "sec_top10_pct": 28.0, "list_top10_sum_pct": 26.8, "diff_pct_pts": 1.2, "signal_gap": false, "top20_sum_pct": 85.4 } },
    { "card": 6, "name": "Tag Cohort %",              "tier": "MED",  "tier_emoji": "🟡",
      "fields": {
        "tag_rows": [
          {"tag":"sniper","pct":4.8,"count":42,"usd_interp":48000},
          {"tag":"smart","pct":3.3,"count":28,"usd_interp":33000},
          {"tag":"kol_proxy","pct":2.1,"count":6,"usd_interp":21000},
          {"tag":"dev","pct":1.2,"count":1,"usd_interp":12000},
          {"tag":"bundler","pct":0.6,"count":3,"usd_interp":6000},
          {"tag":"insider","pct":0.4,"count":2,"usd_interp":4000}
        ], "sum_pct": 12.4 } },
    { "card": 7, "name": "Bot-Wash Proxy + Fee/Vol",  "tier": "MED",  "tier_emoji": "🟡",
      "fields": { "fee_usd_24h": 4200, "fee_vol_ratio_pct": 0.42, "bot_vol_pct_proxy": 28.4, "bot_trade_pct_proxy": 31.1 } }
  ],
  "holder_list": [
    { "rank": 1, "owner": "5xoEnd2Q...", "tag_label": "kol_proxy", "amount_tokens": 142000000, "pct_of_supply": 14.2, "holding_usd_interp": 485682 },
    { "rank": 2, "owner": "9WzicdK8...", "tag_label": "smart",     "amount_tokens": 98210000,  "pct_of_supply":  9.8, "holding_usd_interp": 335992 }
  ],
  "risk_score_daily": [],
  "invariants": { "priceCalc_ok": true, "buySellSum_ok": true, "top10_diff_ok": true, "tag_sum_104_ok": true, "drawdown_formula_ok": true, "pipeline_gap_count": 0, "signal_gap_count": 0 }
}
```

---

## 5. Invariants & Cross-Checks

| Invariant | Tolerance | Fail flag |
|---|---:|---|
| `B.top10HolderPercent × 100` vs `sum(C.rows[0:10].percent_of_supply)` | ±5 pct pts | ⚠ signal_gap pill on CARD 5 |
| `B.creatorPercentage` vs tag `dev`% in step 5 join | Order-of-magnitude check (both < 100%) | ⚠ signal_gap pill on CARD 4 |
| `fee_vol_ratio ≥ 0` and `fee_vol_ratio < 10` | 0 ≤ x ≤ 10 | Clamp + log |
| If rug_score forced to 10 by override → final displayed tier = ❌ RUG/NG always | 0 tolerance | Never allow tier demotion below VERY HIGH |
| `summary.liquidity = A.liquidity` and `liq_current in CARD 2` match | exact | Mismatch → pipeline_gap count footer +1 |
