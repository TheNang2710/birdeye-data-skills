# 10 · Composite DD 10-Step Rating (Skill #3 FAST/STD/DEEP)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| FAST: 71 · STANDARD: 155 · DEEP: 266 | Client-side composite score + modules 01–09 subset (by mode). | All (Sol primary). | Full Skill #3 Token Due Diligence. |

## Params (Client-Side Selector)

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `depth` (mode) | ✅ | string enum | `fast` | `fast` / `standard` / `deep` | Determines which modules are included + CU budget (71/155/266). |
| `address` | ✅ | string | — | Mint or 0x40 contract | Token being analyzed. |
| `chain` | ❌ | string | `sol` | sol / bsc / base / eth | Lowercase chain id. |

## Mode to Module Mapping

| # | Module Name | CU | FAST (71) | STANDARD (155) | DEEP (266) |
|---:|---|---:|:---:|:---:|:---:|
| 01 | Token Overview + Money Flow | 21 | ✅ | ✅ | ✅ |
| 02 | Liquidity OHLC Drawdown | 15 | ❌ | ✅ | ✅ |
| 03 | Token Security v2 | 30 | ✅ | ✅ | ✅ |
| 04 | Holder Distribution top20 | 30 | ❌ | ✅ | ✅ |
| 05 | Holder Profile 5 Tags | 30 | ❌ | ✅ | ✅ |
| 06 | Top Traders Tags / PnL | 30 | ❌ | ✅ | ✅ |
| 07 | Smart Money Token List | 20 | ✅ | ✅ | ✅ |
| 08 | Trade Data Aggregates | 10 | ❌ | ✅ +20 (delta 2 windows) | ✅ +20 |
| 09 | Fee + Mint/Burn Events | 35 | ❌ | ❌ | ✅ 35 |
| 10 | Final Score (client) | 0 | ✅ | ✅ | ✅ |
| | **Σ CU by mode** | | **71** | **155** | **266** |

## Final Score Formula (Weighted)

```
BASE_10 = SEC*0.30 + SMKT*0.25 + ACT*0.25 + VOL*0.20 (each pillar 0-10 → weighted sum)
FINAL = BASE_10
      - (LPDrawdown >30% ? 1.5 : 0)   // Penalty #1 LP Drawdown
      - (BotVolProxy>40% ? 1.0 : 0)    // Penalty #2 Bot Proxy
      - Σ(tag any >25% supply ? 0.5/tag // Penalty #3 Tag Concentration
clamp(FINAL, 0, 10)
```

## Final → Rating A-F / NG Map

| Final ≥ | Rating | Label |
|---|---|---|
| 9 | S | 🌟 STRONG BUY |
| 8 | A | 🟢 BUY |
| 7 | B | ✅ ACCUMULATE |
| 6 | C | ⚠ HOLD / WATCH |
| 5 | D | 🔻 REDUCE |
| 4 | F | 🛑 SELL / AVOID |
| < 4 | NG | ❌ NO-GO |

## Integration Notes
- Control panel input selector `#dd_depth` = FAST / STANDARD / DEEP. User choose CU budget.
- CLI argv subcmd: `birdeye_cli.py dd --address <ADDR> --chain sol --depth fast → output payload json cached.
- Save 3 last runs cache to localStorage budget alert.
