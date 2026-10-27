---
name: birdeye-skills
description: "Master guide for the Birdeye Skills CLI — install once, then run any of the eight on-chain discovery & insight skills (token due-diligence, trending list, price surge, wallet score, wallet style, kline pattern, token trending, junk prediction) straight from the terminal. Use when a user wants to install the CLI, set up a Birdeye API key, or needs the command for a given skill without reading the source."
argument-hint: "birdeye-cli <skill> --chain <sol|bsc|base|eth> … --format <ui|json|telegram|plain>"
metadata:
  cli: "birdeye-cli"
  python: ">=3.10"
  dependency: "requests (only third-party dep)"
---

# Birdeye Skills — Master Guide

One CLI, eight skills. Install it once, set one API key, then run any skill from the
terminal. You never need to open the source: this document is the whole contract —
install, configure, run, read the output. Each skill also has its own
`skills/<name>/SKILL.md` with flags, cost and error map.

- **Entrypoint:** `birdeye-cli`
- **Requires:** Python ≥ 3.10 · one third-party dep (`requests`)
- **Skills:** `token-dd-score` · `trending-list` · `price-surge` · `wallet-score` · `wallet-style` ·
  `kline-pattern` · `token-trending-score` · `junk-predict`

## Core Capabilities

- Eight skills behind one command, one credential, one output contract
- Runs fully offline-installable — no source browsing required, this doc is enough
- Four machine-safe output formats (`ui` · `json` · `telegram` · `plain`) plus `raw-json`
- `json` and `plain` are HTML-free, ready for bots and pipelines
- Per-run CSV cache replays any result at **0 CU** (`history-list` → `history-render`)
- Every response ends with a `⚡CU` footer, so cost is never a surprise

---

## 1. Install

Pick one. Option A or B is the normal path; D needs no install at all.

### A. From the folder you were given (recommended)

```bash
cd <path-to>/new
pipx install -e .
```

`-e` (editable) matters: it keeps `skills/` and `modules/` resolvable at runtime.
If `pipx` is unavailable: `python3 -m pip install -e .`.

### B. From a private Git repo (no source publication)

```bash
pipx install "git+https://<TOKEN>@github.com/<org>/<repo>.git@main#subdirectory=new"
```

`<TOKEN>` is a read-only personal access token — the repo stays private, the user only
needs the token and the URL. Drop `@main` to track the default branch, or pin a tag.

### C. From a built wheel

```bash
pip install ./birdeye_skills_cli-1.0.0-py3-none-any.whl
```

### D. No install

```bash
cd <path-to>/new
python3 birdeye_cli.py <subcommand> …      # identical arguments to birdeye-cli
```

Confirm the install: `birdeye-cli --help`.

---

## 2. Configure the API key

A Birdeye key is required for every skill. The CLI resolves it in this order (first hit
wins):

1. `$BIRDEYE_API_KEY` (env var)
2. `~/.config/birdeye/.env` — written by `config --apply`
3. `~/.birdeye.env`
4. `./.env` (skill-local, git-ignored)

```bash
birdeye-cli config --check          # exit 0 = ready · exit 1 = missing
birdeye-cli config --status         # masked key (head2****tail2) + source + path
birdeye-cli config --apply <KEY>    # write ~/.config/birdeye/.env (chmod 600)
```

`config --apply` is the one-liner to hand a new user: run `--check`, and if it fails,
run `--apply <KEY>`. The full key is never printed — only a `head2****tail2` mask.

---

## 3. Run a skill

```bash
birdeye-cli <skill> [flags] --format <ui|json|telegram|plain|raw-json>
```

