# Wallet Score API — Include-based Compact Endpoint

> Version: v3.1 | Base: `birdeye_cli.py wallet-score`
> Updated: 2026-10-11

---

## 1. Overview

The Wallet Score API accepts a wallet address and returns **numeric-only data blocks** selected via the `--include` parameter. No formulas, no explanatory text — just structured numbers. CU cost scales with the number of blocks included.

```
python3 birdeye-screener/scripts/birdeye_cli.py wallet-score \
  --chain sol \
  --wallet <WALLET_ADDRESS> \
  --duration 30d \
  --pnl-method wac \
  --include <block1>,<block2>,...
```

---

## 2. Data Blocks & CU Cost

| Block | CU | API Source | Description |
|---|---|---|---|
| `pnl` | 30 | `GET /wallet/v2/pnl/summary?duration=30d` | PnL summary 30d |
| `pnl_24h` | 30 | `GET /wallet/v2/pnl/summary?duration=24h` | PnL summary 24h (diagnostic) |
| `pnl_90d` | 30 | `GET /wallet/v2/pnl/summary?duration=90d` | PnL summary 90d (trend) |
| `tokens` | 30 | `POST /wallet/v2/pnl/details` | Per-token breakdown, deep-loss tiers, cash-out, concentration |
| `wallet` | 40 (cached→0) | `POST /wallet/v2/tx/first-funded` | Wallet age, creation block, first tx |
| `portfolio` | 30 | `GET /wallet/v2/current-net-worth` | Current net worth, token count |
| `leaderboard` | 25 (cached→0) | `GET /wallet/v2/leaderboard` | Rank vs top-100 daily leaderboard |
| `score` | 0 (computed) | (requires pnl + pnl_90d + tokens + leaderboard) | Alpha score + 4 components |

**CU Savings:**
- `wallet` block: 40 CU first call, **0 CU** on repeat (permanent CSV cache — wallet age never changes)
- `leaderboard` block: 25 CU first call of the day, **0 CU** after (24h cache)
- Full score run (all blocks): ~190 CU first, ~150 CU repeat
- Minimal: `pnl` only = **30 CU**

**Auto-dependencies:** Including `score` automatically adds `pnl`, `pnl_90d`, `tokens`, `leaderboard`.

---

## 3. Response Format

All responses are JSON with a `#RUN_ID` prefix line (parsers should skip the first line).

```json
{
  "schemaVersion": 1,
  "kind": "wallet-score-compact-v1",
  "runId": "wallet-alpha_sol_<wallet10>_30d_<ts>",
  "wallet": "<WALLET_ADDRESS>",
  "chain": "sol",
  "duration": "30d",
  "pnl_method": "wac",
  "snapshot_time": 1791717706,
  "cu_used_total": 90,
  "cu_breakdown": {
    "step0_leaderboard_benchmark": 0,
    "step1_pnl_summary": 30,
    "step1b_pnl_summary_24h": 0,
    "step1c_pnl_summary_90d": 30,
    "step2_per_token_pnl_rug": 30,
    "step3_first_funded": 0,
    "step4_portfolio_v2": 0
  },
  "blocks": {
    "...": "only included blocks appear here"
  }
}
```

---

## 4. Block Field Reference

### `pnl` — PnL Summary 30d (30 CU)

| Field | Type | Description |
|---|---|---|
| `realized_pnl_usd` | float | Realized profit/loss (chốt) |
| `unrealized_pnl_usd` | float | Unrealized profit/loss (giấy) |
| `total_pnl_usd` | float | Total PnL = realized + unrealized |
| `volume_usd` | float | Total trading volume |
| `win_rate_percent` | float | Win rate percentage |
| `total_trade` | int | Total number of trades |
| `unique_tokens` | int | Number of unique tokens traded |

### `pnl_24h` — PnL Summary 24h (30 CU)

| Field | Type | Description |
|---|---|---|
| `realized_pnl_usd` | float | Realized PnL in last 24h |

### `pnl_90d` — PnL Summary 90d (30 CU)

| Field | Type | Description |
|---|---|---|
| `realized_pnl_usd` | float | Realized PnL in last 90d |
| `previous_60d_pnl_usd` | float | PnL in 60d before the last 30d (= 90d − 30d) |

### `tokens` — Per-Token Breakdown (30 CU)

