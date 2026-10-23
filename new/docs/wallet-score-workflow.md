# Workflow: Wallet Score (Skill #13)

## What it does
Rates a wallet's trading skill with a 0–100 alpha score and a copy-tradeability score, using 4 factors: profitability, consistency, quality, and activity.

## When to use
- You found a wallet making money and want to know if it's skill or luck.
- You want to copy-trade a wallet and need to assess feasibility.
- You want a quick "is this wallet worth following?" verdict.

## Inputs
- **Wallet address** (e.g. `5tzS9vNSLP...`)
- **Chain** (sol / bsc / base / eth)
- **Duration**: 7d (short-term) or 30d (more reliable)
- **Optional**: tick "Wallet Style badge" to also get the trading-style classification (0 extra CU)

## Step-by-step

### 1. Open Wallet Score
Go to **🧠 Wallet & Smart Money → Skill #13 · Wallet Score**.

### 2. Enter the wallet
- Paste the wallet address in the **Wallet** field.
- Choose **Chain** (default: sol).
- Choose **Duration** (default: 30d).

### 3. (Optional) Enable Wallet Style
Tick the **+ Wallet Style badge** checkbox. This reuses the already-fetched PnL data — no extra API cost — and adds a style badge next to the score.

### 4. Run
Click **Run**. Wait ~3–10 seconds (first run fetches PnL data).

### 5. Read the output
- **Arc gauge** shows the alpha score (0–100). The arc fill = score% of the semicircle.
- **Tier** (💎 LEGENDARY / 🟢 ELITE / 🟡 PRO / 🟠 ADVANCED / 🟤 NOVICE / 🔴 RISK).
- **4 component cards**: Profitability (35%), Consistency (35%), Quality (20%), Activity (10%). Hover each for the formula.
- **Style badge** (if enabled): e.g. "🦅 Old Hunter". Hover to see meaning.
- **Copy-tradeability score** (0–100) with tier.

### 6. Save & reuse
- The run is auto-saved to **History**. Click any past run to replay (0 CU).
- Use the **📋 copy button** next to the CLI command to copy the full command.
- Use the **📋 copy button** next to the wallet input to copy the address.

## How to read the score
| Score | Meaning |
|-------|---------|
| ≥ 95 | Elite trader, consistent profitability, strong loss discipline |
| 80–94 | Strong, worth following |
| 65–79 | Solid, but has weaknesses |
| 50–64 | Average — some skill, some luck |
| 30–49 | Below average |
| < 30 | High risk — likely losing money |

## Copy-Tradeability Score — how it's calculated

The copy-tradeability score (0–100) answers: **"If I copy this wallet's trades, will I actually make money, and can I realistically follow them?"**

It is a weighted average of **5 factors** (each normalized to 0–1, then ×100):

```
copy_score = 100 × (
    0.22 × entry        # can I enter at a similar price?
  + 0.22 × profit       # does each trade make enough $?
  + 0.20 × hold         # is the hold time long enough to follow?
  + 0.18 × feasible     # are there too many trades to copy?
  + 0.18 × edge         # is the edge sustainable (not just luck)?
)
```

### Factor formulas

| Factor | Formula | What it measures |
|--------|---------|------------------|
| **entry** | `clamp(0.12 + (1 − entry_under_100k))` | % of tokens that 5×'d (proxy for entering under $100k mcap — hard to copy at same price) |
| **profit** | `clamp(avg_trade_usd / 80)` | avg realized profit per trade; ≥$80 = 1.0 |
| **hold** | `clamp((1 − fast_flip×1.6) × clamp(avg_hold_s / 172800 + 0.15))` | estimated avg hold time; ≥48h = good; fast flips penalized |
| **feasible** | `clamp(1 − total_trades / 2500)` | fewer trades = easier to copy; >2500 trades = 0 |
| **edge** | `clamp(1 − 0.6×entry_under_100k − 0.6×fast_flip)` | edge sustainability; high 5x-rate + fast flips = low edge |

Where:
- `entry_under_100k = count(tokens with realized_profit_percent ≥ 400%) / total_tokens` — proxy for early entry
- `fast_flip = clamp(trades_per_day / 100, 0, 1) × 0.5`
- `avg_hold_s = (duration_days × 86400) / (total_trades / unique_tokens)`

### Copy tiers

| Tier | Score + conditions | Meaning |
|------|--------------------|---------|
| 💎 Elite Copy | ≥70 · profit≥50 · feasible≥40 · edge≥40 | High profit, sustainable edge, easy to follow |
| 🟢 Steady Safe Copy | ≥55 · hold≥50 · profit≥35 | Reliable, patient, profitable |
| 🟡 Risky High-Profit Copy | ≥45 · profit≥60 | Big wins but risky style |
| ⚪ Long-Term Patient Copy | ≥40 · hold≥60 | Slow holds, low activity |
| ⚪ Speculative Entry Copy | ≥30 · entry<40 | Early entries hard to replicate |
| 🔴 Low Edge / Noisy | ≥15 | Random-ish results |
| ⛔ Do Not Copy | <15 | Not worth following |

### Worked example

Wallet `A8yCtfXB2V…` (30d, wac):

| Input | Value |
|-------|-------|
| total_trades | 54 |
| unique_tokens | 20 |
| tokens ≥ 5x | 15 |
| avg profit / trade | $27,524 |
| duration | 30 days |
| trades/day | 1.8 |

**Step 1 — compute proxies:**
- `entry_under_100k = 15 / 20 = 0.75`
- `fast_flip = clamp(1.8 / 100) × 0.5 = 0.009`
- `avg_hold_s = (30 × 86400) / (54 / 20) = 2,592,000 / 2.7 = 960,000s ≈ 266h`

**Step 2 — compute each factor (0–1):**
- `entry    = clamp(0.12 + (1 − 0.75)) = clamp(0.37) = 0.370`
- `profit   = clamp(27524 / 80) = clamp(344) = 1.000`
- `hold     = clamp((1 − 0.009×1.6) × clamp(960000/172800 + 0.15)) = clamp(0.985 × 1.0) = 0.985`
- `feasible = clamp(1 − 54/2500) = clamp(0.978) = 0.978`
- `edge     = clamp(1 − 0.6×0.75 − 0.6×0.009) = clamp(0.545) = 0.545`

**Step 3 — weighted sum:**
```
copy_score = 100 × (
    0.22 × 0.370   = 0.0814
  + 0.22 × 1.000   = 0.2200
  + 0.20 × 0.985   = 0.1970
  + 0.18 × 0.978   = 0.1760
  + 0.18 × 0.545   = 0.0981
)
= 100 × 0.7725 = 77.3
```

**Tier:** `Elite Copy 💎` (score ≥70, profit=100≥50, feasible=97.8≥40, edge=54.5≥40)

> ⚠ Note: the `copy_formula` field in the raw JSON output contains the exact breakdown for every run. Hover the copy-tradeability card in the UI to see it.

## CU cost
- **First run (30d)**: ~30 CU
- **Replay from history**: 0 CU
- **With style badge**: same cost (0 extra CU)
