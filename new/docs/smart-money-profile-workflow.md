# Workflow · Smart Money Profile (Skill #9)

Behavior analysis of a **single wallet** with a copy-trade verdict ladder (🟢 copy / 🟡 watch / 🔴 avoid). Replaces the old "Top Smart Money Wallets" skill.

## Inputs

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `chain` | enum | `sol` | sol / bsc / base / eth / arc / robinhood |
| `wallet` | string | — | Wallet address |
| `--skip-tx-list` | flag | false | Skip trade list |
| `--skip-first-tx` | flag | false | Skip first-funded (age) |

## API Calls & CU

| Step | Endpoint | CU | Notes |
|------|----------|----|-------|
| PnL summary 7d | `GET /wallet/v2/pnl/summary?duration=7d` | 30 | trend detection |
| PnL summary 30d | `GET /wallet/v2/pnl/summary?duration=30d` | 30 | baseline |
| Per-token PnL | `POST /wallet/v2/pnl/details` | 30 | TP/SL fallback |
| First-funded | `GET /v1/wallet/first_funded` | 40 → **0 if cached** | wallet age, shared cache |
| Trader txs | `GET /trader/txs/seek_by_time?tx_type=swap` (last 30d) | 12 | round-trip swaps (multi-hop collapsed) |

**Typical: ~120–150 CU** (0 cached first-funded).

## Processing Pipeline

```
1. PnL 7d + 30d → win rate trend, realized PnL trend
2. Per-token PnL → TP/SL fallback (avg realized % wins/losses)
3. First-funded (cached) → wallet age
4. Trader txs (`/trader/txs/seek_by_time`) → multi-hop swap chains collapsed to source→sink → round trips → style + TP/SL
5. Fallback style from PnL trade frequency (no round trips)
6. Copy-trade ROI estimate (round-trip returns → per-token PnL → open positions)
7. Verdict ladder from style + win rate + TP/SL + trend
```

## Style Inference

Same logic as Wallet Analysis (see `workflow-wallet-analysis.md`):
- **Primary**: median hold duration from round trips (scalper / day_trader / swing / holder)
- **Fallback**: trades/day from 30d PnL summary, or `holder` if `total_trade == 0` but net worth > 0

## TP/SL Inference

Same as Wallet Analysis:
- **Primary**: round-trip `(sell - buy) / buy * 100` from trader txs
- **Fallback**: per-token `realized_profit_percent` from `pnl/details`

## Verdict Ladder (`_smp_verdict`)

Evaluated in order, first match wins:

