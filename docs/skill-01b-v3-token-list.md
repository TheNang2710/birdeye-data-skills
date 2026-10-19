# Skill #1b · V3 Token List

## High-Level Concept

V3 token list endpoint with `min_volume` filter and enriched trade_count/holders data. More flexible than Skill #1 for screening.

## Inputs

| Field | Type | Description |
|-------|------|-------------|
| `chain` | enum | sol / bsc / base / eth / arc / robinhood |
| `min_volume` | float | Minimum 24h volume (USD) |
| `sort_by` | enum | volume / market_cap / holders |
| `offset` | int | Pagination offset |
| `limit` | int | Max results |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| V3 token list | `/defi/v3/token/list` | 50 |

## CLI

```bash
python3 birdeye_cli.py v3-token-list --chain sol --min_volume 1000000 --sort_by volume
```
