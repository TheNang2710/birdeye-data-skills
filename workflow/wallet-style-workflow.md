# Workflow: Wallet Style (Skill #11)

## What it does
Classifies a wallet's trading style into one of 20 named badges (e.g. "🦅 Old Hunter", "🌾 Harvester", "🐑 Retail Loser") based on trade frequency and P&L quality.

## When to use
- You want to understand *how* a wallet trades, not just *if* it's profitable.
- You're comparing wallets and want to categorize them by style.
- You want to know if a wallet is a sniper, grinder, diamond-hands, or passive investor.

## Inputs
- **Wallet address**
- **Chain** (sol / bsc / base / eth)
- **Duration**: 7d or 30d

## Step-by-step

### 1. Open Wallet Style
Go to **🧠 Wallet & Smart Money → Skill #11 · Wallet Style**.

### 2. Enter the wallet
- Paste the wallet address.
- Choose **Chain** and **Duration** (30d recommended).

### 3. Run
Click **Run**.

### 4. Read the output
- **Main badge**: emoji + name (e.g. "📈 Steady Hand"). Hover for the plain-language meaning.
- **Frequency axis**: L1 Rare / L2 Regular / L3 Frequent / L4 Machine (trades/day).
- **P&L axis**: P5 Strong Profit / P4 Net Profit / P3 Break-Even / P2 Net Loss / P1 Heavy Loss.
- **Badges**: additional context (e.g. "⚠️ Thin Sample" for low trade counts).
- **Speed subtitle** (if tx list available): median hold time.

### 5. Save & reuse
- Auto-saved to **History**. Replay for 0 CU.
- Copy buttons for address and CLI command.

## The 4×5 Grid Cheat Sheet

| | P5 Profit | P4 Profit | P3 Flat | P2 Loss | P1 Heavy Loss |
|---|---|---|---|---|---|
| **L1 Rare** | 🗡️ One-Shot | 🧘 Zen Winner | 👀 Bystander | 💧 Toe In Water | ⚰️ Wiped Out |
| **L2 Regular** | 🦅 Old Hunter | 📈 Steady Hand | ☕ Lukewarm | 🐑 Retail Loser | 🕳️ Deep Underwater |
| **L3 Frequent** | 🌾 Harvester | ⚔️ Active Winner | 🌀 Spinning Top | 💸 Fee Donor | 🩸 Bleeding Out |
| **L4 Machine** | 🖨️ Money Printer | ⚙️ Full-Auto | 🪫 Worn Down | 🔥 Gas Burner | 💥 Self-Destruct |

## CU cost
- **30d run**: ~60–90 CU
- **Replay from history**: 0 CU
