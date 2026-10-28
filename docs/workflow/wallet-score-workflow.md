# `wallet-score` — Public Workflow

Score a wallet's trading skill: a **0–100 alpha score** across four weighted components,
plus a **copy-tradeability score** that answers *"if I copy this wallet, will I make money
and can I realistically follow it?"*.

## High-Level Concept

Four components — **Profitability P40 / Consistency C25 / Quality Q20 / Activity A15** —
combined into one alpha score and a tier. Hard filters (`tx ≥ 20`, `volume ≥ USD 5k`,
`rug% ≤ 50%`) short-circuit obviously thin wallets before the full spend. A separate
copy-tradeability model rates whether the wallet's trades are actually reproducible.

- Wallet age / funding provenance is cached permanently, so a repeat run costs **0 CU** for
  that block.
- The PnL method is selectable: weighted-average cost (`wac`) or cashflow difference
  (`net_cash`).
- Every fetch block can be skipped (`--skip-rug` / `--skip-portfolio` / `--skip-first-tx`)
  to trim CU.

## At a Glance

| Step | Endpoint | What it checks / produces | Mode | CU |
|---|---|---|---:|---:|
| 1 | `GET /wallet/v2/pnl/summary` | realized + total PnL, ROI, trade count, volume, win-rate over `--duration` | always | 30 |
| 1b | `GET /wallet/v2/pnl/summary` (24h, 90d) | short-term + 60-day trend windows for **Consistency** | full mode | 30 each |
| 1c | — | hard filter `tx ≥ 20`, `volume ≥ USD 5k` → early exit if it fails | always | 0 |
| 2 | `POST /wallet/v2/pnl/details` | per-token PnL, profit concentration and deep-loss / rug proxy — **Quality** | unless `--skip-rug` | 30 |
| 3 | `POST /wallet/v2/tx/first-funded` | wallet age / funding provenance — **Activity** | unless `--skip-first-tx` | ~40 (cached → 0) |
| 4 | `GET /wallet/v2/current-net-worth` | current portfolio holdings — **Activity** | unless `--skip-portfolio` | 30 |
| 5 | — | compose P40/C25/Q20/A15 → alpha score + tier, then the 5-factor copy-tradeability score | always | 0 |

Early fail after Step 1 = **30 CU**; full pipeline worst-case **~110 CU**.

## Step by Step

### Step 1 — PnL summary
`/wallet/v2/pnl/summary` returns the core PnL overview for the chosen window: realized and
total PnL, ROI, trade count, invested/sold volume and win-rate. This feeds **Profitability**
and, blended with the 24h and 90d windows, **Consistency** (is the edge stable across
windows or a one-off?).

### Step 2 — Per-token PnL / deep-loss
`/wallet/v2/pnl/details` gives the per-token breakdown used for **Quality**: how concentrated
the profit is in a few tokens, the realization ratio, and deep-loss (rug-like) tokens.
`--skip-rug` forces the rug fraction to 0 and leans on the realization ratio only.

### Step 3 — First-funded (wallet age)
`/wallet/v2/tx/first-funded` resolves the wallet's age and funding provenance. Because this
never changes, the result is stored in a **permanent** cache: the first run pays ~40 CU, every
later run pays 0.

### Step 4 — Portfolio V2
`/wallet/v2/current-net-worth` returns current holdings. Together with wallet age this gives
**Activity** a sense of whether the wallet is active and current, not dormant.

### Step 5 — Compose
The four components combine into the alpha score and tier; a second 5-factor model
(`entry`, `profit`, `hold`, `feasible`, `edge`) produces the copy-tradeability score and its
tier. The exact per-factor arithmetic is exposed in the `copy_formula` field of the `json`
output.

## Scoring (high level)

```
alpha = 0.40 × Profitability + 0.25 × Consistency + 0.20 × Quality + 0.15 × Activity
```

- **Profitability** — realized/total PnL vs ROI, blended against fixed ROI thresholds.
- **Consistency** — stability of the edge across the 24h / duration / 90d windows.
- **Quality** — profit concentration, realization ratio, deep-loss exposure.
- **Activity** — wallet age, current portfolio, trade liveliness.

**Copy-tradeability** (0–100) is a weighted mean of `entry` (0.22) · `profit` (0.22) ·
`hold` (0.20) · `feasible` (0.18) · `edge` (0.18) — i.e. can you enter at a similar price,
does each trade pay enough, is the hold long enough to follow, are there too many trades,
and is the edge sustainable.

## Output

- `plain`: terminal scorecard — alpha score, tier, the four component scores, copy-trade tier.
- `compact`: a trimmed `blocks` object (`--include` picks which blocks).
- `json` / `raw-json`: the full envelope including the `copy_formula` breakdown.
- `telegram`: compact score summary.
- `ui`: arc gauge + component cards + copy-tradeability card.

Read it in this order:

1. **Alpha score + tier** — `0..100` and the tier.
2. **Four components** — Profitability · Consistency · Quality · Activity, each `0..100`.
3. **Copy-tradeability score + tier** — `copy_formula` in `json` shows every factor.
4. **Skips** — any `--skip-*` block reports `0` CU and is marked skipped.
5. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

Early-exit runs return the filter that failed instead of a score.

## Cost

| Run | CU |
|---|---:|
| Early hard-filter fail (tx < 20 or volume < USD 5k) | **30** |
| Full pipeline (worst case) | **~110** |
| `--skip-*` flags | trim the matching step to 0 |
| First-funded re-run (cache hit) | step 3 = 0 |
| `--include-style` | +0 |
| Replay from history / cache | 0 |

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | `birdeye-cli config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
