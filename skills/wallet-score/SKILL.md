---
name: wallet-score
description: "Score a crypto wallet's alpha and copy-tradeability on Birdeye. Four components — Profitability (P40), Consistency (C25), Quality (Q20), Activity (A15) — with hard filters (tx >= 20, volume >= $5k, rug% <= 50%). Use when the user asks to score a wallet, judge wallet or trader quality, copy-trade score, wallet alpha, wallet PnL review, or whether a wallet is worth copying."
argument-hint: "wallet-score --chain <sol|bsc|base|eth> --wallet <ADDR> [--duration <all|90d|30d|7d|24h>] [--pnl-method <wac|net_cash>] [--include <blocks>] [--format <ui|json|telegram|plain|raw-json>]"
metadata:
  cliHelp: "birdeye-cli wallet-score --help"
  cuWorst: 110
  cuEarlyFail: 30
  components: "profitability(0.40), consistency(0.25), quality(0.20), activity(0.15)"
---

# Wallet Score

Four-component score for a single wallet: **P40 / C25 / Q20 / A15**. Hard filters
(`tx >= 20`, `volume >= $5k`, `rug% <= 50%`) short-circuit low-quality wallets.

## Core Capabilities

- Two verdicts in one run: a 0–100 alpha score and a copy-tradeability score
- Four weighted components — Profitability (P40), Consistency (C25), Quality (Q20), Activity (A15)
- Hard filters (tx >= 20, volume >= USD 5k, rug% <= 50%) short-circuit obviously low-quality wallets before the full spend
- First-Tx funding provenance is resolved and cached permanently, so repeat runs cost 0 CU for that block
- PnL method is selectable — weighted-average cost (`wac`) or cashflow difference (`net_cash`)
- Every fetch block can be skipped (`--skip-rug` / `--skip-portfolio` / `--skip-first-tx`) to trim CU

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → a key is resolvable, proceed.
- exit `1` → ask the user for their Birdeye API key, then
  `birdeye-cli config --apply <KEY>` (writes `~/.config/birdeye/.env`, chmod 600).

Key order: `$BIRDEYE_API_KEY` → `~/.config/birdeye/.env` → `~/.birdeye.env` → `./.env`.
Fallback CLI: `python3 birdeye_cli.py wallet-score ...`.

## Usage

```bash
birdeye-cli wallet-score --chain sol --wallet <ADDR> --duration 30d --format plain
birdeye-cli wallet-score --chain sol --wallet <ADDR> --include pnl,tokens,score --format compact
```

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` |
| `--wallet` | — | **required**, wallet address |
| `--duration` | `30d` | `all` · `90d` · `30d` · `7d` · `24h` |
| `--pnl-method` | `wac` | `wac` (weighted avg cost) · `net_cash` (cashflow diff) |
| `--skip-rug` | off | drop per-token rug% fetch (−10 CU) |
| `--skip-portfolio` | off | drop Portfolio V2 fetch (−30 CU) |
| `--skip-first-tx` | off | drop First-Tx funded provenance (−40 CU) |
| `--include-style` | off | also compute wallet style (0 extra CU, reuses fetched data) |
| `--include` | — | comma blocks: `pnl,pnl_90d,pnl_24h,tokens,wallet,portfolio,leaderboard,score` |
| `--format` | `ui` | `ui` · `json` · `telegram` · `plain` · `raw-json` · `compact` |

## CU budget

Worst case ~110 CU: PnL Summary 30 → per-token rug% 10 → FirstTx 40 → Portfolio 30.
Early hard-filter failure costs 30 CU only. Use the `--skip-*` flags to trim.

## Error handling

`[E401]` bad key → `config --apply <KEY>` · `[E403]` tier/route blocked ·
`[E429]` rate-limited, back off · `[E500]` Birdeye upstream, retry.
