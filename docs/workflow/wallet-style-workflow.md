# `wallet-style` — Public Workflow

Tag **how** a wallet trades — a **20-cell frequency × P&L grid** plus a speed subtitle and
risk badges (scaling, gas). Answers *scalper or swing trader?* rather than *is it profitable?*

## High-Level Concept

The wallet is placed on a 4×5 grid: the **frequency axis** (trades/day) crossed with the
**P&L axis** (profit quality). That cell gives the style badge. The trade history adds a
**speed subtitle** (median hold time) and context badges, and the first-funded lookup (wallet
age) is reused from cache.

## At a Glance

| Step | Endpoint | What it checks / produces | Mode | CU |
|---|---|---|---:|---:|
| 1 | `GET /wallet/v2/pnl/summary` | realized PnL, trade count and volume over `--duration` → the frequency and P&L axis values | always | 30 |
| 2 | `POST /wallet/v2/pnl/details` | per-token PnL breakdown for the P&L axis quality | always | 30 |
| 3 | `GET /v1/wallet/tx_list` | trade history → median hold (speed subtitle), scaling in/out and gas badges | unless `--skip-tx-list` | ~30 |
| 4 | `POST /wallet/v2/tx/first-funded` | wallet age / funding provenance | unless `--skip-first-tx` | cached → 0 |
| 5 | — | place the wallet on the 4×5 grid → badge + speed subtitle | always | 0 |

~90 CU: PnL summary 30 + details 30 + tx_list ~30; first-funded cached = 0.

## Step by Step

### Step 1 — PnL summary
`/wallet/v2/pnl/summary` gives trade count and volume (→ **frequency**) and realized PnL
(→ **P&L quality**) for the chosen window (`7d` or `30d`).

### Step 2 — PnL details
`/wallet/v2/pnl/details` gives the per-token breakdown used to judge the *quality* of the
P&L — steady grind versus one lucky token.

### Step 3 — Trade history
`/v1/wallet/tx_list` supplies the median hold time (the **speed subtitle**: scalp / swing /
hold) and the badges for scaling in/out and gas behaviour. `--skip-tx-list` removes this
block (−~30 CU) and the subtitle/badges with it.

### Step 4 — First-funded (wallet age)
`/wallet/v2/tx/first-funded` resolves wallet age. Cached, so it is free on repeat runs.

### Step 5 — Place on the grid
The frequency level (`L1 Rare` … `L4 Machine`) and P&L level (`P1 Heavy Loss` … `P5 Strong
Profit`) select one of 20 style badges, and a thin-sample guard adds a context badge when
the trade count is too low to be confident.

## Scoring (high level)

No composite score — the output is a **style cell**:

- **Frequency axis** (trades/day): `L1 Rare` · `L2 Regular` · `L3 Frequent` · `L4 Machine`.
- **P&L axis**: `P5 Strong Profit` · `P4 Net Profit` · `P3 Break-Even` · `P2 Net Loss` ·
  `P1 Heavy Loss`.
- **Badge** = the emoji + name of the resulting cell (e.g. `Old Hunter`, `Money Printer`).
- **Speed subtitle** = median hold time (present only when the tx list was fetched).
- **Context badges** e.g. `Thin Sample` when the trade count is low.

## Output

- `plain`: badge + axes + speed subtitle in a compact block.
- `json` / `raw-json`: the full envelope — grid cell, axis levels, subtitle, badges.
- `telegram`: compact badge summary.
- `ui`: main badge + frequency/P&L axes + context badges.

Read it in this order:

1. **Main badge** — emoji + style name from the grid cell.
2. **Frequency axis** — `L1` … `L4`.
3. **P&L axis** — `P5` … `P1`.
4. **Speed subtitle** — median hold time (tx list required).
5. **Context badges** — thin-sample and similar caveats.
6. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

## Cost

| Run | CU |
|---|---:|
| Full run (`30d`) | **~90** |
| `--skip-tx-list` | −~30 (grid only, no speed subtitle / badges) |
| First-funded cache hit | step 4 = 0 |
| Replay from history / cache | 0 |

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | `birdeye-cli config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
