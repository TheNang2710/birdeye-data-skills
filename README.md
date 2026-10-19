# 🛰 Birdeye Data Skills — Hub & Test Console

A self-contained local app for running Birdeye on-chain data skills:

- **Home page** (`/`) — landing page with skill cards + setup guide.
- **Test console** (`/test`) — runs the CLI engine as a subprocess and renders
  results in a clean web UI (the "deploy screen").

> **Local-only by design** — no source code is exposed to the browser, only
> the test UI + JSON results. No external hosting required.
> The **same** `deploy-vercel/public/` folder powers both the local hub
> (port `8765`) and the Vercel deployment — one UI, one source of truth.

---

## ✨ Features

- **Landing page** with skill cards, group badges and a setup guide
- **11 skills** across 3 groups (Discover / Token / Wallet)
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
├── deploy-vercel/
│   ├── public/               # SHARED web app (local 8765 + Vercel)
│   │   ├── index.html        # Landing page (skill cards + setup guide)
│   │   ├── test.html         # Test console (deploy screen)
│   │   ├── detail.html       # Per-skill drill view
│   │   ├── hub.js / hub.css  # Shared front-end bundle
│   │   └── catalog.json      # Static skill catalog (Vercel fallback)
│   └── api/                  # Vercel serverless functions (run.py, meta.py)
├── birdeye-screener/
│   ├── scripts/
│   │   ├── birdeye_cli.py    # CLI engine (all skills)
│   │   └── modules/          # Skill modules (wallet_data, contract_dd, kline_pattern)
│   ├── requirements.txt      # Python dependencies
│   └── .env.example          # API key template
├── birdeye_ui.py             # Local hub server (serves deploy-vercel/public/)
├── server.sh                 # One-command server control
├── docs/                     # Skill workflow docs (core concepts)
└── README.md
```

---

## 🚀 How to Run Locally

### Prerequisites

- **Python 3.8+** — check with: `python3 --version`
- **pip** — comes bundled with Python
- **Internet access** (to call the Birdeye API)
- **Birdeye API key** — sign up for free at
  [birdeye.so/user/api](https://birdeye.so/user/api)

---

### Step 1: Clone the repo

```bash
git clone https://github.com/TheNang2710/birdeye-data-skills.git
cd birdeye-data-skills
```

---

### Step 2: Install dependencies

```bash
pip install -r birdeye-screener/requirements.txt
```

> Only one dependency: `requests`. No Node.js or any other framework required.

---

### Step 3: Configure the API key

There are **3 ways** — pick one:

**Option A — Via the UI (recommended):** Skip this step, go straight to Step 4,
then paste the key into the "API Key" field on the interface and click **Set**.
The key is stored in browser `localStorage` + server memory (not persisted unless
you choose persist).

**Option B — Environment variable:**
```bash
export BIRDEYE_API_KEY=your_api_key_here
```

**Option C — `.env` file:**
```bash
cp birdeye-screener/.env.example birdeye-screener/.env
# open birdeye-screener/.env and replace your_api_key_here with your real key
```

> ⚠️ Never commit the `.env` file — it is already in `.gitignore`.

---

### Step 4: Start the server

**Option A — one-command control script (recommended):**
```bash
./server.sh start        # background  → http://127.0.0.1:8765
./server.sh fg           # foreground  (Ctrl+C to stop)
./server.sh watch        # auto-restart on file change
./server.sh status       # show running state
./server.sh stop         # stop the server
```

**Option B — run the Python server directly:**
```bash
python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload
```

You will see a log like:
```
[UI] 🛰 Birdeye Data Skills Hub (32 skills) → http://127.0.0.1:8765
[UI] hot reload: ON (read UI_HTML per request)
```

---

### Step 5: Open the browser

```
http://localhost:8765/              # landing page (skill cards + setup guide)
http://localhost:8765/test          # test console (run skills)
http://localhost:8765/detail        # per-skill drill view
```

Usage:
1. Open the **test console** at `/test`
2. Pick a skill from the left column (or filter by group in the top bar)
3. Fill in the parameters in the middle form
4. Click **▶ Run**
5. View results in 4 tabs: 🖥 UI · 📄 Plain · ✈️ Telegram · { } JSON
6. Click any entry in the **History** column on the right to replay (0 CU, from local cache)

---

### Running the CLI directly (without the web UI)

You can also run each skill directly via the CLI:

```bash
cd birdeye-screener

# List trending tokens
python3 scripts/birdeye_cli.py trending-list --chain sol --interval 1h --limit 20 --format telegram

# Token due diligence
python3 scripts/birdeye_cli.py token-dd --chain sol --address <TOKEN_ADDRESS> --format rendered

# Wallet score
python3 scripts/birdeye_cli.py wallet-score --chain sol --wallet <WALLET_ADDRESS> --duration 30d --format rendered
```

See all commands:
```bash
python3 scripts/birdeye_cli.py --help
```

---

## 🔧 Server Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `8765` | Port to listen on |
| `--host` | `127.0.0.1` | Bind address (use `0.0.0.0` for LAN) |
| `--reload` | off | Re-read static UI (`deploy-vercel/public/`) from disk per request |

---

## 🧠 Core Concepts

### How it works

```
┌──────────────────────────────────────────────────────┐
│  Browser (localhost:8765)                             │
│  ┌────────────────────────────────────────────────┐  │
│  │  /       → Landing page (skill cards + setup)  │  │
│  │  /test   → Skill list → Form → Run button      │  │
│  │  Output: UI / Plain / Telegram / JSON          │  │
│  │  History sidebar (click → replay, 0 CU)        │  │
│  └──────────────┬─────────────────────────────────┘  │
└─────────────────┼────────────────────────────────────┘
                  │ POST /api/run  {script, argv}
                  ▼
┌──────────────────────────────────────────────────────┐
│  birdeye_ui.py                                        │
│  • Serves the shared UI from deploy-vercel/public/   │
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
3. `script` is whitelisted to `birdeye_cli` only — no arbitrary command
   execution.
4. `argv` tokens are rejected if they contain shell metacharacters.

---

## 📝 License

For personal / internal use. Birdeye API terms apply.
