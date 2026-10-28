---
name: wallet-score
description: "Score a crypto wallet's alpha and copy-tradeability on Birdeye. Four components — Profitability (P40), Consistency (C25), Quality (Q20), Activity (A15) — with hard filters (tx >= 20, volume >= USD 5k, rug% <= 50%). Use when the user asks to score a wallet, judge wallet or trader quality, copy-trade score, wallet alpha, wallet PnL review, or whether a wallet is worth copying."
argument-hint: "birdeye-cli wallet-score --chain <sol|bsc|base|eth> --wallet <ADDR> [--duration <all|90d|30d|7d|24h>] [--pnl-method <wac|net_cash>] [--include <blocks>] [--format <ui|json|telegram|plain|raw-json|compact>]"
metadata:
  cliHelp: "birdeye-cli wallet-score --help"
  cuWorst: 110
  cuEarlyFail: 30
  components: "profitability(0.40), consistency(0.25), quality(0.20), activity(0.15)"
---

# Wallet Score

Four-component score for a single wallet: **P40 / C25 / Q20 / A15**. Hard filters
(`tx >= 20`, `volume >= USD 5k`, `rug% <= 50%`) short-circuit low-quality wallets
before the full spend.

## Core Capabilities

- Two verdicts in one run: a 0–100 alpha score and a copy-tradeability score
- Four weighted components — Profitability (P40), Consistency (C25), Quality (Q20), Activity (A15)
- Hard filters (tx >= 20, volume >= USD 5k, rug% <= 50%) short-circuit obviously low-quality wallets before the full spend
- First-Tx funding provenance is resolved and cached permanently, so repeat runs cost 0 CU for that block
- PnL method is selectable — weighted-average cost (`wac`) or cashflow difference (`net_cash`)
- Every fetch block can be skipped (`--skip-rug` / `--skip-portfolio` / `--skip-first-tx`) to trim CU
- Runs on `sol` · `bsc` · `base` · `eth`

## Flow

`birdeye-cli wallet-score …` runs these steps against Birdeye. The hard filter runs
right after Step 1, so an obviously thin wallet stops early.

| Step | Endpoint | What it checks / produces | Mode |
|---|---|---|---|
| 1 | `GET /wallet/v2/pnl/summary` | realized + total PnL, ROI, trade count, volume, win-rate over `--duration` — feeds **Profitability** + **Consistency** (30 CU) | always |
| 1b | `GET /wallet/v2/pnl/summary` (24h, 90d) | short-term and 60-day trend windows for **Consistency** (30 CU each) | full mode |
| 1c | — | hard filter: `tx >= 20` · `volume >= USD 5k` → early exit before Step 2 if it fails | always |
| 2 | `POST /wallet/v2/pnl/details` | per-token PnL, profit concentration and deep-loss / rug proxy — feeds **Quality** (30 CU; `--skip-rug` trims) | unless `--skip-rug` |
| 3 | `POST /wallet/v2/tx/first-funded` | wallet age / funding provenance — feeds **Activity** (~40 CU; permanent cache → 0 CU) | unless `--skip-first-tx` |
| 4 | `GET /wallet/v2/current-net-worth` | current portfolio holdings — feeds **Activity** (30 CU) | unless `--skip-portfolio` |
| 5 | — | compose: P40 + C25 + Q20 + A15 → alpha score + tier, then the 5-factor copy-tradeability score | always |

Early fail after Step 1 costs **30 CU**; the full pipeline is worst-case **~110 CU**.

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → a key is resolvable, proceed.
- exit `1` → no key. Ask the user for their Birdeye API key, then run
  `birdeye-cli config --apply <KEY>` (writes `~/.config/birdeye/.env`, chmod 600).

Key order: `$BIRDEYE_API_KEY` → `~/.config/birdeye/.env` → `~/.birdeye.env` → `./.env`.
Fallback CLI: `python3 birdeye_cli.py wallet-score ...` (see the repo `README.md` for install).

## Usage

```bash
birdeye-cli wallet-score --chain sol --wallet <ADDR> --duration 30d --format plain
birdeye-cli wallet-score --chain sol --wallet <ADDR> --include pnl,tokens,score --format compact
birdeye-cli wallet-score --chain sol --wallet <ADDR> --duration 30d --skip-portfolio --skip-first-tx --format json
```

## Arguments

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` |
| `--wallet` | — | **required**, wallet address |
| `--duration` | `30d` | `all` · `90d` · `30d` · `7d` · `24h` |
| `--pnl-method` | `wac` | `wac` (weighted avg cost) · `net_cash` (cashflow diff) |
| `--skip-rug` | off | drop per-token rug% fetch (−~10 CU); rug_fraction forced to 0 |
| `--skip-portfolio` | off | drop the current-net-worth fetch (−30 CU) |
| `--skip-first-tx` | off | drop first-funded provenance (−40 CU; reuses permanent cache when present) |
| `--include-style` | off | also compute wallet style (0 extra CU, reuses fetched data) |
| `--include` | — | comma blocks: `pnl,pnl_90d,pnl_24h,tokens,wallet,portfolio,leaderboard,score` |
| `--format` | `plain` on the CLI | `ui` · `json` · `telegram` · `plain` · `raw-json` · `compact` |

## Cost

| Run | CU |
|---|---|
| Early hard-filter fail (tx < 20 or volume < USD 5k) | **30** |
| Full pipeline (worst case) | **~110** |
| `--skip-*` flags | trim the matching step to 0 |
| First-funded re-run (cache hit) | step 3 = 0 |
| `--include-style` | +0 |
| Replay from history / cache | 0 |

## Output

- `plain`: terminal scorecard — alpha score, tier, the four component scores, copy-trade tier
- `compact`: a trimmed `blocks` object (`--include` picks which blocks)
- `json` / `raw-json`: the full result envelope including the `copy_formula` breakdown
- `telegram`: compact score summary
- `ui`: arc gauge + component cards + copy-tradeability card (console)

Read it in this order:

1. **Alpha score + tier** — `0..100` and the tier (LEGENDARY / ELITE / PRO / ADVANCED / NOVICE / RISK).
2. **Four components** — Profitability · Consistency · Quality · Activity, each `0..100`.
3. **Copy-tradeability score + tier** — whether the trades can realistically be followed; `copy_formula` in `json` shows every factor.
4. **Skips** — any `--skip-*` block reports `0` CU and is marked as skipped.
5. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

Early-exit runs return the filter that failed instead of a score.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | re-run `config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
