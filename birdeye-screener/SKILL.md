---
name: birdeye-screener
description: High-volume on-chain token screener powered by Birdeye Data API. Three execution layers exist. (Layer C RECOMMENDED for bot-friendly CLI + Telegram paste-ready output): unified `scripts/birdeye_cli.py` exposes two subcommands: (1) `trending-list` — discovery hot-token list via `/defi/v3/token/list` (50 CU default, real volume ≥$100 filter; optional `--source trending` 30 CU with pipeline_gap fallback), 4 chains, 3 intervals, 6 sort fields, `--platform pump.fun` filter, 3 output formats (plain / telegram / raw-json). (2) `token-dd --address` — "Should I Buy This Token?" scorecard. Calls 4 endpoints batch: token_overview + includes=money_flow (21 CU SOL / 18 CU non-SOL) + token_security (30 CU) + smart-money batch join (20 CU) → total 71 CU / token. Produces SEC/SMKT/ACT/VOL weighted score 0-10 with 6-level verdict, 4 invariant checks, CU footer, same 3 formats. (Layer A) `scripts/birdeye_screener.py` = Mode-A FULL multi-filter screener with 50 CU MVP + hydrate tiers (48/token + 20 SM batch), 3 subcommands `scan/token/config`. (Layer B) `scripts/birdeye_trending_simple.py` = Mode-B SIMPLE cheap 30 CU standalone trending via `/defi/token_trending`. Supports Solana, BSC, Base, Ethereum. Uses the user's own Birdeye API key. Use when user asks: token screener, 5m hot tokens, high-volume, Birdeye scan, trending tokens, pumping now, dev holding filter, smart money list, multi-chain discovery, trending list, token due diligence, token DD, should I buy this token, token risk score, buy/sell pressure, money flow, telegram signal, paste to telegram.
argument-hint: "trending-list --chain <sol|bsc|base|eth> [--interval <1h|4h|24h>] [--source <v3-list|trending>] [--sort-by <volumeUSD|liquidity|rank|market_cap|trade_count|holder>] [--limit <1-100>] [--platform <pump.fun|moonshot|raydium|...>] [--offset <0-10000>] [--format <plain|telegram|raw-json>]  |  token-dd --chain <sol|bsc|base|eth> --address <ADDR> [--format <plain|telegram|raw-json>]  |  simple --chain <sol|bsc|base|eth> [--interval <1h|4h|24h>] [--sort-by <volumeUSD|liquidity|rank>] [--limit <1-100>]  |  scan --chain <sol|bsc|base|eth> [--window <1m|5m|30m|1h|4h|24h>] [--sort-by <volume|market_cap|trade_count|holder>] [--direction <desc|asc>] [--limit <1-100>] [--platform <pump.fun|moonshot|raydium|...>] [--min-market-cap <USD>] [--max-market-cap <USD>] [--min-liquidity <USD>] [--max-liquidity <USD>] [--min-volume <USD>] [--min-price-change-pct <%>] [--min-trade-count <n>] [--min-holder <n>] [--min-smart-money <n>] [--max-dev-hold-pct <%>] [--min-buy-ratio <0-1>] [--hydrate <off|top10|top20|all>]  |  token --chain <sol|bsc|base|eth> --address <addr>  |  config --check | config --apply <KEY>"
metadata:
  cliHelpLayerC: "python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_cli.py --help"
  cliHelpTrendingList: "python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_cli.py trending-list --help"
  cliHelpTokenDD: "python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_cli.py token-dd --help"
  cliHelpSimple: "python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_trending_simple.py --help"
  cliHelpFull: "python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_screener.py --help"
  cuPerTrendingV3List: 50
  cuPerTrendingNative: 30
  cuPerTokenDD: 71
  cuPerTokenDDNoSM: 51
  cuPerScanMvp: 50
  cuPerHydrateToken: 48
  cuPerSmartMoneyBatch: 20
---

# Three-Layer Routing (Agent Logic)

