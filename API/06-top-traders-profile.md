# 06 · Top Traders Profile (Wallet Tags / PnL / Win)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| 20–30 per call (pagination via limit / sort_by) | `GET /defi/v2/tokens/top_traders` | All chains. | Skill #3 Step 6 (STANDARD/DEEP). Skill #9 SmartTraders. |

## Params

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `address` | ✅ | string | — | Token addr (mint or 0x). | All chains. |
| `time_frame` | ❌ | string | `24h` | `5m / 15m / 1h / 4h / 24h / 7d / 30d` | 30d recommended for Skill9 win-rate calc. |
| `sort_by` | ❌ | string | `volumeUsd` | `volumeUsd` · `holdVolume` · `realizedPnl` · `tradeCount` | hold_volume = sort by top current large holders (recommended for Step 4 join). |
| `limit` | ❌ | int | 10 | 10–50 max. | 50 max per Birdeye docs. |
| `chain` | ❌ | string | sol | All lower chains. |

## Response Fields

| Field | Type | Nullable | Description |
|---|---|:---:|---|
| `rows[]` | array | ❌ | Top traders rows. |
| `rows[].wallet` | string addr | ❌ | Wallet pk |
| `rows[].volumeUsd` | number $ | ❌ | ⚠ lowercase `Usd` not USD. CamelCase quirk. |
| `rows[].volumeBuyUSD / volumeSellUSD` | number $ | ✅ | ⚠ uppercase `USD` (different casing from volumeUsd!). Known bug #4 docs. |
| `rows[].realizedPnl` | number $ | ✅ | Closed PnL 30 days. |
| `rows[].unrealizedPnl` | number $ | ✅ | Open PnL. |
| `rows[].tradeCount` | int | ✅ | Trades count window. |
| `rows[].winCount / loseCount` | int | ✅ | For rate calc. |
| `rows[].holdVolume` | number $ | ✅ | Current position size USD (when sort_by=hold_volume). |
| `rows[].holdAvgPrice` | number $ | ✅ | Weighted avg entry price. |
| `rows[].tags[]` | string array | ✅ | Same 5-tag vocabulary as module 05! Critical JOIN column. |

## Integration Notes
- **Step 6 JOIN:** Holder rows from module 04 → join `owner = wallet` in top-traders (match sort_by=hold_volume limit=200) → attach `tags[]` array to each holder. Also PnL & buyPrice data.
- **BotProxy% heuristic Step 6b:** Tag share inside top10 traders = insider + bundler share (count) + `tradeCount / unique wallet window ratio proxy` > 5 → wash trade Bot Vol Proxy %. Always label with ⚠ "BotProxy%" label, never just "Bot%".
- Skill #9 Smart Trader Criteria Primary source data for win_rate, pnl_mult, trade_count, tags.
