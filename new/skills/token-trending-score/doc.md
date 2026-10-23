# Token Trending Score — Skill #22 · `token-trending-score`

Momentum / "how hot is this right now" score for a **single token**. Produces one
**0–100 score per interval** plus an **overall score** (mean of the intervals),
built from six weighted components — **momentum-heavy** — then scaled by two
continuous gates (security + liquidity) that filter junk without hard cliffs.

- **Module file:** `trending-score.py` (stdlib only, no third-party deps)
- **Scoring engine:** `modules/trending_score.py` (single source of truth — the
  module is the HTTP + render wrapper, the engine owns all math)
- **Workflow:** [`docs/skill-22-token-trending-score.md`](../../docs/skill-22-token-trending-score.md)
- **Full reference (local-only):** `docs-local/trending-score-full.md` — every
  formula, ramp anchor and worked example in one place. Kept out of the public repo.
- **Kind id:** `token-trending-score-v1` · **skill_version:** `1.0`

> Skill #1 · `trending-list` is a **pure API passthrough** and does no scoring.
> This skill is the one that owns the momentum model.

---

## 1. What it does

Two models share one output shape:

| Model | Core idea | Used for |
|---|---|---|
| `classic` | Original 6-component momentum model on **every** interval | Stable, backtest-friendly baseline |
| `hybrid` | `classic` blended with an interval-native wallets / volume / pace "attention" formula on `1h` / `4h` / `24h` | Attention-aware interval ranking |

Intervals scored: **`5m · 15m · 30m · 1h · 4h · 6h · 12h · 24h`**.
`overall_trending_score` = mean of the per-interval scores.

Six components (identical weights in both models) — **momentum carries the score**:

| Component | Weight | Reads |
|---|---:|---|
| Volume Growth | 0.30 | per-candle volume momentum (log-regression) or `v{iv}USD` vs baseline |
| Swap Activity | 0.15 | `trade{iv}` vs baseline (candle intervals fall back to the volume score) |
| Price Momentum | 0.25 | log(close) regression over the window, or `priceChange{iv}Percent` |
| Liquidity Health | 0.10 | `liquidity / marketCap` ratio + recent 1h drawdown stability |
| Holder Dynamics | 0.10 | holder-count growth (chart) + holder-profile cohort health + holder-count sufficiency |
| Security | 0.10 | contract-risk penalties (authority, LP, taxes, concentration) |

Security, liquidity and holder breadth keep a small share of the composite
**and** act as continuous gates (see §2.4), so a junk token is filtered while
momentum still decides the ranking.

Raw composite per interval:

```
raw   = Σ component_score × component_weight          # Σ weights = 1.00
gate  = 0.35·security_gate(security_score)
      + 0.50·liquidity_gate(effective_liquidity)
      + 0.15·holder_gate(holder_count)
final = raw × gate
```

---

## 2. Models

### 2.1 `classic` (default)

The six-component model above, evaluated independently per interval. Volume and
price momentum use a **full-series regression** on the candle window when candles
are available (`5m/15m/30m` → 1-second candles; `1h+` → 1-minute candles);
overview-served intervals (`5m/1h/4h/24h`) fall back to `v{iv}USD` / `trade{iv}` /
`priceChange{iv}Percent` against a median snapshot baseline or the Birdeye
`*History` field.

Baseline uses collected **overview snapshots** (median over a per-interval window)
when ≥ 3 samples exist, otherwise the single `*History` field.

### 2.2 `hybrid`

`hybrid` keeps the classic components (quality + risk context) and blends in an
interval-native formula where the Birdeye overview windows are strongest.

Supported intervals — **`1h`, `4h`, `24h`**:

```
native_raw(T) = 1.00·log10(1 + wallets_T)
              + 0.50·log10(1 + volume_T_usd)
              + 0.25·pace_now_wallets(T)
              + 0.25·pace_window_volume(T)
              + 0.25·tanh(price_change_T_pct / 25)

native_score(T) = 50 + 50·tanh((native_raw − 4.00) / 1.35)     # normalized to 0–100

hybrid_raw(T)   = 0.55·native_score(T) + 0.45·classic_raw(T)
hybrid_final(T) = hybrid_raw(T) × gate
```

