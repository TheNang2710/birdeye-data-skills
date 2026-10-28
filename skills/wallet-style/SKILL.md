---
name: wallet-style
description: "Tag a crypto wallet's trading style from a 20-cell frequency × P&L grid, with a speed subtitle and risk badges. Use when the user asks about a wallet's trading style, whether it is a scalper or swing trader, copy-trade behaviour, wallet frequency, hold time, or trade pacing."
argument-hint: "birdeye-cli wallet-style --chain <sol|bsc|base|eth> --wallet <ADDR> [--duration <7d|30d>] [--pnl-method <wac|net_cash>] [--skip-tx-list] [--skip-first-tx] [--format <ui|json|telegram|plain|raw-json>]"
metadata:
  cliHelp: "birdeye-cli wallet-style --help"
  cuTypical: 90
  axes: "frequency (x) × P&L (y)"
---

# Wallet Style

20-cell **frequency × P&L** grid plus a speed subtitle and badges (scaling, gas).
Reuses the first-funded lookup from cache (0 CU when present).

## Core Capabilities

- Places the wallet on a 20-cell frequency × P&L grid rather than returning a raw trade list
- Adds a speed subtitle (scalp / swing / hold) derived from real trade pacing
- Attaches risk badges — scaling in/out and gas behaviour — from the tx list
- Reuses the cached first-funded lookup, so wallet age costs 0 CU when already known
- The tx-list block can be skipped (`--skip-tx-list`, −~30 CU) when only the grid position is needed
- Runs on `sol` · `bsc` · `base` · `eth`

## Flow

`birdeye-cli wallet-style …` runs these steps against Birdeye.

| Step | Endpoint | What it checks / produces | Mode |
|---|---|---|---|
| 1 | `GET /wallet/v2/pnl/summary` | realized PnL, trade count and volume over `--duration` → the **frequency** and **P&L** axis values (30 CU) | always |
| 2 | `POST /wallet/v2/pnl/details` | per-token PnL breakdown, for the P&L axis quality (30 CU) | always |
| 3 | `GET /v1/wallet/tx_list` | trade history → median hold (speed subtitle), scaling-in/out and gas badges (~30 CU) | unless `--skip-tx-list` |
| 4 | `POST /wallet/v2/tx/first-funded` | wallet age / funding provenance (permanent cache → 0 CU) | unless `--skip-first-tx` |
| 5 | — | compose: place the wallet on the 4×5 grid → badge + speed subtitle | always |

~90 CU: PnL summary 30 + details 30 + tx_list ~30; first-funded cached = 0.

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → a key is resolvable, proceed.
- exit `1` → no key. Ask the user for their Birdeye API key, then run
  `birdeye-cli config --apply <KEY>` (writes `~/.config/birdeye/.env`, chmod 600).

Key order: `$BIRDEYE_API_KEY` → `~/.config/birdeye/.env` → `~/.birdeye.env` → `./.env`.
Fallback CLI: `python3 birdeye_cli.py wallet-style ...` (see the repo `README.md` for install).

## Usage

```bash
birdeye-cli wallet-style --chain sol --wallet <ADDR> --duration 30d --format plain
birdeye-cli wallet-style --chain sol --wallet <ADDR> --skip-tx-list --format json
```

## Arguments

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` |
| `--wallet` | — | **required**, wallet address |
| `--duration` | `30d` | `7d` · `30d` |
| `--pnl-method` | `wac` | `wac` (weighted avg cost) · `net_cash` (cashflow diff) |
| `--skip-tx-list` | off | drop `/v1/wallet/tx_list` (−~30 CU); no speed / scaling / gas badges |
| `--skip-first-tx` | off | drop wallet age (reuses permanent cache when present) |
| `--format` | `plain` on the CLI | `ui` · `json` · `telegram` · `plain` · `raw-json` |

## Cost

| Run | CU |
|---|---|
| Full run (`30d`) | **~90** |
| `--skip-tx-list` | −~30 (grid only, no speed subtitle / badges) |
| First-funded cache hit | step 4 = 0 |
| Replay from history / cache | 0 |

## Output

- `plain`: badge + axes + speed subtitle in a compact block
- `json` / `raw-json`: the full result envelope, including the grid cell and axis levels
- `telegram`: compact badge summary
- `ui`: main badge + frequency/P&L axes + context badges

Read it in this order:

1. **Main badge** — emoji + style name (e.g. `Old Hunter`) from the grid cell.
2. **Frequency axis** — `L1 Rare` / `L2 Regular` / `L3 Frequent` / `L4 Machine` (trades/day).
3. **P&L axis** — `P5 Strong Profit` … `P1 Heavy Loss`.
4. **Speed subtitle** — median hold time (present only when the tx list was fetched).
5. **Context badges** — e.g. `Thin Sample` for a low trade count.
6. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | re-run `config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
