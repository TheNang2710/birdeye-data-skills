# Wallet Score v2 — Absolute Scaling Formula

## Why a new method

The v1 formula (GMGN-style) used **percentile rank** across a leaderboard of 1000+ wallets. Birdeye's per-wallet API does not return a leaderboard, so v1 fell back to a **linear baseline** ($1k→0 / $50k→100) which is arbitrary and misses the shape of real profit distributions.

v2 scores each wallet on **absolute, transparent thresholds** derived from trader-relevant anchors. No leaderboard needed. Each component maps raw data → 0..100 with documented breakpoints.

## Data sources (Birdeye API)

| Step | Endpoint | CU | Fields used |
|------|----------|----|-------------|
| 1 | `GET /wallet/v2/pnl/summary` | 30 | `counts.total_trade`, `counts.win_rate`, `pnl.realized_profit_usd`, `pnl.unrealized_usd`, `pnl.realized_profit_percent`, `cashflow_usd.total_invested`, `cashflow_usd.total_sold`, `cashflow_usd.current_value` |
| 2 | `GET /wallet/v2/pnl` (per-token) | 10 | `tokens[].pnl.total_percent` → rug% |
| 3 | `POST /wallet/v2/tx/first-funded` | 40 | wallet age (solana only) |
| 4 | `GET /wallet/v2/current-net-worth` | 30 | net worth, holdings |

**Short-term trend**: call summary again with `duration=24h` (additive 30 CU, optional). If skipped, trend component = 100 (neutral).

## Hard filters (pre-gate, fail → ×0.50 penalty)

- `total_trade ≥ 20`
- `volume_usd = max(total_invested, total_sold) ≥ $5,000`
- `rug_fraction ≤ 0.50` (if rug data unavailable, treat as pass with note)

## Component formulas (weights 40 / 25 / 20 / 15)

### 1. Profitability (40%)

```
profit_base = clamp(50 * log2(max(realized_usd, 1) / 10000) + 50, 0, 100)

Breakpoints:
  realized ≤ $0      → 0
  $10,000            → 50
  $100,000           → ~100 (capped)
  ≥ $640,000         → 100 (max)

unrealized_penalty:
  if unrealized_usd < 0 and |unrealized| > 0.10 * |realized|:
      ratio = |unrealized| / max(|realized|, 1)
      penalty_factor = clamp(ratio / 0.50, 0, 1)   # full penalty when loss = 50% of realized
      profit_score = profit_base * (1 - 0.5 * penalty_factor)
  else:
      profit_score = profit_base
```

### 2. Consistency (25%)

Three sub-signals:
- `wr_score = clamp(win_rate_fraction * 150, 0, 100)` — 67% win rate → 100
- `tx_score = clamp(log1p(total_trade) / log1p(300) * 100, 0, 100)` — 300 trades → 100
- `trend_score` (24h vs 30d realized):
  - if `realized_24h ≥ 0` → 100
  - else → `clamp(100 * (1 - |realized_24h| / max(|realized_30d|, 1)), 0, 100)`

```
consistency_score = 0.40 * wr_score + 0.30 * tx_score + 0.30 * trend_score
```

### 3. Quality (20%)

```
rug_fraction       = rug_tokens / scanned_tokens   (0 if data unavailable)
concentration      = clamp(log10(max(realized_profit_percent, 1)) / 7, 0, 1)
                     # >100x profit (10000%) → high concentration risk
diversification    = 1 - concentration
realization_ratio  = max(realized_usd, 0) / (max(realized_usd, 0) + max(unrealized_usd, 0) + 1e-9)

quality_score = (1 - rug_fraction) * (0.60 + 0.40 * diversification) * realization_ratio * 100
```

### 4. Activity (15%)

```
vol_score  = clamp(log10(max(volume_usd, 1) / 1000) * 20, 0, 100)
              # $1k vol → 0, $100k → 40, $10M → 80, $100M → 100
tx_score   = clamp(log1p(total_trade) / log1p(500) * 100, 0, 100)

activity_score = 0.60 * vol_score + 0.40 * tx_score
```

### Final

```
alpha = 0.40*profit + 0.25*consistency + 0.20*quality + 0.15*activity
if any hard filter fails: alpha *= 0.50
alpha = clamp(alpha, 0, 100)
```

Tiers: ≥80 ELITE 🟢 · ≥60 PRO 🟡 · ≥40 NOVICE 🟠 · <40 RISK 🔴

---

