# 13 · Modular Token DD Include API (Design Concept / Selector-driven)

> **Concept source:** User-requested module hóa Token DD. Client selects `include[]` flags → each flag adds specific data payload AND adds a labeled CU surcharge on top of the BASE 71 CU tier. Final payload is shaped by which `includes` were requested. Mirrors RugCheck.xyz 13-field summary + tag% + top-N holders + 30d risk-history series.

---

## Summary Table

| Endpoint concept | Method | Chains | BASE CU | CU adder per flag |
|---|---|---|---:|---:|
| `/local/token/dd` (client composite selector — NOT a real Birdeye endpoint) | Composite client-side. Powers Skill #3 + Skill #17b RugCheck. | All (Sol primary). | **71** (BASE) | `+list=+30` · `+advanced_security=+21` · `+risk_history=+30` (per-selector) |

### CU Tiers by include combination (Σ cumulative)

| Tier Name | `include[]` flags | Base | +list 30 | +advsec 21 | +history 30 | **Σ Total** |
|---|---|---:|---:|---:|---:|---:|
| **BASE** (default · FAST) | none | 71 | — | — | — | **71** |
| **+HOLDER-LIST** | `include=list` | 71 | ✅ | — | — | **101** |
| **+ADVANCED-SECURITY** | `include=advanced_security` | 71 | — | ✅ | — | **92** |
| **+RISK-HISTORY 30d** | `include=risk_history` | 71 | — | — | ✅ | **101** |
| **STANDARD** | `include=list,advanced_security` | 71 | ✅ | ✅ | — | **122** |
| **FULL-ANALYTICS** | `include=list,risk_history` | 71 | ✅ | — | ✅ | **131** |
| **DEEP (all flags)** | `include=list,advanced_security,risk_history` | 71 | ✅ | ✅ | ✅ | **152** |

> Compare vs old tiers: FAST 71 (same baseline), OLD STD 155 → NEW 122 (cheaper 33 CU by reusing endpoints vs duplicating), OLD DEEP 266 → NEW 152 (merge delta-2windows + mint-burn directly into `advanced_security` block).

---

## Params (Composite Selector)

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `address` | ✅ | string | — | Sol base58 32–44 or EVM `0x40` | Token address. |
| `chain` | ❌ | string enum | `sol` | `sol` / `bsc` / `base` / `eth` | Chain id lowercase. |
| `depth` (legacy) | ❌ | string enum | `base` | `base` / `standard` / `deep` | Shorthand: auto-preset includes. Ignored if user explicitly sets `include[]`. |
| **`include[]`** (new selector) | ❌ | csv string[] | `[]` | `list` · `advanced_security` · `risk_history` | Comma-separated. Order-independent. Each valid token adds its payload block + CU adder. Invalid tokens → ignored, not billed. |
| `include=list` extra: `list_top_n` | ❌ | int | `20` | 10 / 20 / 50 | Holder rows returned in `holder_list[]` block. Note: `top_n > 20` → CU adder still +30 (Birdeye list endpoint single-cost). |
| `include=risk_history` extra: `history_points` | ❌ | int | `30` | 7 / 14 / 30 | Daily snapshot points. Each snapshot = composite score recomputed client-side. |
| `tag_cohort_interpolate` | ❌ | bool | `true` | — | When true: each tag% row also contains interpolated holding USD (see calc below). 0 CU. |
| `rating_band` | ❌ | string enum | `af_ng` | `af_ng` | Rating thresholds (S / A / B / C / D / F / NG). Future tiers reserved. |

### `include[]` Flag ↔ Data Block ↔ CU Adder ↔ Birdeye Endpoint Map

