# 04 · Holder Distribution Top-N (Skill #3 · Step 4)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| 10–30 | `GET /holder/v1/distribution` | **Solana only.** | Step 4 (STANDARD/DEEP). Skill #6 Top 20 Holders standalone. |

## Params

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `token_address` | ✅ | string | — | **⚠ NOT `address`. Sol mint addr only.** Common bug: wrong param = 400 response. |
| `mode` | ✅ | string | — | Must be `top` for top N. |
| `top_n` | ❌ | int | 20 | 10, 20, 50 (30 CU) | — |
| `include_list` | ❌ | boolean | true | true / false | Include detailed rows list. |

## Response Fields

| Field | Type | Nullable | Description |
|---|---|:---:|---|
| `top5_pct` / `top10_pct` / `top20_pct` | number 0-100 % | ❌ | Aggregate concentration percent (%). Top 5/10/20 holders% of supply. |
| `totalHolders | int | ❌ | Unique holder count mirror. |
| `rows[]` | array | ❌ | Top-N list (if include_list). Each row: |
| `rows[].owner` | string | ❌ | Base58 wallet address. |
| `rows[].amount` | number units | ❌ | Token units held (raw integer, not decimals-adjusted yet.) |
| `rows[].percent_of_supply` | number % (0-100) | ❌ | Ownership share % |
| `rows[].usd_value` | number USD | ✅ | Current holding value USD = amount × price. |
| `rows[].tag` | string | ✅ | **Client-side join inject** from Top-Traders module (step 6):** `wallet_tags` array match `owner` = wallet. | Not native. Tag values: `dev`/`bundler`/`sniper`/`insider`/`smart_trader`/`KOL-proxy`/`retail`. |

## Sample Request

```bash
# ⚠ KEY PARAM NAME = token_address NOT address — top_n=20 include_list=true
curl -s --get "https://public-api.birdeye.so/holder/v1/distribution" \
  -H "X-API-KEY: $BIRDEYE_API_KEY" \
  --data-urlencode "token_address=BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK" \
  --data-urlencode "mode=top" --data-urlencode "top_n=20" \
  --data-urlencode "include_list=true" --data-urlencode "chain=sol"
```

## Integration Notes
- Skill 17b RugCheck `holders_top_n` table STRUCTURE primary SOURCE module.
- Concentration threshold RugCheck HIGH card: `top10_pct > 40%` = HIGH severity −1.0 penalty.
- Distribution isHolding top20 top2_pct > 40% combined = Whale dump risk visual alert user.
- BotProxy% heuristic in Step 6b: BotVol proxy = tag=`insider + bundler` share top holder total percent.