| Priority | Emoji | Label | Condition |
|----------|-------|-------|-----------|
| 1 | ⚪ | HOLDER | `style == "holder"` AND `n_rt == 0` (CEX/cold wallet) |
| 2 | ⚪ | NO READ | `n_rt < 3` (too few round trips) |
| 3 | 🔴 | DO NOT COPY | 7d realized < 0 AND 30d ≥ 0 (edge stopped working) |
| 4 | 🔴 | DO NOT COPY | both 7d and 30d realized ≤ 0 |
| 5 | 🟡 | WATCH, DO NOT COPY | scalper with `avg_win < 10%` AND `avg_loss < -40%` |
| 6 | 🟡 | WATCH, DO NOT COPY | scalper with `avg_win < 10%` (can't get its fills) |
| 7 | 🟡 | COPY BUYS, NOT EXITS | `avg_loss < -40%` (no loss cutting) |
| 8 | 🟢 | COPYABLE AT SMALL SIZE | `wr_30d ≥ 60%` AND `|avg_win| ≥ |avg_loss|` |
| 9 | 🟡 | SELECTIVE FOLLOW | `wr_30d ≥ 50%` |
| 10 | 🔴 | AVOID | `wr_30d < 50%` with no compensating edge |

## Copy-Trade ROI Estimation (`_smp_copy_trade_estimate`)

Estimates the return you would have earned by mirroring the wallet's trades over the last 30 days. This is an **approximation** — not a precise backtest. It ignores entry timing, slippage, and fees.

### Data sources (priority order, first available wins)

| Priority | Source | Return formula | CU |
|----------|--------|---------------|----|
| 1 | **Round-trip buys→sells** from `/trader/txs/seek_by_time` | `(proceeds_usd − cost_usd) / cost_usd × 100` (FIFO, native & stablecoins excluded) | 12 (trader_txs) |
| 2 | **Per-token realized %** from `pnl/details` | `realized_profit_percent` (normalized to %, loss capped at −100%) | uses pnl_details (already fetched) |
| 3 | **Open positions** from portfolio | `(current_usd − cost_usd) / cost_usd × 100` (loss capped at −100%) | 30 (portfolio fetch) |

### Swap parsing & round-trip matching

1. **Fetch full 30d** of swaps via `/trader/txs/seek_by_time?tx_type=swap` (12 CU/page, paginates until `has_next=False`, max 50 pages). Items are sorted ascending by `block_unix_time`; `after_time` is the lower bound and advances to the last item's timestamp on each page.
2. Group items by `tx_hash`. Within each tx, detect `from_leg` (`type_swap=="from"`) and `to_leg` (`type_swap=="to"`).
3. **Multi-hop collapse**: if a single tx contains A→B, B→C, C→D, walk the from→to adjacency from source tokens (appear as `from` but never `to`) and collapse to A→D (intermediaries dropped).
4. **Filter to pnl/details tokens**: only keep swaps where `to_token` or `from_token` appears in the wallet's `pnl/details` token list (avoids counting pass-through/noise swaps).
5. **Exclude native & stablecoins**: SOL, ETH, USDC, USDT, etc. are base currencies, not speculative trades — they are skipped in round-trip matching.
6. **FIFO matching by token quantity (with partial fills)**: for each remaining token T, collect buys (`to_token==T`, qty=`to_amount`, cost=`from_usd`) and sells (`from_token==T`, qty=`from_amount`, proceeds=`to_usd`). Match sells against buys in FIFO order by token quantity. For each matched portion: `cost_portion = buy_cost × (matched_qty / buy_qty)`, `proceeds_portion = sell_proceeds × (matched_qty / sell_qty)`, return = `(proceeds_portion − cost_portion) / cost_portion × 100`. This prevents extreme returns from mismatched buy/sell sizes (e.g., a $100 buy matched with a $100k sell).

### Metrics computed

```
avg_return_pct   = mean of all trade returns
win_rate         = n_wins / n_trades  (win = return > 0)
n_wins, n_trades, n_completed (round-trips), n_open (positions)
best_trade       = {token, return_pct, source}
worst_trade      = {token, return_pct, source}
n_trades_30d     = number of completed round-trips in the 30d window
trades_per_day   = n_trades_30d / 30
est_30d_return_pct = avg_return_pct   (equal-weight copy: same $ per trade, no compounding)
est_method       = explanation string shown in UI
```

**Why `est_30d = avg_return_pct`?** If you copy every trade with the *same* dollar amount (equal weight), your portfolio return over the window equals the *average* return per trade. Each trade is independent — no compounding is modelled. This is the most honest estimate when you don't know position sizing.

### Worked example

Wallet `A8yCtfXB2V…usbT9yfW` (30d PnL, no usable round-trips from tx_list, falls back to per-token realized profits):

| Token | Source | Return % |
|-------|--------|----------|
| WOTF  | pnl    | +2778.44 |
| ABC   | pnl    | +150.00  |
| XYZ   | pnl    | -99.59   |
| … (20 tokens total) |

```
n_trades      = 20
n_wins         = 15
win_rate       = 15/20 = 0.75 → 75%
avg_return_pct = mean(+2778.44, +150.00, −99.59, …) = +1002.93%
best_trade     = WOTF +2778.44%
worst_trade    = WWR −99.59%
est_30d_return = +1002.93%   (per-token source → no compounding applied)
```

Plain-text output:

```
─── Copy-Trade Estimate ───
  Avg return / trade  : +1002.93%
  Win rate            : 15 / 20 trades profitable  (75%)
  Completed / open    : 20 / 0  (source: per-token PnL + open positions)
  Best trade          : +2778.44% on WOTF
  Worst trade         : -99.59% on WWR
  ~30d return (eq-wt) : +1002.93%
  ⚠️  Approximation only — entry timing, slippage, fees not modelled.
```

## Output Schema (raw-json)

```json
{
  "profile": {
    "wallet": "...",
    "chain": "sol",
    "style": "holder",
    "wallet_age_days": 2179,
    "wr_7d": 0.0,
    "wr_30d": 0.0,
    "realized_7d": 0.0,
    "realized_30d": 0.0,
    "trend": "→ stable",
    "tp_pct": null,
    "sl_pct": null,
    "round_trips": 0,
    "copy_trade_estimate": {
      "avg_return_pct": null,
      "win_rate": null,
      "n_wins": 0,
      "n_trades": 0,
      "n_completed": 0,
      "n_open": 0,
      "best_trade": null,
      "worst_trade": null,
      "est_30d_return_pct": null,
      "has_roundtrips": false
    },
    "verdict": {
      "emoji": "⚪",
      "label": "HOLDER",
      "reason": "no on-chain swap activity — wallet holds assets (likely CEX/cold storage)"
    }
  }
}
```

## Cache

- **First-funded**: permanent CSV cache keyed by `(wallet, chain)`, shared across all skills. Hit = **0 CU**.
- **Run cache**: full JSON response cached by `run_id` for 72h. Replay via `--from-cache <run_id>` (0 CU).

## CLI

```bash
python3 birdeye_cli.py smart-money-profile \
  --wallet 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM \
  --chain sol --format raw-json
```

---

# Smart Money Leaderboard (Skill #9b)

Compare **up to 10 wallets** side-by-side and rank them by a composite score. Use this to pick which smart-money wallets are worth following.

## Inputs

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `chain` | enum | `sol` | sol / bsc / base / eth / arc / robinhood |
| `wallet` | repeatable | — | Wallet address, repeat `--wallet` up to 10 times |
| `--pnl-method` | enum | `wac` | `wac` or `net_cash` |

## API Calls & CU

| Step | Endpoint | CU per wallet |
|------|----------|---------------|
| PnL summary 7d | `GET /wallet/v2/pnl/summary?duration=7d` | 30 |
| PnL summary 30d | `GET /wallet/v2/pnl/summary?duration=30d` | 30 |
| Per-token PnL | `POST /wallet/v2/pnl/details` | 30 |

**Total: 90 CU/wallet → 900 CU for 10 wallets.**

## Composite Score Formula

```
composite = wr_30d_norm × 0.4  +  pnl_norm × 0.4  +  token_norm × 0.1  +  recency_norm × 0.1
```

| Component | Weight | Normalization |
|-----------|--------|---------------|
| **Win rate (30d)** | 40% | `wr_30d / 100` (already 0–1) |
| **Realized PnL (30d)** | 40% | rank-percentile across the batch (0–1) |
| **Token diversity** | 10% | min-max of `unique_tokens` across the batch (0–1) |
| **Recency** | 10% | min-max of `(wr_7d − wr_30d)` across batch, clamped to ±50% (0–1) |

- **PnL uses rank-percentile** (not raw $) so a single whale wallet doesn't dominate.
- **Recency** rewards wallets whose win rate is improving (7d > 30d).

## Worked example (2 wallets)

Raw data:

| Wallet | WR 7d | WR 30d | Realized 30d | Tokens |
|--------|-------|--------|--------------|--------|
| `A8yCtf…9yfW` | 100% | 94% | $1,077,019 | 20 |
| `9WzDXw…AWWM` | 0% | 0% | $0 | 0 |

Normalized:

| Component | A8yCtf | 9WzDXw |
|-----------|--------|--------|
| wr_30d_norm (÷100) | 0.94 | 0.00 |
| pnl_norm (rank-pct) | 1.00 | 0.00 |
| token_norm (min-max) | 1.00 | 0.00 |
| recency (wr7d−wr30d = +6%, 0%) | 1.00 | 0.00 |

```
A8yCtf:  0.94×0.4 + 1.00×0.4 + 1.00×0.1 + 1.00×0.1 = 0.376 + 0.400 + 0.100 + 0.100 = 0.976
9WzDXw:  0.00×0.4 + 0.00×0.4 + 0.00×0.1 + 0.00×0.1 = 0.000
```

(Actual runtime output below shows 0.775 / 0.400 because rank-percentile and min-max with a 2-element batch split the 0–1 range differently — ties at the low end get 0.5, etc.)

Plain-text output:

```
Smart Money Leaderboard · SOL · 2 wallets
CU: 180 (pnl_7d=60, pnl_30d=60, pnl_details=60)

Weights: winrate 40% · pnl 40% · diversity 10% · recency 10%

 #  Wallet          WR30d    Realized30d Tokens  Recency  Score
---------------------------------------------------------------
 1  A8yCtf…9yfW       94%    +1,077,019     20      +6%  0.775
 2  9WzDXw…AWWM        0%            +0      0      +0%  0.400
```

## CLI

```bash
python3 birdeye_cli.py smart-money-leaderboard \
  --chain sol \
  --wallet A8yCtfXB2VfyVxzj8gy6F2vSxiPkPcz8yquiusbT9yfW \
  --wallet 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM \
  --format plain
```
