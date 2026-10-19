# Skill #1 · Trending List

## High-Level Concept

Fetches the hottest tokens by volume/rank/liquidity from Birdeye's trending endpoint. Returns a sortable list with key metrics (price, volume, liquidity, market cap, holder count).

## Inputs

| Field | Type | Description |
|-------|------|-------------|
| `chain` | enum | sol / bsc / base / eth / arc / robinhood |
| `sort_by` | enum | rank / volume / liquidity |
| `interval` | enum | 5m / 15m / 1h / 4h / 24h |
| `platform` | string | Filter by launch platform (e.g. pump.fun) |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| Trending tokens | `/defi/token_trending` | 30 |

## Output Fields

```json
{
  "rows": [
    {"address": "...", "symbol": "SOL", "price": 150.0,
     "volume_24h": 1.2e9, "liquidity": 6.6e9, "market_cap": 6.6e10,
     "holders": 8651021, "rank": 1}
  ]
}
```

## CLI

```bash
python3 birdeye_cli.py trending-list --chain sol --sort_by volume --interval 24h
```
