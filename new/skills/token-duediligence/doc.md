# Token Due-Diligence Score — Skill #24 · `token-dd-score`

Contract due-diligence score for a single token. Produces one number on a
**0–100 scale** plus a letter rating **A+ → F**, built from five weighted pillars
and scaled by a **smooth liquidity-drawdown gate**.

- **Module file:** `token-dd-score.py` (stdlib only, no third-party deps)
- **Workflow / derivation:** [`docs/token-dd-score-workflow.md`](../../docs/token-dd-score-workflow.md)
- **Full reference (local-only):** `docs-local/token-dd-score-full.md` — every formula,
  ramp anchor and worked example in one place. Kept out of the public repo on purpose.
- **Kind id:** `token-dd-score-v1` · **skill_version:** `1.0`

---

## 1. What it does

Declared weights are **chain-aware**: on **Solana** the base profile is shifted by
6 points from Security (3 → Holders, 3 → Liquidity), because a Solana mint's
authority controls are a much weaker risk signal than holder distribution and
real exit liquidity (see §4.1). Non-Solana chains keep the base profile.

| Pillar | What it reads | Solana weight | Non-Solana weight | Standard (re-normalised) |
|---|---|---:|---:|---:|
| Security | mint / freeze authority, mutable metadata, LP lock, creator dump power, not-freezable / not-LST / not-fake | **0.17** | 0.23 | 0.256 |
| Holders | top1 / top3 / top10 concentration, holder base, cohort risk (dev+sniper+bundler), sniper density | **0.28** | 0.25 | 0.278 |
| Activity | engagement, buy pressure, multi-interval momentum, multi-interval drawdown risk | 0.20 | 0.20 | 0.222 |
| Liquidity | depth, 24h stability, valuation (mcap vs liquidity), trend, pair count | **0.25** | 0.22 | 0.244 |
| Smart Money | SM presence, multi-interval cohort flow, holding quality, whales, KOLs | 0.10 | 0.10 | — (standard drops it) |

Every pillar is a **weighted mean of ramped sub-scores**. A sub-signal that is
absent is dropped **and its weight is removed from the denominator**, so the
pillar score reflects measured coverage only (GMGN contract-dd rule). Each pillar
reports its own `coverage` (0–1 = share of declared weight that was measurable).

Then:

```
FINAL = weighted_pillar_mean × gate

liq_pen  = 0.10 × smoothstep(ramp(liquidity_drawdown_from_peak_pct        / 100, 0.20, 0.70))
exit_pen = 0.15 × smoothstep(ramp(exit_liquidity_drawdown_from_peak_pct   / 100, 0.20, 0.70))
pen      = max(liq_pen, exit_pen)          # worst term binds — not summed
gate     = 1 − pen                         # floor 0.85 → at most a 15 % total discount
```

The gate reads **deterioration, not depth**. Absolute depth is already scored by the
Liquidity pillar (`depth`), so gating on it as well penalised one weakness twice: a token with
`USD 5k` exit liquidity scored low on `depth` *and* then lost a further ~25 % of its **total**
score. The gate now only asks *how far liquidity has fallen from its recent peak* over the OHLC
window:

| drawdown from peak | `liq_pen` | `exit_pen` | gate |
|---|---:|---:|---:|
| ≤ 20 % | 0.000 | 0.000 | 1.000 |
| 35 % | 0.014 | 0.021 | 0.979 |
| 50 % | 0.040 | 0.060 | 0.940 |
| 70 %+ | 0.100 | 0.150 | 0.850 |

Consequences:

- **No double penalty** — a thin-but-stable pool (`USD 5k` exit, flat depth) keeps `gate = 1.000`;
  its low score comes from the Liquidity pillar alone, where it belongs.
- **Only bleeding pools are discounted** — the penalty starts at 20 % below the window peak and
  saturates at 70 % below.
- **Moderate cap** — the worst term binds (`max`, not sum), so the total discount never exceeds
  **15 %**.
- **Standard mode is neutral** — no OHLC window ⇒ no drawdown ⇒ `gate = 1.000`; `depth` and
  `valuation` still score the pillar.