## Sample run — wallet `8q2ycywXyk4P7CTxXSbwVWF4em57jcxEtbCKrhoGW963`

### API responses (30d, net_cash)

**Step 1 — `/wallet/v2/pnl/summary` (30 CU):**
```json
{
  "counts": { "total_buy": 207, "total_sell": 518, "total_trade": 725,
              "total_win": 12, "total_loss": 31, "win_rate": 0.2727 },
  "pnl": { "realized_profit_usd": 9773542.66, "unrealized_usd": 1.46,
           "total_usd": 9773544.12, "realized_profit_percent": 1782610.37,
           "avg_profit_per_trade_usd": 13480.75 },
  "cashflow_usd": { "total_invested": 611.10, "total_sold": 9774144.53,
                    "current_value": 62.12 }
}
```

**Step 2 — `/wallet/v2/pnl` (per-token):** endpoint now requires `token_addresses` → **rug data unavailable** → `rug_fraction = 0` (noted).

**Step 3 — first-funded:** wallet age (solana).

**Step 4 — `/wallet/v2/current-net-worth` (30 CU):**
```
qOMPUTE  $47.03   LOOP  $13.99   SOL  $0.93   RESTORE  $0.11   SOL  $0.06
total ≈ $62.12  (wallet cashed out nearly all profit)
```

**Short-term trend — `/wallet/v2/pnl/summary?duration=24h` (30 CU):**
```
realized_24h = -$2.57   unrealized_24h = $7.62   trades_24h = 132   win_rate = 18.2%
```

### Hard filters
- total_trade 725 ≥ 20 ✅
- volume = max(611, 9774144) = $9,774,144 ≥ $5,000 ✅
- rug_fraction 0 ≤ 0.50 ✅ (data unavailable, assumed pass)
- **all pass → no penalty**

### Component calculation

**Profitability (40%):**
```
profit_base = clamp(50 * log2(9773542.66 / 10000) + 50, 0, 100)
            = clamp(50 * log2(977.35) + 50, 0, 100)
            = clamp(50 * 9.935 + 50, 0, 100) = clamp(546.8, 0, 100) = 100
unrealized = +$1.46 (positive) → no penalty
profit_score = 100.0
```

**Consistency (25%):**
```
wr_score    = clamp(0.2727 * 150, 0, 100) = 40.91
tx_score    = clamp(log1p(725)/log1p(300) * 100, 0, 100) = clamp(6.59/5.71*100) = 100
trend_score = clamp(100 * (1 - |-2.57| / 9773542.66), 0, 100) = 100 (24h loss negligible vs 30d)
consistency_score = 0.40*40.91 + 0.30*100 + 0.30*100 = 16.36 + 30 + 30 = 76.36
```

**Quality (20%):**
```
rug_fraction    = 0.0 (data unavailable)
concentration   = clamp(log10(1782610.37) / 7, 0, 1) = clamp(6.251 / 7, 0, 1) = 0.893
diversification = 1 - 0.893 = 0.107
realization_ratio = 9773542.66 / (9773542.66 + 1.46) = 0.9999 ≈ 1.000
quality_score = (1 - 0) * (0.60 + 0.40 * 0.107) * 1.000 * 100
              = (0.60 + 0.043) * 100 = 64.3
```

**Activity (15%):**
```
vol_score = clamp(log10(9774144.53 / 1000) * 20, 0, 100)
          = clamp(log10(9774.14) * 20, 0, 100) = clamp(3.990 * 20) = 79.8
tx_score  = clamp(log1p(725)/log1p(500) * 100, 0, 100) = clamp(6.59/6.22*100) = 100 (clamped)
activity_score = 0.60 * 79.8 + 0.40 * 100 = 47.9 + 40 = 87.9
```

### Final
```
alpha = 0.40*100.0 + 0.25*76.36 + 0.20*64.3 + 0.15*87.9
      = 40.0 + 19.09 + 12.86 + 13.19
      = 85.14
```
**Tier: ELITE 🟢** (profitability exceptional, dragged by low win rate & high single-token concentration)

### Data gaps (ignored / defaulted)

| Field | Status | Handling |
|-------|--------|----------|
| `unique_tokens` | Not in summary response | Activity uses `total_trade` as proxy |
| `rug_token_percent` | Per-token endpoint requires `token_addresses` now | `rug_fraction = 0`, noted in step checks |
| 180d PnL trend | 30d and 90d responses identical for this wallet | Short-term 24h vs 30d trend used instead |
| Liquidity-adjusted PnL | Not available | Uses raw realized/unrealized |
