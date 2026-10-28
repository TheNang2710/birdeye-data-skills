---
name: token-dd-score
description: "Should I buy this token — Birdeye Token Due-Diligence Score. Produces a 0-100 score plus an A+..F risk rating across five weighted pillars (Security, Holders, Activity, Liquidity, Smart Money), then a smooth liquidity-drawdown gate. Two depths are available — standard (token_overview + token_security + live liquidity snapshot, ~56 CU) and advanced (adds holder distribution / profile / top holders / token money flow / 24h liquidity OHLC, ~186 CU). Use when the user asks for token due diligence, token DD, token risk score, should I buy this token, rug check, holder concentration, buy/sell pressure, money flow, or a token scorecard."
argument-hint: "birdeye-cli token-dd-score --chain <sol|bsc|base|eth> --address <MINT> [--mode <standard|advanced>] [--top-n <10|20|50>] [--weights-preset <name>] [--weights <pillar=w,...>] [--rescore <run-id>] [--format <plain|json|telegram|raw-json|ui>]"
metadata:
  cliHelp: "birdeye-cli token-dd-score --help"
  cuPerStandard: 56
  cuPerAdvanced: 186
  pillars: "security, holders, activity, liquidity, smart_money"
---

# Token Due-Diligence Score

Five fixed pillars, each a weighted mean of ramped sub-scores, then a smooth
liquidity-drawdown gate. Missing sub-signals are dropped **and** their weight is removed, so a
pillar score reflects measured coverage only (weights renormalize instead of collapsing to zero).

## Core Capabilities

- Returns one verdict number rather than a field dump — for when the ask is whether to buy at all
- Composite built from five fixed pillars: Security · Holders · Activity · Liquidity · Smart Money
- Missing sub-signals are dropped and their weight removed, so a pillar reflects measured coverage instead of silently passing — each pillar reports its coverage and a `⚠ coverage_caveat` flags thin runs
- A confirmed honeypot is a hard stop: the Security pillar is forced to 0
- Ends with a smooth liquidity-drawdown gate, then maps the score to an A+..F risk rating
- Adds a score-independent `liquidity_health` label — `DYING` (liquidity down 80–99% from peak) or a red `DEAD` (≥99% down, or either pool below USD 10) — shown even when the score is still non-zero
- Liquidity depth is a **live snapshot** — total from `token_overview`, exit from `POST /defi/v3/liquidity/latest/token` — never a stale OHLC bar close; if OHLC is the fallback the value is labelled `… ago (OHLC close)`
- Every deduction names the field behind it, so any low score stays traceable
- Runs on `sol` · `bsc` · `base` · `eth` · `arc` · `robinhood`

## Flow

`birdeye-cli token-dd-score …` runs these steps against Birdeye. `standard` stops after Step 2b;
`advanced` runs all of them.

| Step | Endpoint | What it checks / produces | Mode |
|---|---|---|---|
| 1 | `GET /defi/token_overview?includes=money_flow` | price, market cap, liquidity, holder count, 24h volume, net flow — feeds **Activity** + **Liquidity** (21 CU) | both |
| 2 | `GET /defi/token_security` | honeypot flag, mint / freeze authority, ownership renouncement, buy/sell tax, top-10 concentration — the **Security** pillar (30 CU) | both |
| 2b | `POST /defi/v3/liquidity/latest/token` | live **total + exit** liquidity snapshot (5 CU) | both (Solana) |
| 3 | `/holder/v1/distribution?mode=top&top_n=N` + `/token/v1/holder-profile` | holder concentration + cohort tags (dev / bundler / sniper / insider) — the **Holders** pillar (60 CU) | advanced |
| 4 | `/defi/v3/token/holder?mode=wallet` + `/defi/v3/token/money-flow` | top holders, plus smart-money / whales / KOL buy-sell flow — the **Smart Money** pillar (40 CU) | advanced |
| 5 | `/defi/v3/liquidity/ohlc/token` | 24h liquidity drawdown series (min / max / median / p95 / trend) for the gate (30 CU) | advanced |
| 6 | — | compose: 5 pillars → weighted mean → × smooth gate → A+..F rating + `liquidity_health` | both |

`standard` = Step 1 + 2 (+ 2b on Solana) = **56 CU**. `advanced` = all steps = **186 CU**.

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → a key is resolvable, proceed.
- exit `1` → no key. Ask the user for their Birdeye API key, then run
  `birdeye-cli config --apply <KEY>` (writes `~/.config/birdeye/.env`, chmod 600).

Key resolution order: `$BIRDEYE_API_KEY` → `~/.config/birdeye/.env` → `~/.birdeye.env` → `./.env`.
If `birdeye-cli` is not on `PATH`, run `python3 birdeye_cli.py <args>` from the repo folder
(see the repo `README.md` for install).

## Usage

```bash
birdeye-cli token-dd-score --chain sol --address <MINT> --mode advanced --format plain
birdeye-cli token-dd-score --chain sol --address <MINT> --mode standard --format json
```

## Arguments

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` · `arc` · `robinhood` |
| `--address` | — | **required**, token contract / mint |
| `--mode` | `standard` | `standard` = overview + security + live liquidity snapshot (56 CU) · `advanced` = all pillars (186 CU) |
| `--top-n` | `20` | holder rows from distribution (advanced): `10` · `20` · `50` |
| `--liq-resolution` | `15m` | `auto` = 15m for the 24h window |
| `--liq-candles` | `96` | liquidity OHLC candles (max 100); 15m × 96 = 24h |
| `--pace` | off | enable the pace sub-signal in Activity |
| `--skip` | — | advanced only: `distribution,holder_profile,top_holders,token_money_flow,liquidity` |
| `--weights-preset` | `default` | alternate weight presets |
| `--weights` | — | override pillar weights, e.g. `security=0.30,holders=0.20`; omitted pillars keep their preset, then the set renormalises to 1.0 |
| `--rescore` | — | 0-CU re-score from a run-id / cache path / base64 |
| `--format` | `plain` on the CLI | `plain` · `json` · `telegram` · `raw-json` · `ui` |

## Output

All four text formats are Telegram-pasteable. `json` / `plain` are clean of HTML for bot
integration; `ui` returns the HTML renderer payload for the local console.

Read it in this order:

1. **Score + rating** — `0..100` and the A+..F band (A+ ≥ 95 = "Hot").
2. **Pillar table** — five rows, each with its own score and a **coverage** figure; a thin
   pillar shows lower coverage and may carry `⚠ coverage_caveat`.
3. **`liquidity_health`** — independent of the score: `DYING` / `DEAD` can appear on a decent
   score.
4. **Deductions** — each names the field that caused it, so any low score is traceable.
5. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

Ratings are **risk labels only** — no buy/sell recommendations.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | re-run `config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
