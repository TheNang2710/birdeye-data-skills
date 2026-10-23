---
name: kline-pattern
description: "Classify a candlestick (kline) pattern from Birdeye OHLCV and emit a 0..100 pattern score. Use when the user asks about candlestick patterns, chart pattern, doji/engulfing/hammer, technical setup, kline analysis, or candle structure for a token."
argument-hint: "kline-pattern --chain <sol|bsc|base|eth> --address <MINT> [--resolution <1m|5m|15m|30m|1h|4h|1d>] [--window <7d|3d|1d>] [--format <ui|json|telegram|plain|raw-json>]"
metadata:
  cliHelp: "birdeye-cli kline-pattern --help"
  cuMin: 25
  cuMax: 100
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

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → proceed. exit `1` → `birdeye-cli config --apply <KEY>`
  (writes `~/.config/birdeye/.env`, chmod 600).

Fallback CLI: `python3 birdeye_cli.py kline-pattern ...`.

## Usage

```bash
birdeye-cli kline-pattern --chain sol --address <MINT> --resolution 15m --window 7d --format plain
```

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` |
| `--address` | — | **required**, token contract |
| `--resolution` | `15m` | `1m` · `5m` · `15m` · `30m` · `1h` · `4h` · `1d` |
| `--window` | `7d` | lookback e.g. `7d` · `3d` · `1d`; needs >= 8 candles |
| `--format` | `ui` | `ui` · `json` · `telegram` · `plain` · `raw-json` |

## Output

`json` / `plain` are clean of HTML for bot integration; every response carries a `⚡CU` footer.

## Error handling

`[E401]` bad key → `config --apply <KEY>` · `[E403]` tier/route blocked ·
`[E429]` rate-limited, back off · `[E500]` Birdeye upstream, retry.