| Skill | What it answers | Example |
|---|---|---|
| `token-dd-score` | Should I trust this token? risk + A+..F rating | `birdeye-cli token-dd-score --chain sol --address <MINT> --mode advanced --format json` |
| `trending-list` | What is hot right now on this chain? | `birdeye-cli trending-list --chain sol --interval 24h --limit 20 --format plain` |
| `price-surge` | What is surging in my market-cap band, risk-screened? | `birdeye-cli price-surge --chain solana --interval 5m --mode min --min-market-cap 50000 --max-market-cap 5000000 --format plain` |
| `wallet-score` | Wallet alpha + copy-tradeability | `birdeye-cli wallet-score --chain sol --wallet <ADDR> --duration 30d --format plain` |
| `wallet-style` | Scalper or swing? trading-style tag | `birdeye-cli wallet-style --chain sol --wallet <ADDR> --format plain` |
| `kline-pattern` | Candlestick / chart pattern for a token | `birdeye-cli kline-pattern --chain sol --address <MINT> --resolution 15m --window 7d` |
| `token-trending-score` | How hot / trending / momentum a token is | `birdeye-cli token-trending-score --chain sol --address <MINT> --model hybrid` |
| `junk-predict` | Scam / dust / junk-token filter | `birdeye-cli junk-predict --chain sol --tokens <MINT1>,<MINT2> --model unsupervised` |

Common flags (every skill):

| Flag | Notes |
|---|---|
| `--chain` | `sol` · `bsc` · `base` · `eth` |
| `--format` | `ui` (default) · `json` · `telegram` · `plain` · `raw-json` |
| `--nocache` | bypass the CSV cache and refetch |

Per-skill flags, cost and error handling live in each `skills/<name>/SKILL.md`; the
skill's own help is always authoritative: `birdeye-cli <skill> --help`.

---

## 4. Output formats

| Format | Use | HTML-free |
|---|---|---|
| `ui` | HTML payload for the local console | no |
| `json` | clean structured output | yes |
| `plain` | plain text for shells/logs | yes |
| `telegram` | Markdown for chat delivery | yes |
| `raw-json` | unrendered upstream payload | yes |

Machines and bots should always use `--format json` or `--format plain`.

---

## 5. Save CU — replay any run at 0 CU

Every run is cached. Instead of re-running the same inputs, list and re-render:

```bash
birdeye-cli history-list                 # recent runs (id · skill · inputs · CU)
birdeye-cli history-render <run_id>      # re-emit a run in any format — 0 CU
```

Prefer a cached replay over a re-run whenever the inputs have not changed. Watch the
`⚡CU` footer on every response to budget accordingly.

---

## 6. Optional — local console

A stdlib-only web console (port 8765) that runs each skill and renders the `ui` payload:

```bash
./server.sh start      # background → http://127.0.0.1:8765/
./server.sh fg         # foreground
./server.sh watch      # auto-restart on file change
./server.sh stop
```

---

## 7. Errors and troubleshooting

| Code | Meaning | Fix |
|---|---|---|
| `[E401]` | bad / missing key | `birdeye-cli config --apply <KEY>` |
| `[E403]` | tier or route blocked | check plan / chain support for the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream error | retry later |

Config troubleshooting:

| Symptom | Cause | Fix |
|---|---|---|
| `config --check` exits 1 | no key resolvable | run `config --apply <KEY>` |
| skill exits 2 | missing key at runtime | same as above |
| `command not found: birdeye-cli` | not installed / not on `PATH` | re-run the install (§1) or use `python3 birdeye_cli.py` |

---

## 8. Skill index

Each skill is self-contained — its `SKILL.md` carries the credential guard, flags, CU
cost and error map, and is the source of truth for that skill:

- [`skills/token-duediligence/SKILL.md`](skills/token-duediligence/SKILL.md) — token due-diligence
- [`skills/trending-list/SKILL.md`](skills/trending-list/SKILL.md) — hot-token list passthrough
- [`skills/price-surge/SKILL.md`](skills/price-surge/SKILL.md) — market-cap-banded price-surge screen with rug / wash / honeypot auto-filter
- [`skills/wallet-score/SKILL.md`](skills/wallet-score/SKILL.md) — wallet alpha + copyability
- [`skills/wallet-style/SKILL.md`](skills/wallet-style/SKILL.md) — trading-style tagger
- [`skills/kline-pattern/SKILL.md`](skills/kline-pattern/SKILL.md) — candlestick patterns
- [`skills/token-trending-score/SKILL.md`](skills/token-trending-score/SKILL.md) — momentum
- [`skills/junk-predict/SKILL.md`](skills/junk-predict/SKILL.md) — junk-token filter
