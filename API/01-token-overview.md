# 01 · Token Overview + Money Flow (Skill #3 · Step 1)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| 21 (18 base + 3 money_flow include) | `GET /defi/token_overview?address=<ADDR>&includes=money_flow` | All (Solana primary) | Step 1 (FAST, STANDARD, DEEP) |

## Params

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `address` | ✅ | string (mint/EVM) | — | Mint addr 32-44 bs58 SOL; 0x40 EVM | Token contract address. SOL = mint. |
| `includes` | ❌ | string | none | `money_flow` (+3 CU), `circulating_supply` | Multiple: comma separated. Without `money_flow` = 18 CU only. |
| `chain` | ❌ | string | sol | sol · bsc · base · eth · arb · matic | Chain id lowercase. |

## Response Fields

| Field | Type | Nullable | Description |
|---|---|:---:|---|
| `address` | string | ❌ | Echo input address. |
| `symbol` | string | ❌ | Ticker symbol (uppercase usually). |
| `name` | string | ❌ | Full token name. |
| `price` | number (float64) | ❌ | Last trade USD price. |
| `priceChange{1h,4h,24h}Percent` | number (%) | ✅ | Price change percent vs 1h/4h/24h ago. Field camelCase. |
| `marketCap` | number | ✅ | Market cap USD = price × circulating_supply if present. |
| `fdv` | number | ✅ | Fully diluted valuation = price × total supply. |
| `liquidity` | number | ❌ | Aggregated current liquidity USD across DEX pools. Snake_case alias `liquidity` OK. |
| `holder` | int | ✅ | ⚠ **Snake_case!** Not `holders`. Unique wallet holders count. |
| `v24hUSD` | number | ✅ | Volume USD past 24h. |
| `trade24h` | int | ✅ | Total trades 24h window. |
| `uniqueWallet24h` | int | ✅ | Unique traders 24h window. |
| `global_fees_paid` | number | ✅ | ⚠ Snake_case. Total fees paid 24h across DEXes USD. |
| `circulatingSupply` | number | ✅ | Circulating token units. |
| `supply` | number | ✅ | Total supply if exposed (not all chains). |
| `moneyFlow[]` | array | ✅ | ⚠ `includes=money_flow` required. 32 frames default. Each frame: `{frame, volumeBuyUsd, volumeSellUsd, netUsd, walletBuy, walletSell}`. |

## Sample Request (curl)

```bash
curl -s --get "https://public-api.birdeye.so/defi/token_overview" \
  -H "X-API-KEY: $BIRDEYE_API_KEY" \
  --data-urlencode "address=BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK" \
  --data-urlencode "includes=money_flow" \
  --data-urlencode "chain=sol" \
  | python3 -m json.tool | head -40
```

## Integration Notes
- FAST mode (71 CU skill 71) uses ONLY this module (21 CU) as the core price/MC/holder/money-flow base.
- For non-metadata (holder holder>
- `holder` field is the PRIMARY holder count source. DO NOT confuse with `holder-profile endpoint. Add link link! There is NO `holders` field: returns snake_case `holder`, it: single holder count. snake_case singular!
- Wallet 24h Delta Proxy = `uniqueWallet24h` (24` window holder change change window diff 2 windows.
- Do NOT not call a `/defi/netflow-separate-endpoint`; use `moneyFlow` frame data inside token_overview +3.
