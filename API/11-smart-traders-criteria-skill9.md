# 11 · Smart Traders Criteria (Skill #9 · Dynamic Thresholds)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| FAST 30 · STD 150 · DEEP 500 | `/smart-money/v1/token/list` (Step A) + loop `/defi/v2/tokens/top-traders` (Step B each token) + `/wallet/v1/token/list` (Step D each top20 wallet enrich) | Solana (primary); EVM future. | Skill #9: Top Smart Money Wallets. |

## Params (Dynamic User Inputs — Skill #9 Control Panel)

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `depth` / scan mode | ✅ | string enum | `fast` | fast (30) / standard (150) / deep (500 CU) | Controls how many tokens in Step B loop. |
| `min_trades_30d` | ❌ | int slider | 15 | 5–50 | Required rule R1 minimum trades 30d window. |
| `min_unique_tokens_30d` | ❌ | int slider | 8 | 3–30 | Required rule R2 minimum unique tokens traded. |
| `enforce_tag_or_winrate_50` | ❌ | boolean | true | true/false | Toggle required rule R3 (must have smart tag OR WR≥50%). |
| `blacklist_addresses` | ❌ | string (comma list) | "" | Any base58/0x addresses, separated by commas or newlines | Required rule R4 wallets to exclude. |
| `pass_score_min` | ❌ | int | 70 | 0–100 | Minimum weighted score PASS threshold (default 70). |
| `chain` | ❌ | string | `sol` | sol · bsc · base · eth | Chain scope. |

## Scoring: Required Rules (Fail = Drop / Not Smart)

| Rule ID | Description | User Input (Dynamic) | Default | Source API |
|---|---|---|---|---|
| R1 | Trade Count 30d ≥ MIN_TRADES (required) | Slider min 5→50 | 15 trades | /defi/v2/tokens/top_traders (time_frame=30d tradeCount field) |
| R2 | Unique tokens traded 30d ≥ MIN_UNIQUE | Slider 3→30 | 8 unique | Same endpoint, dedup distinct tokens across wallet trades (if needed = call wallet trade history extra CU) |
| R3 | Has tag SM/KOL/PRO (Tag ∈ {SM_OWNED, KOL_WHALE, PRO_TRADER, COPY_TARGET}) OR Win Rate ≥ 50% (if no tag) | Checkbox (toggle on/off enforce) | default on | Same endpoint tags[] array + winCount/(winCount+loseCount) |
| R4 | NOT in user BLACKLIST list (comma separated wallet addresses) | Textarea comma list | empty | User input filter |

## Weighted Score (Min 70/100 to PASS)

| Layer | Weight pts | Criteria buckets (lower/upper points) | Source |
|---|---:|---|---|
| WIN_RATE_30D | 0–40 | <30% → 0pt; 30–40% → 10pt; 40–48% → 20pt; 48–55% → 30pt; >55% → 40pt | winCount / (win+lose) 30d endpoint 06 calc |
| PNL_MULT_30D | 0–25 | <1.0× → 0; 1.0–1.5× → 8; 1.5–2.5× → 15; 2.5–4× → 20; >4× → 25pt | realizedPnl_30d / avg_holdings 30d proxy |
| SM_RANK_GLOBAL (if in list) | 0–20 | No rank → 6; ≤#1000 →10; ≤#500 →14; ≤#200 →17; ≤#50 →20 | Module 07 rows[].rank_in_sm_top100 |
| UNREALIZED_DRAWDOWN_MAX_30D | 0–15 | >50% → 0; 35–50% →4; 20–35% →8; 10–20% →12; <10% →15 | wallet max open PnL drawdown from peak (Step 6 unrealizedPnL history proxy) |

## Scan Flow (CU Budget)

```
┌─ Step A (ALL MODES, 20 CU) ──────────────────────────────────────┐
│  GET /smart-money/v1/token/list limit=50  today.                 │
│  → Collect tokens traded today with ≥ MIN_SM (≥1 SM wallet in)    │
│  → Cost so far = 20 CU                                            │
├─ Step B (per token, 10 CU × N tokens) ───────────────────────────┤
│  Mode: FAST     → 1 token (top1)               = +10 CU (Σ30)    │
│  Mode: STANDARD → 13 tokens → 13 × 10           = +130 (Σ150)    │
│  Mode: DEEP     → 48 tokens → 48 × 10           = +480 (Σ500)    │
│  GET /defi/v2/tokens/top_traders limit=50 → collect wallet rows  │
├─ Step C (CLIENT 0 CU) ───────────────────────────────────────────┤
│  Dedup wallets across all tokens collected → global wallet set    │
│  Score EVERY wallet on 4 rules required + weighted 4 layers       │
│  Filter all required rules passed AND score ≥ 70/100              │
│  Sort by composite score DESC                                    │
├─ Step D (OPTIONAL, Enrich top N wallets) 10 CU / wallet ─────────┤
│  Mode: FAST → SKIP. STD: top 5; DEEP: top 20 wallets enrich      │
│  GET /wallet/v1/token/list owner=<wallet> limit=20               │
│  → Display current holdings top tokens, tags, last moves         │
└──────────────────────────────────────────────────────────────────┘
```

## Integration Notes
- Control panel UI: 4 RULE-SLIDERS (min_trades, min_unique, checkbox-enforce-R3, blacklist textarea) + 4 WEIGHT SCORE THRESHOLD SLIDERS (user can adjust what win-rate qualifies as which bucket) + FAST / STANDARD / DEEP segmented button group + ⚡CU badge live update + 📖 View recipe toggle panel.
- SKIP real backend CLI for STANDARD/DEEP this v3 (just scaffold). FAST: call module 07 endpoint /smart-money list + show recipe result.