| Field | Type | Description |
|---|---|---|
| `deep_loss_token_count` | int | Total deep-loss tokens (total_percent ≤ −50%) |
| `deep_loss_token_scanned` | int | Total tokens scanned |
| `deep_loss_fraction` | float | `deep_loss_count / deep_loss_scanned` (0..1) |
| `deep_loss_penalty_pts` | float | Penalty = **weighted bag-hold** loss fraction × 100 |
| `loss_critical_count` | int | Tokens losing ≥90% (total_percent ≤ −0.90) |
| `loss_severe_count` | int | Tokens losing ≥75% (total_percent ≤ −0.75) |
| `loss_moderate_count` | int | Tokens losing ≥50% (total_percent ≤ −0.50) |
| `bag_hold_loss_count` | int | Loss tokens where `realized_profit_usd ≤ 0` (never cashed out — bad) |
| `smart_exit_loss_count` | int | Loss tokens where `realized_profit_usd > 0` (already booked profit — good) |
| `bag_hold_loss_fraction` | float | `bag_hold_loss_count / deep_loss_scanned` (0..1) |
| `profit_concentration` | float | Largest profit / total positive profit (0..1) |
| `severe_loss_positions` | int | Tokens with realized loss >50% |
| `closed_positions` | int | Tokens with both buy and sell |
| `profitable_positions` | int | Tokens with positive realized PnL |

### `wallet` — First Funded (40 CU, cached→0)

| Field | Type | Description |
|---|---|---|
| `wallet_age_days` | int | Wallet age in days |
| `wallet_created_ts_unix` | int | Creation timestamp (unix) |
| `wallet_created_block` | int | Creation block number |
| `first_tx_hash_prefix` | string | First 16 chars of first transaction hash |

### `portfolio` — Current Holdings (30 CU)

| Field | Type | Description |
|---|---|---|
| `current_net_worth_usd` | float | Current net worth in USD |
| `portfolio_token_count` | int | Number of tokens currently held |

### `leaderboard` — Leaderboard Rank (25 CU, cached→0)

| Field | Type | Description |
|---|---|---|
| `rank` | int | Position among top-100 leaderboard (1 = best) |
| `leaderboard_size` | int | Leaderboard size (usually 100) |
| `benchmark_realized_pnl_usd` | float | Top-1 wallet's realized PnL (max reference) |

### `score` — Alpha Score (0 CU, computed)

| Field | Type | Description |
|---|---|---|
| `alpha` | float | Final alpha score (0..100) |
| `tier` | string | Tier name (LEGENDARY/ELITE/PRO/ADVANCED/NOVICE/RISK) |
| `profitability` | float | Profitability component score |
| `consistency` | float | Consistency component score |
| `quality` | float | Quality component score |
| `activity` | float | Activity component score |

---

## 5. Deep-Loss Token Detection — Data Source & Logic

**Note:** These are **NOT "rug" tokens**. The API has no rug-detection data. What we measure is
simply tokens that lost a lot of value (`total_percent ≤ −50%`). A token at −90% is not necessarily
bad — if the trader already realized a big profit, the remaining position being down is just a
"runner" that didn't work out. The penalty only applies when the trader **never cashed out**
(`realized_profit_usd ≤ 0`) — i.e. they're bag-holding.

**Source:** `POST /wallet/v2/pnl/details` (30 CU).

### API Call
```http
POST https://public-api.birdeye.so/wallet/v2/pnl/details
Headers: x-chain: solana, X-API-KEY: <key>
Body: { "wallet": "<addr>", "duration": "30d", "pnl_method": "wac",
        "position_scope": "duration_only", "sort_by": "last_trade",
        "sort_type": "desc", "limit": 100, "offset": 0 }
CU: 30
```

### Response Structure
```json
{
  "data": {
    "tokens": [
      {
        "pnl": {
          "realized_profit_usd": 1500.0,      // profit already booked (chốt lời)
          "realized_profit_percent": 0.15,
          "unrealized_usd": -2400.0,           // paper loss on remaining position
          "unrealized_percent": -0.90,
          "total_percent": -0.60,              // combined realized + unrealized %
          "total_usd": -900.0
        },
        "counts": { "total_buy": 5, "total_sell": 5 }
      },
      ...
    ]
  }
}
```

### Step 1 — Classify Loss Depth (by `total_percent`)
| Tier | Threshold | Weight |
|---|---|---|
| **CRITICAL** | `total_percent ≤ −0.90` (≥90% loss) | ×1.0 |
| **SEVERE** | `total_percent ≤ −0.75` (≥75% loss) | ×0.67 |
| **MODERATE** | `total_percent ≤ −0.50` (≥50% loss) | ×0.33 |

### Step 2 — Classify Cash-Out (for loss tokens only)
For each loss token (`total_percent ≤ −0.50`):
- **SMART_EXIT** (good, NO penalty): `realized_profit_usd > 0`
  → Trader already booked profit. The remaining position being down is acceptable risk management.
- **BAG_HOLD** (bad, penalized): `realized_profit_usd ≤ 0`
  → Trader never took profit, just holding a losing bag.

