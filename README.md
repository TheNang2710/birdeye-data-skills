# Birdeye Data Skills

On-chain **discovery & insight skills** for [Birdeye](https://birdeye.so) data — run them
from your terminal with one command and one API key.

A single thin CLI (`birdeye-cli`) forwards each request to a hosted **scoring engine** that
runs the actual pipeline; the CLI prints the result in the format you ask for. You never
need to read the source: this document plus each `skills/<name>/SKILL.md` is the whole
contract.

- **Entrypoint:** `birdeye-cli` (or `python3 birdeye_cli.py`)
- **Requires:** Python ≥ 3.8 · a Birdeye API key · internet access
- **Skills:** `token-dd-score` · `trending-list` · `price-surge` · `wallet-score` ·
  `wallet-style` · `kline-pattern` · `token-trending-score` · `junk-predict`

## Core Capabilities

- Eight skills behind one command, one credential, one output contract
- Pure CLI onboarding: create a Birdeye key on your account, store it once, run anything
- Five output formats — `plain` · `json` · `telegram` · `raw-json` · `ui` — with `plain`/`json`
  free of HTML, ready for bots and pipelines
- Every response ends with a `⚡CU` footer, so API cost is never a surprise
- Full flag surface per skill (`birdeye-cli <skill> --help`), and every deduction names the
  field behind it, so any verdict stays traceable

## What runs here vs. what runs remotely

This repository is the **open shell**; the scoring logic is a **closed engine**.

| Layer | Where it lives | Contains |
|---|---|---|
| CLI client | this repo — [`birdeye_cli.py`](birdeye_cli.py) | argument forwarding, key handling, output rendering |
| Console UI | this repo — `public/` | the web console (shell + proxy) |
| Engine | private service | formulas, weights, ML model assets, Birdeye API calls |

The CLI sends `{argv, key}` to `https://birdeye-score-engine.vercel.app/api/run` and prints
the response. Point it elsewhere with `--engine <URL>` or `BIRDEYE_ENGINE` if you self-host
the engine.

## 1. Install

Pick one. Option A or B is the normal path; option C needs no install at all.

### A. pipx (recommended)

```bash
pipx install "git+https://github.com/TheNang2710/birdeye-data-skills.git"
```

### B. pip

```bash
python3 -m pip install "git+https://github.com/TheNang2710/birdeye-data-skills.git"
```

### C. No install — run the single file

```bash
git clone https://github.com/TheNang2710/birdeye-data-skills.git
cd birdeye-data-skills
python3 birdeye_cli.py --help        # identical arguments to birdeye-cli
```

Confirm the install: `birdeye-cli --help`.

**Windows:** use `python` instead of `python3`. If `birdeye-cli` is not found after pipx,
run `pipx ensurepath` and reopen the terminal.

## 2. Get and set the API key

1. Create an API key in your Birdeye account dashboard.
2. Store it once:

```bash
birdeye-cli config --apply <KEY>     # writes ~/.config/birdeye/.env (chmod 600)
birdeye-cli config --check           # exit 0 = ready · exit 1 = missing
birdeye-cli config --status          # masked key + source + path
```

The full key is never printed — only a `head2****tail2` mask.

Resolution order (first hit wins):

| # | Source | Notes |
|---:|---|---|
| 1 | `$BIRDEYE_API_KEY` | environment variable, highest priority |
| 2 | `~/.config/birdeye/.env` | written by `config --apply` |
| 3 | `~/.birdeye.env` | legacy location |
| 4 | `./.env` | project-local, git-ignored |

You can also pass a key for a single run: `birdeye-cli <skill> … --key <KEY>`.

## 3. Run a skill

```bash
birdeye-cli <skill> --chain <chain> [skill flags] --format <fmt>
```

- **Input** is a set of flags: the chain, the required subject (`--address` for a token,
  `--wallet` for a wallet, `--tokens` for a batch) and any thresholds or mode switches.
- **Output** is the requested format plus a `⚡CU` cost footer.
- **Discover flags:** `birdeye-cli <skill> --help` prints the full, authoritative flag list.

| Intent | Skill | Example |
|---|---|---|
| Should I trust this token? risk + A+..F rating | `token-dd-score` | `birdeye-cli token-dd-score --chain sol --address <MINT> --mode advanced --format plain` |
| What is hot right now? | `trending-list` | `birdeye-cli trending-list --chain solana --interval 24h --limit 20 --format plain` |
| What is surging in my market-cap band, risk-screened? | `price-surge` | `birdeye-cli price-surge --chain solana --interval 1h --mode standard --min-market-cap 50000 --max-market-cap 5000000 --format plain` |
| Wallet alpha + copy-tradeability | `wallet-score` | `birdeye-cli wallet-score --chain sol --wallet <ADDR> --duration 30d --format plain` |
| Scalper or swing? | `wallet-style` | `birdeye-cli wallet-style --chain sol --wallet <ADDR> --format plain` |
| Candlestick / chart pattern | `kline-pattern` | `birdeye-cli kline-pattern --chain sol --address <MINT> --resolution 15m --window 7d` |
| How hot / trending is a token? | `token-trending-score` | `birdeye-cli token-trending-score --chain sol --address <MINT> --model hybrid` |
| Scam / dust / junk filter | `junk-predict` | `birdeye-cli junk-predict --chain sol --tokens <MINT1>,<MINT2> --model unsupervised` |

## 4. Output formats

| Format | Use | HTML-free |
|---|---|---|
| `plain` | terminal table, default on the CLI | yes |
| `json` | structured JSON for bots/pipelines | yes |
| `telegram` | Markdown for chat delivery | yes |
| `raw-json` | unrendered upstream payload | yes |
| `ui` | HTML payload (the console renderer) | no |

Reading the output:

- The last line is always the cost footer — `⚡CU: <total> (<breakdown>)` — e.g.
  `⚡CU: 30 (token_trending=30)`. Budget against this number.
- Ratings (A+..F) and liquidity labels (`DYING` / `DEAD`) are **risk labels only** — the
  skills never give buy/sell recommendations.
- `--format json` is the right choice for scripting; `plain` is the right choice to read in
  a terminal.

## 5. What each skill does — flow at a glance

Each skill is a small pipeline over Birdeye endpoints. Full step-by-step detail, flags and
reading notes live in [`skills/<name>/SKILL.md`](skills/).

| Skill | Steps (Birdeye endpoints) | Modes | CU |
|---|---|---|---|
| `token-dd-score` | overview + security + live liquidity; advanced adds holder distribution/profile, top holders, money flow, 24h liquidity OHLC | `standard` / `advanced` | 56 / 186 |
| `trending-list` | one `/defi/token_trending` call, no local scoring | — | 30 |
| `price-surge` | token-list v3 surge feed; advanced hydrates top rows (top traders, holder profile, optional security) | `standard` / `advanced` | 50 / 50-430 |
| `wallet-score` | PnL summary + per-token rug% + first-funded + portfolio | — | 30-110 |
| `wallet-style` | PnL summary + PnL details + `tx_list` | — | 60-90 |
| `kline-pattern` | one OHLCV call | — | 25-100 |
| `token-trending-score` | creation info + OHLCV + liquidity OHLC (+ live snapshot) + overview + holder chart/profile + security | `classic` / `hybrid` | ~176 |
| `junk-predict` | token overview (+ holder distribution) per token | 3 models | 21-51 / token |

Every skill's `SKILL.md` carries its own credential guard, argument table, step flow
(which API, what it checks, in which mode), CU cost and error map. The same flows in prose —
high-level concept, step by step, weights and how to read the output — live in
[`docs/workflow/`](docs/workflow/).

## 6. Exit codes

| Exit | Meaning | CU spent? |
|---:|---|---|
| 0 | Success | actual CU |
| 1 | No Birdeye API key configured | 0 CU |
| 2 | Invalid arguments / unknown command | 0 CU |
| 3 | API key missing at runtime | 0 CU |
| 4 | Upstream / engine error (bad key, plan block, rate limit, network) | partial possible on 429 |
| 5 | Post-response invariant failed — `pipeline_gap` badge | CU (already called) |

## 7. Local console UI (optional)

The repo also ships a **web console** — a frontend plus a tiny local proxy over the same
engine. Zero dependencies (stdlib only), no build step. Clone, start one process, open the
browser.

```bash
git clone https://github.com/TheNang2710/birdeye-data-skills.git
cd birdeye-data-skills

./server.sh start      # macOS / Linux → http://127.0.0.1:8765/
python server.py       # Windows (cmd / PowerShell), then open the URL it prints
```

Open <http://127.0.0.1:8765/>, then paste your Birdeye API key into the Key bar (browser-only)
— or save it to this project's `.env`, or export `BIRDEYE_API_KEY` before starting.

The console gives every skill a point-and-click form, the same five output formats, a
collapsible **History** panel with 0-CU replay, and a copy-ready `cURL` per run. The frozen v1
console is at `/v1`; the hosted build is at <https://birdeye-data-skills.vercel.app>.

Controls: `./server.sh {start|stop|restart|fg|watch|status}`. Full guide —
[`docs/local-console.md`](docs/local-console.md).

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `config --check` exits 1 | no key resolvable | `birdeye-cli config --apply <KEY>` |
| skill exits 3 | key missing at runtime | same as above |
| skill exits 4 | engine/upstream error | check the key and plan, then retry |
| `command not found: birdeye-cli` | not on `PATH` | re-install (§1) or use `python3 birdeye_cli.py` |
| `engine error: engine_unreachable` | no network / engine down | retry, or set `--engine <URL>` |

## Notes

- Standard `token-dd-score` pulls overview + security + a live liquidity snapshot (~56 CU);
  advanced adds holder distribution, holder profile, top holders, token money flow and 24h
  liquidity OHLC (~186 CU).
- The "current" liquidity / exit-liquidity figure is a **live snapshot** (`token_overview` +
  `POST /defi/v3/liquidity/latest/token`), never a stale OHLC bar close.
- `trending-list` is deliberately thin: one `/defi/token_trending` call, one list.
- `price-surge` starts from token list v3; `standard` is a single 50 CU call, `advanced`
  hydrates at most `--top` rows. Excluded rows stay visible with their reason;
  `--no-auto-filter` keeps them all.
- Ratings are risk labels only — no buy/sell recommendations.
