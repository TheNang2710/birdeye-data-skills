# 08 · Trade Data Aggregates (24h / 5m Window)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| 10 CU each | `GET /defi/v3/token/trade-data/single?address=` + `/defi/v3/token/price-stats/single` | All chains. | Step 2b (Delta Holder/Trader proxy). Skill #1 & #1b trending lists. |

## Params Trade Data

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `address` | ✅ | string | — | All tokens. |
| `time_frame` | ❌ | string | `24h` | `5m/15m/1h/4h/24h/7d/30d` | Call 24h + 48h then diff for 24h delta. |

## Response Fields

| Field | Type | Nullable | Description |
|---|---|:---:|---|
| `trade24h` | int | ❌ | Total trades (time_frame = window). |
| `uniqueWallet24h` | int | ❌ | Unique traders count window. |
| `buyVolume / sellVolume` | number $ | ✅ | Buy vs sell aggregates. |
| `buyCount / sellCount` | int | ✅ | Number of buys / sells. |
| `buy_ratio` | number 0–100% | ✅ | Compute: `buyCount / (buyCount+sellCount) ×100` proxy. |

## Integration Notes
- **Holder24hDelta & TraderDelta proxy:** call twice (24h + 48h windows) diff uniqueWallet24h − last holder proxy + 04 holder endpoint data = trends.
- VOL Score Pillar 20% FINAL = 4 window Vol trade data aggregated increasing = +1 each.
- Step 6b Bot Proxy Ratio: trade24h / uniqueWallet24h > 50 → extremely high ratio = wash trade BotProxy elevated.
