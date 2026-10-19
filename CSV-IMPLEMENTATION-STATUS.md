# CSV vs HUB Catalog · Implementation Status

> **CSV source:** `birdeye-screener/Birdeye Data Skills - marketplace-catalog.csv` (48 market rows from Birdeye Data)
> **HUB source:** `birdeye_ui.py` literal `_30_SKILLS_CATALOG` (32 items curated across 8 groups; name misnomer — actually 32 skills now)

---

## 0. Summary at a Glance

| Metric | Count |
|---|---:|
| Marketplace CSV rows total (excl header) | **48** |
| HUB catalog items (8 groups) | **32** |
| Items **LIVE / implemented** in CLI + UI panels | **4** |
| Items **WIP / placeholder card exists in sidebar** | **28** |
| CSV rows **NOT YET mapped** into HUB catalog (roadmap) | **16** |
| Chat / AI feature (Skill #28) | **HIDDEN (lean UI feature flag OFF)** |

**4 LIVE IMPLEMENTED = 100% of user's P0 core workflow:**
1. 🔥 Discovery → Skill #1 · Trending List (Mode-B Simple · 30 CU)
2. 🔥 Discovery → Skill #1b · V3 Token List (Mode-A Advanced · 50 CU)
3. 🛡 Token DD → Skill #3 · Token DD (Should I Buy? · 71 CU FAST mode)
4. ⚙ Utils & Settings → Skill #28 · API Key (session / persist to ~/.birdeye.env chmod 600)

---

## 1. Category-by-Category Mapping Table

### 🟠 Category 1 · Discovery (CSV: 15 rows → HUB: 3 items)

| CSV row | CSV skill name (core_calls) | HUB Skill | HUB ID | Status | Notes |
|---:|---|---|---|:---:|---|
| 2 | `birdeye-5-minute-trending-tokens` (market trending-5m) | Skill #1 · Trending List (subset via --interval 5m) | `tl` / `tl_v3` | ✅ **LIVE** | Use `--interval 5m` + `--source v3-list` on the CLI; UI dropdown supports 5m/1h/4h/8h/24h |
| 3 | `birdeye-launchpad-trending-tokens` (market launchpad-trending) | Skill #1 + `--platform pump.fun` (subset) | `tl` | ⚠ **PARTIAL** | Platform filter works; launchpad identity column is WIP in render columns |
| 4 | `birdeye-launchpad-new-tokens` (market launchpad-new) | Skill #2 · New Pairs | `new_pair` | 🚧 WIP | Placeholder card live in sidebar; no CLI subcommand yet |
| 5 | `birdeye-pumpfun-trending-tokens` (market pumpfun-trending) | Skill #1b V3 Token List + platform=pump.fun | `tl_v3` | ✅ **LIVE** | `--platform pump.fun` forces v3-list source route automatically |
| 6 | `birdeye-pumpfun-new-tokens` (market pumpfun-new) | Skill #2 · New Pairs (filter) | `new_pair` | 🚧 WIP | Same WIP as row 4 |
| 7 | `birdeye-newly-listed-tokens` (market new-listings) | Skill #2 · New Pairs | `new_pair` | 🚧 WIP | |
| 8 | `birdeye-near-graduation-tokens` (market near-graduation) | NOT IN HUB YET | — | 🔲 Roadmap | Consider adding to 🔥 Discovery group in future |
| 9 | `birdeye-recently-migrated-tokens` (market migrated) | Skill #1b (subset by sort/filter) | `tl_v3` | ⚠ PARTIAL | Approximate via `--sort_by last_trade_timestamp` override (WIP) |
| 10 | `birdeye-migrated-token-screener` (market migrated-quality) | NOT IN HUB YET | — | 🔲 Roadmap | |
| 11 | `birdeye-5-minute-volume-surge` (market volume-surge-5m) | NOT IN HUB YET | — | 🔲 Roadmap | |
| 12 | `birdeye-5-minute-price-surge` (market price-surge-5m) | NOT IN HUB YET | — | 🔲 Roadmap | |
| 13 | `birdeye-5-minute-most-traded` (market most-traded-5m) | Skill #1b sort by trade_interval_count | `tl_v3` | ⚠ PARTIAL | Sort/filter client-side; `--sort-by trade_count` not yet in argparse list |
| 14 | `birdeye-smart-money-token-radar` (market smart-money) | Skill #8 · Smart Money Hot Tokens | `sm_tokens` | 🚧 WIP | Placeholder in sidebar; endpoint = `/smart-money/v1/token/list` (already joined in Skill #3 DD FAST as batch) |
| 15 | `birdeye-market-radar` (market-radar run) | NOT IN HUB YET | — | 🔲 Roadmap | 100-point method; large separate module |

**Discovery coverage:** 2 of 15 CSV rows = LIVE end-to-end; 4 = WIP placeholders; 9 = future roadmap.

---

### 🛡 Category 2 · Token Due Diligence (CSV rows 16–28 → HUB group has 5 items)

| CSV row | CSV skill name | HUB Skill | HUB ID | Status |
|---:|---|---|---|:---:|
| 16 | `birdeye-token-basic-info` (token info) | Skill #3 · Token DD → Sec OVERVIEW | `dd` | ✅ **LIVE** | Part of token_overview payload (18 CU) — price/MC/FDV/LIQ/holder/v24h all rendered |
| 17 | `birdeye-token-security-check` (token security) | Skill #3 + Skill #4 | `dd` + `security` | ✅ LIVE (step 3 within DD) + 🚧 WIP (Skill #4 standalone) | token_security 30 CU call is integrated in Skill #3 FAST |
| 18 | `birdeye-liquidity-pool-analysis` (token liquidity; token pools) | Skill #5 · OHLCV + Liq Drawdown | `chart` | 🚧 WIP | Liquidity drawdown OHLC = `/defi/v3/liquidity-ohlc-token` design in `/API/02-chart-ohlcv-liquidity.md` |
| 19 | `birdeye-holder-distribution-analysis` (holder-analysis run) | Skill #4/Skill #6 | `security`/`holders` | 🚧 WIP | holder/v1/distribution + top-traders tags = 60 CU spec done |
| 20 | `birdeye-top-holders` (token holder-ranking) | Skill #6 · Top 20 Holders | `holders` | 🚧 WIP | |
| 21 | `birdeye-top-token-traders` (token traders) | Skill #6 + JOIN tags | `holders` | 🚧 WIP | tags array in top_traders response — spec done |
| 22 | `birdeye-token-kline-chart` (market kline) | Skill #5 · OHLCV + Liq Drawdown | `chart` | 🚧 WIP | |
| 23 | `birdeye-large-trade-scanner` (token large-trades) | NOT IN HUB YET | — | 🔲 Roadmap | |
| 24 | `birdeye-token-trade-activity` (token trades) | Money Flow section (Skill #3 DD FAST) | `dd` | ⚠ PARTIAL | buy$ + sell$ across 9 windows rendered; trade-level rows = roadmap |
| 25 | `birdeye-token-mint-burn-activity` (token mint-burn) | Skill #4 Security step 9 | `security` | 🚧 WIP | Mint authority logic (ownerAddress null) is LIVE; event rows = WIP |
| 26 | `birdeye-token-transfer-activity` (token transfers) | NOT IN HUB YET | — | 🔲 Roadmap | |
| 27 | `birdeye-token-due-diligence` (token-dd run) | Skill #3 · Token DD (Should I Buy?) | `dd` | ✅ **LIVE** | 71 CU FAST mode. STANDARD 155 CU / DEEP 266 CU = --depth roadmap |
| 28 | `birdeye-wallet-trade-history` (wallet activity) | Skill #11 · Wallet Trades | `wallet_trades` | 🚧 WIP | |

---

### 🧠 Category 3 · Wallet & Smart Money (CSV rows 28–38 → HUB group has 7 items)

HUB Skill #9 (smart traders criteria / recipe input matrix + segmented FAST30/STD150/DEEP500 + 4 sliders) = **control panel DESIGN DONE, live in UI**, CLI logic pending.

| CSV row | skill | HUB ID | Status |
|---:|---|---|:---:|
| 29 | `birdeye-wallet-recent-sells` (wallet sells) | Skill #11 wallet_trades filter | 🚧 WIP |
| 30 | `birdeye-wallet-net-buying` (wallet net-flow) | Skill #12 wallet_money_flow | 🚧 WIP |
| 31 | `birdeye-wallet-pnl-analysis` (wallet pnl) | Skill #10 wallet_portfolio → PnL tab | 🚧 WIP |
| 32 | `birdeye-wallet-trading-style` (wallet-analysis run) | Skill #9 Top Smart Money Wallets → profile | `sm_wallets` | ✅ CONTROLS LIVE, CLI WIP | 4 rule inputs + 4 weight sliders + recipe link `/API/11-smart-traders-criteria-skill9.md` |
| 33 | `birdeye-wallet-copy-trade-assessment` (wallet-score run) | Skill #13 copy_trade | 🚧 WIP |
| 34 | `birdeye-compare-smart-money-wallets` (wallet compare) | NOT IN HUB YET | 🔲 Roadmap |
| 35 | `birdeye-dev-created-tokens` (wallet created-tokens) | Skill #17 KOL / Dev Links | `kols` | 🚧 WIP |
| 36 | `birdeye-dev-launch-track-record` (dev-analysis run) | Skill #17 | `kols` | 🚧 WIP |
| 37 | `birdeye-token-smart-money-trades` (track smart-money-token) | Skill #14 · SM Flow 1 Token | `sm_flow_token` | 🚧 WIP |
| 38 | `birdeye-selected-kol-wallet-activity` (track kol) | Skill #17 KOL / Dev Links | `kols` | 🚧 WIP |

**Note:** HUB group also contains Skill #8 SM Hot Tokens (WIP) — maps to CSV row 14 smart-money token list.

---

### 🔐 Category 4 · Security & Risk (2+ items → 4 HUB cards)

| HUB Item | Maps to CSV? | ID | Status |
|---|---|---|:---:|
| Skill #15 Rugpull Risk Score | Token-security + heuristic aggregate | `rug_score` | 🚧 WIP | Scorecard formula = /API/10 composite |
| Skill #16 LP Lock Checker | Birdeye lpLocked field (step 2 card 2) | `lp_check` | 🚧 WIP | |
| Skill #17 KOL / Dev Links | CSV rows 35/36/38 | `kols` | 🚧 WIP | |
| Skill #17b RugCheck Risk Audit (7 cards · 13 summary · top-holders) | NOT explicit in CSV (proprietary 1-page format) | `rugcheck_risk_audit` | 🚧 SPEC DONE (workflow file `/WORKFLOW-03-RUGCHECK-SECURITY-AUDIT.md`) | 90 CU design = 3-endpoint recipe (21+30+30+9 buf) |

---

### ⛓ Chain & Platform (4 HUB items) / 📈 History (4) / 🤖 Alerts (2) / ⚙ Utils (3)

Most of these (Skills 18–27, 29 billing, 30 about) = **no direct CSV mapping** (they are aggregate/UX helpers). Status:

| ID | Skill | Status |
|---|---|:---:|
| `chains` | #18 Cross-Chain Compare | 🚧 WIP |
| `pf_tokens` | #19 Platform filter (pump.fun etc.) | ⚠ PARTIAL (routes through `--platform` in Skill #1 today) |
| `meme_index` / `l2_new` | #20/#21 | 🚧 WIP |
| `price_1y`/`vol_profile`/`corr_map`/`events` | #22–#25 History & Charts | 🚧 WIP |
| `alert_surge` / `tg_signal` | #26/#27 Alerts & Bots | 🚧 WIP (Signal pack = formats already exist; Telegram webhook payload = next) |
| `key` | #28 API Key | ✅ **LIVE** |
| `billing` | #29 CU Usage Monitor | 🚧 WIP |
| `about` | #30 About / Docs Links | ✅ **LIVE** |
| — | **#28b AI BYO Chat (LLM skill)** | 💤 FEATURE FLAG OFF (commented blocks; re-enable in 2 places in `birdeye_ui.py`) |

---

## 2. Legend

| Tag | Meaning |
|---|---|
| ✅ **LIVE** | End-to-end: sidebar → control panel → Run button → CLI subcommand → Birdeye API call → rendered output + cache + footer CU meter ALL work |
| ⚠ **PARTIAL** | Some subset of the functionality works under a different HUB skill ID today (e.g., launchpad trending = platform filter on TL) |
| 🚧 **WIP** | Placeholder card exists in sidebar catalog / control panel scaffolding exists / spec file exists — but Run button shows "Skill WIP" banner (no CLI call) |
| 🔲 **Roadmap** | Not yet in the 32-item HUB catalog. CSV rows > HUB count means room to expand the hub in future releases |
| 💤 FEATURE FLAG OFF | Implemented in code but intentionally hidden for lean-UI deploy. Uncomment 2 clearly marked blocks in `birdeye_ui.py` (HTML chat div + boot IIFE chat wiring) to re-enable |