**DEFAULT = Layer C unified CLI. Use it 90% of the time for discovery + DD workflow.**
  - User asks "trending / hot / what's pumping / discovery list" → invoke `birdeye_cli.py trending-list`.
  - User asks "DD / due diligence / should I buy / risk check / token score / money flow / buy sell pressure / overview" → invoke `birdeye_cli.py token-dd --address <ADDR>`.
  - User explicitly asks "cheap scan / minimal CU / no filters" → use Layer B `birdeye_trending_simple.py` or Layer C `trending-list --source trending`.
  - User explicitly asks "screener / filter by MC range / hydrate signals / dev holding filter / smart money filter / bundle ratio" → use Layer A `birdeye_screener.py scan ... --hydrate top10|top20|all`.
  - User asks "wallet style / classify how a wallet trades / sniper / swing / hoarder / whale / trading style / frequency × PnL grid" → invoke `birdeye_cli.py wallet-style --wallet <ADDR>`. (Full concept + formulas in `references/wallet-style-skill.md`.)
  - User asks "wallet score / alpha score / is this wallet good / 0-100 score" → invoke `birdeye_cli.py wallet-score --wallet <ADDR>`.

## Layer C — Unified Bot-Friendly CLI (RECOMMENDED)

Two subcommands, three output formats, credential path shared with Layer A/B.

### `trending-list` — Skill #1 Discovery (default 50 CU)

