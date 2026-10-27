# Skill #6 · Spam Token Cleaner (STC)

## High-Level Concept

Sweeps multiple chains for potential spam/low-quality tokens (high market cap, very low 24h volume) and enriches them with holder concentration data via web scraping (0 Birdeye holder CU). Sorts by market cap → top wallet value → liquidity → volume asc.

## Inputs

| Field | Type | Description |
|-------|------|-------------|
| `chains` | list | sol / robinhood / base / bsc / eth |
| `min_mcap` | float | Minimum market cap (default $1B) |
| `max_volume_24h` | float | Maximum 24h volume (default $50) |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| V3 token list (per chain) | `/defi/v3/token/list` | 50 × N chains |
| Holder top1/top10% | Web scrape | 0 CU |

**Total: ~70+ CU** (varies by chain count).

## CLI

```bash
python3 birdeye_cli.py stc --chains sol,base,bsc --min_mcap 1000000000
```
