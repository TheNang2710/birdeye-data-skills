---
name: price-surge
description: "Scan a chain for price-surge signals inside a market-cap band and auto-filter high-risk tokens (rug-pull, wash trading, honeypots). Use when the user wants surging / pumping tokens right now, a momentum screener within a market-cap range, or a risk-screened surge list. Starts from Birdeye's token list v3 and, in advanced mode, hydrates per-token top-trader and holder-health data, with an optional security check."
argument-hint: "price-surge --chain <solana|bsc|base|ethereum|arbitrum|robinhood> [--interval <1m|5m|30m|1h|2h|4h|8h|24h|7d|30d>] [--mode <standard|advanced>] [--min-price-change <pct>] [--min-market-cap <usd>] [--max-market-cap <usd>] [--min-liquidity <usd>] [--min-volume <usd>] [--sort-by <price_change|volume|market_cap|liquidity|trade_count|holder>] [--sort-type <desc|asc>] [--limit <1..100>] [--offset <n>] [--top <n>] [--with-security] [--format <ui|json|telegram|plain>]"
metadata:
  cliHelp: "birdeye-cli price-surge --help"
  cuTypical: 50
  endpoint: "/defi/v3/token/list"
---

# Price Surge Screen

Surge screener that starts from Birdeye's **token list v3** and layers a
risk screen on top. Two cost tiers, one shared feed:

- **`standard`** — a single `/defi/v3/token/list` call (**50 CU flat**). The surge,
  liquidity, volume and market-cap filters are applied server-side, then
  structural rug + wash proxies run locally.
- **`advanced`** — the same list plus per-token hydration for the top rows:
  top-trader tags and holder-profile cohorts, with an optional `--with-security`
  security check (+30 CU/row).

The CLI decides what to fetch, filter and exclude — the caller only picks the
chain, the surge window, the market-cap band and the risk caps.

## Core Capabilities

- Market-cap **range** filtering (min / max) applied server-side, so the band costs nothing extra
- Auto-excludes high-risk tokens in two passes:
  - **list pass** (always): stale market cap, zero liquidity, zero-holders-with-trades, thin liquidity, honeypot proxy (no sell side), wash-trade churn
  - **advanced pass**: confirmed honeypot, honeypot tax, rug-pull proxies, dev-hold and top-10 concentration over the caps, low KOL
- Per-token **basic info**: price · market cap · liquidity · volume · trades · holders · dev holding · KOL buyer count
- Per-token **security check** (opt-in via `--with-security`): honeypot detection, mint / freeze renouncement, metadata open-source status, LP lock, buy/sell tax, top-10 concentration
- Per-token **holder health**: top-10 concentration, per-cohort tag distribution, profitable-wallet ratio
- Every excluded row is kept in a visible *Auto-filtered* table with its reason — nothing is dropped silently
- `--no-auto-filter` turns the exclusion off; `--no-holder-health` skips the Solana holder call
- Runs on `solana` · `bsc` · `base` · `ethereum` · `arbitrum` · `robinhood`
- `ui` renders a compact **list-row table** with a stat strip, one collapsed *health* cell and one collapsed *security* cell; `plain` and `telegram` render compact lists

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → proceed.
- exit `1` → `birdeye-cli config --apply <KEY>` (writes `~/.config/birdeye/.env`, chmod 600).

Fallback CLI: `python3 birdeye_cli.py price-surge ...`.

## Usage

```bash
# Cheapest run — one token-list call, 50 CU
birdeye-cli price-surge --chain solana --interval 1h --mode standard \
  --min-price-change 50 --min-market-cap 50000 --max-market-cap 5000000 --limit 10 --format plain

# Advanced — hydrate holder health for the top 10 rows, plus the security check
birdeye-cli price-surge --chain solana --interval 1h --mode advanced \
  --with-security --min-market-cap 50000 --max-market-cap 5000000 --top 10 \
  --max-top10-pct 60 --max-dev-hold-pct 15 --format ui

# Keep everything (no exclusion) and dump the upstream payload
birdeye-cli price-surge --chain solana --interval 1h --no-auto-filter --limit 50 --format json
```

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `solana` | `solana` · `bsc` · `base` · `ethereum` · `arbitrum` · `robinhood` |
| `--interval` | `1h` | Surge window: `1m` · `5m` · `30m` · `1h` · `2h` · `4h` · `8h` · `24h` · `7d` · `30d` |
| `--mode` | `standard` | `standard` = token list v3 only; `advanced` = list + per-token hydration |
| `--min-price-change` | `50` | Surge floor: minimum price change % over `--interval` |
| `--min-market-cap` / `--max-market-cap` | — | Lower / upper bound of the market-cap band (server-side) |
| `--min-liquidity` / `--max-liquidity` | `10000` / — | Liquidity floor / ceiling |
| `--min-volume` | `5000` | Minimum traded USD volume over `--interval` |
| `--min-trade-count` | — | Minimum trade count over `--interval` |
| `--min-holders` | — | Minimum holder count |
| `--platform` | — | Launch platform, e.g. `pump.fun` |
| `--sort-by` | `price_change` | `price_change` · `volume` · `market_cap` · `liquidity` · `trade_count` · `holder` |
| `--sort-type` | `desc` | `desc` · `asc` |
| `--limit` | `10` | Rows to return, 1..100 |
| `--offset` | `0` | Pagination offset |
| `--top` | `10` | advanced: hydrate at most this many of the top kept rows (CU bound) |
| `--with-security` | off | advanced: add the per-token security check (`/defi/token_security`, +30 CU/row) |
| `--no-auto-filter` | off | Keep every row, switch off the automatic exclusion |
| `--no-holder-health` | off | advanced: skip the holder profile call (Solana only, −30 CU/row) |
| `--max-liq-mcap-ratio` | `0.005` | Exclude when liquidity / market_cap falls below this (rug-pull proxy) |
| `--max-trades-per-wallet` | `150` | Exclude when 24h trades / 24h unique wallets exceeds this (wash-trade proxy) |
| `--max-dev-hold-pct` | — | advanced: exclude when dev holds more than this % of supply |
| `--max-top10-pct` | — | advanced: exclude when top-10 holders own more than this % of supply |
| `--min-kol-buyers` | — | advanced: exclude when the tagged KOL buyer count is below this |
| `--format` | `ui` | `ui` · `json` · `telegram` · `plain` |

## Cost

| Tier | Calls | CU |
|---|---|---|
| `standard` | `/defi/v3/token/list` | **50** flat |
| `advanced` | list + per hydrated row: `/defi/v2/tokens/top_traders`, and on Solana `/token/v1/holder-profile` | 50 + 60 × hydrated rows (30 on non-Solana) |
| `advanced --with-security` | as above + `/defi/token_security` per hydrated row | 50 + 90 × hydrated rows (60 on non-Solana) |

`--top` bounds the advanced spend; the holder-profile call is Solana-only.
Security doubles as the top-10% source on every chain, so no separate
holder-distribution call is needed.

## Output

- `ui`: compact list-row table with a stat strip, a collapsed *health* cell and a collapsed *security* cell + an *Auto-filtered* table
- `plain`: compact terminal table
- `telegram`: per-token guard summary
- `json`: upstream response payload

Every row keeps `risk_flags` and (for excluded rows) `exclude_reason`, so the screen stays auditable.

## Error handling

`[E401]` bad key → `config --apply <KEY>` · `[E403]` tier/route blocked ·
`[E429]` rate-limited, back off · `[E500]` Birdeye upstream, retry.
Holder profile is Solana-only; on other chains it is skipped and flagged.
