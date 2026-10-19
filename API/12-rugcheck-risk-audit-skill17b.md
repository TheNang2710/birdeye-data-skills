# 12 · RugCheck-Style Risk Audit (Skill #17b · 90 CU)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| 90 (21 + 30 + 30 + 19 buffer) | Module 01 (overview) + 03 (security) + 04 (holders top20). Optional 05 tags for join. | Solana primary. EVM in future. | Skill #17b RugCheck Risk Audit standalone. |

## Params

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `address` | ✅ | string (mint) | — | Base58 mint address | Solana token contract (primary). |
| `chain` | ❌ | string | `sol` | sol · bsc · base · eth | Currently SOL only. |
| `holders_top_n` | ❌ | int | 20 | 10 / 20 / 50 | Max rows in holders_top_n table (affects CU). |

## CU 90 Breakdown Exact

| Module | CU |
|---|---:|
| 01 Token Overview + Money Flow | 21 |
| 03 Token Security v2 | 30 |
| 04 Holder Distribution top 20 (for holders table) | 30 |
| Buffer (edge cases, API overhead) | +19 |
| **TOTAL** | **90** |

## Final JSON Response Structure (Full Shape)

```jsonc
{
  "address": "...", "chain": "sol", "symbol": "...", "name": "...",
  "snapshot_time": "ISO", "cu_used_total": 90, "latency_ms": 1200,
  "overview_13": {
    "supply": 1.23e9, "creator_address": "58 char base58",
    "creator_balance_pct": 3.7, "market_cap_usd": 1234567.89,
    "holders": 2847, "mint_auth_renounced": true,
    "metadata_auth_renounced": true, "transfer_fee_pct": 0.0,
    "max_fee_pct": 0.0, "fee_authority_live": false,
    "withheld_fee_auth_live": false, "lp_locked_pct": 87.4,
    "liquidity_usd": 54321.00
  },
  "risks_7": [
    {"id":"lp_unlocked","severity":"CRIT","passed":false,"threshold":"lp_locked ≥ 90","detail":"87.4% locked < 90","penalty":-1.5},
    {"id":"top10_conc","severity":"HIGH","passed":false,"threshold":"top10 ≤ 40","detail":"Top 10 = 54%","penalty":-1.0},
    {"id":"low_liquidity","severity":"MED","passed":true,"threshold":"≥ 25k $","detail":"54k > 25k","penalty":0},
    {"id":"mc_per_holder","severity":"MED","passed":true,"threshold":"MC/h ≤ 500$","detail":"MC/holder=434$ ≤500","penalty":0},
    {"id":"few_lp_provider","severity":"LOW","passed":true,"threshold":"≥3 LPs distinct","detail":"5 LPs detected","penalty":0},
    {"id":"transfer_fee","severity":"LOW","passed":true,"threshold":"≤ 5% fee","detail":"0% fee","penalty":0},
    {"id":"mutable_meta","severity":"LOW","passed":false,"threshold":"meta RENOUNCED","detail":"Metadata mutable OFF","penalty":-0.2}
  ],
  "holders_top_n": [
    {"rank":1,"owner":"Base58","owner_tag":"dev","amount":1.23e8,"percent_of_supply":10.01,"usd_value":123456.78,"avg_buy_price_usd":0.00083,"pnl_usd":23456.78,"pnl_pct":23.4}
  ],
  "final": {
    "sum_penalty": -2.7, "raw_score_base7": 7.0, "rugcheck_final_score": 4.3,
    "rating": "MEDIUM RISK",
    "verdict": "WATCH · Wait team lock LP to 90%."
  }
}
```

## 7 Risk Thresholds Penalty Table

| id | Severity | TRUE(PASS) condition | Penalty |
|---|:---:|---|---:|
| lp_unlocked | CRIT 🔴 | lp_locked_pct ≥ 90 | −1.5 |
| top10_conc | HIGH 🟠 | top10Holder% (module 03) ≤ 40 | −1.0 |
| low_liquidity | MED 🟡 | liquidity_usd ≥ 25 000 | −0.5 |
| mc_per_holder | MED 🟡 | MC / holders ≤ 500 USD avg | −0.5 |
| few_lp_provider | LOW 🔵 | distinct LPs pool wallet in top-holder list ≥ 3 | −0.3 |
| transfer_fee | LOW 🔵 | transfer_fee ≤5% AND max_fee ≤10% | −0.2 |
| mutable_meta | LOW 🔵 | metadata auth renounced = true | −0.2 |

## Integration Notes
- UI scaffold: Skill #17b `rugcheck_risk_audit` → drill mode control proposal panel. Output renderer = 3 blocks (overview_13 fields grid, 7 risk cards severity-colored, holders table).
- Rating final = sum all penalties added to 7.0 base → map LOW/MEDIUM/HIGH/CRITICAL RISK bands.
- Positioning in overall workflow: Skill #3 DD Next-Actions = one click deep link run RugCheck for same address.
