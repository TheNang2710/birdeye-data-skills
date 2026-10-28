---
name: trending-list
description: "Return Birdeye's hot-token leaderboard from `/defi/token_trending` with no local scoring or re-ranking. Use when the user wants the current trending token list, hot tokens by chain, Birdeye-ranked movers, or a lightweight discover/list view before deeper token analysis."
argument-hint: "trending-list --chain <solana|bsc|base|ethereum|arbitrum|robinhood|multi_chain> [--mode <selective|classic>] [--interval <5m|30m|1h|4h|24h>] [--sort-by <rank|volumeUSD|liquidity>] [--sort-type <desc|asc>] [--limit <1..50>] [--offset <n>] [--platform <text>] [--format <ui|json|telegram|plain|raw-json>]"
metadata:
  cliHelp: "birdeye-cli trending-list --help"
  cuTypical: 30
  endpoint: "/defi/token_trending"
---

# Trending Token List

Lightweight hot-token list from Birdeye's own trending endpoint. This skill is intentionally
simple: **one API call, one list, no local ranking model**.

## Core Capabilities

- Pure API passthrough — the ordering belongs to Birdeye, not to a local score
- One call returns the whole list at a flat **30 CU**
- Compact param set for discover mode: `chain` · `mode` · `interval` · `sort_by` · `sort_type` · `limit` · `offset`
- `selective` is the default mode and supports all intervals; `classic` supports `1h` · `4h` · `24h` only
- Optional `platform` text filter when the upstream row exposes a matching field
- UI renders a dense screener-style table plus summary cards for quick scanning
- Token logos carry a small bottom-right chain badge; on `multi_chain`, the badge follows each row's chain
- `json` / `raw-json` return the **upstream response payload**, not a wrapped local score object
- Works well as the first step before `token-dd-score` or `token-trending-score`

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → proceed.
- exit `1` → `birdeye-cli config --apply <KEY>` (writes `~/.config/birdeye/.env`, chmod 600).

Fallback CLI: `python3 birdeye_cli.py trending-list ...`.

## Usage

```bash
birdeye-cli trending-list --chain solana --mode selective --interval 24h --sort-by rank --limit 20 --format plain
birdeye-cli trending-list --chain solana --mode classic --sort-by volumeUSD --sort-type desc --interval 4h --limit 25 --format ui
birdeye-cli trending-list --chain solana --mode selective --interval 1h --limit 50 --format json
```

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `solana` | `solana` · `bsc` · `base` · `ethereum` · `arbitrum` · `robinhood` · `multi_chain` |
| `--mode` | `selective` | `selective` supports all intervals; `classic` supports `1h` · `4h` · `24h` only |
| `--interval` | `24h` | `5m` · `30m` · `1h` · `4h` · `24h` |
| `--sort-by` | `rank` | Birdeye-side sort: `rank` · `volumeUSD` · `liquidity` |
| `--sort-type` | auto | `rank` defaults to `asc`; `volumeUSD` and `liquidity` default to `desc` |
| `--limit` | `20` | 1..50 rows |
| `--offset` | `0` | pagination offset |
| `--platform` | — | best-effort text filter, e.g. `pump.fun` |
| `--format` | `ui` | `ui` · `json` · `telegram` · `plain` · `raw-json` |

## Output

- `ui`: screener-style card + compact leaderboard table
- `plain`: compact terminal table
- `telegram`: lightweight hot-list summary
- `json` / `raw-json`: upstream Birdeye response payload

This skill does **not** attach local scores, gates or heuristics. If the user wants a scored view,
send the chosen token into `token-trending-score` or `token-dd-score`.

## Error handling

`[E401]` bad key → `config --apply <KEY>` · `[E403]` tier/route blocked ·
`[E429]` rate-limited, back off · `[E500]` Birdeye upstream, retry.
