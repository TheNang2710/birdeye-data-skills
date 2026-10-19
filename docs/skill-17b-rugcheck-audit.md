# Skill #17b · RugCheck Audit (Live)

## High-Level Concept

A live audit that mirrors the rugcheck.xyz format: 7 risk cards + liquidity min/max/drawdown + holder top-20 + insider/dev/sniper/bundle cohort analysis. Returns a risk score and detailed breakdown.

## Inputs

| Field | Type | Description |
|-------|------|-------------|
| `chain` | enum | sol / bsc / base / eth |
| `address` | string | Token contract address |
| `--holders` | flag | Include holder top-20 list |

## API Calls & CU

| Step | Endpoint | CU |
|------|----------|----|
| Token security | `/defi/v3/token/security` | 30 |
| Markets (liq min/max/DD) | `/defi/v2/markets` | 20 |
| Holder list top-20 | `/holder/v1/distribution` | 30 |
| Insider/dev cohorts | `/holder/v1/...` | 21 |

**Total: ~142 CU** (holders included).

## Risk Cards

1. **Mint authority** — can the supply be inflated?
2. **Freeze authority** — can transfers be frozen?
3. **LP lock** — is liquidity locked and for how long?
4. **Top-10 concentration** — are a few wallets controlling the supply?
5. **Insider/dev holdings** — creator/dev wallet exposure
6. **Sniper/bundle activity** — MEV/sniper wallet share
7. **Buy/sell tax** — transfer fees

## CLI

```bash
python3 birdeye_cli.py rugcheck-audit --chain sol --address <TOKEN_ADDR> --holders
```
