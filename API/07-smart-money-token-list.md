# 07 · Smart Money Token List (Skill #3 · Step 8 + Skill #8)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| 20 CU (hard-capped) | `GET /smart-money/v1/token/list` | All chains. | Skill #3 Step 8 FAST mode included (20 CU 71 total). Skill #8 standalone. |

## Params

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `limit` | ❌ | int | 20 | Hard-capped by Birdeye (max 20 returned regardless). | Ignore values >20 silently. |
| `sort_by` | ❌ | string | `smart_traders_no` | `smart_traders_no / net_flow_24h / sm_rank` | smart_traders_no = today SM wallets count traded. |
| `time_range` | ❌ | string | `1d` | `1d / 7d / 30d` | 1d day-trading SM signal. |
| `chain` | ❌ | string | sol | All supported lower chains. |

## Response Fields

| Field | Type | Nullable | Description |
|---|---|:---:|---|
| `rows[]` | array (size <= 20) | ❌ | Ranked by sort |
| `rows[].address` | string | ❌ | Token contract (join key to other DD modules on address). |
| `rows[].symbol / name` | string | ❌ | Token meta |
| `rows[].smart_traders_no` | int | ✅ | Count of Birdeye SM wallets holding/trading. |
| `rows[].rank_in_sm_top100` | int or null | ✅ | #1…#100 if in global SM top 100 today; else null. Used in SMKT scoring pillar! 🎯 |
| `rows[].net_flow_24h_usd` | number $ | ✅ | Net buy$ - sell$ from SM wallets. |
| `rows[].sm_buy_count_24h / sm_sell_count_24h` | int | ✅ | Trades count today from SM. |

## Sample Request

```bash
curl -s --get "https://public-api.birdeye.so/smart-money/v1/token/list" \
  -H "X-API-KEY: $BIRDEYE_API_KEY" \
  --data-urlencode "limit=20" \
  --data-urlencode "sort_by=smart_traders_no" \
  --data-urlencode "time_range=1d" \
  --data-urlencode "chain=sol"
```

## Integration Notes
- Used in SMKT scoring (25% pillar FINAL). rank_in_sm_top100 ≤#50 = max points +4 tier.
- 0 SM holders holding (rows empty for token) = ACT pillar score reduces.
- Skill #9 Fastest heuristic mode (30 CU) = return top ranked in this list without scanning holders.
- Fast mode Skill #3 = **21 overview +30 security +20 sm-list = 71 CU FAST exactly.**
