# Skill #1 · Trending List

## High-Level Concept

Returns the hottest tokens on a chain straight from Birdeye's trending
endpoint. This skill is a **pure API passthrough** — it does not score or
re-rank anything. The rows are exactly what `/defi/token_trending` returns.

> Need a scored ranking? Use **Skill #22 · `token-trending-score`**
> ([docs](token-trending-score-workflow.md)) — that skill owns the momentum
> model (`classic` / `hybrid`). Skill #1 deliberately stays a thin wrapper.

## Core Capabilities

- Pure API passthrough — no local score, no local re-ranking
- One `/defi/token_trending` call returns the whole list at **30 CU**
- Compact discover params only: chain, mode, interval, sort, limit, offset, optional platform
- `mode=selective` is the default and supports all intervals; `classic` supports 1h, 4h and 24h only
- `ui` renders a dense screener-style leaderboard with summary cards
- Token logos carry a small bottom-right badge for the row's chain; this matters most on `multi_chain`
- `json` / `raw-json` return the upstream Birdeye payload

## Inputs

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `chain` | enum | `solana` | solana / bsc / base / ethereum / arbitrum / robinhood / multi_chain |
| `mode` | enum | `selective` | `selective` for all intervals; `classic` for 1h / 4h / 24h |
| `sort_by` | enum | `rank` | rank / volumeUSD / liquidity (Birdeye-side sort) |
| `sort_type` | enum | auto | `rank` → asc, everything else → desc |
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

`ui` and `plain` are local renderings for humans. `json` / `raw-json` keep the upstream payload
shape so bots and downstream scripts do not need to undo a local wrapper.

### Row

```json
{
  "rank": 1,
  "address": "...",
  "chain": "solana",
  "chain_label": "Solana",
  "symbol": "SOL",
  "name": "Solana",
  "logo_uri": "https://...",
  "price": 150.0,
  "fdv": 6.6e10,
  "marketcap": 6.6e10,
  "liquidity": 6.6e9,
  "volume_interval": 1.2e9,
  "price_change_interval_pct": 4.2
}
```

`volume_interval` and `price_change_interval_pct` follow the `--interval` you pass
(`5m` · `30m` · `1h` · `4h` · `24h`) — the endpoint returns one interval per call, so the
table exposes a single `Vol(<interval>)` and `<interval> %` column rather than a fixed
5m/1h/4h/24h set.

### UI envelope

| Field | Description |
|-------|-------------|
| `kind` | `trending-list-v1` |
| `params` | Echo of every input |
| `source` / `source_label` | `birdeye` and its human label |
| `sort_note` | How the list ended up ordered |
| `platform_note` | Set when a `--platform` filter could not be applied |
| `n_tokens` | Row count |
| `rows` | The Birdeye rows |
| `raw_response` | Full upstream payload, preserved for inspection |
| `cu_breakdown` | Per-step CU, e.g. `["token_trending=30"]` |

## CLI

```bash
# Birdeye trending only (30 CU)
python3 birdeye_cli.py trending-list --chain solana --mode selective --interval 24h --sort-by rank --limit 20

# Sort Birdeye-side by volume
python3 birdeye_cli.py trending-list --chain solana --mode classic --sort-by volumeUSD --interval 4h --limit 20 --format telegram
```
