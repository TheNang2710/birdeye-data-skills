# `kline-pattern` — Public Workflow

Classify a token's candlestick price action into one of **11 named patterns** and emit a
**0–100 pattern score**. One OHLCV call does the whole job.

## High-Level Concept

The skill reads the candle series for the chosen resolution and window, computes six
measurements at the current bar, and maps them to a named pattern plus a score. It needs at
least **8 candles** in the window. CU scales with the candle count.

## At a Glance

| Step | Endpoint | What it checks / produces | Mode | CU |
|---|---|---|---:|---:|
| 1 | `GET /defi/v3/ohlcv` | the candle series for `--resolution` over `--window` | always | 25–100 |
| 2 | — | needs ≥ 8 candles; classify the pattern at the current bar from 6 measurements → `0..100` score | always | 0 |
| 3 | — | render: pattern label, measurement cards, matched evidence, score deltas from the base 50 | always | 0 |

One API call only — **25–100 CU** depending on how many candles the window returns.

## Step by Step

### Step 1 — OHLCV
`/defi/v3/ohlcv` returns open / high / low / close / volume candles for the resolution
(`1m` … `1d`) over the window. Nothing else is fetched — no holder, security or liquidity
call is needed.

### Step 2 — Classify
Six measurements at the current bar:

| Measurement | Meaning |
|---|---|
| `trend` | recent closes vs older closes — up / down / flat |
| `slope` | recent vs older level — positive = rising |
| `volatility` | mean (high − low) / close over recent candles |
| `drawdown` | (all-time-high − current) / all-time-high |
| `vol_ratio` | last volume vs the trailing average |
| `up_from_low` | (current − all-time-low) / all-time-low |

These map to one of 11 patterns (Strong Uptrend / Uptrend Channel / Breakout / Sideways
Consolidation / Strong Downtrend / Downtrend Channel / Breakdown / Bottoming Out / Topping
Out / High Volatility / Low Volatility) and a base score that the matched conditions adjust.

### Step 3 — Render
Shows the pattern label with a colour-coded score, the six measurement cards, the list of
matched evidence and how the base score (50) was adjusted.

## Scoring (high level)

The pattern starts from a neutral base of **50** and each matched condition moves it up or
down — e.g. a clear uptrend with a shallow drawdown scores high, a breakdown scores low. The
`evidence` list and the `score deltas` make every move traceable. A window with fewer than 8
candles cannot be classified.

## Output

- `plain`: pattern label + score + the six measurements, clean of HTML for bot integration.
- `json` / `raw-json`: the full envelope — pattern, score, measurements, evidence, deltas.
- `telegram`: compact pattern summary.
- `ui`: pattern label + colour-coded score + measurement cards.

Read it in this order:

1. **Pattern label + score** — e.g. `Uptrend Channel` with a `0..100` score.
2. **Six measurements** — `trend` · `slope` · `volatility` · `drawdown` · `vol_ratio` ·
   `up_from_low`.
3. **Evidence** — the conditions that matched, and the score deltas from the base 50.
4. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

## Cost

| Candles returned | CU |
|---|---:|
| 0–100 | **25** |
| 101–300 | 30 |
| 301–1000 | 40 |
| 1001–2000 | 75 |
| 2001–5000 | 100 |

Replay from history / cache = 0 CU.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | `birdeye-cli config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |

A window with fewer than 8 candles is rejected rather than returning a guess.
