# Skill #22 · Token Trending Score

## High-Level Concept

Computes a **0–100 trending score** for a single token across five intervals
(**1m, 5m, 1h, 4h, 24h** — aligned to Birdeye's available overview windows,
inspired by GMGN's 1m/5m/1h/6h/24h trending structure).

The score blends **six weighted components** — volume growth, swap activity,
price momentum, liquidity health, holder dynamics, and security — into one
composite per interval. An **overall** score is the mean of the five interval
scores.

The core innovation is the **Growth Score formula** with a **median baseline**:
instead of comparing the last candle to the previous candle (noisy, few-candle
momentum), each component compares the **current window value** against the
**median of historical same-length windows**. This gives robust, statistically
meaningful momentum that isn't dominated by a single outlier candle.

Security acts as a **hard floor**: risky/scam tokens (security < 40) have
their composite multiplied by `0.1`, so they can never score high regardless of
volume or price momentum. This prevents pump-and-dump or honeypot tokens from
appearing trending.

All raw Birdeye data is **cached to CSV** (OHLCV 1m, liquidity 1m, security,
and momentum snapshots) for later backtesting and ML weight-tuning.

---

## Growth Score Formula (Core)

For any metric `X` (volume, swaps, unique wallets):

```
G_X = (X_current + ε) / (Baseline_X + ε)
GrowthScore_X = min(100, 100 × ln(1 + G_X) / ln(16))
```

Where `ε = 1e-8` prevents division by zero.

**Mapping curve:**

| G (current / baseline) | Growth Score | Meaning |
|------------------------|-------------|---------|
| 0.5 (half)             | ~14.6       | Declining |
| 1.0 (no change)        | 25.0        | Neutral |
| 2.0 (doubled)          | ~39.6       | Growing |
| 4.0 (4×)               | ~58.0       | Strong growth |
| 8.0 (8×)               | ~79.2       | Hot |
| 15.0+ (15×)            | 100         | Explosive |

### Baseline = Median of Historical Windows

For each interval `T`, the baseline is the **median** of the same metric across
historical snapshots within a lookback window:

| Interval | Baseline lookback | # of windows needed |
|----------|-------------------|---------------------|
| 1m       | last 1 hour       | ~60 × 1m snapshots  |
| 5m       | last 4 hours      | ~48 × 5m snapshots  |
| 1h       | last 24 hours     | ~24 × 1h snapshots  |
| 4h       | last 72 hours     | ~18 × 4h snapshots  |
| 24h      | last 7 days       | ~7 × 24h snapshots  |

If fewer than 3 snapshots are available (e.g., new token), the baseline falls
back to Birdeye's `*History*` field — the immediately preceding window of the
same length (e.g., `vHistory5mUSD` for the 5m interval).

---

## Components & Weights

| Component | Weight | Sub-factors |
|-----------|--------|-------------|
| **Volume Growth** | 20% | Growth Score of `v{iv}USD` vs baseline |
| **Swap Activity** | 15% | Growth Score of `trade{iv}` vs baseline |
| **Price Momentum** | 20% | `priceChange{iv}%` → growth-style norm |
| **Liquidity Health** | 15% | liq/mcap ratio (70%) + 1h stability (30%) |
| **Holder Dynamics** | 15% | holder count sufficiency log (60%) + unique wallet growth (40%) |
| **Security** | 15% | penalty model; honeypot → hard floor 0 |

### 1. Volume Growth (20%)
- **Current**: `v1mUSD`, `v5mUSD`, `v1hUSD`, `v4hUSD`, `v24hUSD` from `token_overview`
- **Baseline**: median of same field across snapshots, or `vHistory{iv}USD`
- **Score**: `growth_score(current, baseline)`

### 2. Swap Activity (15%)
- **Current**: `trade{iv}` (number of swaps in window)
- **Baseline**: median of `trade{iv}` across snapshots, or `tradeHistory{iv}`
- **Score**: `growth_score(current, baseline)`

### 3. Price Momentum (20%)
- **Input**: `priceChange{iv}Percent` directly from `token_overview`
- **Score**: `growth_score_from_pct(change_pct)` — same ln curve, so +100% → 39.6, +300% → 58.0

### 4. Liquidity Health (15%)
- **liq/mcap ratio** (70%): `liquidity / marketCap`. 0.10+ → 100, 0.05 → 70, 0.02 → 40
- **stability** (30%): inverse of 1h liquidity drawdown. 0% dd → 100, 50%+ dd → 0

### 5. Holder Dynamics (15%)
- **sufficiency** (60%): `log10(holder_count) / log10(1M) × 100`. 10 → 16, 1K → 50, 100K → 83, 1M → 100
- **growth** (40%): `uniqueWallet{iv}ChangePercent` → growth-style normalization

### 6. Security (15%)
- Start at 100. **Honeypot → 0** (hard floor).
- Penalties: mint active −30, freeze active −25, LP unlocked −25, top10 > 60% −20, sell tax > 10% −20.
- **Risk gate**: security < 40 → `final = raw × 0.1`

---

## API Calls & CU

| Step | Endpoint | CU | Cached as |
|------|----------|----|-----------|
| Creation time | `/defi/token_creation_info` | 35 | — (per run) |
| OHLCV 1m (from creation, capped 5000) | `/defi/v3/ohlcv` | 25–100 | `ohlcv_1m.csv` (24h) |
| Liquidity 1m (from creation) | `/defi/v3/liquidity/history/token` | 20 | `liquidity_1m.csv` (24h) |
| Token overview + money_flow | `/defi/token_overview` | 21 | — (per run) |
| Token security | `/defi/token_security` | 30 | `security.csv` (7d) |
| **Total (worst case)** | | **~206** | |

---

## Data Collection for Baseline

The `collect_momentum_data.py` script builds the snapshot history needed for
median baselines:

```bash
# Collect from 20 new-listing tokens, poll every 1s for 1h
python3 collect_momentum_data.py --chain sol --source new_listing --limit 20 --duration 3600 --interval 1

# Collect from 20 trending tokens
python3 collect_momentum_data.py --chain sol --source trending --limit 20 --duration 3600

# Collect specific addresses
python3 collect_momentum_data.py --chain sol --source addresses --addresses ADDR1,ADDR2 --duration 3600
```

**Workflow per token:**
1. Fetch `token_creation_info` once → `blockUnixTime`
2. Fetch `token_security` once → cached 7 days
3. Poll `token_overview` every `--interval` seconds for up to `--duration`
4. Save each snapshot to `momentum_snapshots/{chain}_{addr}_snapshots.csv`
5. Stop early if no data change for `--no-change-stop` seconds (default 600s = 10 min)

Each snapshot row contains: timestamp, price, marketCap, liquidity, holder,
v{1m,5m,1h,4h,24h}USD, trade{iv}, buy/sell{iv}, uniqueWallet{iv},
priceChange{iv}%, plus all *History* fields.

---

## Step-by-Step Calculation Example: SOL

Token: SOL (`So1111...1112`), chain: solana

### Inputs
- marketCap = $63.5B, liquidity = $6.4B, holder = 8.67M
- v5mUSD = $17.4M, vHistory5mUSD = $15.2M
- trade5m = 139,187, tradeHistory5m = 144,332
- priceChange5mPercent = -0.15%
- Security = 100 (clean, no penalties)

### 5m Interval Calculation

**Volume Growth:**
- G = (17.4M + ε) / (15.2M + ε) ≈ 1.145
- Score = 100 × ln(1 + 1.145) / ln(16) = 100 × ln(2.145) / 2.773 ≈ 100 × 0.763 / 2.773 ≈ 27.5

**Swap Activity:**
- G = 139,187 / 144,332 ≈ 0.964
- Score = 100 × ln(1.964) / 2.773 ≈ 100 × 0.675 / 2.773 ≈ 24.3

**Price Momentum:**
- change = -0.15% → G = 1 + (-0.15/100) = 0.9985
- Score = 100 × ln(1.9985) / 2.773 ≈ 24.9

**Liquidity Health:**
- ratio = 6.4B / 63.5B ≈ 0.10 → ratio_score = 100
- 1h drawdown ≈ 2% → stability = 100 - 2×2 = 96
- Score = 100 × 0.70 + 96 × 0.30 = 98.8

**Holder Dynamics:**
- sufficiency = log10(8.67M) / log10(1M) × 100 ≈ 99.4
- uniqueWallet5m change ≈ -9.6% → growth_score ≈ 22.8
- Score = 99.4 × 0.60 + 22.8 × 0.40 ≈ 68.8

**Security:** 100

**Composite (5m):**
- raw = 27.5×0.20 + 24.3×0.15 + 24.9×0.20 + 98.8×0.15 + 68.8×0.15 + 100×0.15
- raw = 5.5 + 3.6 + 5.0 + 14.8 + 10.3 + 15.0 = 54.2
- security ≥ 40 → no cap
- **5m score = 54.2**

### All Intervals (actual run)

| Interval | Score | Vol | Swap | Price | Liq | Hold | Sec |
|----------|-------|-----|------|-------|-----|------|-----|
| 1m       | 53.0  | 22  | 22   | 25    | 100 | 69   | 100 |
| 5m       | 53.2  | 20  | 23   | 25    | 100 | 71   | 100 |
| 1h       | 54.0  | 24  | 24   | 25    | 100 | 71   | 100 |
| 4h       | 55.1  | 27  | 27   | 25    | 100 | 72   | 100 |
| 24h      | 54.7  | 27  | 25   | 24    | 100 | 70   | 100 |

**Overall: 54.0/100** — SOL is a stable large-cap with low short-term momentum
growth (volume ≈ baseline), so it scores mid-range despite perfect liquidity
and security. This is correct behavior: a trending score should reward
**growth above baseline**, not just large absolute size.

---

## CSV Cache Structure

```
~/.cache/birdeye-trending-csv/
├── {chain}_{addr}_ohlcv_1m.csv          # 1m OHLCV candles
├── {chain}_{addr}_liquidity_1m.csv      # 1m liquidity USD
├── {chain}_{addr}_security.csv          # security fields (7d cache)
└── momentum_snapshots/
    └── {chain}_{addr}_snapshots.csv     # time-series overview snapshots
```

---

## Future ML Tuning

The weights in `DEFAULT_WEIGHTS` are initial baselines. For tuning:
1. Run `collect_momentum_data.py` across many tokens (new_listing + trending)
2. Label outcomes (e.g., did price go up 2× in next 24h? did it rug?)
3. Train a model to predict labels from the 6 component sub-scores
4. Derive optimal weights via logistic regression / gradient boosting
5. Override `DEFAULT_WEIGHTS` or pass `weights=` param to `compute_trending_score`