Pace terms clip the short/long ratio to `0.25× … 4×` then take `log2`; they are
**disabled (0) when `uniqueWallet24h < 50`**, so tiny/new tokens do not look
permanently "accelerating".

| Interval | `pace_now_wallets` | `pace_window_volume` |
|---|---|---|
| `1h` | `log2(clip(wallet_5m · 6 / wallet_30m))` | `log2(clip(volume_30m · 2 / volume_1h))` |
| `4h` | `log2(clip(wallet_30m · 4 / wallet_2h))` | `log2(clip(volume_2h · 2 / volume_4h))` |
| `24h` | `log2(clip(wallet_1h · 4 / wallet_4h))` | `log2(clip(volume_4h · 6 / volume_24h))` |

Intervals the overview cannot support (`5m/15m/30m/6h/12h`) fall back to the
classic score and are marked `mode = "classic_fallback"`.

`hybrid` adds **no** extra API calls — it only changes the scoring blend.

### 2.3 Data dependencies & the availability guard

`hybrid` can only score an interval natively when the **token overview** block is
present, because `native_score(T)` reads overview-only fields:

| field | used for |
|---|---|
| `uniqueWallet{1h,4h,24h,5m,30m,2h,…}` | wallet term + pace ratios |
| `v{1h,4h,24h,30m,2h,…}USD` | volume term + pace ratios |
| `priceChange{interval}Percent` | price term (`tanh(pct/25)`) |

If overview wallets/volume are missing for an interval, the engine returns
`None` and the caller silently falls back to the classic score. To make that
degradation visible, every run emits a `warnings[]` list plus a
`coverage` block, and `pipeline_gap` is `true` when any **critical** warning is
present:

| code | level | meaning |
|---|---|---|
| `overview_missing` | critical | token_overview unavailable — volume/swaps/holder/price use candles only |
| `hybrid_not_ready` | critical | hybrid missing overview wallets+volume on some of `1h/4h/24h` → classic fallback |
| `ohlcv_1m_thin` | critical | fewer than 3 one-minute candles — regression unusable |
| `ohlcv_1s_thin` | warn | fewer than 3 one-second candles — `5m/15m/30m` fall back to 1m |
| `liquidity_thin` | warn | fewer than 3 liquidity points — stability sub-score is neutral |

`coverage` reports how many of the three hybrid-native intervals actually got
overview data: `{ model, hybrid_intervals: ["1h","4h","24h"], hybrid_ready,
hybrid_coverage: "3/3" }`. So `classic` needs **ohlcv + liquidity**; `hybrid`
additionally needs **overview**. The `coverage` block stays in the JSON envelope
for transparency but is no longer rendered in the UI. Warnings surface in every
format (plain / telegram / json / ui) — the UI shows only actionable
(`critical` / `warn`) rows and a `⚠ pipeline_gap` badge when `pipeline_gap` is
`true`.

### 2.4 Junk gates (weighted: security + liquidity + holder)

Security, liquidity and holder breadth are deliberately **not** hard triggers.
Each maps to a `0..1` gate and then the three combine into one weighted
multiplier, so the score stays momentum-driven while genuinely junk tokens are
filtered. All gates are piecewise-linear, so a small data change never flips the
verdict between two arbitrary values.

