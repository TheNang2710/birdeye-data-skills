# Skill #21 · Kline Pattern

## High-Level Concept

Classifies a token's recent candlestick price action into one of **11 named patterns** and assigns a **0–100 score** indicating the strength/direction of the pattern. A single OHLCV call feeds six numeric measurements; a rule-based classifier picks the first matching pattern and computes deltas to a base score of 50.

## Inputs

| Field | Type | Description |
|-------|------|-------------|
| `chain` | enum | sol / bsc / base / eth / arc / robinhood |
| `address` | string | Token contract address |
| `resolution` | enum | 1m / 5m / 15m / 30m / 1h / 4h / 1d |
| `window` | string | e.g. `1d`, `7d`, `30d`, `1y` |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| OHLCV candles | `/defi/v3/ohlcv` | **tiered by candle count** (see below) |

### OHLCV v3 CU Tiers
CU scales with the number of candles returned:

| Candles | CU |
|---------|----|
| 0–100 | 25 |
| 101–300 | 30 |
| 301–1000 | 40 |
| 1001–2000 | 75 |
| 2001–5000 | 100 |

## The 6 Measurements

Each measurement card in the UI has a hover tooltip explaining its meaning.

### 1. `trend_up` (categorical: up / flat / down)
```
m9  = mean(last 9 closes)
m21 = mean(last 21 closes)   (or all closes if n < 21)
ratio = m9 / m21
  ratio > 1.003 → "up"
  ratio < 0.997 → "down"
  else          → "flat"
```
*Meaning: short-term (9-candle) price vs medium-term (21-candle) average.*

### 2. `slope` (float, momentum)
```
if n >= 24:
  recent = mean(closes[-5:])
  older  = mean(closes[-24:-19])
  slope  = (recent - older) / older
else:
  slope = (closes[-1] - closes[0]) / closes[0]
```
*Meaning: price momentum over ~19 candles. Positive = rising, negative = falling.*

### 3. `volatility` (float)
```
body = last 14 candles
vol_pcts[i] = (high[i] - low[i]) / close[i]
volatility = mean(vol_pcts)
```
*Meaning: average intraday range as % of close. Higher = wider swings (riskier).*

### 4. `drawdown` (float, 0..1)
```
max_h = max(all highs)
drawdown = (max_h - close[-1]) / max_h
```
*Meaning: how far current price is below the period high. 0 = at highs; 0.5 = 50% below peak.*

### 5. `vol_ratio` (float)
```
if n >= 22:
  mean_prev = mean(vols[-21:-1])
  vol_ratio = vols[-1] / mean_prev
else:
  vol_ratio = 1.0
```
*Meaning: last-candle volume vs average of previous 21. >1 = above-average volume (confirms move); <1 = drying up.*

### 6. `up_from_low` (float, 0..∞)
```
min_l = min(all lows)
up_from_low = (close[-1] - min_l) / min_l
```
*Meaning: recovery from the period low. 0 = at lows; higher = more recovery off the bottom.*

## Pattern Classification (first-match-wins)

Base score = **50**. Each pattern applies deltas (±points). The first matching pattern in this order wins:

| # | Pattern | Condition | Score Delta |
|---|---------|-----------|-------------|
| 1 | `strong_uptrend` | trend=up AND slope>0.03 AND drawdown<0.1 | +35 |
| 2 | `uptrend_channel` | trend=up AND slope>0.01 | +10 |
| 3 | `breakout` | trend=flat→up AND vol_ratio>1.5 AND slope>0.02 | +25 |
| 4 | `strong_downtrend` | trend=down AND slope<-0.03 AND drawdown>0.3 | -35 |
| 5 | `downtrend_channel` | trend=down AND slope<-0.01 | -10 |
| 6 | `breakdown` | trend=flat→down AND vol_ratio>1.5 AND slope<-0.02 | -25 |
| 7 | `bottoming_out` | drawdown>0.3 AND up_from_low<0.1 AND vol_ratio>1.3 | +20 |
| 8 | `topping_out` | drawdown<0.1 AND up_from_low>1.0 AND vol_ratio>1.3 | -20 |
| 9 | `high_volatility` | volatility>0.08 | -15 |
| 10 | `low_volatility` | volatility<0.02 | +5 |
| 11 | `sideways_consolidation` | (fallback, always matches) | ±0 |

Final score is clamped to `[0, 100]`.

## Output Fields

```json
{
  "pattern": "uptrend_channel",
  "label": "📈 Uptrend Channel",
  "score": 60.0,
  "color": "#22c55e",
  "measurements": {
    "trend_up": "up", "slope": 0.0123, "volatility": 0.034,
    "drawdown": 0.05, "vol_ratio": 1.8, "up_from_low": 0.42,
    "n_candles": 168
  },
  "evidence": ["trend_up=up", "slope=0.0123 > 0.01"],
  "deltas": ["+10 uptrend_channel"]
}
```

## CLI

```bash
python3 birdeye_cli.py kline-pattern \
  --chain sol --address <TOKEN_ADDR> \
  --resolution 1h --window 7d \
  --format rendered
```
