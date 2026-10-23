# Skill #1 · Trending List

## High-Level Concept

Returns the hottest tokens on a chain straight from Birdeye's trending
endpoint. This skill is a **pure API passthrough** — it does not score or
re-rank anything. The rows are exactly what `/defi/token_trending` returns.

> Need a scored ranking? Use **Skill #22 · `token-trending-score`**
> ([docs](skill-22-token-trending-score.md)) — that skill owns the momentum
> model (`classic` / `hybrid`). Skill #1 deliberately stays a thin wrapper.

## Inputs

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `chain` | enum | `sol` | sol / eth / bsc / base / arc / robinhood |
| `sort_by` | enum | `rank` | rank / volumeUSD / liquidity (Birdeye-side sort) |
| `sort_type` | enum | `desc` | desc / asc |
| `interval` | enum | `24h` | 5m / 30m / 1h / 4h / 24h |
| `offset` | int | `0` | Pagination offset |
| `limit` | int | `20` | Rows to return, 1–50 |
| `platform` | string | — | Best-effort client-side filter (e.g. `pump.fun`) |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| Trending tokens | `/defi/token_trending` | 30 |

Total: **30 CU** per call. No per-token follow-up calls.

## Output

### Row

```json
{
  "rank": 1,
  "address": "...",
  "symbol": "SOL",
  "name": "Solana",
  "logo_uri": "https://...",
  "price": 150.0,
  "fdv": 6.6e10,
  "marketcap": 6.6e10,
  "liquidity": 6.6e9,
  "volume_interval": 1.2e9,
  "price_change_interval_pct": 4.2,
  "volume_24h": 1.2e9,
  "price_change_24h_pct": 4.2,
  "trade_24h": 120000,
  "holder": 8651021
}
```

### Envelope

| Field | Description |
|-------|-------------|
| `kind` | `trending-list-v1` |
| `params` | Echo of every input |
| `source` / `source_label` | `birdeye` and its human label |
| `sort_note` | How the list ended up ordered |
| `platform_note` | Set when a `--platform` filter could not be applied |
| `n_tokens` | Row count |
| `rows` | The Birdeye rows |
| `cu_breakdown` | Per-step CU, e.g. `["token_trending=30"]` |

## CLI

```bash
# Birdeye trending only (30 CU)
python3 birdeye_cli.py trending-list --chain sol --interval 24h --limit 20

# Sort Birdeye-side by volume
python3 birdeye_cli.py trending-list --chain sol --sort-by volumeUSD --limit 20 --format telegram
```
