# Workflow: Contract DD (Skill #5)

## What it does
Computes a composite 0–100 safety score for a token contract from three pillars: contract safety (45%), holder structure (30%), and price action (25%).

## When to use
- Before buying a token, to check for red flags (mint authority, LP lock, taxes, honeypot).
- To compare the safety of multiple tokens.
- As a quick "is this token safe to hold?" check.

## Inputs
- **Token address**
- **Chain** (sol / bsc / base / eth)
- **Optional**: `--skip-kline` to skip the price-action pillar (saves ~25–100 CU)

## Step-by-step

### 1. Open Contract DD
Go to **🛡 Token Due Diligence → Skill #5 · Contract DD**.

### 2. Enter the token
- Paste the token contract address.
- Choose **Chain**.

### 3. Run
Click **Run**.

### 4. Read the output
- **Composite score** (0–100) with tier: 🟢 Safe (≥80) / 🟡 Caution (60–79) / 🟠 Risk (40–59) / 🔴 Danger (<40).
- **3 pillar cards**: Safety, Holders, Price.
- **Breakdown cards**: each penalty item with delta (e.g. "-5 · LP lock status unknown").
- **CU breakdown**: shows per-endpoint cost.

### 5. Save & reuse
- Auto-saved to **History**. Replay for 0 CU.
- Copy buttons for address and CLI command.

## Red Flags to Watch

| Flag | Penalty | Severity |
|------|---------|----------|
| Mint authority active | −25 | High |
| Freeze authority active | −20 | High |
| LP < 50% locked | −25 | High |
| Honeypot | −50 | Critical |
| Top-10 holders > 80% | −30 | High |
| Buy/sell tax > 10% | −15 each | Medium |

## CU cost
- **Full run**: ~86–161 CU (varies by kline candle count)
- **With --skip-kline**: ~61 CU
- **Replay from history**: 0 CU