- Default source = `/defi/v3/token/list` (50 CU) with server-side `min_volume_X_usd=100` filter → guaranteed real non-zero volume.
- Optional cheap mode: `--source trending` (30 CU, native `/defi/token_trending`). Script auto-detects >50% rows with volume < $1 and emits `⚠ pipeline_gap` + fallback client-side sort.
- 4 chains: `sol / bsc / base / eth`.
- 3 intervals: `1h / 4h / 24h`.
- 6 sort fields: `volumeUSD / liquidity / rank / market_cap / trade_count / holder`. Last two only supported with `--source v3-list`.
- Platform filter: `--platform pump.fun` (moonshot / raydium / jupiter studio / meteora dbc / diesel / gobolt / trix / bags.fm / possumlabs / letsbonk.fun / trix / meme.com platform / etc — passed server-side).
- 3 formats:
  - `--format plain` (default): 11px ASCII compact table, footer CU breakdown, latency ms, snapshot UTC time, 3 "📋 Paste next" lines copy-paste-ready for token-dd.
  - `--format telegram`: `🔥` emoji header, wrap rows inside `` ``` `` monospace block, 5 token addresses cut to `head…tail` for paste into Telegram. < 4096 chars with `--limit ≤ 15`.
  - `--format raw-json`: single-line JSON for downstream bot ingestion. Keys camelCase; includes cu_used_total, latency_ms, snapshot_time.
- Pagination: `--offset 0-10000`; limit 1-100.

### `token-dd` — Skill #3 "Should I Buy This Token?" Scorecard (71 CU / token)

One-shot 4-endpoint batch aggregation:
  1. `/defi/token_overview?includes=money_flow` — 21 CU on SOL (18 CU + 3 CU money_flow), 18 CU elsewhere.
  2. `/defi/token_security` — 30 CU (risk / honeypot / LP lock / dev + top10 %).
  3. `/smart-money/v1/token/list` top 20 batch join — 20 CU (rank + smart_traders_no).

**Sections printed:**
1. Header row: chain badge · symbol · name · price · MC · LIQ · FDV · Holders · address line.
2. Risk / Security: `Dev hold%` (creatorPercentage×100) ✅/⚠/🔴, `Top10%` ✅/⚠/🔴, Honeypot flag ✅/🔴, LP lock ✅/🔴.
3. Price ΔP% by windows: 5m / 30m / 1h / 4h / 24h (signed %, green/red in ANSI plain).
4. Buy/Sell Pressure + Money Flow table (9 cols): Vol$ / Buy$ / Sell$ / Buy$% / Buys / Sells / Trade-Buy% / Wallets / NetFlow$.
5. Smart Money section: rank if in top-20 today, wallet count, 🌟 rating; else "Not in global top 20 today".
6. Weighted scorecard 0–10: SEC (30%) · SMKT (25%) · ACT (25%) · VOL (20%) → FINAL → verdict {STRONG BUY, BUY, HOLD, WATCH, AVOID, SELL RED FLAG}.
7. Footer: CU breakdown line (e.g. `overview_+mf=21 + security=30 + sm_batch=20 = 71 CU`), latency ms, snapshot UTC.
8. Invariants footer: `✅ All invariants passed (priceCalc, buySellSum)` OR `⚠ N pipeline gap(s): …`.

**4 Invariants checked before rendering:**
1. `buySellSum`: `vBuy$ + vSell$ = v$ ± 7%`. Fail → gap.
2. `priceCalc`: `(price − historyPrice) / historyPrice × 100 = priceChange% ± 0.5%`. Fail → gap.
3. `moneyflowSum`: native `moneyFlow[frame].net` == `vBuy$ − vSell$ ± 5%` (only on SOL where includes=money_flow). Fail → gap.
4. `devTop10Sum`: `dev% + top10% ≤ 105`. Fail → gap.

**3 output formats**: `plain` (ANSI terminal), `telegram` (multi-section markdown, wrap scores/codeblocks with backticks, addresses inline backtick), `raw-json` (single line for downstream bot framework, keys camelCase with cu_breakdown array & gaps array & verdict & final_score).

## Layer A & Layer B (Backward Compat)

See the rest of this doc below for Layer A FULL screener and Layer B SIMPLE trending — kept for workflows that explicitly mention "screener / hydrate / advanced filters". Both share credential loader with Layer C.

---

## Credential Pre-flight (RUN BEFORE ANY INVOCATION)

1. Run:
   ```bash
   python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_screener.py config --check
   ```
2. If exit code is `0` → proceed.
3. If exit code is `1`:
   - Show the user the output.
   - Ask the user to provide their Birdeye API key.
   - Then save it by running:
     ```bash
     python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_screener.py config --apply <BIRDEYE_API_KEY>
     ```
   - Confirm save succeeded and the key passes verification (`/defi/v3/token/list` dry call).

**All three layers (A, B, C) read the same credential order:** `BIRDEYE_API_KEY` env var → `~/.config/birdeye/.env` → `~/.birdeye.env` → skill-local `.env` (fallback).

**CU BUDGET DISCIPLINE — always show the CU meter in every response:**
- Layer C `trending-list --source v3-list` = 50 CU / call.
- Layer C `trending-list --source trending` = 30 CU / call (but watch for `⚠ pipeline_gap`).
- Layer C `token-dd` = 71 CU / token on SOL; 68 CU / token non-SOL (no money_flow extra).
- Layer A `--hydrate off` (DEFAULT) = MVP mode, only 50 CU per scan. **Use this by default unless the user explicitly asks for smart money, dev holding, or buy ratio filters.**
- Layer A `--hydrate top10` = 50 + 10×48 + 20 = 550 CU per scan.
- Layer A `--hydrate top20` = 50 + 20×48 + 20 = 1030 CU per scan.
- Layer A `--hydrate all` = 50 + N×48 + 20 CU where N = limit (up to 100×48 = 4850 CU / scan). **Only use if the user explicitly confirms the CU spend.**

**Always render a one-line CU+latency footer after every scan, e.g. `⚡CU: 71 (overview_+mf=21 + security=30 + sm_batch=20) | ⏱1402ms | 📸2025-10-09T03:30:01`**

---

## Core Concepts

- **Compute Unit (CU)** — Birdeye charges per endpoint, not per subscription credit. Each endpoint has a fixed CU cost:
  - `GET /defi/v3/token/list` → 50 CU (MVP scan)
  - `GET /defi/token_security` → 30 CU / token (dev holding share, top10 holder %)
  - `GET /defi/token_overview?frames=5m` → 18 CU / token (buy/sell counts → buy imbalance ratio)
  - `GET /smart-money/v1/token/list` → 20 CU / batch (smart trader count lookup)
- **Pipeline gap date-stamp** — every token row includes `snapshot_time` from `updateTime` of the scan. If a hydrated field (dev_hold, smart_money, buy_ratio) comes back null/empty, show `N/A` with a tiny `⚠signal_gap` badge — **NEVER show 0 for unknown values**.
- **Proxy fields for coverage gaps** — Birdeye does not expose a raw `bundler_rate` natively. We compute `buy_imbalance_ratio = buys_5m / (buys_5m + sells_5m)` as a proxy. **Always label it "Buy Imbalance" not "Bundle Rate" to avoid confusion.**
- **Platform filter** — passed directly to Birdeye `platform_name` parameter. Supported: `pump.fun`, `moonshot`, `mayhem`, `raydium`, `meteora dbc`, `letsbonk.fun`, `jupiter studio`, `gobolt`, `bags.fm`, `possumlabs`, `trix`, `diesel`, `meme.com platform`.
- **Client-side filters** — three fields don't have server-side Birdeye filters: `max_holder`, `max_price_change_pct`, `min_smart_money`, `max_dev_hold_pct`, `min_buy_ratio`. The CLI applies them post-hydrate and reports `rows_shown / rows_fetched`.

## Sub-commands

| Sub-command | Description |
|-------------|-------------|
| `screener scan` | High-volume token screener — the main entry point. Defaults to 5m window on Solana, MVP 50 CU. |
| `screener token` | Hydrate one single token in full: overview (18 CU) + security (30 CU) + optional smart-money join. Total 48 CU / token + 20 CU SM batch. |
| `screener config` | Check, save, or verify the user's Birdeye API key. Stored in `~/.config/birdeye/.env`. |

## Supported Chains

`sol` (Solana) / `bsc` (BSC) / `base` (Base) / `eth` (Ethereum)

## `screener scan` Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--chain` | Yes | `sol` | `sol` / `bsc` / `base` / `eth` |
| `--window` | No | `5m` | Aggregation window for sort and default filters: `1m` / `5m` / `30m` / `1h` / `4h` / `24h` |
| `--sort-by` | No | `volume` | Ranking field: `volume` / `market_cap` / `trade_count` / `holder` |
| `--direction` | No | `desc` | `asc` / `desc` |
| `--limit` | No | `50` | 1 – 100 tokens per scan (Birdeye hard cap 100 per page, offset not exposed to keep CU predictable) |
| `--platform` | No | *(all)* | Platform launchpad filter name, e.g. `--platform pump.fun` |
| `--offset` | No | `0` | Pagination offset (0 – 10000 by Birdeye rules). **Avoid deep pagination to save user time; Birdeye recommends scroll API for batch work. Only use offset when user explicitly asks "next page".** |
| **Server-side numeric filters** | No | *(none)* | Applied by Birdeye, reduce result rows early (cheapest CU strategy): |
| `--min-market-cap` / `--max-market-cap` | No | — | USD |
| `--min-liquidity` / `--max-liquidity` | No | — | USD |
| `--min-volume` | No | — | USD, measured over the selected `--window` |
| `--min-price-change-pct` | No | — | Percentage (e.g. `10` = ≥ +10% in the window). Birdeye only has MIN, not MAX — max filter is client-side when hydrate is on. |
| `--min-trade-count` | No | — | Count in the window |
| `--min-holder` | No | — | Holder count (absolute, not %) |
| **Hydrate + client-side filters** | No | *(off)* | Require `--hydrate`; costs extra CU (see table above): |
| `--hydrate` | No | `off` | `off` / `top10` / `top20` / `all` — how many of the top-N rows get the security/overview/SM hydration pass |
| `--min-smart-money` | No | — | Req. hydrate ≥ top10. Min number of Birdeye-tagged smart traders holding the token. (Smart Money batch is top-100 ranking → tokens outside show `N/A` not 0.) |
| `--max-dev-hold-pct` | No | — | Req. hydrate. Max percentage of supply still held by the creator/deployer wallet. (Recommended safe zone: `--max-dev-hold-pct 5`.) |
| `--min-buy-ratio` | No | — | Req. hydrate. 0–1 threshold for buy_imbalance. Bullish bias: `--min-buy-ratio 0.55`. |

