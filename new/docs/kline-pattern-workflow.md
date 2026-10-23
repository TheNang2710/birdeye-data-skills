# Workflow: Kline Pattern (Skill #21)

## What it does
Classifies a token's candlestick price action into one of 11 named patterns (e.g. "📈 Uptrend Channel", "💥 Breakdown") and assigns a 0–100 score. Uses 6 measurements: trend, slope, volatility, drawdown, volume ratio, and recovery from low.

## When to use
- You want a quick read on a token's price action direction.
- You're checking if a token is trending, consolidating, or reversing.
- As the price-action pillar in Contract DD (Skill #5).

## Inputs
- **Token address**
- **Chain** (sol / bsc / base / eth)
- **Resolution**: 1m / 5m / 15m / 30m / 1h / 4h / 1d
- **Window**: e.g. 1d, 7d, 30d, 1y

## Step-by-step

### 1. Open Kline Pattern
Go to **📈 History & Charts → Skill #21 · Kline Pattern**.

### 2. Enter the token
- Paste the token contract address.
- Choose **Chain**, **Resolution** (e.g. 1h), and **Window** (e.g. 7d).

### 3. Run
Click **Run**.

### 4. Read the output
- **Pattern label**: e.g. "📈 Uptrend Channel" with a color-coded score (0–100).
- **6 measurement cards**: trend, slope, volatility, drawdown, vol_ratio, up_from_low. **Hover each card** to see what the number means.
- **Evidence**: list of conditions that matched.
- **Score deltas**: how the base score (50) was adjusted.

### 5. Save & reuse
- Auto-saved to **History**. Replay for 0 CU.
- Copy buttons for address and CLI command.

## Pattern Quick Reference

| Pattern | Score Bias | Meaning |
|---------|-----------|---------|
| Strong Uptrend | +35 | Clear uptrend, shallow drawdown |
| Uptrend Channel | +10 | Moderate uptrend |
| Breakout | +25 | Flat→up with volume spike |
| Strong Downtrend | −35 | Clear downtrend, deep drawdown |
| Downtrend Channel | −10 | Moderate downtrend |
| Breakdown | −25 | Flat→down with volume spike |
| Bottoming Out | +20 | At lows, volume picking up |
| Topping Out | −20 | At highs, volume picking up |
| High Volatility | −15 | Wide price swings |
| Low Volatility | +5 | Calm, tight range |
| Sideways Consolidation | ±0 | No clear direction |

## How to read the 6 measurements
| Metric | Hover explanation |
|--------|-------------------|
| **trend** | mean(last 9 closes) vs mean(last 21 closes). up/down/flat |
| **slope** | (recent 5 − older 5) / older 5. Positive = rising |
| **volatility** | mean of (high−low)/close over last 14 candles |
| **drawdown** | (ATH − current) / ATH. 0 = at highs |
| **vol_ratio** | last volume / mean(prev 21). >1 = above average |
| **up_from_low** | (current − ATL) / ATL. 0 = at lows |

## CU cost
CU scales with candle count returned by OHLCV:
- 0–100 candles → 25 CU
- 101–300 → 30 CU
- 301–1000 → 40 CU
- 1001–2000 → 75 CU
- 2001–5000 → 100 CU

**Replay from history**: 0 CU
