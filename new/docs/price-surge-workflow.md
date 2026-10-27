# Skill #2 · Price Surge Screen

## High-Level Concept

Finds tokens that are **surging right now inside a market-cap band**, then
automatically removes the ones carrying obvious rug / wash / honeypot risk.

The feed is Birdeye's **token list v3** (`/defi/v3/token/list`). That endpoint
already accepts the surge, liquidity, volume and market-cap filters
server-side, so the cheap tier is a single call. The skill adds a two-pass
risk screen on top and, in `advanced` mode, hydrates a bounded number of rows
with per-token top-trader and holder-health data — plus an optional per-token
security check (`--with-security`).

> The caller only chooses the chain, the surge window, the market-cap band and
> the caps. Which endpoint backs each field is an implementation detail — the
> CLI decides what to fetch and what to exclude.

## Core Capabilities

- Market-cap **range** filtering (min / max), applied server-side
- Two-pass **auto-exclusion** of high-risk rows (list proxies → advanced checks)
- **Basic info** per token: price · market cap · liquidity · volume · trades · holders · dev holding · KOL buyer count
- **Security check** per token (opt-in via `--with-security`): honeypot detection, mint / freeze renouncement, metadata open-source status, LP lock, buy/sell tax, top-10 concentration
- **Holder health** per token: top-10 concentration, cohort tag distribution, profitable-wallet ratio
- Excluded rows stay visible with their reason instead of being dropped silently
- Compact **list-row table UI** with a stat strip, a single collapsed *health* cell and a single collapsed *security* cell, plus an *Auto-filtered* table

## Inputs

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `chain` | enum | `solana` | solana / bsc / base / ethereum / arbitrum / robinhood |
| `interval` | enum | `1h` | Surge window: 1m / 5m / 30m / 1h / 2h / 4h / 8h / 24h / 7d / 30d |
| `mode` | enum | `standard` | `standard` = token list v3 only; `advanced` = list + per-token hydration |
| `min_price_change` | number | `50` | Surge floor — minimum price change % over `interval` |
| `min_market_cap` / `max_market_cap` | number | — | Market-cap band (server-side) |
| `min_liquidity` / `max_liquidity` | number | `10000` / — | Liquidity floor / ceiling |
| `min_volume` | number | `5000` | Minimum traded USD volume over `interval` |
| `min_trade_count` | int | — | Minimum trades over `interval` |
| `min_holders` | int | — | Minimum holder count |
| `platform` | string | — | Launch platform, e.g. `pump.fun` |
| `sort_by` | enum | `price_change` | price_change / volume / market_cap / liquidity / trade_count / holder |
| `sort_type` | enum | `desc` | desc / asc |
| `limit` | int | `10` | Rows to return, 1–100 |
| `offset` | int | `0` | Pagination offset |
| `top` | int | `10` | advanced: hydrate at most this many top kept rows (CU bound) |
| `with_security` | bool | off | advanced: add the per-token security check (`/defi/token_security`, +30 CU/row) |
| `no_auto_filter` | bool | off | Keep every row, switch off the automatic exclusion |
| `no_holder_health` | bool | off | advanced: skip the holder profile call (Solana only, −30 CU/row) |

### Advanced risk caps

| Field | Default | Excludes when |
|-------|---------|---------------|
| `max_liq_mcap_ratio` | `0.005` | liquidity / market_cap below the ratio |
| `max_trades_per_wallet` | `150` | 24h trades / 24h unique wallets above the ratio |
| `max_dev_hold_pct` | — | dev holds more than this % of supply |
| `max_top10_pct` | — | top-10 holders own more than this % of supply |
| `min_kol_buyers` | — | tagged KOL buyer count below this |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| Surge feed | `/defi/v3/token/list` | 50 |
| Security, per hydrated row (`--with-security`) | `/defi/token_security` | 30 |
| Top traders, per hydrated row (advanced) | `/defi/v2/tokens/top_traders` | 30 |
| Holder profile, per hydrated row (advanced, Solana) | `/token/v1/holder-profile` | 30 |

- **`standard`** → 50 CU flat.
- **`advanced`** → `50 + 60 × hydrated_rows` on Solana, `50 + 30 × hydrated_rows` on other chains (the holder profile call is Solana-only).
- **`advanced --with-security`** → `50 + 90 × hydrated_rows` on Solana, `50 + 60 × hydrated_rows` on other chains.
- `--top` bounds the hydrated row count, and therefore the advanced spend.
- Security doubles as the top-10% source on every chain (`top10HolderPercent` + `creatorPercentage`), so no separate holder-distribution call is needed.

## Filters & Auto-Exclusion

Two passes. Every failed row keeps its **reason** and is listed in the
*Auto-filtered* table, so the screen is reversible (`--no-auto-filter`) and
auditable.

### Pass 1 — list proxies (always on in `standard` and `advanced`)

| Reason | Rule |
|--------|------|
| `stale_market_cap` | market_cap > fdv × 1.01 |
| `no_liquidity` | liquidity ≤ 0 |
| `zero_holders_with_trades` | holder == 0 while trades > 0 in the window |
| `thin_liquidity` | liquidity / market_cap below `--max-liq-mcap-ratio` |
| `honeypot_proxy` | buys ≥ 20 while sells == 0 in the last 24h (no sell side) |
| `wash_trade_proxy` | 24h trades / 24h unique wallets above `--max-trades-per-wallet` |

