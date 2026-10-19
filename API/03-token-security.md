# 03 · Token Security v2 (Skill #3 · Step 3)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| 30 | `GET /defi/token_security?address=<ADDR>` | All chains (Sol & EVM field differences noted) | Step 3 (ALL modes). Skill #4 Security + RugCheck step 3. |

## Params

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `address` | ✅ | string | — | Mint / contract address | Sol / EVM 0x40 |
| `chain` | ❌ | string | sol | sol · bsc · base · eth | lowercase |

## Response Fields

| Field | Type | Nullable | Description |
|---|---|:---:|---|
| `ownerAddress` | string / null | ✅ | **SOL:** `null` = mint authority RENOUNCED (Safe). Non-null = live mint authority = NG mint-infinite risk. | EVM = separate `mintable` boolean field. |
| `freezeAuthority` | string / null | ✅ | SOL: null = freeze RENOUNCED. Non-null = freeze can burn user wallets. |
| `mutableMetadata` | boolean | ✅ | `false` = metadata RENOUNCED / immutable. `true` = team can change logo/token name/socials anytime. |
| `creatorPercentage` | number 0-1 | ❌ | Dev/creator holding% of supply (0-1, multiply ×100 for percent). |
| `top10HolderPercent` | number 0-1 | ❌ | Top 10 holders% platform + user combined (Sol wallet% (sum top10 wallets) |
| `top10UserPercent` | number 0-1 | ❌ | Top 10 USER-ACCOUNT holders (platform abstraction, not wallet). Distinct platforms like CEX vaults. |
| `isHoneypot` | boolean | ✅ | **EVM only.** Sol: proxy = no official exposed honeypot. |
| `lpLocked` | boolean | ❌ | Liquidity pool tokens locked ≥ 1 year (common definition). If FALSE → CRIT risk RugCheck Card #1. |
| `transferFee` | object pct | ✅ | Transfer fee / trade fee in %. |
| `maxFee` | object pct | ✅ | Max possible future fee if mutable. |
| `withholdFee` | object pct | ✅ | Withheld fee by team. |

## Sample Request

```bash
curl -s --get "https://public-api.birdeye.so/defi/token_security" \
  -H "X-API-KEY: $BIRDEYE_API_KEY" \
  --data-urlencode "address=BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK" \
  --data-urlencode "chain=sol"
```

## Integration Notes
- SEC 30% weight pillar base 4-trụ FINAL score.
- FAST mode (71 CU) includes this module (30 CU) = Step 3 71 - overview 21 + SM list 20).
- RugCheck 7-risk cards (skill 17b) = direct source module.
- RugCheck 13-overview-fields mapping:
  - MintAuthRen = ownerAddress===null
  - MetadataAuthRen = mutableMetadata===false
  - FeeAuthLive = freezeAuthority!=null || fee not burned
  - CreatorBalance% = creatorPercentage × 100
  - Transfer / Max / Withheld Fee
  - lpLocked
  - Top10HolderConc = top10HolderPercent×100 → HIGH risk > 40% threshold
- Honeypot = TRUE or mint burn penalty.