## `screener token` Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--chain` | Yes | `sol` / `bsc` / `base` / `eth` |
| `--address` | Yes | Token mint/contract address |
| `--window` | No | Default `5m`. Frames passed to token_overview. |
| `--no-smart-money` | No | Skip the 20 CU Smart Money batch join. |

## Response Field Reference

Every row in `scan --raw` JSON output contains these fields. For non-raw the CLI prints a compact table.

**MVP fields (always present, 50 CU):**

| Field | Type | Meaning |
|-------|------|---------|
| `address` | string | Token contract/mint address |
| `symbol` | string | Ticker |
| `name` | string | Full name |
| `market_cap` | number USD | Current circulating market cap |
| `liquidity` | number USD | Pool liquidity |
| `volume` | number USD | Volume in the scan window |
| `trade_count` | integer | Trade count in window |
| `holder` | integer | Unique holder count |
| `price_change_pct` | number % | Price change over the window. Can be negative. |
| `price` | number USD | Latest price |
| `fdv` | number USD | Fully diluted valuation (total supply × price) |
| `platform_name` | string or null | Launchpad platform when Birdeye reports it |
| `last_trade_unix_time` | integer | Unix seconds of the most recent swap |
| `recent_listing_unix_time` | integer | Unix seconds of listing creation |
| `snapshot_time` | ISO string | Birdeye's `updateTime` timestamp for the scan |
| `cu_used_total` | integer | Total CU charged for this run (MVP + hydrate + SM) |
| `latency_ms` | integer | Round-trip wall-clock in ms |

