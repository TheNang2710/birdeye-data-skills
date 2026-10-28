# `junk-predict` — Public Workflow

Per-token classifier producing a **0–100 junk score** from cheap quality signals, plus a
boolean `is_junk` verdict. Three fixed models are available so an explainable rule-based
verdict can be compared against the learned ones.

## High-Level Concept

Junk / dust / scam tokens are usually identifiable from a handful of cheap fields: very high
market cap with almost no traded volume, near-zero liquidity, very few traders relative to
trades, and top-holder concentration. The skill fetches those fields per token, runs one of
three fixed models, and returns a per-token score — not a single blended number — so a whole
list can be filtered in one run.

- Three models: `unsupervised` (LR16) · `function` (tuned heuristic) · `supervised` (GBM).
- Holder distribution is **opt-in** (+30 CU/token) and only fetched when the concentration
  input is wanted.
- `junk-quick-test` spot-checks the model on random list tokens with **no per-token overview
  call** — the cheap way to sanity-check the model.
- `--score-b64` re-scores a previous run at **0 CU**.

## At a Glance

| Step | Endpoint | What it checks / produces | Mode | CU |
|---|---|---|---:|---:|
| 1 | `GET /defi/token_overview` | market cap, liquidity, 24h volume, trades, traders — the core quality signals | per token | 21 |
| 2 | `GET /holder/v1/distribution` (top 20) | top-holder concentration — the holding term | per token, unless `--no-holding` | 30 |
| 3 | — | run the selected model → `junk_score` `0..100` + `is_junk` | per token | 0 |
| 4 | — | a continuous holding-share adjustment layered on the model output (dropped to 0 with `--no-holding`) | per token | 0 |

`junk-predict` = `/defi/token_overview` (21 CU) + `/holder/v1/distribution` (30 CU) per token
→ **~51 CU/token** (21 CU with `--no-holding`).

## Step by Step

### Step 1 — Token overview
`/defi/token_overview` supplies the model inputs: market cap, liquidity, 24h volume, trade
count and unique-trader count. These are the cheap signals that separate a real token from a
dust / spam token.

### Step 2 — Holder distribution (opt-in)
`/holder/v1/distribution` (top 20) adds top-holder concentration, which is a strong junk
signal. `--no-holding` skips it (−30 CU/token) and the concentration term is treated as 0.

### Step 3 — Model
The selected model (`unsupervised` / `function` / `supervised`) maps the inputs to a
`junk_score` between 0 and 100 and an `is_junk` verdict at the model threshold. Model
parameters are fixed — the CLI does not tune them.

### Step 4 — Holding adjustment
A continuous holding-share term is layered on the model output (no cliff), then dropped when
`--no-holding` was used.

### `junk-quick-test`
Samples up to **5000 tokens from the v3 token list in one call** and runs the model on the
list data — **no per-token overview call** — so it is very cheap for bulk spot-checks. Use it
to gauge the model, not to score specific addresses.

## Scoring (high level)

Inputs: market cap · liquidity · 24h volume · trades · traders · top-holder concentration.

| Model | Type | Character |
|---|---|---|
| `unsupervised` | LR16 | learned structure without labels |
| `function` | tuned heuristic | fully explainable rule-based verdict |
| `supervised` | GBM | strongest learned separation |

Output per token: `junk_score` (higher = more junk-likely) and `is_junk` (the boolean at the
model threshold). A re-score from `--score-b64` returns the same shape at 0 CU.

## Output

- `plain`: one row per token — address, `junk_score`, `is_junk`, key inputs.
- `json` / `raw-json`: the full envelope — per-token rows plus the model name and inputs.
- `telegram`: compact per-token verdicts.
- `ui`: per-token junk score with a colour-coded verdict.

Read it in this order:

1. **`junk_score`** — `0..100` per token; higher = more junk-likely.
2. **`is_junk`** — the boolean verdict at the model threshold.
3. **Inputs** — market cap / liquidity / volume / trades / traders (and concentration unless
   `--no-holding`).
4. **Model** — which of the three models produced the verdict.
5. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

## Cost

| Run | CU |
|---|---:|
| `junk-predict` with holding | **~51 × tokens** |
| `junk-predict --no-holding` | **~21 × tokens** |
| `junk-predict --score-b64` (re-score) | **0** |
| `junk-quick-test --num N` | one list call, then model runs locally |

Scale `--tokens` count × ~51 CU; use `--no-holding` to roughly halve the cost.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | `birdeye-cli config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
| `invalid --score-b64 payload` | malformed re-score envelope | re-export the base64 from a prior run |