`gate_detail` reports `liquidity_drawdown_pct`, `exit_drawdown_pct`, `liquidity_penalty`,
`exit_penalty`, `binding` (`exit_drawdown` / `liquidity_drawdown` / `none`) and a reserved
`holder_change_penalty` (always `null` for now — multi-interval holder change is a future
deterioration input).

---

## 2. Modes

| Mode | Endpoints called | CU | Notes |
|---|---|---:|---|
| `standard` | `token_overview` + `token_security` | **51** | No cohorts, no snipers, no exit liquidity, no stability/trend, no smart money → weights re-normalised across 4 pillars; response carries a `coverage_caveat`. Numbers are **not comparable** with advanced. |
| `advanced` | standard + `distribution` + `holder-profile` + `top_holders` + `token_money_flow` + `liquidity/ohlc/token` | **181** | All five pillars measurable. |

Optional add-ons (advanced only):

- `--skip distribution,holder_profile,top_holders,token_money_flow,liquidity` → drop selected endpoints and refund their CU.

Solana-only endpoints (`distribution`, `holder_profile`, `liquidity_ohlc`) are
auto-skipped on non-Solana chains and their CU is booked into
`meta.cu_breakdown.refunded_rollback`.

---

## 3. Commands

### 3.1 Via the unified CLI (recommended — adds cache + history re-render)

```bash
python3 birdeye_cli.py token-dd-score --chain sol --address <MINT> --mode standard
python3 birdeye_cli.py token-dd-score --chain sol --address <MINT> --mode advanced
```

### 3.2 Standalone

```bash
python3 skills/token-duediligence/token-dd-score.py --chain sol --address <MINT> --mode advanced
```

### 3.3 0-CU re-score (replay cached inputs, no API call)

```bash
python3 birdeye_cli.py token-dd-score --rescore <run_id|path|base64>
python3 birdeye_cli.py token-dd-score --rescore <run_id> --weights-preset strict-liquidity
```

`--rescore` re-uses the raw inputs stored by a previous run, so changing the
weight preset, `--pace`, `--top-n` or `--explain` costs **0 CU**. Disable the
input snapshot with `--no-store-inputs` (then re-score is unavailable).

### 3.4 Flags

| Flag | Default | Meaning |
|---|---|---|
| `--chain` | `sol` | `sol` (default, "solana"), `bsc`, `base`, `eth`, `arc`, `robinhood` |
| `--address` | required | Token contract / mint address |
| `--mode` | `standard` | `standard` \| `advanced` |
| `--top-n` | `20` | Holder rows requested from `/holder/v1/distribution` (`10`\|`20`\|`50`) |
| `--liq-resolution` | `15m` | Liquidity OHLC resolution (`auto` → `15m`) |
| `--liq-candles` | `96` | Candle count, max 100 → `15m × 96 = 24h` |
| `--pace` | off | Enable the pace sub-signal in Activity (Phase 2) |
| `--skip` | — | Comma list of endpoints to skip (advanced) |
| `--weights-preset` | `default` | `default` \| `strict-liquidity` \| `security-first` |
| `--rescore` | — | 0-CU replay (run-id / cache path / base64 result) |
| `--no-store-inputs` | off | Do not persist raw inputs (kills `--rescore`) |
| `--explain` | off | Include the per-sub-signal breakdown in the `ui` payload |
| `--format` | `ui` | `ui` \| `json` \| `plain` \| `telegram` \| `raw-json` \| `render` \| `rendered` |

---

## 4. Weight presets

| Preset | Security | Holders | Activity | Liquidity | Smart Money |
|---|---:|---:|---:|---:|---:|
| `default` | 0.23 | 0.25 | 0.20 | 0.22 | 0.10 |
| `strict-liquidity` | 0.18 | 0.19 | 0.13 | **0.38** | 0.12 |
| `security-first` | **0.34** | 0.21 | 0.12 | 0.23 | 0.10 |

In `standard` mode the Smart Money weight is removed and the rest are
re-normalised to sum 1.0 (`default` → 0.256 / 0.278 / 0.222 / 0.244).

### 4.1 Chain-specific shift (Solana)

On **Solana** every preset is rebalanced **before** the coverage re-normalisation:

```python
SOL_WEIGHT_SHIFT = { "security": -0.06, "holders": +0.03, "liquidity": +0.03 }
weights = base_preset + SOL_WEIGHT_SHIFT      # only when chain is sol
```

