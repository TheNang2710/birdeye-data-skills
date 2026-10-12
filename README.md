# 🧪 Birdeye Data Skills — Test Console

A self-contained local test console for running Birdeye on-chain data skills.
Runs the CLI engine as a subprocess and renders results in a clean web UI.

> **Local-only by design** — no source code is exposed to the browser, only
> the test UI + JSON results. No external hosting required.

---

## ✨ Features

- **12 skills** across 3 groups (Discover / Token / Wallet)
- **4 output formats**: 🖥 UI · 📄 Plain · ✈️ Telegram · { } JSON
- **History sidebar** — click any past run to replay at **0 CU** (cached)
- **Light / Dark theme** toggle
- **Group filter** — keyboard shortcuts `1`–`4`
- **API key** kept in browser session + server memory (optional persist)
- **Copy-to-clipboard** command for each skill

---

## 📁 Project Structure

```
birdeye-data-skills/
├── deploy/
│   ├── index.html          # Test console UI (port 8899)
│   └── server.py           # Minimal HTTP server + CLI runner
├── birdeye-screener/
│   ├── scripts/
│   │   ├── birdeye_cli.py  # CLI engine (all skills)
│   │   └── modules/        # Skill modules (wallet_data, contract_dd, kline_pattern)
│   ├── requirements.txt    # Python dependencies
│   └── .env.example        # API key template
├── docs/                   # Skill workflow docs (core concepts)
└── README.md
```

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install -r birdeye-screener/requirements.txt
```

### 2. Set your Birdeye API key

Get a free key at [[birdeye.so/user/api](https://birdeye.so/user/api)](https://data.birdeye.so/docs/authentication).

**Option A — UI (recommended):** Start the server, then paste your key in the
API key bar at the top and click **Set**. The key is stored in browser
`localStorage` + server memory.

**Option B — Environment variable:**
```bash
export BIRDEYE_API_KEY=your_api_key_here
```

**Option C — `.env` file:**
```bash
cp birdeye-screener/.env.example birdeye-screener/.env
# edit birdeye-screener/.env and set BIRDEYE_API_KEY=your_api_key_here
```

### 3. Start the server

```bash
python3 deploy/server.py --port 8899
```

### 4. Open the console

```
http://localhost:8899
```

---

## 🔧 Server Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `8899` | Port to listen on |
| `--host` | `127.0.0.1` | Bind address (use `0.0.0.0` for LAN) |
| `--cli-path` | `../birdeye-screener/scripts/birdeye_cli.py` | Path to CLI engine |

---

## 🧠 Core Concepts

### How it works

```
┌──────────────────────────────────────────────────────┐
│  Browser (localhost:8899)                             │
│  ┌────────────────────────────────────────────────┐  │
│  │  Skill list → Form → Run button                │  │
│  │  Output: UI / Plain / Telegram / JSON          │  │
│  │  History sidebar (click → replay, 0 CU)        │  │
│  └──────────────┬─────────────────────────────────┘  │
└─────────────────┼────────────────────────────────────┘
                  │ POST /api/run  {script, argv}
                  ▼
┌──────────────────────────────────────────────────────┐
│  server.py                                            │
│  • Whitelists script (only birdeye_cli)              │
│  • Sanitizes argv (no shell metacharacters)           │
│  • Injects BIRDEYE_API_KEY into subprocess env        │
│  • Runs: python3 birdeye_cli.py <argv>               │
└─────────────────┬────────────────────────────────────┘
                  │ stdout (JSON / HTML / text)
                  ▼
┌──────────────────────────────────────────────────────┐
│  birdeye_cli.py                                       │
│  • Calls Birdeye REST API                             │
│  • Caches each run to ~/.cache/birdeye-skills-runs/   │
│  • Outputs rendered HTML or structured JSON           │
└──────────────────────────────────────────────────────┘
```

### API Key Security

- The key is **never** embedded in HTML or returned in responses.
- `/api/key-info` only returns a masked preview (`ab****yz`).
- `persist=true` writes to `~/.birdeye.env` with `0600` permissions.
- `.env` files are in `.gitignore` — they will never be committed.

### CU (Credit Unit) System

- Each skill consumes CU from your Birdeye API quota.
- **Replaying history costs 0 CU** — results are served from local cache.
- CU usage is shown as a chip after each run.

---

## 📦 Skills Catalog

### 🔥 Discover

| Skill | CU | Description |
|-------|-----|-------------|
| Trending List | 30–50 | Top trending tokens by volume/mcap/liquidity |
| Smart Wallets | 30–500 | Discover top smart-money wallets (FAST/STD/DEEP) |

### 🔍 Token

| Skill | CU | Description |
|-------|-----|-------------|
| Token DD | ~71 | Full token due diligence: scores, holders, liquidity, security |
| Contract DD | ~86 | Contract security audit + honeypot/mint/blacklist + kline |
| RugCheck Audit | ~142 | Full rugcheck security + risk history + holder concentration |
| Kline Pattern | 25–100 | Candlestick pattern detection + support/resistance |

### 📊 Wallet

| Skill | CU | Description |
|-------|-----|-------------|
| Wallet Score | 30–110 | 0–100 alpha score + copy-tradeability score |
| Wallet Style | ~90 | Trading style fingerprint: frequency × pnl × hold-time |
| Wallet Analysis | ~240 | Multi-interval PnL + top tokens + portfolio breakdown |
| Smart Money Profile | ~120 | Smart-money wallet profile: pnl, win rate, net worth |
| Smart Money Leaderboard | 90/w | Rank multiple wallets by alpha score, PnL, win rate |

---

## ⌨️ Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1` | Show All skills |
| `2` | Filter Discover group |
| `3` | Filter Token group |
| `4` | Filter Wallet group |

---

## 📚 Documentation

Detailed workflow docs for each skill are in [`docs/`](docs/):

- [Trending List Workflow](docs/trending-list-workflow.md)
- [Token DD Workflow](docs/token-dd-workflow.md)
- [Contract DD Workflow](docs/contract-dd-workflow.md)
- [Kline Pattern Workflow](docs/kline-pattern-workflow.md)
- [Wallet Score Workflow](docs/wallet-score-workflow.md)
- [Wallet Style Workflow](docs/wallet-style-workflow.md)

---

## 🔒 Security Notes

1. **Never commit your `.env` file** — it is gitignored, but double-check.
2. The default host is `127.0.0.1` (localhost only). Use `--host 0.0.0.0`
   only on a trusted network, behind a reverse proxy with authentication.
3. The server only serves `index.html` — no other static files are accessible,
   preventing source code leakage.
4. `script` is whitelisted to `birdeye_cli` only — no arbitrary command
   execution.
5. `argv` tokens are rejected if they contain shell metacharacters.

---

## 📝 License

For personal / internal use. Birdeye API terms apply.
