# Skill #5 · Contract DD

## High-Level Concept

A composite **0–100 safety score** for a token contract, built from three weighted pillars:

| Pillar | Weight | What it measures |
|--------|--------|------------------|
| **Safety** | 45% | Mint/freeze authority, LP lock, buy/sell taxes, honeypot |
| **Holders** | 30% | Top-10 concentration, holder count, LP holder % |
| **Price** | 25% | Kline pattern score (trend, drawdown, volatility) |

Each pillar starts at 100 and is reduced by penalties. The composite is the weighted sum, mapped to a tier.

## Inputs

| Field | Type | Description |
|-------|------|-------------|
| `chain` | enum | sol / bsc / base / eth / arc / robinhood |
| `address` | string | Token contract address |
| `--skip-kline` | flag | Skip the price-action pillar (saves ~25–100 CU) |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| Token overview + money flow | `/defi/v3/token/overview` + `money_flow` | ~21 |
| Security | `/defi/v3/token/security` | 30 |
| Holder distribution | `/holder/v1/distribution` | 30 |
| Kline (price action) | `/defi/v3/ohlcv` | **25–100** (tiered by candle count) |

**Total: ~86–161 CU** (varies by kline candle count).

## Pillar 1 — Safety (45%)

Start at 100, subtract penalties:

| Check | Penalty | Condition |
|-------|---------|-----------|
| Mint authority active | −25 | `mintAuthority` not renounced |
| Freeze authority active | −20 | `freezeAuthority` not disabled |
| LP unlocked (<50%) | −25 | LP locked < 50% |
| LP partially locked (50–80%) | −10 | LP locked 50–80% |
| LP lock unknown | −5 | No LP data |
| High buy tax (>10%) | −15 | buy tax > 10% |
| Buy tax (5–10%) | −5 | buy tax 5–10% |
| High sell tax (>10%) | −15 | sell tax > 10% |
| Sell tax (5–10%) | −5 | sell tax 5–10% |
| Honeypot | −50 | `isHoneypot == true` |

Clamped to `[0, 100]`.

## Pillar 2 — Holders (30%)

Start at 100, subtract penalties based on holder concentration:

| Check | Penalty | Condition |
|-------|---------|-----------|
| Top-10 > 80% | −30 | top 10 holders own > 80% |
| Top-10 > 60% | −15 | top 10 holders own 60–80% |
| Top-10 > 40% | −5 | top 10 holders own 40–60% |
| Holder count < 100 | −20 | fewer than 100 holders |
| Holder count < 1000 | −10 | 100–1000 holders |
| No holder data | −10 | holder API failed |

Clamped to `[0, 100]`.

## Pillar 3 — Price (25%)

Uses the Kline Pattern module (Skill #21) to score price action. If kline data is unavailable, a flat −5 penalty is applied and the score starts at 50.

The price score = `kline_result["score"]` (0–100), or 50 − 5 = 45 if no kline data.

## Composite & Tiers

```
composite = safety × 0.45 + holders × 0.30 + price × 0.25
```

| Tier | Range | Emoji |
|------|-------|-------|
| Safe | ≥ 80 | 🟢 |
| Caution | 60–79 | 🟡 |
| Risk | 40–59 | 🟠 |
| Danger | < 40 | 🔴 |

## Output Fields

```json
{
  "composite": 87.5,
  "tier": {"name": "Safe", "emoji": "🟢", "color_hex": "#22c55e"},
  "safety_score": 100.0,
  "holders_score": 100.0,
  "price_score": 50.0,
  "safety_breakdown": [{"name": "mint_renounced", "delta": 0, "detail": "..."}],
  "holders_breakdown": [...],
  "price_breakdown": [...],
  "cu_breakdown": ["overview+mf=21", "security=30", "holders=30", "kline=25"]
}
```

## CLI

```bash
python3 birdeye_cli.py contract-dd \
  --chain sol --address <TOKEN_ADDR> \
  --format rendered
```
