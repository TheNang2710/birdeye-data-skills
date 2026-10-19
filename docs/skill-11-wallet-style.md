# Skill #11 · Wallet Style

## High-Level Concept

Classifies a wallet's trading style into a **4×5 grid** of **Frequency (L1–L4)** × **P&L (P1–P5)**, producing one of 20 named style badges (e.g. "🦅 Old Hunter", "🌾 Harvester", "🐑 Retail Loser"). Each cell has an emoji, a name, and a plain-language meaning shown on hover.

The grid uses two independent axes:
- **Frequency** = trades per day (how often the wallet trades)
- **P&L level** = return ratio + win rate + loss tail quality

## Inputs

| Field | Type | Description |
|-------|------|-------------|
| `chain` | enum | sol / bsc / base / eth / arc / robinhood |
| `wallet` | string | Wallet address |
| `duration` | enum | 7d / 30d |
| `--skip-tx-list` | flag | Skip per-tx trade list (saves CU) |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| PnL summary | `/wallet/v1/pnl/summary` | ~30 |
| Per-token PnL | `/wallet/v1/pnl/token-list` | ~30 |
| First-funded (provenance) | `/wallet/v1/first-funded` | 0 (cached) |

**Total: ~60–90 CU** (varies by optional tx list).

## Axis 1 — Frequency (L1–L4)

```
per_day = total_trades / duration_days
```

| Level | Name | Trades/day |
|-------|------|------------|
| L1 | Rare | < 1 |
| L2 | Regular | 1 – < 10 |
| L3 | Frequent | 10 – ≤ 50 |
| L4 | Machine | > 50 |

## Axis 2 — P&L Level (P1–P5)

```
pnl_ratio = realized_pnl_usd / total_invested_usd
lt50_share = (tokens down >50%) / total_tokens
```

| Level | Name | Condition |
|-------|------|-----------|
| P5 | Strong Profit | `pnl_ratio > 0.5` AND `tokens ≥ 5` AND (`win_rate ≥ 0.5` OR `lt50_share < 0.15`) |
| P4 | Net Profit | `pnl_ratio > 0.1` |
| P3 | Break-Even | `|pnl_ratio| ≤ 0.10` |
| P2 | Net Loss | `realized < 0` OR `pnl_ratio < 0` |
| P1 | Heavy Loss | `lt50_share ≥ 0.40` AND `realized < 0` |

*(Tested in order, first match wins. Default = P3.)*

## The 4×5 Style Grid

| | P5 Strong Profit | P4 Net Profit | P3 Break-Even | P2 Net Loss | P1 Heavy Loss |
|---|---|---|---|---|---|
| **L4 Machine** | 🖨️ Money Printer | ⚙️ Full-Auto Grinder | 🪫 Worn Down | 🔥 Gas Burner | 💥 Self-Destruct |
| **L3 Frequent** | 🌾 Harvester | ⚔️ Active Winner | 🌀 Spinning Top | 💸 Fee Donor | 🩸 Bleeding Out |
| **L2 Regular** | 🦅 Old Hunter | 📈 Steady Hand | ☕ Lukewarm | 🐑 Retail Loser | 🕳️ Deep Underwater |
| **L1 Rare** | 🗡️ One-Shot | 🧘 Zen Winner | 👀 Bystander | 💧 Toe In The Water | ⚰️ Wiped Out |

## Badges

Additional context badges may be attached:
- **⚠️ Thin Sample** — too few trades for a reliable classification
- **Speed subtitle** — median hold time (from tx list, if available)

## Output Fields

```json
{
  "main_title": {
    "emoji": "🦅", "en": "Old Hunter",
    "meaning": "Rarely swings, mostly connects",
    "freq": "L1", "pnl": "P5"
  },
  "freq": {"key": "L1", "name": "Rare", "per_day": 0.3},
  "pnl_level": "P5",
  "badges": [["⚠️", "Thin Sample", "30d only 3 trades"]],
  "metrics": {"total_trade": 9, "win_rate": 0.67, "pnl_ratio": 1.23, ...}
}
```

## Reuse in Wallet Score (Skill #13)

When `--include-style` is passed to `wallet-score`, the same `_wsf_compute()` runs on the already-fetched PnL data — **0 extra CU** — and the Style Badge is rendered next to the alpha score with a hover tooltip showing `{name} · {freq}×{pnl} · {meaning}`.

## CLI

```bash
python3 birdeye_cli.py wallet-style \
  --chain sol --wallet <WALLET_ADDR> \
  --duration 30d --format rendered
```
