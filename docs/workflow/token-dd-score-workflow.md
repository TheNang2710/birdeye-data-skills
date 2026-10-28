# `token-dd-score` — Public Workflow

Due-diligence scorecard for one token: **five weighted pillars → a smooth
liquidity-drawdown gate → a 0–100 score and an A+..F risk rating**.

This is the public, high-level version. The exact sub-signal ramps and constants live
in the closed engine; this document describes the concept, the step order, the endpoint
behind each step, the pillar weights and how to read the output.

## High-Level Concept

Ask one question — *"should I trust this token?"* — and get one number plus a rating,
instead of a raw field dump. Five independent pillars are each scored 0–100, combined by
a weighted mean, then multiplied by a continuous gate that only reacts to liquidity
**deterioration** (not absolute depth, which the Liquidity pillar already scores).

- Missing sub-signals are **dropped together with their weight**, so a pillar score always
  reflects measured coverage — each pillar reports a `coverage` figure and a thin run is
  flagged with `coverage_caveat`.
- A **confirmed honeypot** is the only hard stop: Security → 0 and the whole run → `F`.
- Depth is read from a **live snapshot** (`token_overview` + `POST /defi/v3/liquidity/latest/token`),
  never a stale OHLC bar close; when the OHLC close is the only fallback it is labelled
  `… ago (OHLC close)`.
- A score-independent `liquidity_health` label (`DYING` / `DEAD`) is shown even when the
  score itself is still non-zero.

## At a Glance

`standard` stops after Step 2b; `advanced` runs every step.

| Step | Endpoint | What it checks / produces | Mode | CU |
|---|---|---|---:|---:|
| 1 | `GET /defi/token_overview?includes=money_flow` | price, market cap, liquidity, holder count, 24h volume, per-frame buy/sell flow — feeds **Activity** + **Liquidity** | both | 21 |
| 2 | `GET /defi/token_security` | honeypot flag, mint / freeze authority, metadata, LP lock, buy/sell tax, creator hold, top-10 concentration — the **Security** pillar | both | 30 |
| 2b | `POST /defi/v3/liquidity/latest/token` | live **total + exit** liquidity snapshot (Solana only) | both | 5 |
| 3 | `/holder/v1/distribution?mode=top` + `/token/v1/holder-profile` | holder concentration + cohort tags (dev / bundler / sniper / insider) — the **Holders** pillar | advanced | 60 |
| 4 | `/defi/v3/token/holder?mode=wallet` + `/defi/v3/token/money-flow` | top holders + smart-money / whales / KOL buy-sell flow — the **Smart Money** pillar | advanced | 40 |
| 5 | `GET /defi/v3/liquidity/ohlc/token` | 24h liquidity drawdown series (min / max / median / p95 / trend) for the gate | advanced | 30 |
| 6 | — | compose 5 pillars → weighted mean → × gate → rating + `liquidity_health` | both | 0 |

`standard` = 1 + 2 (+ 2b) = **56 CU** · `advanced` = **186 CU**.
Solana-only endpoints are skipped on other chains and their CU is refunded.

## Step by Step

### Step 1 — Token overview (one call, all frames)
One call returns the full trade-dynamic grid (1m, 5m, 15m, 30m, 1h, 2h, 4h, 24h). It
supplies price, market cap, liquidity, holder count, 24h volume, unique wallets, per-frame
volume / buy / sell and price-change percentages, plus the token-level `moneyFlow[]` block.
If no usable frame is returned the response is flagged `pipeline_gap`.

### Step 2 — Token security
The Security pillar. Checks: mint authority renounced?, freeze authority renounced?
(Solana), metadata mutable?, LP locked?, **can the creator actually dump?** (creator hold
combined with whether any transfer authority is still live), plus not-freezable /
not-LST / not-fake guards. A live `isHoneypot` forces Security = 0 and the run → `F`.

### Step 2b — Live liquidity snapshot (Solana)
`token_overview.liquidity` is a live snapshot but has no exit liquidity, and the OHLC
endpoint only publishes bar closes. This cheap call returns current **total + exit +
stable** liquidity in one shot so both modes get a same-instant snapshot. On non-Solana
chains it is skipped (no live exit figure) and the Liquidity depth uses total liquidity only.

### Step 3 — Holder concentration & cohorts (advanced)
Reads the top-holder distribution (`top1`, `top3`, `top10` share of supply) and the native
holder-profile cohorts (`dev`, `bundler`, `sniper`, `insider`, `smart_trader`, `kol`).
Computes the concentration penalties and a cohort-risk term (dev + sniper + bundler share)
and a sniper-density term. In `standard` mode only `top10HolderPercent` from Step 2 is
available, so top1/top3 and the cohort terms are dropped and re-normalised — **standard and
advanced holder scores are not directly comparable**.

