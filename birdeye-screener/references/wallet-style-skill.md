# Skill #11 · Wallet Style — GMGN wallet-style ported to Birdeye API

## 1. High-Level Concept

`wallet-style` classifies **how** a wallet trades — not whether it is profitable (Skill #13 Wallet Score does that), but the *shape* of its behavior. It answers: *"Is this wallet a sniper, a swing trader, a hoarder, a whale, or a losing chaser?"*

The classification is a **2-axis grid**:

| Axis | Levels | Meaning |
|------|--------|---------|
| **Frequency** (L1–L4) | how often the wallet trades per day | L1 rarely trades, L4 bots/scalpers |
| **P&L** (P1–P5) | quality of realized returns | P1 losing, P5 elite compounder |

Every wallet lands in **one of 20 cells** (L1×P1 … L4×P5). Each cell has a name, emoji, and a one-line meaning. On top of the grid we add:

- **Speed subtitle** — median holding window (flash / intraday / swing / long hold)
- **Badges** — orthogonal traits that all fire independently (lottery, scale-in, whale, hoarder, new wallet, …)

This is a direct port of GMGN's `gmgn-wallet-style` skill, re-mapped from GMGN's portfolio/activity endpoints to Birdeye's PnL + tx_list endpoints.

---

## 2. API Calls & CU Budget

| Step | Endpoint | CU | Cached? | What it gives |
|------|----------|----|---------|---------------|
| 1 | `GET /wallet/v2/pnl/summary` | 30 | no | counts (buy/sell/tokens), win_rate, realized/unrealized PnL $, total invested |
| 2 | `POST /wallet/v2/pnl/details` | 30 | no | per-token `realized_profit_percent` → bucket into 5x/2x/0x/-5%/<-5% |
| 3 | `GET /v1/wallet/tx_list` | ~30 | no (optional) | buy/sell timing → speed subtitle + scale/hoard badges |
| 4 | `POST /wallet/v2/tx/first-funded` | 40 | **yes (permanent)** | wallet first-funding block time → wallet age in days |

**Total CU:** 90 default · 60 with `--skip-tx-list` · 30 with both skips · **first-funded is always 0 on repeat runs** (immutable metadata → permanent CSV cache shared with Skill #13).

### Why first-funded is cached
Wallet first-funding time never changes. We store the raw response in `wallet_first_funded_cache.csv` keyed by `(wallet, chain)`. A cache hit skips the 40 CU call entirely. The same CSV is read by Skill #13 Wallet Score, so running both skills on the same wallet pays first-funded only once ever.

---

## 3. Step-by-Step for One Wallet

Given `wallet = 8vcR9ZzrGk…` on `solana`, `duration = 30d`:

### Step 1 — Fetch summary (30 CU)
`GET /wallet/v2/pnl/summary?wallet=…&duration=30d&pnl_method=wac`

Extract:
```
counts.total_buy       = 239
counts.total_sell      = 239
counts.unique_tokens   = 3
counts.win_rate        = 0.333
pnl.realized_profit_usd   = 335,500
pnl.unrealized_pnl_usd    = -69,533
cashflow.total_invested   = 390,645
```

### Step 2 — Fetch per-token details (30 CU)
`POST /wallet/v2/pnl/details` body `{wallet, duration, pnl_method}`

For each token read `realized_profit_percent` and bucket:
- `gt_5x`   : percent ≥ 400  (i.e. ≥5×)
- `2x_5x`   : 100 ≤ percent < 400
- `0x_2x`   : 0 ≤ percent < 100
- `nd5_0x`  : -5 ≤ percent < 0
- `lt_nd5`  : percent < -5

Result: `{gt_5x:1, 2x_5x:0, 0x_2x:1, nd5_0x:0, lt_nd5:2}`

### Step 3 — Fetch tx_list (30 CU, optional via `--skip-tx-list`)
`GET /v1/wallet/tx_list?wallet=…&limit=100`

Parse `data[chain][].balanceChange[]`:
- **buy** = a token amount > 0 AND native (SOL) amount < 0
- **sell** = a token amount < 0 AND native amount > 0

Group trades by token. For each token compute the **copy window** = `first_sell_ts - first_buy_ts`. Take the median across tokens (needs ≥3 samples).

### Step 4 — Fetch first-funded (cached → 0 CU)
Look up `wallet_first_funded_cache.csv`. If miss, call `POST /wallet/v2/tx/first-funded` (40 CU) and cache the raw response.

Extract `data[wallet].block_unix_time` → `wallet_age_days = (now - block_unix_time) / 86400`.

---

## 4. Computation & Formulas

### 4.1 Frequency level
```
per_day = (total_buy + total_sell) / duration_days

L1  if per_day < 1        ("Rare")
L2  if 1 ≤ per_day < 10   ("Regular")
L3  if 10 ≤ per_day < 50  ("Frequent")
L4  if per_day ≥ 50        ("Machine")
```
*(GMGN uses `token_num` for sample sufficiency, but `token_num` ignores `--period` — we use `buy+sell` instead, which honors the window.)*

### 4.2 P&L level
First compute:
```
pnl_ratio   = realized_profit_usd / total_invested_usd     # GMGN's realized_profit_pnl
lt50_share  = lt_nd5_count / total_token_count              # share of tokens losing >5%
realized_usd = realized_profit_usd
```

Then test **in order, stop at first match**:

| Level | Condition | Meaning |
|-------|-----------|---------|
| **P5** | `pnl_ratio > 0.5` AND `unique_tokens ≥ 5` AND (`win_rate ≥ 0.5` OR `lt50_share < 0.15`) | Elite compounder — big returns + enough tokens to prove it's not luck |
| **P4** | `pnl_ratio > 0.1` | Net winner |
| **P1** | `lt50_share ≥ 0.40` AND `realized_usd < 0` | Heavy loser — most tokens deep red |
| **P3** | `abs(pnl_ratio) ≤ 0.10` | Break-even / choppy |
| **P2** | `realized_usd < 0` OR `pnl_ratio < 0` | Net loser (catch-all) |

> **Always print the absolute `realized_profit_usd` next to the title** — a high-frequency wallet can have a big $ win but a small ratio, or vice versa. The ratio alone is misleading.

### 4.3 Speed subtitle (needs tx_list, ≥3 tokens)
```
copy_window[i] = first_sell_ts[token_i] - first_buy_ts[token_i]
median_seconds = median(copy_window)

flash     if median < 60s      ("Flash Flipper")
intraday  if median < 24h      ("Intraday")
swing     if median < 7d       ("Swing")
long hold if median ≥ 7d       ("Long Hold")
```
*(GMGN's `avg_holding_period` is unreliable — up to 22,000× inflated. We always compute from raw tx timing instead.)*

### 4.4 Badges (orthogonal — all that trigger fire)

| Badge | Condition |
|-------|-----------|
| 🎰 Lottery | `win_rate < 0.35` AND `gt_5x ≥ 1` — low WR but hit a moonshot |
| 📈 Scale-in | avg buys per token ≥ 3 (from tx_list) |
| 📉 Scale-out | avg sells per token ≥ 3 |
| 🐹 Hoarding | max(buy_count, sell_count) per token ≥ 3 |
| 📦 Distributing | sells ≥ 3 across distinct tokens |
| 🐋 Whale | avg buy value ≥ $10,000 |
| 🆕 New wallet | `wallet_age_days < 30` |
| ⚠️ Insufficient sample | `total_trade < 20` — grid may be noisy |

---

## 5. 4×5 Style Grid (L1–L4 × P1–P5)

The final cell is `(freq_level, pnl_level)`. The 20-cell map defines `(emoji, name, meaning)` — e.g.:

- **L3 × P4** = ⚔️ *Active Winner* — "Busy hands that actually keep the money"
- **L4 × P1** = 💥 *Self-Destruct* — "Machine-speed frequency plus broad heavy losses"
- **L1 × P5** = 🗡️ *One-Shot* — "Almost never trades, and lands it when it does"

The rendered UI highlights the active cell and dims the others.

---

## 6. Classification Workflow (full pipeline)

```
1. summary (30 CU)        → counts, realized PnL, invested, win_rate
2. details (30 CU)        → per-token realized% → 5 P&L buckets
3. [optional] tx_list (30 CU) → buy/sell timing → speed + scale badges
4. first-funded (cached=0)→ wallet_age_days
5. compute:
   per_day      = (buy+sell)/days          → L1..L4
   pnl_ratio    = realized/invested
   pnl_level    = P5→P4→P1→P3→P2 (first match)
   speed        = median(first_sell - first_buy) per token
   badges       = all orthogonal triggers
6. cell = (L?, P?) → look up name/emoji/meaning
7. render: UI card (4×5 grid + metrics + badges) | plain | telegram | raw-json
8. cache full payload as kind=wallet-style-v1 (re-render = 0 CU)
```

---

## 7. CLI Usage

```bash
# Full (90 CU first run, 60 CU repeat thanks to first-funded cache)
python3 birdeye-screener/scripts/birdeye_cli.py wallet-style \
  --chain sol --wallet <ADDR> --duration 30d --pnl-method wac --format rendered

# Fast, no speed badge (60 CU)
... wallet-style --chain sol --wallet <ADDR> --duration 7d --skip-tx-list --format rendered

# Minimal (30 CU)
... wallet-style --chain sol --wallet <ADDR> --duration 30d --skip-tx-list --skip-first-tx --format telegram

# 0 CU replay from cache
python3 birdeye-screener/scripts/birdeye_cli.py history-render --run-id <RUN_ID> --format render
```

### Args
- `--chain`: sol / bsc / base / eth / arc
- `--wallet`: address
- `--duration`: 7d | 30d (matches GMGN)
- `--pnl-method`: wac (default) | net_cash
- `--skip-tx-list`: skip tx_list → no speed/scale badges, save 30 CU
- `--skip-first-tx`: skip first-funded → wallet age N/A, save 40 CU (only matters if not cached)
- `--format`: rendered | plain | telegram | raw-json
