# 02 · Chart OHLCV + Liquidity Drawdown 24h (Skill #3 · Step 2)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| 15–25 (15 OHLCV V3 + 10 Liquidity OHLC) | `GET /defi/v3/ohlcv/get?address=` · `GET /defi/v3/liquidity-ohlc-token?address=` | Solana (primary); OHLCV V3 All. | Skill #5 (standalone); Step 2 DD (STANDARD/DEEP). |

## Params (OHLCV V3)

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `address` | ✅ | string | — | Token mint address | SOL: mint addr. |
| `type` | ❌ | string interval | `1h` | 1s · 15s · 30s · 1m · 5m · 15m · 1h · 4h · 1d | V3 supports sub-minute intervals. |
| `time_from` / `time_to` | ❌ | unix seconds | now-26h → now | — | Use integer sec. 26h window = 26 buckets 1h + 2h pad. |
| `chain` | ❌ | string | sol | All common chains | OHLCV V3 works cross-chain. |

## Params (Liquidity OHLC Token)

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `address` | ✅ | string | — | Mint address (SOL only currently) | — |
| `type` | ❌ | string | 1h | 1m · 5m · 15m · 1h · 4h · 1d | Bucket size. |
| `time_from` / `time_to` | ❌ | unix sec | last 26h | — | 26h for drawdown. |

## Response Fields (Liquidity OHLC)

| Field | Type | Nullable | Description |
|---|---|:---:|---|
| `items[]` | array | ❌ | Each bucket = `{t, tvlO (open), tvlH (high), tvlL (low), tvlC (close), changeU, changeP}` |
| `minLiq24h` | number | ❌ | min(items.*.tvlL) | Minimum liquidity 24h. |
| `maxLiq24h` | number | ❌ | max(items.*.tvlH) | Peak liquidity 24h. |
| `drawdownPct` | number | ❌ | (maxLiq24h − minLiq24h) / maxLiq24h × 100 | Rolling drawdown % worst-case. |

## Sample Request

```bash
# Last 26h 1h liquidity buckets
curl -s --get "https://public-api.birdeye.so/defi/v3/liquidity-ohlc-token" \
  -H "X-API-KEY: $BIRDEYE_API_KEY" \
  --data-urlencode "address=<MINT>" \
  --data-urlencode "type=1h" \
  --data-urlencode "time_from=$(date -v-26H +%s)" \
  --data-urlencode "time_to=$(date +%s)" \
  --data-urlencode "chain=sol"
```

## Integration Notes
- DEEP mode adds this module = +10–20 CU vs FAST 71.
- Threshold: `drawdownPct > 30%` → **LP Risk Penalty** in FINAL Step 10 scorecard (−1.5).
- Skill #5 "OHLCV + Liq Drawdown 24h" WIP = EXPOSE these 2 endpoint outputs in a standalone panel with chart rendering (future).
- For drawdown calculation always pick **PEAK 24h high / TROUGH 24h low** (not last 2 buckets).