```
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

`effective_liquidity` is the realistic sell-side depth:

- **Solana** — `min(liquidity, exit_liquidity)` when the exit figure is reported
  (the liquidity OHLC endpoint returns `close_exit_liquidity_usd`);
- **other chains** — the reported `liquidity`.

`is_risky` (the UI junk-gate badge) is `true` when the combined gate drops below
`0.5`.

| Parameter | Value |
|---|---:|
| `GATE_WEIGHTS` (security / liquidity / holder) | 0.35 / 0.50 / 0.15 |
| `HONEYPOT_MULTIPLIER` | 0.02 |
| `LIQ_GATE_T1 / T2 / T3 / T4` | 1 000 / 4 000 / 10 000 / 50 000 |
| `LIQ_GATE_G1 / G2` | 0.50 / 0.80 |
| `HOLDER_GATE_T1 / T2 / T3` | 100 / 1 000 / 2 000 |
| `HOLDER_GATE_G1` | 0.90 |

---

## 3. Commands

### 3.1 Via the unified CLI (recommended — adds cache + History tab)

```bash
python3 birdeye_cli.py token-trending-score --chain sol --address <MINT> --model classic --format plain
python3 birdeye_cli.py token-trending-score --chain sol --address <MINT> --model hybrid  --format json
```

### 3.2 Standalone

```bash
python3 skills/token-trending-score/trending-score.py --chain sol --address <MINT> --model hybrid
```

### 3.3 Flags

| Flag | Default | Meaning |
|---|---|---|
| `--chain` | `sol` | `sol`, `bsc`, `base`, `eth`, `arc`, `robinhood` |
| `--address` | required | token contract / mint address |
| `--model` | `classic` | `classic` \| `hybrid` |
| `--candles` | `5000` | 1-minute OHLCV candle count (5000 = 100 CU, ≈83h) |
| `--nocache` | off | bypass the 24h CSV snapshot cache and refetch |
| `--format` | `ui` | `ui` \| `json` \| `telegram` \| `plain` \| `raw-json` \| `rendered` |

---

## 4. API calls & CU

| Step | Endpoint | CU |
|---|---|---:|
| Creation time (anchor) | `/defi/token_creation_info` | 35 |
| OHLCV 1m candles | `/defi/v3/ohlcv?type=1m` | 25–100 |
| Liquidity OHLC 1m (+ exit liquidity) | `/defi/v3/liquidity/ohlc/token` | 20 |
| Overview + money flow | `/defi/token_overview?includes=money_flow` | 21 |
| OHLCV 1s candles (short intervals) | `/defi/v3/ohlcv?type=1s` | 25–100 |
| Holder chart 1m | `/token/v1/holder/chart` | 30 |
| Holder profile | `/token/v1/holder-profile` | 21 |
| Security | `/defi/token_security` | 30 |

Typical total **≈171 CU** (up to ≈257 CU when both OHLCV calls return large
candle sets). `/defi/v3/ohlcv` CU scales with returned candle count:
`0–100 → 25`, `101–300 → 30`, `301–1000 → 40`, `1001–2000 → 75`, `2001–5000 → 100`.
The `⚡CU cost` footer on every render carries the actual billed amount.

---

## 5. Interval score bands

Colour bands used by the UI card (per interval):

| Score | Band | Colour |
|---|---|---|
| ≥ 70 | Hot | green |
| 50 – <70 | Warm | lime |
| 30 – <50 | Cool | amber |
| 15 – <30 | Weak | orange |
| < 15 | Cold | red |

These are **momentum intensity labels, not trade advice**.

---

## 6. Output contract

`--format json` / `raw-json` returns a clean, HTML-free envelope:

```jsonc
{
  "schemaVersion": 1, "kind": "token-trending-score-v1",
  "run_id": "ts_<chain>_<addr>_<ts>",
  "cu_used": 171,
  "params":  { "chain", "address", "candles", "model", "argv" },
  "symbol": "…", "name": "…", "model": "classic" | "hybrid",
  "overall_trending_score": 61.4,
  "intervals": {
    "5m" | "15m" | "30m" | "1h" | "4h" | "6h" | "12h" | "24h": {
      "trending_score": 61.4,
      "raw_score": 61.4,
      "security_multiplier": 1.0,
      "liquidity_multiplier": 1.0,
      "holder_multiplier": 1.0,
      "gate_multiplier": 1.0,
      "components": {
        "volume":    { "score", "source", "volume_current", "volume_baseline", … },
        "swaps":     { "score", "source", "swaps_current", "swaps_baseline", … },
        "price":     { "score", "source", "slope_log", "r2", … },
        "liquidity": { "score", "liq_mcap_ratio", "liq_drawdown_1h_pct", "subscores" },
        "holder":    { "score", "subscores", "holder_growth", "holder_health" },
        "security":  { "score", "penalties", "honeypot", … },
        "formula_native": { … }          // hybrid only
      },
      "mode": "hybrid" | "classic_fallback",   // hybrid only
      "blend": { "native_weight", "classic_weight", "native_score",
                 "classic_raw_score", "hybrid_raw_score" }   // hybrid only
    }
  },
  "is_risky": false,
  "gates": {
    "weights":   { "security": 0.35, "liquidity": 0.50, "holder": 0.15 },
    "security":  { "multiplier": 1.0, "reason": "security_ok", "score": 88.0 },
    "liquidity": { "multiplier": 1.0, "reason": "liquidity_ok", "effective_liquidity": 62000,
                   "used_exit_liquidity": false, "liquidity": 62000, "exit_liquidity": null },
    "holder":    { "multiplier": 1.0, "reason": "holder_ok", "holder_count": 4200 },
    "combined_multiplier": 1.0,
    "reason": "weighted_gate"
  },
  "security": { "final", "penalties": [ { "name", "delta", "detail" } ], … },
  "weights": { "volume", "swaps", "price", "liquidity", "holder", "security" },
  "meta": { "market_cap", "holder_count", "liquidity", "n_snapshots",
            "n_1m_candles", "n_1s_candles", "n_liq_points", "n_holder_chart",
            "holder_profile", "hybrid_supported_intervals", … },
  "coverage":    { "model", "hybrid_intervals", "hybrid_ready", "hybrid_coverage" },
  "pipeline_gap": false,                          // true if any critical warning
  "warnings":    [ { "code", "level", "detail" } ],   // see §2.3
  "cu_breakdown": [ "creation_info=35", "ohlcv_v3_1m=100", "liq_ohlc_exit=20",
                    "overview+mf=21", "ohlcv_1s=40", "holder_chart=30",
                    "holder_profile=21", "security=30" ]
}
```

- `--format ui` returns a **payload wrapper** with every render pre-computed so the
  console can flip tabs with no re-run:
  `{ skill, skill_version, format_renderers, payload, rendered_plain,
  rendered_telegram, rendered_json, rendered_raw-json, rendered_ui, html }`
  (same shape as `token-dd-score._ui_envelope`).
- `--format plain` / `telegram` return monospace tables with the `⚡CU` footer.
- Cache payloads (written to `~/.cache/birdeye-skills-runs/`) keep
  `rendered_plain` / `rendered_telegram` / `rendered_json` / `rendered_ui` so the
  History tab can re-render with **0 CU**.

---

## 7. Integration contract (for `birdeye_cli.py`)

The unified CLI loads this file with `importlib` (the filename contains dashes, so
a plain `import` is impossible) and expects exactly three symbols:

```python
SKILL_NAME          # str  -> "token-trending-score"
add_parser(sub, chains=None)   # argparse subparser factory; sets set_defaults(func=run)
run(args)           # int  -> 0 = ok
```

Registration in `birdeye_cli.py`:

```python
_trending_score = _load_external_skill("skills", "token-trending-score", "trending-score.py")
if _trending_score is not None:
    _trending_score.add_parser(sub, CHAINS)
```

---

## 8. Caveats

- **Snapshots are local state.** Median baselines need ≥ 3 collected overview
  snapshots inside the per-interval window; without them the model falls back to
  the single Birdeye `*History` field (noisier).
- **Candle coverage vs interval.** `5m/15m/30m` read 1-second candles (last ≈70 min);
  `6h/12h/24h` can exceed the 1-minute window if `--candles` is small — the
  regression then uses whatever is available and reports `n_points`.
- **Swap count is not in candles.** For `15m/30m/6h/12h` the swaps component
  reuses the volume score as a proxy (`source = "volume_proxy"`) and has no
  independent trade-count signal.
- **`hybrid` is additive, not a new data source.** It never adds API calls; it
  re-blends on `1h/4h/24h` and marks the rest `classic_fallback`.
- **Pace is gated.** Pace terms contribute 0 unless `uniqueWallet24h ≥ 50`.
- **Scores are intensity, not advice.** Never read a high score as a buy signal.