| Flag token | Payload block added | CU adder | Birdeye endpoint(s) backing the block |
|---|---|---:|---|
| **`list`** | `holder_list[]` top-N rows + LP_concentration% | **+30** | `/holder/v1/distribution?mode=top&top_n=N&include_list=true` (⚠ param `token_address`) |
| **`advanced_security`** | `liq_stats` (min/max/drawdown 24h) + `holder_24h_delta` + `trader_24h_delta` + `tag_cohorts[]` (5 tags + KOL proxy) + `bot_proxy_volume_trade_pct` + `fee_mint_burn[]` | **+21** | `/defi/v3/liquidity-ohlc-token` (15) + `/defi/v3/token/fee/single` (~5) + `/defi/v3/token/mint-burn-txs` (~1) buffer inside + holder/trader delta from step1 `v24hHolderUniqueWallets` + tag% 5 rows from step5 (absorbed into `advanced_security` at zero extra charge by reordering call budget). |
| **`risk_history`** | `risk_score_daily[30]` array of `{ts, final_score, rating, sec, smkt, act, vol}` | **+30** | Snapshot source = Đức (reference data). Internally: 30-daily window step1 `money_flow` aggregate + 30-daily step3 token_security latest available + linear interpolate missing days. |

### BASE block (71 CU — ALWAYS included, 0 adder)

Always present regardless of `include[]`. Mirrors the live FAST 71 CU tier.

```
BASE = overview(21) + security(30) + smart_money_batch(20)
```

BASE fields in output:
```json
{
  "meta": { "address": "", "chain": "sol", "symbol": "", "name": "", "logo": "", "decimals": 0, "cu_billed": 71, "include_flags": [] },
  "price_mc_liq": {
    "price_usd": 0, "mc": 0, "fdv_mc_ratio": 0, "liquidity_usd_current": 0,
    "holders_total": 0, "traders_unique_24h": 0,
    "pct_change_1m":0,"pct_change_5m":0,"pct_change_15m":0,"pct_change_30m":0,
    "pct_change_1h":0,"pct_change_2h":0,"pct_change_4h":0,"pct_change_8h":0,"pct_change_24h":0
  },
  "volume_24h": { "v24h_usd": 0, "buys_count_24h":0, "sells_count_24h":0,
    "buy_usd_24h":0, "sell_usd_24h":0, "net_flow_usd_24h":0,
    "buy_ratio_24h": 0.5, "wallet_ratio_24h": 0.5
  },
  "money_flow_32": [{ "t":0,"buy":0,"sell":0,"net":0,"wallet_buy":0,"wallet_sell":0 }],
  "security": {
    "creator_pct": 0, "top10_holder_pct": 0, "top10_user_pct": 0,
    "lp_locked": false, "mutable_metadata": false, "freeze_authority": false,
    "owner_address": "", "mint_authority_renounced_sol": true,
    "is_honeypot_evm_only": null
  },
  "smart_market": { "in_sm_top20": false, "rank_in_sm_top100": null, "smart_traders_no": 0 },
  "score_pillars_0_10": { "sec":0, "smkt":0, "act":0, "vol":0 },
  "score_final_0_10": 0,
  "rating": "NG",
  "verdict": "❌ NO-GO"
}
```

---

## Payload Shapes for each `include[]` block

### A. `include=list` → +30 CU → `holder_list[]` + `lp_concentration_pct`

```json
{
  "holder_list_meta": {
    "requested_top_n": 20,
    "returned_rows": 20,
    "sum_pct_checked_vs_security_top10": 0.05
  },
  "lp_concentration_pct": {
    "top_2_holders_pct_sum": 54.1,
    "top_10_holders_pct_sum": 72.8,
    "top_20_holders_pct_sum": 85.4,
    "known_cex_or_burn_pct": 8.2
  },
  "holder_list": [
    {
      "rank": 1,
      "owner": "5xo...",
      "amount_raw": "1234567890",
      "amount_tokens": 1234567.89,
      "pct_of_supply": 14.2,
      "holding_usd_interpolated": 1420.55,
      "tag_label_client_guess": null,
      "avg_buy_price_if_known": null,
      "pnl_usd_if_known": null
    }
  ]
}
```

**Invariant**: `sum(holder_list[].pct_of_supply)` for `rank<=10` MUST be within `±5%` of `security.top10_holder_pct` (BASE). Otherwise → badge ⚠ `signal_gap`. The diff is stored in `holder_list_meta.sum_pct_checked_vs_security_top10`.

