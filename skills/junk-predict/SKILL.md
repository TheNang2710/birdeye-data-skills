---
name: junk-predict
description: "Junk-token predictor — scores token addresses 0..100 for junk likelihood from market cap, liquidity, volume, trades, traders and top-holder concentration. Three fixed models are available — unsupervised (LR16), function (tuned heuristic) and supervised (GBM). Use when the user asks whether a token is junk / a scam / low quality, junk-score a token or a batch of tokens, filter dust tokens, or screen tokens by quality."
argument-hint: "junk-predict --chain <sol|bsc|base|eth> --tokens <ADDR1,ADDR2,...> [--model <unsupervised|function|supervised>] [--no-holding] [--format <ui|json|telegram|plain|raw-json>]"
metadata:
  cliHelp: "birdeye-cli junk-predict --help"
  cuPerToken: 51
  cuPerTokenNoHolding: 21
---

# Junk Token Prediction

Per-token classifier producing a 0..100 junk score. Fetches `/defi/token_overview`
(21 CU) + `/holder/v1/distribution` (30 CU) per token → **~51 CU/token** (21 CU with
`--no-holding`). Model parameters are fixed.

## Core Capabilities

- Batch-scores many tokens in one run and returns a per-token verdict, not a single blended number
- Three selectable models — `unsupervised` (LR16), `function` (tuned heuristic) and `supervised` (GBM) — so an explainable rule-based verdict can be compared against the learned ones
- Inputs are cheap quality signals only: market cap, liquidity, volume, trades, traders and top-holder concentration
- Holder distribution is opt-in (+30 CU/token) and only fetched when the concentration input is wanted
- Runs at ~21 CU/token, so screening a whole list stays cheap

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → proceed. exit `1` → `birdeye-cli config --apply <KEY>`
  (writes `~/.config/birdeye/.env`, chmod 600).

Fallback CLI: `python3 birdeye_cli.py junk-predict ...`.

## Usage

```bash
birdeye-cli junk-predict --chain sol --tokens <MINT1>,<MINT2> --model unsupervised --format plain
birdeye-cli junk-predict --chain sol --tokens <MINT> --no-holding --format json
birdeye-cli junk-quick-test --chain sol --num 30 --format json
```

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` |
| `--tokens` | — | **required**, comma/newline-separated addresses |
| `--model` | `unsupervised` | `unsupervised` (LR16) · `function` (tuned heuristic) · `supervised` (GBM) |
| `--no-holding` | off | skip holder distribution (−30 CU/token); concentration term → 0 |
| `--score-b64` | — | 0-CU re-score from a prior run envelope / results (base64) |
| `--format` | `ui` | `ui` · `json` · `telegram` · `plain` · `raw-json` |

`junk-quick-test` scores N random tokens sampled from the v3 token list in a single call
(useful for a spot-check of the model, not for specific addresses).

## CU budget

Scale `--tokens` count × ~51 CU. Use `--no-holding` to halve the cost when concentration
is not needed.

## Error handling

`[E401]` bad key → `config --apply <KEY>` · `[E403]` tier/route blocked ·
`[E429]` rate-limited, back off · `[E500]` Birdeye upstream, retry.