### Step 3 — Compute Penalty
```
weighted_bag_hold = bag_hold_critical × 1.0
                  + bag_hold_severe   × 0.67
                  + bag_hold_moderate × 0.33

deep_loss_penalty_pts = min(100, weighted_bag_hold / token_count_in_scan × 100)
```

**Example:** 3 tokens at −90% loss, all with `realized_profit_usd ≤ 0` (bag-hold), out of 4 scanned:
→ `weighted_bag_hold = 3 × 1.0 = 3` → `penalty = 3/4 × 100 = 75 pts` (deducted from Quality).

**Example (smart exit):** Same 3 tokens at −90%, but all have `realized_profit_usd > 0`:
→ `bag_hold_loss_count = 0` → `penalty = 0 pts` (no quality penalty — trader cashed out).

---

## 6. Examples

### Example 1: PnL only (30 CU)
```bash
python3 birdeye-screener/scripts/birdeye_cli.py wallet-score \
  --chain sol --wallet 8vcR9ZzrGk6nbTHcveSjacDGXjqJR3oVZNUeu3rhTLBg \
  --include pnl
```
```json
{
  "cu_used_total": 30,
  "blocks": {
    "pnl": {
      "realized_pnl_usd": 335500.10,
      "unrealized_pnl_usd": -56826.16,
      "total_pnl_usd": 278673.94,
      "volume_usd": 390644.58,
      "win_rate_percent": 33.33,
      "total_trade": 478,
      "unique_tokens": 3
    }
  }
}
```

### Example 2: Wallet + Portfolio (30 CU, wallet cached)
```bash
python3 birdeye-screener/scripts/birdeye_cli.py wallet-score \
  --chain sol --wallet 8vcR9ZzrGk6nbTHcveSjacDGXjqJR3oVZNUeu3rhTLBg \
  --include wallet,portfolio
```
```json
{
  "cu_used_total": 30,
  "blocks": {
    "wallet": {
      "wallet_age_days": 6,
      "wallet_created_ts_unix": 1791124850,
      "wallet_created_block": 453286268,
      "first_tx_hash_prefix": "3fZrB4eCzqc4StHK"
    },
    "portfolio": {
      "current_net_worth_usd": 87.98,
      "portfolio_token_count": 1
    }
  }
}
```

### Example 3: Full Score (90 CU, leaderboard cached)
```bash
python3 birdeye-screener/scripts/birdeye_cli.py wallet-score \
  --chain sol --wallet 8vcR9ZzrGk6nbTHcveSjacDGXjqJR3oVZNUeu3rhTLBg \
  --include score
```
```json
{
  "cu_used_total": 90,
  "blocks": {
    "pnl": { "...": "auto-included" },
    "pnl_90d": { "...": "auto-included" },
    "tokens": {
      "deep_loss_token_count": 3,
      "deep_loss_token_scanned": 4,
      "deep_loss_fraction": 0.75,
      "deep_loss_penalty_pts": 75.0,
      "loss_critical_count": 3,
      "loss_severe_count": 0,
      "loss_moderate_count": 0,
      "bag_hold_loss_count": 3,
      "smart_exit_loss_count": 0,
      "bag_hold_loss_fraction": 0.75,
      "profit_concentration": 1.0,
      "severe_loss_positions": 1,
      "closed_positions": 4,
      "profitable_positions": 1
    },
    "leaderboard": { "...": "auto-included" },
    "score": {
      "alpha": 55.42,
      "tier": "ADVANCED",
      "profitability": 75.89,
      "consistency": 66.36,
      "quality": 0.0,
      "activity": 56.33
    }
  }
}
```

---

## 7. Tier Thresholds

| Tier | Alpha Range | Color |
|---|---|---|
| LEGENDARY | ≥ 95 | `#22d3ee` (cyan) |
| ELITE | ≥ 80 | `#22c55e` (green) |
| PRO | ≥ 65 | `#facc15` (yellow) |
| ADVANCED | ≥ 50 | `#fb923c` (orange) |
| NOVICE | ≥ 30 | `#f87171` (light red) |
| RISK | < 30 | `#dc2626` (red) |

---

## 8. Notes

- **`--nocache`** flag forces fresh data (skips 24h wallet CSV cache). Does NOT affect first-funded permanent cache.
- **First-funded cache** (`wallet_first_funded_cache.csv`): wallet age data never changes → cached permanently per wallet+chain.
- **Leaderboard cache**: 24h TTL, shared across all wallet runs.
- **`pnl_method`**: `wac` (weighted average holding cost, default) or `net_cash` (cashflow difference).
- **`duration`**: `all`, `90d`, `30d` (default), `7d`, `24h`.
