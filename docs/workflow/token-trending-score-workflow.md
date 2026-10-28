# `token-trending-score` — Public Workflow

A **0–100 momentum / trending score per interval** for one token, so short pumps and
sustained trends are separated. Two models: `classic` (momentum baseline) and `hybrid`
(adds the wallets / volume / pace interval formula).

## High-Level Concept

Momentum decides trending — volume and price carry ~55% of the composite weight, while
security and liquidity carry ~10% each. Security and liquidity also act as **continuous
gates**: a low value scales the score down smoothly rather than triggering a hard cliff, so
junk is filtered while momentum still decides the ranking. A **confirmed honeypot** is the
only hard stop. A score-independent `liquidity_health` label (`DYING` / `DEAD`) is reported
even when the trending score is still high.

- `classic` works on any token (momentum baseline).
- `hybrid` blends in the wallets / volume / pace "attention" formula on `1h` / `4h` / `24h`;
  other intervals fall back to `classic` and are marked `classic_fallback`.
- Depth is read from a **live snapshot** (`token_overview` + `POST /defi/v3/liquidity/latest/token`),
  never a stale OHLC close; an OHLC fallback is labelled with its `ohlc_age_seconds`.

## At a Glance

| Step | Endpoint | What it checks / produces | Mode | CU |
|---|---|---|---:|---:|
| 1 | `GET /defi/token_creation_info` | token age / creation context | always | 35 |
| 2 | `GET /defi/v3/ohlcv` | 1m candles (default 5000) for the price / volume / pace series | always | 25–100 |
| 3 | `GET /defi/v3/liquidity/ohlc/token` | liquidity drawdown series → stability + `liquidity_health` | always | 20 |
| 4 | `POST /defi/v3/liquidity/latest/token` | live **total + exit** liquidity snapshot | Solana | 5 |
| 5 | `GET /defi/token_overview` | price, market cap, liquidity, holder count, 24h volume | always | 21 |
| 6 | `GET /token/v1/holder/chart` | holder growth series — the Holder Dynamics component | always | 30 |
| 7 | `GET /token/v1/holder-profile` | cohort tags / holder health for Holder Dynamics | always | 21 |
| 8 | `GET /defi/token_security` | honeypot flag, mint / freeze, tax — the Security component + gate | always | 30 |
| 9 | — | classify intervals (`native` / `classic_fallback`), compute `raw × gate`, `is_risky`, `liquidity_health` | always | 0 |

Typical total **~176 CU**, up to **~262 CU** when the OHLCV window is large (Solana adds the
5 CU snapshot). `hybrid` adds **no** extra API calls — it only changes the scoring logic.

## Step by Step

### Step 1 — Creation info
`/defi/token_creation_info` gives the token's age / creation context, so a brand-new token is
read differently from an established one.

### Step 2 — OHLCV
`/defi/v3/ohlcv` supplies the 1m candle series (default 5000) that drives the price, volume
and pace inputs. CU scales with the candle count.

### Step 3 — Liquidity OHLC
`/defi/v3/liquidity/ohlc/token` gives the liquidity (and exit-liquidity) drawdown series used
for the stability term and the `liquidity_health` badge.

### Step 4 — Live liquidity snapshot (Solana)
`POST /defi/v3/liquidity/latest/token` returns current **total + exit** liquidity in one
cheap call, so the gate compares a live snapshot instead of a stale bar close.

### Steps 5–8 — Overview, holders, security
`token_overview` adds price / market cap / liquidity / holder count / 24h volume; the holder
chart and holder profile give the holder-growth and cohort-health signals; `token_security`
gives the honeypot flag, mint / freeze authority and tax used by the Security gate. All
feed the composite and the three gates.

### Step 9 — Compose
Each interval gets a `raw` score; the three gates combine into one multiplier; the final
score is `raw × gate`. Intervals where `hybrid` cannot apply the native formula are marked
`classic_fallback`. `is_risky` is `true` when the combined gate drops below `0.5`.

## Scoring (high level)

**Classic components and weights:**

| Component | Weight |
|---|---:|
| Volume growth | 0.30 |
| Swap activity | 0.15 |
| Price momentum | 0.25 |
| Liquidity health | 0.10 |
| Holder dynamics | 0.10 |
| Security | 0.10 |

```
raw   = Σ component_score × component_weight      # Σ weights = 1.00
gate  = 0.35·security_gate + 0.50·liquidity_gate + 0.15·holder_gate
final = raw × gate
```

- `security_gate` scales with the security score; a **honeypot collapses it to near zero**
  (the only hard stop).
- `liquidity_gate` and `holder_gate` ramp smoothly on effective depth (`min(liquidity, exit
  liquidity)` where reported) and holder count — a heavy-penalty band at very low depth, no
  hard cliff.
- `is_risky` when the combined gate < 0.5.

**Hybrid** keeps the classic score and blends a native "attention" score on the supported
intervals:

```
hybrid_raw(T) = 0.55 · native_score(T) + 0.45 · classic_raw(T)      # 1h / 4h / 24h
hybrid_final  = hybrid_raw × gate
```

The native formula rewards wallets, volume and short-vs-long pace, with the pace terms
disabled for tokens with too few 24h wallets. Unsupported intervals (`5m`, `15m`, `30m`,
`6h`, `12h`) fall back to `classic` and are labelled `classic_fallback`.

**Liquidity health** (independent of the score): `DEAD` when the pool drawdown is extreme or
either pool is below USD 10; `DYING` when the drawdown is very high; otherwise `LIQ_OK`.

## Output

- `plain`: per-interval score table + overall verdict, clean of HTML.
- `json` / `raw-json`: the full envelope — score, gate multipliers, per-interval rows,
  `liquidity_health`, `is_risky`.
- `telegram`: compact momentum summary.
- `ui`: per-interval score table + gate block + `liquidity_health` badge.

Read it in this order:

1. **Overall score + verdict** — the composite `0..100` from `raw × gate`.
2. **Per-interval rows** — each interval (`5m` … `24h`) with its score and status
   (`native` / `classic_fallback` on `hybrid`).
3. **Gates** — `security` / `liquidity` / `holder` multipliers and reasons; `is_risky`.
4. **`liquidity_health`** — independent of the score; `DYING` / `DEAD` can appear on a high
   trending score.
5. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

## Cost

| Block | CU |
|---|---:|
| Creation info (`/defi/token_creation_info`) | 35 |
| OHLCV 1m (`/defi/v3/ohlcv`) | 25–100 (by candle count) |
| Liquidity OHLC (`/defi/v3/liquidity/ohlc/token`) | 20 |
| Liquidity latest (`/defi/v3/liquidity/latest/token`) | 5 (Solana) |
| Token overview (`/defi/token_overview`) | 21 |
| Holder chart (`/token/v1/holder/chart`) | 30 |
| Holder profile (`/token/v1/holder-profile`) | 21 |
| Token security (`/defi/token_security`) | 30 |

Typical **~176**, up to **~262** at the largest OHLCV window. Replay from cache = 0 CU.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | `birdeye-cli config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
| `pipeline_gap` | a required upstream block was missing | the run is flagged instead of silently degraded |
