---
name: wallet-style
description: "Tag a crypto wallet's trading style from a 20-cell frequency × P&L grid, with a speed subtitle and risk badges. Use when the user asks about a wallet's trading style, whether it is a scalper or swing trader, copy-trade behaviour, wallet frequency, hold time, or trade pacing."
argument-hint: "wallet-style --chain <sol|bsc|base|eth> --wallet <ADDR> [--duration <7d|30d>] [--pnl-method <wac|net_cash>] [--format <ui|json|telegram|plain|raw-json>]"
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
- The tx-list block can be skipped (−30 CU) when only the grid position is needed

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → proceed. exit `1` → `birdeye-cli config --apply <KEY>`
  (writes `~/.config/birdeye/.env`, chmod 600).

Fallback CLI: `python3 birdeye_cli.py wallet-style ...`.

## Usage

```bash
birdeye-cli wallet-style --chain sol --wallet <ADDR> --duration 30d --format plain
birdeye-cli wallet-style --chain sol --wallet <ADDR> --skip-tx-list --format json
```

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` |
| `--wallet` | — | **required**, wallet address |
| `--duration` | `30d` | `7d` · `30d` |
| `--pnl-method` | `wac` | `wac` · `net_cash` |
| `--skip-tx-list` | off | drop `/v1/wallet/tx_list` (−30 CU); no speed/scaling/gas badges |
| `--skip-first-tx` | off | drop wallet age (reuses permanent CSV cache when present) |
| `--format` | `ui` | `ui` · `json` · `telegram` · `plain` · `raw-json` |

## CU

~90 CU: PnL summary 30 + details 30 + tx_list ~30; first-funded cached = 0.

## Error handling

`[E401]` bad key → `config --apply <KEY>` · `[E403]` tier/route blocked ·
`[E429]` rate-limited, back off · `[E500]` Birdeye upstream, retry.
