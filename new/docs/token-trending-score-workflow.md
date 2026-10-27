# Skill #22 · Token Trending Score

## High-Level Concept

Computes a **0–100 trending score** for a single token across multiple intervals.
The module now supports **two internal models**:

| Model | Purpose | Core idea |
|---|---|---|
| `classic` | Stable baseline | Original 6-component momentum model |
| `hybrid` | Revised trend attention | Blend `classic` with a wallets / volume / pace formula on overview intervals |

`classic` remains the backward-compatible model. `hybrid` keeps the old model's
quality and risk context, but adds a stronger "what is hot right now" signal on
`1h`, `4h`, and `24h`.

---

## Classic Model

The original model blends six components into one composite per interval.
Weights are **momentum-heavy** — volume and price carry 55%:

| Component | Weight | Notes |
|---|---:|---|
| Volume Growth | 30% | `v{iv}USD` vs median baseline or history fallback |
| Swap Activity | 15% | `trade{iv}` vs median baseline or history fallback |
| Price Momentum | 25% | regression on candle closes, or `priceChange{iv}Percent` fallback |
| Liquidity Health | 10% | liquidity / mcap + recent stability |
| Holder Dynamics | 10% | holder growth + holder profile health + sufficiency |
| Security | 10% | contract risk penalties |

Security, liquidity and holder breadth keep a small share of the composite
**and** act as continuous gates (see *Junk Gates* below), so junk is filtered
while momentum still decides the ranking. All gates are piecewise-linear, so a
small data change never flips the verdict between two arbitrary values.

```text
raw   = Σ component_score × component_weight      # Σ weights = 1.00
gate  = 0.35·security_gate(security_score)
      + 0.50·liquidity_gate(effective_liquidity)
      + 0.15·holder_gate(holder_count)
final = raw × gate
```

This model works well as a **quality-aware momentum score**, but it can underweight
absolute attention spikes in wallets and volume.

---

## Hybrid Model

`hybrid` starts from `classic` and then blends in an interval-native "attention"
formula where Birdeye overview windows are strongest.

### Native Formula

Supported intervals:

- `1h`
- `4h`
- `24h`

For each supported interval `T`:

```text
native_raw(T) =
    1.00 * log10(1 + wallets_T)
  + 0.50 * log10(1 + volume_T_usd)
  + 0.25 * pace_now_wallets(T)
  + 0.25 * pace_window_volume(T)
  + 0.25 * tanh(price_change_T_pct / 25)
```

The raw formula is then normalized onto 0–100 with a smooth tanh curve.

### Pace Terms

Both pace terms are clipped to `0.25x .. 4x` before taking `log2`.

| Interval | `pace_now_wallets(T)` | `pace_window_volume(T)` |
|---|---|---|
| `1h` | `log2(clip(wallet_5m * 6 / wallet_30m))` | `log2(clip(volume_30m * 2 / volume_1h))` |
| `4h` | `log2(clip(wallet_30m * 4 / wallet_2h))` | `log2(clip(volume_2h * 2 / volume_4h))` |
| `24h` | `log2(clip(wallet_1h * 4 / wallet_4h))` | `log2(clip(volume_4h * 6 / volume_24h))` |

The pace terms are disabled when `wallet_24h < 50`, so tiny/new tokens do not
look permanently "accelerating".

### Blend

For supported intervals:

```text
hybrid_raw(T) = 0.55 * native_score(T) + 0.45 * classic_raw(T)
hybrid_final(T) = hybrid_raw(T) * gate
```

For unsupported intervals (`5m`, `15m`, `30m`, `6h`, `12h`), `hybrid` falls back
to the `classic` interval score and marks the interval as `classic_fallback`.

This gives us:

- the **responsiveness** of the new interval formula
- the **stability** of the old regression/baseline model
- the **risk brake** from the three continuous junk gates

---

## Junk Gates

Security, liquidity and holder breadth are deliberately **not** hard triggers.
Each maps to a `0..1` gate, and the three combine into one weighted multiplier
that scales the momentum score:

```text
gate = 0.35·security_gate + 0.50·liquidity_gate + 0.15·holder_gate

security_gate(sec)  = sec / 100
                      ↳ honeypot → 0.02   (the only hard stop — overrides the sum)

liquidity_gate(liq) = piecewise ramp on the effective depth (USD):
                      < 1 000          → 0.00
                      1 000  → 4 000   → 0.00 → 0.50
                      4 000  → 10 000  → 0.50 → 0.80
                      10 000 → 50 000  → 0.80 → 1.00
                      >= 50 000        → 1.00

holder_gate(h)      = piecewise ramp on holder count:
                      <= 100           → 0.00
                      100  → 1 000     → 0.00 → 0.90
                      1 000 → 2 000    → 0.90 → 1.00
                      >= 2 000         → 1.00
```

`effective_liquidity` is the realistic sell-side depth. It is resolved from the
**live snapshot** first, and the OHLC series is only a fallback:

| side | priority order |
|---|---|
| total liquidity | `token_overview.liquidity` → `liquidity/latest.liquidity_usd` → last OHLC close |
| exit liquidity | `liquidity/latest.exit_liquidity_usd` → last OHLC close |

On **Solana** the effective depth is `min(liquidity, exit_liquidity)` when the exit
figure is reported, otherwise the reported `liquidity`. `token_overview` is the live
snapshot every chain exposes, so the gate stops comparing a live overview figure
against a stale OHLC close (the mismatch this revision fixes); `liquidity/latest`
(`POST /defi/v3/liquidity/latest/token`, Solana only) adds live exit liquidity.
When the OHLC close is the fallback, the gate block carries
`liquidity_source` / `exit_liquidity_source` = `"ohlc_close"` and
`ohlc_age_seconds` (seconds between the last bar and the request), so the renderer
labels the depth as stale instead of treating it as current.

