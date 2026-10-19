# Workflow · Wallet Analysis (Skill #14)

Deep-dive on a **single wallet**: holdings, performance, trading style, risk, and a structured verdict. Replaces the old "SM Flow 1 Token" skill.

## Inputs

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `chain` | enum | `sol` | sol / bsc / base / eth / arc / robinhood |
| `wallet` | string | — | Wallet address |
| `--intervals` | csv | `24h,7d,30d,90d,all` | PnL intervals to fetch |
| `--skip-tx-list` | flag | false | Skip trade list (no style/TP-SL from round trips) |
| `--skip-first-tx` | flag | false | Skip first-funded (age) |
| `--skip-portfolio` | flag | false | Skip current holdings |

## API Calls & CU

| Step | Endpoint | CU | Notes |
|------|----------|----|-------|
| PnL summary ×N intervals | `GET /wallet/v2/pnl/summary?duration=` | 30 each | 5 intervals = 150 CU |
| Per-token PnL | `POST /wallet/v2/pnl/details` | 30 | profit concentration, TP/SL fallback |
| First-funded | `GET /v1/wallet/first_funded` | 40 → **0 if cached** | wallet age, shared cache across skills |
| Portfolio v2 | `GET /v2/wallet/portfolio` | 30 | current holdings, asset concentration |
| Tx list | `GET /v1/wallet/tx_list?limit=100` | 30 | round-trip TP/SL + style |
| Net-worth history (Solana) | `GET /wallet/v2/net-worth?type=1d&count=90` | 50 | real start/end net-worth per interval |

**Typical: ~290–330 CU** (5 intervals + details + portfolio + tx + networth + 0 cached first-funded).

## Processing Pipeline

```
1. PnL summaries (per interval) → trading + performance blocks
2. Per-token PnL → profit concentration, TP/SL fallback
3. First-funded (cached) → wallet age
4. Portfolio → net worth, token count, asset concentration
5. Tx list → round-trip holds → style + TP/SL
6. Net-worth history (Solana) → real start/end net-worth per interval
7. Fallback style from PnL summary when no round trips
8. Compose profile + risk + verdict
```

> **Note:** `avg_hold_duration` is intentionally **not** in the output. The tx_list round-trip hold calculation is unreliable for most wallets (partial fills, native-token vs USD mismatches) and was consistently returning `N/A`. Style inference still uses round-trip holds internally, but the hold-duration field is not surfaced.

## Style Inference (`_wa_infer_style`)

**Primary signal** — buy→sell round trips from `tx_list` (median hold duration):

| Hold | Style |
|------|-------|
| `< 1h` | `scalper` |
| `1–24h` | `day_trader` |
| `1–7d` | `swing` |
| `> 7d` | `holder` |

**Fallback** (when `tx_list` yields no swaps — common for CEX/cold wallets):
- If `total_trade == 0` and `net_worth > 0` → `holder` (holds assets, no on-chain swaps)
- If `total_trade == 0` and no value → `unknown`
- Otherwise derive from **trades/day** (30d window):
  - `≥ 5/day` → `scalper` (if `trades/token > 3`) else `day_trader`
  - `≥ 1/day` → `day_trader`
  - `≥ 0.1/day` → `swing`
  - `< 0.1/day` → `holder`

## TP/SL Inference (`_wa_tp_sl_pattern`)

**Primary** — round-trip P&L from `tx_list`:
```
pct = (sell_sol_amount - buy_sol_amount) / buy_sol_amount * 100
```
- `avg_win_pct` = mean of pct ≥ 0
- `avg_loss_pct` = mean of pct < 0

**Fallback** — per-token `realized_profit_percent` from `pnl/details` (normalized to %).

## Assets & Net-Worth History

For each interval, `start_net_worth` and `end_net_worth` come from the **real** `/wallet/v2/net-worth` history API (Solana only, 50 CU, 90 daily snapshots).

- `end_net_worth` = current portfolio value (from portfolio v2, or 30d PnL `current_value` as fallback).
- `start_net_worth` = net-worth snapshot at `interval_days` ago (closest available daily snapshot).
- If the wallet had `$0` net worth at interval start (newly funded wallet), `change_percent` is `null` (shown as "N/A (new wallet)") — percentage change from 0 is undefined.
- If history is unavailable (non-Solana or API failure), falls back to approximation: `start = max(current - total_pnl, 0)`.

This replaces the old approximation `start_net_worth = current_value - total_pnl_usd`, which produced absurd results (e.g., PnL existing while net-worth appeared unchanged).

## Output Schema (raw-json)

```json
{
  "profile": {
    "last_transaction_at": 1791765700,
    "wallet_age_days": 2179,
    "trading_style": "holder",
    "take_profit_pct": null,
    "stop_loss_pct": null,
    "round_trips": 0
  },
  "assets": {
    "current": {"net_worth": 3428277672.62, "token_count": 50},
    "intervals": {"24h": {...}, "7d": {...}, "30d": {...}}
  },
  "trading": {"24h": {...}, "7d": {...}, "30d": {...}},
  "performance": {"24h": {...}, "7d": {...}, "30d": {...}},
  "risk": {
    "asset_concentration": {"top_1_weight": 0.34, "top_3_weight": 0.75, "top_5_weight": 0.87},
    "profit_concentration": null,
    "open_positions": {...}
  }
}
```

## Cache

- **First-funded**: permanent CSV cache keyed by `(wallet, chain)`. Any skill that fetches it populates the cache for all skills. Hit = **0 CU**.
- **Run cache**: full JSON response cached by `run_id` for 72h. Replay via `--from-cache <run_id>` (0 CU).

## CLI

```bash
python3 birdeye_cli.py wallet-analysis \
  --wallet 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM \
  --chain sol --format raw-json
```