---

### B. `include=advanced_security` → +21 CU → 7 sub-blocks

```json
{
  "liq_stats_24h_rolling": {
    "current_usd": 125000,
    "min_usd_24h": 98000,
    "max_usd_24h": 195000,
    "drawdown_24h_pct": 49.7,
    "source_endpoint": "/defi/v3/liquidity-ohlc-token type=1h 26 candles"
  },
  "holder_deltas": {
    "holder_count_24h_ago": 1820,
    "holder_count_current": 1955,
    "holder_24h_delta_abs": +135,
    "holder_24h_delta_pct": +7.42,
    "trader_unique_24h_ago": 410,
    "trader_unique_current_window": 512,
    "trader_24h_delta_abs": +102,
    "trader_24h_delta_pct": +24.88
  },
  "tag_cohorts_pct_holding_usd_interpolated": [
    { "tag": "dev",     "pct_of_supply": 1.2,  "holder_count_in_tag": 1,   "holding_usd_interp": 12000.5  },
    { "tag": "sniper",  "pct_of_supply": 4.8,  "holder_count_in_tag": 42,  "holding_usd_interp": 48000.3  },
    { "tag": "bundler", "pct_of_supply": 0.6,  "holder_count_in_tag": 3,   "holding_usd_interp": 6000.1   },
    { "tag": "smart",   "pct_of_supply": 3.3,  "holder_count_in_tag": 28,  "holding_usd_interp": 33000.7  },
    { "tag": "kol_proxy","pct_of_supply": 2.1, "holder_count_in_tag": 6,   "holding_usd_interp": 21000.0  }
  ],
  "volume_24h_bot_proxy": {
    "bot_volume_usd_proxy_pct_of_total": 28.4,
    "bot_trade_count_proxy_pct_of_total": 31.1,
    "bot_volume_usd_proxy": 284000,
    "total_volume_usd_baseline": 1000000,
    "calc_note_bot_proxy_never_native_birdeye": true
  },
  "fee_mint_burn_events": {
    "fee_usd_24h": 4200,
    "fee_to_vol_ratio_pct": 0.42,
    "mint_events_24h_count": 0,
    "burn_events_24h_count": 0,
    "supply_change_24h_pct": 0
  },
  "penalties_applied_to_final": [
    { "name": "lp_drawdown_gt_30",      "points": -1.5 },
    { "name": "bot_proxy_vol_gt_40_pct","points":  0.0 },
    { "name": "tag_cohort_any_gt_25",   "points":  0.0 }
  ],
  "score_final_0_10_adjusted_from_base": 7.42,
  "rating_after_advanced": "B",
  "verdict_after_advanced": "✅ ACCUMULATE"
}
```

#### Interpolated holding $ formula (0 CU — pure client)
For tag cohorts and holder list rows:

```
holding_usd_interpolated = pct_of_supply / 100 × circulating_supply_tokens × price_usd
```

- `circulating_supply_tokens` extracted from BASE `price_mc_liq` block: `mc / price_usd`.
- `price_usd` = BASE step1 token_overview `price`.
- Result is **interpolated by definition** (not native). UI MUST label rows: `holding_usd (interpolated)` → exact label as RugCheck 13-field output.

---

### C. `include=risk_history` → +30 CU → `risk_score_daily[]` (30 dp · Đức source)

```json
{
  "risk_score_daily_meta": {
    "source": "Duc (30 daily snapshots)",
    "points_requested": 30,
    "points_returned": 30,
    "missing_interpolated_count": 2
  },
  "risk_score_daily": [
    {
      "day_ts_epoch_midnight_utc": 1760000000,
      "day_label_iso": "2026-10-09",
      "final_score": 7.6,
      "rating": "B",
      "pillars": { "sec": 7.4, "smkt": 8.1, "act": 7.2, "vol": 7.5 },
      "snapshot_notes": [ "interpolated_holder_delta_day" ]
    }
  ]
}
```