| Parameter | Value |
|---|---:|
| `GATE_WEIGHTS` (security / liquidity / holder) | 0.35 / 0.50 / 0.15 |
| `HONEYPOT_MULTIPLIER` | 0.02 |
| `LIQ_GATE_T1 / T2 / T3 / T4` | 1 000 / 4 000 / 10 000 / 50 000 |
| `LIQ_GATE_G1 / G2` | 0.50 / 0.80 |
| `HOLDER_GATE_T1 / T2 / T3` | 100 / 1 000 / 2 000 |
| `HOLDER_GATE_G1` | 0.90 |

`is_risky` is `true` when the combined gate drops below `0.5`.

## Liquidity health label — `DYING` / `DEAD`

Independent of the score: a token can still trend while its pool is being pulled
dry. `liquidity_health` reports the pool state and never changes the score.

```
dd    = liq_drawdown_1h_pct          # peak-to-trough liquidity move in the last hour
depth = min(liquidity, exit_liquidity)   # thinner reported pool binds

DEAD   if dd >= 99 %   OR   depth < USD 10              # red badge, shown first
DYING  elif dd >= 80 %                                  # amber badge
else   LIQ_OK                                           # no label
```

| field | value |
|---|---|
| `code` | `LIQ_OK` / `LIQ_DYING` / `LIQ_DEAD` |
| `label` | `null` / `DYING` / `DEAD` |
| `tone` / `color` | `neutral` / `warn` (`#f59e0b`) / `bad` (`#ef4444`) |
| `drawdown_pct` | liquidity drawdown used |
| `depth_usd` | thinner pool used |
| `reason` | human-readable cause |

| Parameter | Value |
|---|---:|
| `LIQ_HEALTH_DYING_DD` | 80 |
| `LIQ_HEALTH_DEAD_DD` | 99 |
| `LIQ_HEALTH_DEAD_USD` | 10 |

The badge is rendered first in the header badge row (before the junk-gate badge)
and is surfaced in every format (`ui`, `plain`, `telegram`, `json`).

---

## Output Shape

Per interval the response exposes:

- `trending_score`
- `raw_score`
- `security_multiplier`
- `liquidity_multiplier`
- `holder_multiplier`
- `gate_multiplier`
- `components`

At the top level the response exposes:

- `is_risky` — `true` when the combined gate drops below `0.5`
- `liquidity_health` — `{ code, label, tone, color, drawdown_pct, depth_usd, reason }`
- `gates.weights` — `{ security, liquidity, holder }`
- `gates.security` — `{ multiplier, reason, score }`
- `gates.liquidity` — `{ multiplier, reason, effective_liquidity, used_exit_liquidity, liquidity, exit_liquidity, liquidity_source, exit_liquidity_source, ohlc_age_seconds }`
- `gates.holder` — `{ multiplier, reason, holder_count }`
- `gates.combined_multiplier`
- `gates.reason` — `weighted_gate` or `honeypot_hard_stop`

In `hybrid`, `components.formula_native` is added on every interval:

- supported intervals: filled with wallets / volume / pace breakdown
- unsupported intervals: `score = null`, `reason = interval_not_supported`

Extra interval fields in `hybrid`:

- `mode`: `hybrid` or `classic_fallback`
- `blend.native_weight`
- `blend.classic_weight`
- `blend.native_score`
- `blend.classic_raw_score`
- `blend.hybrid_raw_score`

---

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| Creation time | `/defi/token_creation_info` | 35 |
| OHLCV 1m | `/defi/v3/ohlcv` | 25–100 |
| Liquidity OHLC (+ exit liquidity) | `/defi/v3/liquidity/ohlc/token` | 20 |
| Liquidity latest (current total + exit, Solana) | `/defi/v3/liquidity/latest/token` | 5 (`ceil(5·n^0.8)`) |
| Token overview | `/defi/token_overview` | 21 |
| Holder chart | `/token/v1/holder/chart` | 30 |
| Holder profile | `/token/v1/holder-profile` | 21 |
| Token security | `/defi/token_security` | 30 |
| Typical total | | `~176` to `~262` depending on OHLCV cost (Solana adds the 5 CU liquidity snapshot) |

`hybrid` does **not** add new API calls beyond `classic`; it only changes the
scoring logic.

---

## CLI

```bash
# Original model
python3 birdeye_cli.py token-trending-score --chain sol --address <MINT> --model classic --format plain

# Blended model
python3 birdeye_cli.py token-trending-score --chain sol --address <MINT> --model hybrid --format json
```

| Flag | Default | Notes |
|---|---|---|
| `--model` | `classic` | `classic` or `hybrid` |
| `--candles` | `5000` | 1m candles for classic momentum context |
| `--nocache` | off | bypass local cache |
| `--format` | `ui` | `ui` / `json` / `telegram` / `plain` / `raw-json` |

---

## When To Use Which

| Situation | Recommended model |
|---|---|
| You want the original backtest-friendly momentum model | `classic` |
| You care about current trend attention by interval | `hybrid` |
| You are re-ranking a trending list by the chosen interval | `hybrid` |

In practice:

- `classic` = better **quality-aware momentum**
- `hybrid` = better **attention-aware interval ranking**
