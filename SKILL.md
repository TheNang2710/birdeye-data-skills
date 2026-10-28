---
name: birdeye-skills
description: "Master guide for the Birdeye Skills CLI — install once, set one Birdeye API key, then run any of the eight on-chain discovery & insight skills (token due-diligence, trending list, price surge, wallet score, wallet style, kline pattern, token trending, junk prediction) straight from the terminal. Use when a user wants to install the CLI, set up a Birdeye API key, or needs the command, arguments or output contract for a given skill without reading the source."
argument-hint: "birdeye-cli <skill> --chain <sol|bsc|base|eth> … --format <plain|json|telegram|raw-json|ui>"
metadata:
  cli: "birdeye-cli"
  python: ">=3.8"
  dependency: "none (stdlib only — the CLI is a thin client)"
  engine: "https://birdeye-score-engine.vercel.app"
---

# Birdeye Skills — Master Guide

One CLI, eight skills. Install it once, set one Birdeye API key, then run any skill from the
terminal. The CLI is a **thin client**: it forwards the request to a hosted scoring engine and
prints the result. You never need to open the source — this document plus each
`skills/<name>/SKILL.md` is the whole contract.

- **Entrypoint:** `birdeye-cli` (fallback: `python3 birdeye_cli.py`)
- **Requires:** Python ≥ 3.8 · one Birdeye API key · internet access
- **Skills:** `token-dd-score` · `trending-list` · `price-surge` · `wallet-score` ·
  `wallet-style` · `kline-pattern` · `token-trending-score` · `junk-predict`

## Core Capabilities

- Eight skills behind one command, one credential, one output contract
- Pure CLI onboarding — create a Birdeye key on your account, store it once, run anything
- Five formats (`plain` · `json` · `telegram` · `raw-json` · `ui`); `plain`/`json` are HTML-free
- `birdeye-cli <skill> --help` always prints the authoritative flag list for that skill
- Every response ends with a `⚡CU` footer, so API cost is never a surprise
- No install required: `python3 birdeye_cli.py <skill> …` behaves identically

---

## 1. Install

```bash
pipx install "git+https://github.com/TheNang2710/birdeye-data-skills.git"
```

Alternatives: `python3 -m pip install "git+https://github.com/…"`, or clone the repo and run
`python3 birdeye_cli.py <subcommand> …` with no install. On Windows use `python` instead of
`python3`. Confirm with `birdeye-cli --help`.

---

## 2. Configure the API key

A Birdeye key is required for every skill. Resolution order (first hit wins):

1. `$BIRDEYE_API_KEY` (env var)
2. `~/.config/birdeye/.env` — written by `config --apply`
3. `~/.birdeye.env`
4. `./.env` (project-local, git-ignored)

```bash
birdeye-cli config --check          # exit 0 = ready · exit 1 = missing
birdeye-cli config --status         # masked key (head2****tail2) + source + path
birdeye-cli config --apply <KEY>    # write ~/.config/birdeye/.env (chmod 600)
```

`config --apply` is the one-liner to hand a new user: run `--check`, and if it fails, run
`--apply <KEY>`. A key can also be passed per run with the global `--key <KEY>` flag. The
full key is never printed — only a `head2****tail2` mask.

---

## 3. Run a skill

```bash
birdeye-cli <skill> <required flags> [thresholds / mode switches] --format <fmt>
```

- **Input:** the chain plus the required subject — `--address` (token), `--wallet` (wallet) or
  `--tokens` (batch) — then any optional thresholds and mode switches.
- **Output:** the requested format, ending with the `⚡CU` cost footer.
- **Authoritative flags:** `birdeye-cli <skill> --help`.

| Skill | Answers | Mode switches | CU |
|---|---|---|---|
| `token-dd-score` | Should I trust this token? risk + A+..F rating | `--mode standard\|advanced` | 56 / 186 |
| `trending-list` | What is hot right now? | `--mode selective\|classic` | 30 |
| `price-surge` | What is surging in my market-cap band, risk-screened? | `--mode standard\|advanced` | 50 / 50-430 |
| `wallet-score` | Wallet alpha + copy-tradeability | `--duration`, `--pnl-method` | 30-110 |
| `wallet-style` | Scalper or swing? | `--duration 7d\|30d` | 60-90 |
| `kline-pattern` | Candlestick / chart pattern | `--resolution`, `--window` | 25-100 |
| `token-trending-score` | How hot / trending is a token? | `--model momentum_only\|classic\|hybrid\|human` | ~176 (~95 in momentum_only) |
| `junk-predict` | Scam / dust / junk filter (batch) | `--model unsupervised\|function\|supervised` | 21-51 / token |

---

## 4. Output formats

| Format | Use | HTML-free |
|---|---|---|
| `plain` | terminal table — **default** | yes |
| `json` | structured JSON for bots/pipelines | yes |
| `telegram` | Markdown for chat delivery | yes |
| `raw-json` | unrendered upstream payload | yes |
| `ui` | HTML payload for the web console | no |

Machines should use `--format json` or `--format plain`. The final line is always the cost
footer — `⚡CU: <total> (<breakdown>)`.

---

## 5. Errors and troubleshooting

| Code | Meaning | Fix |
|---|---|---|
| `[E401]` | bad / missing key | `birdeye-cli config --apply <KEY>` |
| `[E403]` | tier or route blocked | check plan / chain support for the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream error | retry later |

| Symptom | Cause | Fix |
|---|---|---|
| `config --check` exits 1 | no key resolvable | run `config --apply <KEY>` |
| skill exits 2 | invalid args | check `birdeye-cli <skill> --help` |
| skill exits 4 | engine / upstream error | check key & plan, then retry |
| `command not found: birdeye-cli` | not installed / not on `PATH` | re-run the install (§1) or use `python3 birdeye_cli.py` |

---

## 6. Skill index

Each skill is self-contained — its `SKILL.md` carries the credential guard, full argument
table, the step flow (which Birdeye endpoint, what it checks, in which mode), CU cost and
error map, and is the source of truth for that skill. A prose walkthrough of each flow
(high-level concept, step by step, weights, how to read the output) lives in
[`docs/workflow/`](docs/workflow/README.md).

- [`skills/token-duediligence/SKILL.md`](skills/token-duediligence/SKILL.md) — token due-diligence score
- [`skills/trending-list/SKILL.md`](skills/trending-list/SKILL.md) — hot-token list passthrough
- [`skills/price-surge/SKILL.md`](skills/price-surge/SKILL.md) — market-cap-banded surge screen with auto rug / wash / honeypot filter
- [`skills/wallet-score/SKILL.md`](skills/wallet-score/SKILL.md) — wallet alpha + copyability
- [`skills/wallet-style/SKILL.md`](skills/wallet-style/SKILL.md) — trading-style tagger
- [`skills/kline-pattern/SKILL.md`](skills/kline-pattern/SKILL.md) — candlestick patterns
- [`skills/token-trending-score/SKILL.md`](skills/token-trending-score/SKILL.md) — momentum
- [`skills/junk-predict/SKILL.md`](skills/junk-predict/SKILL.md) — junk-token filter

Ratings (A+..F) and liquidity labels are **risk labels only** — no buy/sell recommendations.
