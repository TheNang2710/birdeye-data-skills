# 05 · Holder Profile 5 Tags (Skill #3 · Step 5)

## Summary Table

| CU Estimate | Endpoint URLs | Chains | Skill Step(s) |
|---|---|---|---|
| 30 | `GET /token/v1/holder-profile` | Solana only (5 tags). | Skill #6 Top20+Tags; Skill #3 Step 5 (STANDARD/DEEP). |

## Params

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `token_address` | ✅ | string | — | ⚠ NOT `address`. Sol mint addr only. | Common wrong param = 400 error (documented Bug #1). |
| `include_zero_balance` | ❌ | boolean | `false` | true/false | Exclude dust/current zero-balance past holders. |

## Response Fields — Tags Object (5 Cohorts)

Tag enum = `dev | bundler | sniper | insider | smart_trader` (5 Birdeye native tags).

| Field | Type | Nullable | Description |
|---|---|:---:|---|
| `tags.dev` | object | ❌ | Dev / Creator cohort: |
| `tags.dev.percent_of_supply` | number % (0-100) | ❌ | Holding share% of supply. |
| `tags.dev.holder_count` | int | ❌ | Number of wallets tagged. |
| `tags.dev.avg_buy_price` | number USD | ✅ | Average weighted buy price. |
| `tags.dev.pnl_usd` | number USD | ✅ | Realized + Unrealized aggregate PnL USD. |
| `tags.bundler` | object | ❌ | MEV bundler / tx-pump-up wallets. Field structure same as tags.dev. |
| `tags.sniper` | object | ❌ | Launch-sniper (first 100 wallets in, copied config). Same fields. |
| `tags.insider` | object | ❌ | Pre-marketing / internal / team insider. Same fields. |
| `tags.smart_trader` | object | ❌ | Birdeye SM-profiled wallets. Same fields. |

## Integration Notes
- **Client-side calc Holding$ per tag (T5b):** `holdingUsdTagX = tags.X.percent_of_supply / 100 × circulatingSupply × price` (requires overview module circulatingSupply & price from 01).
- KOL tags NOT native → proxy PnL_top_traders > 20k$ in module 06. Label `🤝 KOL-proxy%` when > top-traders 5-10 tags avg PnL threshold.
- Tag concentration penalty Step 10: `any tag percent_of_supply > 25%` → each = −0.5 FINAL score (Tag Concentration Penalty).
- Heavy bundler% > 20% = launch pump & dump pattern red flag.
