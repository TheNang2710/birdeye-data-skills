# Workflow · Skill #3 · Token Due Diligence (Should I Buy?)

> **Goal:** A transparent 10-step audit over Birdeye data that answers "Should I buy this token?". Coverage includes: Holder 24h delta, Top-20 holders, Liquidity min/max/drawdown, Tag% hold (Sniper / Bundler / Smart / KOL / Dev), Bot-proxy% volume, Contract security, composite SEC·30 / SMKT·25 / ACT·25 / VOL·20 weighted score, and final A–F / NG rating.

---

## 0. Skill Header & Equivalent Birdeye APIs

| Field | Value |
|---|---|
| **Skill id** | `dd` |
| **Skill title** | Skill #3 · Token DD (Should I Buy?) |
| **Category** | 🛡 Token Due Diligence (Group 2/8) |
| **Concept architecture** | Modular `include[]` selectors (see `/API/13-modular-token-dd-include-api.md`). BASE always included, each flag adds labeled CU surcharge + data block. |
| **CU cost — BASE (MVP, live)** | **71 CU** = overview+money_flow(21) + security(30) + SM-batch(20) |
| **CU surcharge per include flag** | `+list = +30 CU` · `+advanced_security = +21 CU` · `+risk_history_30d = +30 CU` (labeled CU) |
| **Σ CU — +LIST tier** | 101 CU = 71 + 30 |
| **Σ CU — +ADVANCED SECURITY tier** | 92 CU = 71 + 21 |
| **Σ CU — STANDARD tier (list + advsec)** | **122 CU** = 71 + 30 + 21 (OLD STD=155 CU → **saved 33 CU** by endpoint reuse) |
| **Σ CU — FULL-ANALYTICS (list + history)** | 131 CU = 71 + 30 + 30 |
| **Σ CU — DEEP tier (all 3 flags)** | **152 CU** = 71 + 30 + 21 + 30 (OLD DEEP=266 CU → **saved 114 CU**) |
| **CLI subcommand** | `token-dd` (BASE live; includes via `--include list,advanced_security,risk_history`) |
| **UI status** | ✅ LIVE (BASE 71 CU tier; include selectors = control panel roadmap pills) |

### Include flags ↔ Data blocks ↔ Birdeye endpoints ↔ CU adder