### Pass 2 — advanced checks (only in `advanced`, only for hydrated rows)

| Reason | Rule |
|--------|------|
| `honeypot` | security `isHoneypot` is true (where the chain reports it) |
| `honeypot_tax` | transfer fee ≥ 90% |
| `high_transfer_tax` | transfer fee ≥ 10% (flag only) |
| `rug_pull_risk` | LP not locked while mint / freeze / metadata authority is still live |
| `dev_hold_over_limit` / `high_dev_hold` | dev hold above `--max-dev-hold-pct`, or ≥ 10% (flag) |
| `top10_over_limit` / `top10_concentration` | top-10 above `--max-top10-pct`, or ≥ 50% (flag) |
| `low_kol_buyers` | KOL buyer count below `--min-kol-buyers` |

Top-10 concentration and dev hold in pass 2 come from the security payload
(`top10HolderPercent` / `creatorPercentage`) when `--with-security` is set;
otherwise they are left empty and those two caps simply do not fire.

## Output

### Row

```json
{
  "rank": 1,
  "address": "...",
  "symbol": "TGC",
  "name": "...",
  "logo_uri": "https://...",
  "chain": "solana",
  "price": 0.000059,
  "market_cap": 58510.0,
  "fdv": 60000.0,
  "liquidity": 23720.0,
  "holder": 67,
  "volume_interval": 5840.0,
  "price_change_interval_pct": 31.4,
  "trade_interval_count": 85,
  "liq_mcap_ratio": 0.405,
  "trades_per_wallet_24h": 12.1,
  "dev_hold_pct": 12.4,
  "top10_holder_pct": 48.7,
  "kol_buyer_count": null,
  "profitable_wallet_ratio": 60.0,
  "security": {
    "honeypot": null,
    "mint_renounced": true,
    "freeze_renounced": true,
    "open_source_status": "immutable",
    "lp_locked": null,
    "transfer_fee_pct": 0.0
  },
  "holder_tags": {
    "bundler": {"holder_count": 29, "percent_of_supply": 8.6},
    "sniper": {"holder_count": 3, "percent_of_supply": 1.2}
  },
  "risk_flags": [],
  "excluded": false
}
```

`security`, `dev_hold_pct` and `top10_holder_pct` are only filled when
`--with-security` is set; `holder_tags` / `profitable_wallet_ratio` only when
the row was hydrated in `advanced` mode. Unhydrated rows keep every optional
field `null`.

### UI envelope

| Field | Description |
|-------|-------------|
| `kind` | `price-surge-v1` |
| `params` | Echo of every input, including the advanced caps |
| `source` / `source_label` | `birdeye` and `Birdeye /defi/v3/token/list` |
| `mcap_range` / `sort_note` | Human-readable band and ordering |
| `n_scanned` / `n_rows` / `n_excluded` / `n_hydrated` | Scan counts |
| `hydration_note` | Set when hydration was skipped or bounded |
| `dropped` | `{symbol, address, reason, flags}` for every excluded row |
| `rows` | Kept rows (advanced fields filled only on hydrated rows) |
| `raw_response` | Full upstream token-list payload |
| `cu_breakdown` | Per-step CU, e.g. `["token_list_v3=50", "security=30x3", "top_traders=30x3"]` |

## Field Sources

| Field group | Source |
|-------------|--------|
| Price · market cap · liquidity · volume · trades · holders · price change | `/defi/v3/token/list` |
| Honeypot · mint/freeze renouncement · metadata status · LP lock · transfer tax · top-10 concentration · dev hold (`--with-security`) | `/defi/token_security` |
| Cohort tag distribution (dev · bundler · sniper · insider) | `/token/v1/holder-profile` (Solana) |
| KOL buyer count · profitable-wallet ratio | `/defi/v2/tokens/top_traders` |

KOL is not a native Birdeye tag — the counter is best-effort and reports
**n/a** when no KOL-like tag is present rather than a misleading `0`.

## CLI

```bash
# Cheapest screen — 50 CU
python3 birdeye_cli.py price-surge --chain solana --interval 1h --mode standard \
  --min-price-change 50 --min-liquidity 10000 --min-volume 5000 \
  --min-market-cap 50000 --max-market-cap 5000000 --limit 10 --format plain

# Advanced — hydrate top 10 rows with the security check, tighten the risk caps
python3 birdeye_cli.py price-surge --chain solana --interval 1h --mode advanced \
  --with-security --min-market-cap 50000 --max-market-cap 5000000 --top 10 \
  --max-top10-pct 60 --max-dev-hold-pct 15 --format ui

# Advanced without security (cheaper), top-10% caps left off
python3 birdeye_cli.py price-surge --chain solana --interval 1h --mode advanced \
  --min-market-cap 50000 --max-market-cap 5000000 --top 10 --format ui

# Keep risky rows too, and inspect the raw payload
python3 birdeye_cli.py price-surge --chain solana --interval 1h \
  --no-auto-filter --limit 50 --format json
```
