---
name: junk-predict
description: "Junk-token predictor — scores token addresses 0..100 for junk likelihood from market cap, liquidity, volume, trades, traders and top-holder concentration. Three fixed models are available — unsupervised (LR16), function (tuned heuristic) and supervised (GBM). Use when the user asks whether a token is junk / a scam / low quality, junk-score a token or a batch of tokens, filter dust tokens, or screen tokens by quality."
argument-hint: "birdeye-cli junk-predict --chain <sol|bsc|base|eth> --tokens <ADDR1,ADDR2,...> [--model <unsupervised|function|supervised>] [--no-holding] [--format <ui|json|telegram|plain|raw-json>]"
metadata:
  cliHelp: "birdeye-cli junk-predict --help"
  cuPerToken: 51
  cuPerTokenNoHolding: 21
  endpoint: "/defi/token_overview"
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
- `junk-quick-test` spot-checks the model on random list tokens with **no per-token overview call** — very cheap for bulk sampling
- Runs at ~21 CU/token, so screening a whole list stays cheap
- Runs on `sol` · `bsc` · `base` · `eth`

## Flow

`birdeye-cli junk-predict …` runs these steps against Birdeye, once per token in `--tokens`.

| Step | Endpoint | What it checks / produces | Mode |
|---|---|---|---|
| 1 | `GET /defi/token_overview` | market cap, liquidity, 24h volume, trades, traders — the core quality signals (21 CU) | per token |
| 2 | `GET /holder/v1/distribution` (top 20) | top-holder concentration — the holding term of the score (30 CU) | per token, unless `--no-holding` |
| 3 | — | run the selected model (`unsupervised` / `function` / `supervised`) → per-token `junk_score` `0..100` + `is_junk` | per token |
| 4 | — | a continuous holding-share adjustment is layered on the model output (dropped to 0 with `--no-holding`) | per token |

`junk-quick-test` differs: it samples up to 5000 tokens from the **v3 token list in one call**
and runs the model on list data — no per-token overview call.

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → a key is resolvable, proceed.
- exit `1` → no key. Ask the user for their Birdeye API key, then run
  `birdeye-cli config --apply <KEY>` (writes `~/.config/birdeye/.env`, chmod 600).

Key order: `$BIRDEYE_API_KEY` → `~/.config/birdeye/.env` → `~/.birdeye.env` → `./.env`.
Fallback CLI: `python3 birdeye_cli.py junk-predict ...` (see the repo `README.md` for install).

## Usage

```bash
birdeye-cli junk-predict --chain sol --tokens <MINT1>,<MINT2> --model unsupervised --format plain
birdeye-cli junk-predict --chain sol --tokens <MINT> --no-holding --format json
birdeye-cli junk-quick-test --chain sol --num 30 --format json
```

## Arguments

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` |
| `--tokens` | — | **required**, comma / newline-separated addresses |
| `--model` | `unsupervised` | `unsupervised` (LR16) · `function` (tuned heuristic) · `supervised` (GBM) |
| `--no-holding` | off | skip holder distribution (−30 CU/token); the concentration term → 0 |
| `--score-b64` | — | 0-CU re-score from a prior run envelope / results (base64) |
| `--format` | `plain` on the CLI | `ui` · `json` · `telegram` · `plain` · `raw-json` |

`junk-quick-test` takes `--num <n>` and scores N random tokens sampled from the v3 token list
in a single call — useful to spot-check the model, not to score specific addresses.

## Cost

| Run | CU |
|---|---|
| `junk-predict` with holding | **~51 × tokens** |
| `junk-predict --no-holding` | **~21 × tokens** |
| `junk-predict --score-b64` (re-score) | **0** |
| `junk-quick-test --num N` | one list call, then model runs locally |

Scale `--tokens` count × ~51 CU. Use `--no-holding` to roughly halve the cost when concentration
is not needed.

## Output

- `plain`: one row per token — address, `junk_score`, `is_junk`, key inputs
- `json` / `raw-json`: the full result envelope — per-token rows plus the model name and inputs
- `telegram`: compact per-token verdicts
- `ui`: per-token junk score with a colour-coded verdict (console)

Read it in this order:

1. **`junk_score`** — `0..100` per token; higher = more junk-likely.
2. **`is_junk`** — the boolean verdict at the model threshold.
3. **Inputs** — the market cap / liquidity / volume / trades / traders (and concentration, unless `--no-holding`) behind the score.
4. **Model** — which of the three models produced the verdict.
5. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | re-run `config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
| `invalid --score-b64 payload` | malformed re-score envelope | re-export the base64 from a prior run |
