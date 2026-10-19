# Skill #3 · Token DD (Should I Buy?)

## High-Level Concept

The flagship due-diligence skill. Combines token overview, money flow, security, and smart-money data into a single **A/B/C/D/F/NG** rating with a numeric score (0–10). The "Should I buy?" answer for a token.

## Inputs

| Field | Type | Description |
|-------|------|-------------|
| `chain` | enum | sol / bsc / base / eth / arc / robinhood |
| `address` | string | Token contract address |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| Overview + money flow | `/defi/v3/token/overview` + `money_flow` | ~21 |
| Security | `/defi/v3/token/security` | 30 |
| Smart money join | `/smart-money/...` | ~20 |

**Total: ~71 CU**

## Scoring

Composite score (0–10) mapped to letter grades:

| Grade | Range |
|-------|-------|
| A | ≥ 8.5 |
| B | 7.0–8.4 |
| C | 5.5–6.9 |
| D | 4.0–5.4 |
| F | 2.5–3.9 |
| NG | < 2.5 |

Factors: liquidity, market cap, volume, holder growth, security flags, smart-money activity, money-flow direction.

## CLI

```bash
python3 birdeye_cli.py token-dd --chain sol --address <TOKEN_ADDR>
```