**Hydrate fields (only when `--hydrate top10/top20/all`):**

| Field | Type | Meaning | Pipeline-gap signal |
|-------|------|---------|---------------------|
| `dev_hold_pct` | number % or null | `creatorPercentage * 100` from token_security. Share of supply held by the deployer/creator wallet. | `null` → `⚠signal_gap` |
| `top10_holder_pct` | number % or null | Top-10 non-LP wallet concentration, ×100. (Not including pool/LP addresses where Birdeye marks them as contract.) | `null` → `⚠signal_gap` |
| `smart_money_count` | integer or null | `smart_traders_no` from the Smart Money top-100 list for the chain. Join on token address. | `null` = token is **not in today's SM top 100 ranking**. Never treat as 0. Print as `N/A`. |
| `buy_imbalance_ratio` | number 0–1 or null | `buy5m / (buy5m + sell5m)` from token_overview frames=5m. 0.5 = balanced. > 0.55 = bullish skew. < 0.45 = bearish skew. | `null` → `⚠signal_gap` |
| `unique_wallet_5m` | integer or null | Unique wallets trading the token within 5m. | `null` → `⚠signal_gap` |

## Invariants to Check Before Rendering (Pipeline Gap Detection)

Run these checks after every scan. If any fail, tag the row with a tiny `⚠pipeline_gap` badge in the output column:

1. `volume >= 0`, `liquidity >= 0`, `market_cap >= 0` (non-negative).
2. `market_cap <= fdv` (within ±1% — if not, token has weird circulating supply math).
3. For hydrated rows: `dev_hold_pct + top10_holder_pct <= 105` (±5% tolerance for rounding; >105 means overlap or double-count → gap).
4. For hydrated rows: if `holder == 0` but `trade_count > 0` → gap.
5. Price-change sanity: `price_change_pct` must be within ±0.5% of the formula `(price - history_price) / history_price * 100` whenever both come from the same source. If they differ > 1% → gap.

## Error Handling

- **401 / Invalid API Key** → Print: `[E401] Birdeye rejected the key. Run `screener config --apply <NEW_KEY>` to update.`
- **403 / Forbidden** → Print: `[E403] Key is valid but this route (or chain) is blocked by your Birdeye plan tier. Upgrade or use a different filter.`
- **429 / Rate Limit** → Print: `[E429] Birdeye rate-limited. X-RateLimit-Reset header = <TS> (local time: <HH:MM>). Wait until then, or reduce `--limit` / `--hydrate` depth.` Do NOT retry more than once automatically — user pays CU for each attempt.
- **500** → Print: `[E500] Birdeye upstream error. Retry with same params; if persistent check Birdeye status.`

## Common Usage Examples

```bash
# Default MVP scan — Solana, 5-minute window, sort by volume, top 50.
# Cost: 50 CU. No hydration.
python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_screener.py scan --chain sol

# Same but 1m window, pump.fun only, min 50k liquidity, sort by trade_count, top 20.
# Cost: 50 CU.
python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_screener.py scan \
  --chain sol --window 1m --sort-by trade_count --limit 20 \
  --platform pump.fun --min-liquidity 50000

# Full signal scan — Solana 5m top 20, hydrate signals, filter:
#   smart money ≥ 5 wallets, dev hold ≤ 5% supply, buy ratio ≥ 0.55
# Cost: 50 + 20×48 + 20 = 1030 CU.
python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_screener.py scan \
  --chain sol --window 5m --sort-by volume --limit 20 \
  --min-market-cap 10000 --min-liquidity 10000 \
  --hydrate top20 \
  --min-smart-money 5 --max-dev-hold-pct 5 --min-buy-ratio 0.55

# BSC scan, new Moonshot tokens with min 10% price gain 5m.
# Cost: 50 CU.
python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_screener.py scan \
  --chain bsc --window 5m --sort-by volume --limit 30 \
  --platform moonshot --min-price-change-pct 10

# Single-token deep dive.
# Cost: 18 (overview) + 30 (security) + 20 (SM batch) = 68 CU.
python3 /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/scripts/birdeye_screener.py token \
  --chain sol --address So11111111111111111111111111111111111111112
```