| Include flag | Data block added | Birdeye endpoint(s) powering it | CU adder |
|---|---|---|---:|
| (always) **BASE block** | price/MC/liq · holders · V24h · price Δ% 1m→24h · money_flow[32] · full security · smart-money batch join · score pillars SEC·30/SMKT·25/ACT·25/VOL·20 · FINAL · rating A-F/NG | `/defi/token_overview?includes=money_flow` (21) + `/defi/token_security` (30) + `/smart-money/v1/token/list limit=20` (20) | 71 (tier floor) |
| **`list`** | `holder_list[20]` rows (owner / amount / pct / USD interp · `liq_stats_24h_rolling.min/max/drawdown% + holder_24h_delta abs+pct · trader_24h_delta abs+pct · tag_cohorts[6] pct_supply+USD interp (dev/sniper/bundler/smart/insider/kol_proxy) · bot_proxy_volume%_and_trade% · fee+mint/burn events 24h count · 3 penalties applied → adjusted FINAL + re-rated | `/holder/v1/distribution token_address=<A> mode=top top_n=20 include_list=true` ⚠ param=`token_address` (NOT `address`) | +30 CU |
| **`advanced_security`** | liq drawdown + holder/trader delta (24h) + 6 tag cohorts (incl KOL proxy) + bot wash% proxy + fee/mint/burn events + 3 penalty score adjustments | `/defi/v3/liquidity-ohlc-token type=1h 26 candles` (15) + `/defi/v3/token/fee/single interval=24h` (~5) + `/defi/v3/token/mint-burn-txs limit=10` (~1) + holder-delta/trader-delta from BASE side-channel | +21 CU |
| **`risk_history_30d`** | `risk_score_daily[30]` = 30 daily snapshots of {ts, score, rating, 4 pillars} — snapshot source: Đức (reference) | 30-day window BASE-equivalent approximation per day (see `/API/13.md` Notes §5) + linear interpolate missing days + `missing_interpolated_count` badge ⚠ history_gap when N>0 | +30 CU |

### Birdeye API ↔ DD Step Mapping (10 steps × endpoints — updated for new modular includes)

| Step | Action | Birdeye endpoint | CU | Required for include |
|---:|---|---|---:|---|
| 1 | Overview + price + MC + holder + **Money Flow 32 frames** + holder/trader 24h delta (side-channel) | `GET /defi/token_overview?address=<ADDR>&includes=money_flow` | **21** | BASE (always) |
| 2 | Liquidity min/max → drawdown% rolling 24h | `GET /defi/v3/liquidity-ohlc-token?address=<ADDR>&type=1h&time_from=<now-26h>` | ~15 | advanced_security |
| 3 | **Security scan** (mint auth / honeypot / LP lock / creator% / top10%) | `GET /defi/token_security?address=<ADDR>` | **30** | BASE (always) |
| 4 | Top-20 holders list (owner / amount / pct / usd interp) | `GET /holder/v1/distribution?token_address=<ADDR>&mode=top&top_n=20&include_list=true` ⚠ **param = `token_address`** | 30 | list |
| 5 | Holder 6-tag cohort incl KOL proxy (dev/bundler/sniper/insider/smart + kol_proxy) | `GET /token/v1/holder-profile?token_address=<ADDR>&include_zero_balance=false` + `/defi/v2/tokens/top_traders` PnL KOL join | absorbed into advsec | advanced_security |
| 6 | Top-10 traders PnL + wallet tag JOIN (BotProxy% calc) | `GET /defi/v2/tokens/top_traders?address=<ADDR>&time_frame=24h&limit=10` | absorbed | advanced_security |
| 7 | Fee/Vol ratio → wash-volume proxy (fee_vol_ratio + BotTradeProxy churn) | `GET /defi/v3/token/fee/single?address=<ADDR>&interval=24h` + `/defi/v3/token/mint-burn-txs` | absorbed | advanced_security |
| 8 | **Smart Money batch JOIN** (how many SM hold today? rank?) | `GET /smart-money/v1/token/list?limit=20&sort_by=smart_traders_no&time_range=1d` | **20** | BASE (always) |
| 9 | Mint / Burn authority + supply history events 24h count + pct supply change | `GET /defi/v3/token/mint-burn-txs?address=<ADDR>&limit=10` | absorbed (≤1) | advanced_security |
| 10 | **Composite rating A…F/NG** (BASE calc) + adjusted (adv_security penalties) + 30d history | **Client-side scorecard** + `/API/13.md` penalty table + snapshot Đức source | 0 | all tiers |
| — | Σ default BASE only | | **71** | |
| — | Σ STANDARD (BASE + list + advanced_security) | 71+30+21 | **122** | |
| — | Σ DEEP (all includes BASE + list + advsec + risk_history_30d) | 71+30+21+30 | **152** | |

### Compact interpolated holding $ formula (tag cohorts + holder list — 0 CU)

```
holding_usd_interpolated = pct_of_supply / 100 × circulating_supply_tokens × price_usd
circulating_supply_tokens = marketCap USD / price_usd   (both from step 1)
```
UI MUST label rows `holding_usd (interpolated)` — inline match RugCheck.xyz 13-field summary convention.

### Cross-links
- Modular include concept design → `/API/13-modular-token-dd-include-api.md` (**design source user requested**)
- Per-endpoint low-level params → `/API/01-token-overview.md`, `/API/03-token-security.md`, `/API/04-holder-distribution.md`, `/API/05-holder-profile-top20.md`, `/API/06-top-traders-profile.md`, `/API/07-smart-money-token-list.md`, `/API/10-composite-dd-10step.md`
- Workflow 10-step source + inventory → `/birdeye-dd-workflow.md`
- RugCheck-style 7-card security variant → `/WORKFLOW-03-RUGCHECK-SECURITY-AUDIT.md`

---

## 1. Prerequisites (Preflight · 0 CU)

| # | Check | Fail behaviour |
|---|---|---|
| 1 | API key present (session / env / ~/.birdeye.env) | 🛑 red banner, HALT |
| 2 | Address format valid for chain | 🛑 red banner — see regex table below |
| 3 | Chain ∈ {sol, bsc, base, eth} | 🛑 red banner |

**Address validation regex (preflight, never posts invalid):**

| Chain | Regex | Length | Example |
|---|---|---:|---|
| Solana | `^[1-9A-HJ-NP-Za-km-z]{32,44}$` (base58, no 0/O/l/I) | 32–44 | `BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK` |
| EVM (bsc/eth/base) | `^0x[a-fA-F0-9]{40}$` | 42 chars incl `0x` | `0x8888889293c46393717B76bE2Ac21c1f0F05c8cA` |

---

## 2. Step-by-Step Checking Workflow (FAST · 71 CU · MVP live)

```
START: Input (address, chain) ── preflight 0 CU ──▶ FAIL=🛑 stop / PASS=continue
  │
  ▼
STEP 1 ── /defi/token_overview + includes=money_flow ──▶ 21 CU
  ├─ Extract: price, MC, FDV, liq current, holder count, v24hUSD
  ├─ Extract: priceChangePct {1m,5m,15m,30m,1h,2h,4h,8h,24h}
  ├─ Extract: moneyFlow[32] {volumeBuyUsd, volumeSellUsd, netUsd, walletBuy, walletSell}
  ├─ Derive: buy_sell_rows (9 windows) = buy_ratio / buys/sells count / trade_ratio / wallet ratio
  └─ 🔴 Red-flags (immediate ⛔ inline alert):
       ├─ liquidity < $10,000
       ├─ holder count < 100
       ├─ price 24h change < −50%
       └─ net USD flow negative × 4 consecutive frames
  │
  ▼
STEP 3 ── /defi/token_security ──▶ 30 CU  (skip steps 2; step 3 runs in parallel)
  ├─ Extract: creatorPercentage, top10UserPercentage, top10HolderPercent
  ├─ Extract: isHoneypot (EVM only; Sol → infer from ownerAddress + mintable proxy)
  ├─ Extract: lpLocked, mutableMetadata, freezeAuthority, ownerAddress
  └─ Mint-authority-renounced flag for SOL = (ownerAddress === null)
  │
  ▼
STEP 8 ── /smart-money/v1/token/list (BATCH JOIN) ──▶ 20 CU
  ├─ Fetch 20-token batch (Birdeye HARD LIMIT on this endpoint)
  ├─ Client-side JOIN on `address`
  └─ Per token: extract smart_traders_no (int count) + rank_in_sm_top100 (#1..#100 or null)
  │
  ▼
(Steps 2,4,5,6,7,9 run in STANDARD / DEEP modes only — roadmap)
  │
  ▼
STEP 10 ── CLIENT SIDE SCORECARD (0 CU)
  │
  ├─ A. Compute SEC (security component · 30% weight)
  │    Base = 5/10. Tuning rules from /API/10-composite-dd-10step.md
  │    +3  if Dev hold < 2%     +2  if Top10 hold < 20%
  │    +2  if Dev hold 2–5%     +1  if Top10 hold 20–40%
  │    +1  if Dev hold 5–10%    −2  if Top10 hold > 40%
  │    −2  if Dev hold > 10%
  │    =0  🔴 honeypot=YES  (hard floor; forces FINAL < 3.5 → NG)
  │    +1  if lpLocked=YES
  │
  ├─ B. Compute SMKT (smart-market-fit · 25% weight)
  │    Base = 5/10. Source: step 8 /SM batch join
  │    +4/3/2/1  if rank in SM top100 ≤ {#10, #30, #60, #100}
  │    +2        if wallet count ≥ 20 (no rank)
  │
  ├─ C. Compute ACT (activity momentum · 25% weight)
  │    Base = 5/10. Source: step 1 money_flow + price_changes
  │    +3/+2/+1  buy ratio last win ≥ {62%,55%,51%}
  │    −2/−3     buy ratio last win ≤ {45%,38%}
  │    +3/+2/+1  SM wallet count ≥ {30,10..29,3..9}
  │    +1/−1     Δ% (4h − 5m) > +30 / < −30
  │
  ├─ D. Compute VOL (volume trend · 20% weight)
  │    Base = 5/10. Source: buy_sell_rows across windows 5m..24h
  │    +1 per window Vol$ increases. Max bonus = (N_windows − 1) = +7 typical
  │    −2 if zero windows show Vol$ increase
  │
  ├─ E. APPLY PENALTIES (STANDARD/DEEP modes)
  │    −1.5  LP drawdown 24h > 30%     (STANDARD+ — step 2 result)
  │    −1.0  Bot-proxy vol% > 40%        (STANDARD+ — step 6 tags)
  │    −0.5  per tag > 25% supply        (STANDARD+ — step 5 tags)
  │
  ├─ F. FINAL weighted score
  │    FINAL = clamp( SEC·0.30 + SMKT·0.25 + ACT·0.25 + VOL·0.20 − penalties, 0, 10 )
  │
  └─ G. MAP → LETTER RATING + VERDICT (see table)
  │
  ▼
INVARIANTS CHECK (post-score, 0 CU)
  ├─ price calc MC vs (price × supply from step1) within ±10% → if not → badge ⚠ signal_gap
  ├─ buy$ + sell$ ≈ v24hUSD within 15% → if not → badge ⚠ pipeline_gap
  └─ honeypot=true → MUST force FINAL < 3.5 (NG) — if invariant broke → hard-floor score
  │
  ▼
RENDER + CACHE
  ├─ 5 formats: plain / scorecard / telegram / raw-json / render-html (UI render = client-side payload rehydrate, 0 CU extra)
  ├─ Cache 24h at ~/.cache/birdeye-skills-runs/token-dd_<ADDR>_<TS>.json
  └─ Footer: ⚡71 CU · ΔT ms · #run_id · 💾 badge if re-rendered from cache
```

### Rating → Verdict Threshold Table

| FINAL range | Letter | Color | Verdict |
|---:|---|---|---|
| ≥ 9.0 | **S** | 🟡 gold | 🌟 **STRONG BUY** · hold target 7–30d |
| 8.0–8.99 | **A** | 🟢 green | 🟢 **BUY** · strong fundamentals, low risk |
| 7.0–7.99 | **B** | 🩵 teal | ✅ **ACCUMULATE** · good structure, wait entry |
| 6.2–6.99 | **C** | 🟡 yellow | ⚠ **HOLD / WATCH** · wait for catalysts |
| 5.0–6.1 | **D** | 🟠 orange | 🔻 **REDUCE** · multiple flags, protect capital |
| 3.5–4.99 | **F** | 🔴 red | 🛑 **SELL / AVOID** · broken structure |
| < 3.5 | **NG** | 🔴 dark-red | ❌ **NO-GO** · honeypot / rug / mint-live / catastrophic |

---

## 3. All CLI Commands (Exhaustive)

```bash
# ============================================================
#  WORKDIR:  cd /Users/nguyenthenang/nang/birdeye/app/skills
#  CLI PATH: birdeye-screener/scripts/birdeye_cli.py
#  DEFAULT CU: 71 (FAST) per call unless --depth overrides
# ============================================================

# ------------------------------------------------------------
#  [A] FAST mode · plain ASCII scorecard (default · 71 CU)
# ------------------------------------------------------------
# Solana token — demo RugCheck reference address
python3 birdeye-screener/scripts/birdeye_cli.py \
  token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --format plain

# Short: defaults chain=sol, format=plain
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --address 7GCihhJ9Ev6kEcvX88KqZ3QxCi87BdSxgEoxoY8pump

# Ethereum token — 0x address
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain eth \
  --address 0x8888889293c46393717B76bE2Ac21c1f0F05c8cA

# ------------------------------------------------------------
#  [B] Telegram markdown (paste-ready)
# ------------------------------------------------------------
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --format telegram > /tmp/tg-dd-bfgv.md
#  Then inside Telegram bot:
#    send_document / paste the markdown between ``` ``` code fence

# ------------------------------------------------------------
#  [C] Raw JSON (pipe to jq / bots / spreadsheets)
# ------------------------------------------------------------
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --format raw-json | jq '{final:.final_score,sec:.sec,smkt:.smkt,act:.act,vol:.vol,rating:.rating}'

# ------------------------------------------------------------
#  [D] 0 CU — replay from cache (format switch, no API hit)
# ------------------------------------------------------------
# First, look up a run_id from cache history:
python3 birdeye-screener/scripts/birdeye_cli.py history --limit 10

# Then re-render that same payload snapshot in telegram / scorecard / plain:
python3 birdeye-screener/scripts/birdeye_cli.py replay-run \
  --run-id token-dd_BFgvTe3p_1760001234 --format telegram

# ------------------------------------------------------------
#  [E] BATCH sweep a TL output (bash one-liner · CU = N × BASE)
# ------------------------------------------------------------
# 1) save top-5 trending addresses to addr.txt
python3 birdeye-screener/scripts/birdeye_cli.py trending-list \
  --chain sol --limit 5 --format raw-json \
  | jq -r '.payload.rows[].address' > /tmp/addr.txt
# 2) run DEEP (152 CU each = 760 CU total for 5 tokens)
while read a; do
  python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
    --chain sol --address "$a" \
    --include list,advanced_security,risk_history \
    --format plain | tail -n +3
done < /tmp/addr.txt

# ------------------------------------------------------------
#  [F] NEW MODULAR INCLUDE-BASED TIERS (design from /API/13.md)
# ------------------------------------------------------------
#   CU table reference:
#     BASE                                        =  71 CU
#     --include list                              = +30 → 101
#     --include advanced_security                 = +21 →  92
#     --include risk_history                      = +30 → 101
#     --include list,advanced_security  (STD)     = +51 → 122  (saved 33 vs old 155)
#     --include list,risk_history     (FULL-ANA)  = +60 → 131
#     --include list,advanced_security,risk_history (DEEP) = +81 → 152  (saved 114 vs old 266)

# STANDARD tier: include=list,advanced_security  →  scorecard output
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list,advanced_security \
  --list-top-n 20 \
  --format scorecard

# DEEP tier (all 3 includes)  →  telegram markdown paste-ready
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list,advanced_security,risk_history \
  --list-top-n 20 \
  --history-points 30 \
  --format telegram > /tmp/tg-dd-deep-BFgv.md

# Inspect billed CU + flags only (jq quick summary — no extra API hit)
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list,risk_history \
  --format raw-json | jq '
  {
    billed:      .meta.cu_billed_total,
    breakdown:   .meta.cu_breakdown,
    flags:       .meta.include_flags,
    final_score: .score_final_0_10,
    rating:      .rating,
    liq_DD_pct:  (.advanced_security // {}).liq_stats_24h_rolling.drawdown_24h_pct,
    hist_days:   ((.risk_score_daily // []) | length)
  }'

# Tag cohorts USD interpolated (6 tags: dev/sniper/bundler/smart/insider/kol_proxy)
# Only returned when --include advanced_security   (+21 CU)
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include advanced_security \
  --format raw-json | jq '
    .advanced_security.tag_cohorts_pct_holding_usd_interpolated[]
    | { tag, pct_of_supply, holder_count_in_tag, holding_usd_interp }'

# List top-20 holders + top-10 concentration check vs security.top10_holder_pct
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list \
  --list-top-n 20 \
  --format raw-json | jq '
  {
    security_top10_pct: .security.top10_holder_pct,
    list_top10_sum:    ([.holder_list[] | select(.rank <= 10) | .pct_of_supply] | add),
    diff_pct:          (.security.top10_holder_pct - ([.holder_list[]|select(.rank<=10)|.pct_of_supply]|add)),
    signal_gap:        (((.security.top10_holder_pct - ([.holder_list[]|select(.rank<=10)|.pct_of_supply]|add)) | fabs) > 5),
    lp_top20_sum_pct:  .lp_concentration_pct.top_20_holders_pct_sum
  }'

# Risk history 30d daily snapshots (include=risk_history, +30 CU, source: Đức)
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include risk_history \
  --history-points 30 \
  --format raw-json | jq '
  {
    source:      .risk_score_daily_meta.source,
    pts_return:  .risk_score_daily_meta.points_returned,
    interp_N:    .risk_score_daily_meta.missing_interpolated_count,
    first_10:    [.risk_score_daily[:10][] | {day:.day_label_iso, score:.final_score, rating:.rating}]
  }'
```

### Exit codes (same conventions as TL workflow)

| Exit | Meaning |
|---:|---|
| 0 | Success (score + rating rendered) |
| 2 | Arg parse fail / bad address format — **0 CU** |
| 3 | API key missing — **0 CU** |
| 4 | Birdeye upstream HTTP non-200 — partial CU possible on 429 by Birdeye |
| 5 | Invariant broken: `buy$+sell$` ≠ `v24hUSD` by >15% or honeypot didn't floor score — render output + `⚠ pipeline_gap` |

---

## 4. Response Output Columns (Plain & Scorecard)

### Plain ASCII (format plain)
```
#RUN_ID  token-dd_BFgvTe3p_…   cu=71
───────────────────────────────────────────────────────────
  SYMBOL  RUGK     · BFgvTe3p…g8UK (Solana)
  PRICE   $0.003421   MC $3.42M   FDV $3.42M   LIQ $180K
  HOLDERS 3,241    V24H $1.2M    TRADES/24h  14,820
  ΔP%      1m +1.2%   1h +18.4%  4h +52.1%   24h +210%
───────────────────────────────────────────────────────────
  SCORECARD (hover in UI for formula tooltip)
  ┌──────────┬──────────┬──────────┬──────────┬──────────────┐
  │ SEC  6.2 │ SMKT 5.8 │ ACT  7.1 │ VOL  6.5 │ FINAL  6.4/10│
  │ 30%      │ 25%      │ 25%      │ 20%      │ RATING  C    │
  └──────────┴──────────┴──────────┴──────────┴──────────────┘
  VERDICT:  ⚠ HOLD / WATCH (5.0–6.1 → C)
───────────────────────────────────────────────────────────
  MONEY FLOW  (9 windows, buy>sell = green)
  5m   [█████░░░░] net +$12.4k   (62% buy)
  15m  [████████░] net +$48.1k   (68% buy)
  1h   [██████░░░] net +$120.3k  (61% buy)
  …
  SECURITY  (step 3 /defi/token_security)
    Creator%      : 1.2%         [SAFE < 2%]
    Top10 Holder% : 28%          [OK 20–40%]
    Top10 User%   : 31%
    Mint Auth     : RENOUNCED ✓  (ownerAddress = null)
    LP Locked     : NO           ⚠ consider
    Freeze Auth   : DISABLED ✓
    Honeypot      : NO           (EVM only; Sol = proxy N/A)
  SMART MONEY JOIN (step 8 batch)
    SM Wallets    : 12 holding   rank_top100 = #74
  INVARIANTS      : pass (priceCalc ✓, buySellSum ✓, no pipeline_gap)
───────────────────────────────────────────────────────────
  ⚡ 71 CU total  (overview+mf 21 / security 30 / SM 20)
  Δ 682 ms       · snapshot Unix 1760001234567   · #run_id …
```

### Raw JSON envelope (`kind: "token-dd"`, schemaVersion: 1) — skeleton
```jsonc
{
  "runId": "token-dd_BFgvTe3p_1760001234",
  "kind": "token-dd",
  "schemaVersion": 1,
  "params": {"chain":"sol","address":"BFgvTe3p…g8UK"},
  "cu_used_total": 71,
  "cu_breakdown": {"overview_money_flow":21,"token_security":30,"sm_batch_join":20},
  "latency_ms": 682,
  "snapshot_time": 1760001234567,
  "symbol": "RUGK", "name": "RugCheck Demo",
  "price": 0.003421, "marketCap": 3420000, "fdv": 3420000, "liquidity": 180000,
  "holder": 3241, "v24hUSD": 1200000, "trade24h": 14820,
  "price_changes": [["1m",+1.2],["1h",+18.4],["4h",+52.1],["24h",+210.0]],
  "buy_sell_rows": [["5m",t2,buy,sell,ratio,…], …],
  "money_flow_rows": [["5m",{frame,volumeBuyUsd,volumeSellUsd,netUsd,…}], …],
  "security": {
    "creatorPercentage":1.2,"top10HolderPercent":28.0,"top10UserPercent":31.0,
    "isHoneypot":null,"lpLocked":false,"mutableMetadata":true,
    "freezeAuthority":false,"ownerAddress":null,"mintAuthorityRenounced":true
  },
  "smart_money": {"smart_traders_no":12,"rank_in_sm_top100":74},
  "scores": {"SEC":6.2,"SMKT":5.8,"ACT":7.1,"VOL":6.5,"FINAL":6.4},
  "rating": "C", "verdict": "HOLD / WATCH",
  "invariants": {"priceCalc_ok":true,"buySellSum_ok":true,"pipeline_gap":false,"signal_gap":0}
}
```

---

## 5. Invariants (Mandatory Every Run)

### Base invariants (all tiers)
| Invariant | Tolerance | Fail flag |
|---|---:|---|
| `price × circulatingSupply ≈ marketCap` | ±10% | ⚠ signal_gap pill + note |
| `sum(buy$ + sell$ across windows)` vs `v24hUSD` | ±15% | ⚠ pipeline_gap banner |
| If `isHoneypot === true` → `FINAL` MUST be `< 3.5` (NG) | 0 tolerance | Hard floor score; block rating ≥ C |
| If `ownerAddress != null (Sol)` + 3+ mint events in 24h → force NG | STANDARD/DEEP only | Rating override block |
| `liquidity ≥ 0`, `marketCap ≥ 0`, `holder ≥ 0`, `volume ≥ 0` | 0 tolerance | Row-level red cell + pipeline_gap count footer |

### Include=list invariants
| Invariant | Tolerance | Fail flag |
|---|---:|---|
| `sum(holder_list rank<=10 pct_of_supply)` vs `security.top10_holder_pct` | ±5% | ⚠ signal_gap (stored in `holder_list_meta.sum_pct_checked_vs_security_top10`) |
| `holder_list.rank` uniqueness | 0 tolerance | Drop duplicate rows; append warning to run footer if rank holes |
| `holding_usd_interpolated` per row = `pct/100 × MC/price × price` = `pct × MC / 100` exactly | 0 | If mismatch → recalc client-side (reference formula in /API/13.md) |

### Include=advanced_security invariants
| Invariant | Tolerance | Fail flag |
|---|---:|---|
| `liq_stats_24h_rolling.min_usd_24h ≤ current_usd ≤ max_usd_24h` | 0 | ⚠ signal_gap liq if broken |
| `sum(tag_cohorts.pct_of_supply for 6 tags) ≤ 100` | ±2% buffer for rounding; >105% → ⚠ signal_gap tag_pct_sum_over |
| `bot_proxy_volume_usd ≤ volume_24h_usd_baseline` | 0 | Clamp; if clamped → pill `Bot% clamped` |
| `drawdown% = (max − min)/max × 100` formula match | 0 | Recalc inline in footer to confirm |

### Include=risk_history_30d invariants
| Invariant | Tolerance | Fail flag |
|---|---:|---|
| `points_returned` == `history_points` requested (default 30) or header explicit `missing_interpolated_count` | 0 | Badge ⚠ history_gap N/30 interpolated |
| Final score `0 ≤ final_score ≤ 10` daily | 0 | Clamp rows that violate |
| Rating letters within S/A/B/C/D/F/NG set | 0 | Override row → `-` if invalid |
| Linear interpolation monotonic between real snapshots | — | Debug only; never displayed to user |