The shift runs *after* `standard` drops Smart Money, so it applies to the
4-pillar standard profile too. Rationale: on Solana the mint/freeze authority
checks resolve to a binary "renounced or not", so Security carries less
discriminating power than on EVM, while holder concentration and *realizable*
exit liquidity are the dominant risk drivers. The result is exposed so it is
never silent:

| Field | Meaning |
|---|---|
| `meta.weights_declared` | the weight profile actually declared after the shift |
| `meta.weights_shift` | the applied delta dict, or `null` on non-Solana chains |
| `score.weights_used` | declared weights re-normalised over measurable pillars |

`default` preset, chain-by-chain:

| Chain | Security | Holders | Activity | Liquidity | Smart Money |
|---|---:|---:|---:|---:|---:|
| `sol` | 0.17 | 0.28 | 0.20 | 0.25 | 0.10 |
| any other | 0.23 | 0.25 | 0.20 | 0.22 | 0.10 |

### 4.2 Activity — multi-interval momentum + drawdown

Activity sub-weights (`SUB_W["activity"]`):

| Sub-signal | Weight | Rule |
|---|---:|---|
| `engagement` | 0.40 | trades / volume / wallets per frame |
| `buy_pressure` | 0.10 | buy-ratio across `BUY_FRAMES` (5m/1h/4h/24h) |
| `momentum` | 0.30 | weighted price-change across `MOMENTUM_FRAMES` (15m/1h/4h/24h) |
| `drawdown` | 0.20 | worst *give-back* risk across nested windows |
| `pace` | 0.10 | only counted when `--pace` is on |

`drawdown` treats a fade from a longer window back to a shorter window as risk.
For each nested pair `(24h→1h)`, `(24h→4h)`, `(4h→1h)` the give-back is
`long_pct − short_pct` (how much of the longer-window gain was handed back), and
the current `1h` sell-off contributes `−price_change_1h`. Each term is passed
through a smooth ramp (`giveback` 12%→65%, sell-off 15%→60%); the **worst** risk
drives the sub-score `100 × (1 − risk)`, so a token that pumps then bleeds scores
low even if the point-in-time price is up.

### 4.3 Smart Money — multi-interval cohort flow

The `smart_money` / `whales` / `kol` net-flow sub-scores no longer read 24 h only.
`_cohort_flow_score()` reads the full `(tag × frame)` grid from
`token_overview.moneyFlow` over `SM_FLOW_FRAMES` (5m/1h/4h/24h):

- per-frame score = `smoothstep(net_usd / volume_usd)` on the tag's ramp band;
- weighted mean across frames (5m 0.15 · 1h 0.25 · 4h 0.25 · 24h 0.35);
- **consistency factor**: the share of frame-weight that agrees in sign with the
  mean; final = `50 + (mean − 50) × (0.75 + 0.25 × consistency)`.

So a cohort that is consistently net-buying across every window is rewarded over
one that flips sign between intervals. The per-frame breakdown is exposed in
`smart_money.net_flow_by_frame`, `whale_net_flow_by_frame`,
`kol_net_flow_by_frame` plus `net_flow_consistency`.

---

## 5. Rating bands

| Rating | Score | Verdict |
|---|---|---|
| A+ | ≥ 95 | 🔥 HOT |
| A | ≥ 85 | 🟢 STRONG |
| B+ | ≥ 80 | 🟢 OK |
| B | ≥ 70 | 🟢 FAIR |
| C+ | ≥ 65 | 🟡 WATCH |
| C | ≥ 55 | 🟡 CAUTION |
| D | ≥ 40 | 🟠 RISKY |
| E | 20 – <40 | 🔴 HIGH RISK |
| F | < 20 | ⛔ CRITICAL |

Verdicts are **risk labels, not trade calls** — the skill never emits buy/sell
advice.

Hard blocks (e.g. `isHoneypot = true` on EVM) force `final = 0` and rating `F`.

---

## 6. Output contract

`--format json` / `raw-json` returns:

