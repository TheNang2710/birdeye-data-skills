---
name: token-trending-score
description: "Compute a 0..100 momentum / trending score for a token per interval from OHLCV + liquidity + holders + security. Supports `classic` (original 6-component momentum model) and `hybrid` (classic blended with wallets/volume/pace interval formula). Use when the user asks how hot or how trending a token is, momentum score, whether it is pumping, trend strength, or multi-interval momentum for one token."
argument-hint: "token-trending-score --chain <sol|bsc|base|eth> --address <MINT> [--model <classic|hybrid>] [--candles <n>] [--nocache] [--format <ui|json|telegram|plain|raw-json>]"
metadata:
  cliHelp: "birdeye-cli token-trending-score --help"
  cuTypical: 176
  intervals: "5m, 15m, 30m, 1h, 4h"
---

# Token Trending Score

0..100 momentum score per interval, blended from OHLCV (100 CU) + liquidity (20 CU) +
live liquidity snapshot (5 CU, Solana) + overview (21 CU) + security (30 CU) → typical **~176 CU**.

Models:

- `classic` — original 6-component momentum score
- `hybrid` — `classic` plus wallets / volume / pace interval attention on 1h / 4h / 24h

## Core Capabilities

- Momentum decides trending — volume and price carry 55% of the weight; security and liquidity are 10% each
- Security and liquidity also act as continuous gates, not hard cliffs: a low value scales the score down smoothly so junk is filtered while momentum still ranks
- Liquidity gate uses effective depth — `min(liquidity, exit liquidity)` where reported — with a heavy-penalty band at or below USD 4k; exit liquidity is used on Solana
- Liquidity depth is read from the **live snapshot** (`token_overview` + `POST /defi/v3/liquidity/latest/token`), not a stale OHLC close; the OHLC series only supplies trend/stability, and a fallback is labelled with its `ohlc_age_seconds`
- A confirmed honeypot is the only hard stop (near-zero gate)
- Reports a score-independent `liquidity_health` badge — `DYING` (liquidity down 80–99%) or a red `DEAD` (≥99% down, or either pool below USD 10) — even when the trending score is still high
- Two models: `classic` (OHLCV-only, works on any token) and `hybrid` (adds the wallets / volume / pace native formula on 1h / 4h / 24h)
- Scores 8 intervals — 5m · 15m · 30m · 1h · 4h · 6h · 12h · 24h — so short pumps and sustained trends are separated
- Raises `⚠ pipeline_gap` when required upstream data is missing instead of silently degrading

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → proceed. exit `1` → `birdeye-cli config --apply <KEY>`
  (writes `~/.config/birdeye/.env`, chmod 600).

Fallback CLI: `python3 birdeye_cli.py token-trending-score ...`.

## Usage

```bash
birdeye-cli token-trending-score --chain sol --address <MINT> --format plain
birdeye-cli token-trending-score --chain sol --address <MINT> --model hybrid --format json
birdeye-cli token-trending-score --chain sol --address <MINT> --candles 2000 --nocache --format json
```

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` |
| `--address` | — | **required**, token contract |
| `--model` | `classic` | `classic` · `hybrid` |
| `--candles` | `5000` | 1m candles (5000 = 100 CU, ~83h) |
| `--nocache` | off | bypass the 24h CSV cache and refetch |
| `--format` | `ui` | `ui` · `json` · `telegram` · `plain` · `raw-json` |

## Output

Per-interval momentum plus an overall score.

- `classic` scores all internal intervals with the original model
- `hybrid` blends in wallets / volume / pace attention on overview-supported intervals

Clean `json` / `plain` for bots; `⚡CU` footer on every response.

## Error handling

`[E401]` bad key → `config --apply <KEY>` · `[E403]` tier/route blocked ·
`[E429]` rate-limited, back off · `[E500]` Birdeye upstream, retry.
