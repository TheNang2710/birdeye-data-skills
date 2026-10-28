---
name: kline-pattern
description: "Classify a candlestick (kline) pattern from Birdeye OHLCV and emit a 0..100 pattern score. Use when the user asks about candlestick patterns, chart pattern, doji/engulfing/hammer, technical setup, kline analysis, or candle structure for a token."
argument-hint: "birdeye-cli kline-pattern --chain <sol|bsc|base|eth> --address <MINT> [--resolution <1m|5m|15m|30m|1h|4h|1d>] [--window <7d|3d|1d>] [--format <ui|json|telegram|plain|raw-json>]"
metadata:
  cliHelp: "birdeye-cli kline-pattern --help"
  cuMin: 25
  cuMax: 100
  endpoint: "/defi/v3/ohlcv"
---

# Kline Pattern

One OHLCV call → candlestick pattern classification plus a 0..100 score.
CU scales with the candle count (25–100).

## Core Capabilities

- One OHLCV call does the whole job — no holder, security or liquidity calls needed
- Classifies the candlestick pattern at the current bar from the chosen resolution
- Returns a 0–100 pattern score rather than a plain pattern name
- Resolution is selectable from `1m` to `1d` so scalping and swing candles are both covered
- Needs at least 8 candles in the window; CU scales with candle count (25–100)
- Runs on `sol` · `bsc` · `base` · `eth`

## Flow

`birdeye-cli kline-pattern …` runs these steps against Birdeye.

| Step | Endpoint | What it checks / produces | Mode |
|---|---|---|---|
| 1 | `GET /defi/v3/ohlcv` | the candle series for `--resolution` over `--window` (25–100 CU by candle count) | always |
| 2 | — | needs ≥ 8 candles; classify the pattern at the current bar from 6 measurements (trend, slope, volatility, drawdown, vol_ratio, up_from_low) → 0..100 score | always |
| 3 | — | render: pattern label, measurement cards, matched evidence and the score deltas from the base 50 | always |

One API call only — **25–100 CU** depending on how many candles the window returns.

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → a key is resolvable, proceed.
- exit `1` → no key. Ask the user for their Birdeye API key, then run
  `birdeye-cli config --apply <KEY>` (writes `~/.config/birdeye/.env`, chmod 600).

Key order: `$BIRDEYE_API_KEY` → `~/.config/birdeye/.env` → `~/.birdeye.env` → `./.env`.
Fallback CLI: `python3 birdeye_cli.py kline-pattern ...` (see the repo `README.md` for install).

## Usage

```bash
birdeye-cli kline-pattern --chain sol --address <MINT> --resolution 15m --window 7d --format plain
birdeye-cli kline-pattern --chain sol --address <MINT> --resolution 1h --window 30d --format json
```

## Arguments

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` |
| `--address` | — | **required**, token contract |
| `--resolution` | `15m` | `1m` · `5m` · `15m` · `30m` · `1h` · `4h` · `1d` |
| `--window` | `7d` | lookback e.g. `7d` · `3d` · `1d`; needs >= 8 candles |
| `--format` | `plain` on the CLI | `ui` · `json` · `telegram` · `plain` · `raw-json` |

## Cost

| Candles returned | CU |
|---|---|
| 0–100 | **25** |
| 101–300 | 30 |
| 301–1000 | 40 |
| 1001–2000 | 75 |
| 2001–5000 | 100 |

Replay from history / cache = 0 CU.

## Output

- `plain`: pattern label + score + the six measurements, clean of HTML for bot integration
- `json` / `raw-json`: the full result envelope (pattern, score, measurements, evidence, deltas)
- `telegram`: compact pattern summary
- `ui`: pattern label + colour-coded score + measurement cards (console)

Read it in this order:

1. **Pattern label + score** — e.g. `Uptrend Channel` with a `0..100` score.
2. **Six measurements** — `trend` · `slope` · `volatility` · `drawdown` · `vol_ratio` · `up_from_low`.
3. **Evidence** — the conditions that matched; **score deltas** show how the base 50 moved.
4. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

`⚠` a window with fewer than 8 candles cannot be classified.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | re-run `config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