- Each snapshot = full set (score + pillars). For UI charts → client chooses to plot FINAL line OR 4 pillar lines 4-color stack.
- **Gap policy**: Missing snapshot days → LINEAR INTERPOLATE between neighbors. `missing_interpolated_count` tracks how many; any `> 0` → top badge ⚠ `history_gap (N/30 interpolated)`.

---

## Example curl (Concept — client composite)

> Note: `/local/token/dd` is a **logical endpoint** only. The server today does not expose a single composite HTTP. Instead, the client (browser UI or CLI) composes these blocks by calling Birdeye endpoints directly.

**CLI equivalent (see `WORKFLOW-02-TOKEN-DD.md` §3):**

```bash
# BASE (71 CU) — no includes
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK

# STANDARD: include list + advanced_security = 71+30+21 = 122 CU
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list,advanced_security \
  --format scorecard

# DEEP: include list + adv_security + risk_history (71+30+21+30 = 152 CU)
# Telegram markdown ready → paste
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --chain sol \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list,advanced_security,risk_history \
  --list-top-n 20 \
  --history-points 30 \
  --format telegram

# View header + CU billing breakdown (no extra call — always in meta)
python3 birdeye-screener/scripts/birdeye_cli.py token-dd \
  --address BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK \
  --include list,risk_history \
  --format raw-json | jq '{ billed: .meta.cu_billed, flags: .include_flags, final: .score_final_0_10, rating: .rating }'
```

### Response billing header (always present in meta)

```json
{
  "meta": {
    "address": "BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK",
    "chain": "sol",
    "symbol": "XXX",
    "include_flags": [ "list", "advanced_security", "risk_history" ],
    "cu_breakdown": {
      "base_fast_71": 71,
      "adder_list": 30,
      "adder_advanced_security": 21,
      "adder_risk_history_30d": 30
    },
    "cu_billed_total": 152,
    "cu_saved_vs_old_standard_deep_tier": 114,
    "endpoint_calls": 6
  }
}
```

---

## Notes

1. **BASE always first**. All `include[]` blocks extend BASE; they never run standalone. This guarantees meta + price_mc_liq + core security always exist — downstream renderers never null-check them.
2. **CU billing transparency** (critical for user trust): meta contains per-flag breakdown AND total billed AND how much cheaper vs old monolithic FAST/STD/DEEP tiers 71/155/266 (user sees savings immediately = retention driver).
3. **Tag list compacted** per user request: only `% holding` + interpolated `holding_usd_interp` + count. The system doesn't return raw holder IDs inside tag cohorts; users open `include=list` if they want wallet-level rows.
4. **Liquidity concentration = include=list derived** (no extra call): from `holder_list[]` we compute LP top-2 / top-10 / top-20 sums client-side.
5. **Risk score 30d daily** is marked as from Đức (reference source) to distinguish from Birdeye native endpoints.
6. **Invalid includes are ignored, not billed**. Example: user passes `include=list,unknown_flag` → only `list` gets billed +30 CU, the unknown token is silently dropped and added to `meta.include_flags_skipped`.
7. **Non-Sol chains (EVM)**:
   - `include=advanced_security` — tag cohort and mint-burn events may be partial.
   - `include=list` — `/holder/v1/distribution` is Sol-only today. EVM → `holder_list_meta.returned_rows = 0` + reason note; NOT billed (CU adder rolled back). Partial EVM support — billing is fair; no surprise charge.
8. **Mapping to UI controls in Skill #3 (see `SKILL_CTRLS.dd` in birdeye_ui.py):**
   - Dropdown `depth` → alias (base 71 / standard 122 / deep 152)
   - 3x pill toggles: `📋 include=list (30)` · `🛡 include=advsec (21)` · `📈 include=risk_history (30)`
   - Pill toggle state changes → update CU meter *instantly* (client-side math, zero API call)
9. **Mapping to Skill #17b RugCheck**: RugCheck skill = `include=list,advanced_security` (STD tier, 122 CU) + UI renders 7-card layout instead of scorecard. Same payload bytes, different renderer = `0 CU` re-render (compliant with `makeDDRenderFromPayload` rule).
