# 09 · Fee Flow + Mint/Burn Events (Skill #3 · Steps 7 + 9)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| 20 fee-single + 15 mint-burn = ~35 | `GET /defi/v3/token/fee/single` · `GET /defi/v3/token/mint-burn-txs` | Solana fee; mint/burn All chains. | Step 7 + Step 9 (DEEP mode only). |

## Params Fee Endpoint

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `address` | ✅ | string | — | Token addr. | Sol only. |
| `interval` | ❌ | string or comma list | `24h,1h,7d` | `5m, 1h, 24h, 7d, 30d` | Multiple allowed separated by comma. |

## Response Fields Fee

| Field | Type | Nullable | Description |
|---|---|:---:|---|
| `totalFeeUsd` | number | ✅ | Window total fee USD. Sum. |
| `byDex.*` | object $ | ✅ | DEX breakdown: `jupiter`, `raydium`, `meteora`, `orca`, `pumpdotfun`, etc. |
| `byTip.*` | object $ | ✅ | `priorityFeeUsd`, `jitoTipUsd` (MEV priority). |

## Params Mint/Burn

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `address` | ✅ | string | — | Token mint/contract. |
| `limit` | ❌ | int | 10 | 5-50. |

## Response Fields Mint/Burn

| Field | Type | Nullable | Description |
|---|---|:---:|---|
| `rows[]` | array | ❌ | `{type:"mint"|"burn", amount, tx, block, time, signer}` |

## Integration Notes
- **Wash volume heuristic (Step 7):** `Fee / Vol Ratio` (totalFeeUsd / v24hUSD) < 0.1% → wash trading proxy flag. Fee-Vol < 0.1% red flag.
- Step 9 NG mint infinite trigger: `ownerAddress in security != null` + mint events count 24h ≥ 3 → NG NO-GO rating.
- DEEP mode includes these modules. STANDARD/FAST = SKIP.
