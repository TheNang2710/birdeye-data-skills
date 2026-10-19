# Birdeye API mapping table used by the skill

## Base URL
`https://public-api.birdeye.so`

Header: `X-API-KEY: <YOUR_KEY>` + `x-chain: solana|bsc|base|ethereum`

## Endpoints used

| Purpose | Endpoint | CU | Notes |
|---------|----------|----|-------|
| MVP screener list | `GET /defi/v3/token/list` | 50 | Sort + server-side numeric filters + platform filter. Max limit 100, offset 0-10000. Items under `data.items[]`. |
| Dev holding share | `GET /defi/token_security` | 30 / token | Fields: `creatorPercentage` (×100 = %), `top10UserPercent`. Solana + EVM schemas differ; code accesses via the common keys. |
| Buy count for Buy Imbalance proxy | `GET /defi/token_overview` | 18 / token | `frames=5m` returns `buy5m`, `sell5m`, `uniqueWallet5m`. `buy_imbalance = buy5m / (buy5m + sell5m)`. |
| Smart money trader count | `GET /smart-money/v1/token/list` | 20 / batch | Sort=`smart_traders_no`, limit=100. Token match join on `token` → address. Returns `smart_traders_no` per address. Only covers today's top-100 SM-ranked tokens; unranked = `N/A`, not 0. |

## Sort fields -> Birdeye sort_by mapping

All `volume_*`, `trade_*`, `price_change_*` have per-window suffixes: `_1m_usd`, `_5m_percent`, etc.

| User-facing sort | Birdeye `sort_by` |
|------------------|-------------------|
| volume           | `volume_<window>_usd` |
| market_cap       | `market_cap` |
| trade_count      | `trade_<window>_count` |
| holder           | `holder` |

## Coverage gaps

| Desired field | Birdeye equivalent | Workaround |
|--------------------|-------------------|------------|
| `bundler_rate` | Not exposed | Use `buy_imbalance_ratio` proxy instead. Label "Buy Imbalance", never "Bundle Rate" to avoid misleading. |
| `rug_ratio` / `is_honeypot` (EVM) | Not in list; token_security exposes honeypot only on EVM | Always hydrate per token; on Solana show N/A. |
| `smart_degen_count` filter (server-side) | Only in separate SM list endpoint | Run SM batch list then client-side filter. |

## CU accounting

Hard-coded in the script (`CU` dict). Keep in sync if Birdeye updates CU prices:

```
MVP  = 50 CU (always)
Per-token hydrate = security 30 + overview 18 = 48 CU
SM batch join     = 20 CU (once per scan, regardless of topN depth)
```

Hydrate cost matrix:
- top10: 50 + 480 + 20 = 550 CU
- top20: 50 + 960 + 20 = 1030 CU
- all (100): 50 + 4800 + 20 = 4870 CU

## Pipeline invariants (run before render)

1. `market_cap >= 0`, `liquidity >= 0`, `volume >= 0`
2. `market_cap <= fdv * 1.01` (±1%)
3. `holder == 0` → `trade_count must == 0` (±1 tolerance)
4. Hydrated: `dev_hold_pct + top10_holder_pct <= 105` (±5% rounding tolerance)
5. Price-change sanity: optional. Compare returned `priceChange<W>Percent` with manual `(price - history_price) / history_price` when both are present. Flag > 1% discrepancy.
