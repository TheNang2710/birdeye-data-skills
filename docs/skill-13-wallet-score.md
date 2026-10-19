# Skill #13 · Wallet Score

## High-Level Concept

A **4-factor alpha score (0–100)** that rates a wallet's trading skill, plus a separate **copy-tradeability score (0–100)**. The alpha score blends profitability, consistency, quality (loss discipline), and activity. Sustainability gates cap the score when recent PnL is non-positive.

## Inputs

| Field | Type | Description |
|-------|------|-------------|
| `chain` | enum | sol / bsc / base / eth / arc / robinhood |
| `wallet` | string | Wallet address |
| `duration` | enum | 7d / 30d |
| `pnl_method` | enum | wac (weighted average cost) / fifo |
| `--include-style` | flag | Also compute Wallet Style badge (0 extra CU, reuses data) |
| `--skip-rug` | flag | Skip rug/deep-loss token scan |
| `--skip-portfolio` | flag | Skip portfolio value fetch |
| `--skip-first-tx` | flag | Skip first-funded provenance |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| PnL summary (30d) | `/wallet/v1/pnl/summary` | 30 |
| PnL summary (24h) | `/wallet/v1/pnl/summary` | 0 (cached) |
| PnL summary (90d) | `/wallet/v1/pnl/summary` | 0 (cached) |
| Per-token PnL + rug scan | `/wallet/v1/pnl/token-list` | 0 (cached) |
| First-funded | `/wallet/v1/first-funded` | 0 (cached) |
| Portfolio v2 | `/wallet/v2/portfolio` | 0 (cached) |
| Leaderboard benchmark | `/wallet/v1/leaderboard` | 0 |

**Total: ~30–110 CU** (first run; cached replays cost 0).

## Alpha Score — 4 Components

### 1. Profitability (weight 35%)

```
roi_realized = realized_pnl / invested
roi_total    = (realized + unrealized) / invested
roi_effective = min(roi_realized, roi_total)
roi_base      = clamp((roi_effective + 5%) / 35% × 100, 0, 100)
abs_profit_base = clamp(log10(realized_usd / 100) × 20, 0, 100)
keep_factor   = max(0, 1 − |unrealized| / realized)
profitability = max(roi_base, abs_profit_base) × keep_factor
```

### 2. Consistency (weight 35%)

```
wr_score     = clamp(win_rate / 60% × 100, 0, 100)
trend_score  = 30d vs prev-60d PnL (50 if insufficient history)
dist_score   = 0.60 × profitable_positions + 0.40 × (1 − concentration)
sample_score = clamp(log1p(trades) / log1p(300) × 100, 0, 100)
consistency  = 0.20×wr + 0.40×trend + 0.25×dist + 0.15×sample
```

### 3. Quality (weight 20%)

Measures loss discipline via smart-exit scoring:

```
realization   = realized / (realized + unrealized_positive)
profit_dist   = 1 − profit_concentration
loss_discipline = value-weighted smart_exit_score (by buy USD)
  smart_exit per token: booked profit ≥ paper loss → 100
                        pure bag-hold → 50@0% → 0@−100% loss depth
quality = 0.35×realization + 0.35×profit_dist + 0.30×loss_discipline
```

### 4. Activity (weight 10%)

```
vol_score   = clamp(log10(volume / 1000) × 20, 0, 100)
tx_conf     = clamp(log1p(trades) / log1p(300), 0, 1)
bot_penalty = 1.0 (floor 0.70 when trades > 300)
activity    = (0.60×vol_score + 0.40×tx_conf×100) × bot_penalty
```

### Final Alpha

```
alpha_weighted = P×0.35 + C×0.35 + Q×0.20 + A×0.10
```

**Sustainability gates** (cap the score):
- 30d realized ≤ 0 → cap at 39
- 90d realized ≤ 0 → cap at 49
- prev-60d ≤ 0 AND |prev60d| > $100 → cap at 69

### Alpha Tiers

| Tier | Range | Emoji |
|------|-------|-------|
| LEGENDARY | ≥ 95 | 💎 |
| ELITE | 80–94 | 🟢 |
| PRO | 65–79 | 🟡 |
| ADVANCED | 50–64 | 🟠 |
| NOVICE | 30–49 | 🟤 |
| RISK | < 30 | 🔴 |

## Copy-Tradeability Score (0–100)

A separate score for how copyable a wallet's trades are:

```
entry    = clamp(0.12 + (1 − entry_under_100k))      # 22%
profit   = clamp(avg_profit_per_trade / 80)            # 22%
hold     = clamp((1 − fast_flip×1.6) × clamp(avg_hold/172800 + 0.15))  # 20%
feasible = clamp(1 − trades / 2500)                     # 18%
edge     = clamp(1 − 0.6×entry_under − 0.6×fast_flip)  # 18%
copy_score = 0.22×entry + 0.22×profit + 0.20×hold + 0.18×feasible + 0.18×edge
```

7 tiers (3 copyable, 2 neutral, 2 hard).

## UI Features

- **SVG arc gauge**: 0/100 = empty arc, 100/100 = full semicircle. Score rendered as text inside.
- **Style Badge** (when `--include-style`): gradient pill next to alpha score. Hover shows `{name} · {freq}×{pnl} · {meaning}`.
- **Component cards**: each of the 4 components shows score, weight, and formula on hover.
- **Hard filters** (tx ≥ 20, vol ≥ $5k, deep-loss ≤ 50%): informational only (no alpha multiplier).

## CLI

```bash
python3 birdeye_cli.py wallet-score \
  --chain sol --wallet <WALLET_ADDR> \
  --duration 30d --format rendered --include-style
```