### Step 4 — Activity (advanced)
Built entirely from Step 1 data (no extra call): real trading **engagement** (trades,
volume/liquidity, volume/market-cap turnover, unique wallets), a lighter **buy-pressure**
confirmation, a multi-frame **momentum** term (price / volume / wallet / liquidity change
across nested windows) and a **drawdown** term (give-back between nested windows + live 1h
sell-off). Bot / wash-trade data is not exposed by the API yet, so it is not scored.

### Step 5 — Liquidity risk (advanced)
Summarises the 24h liquidity OHLC window into stats (min / max / median / mean / σ /
drawdown / trend, for both total and exit liquidity). The **gate reads deterioration, not
depth**: it only discounts a pool that has fallen far from its recent peak, and the worst
of the two terms binds, so the total discount is capped and never double-penalises a
thin-but-stable pool. With no OHLC window (standard) the gate is neutral at 1.000.
Separately, `liquidity_health` labels a nearly-gone pool `DYING` / `DEAD` — independently
of the score.

### Step 6 — Smart money (advanced)
Three focus groups mapped onto the endpoints that exist: **smart traders**, **whales**,
**KOLs** — read from the money-flow grid (net USD, buy/sell tx counts, unique traders
across 5m / 1h / 4h / 24h) plus cohort supply and buy/sell history from Step 3 and top
holders from the wallet-mode holder call. Missing groups are dropped, not fabricated.
Smart Money is not measurable in `standard` mode, so that pillar is removed and the rest
re-normalise.

## Scoring (high level)

```
final = Σ (normalised pillar weight × pillar score)  ×  gate
gate  = 1 − max(liquidity_drawdown_penalty, exit_drawdown_penalty)   # ≤ 15% discount
```

**Pillar weights** (preset `default`): Security `0.23` · Holders `0.25` · Activity `0.20`
· Liquidity `0.22` · Smart Money `0.10`. On Solana a fixed shift is applied
(Security −0.06, Holders +0.03, Liquidity +0.03). Presets `strict-liquidity` and
`security-first` are available, and `--weights` can override individual pillars (the set
then re-normalises to 1.0).

**Inside the pillars** (what each is built from):

| Pillar | Sub-signals |
|---|---|
| Security | mint authority · freeze authority · metadata · LP lock · creator-dump power · not-freezable · not-LST · not-fake |
| Holders | top1 concentration · top3 · top10 · holder base size · cohort risk (dev+sniper+bundler) · sniper density |
| Activity | engagement (0.40) · momentum (0.30) · drawdown (0.20) · buy pressure (0.10) · pace (opt-in, `--pace`) |
| Liquidity | depth (0.30) · stability (0.25) · valuation (0.20) · trend (0.15) · pairs (0.10) |
| Smart Money | sm presence (0.25) · sm flow (0.30) · sm quality (0.20) · whale (0.15) · kol (0.10) |

**Rating bands** (risk labels only — never buy/sell advice):

| Rating | Score | Verdict |
|---|---|---|
| A+ | ≥ 95 | HOT |
| A | ≥ 85 | STRONG |
| B+ | ≥ 80 | OK |
| B | ≥ 70 | FAIR |
| C+ | ≥ 65 | WATCH |
| C | ≥ 55 | CAUTION |
| D | ≥ 40 | RISKY |
| E | 20 – <40 | HIGH RISK |
| F | < 20 | CRITICAL |

## Output

All four text formats are Telegram-pasteable; `json` / `plain` are HTML-free.

Read it in this order:

1. **Score + rating** — the `0..100` value and the A+..F band.
2. **Pillar table** — five rows, each with its own score and a **coverage** figure; a thin
   pillar shows lower coverage and may carry `⚠ coverage_caveat`.
3. **`liquidity_health`** — `LIQ_OK` / `DYING` / `DEAD`, independent of the score.
4. **Deductions** — each names the field behind it, so any low score is traceable.
5. **`weights_used` / `pillar_points`** — the normalised weights and each pillar's point
   contribution, so the arithmetic is auditable.
6. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

## Cost

| Mode | Blocks | CU |
|---|---|---:|
| `standard` | overview + security + live snapshot | **56** |
| `advanced` | + holder distribution/profile + top holders + money flow + liquidity OHLC | **186** |
| `--rescore <run-id>` | replay stored inputs locally | **0** |

`--rescore` replays the stored endpoint inputs and re-runs the scoring locally, so you can
switch preset, widen `--top-n` or toggle `--pace` without paying for the data twice.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | `birdeye-cli config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
| `pipeline_gap` | a required upstream block was missing | the run is flagged instead of silently degraded |