```jsonc
{
  "schemaVersion": 1, "kind": "token-dd-score-v1", "skill": "token-dd-score",
  "meta":   { "chain", "address", "symbol", "mode", "weights_preset",
              "weights_declared", "weights_shift",
              "cu_breakdown": { "base", "list", "advanced_security",
                                "risk_history", "refunded_rollback" },
              "cu_billed_total", "endpoint_calls", "api_call_details", "frames_used",
              "caveats", "run_id", "cache_file", "latency_ms" },
  "market": { "price_usd", "market_cap_usd", "liquidity_usd", "exit_liquidity_usd",
              "holders", "volume_24h_usd", "trades_24h", "unique_wallets_24h", … },
  "score":  { "final", "base_before_gate", "rating", "verdict",
              "gate", "gate_detail", "weights_used", "pillar_points" },
  "pillars": { "security" | "holders" | "activity" | "liquidity" | "smart_money":
               { "score", "coverage", "breakdown": [ {name, score, weight, detail} ] } },
  "holder_top": { "top1", "top3", "top10", "top20" },
  "holder_cohorts": { "dev" | "bundler" | "sniper" | "insider" | "smart_trader" | "kol":
                      { "pct_of_supply", "holder_count", "pnl_usd" } },
  "liquidity_stats": {
      "window": { "resolution", "candles", "span_hours", "source" },
      "liquidity":  { "current", "first", "min", "max", "median", "mean",
                      "std", "std_pct_of_mean", "drawdown_pct",
                      "drawdown_from_peak_pct", "trend_pct", "candles" },
      "exit_liquidity": { …same shape… } },
  "smart_money": { "smart_traders_no", "smart_trader_pct_of_supply",
                   "net_flow_24h_usd", "net_flow_source", "net_flow_pct_of_vol",
                   "net_flow_by_frame", "net_flow_consistency",
                   "sm_buy_count_24h", "sm_sell_count_24h", "sm_buy_ratio",
                   "action", "action_detail", "hold_ratio_pct",
                   "kol_count", "kol_source", "kol_pct_of_supply",
                   "kol_net_flow_24h_usd", "kol_net_flow_by_frame",
                   "whale_count", "whale_pct_of_supply",
                   "whale_net_flow_24h_usd", "whale_net_flow_by_frame",
                   "whale_sell_share_pct" },
  "raw_data":     { "overview", "security", "distribution", "holder_profile",
                    "top_holders", "token_money_flow", "liquidity_ohlc" },
  "derived_data": { "market", "flow", "holder_top", "holder_cohorts",
                    "liquidity_stats", "smart_money_signals" },
  "inputs": { … }          // compatibility alias of raw_data, enables --rescore
}
```

`json` / `raw-json` never include the UI `html` payload. `meta.cu_breakdown`
always carries the 5 canonical keys; the footer of every render shows `⚡CU cost`.

---

## 7. Integration contract (for `birdeye_cli.py`)

The unified CLI loads this file with `importlib` (the filename contains dashes,
so a plain `import` is impossible) and expects exactly three symbols:

```python
SKILL_NAME          # str  -> "token-dd-score"
add_parser(sub)     # argparse subparser factory; sets set_defaults(func=run)
run(args)           # int  -> 0 = ok
```

Registration in `birdeye_cli.py`:

```python
def _load_external_skill(*rel_parts):
    ...  # importlib.util.spec_from_file_location

_dd_score = _load_external_skill("skills", "token-duediligence", "token-dd-score.py")
if _dd_score is not None:
    _dd_score.add_parser(sub, CHAINS)
```

---

## 8. Caveats

- `standard` numbers are not comparable with `advanced` (fewer sub-signals, different denominators, no liquidity-drawdown window → the gate is neutral at `1.000`).
- Weights are **chain-dependent**: the Solana 6-point shift (Security → Holders/Liquidity) means `score.weights_used` differs between `sol` and other chains even for the same preset. Use `meta.weights_declared` / `meta.weights_shift` to see exactly what was applied.
- Multi-interval cohort flow and drawdown depend on the frames present in `token_overview.moneyFlow` (typically 5m/15m/1h/4h/8h/24h). Missing frames are dropped and their weight removed — the sub-score never fabricates a window.
- `not_freezable` / `not_lst` are **Solana-only**; on EVM the flags are always false → sub-score is `N/A`, not a pass.
- `--pace` is Phase 2 and OFF by default (requires short-vs-long per-minute rate pairs).
- Bot / wash-trade data is not available from the Birdeye API yet → `wash_trade_proxy` is informational only and is **not scored**.
