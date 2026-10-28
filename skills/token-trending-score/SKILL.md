---
name: token-trending-score
description: "Compute a 0..100 momentum / trending score for a token per interval from OHLCV + liquidity + holders + security. Supports `classic` (original 6-component momentum model), `hybrid` (classic blended with wallets/volume/pace interval formula) and `momentum_only` (price / volume / liquidity only — holder + security dropped and not fetched). Use when the user asks how hot or how trending a token is, momentum score, whether it is pumping, trend strength, or multi-interval momentum for one token."
argument-hint: "birdeye-cli token-trending-score --chain <sol|bsc|base|eth> --address <MINT> [--model <classic|hybrid|momentum_only>] [--candles <n>] [--nocache] [--format <ui|json|telegram|plain|raw-json>]"
metadata:
  cliHelp: "birdeye-cli token-trending-score --help"
  cuTypical: 176
  intervals: "5m, 15m, 30m, 1h, 4h, 6h, 12h, 24h"
---

# Token Trending Score

0..100 momentum score per interval, blended from OHLCV (25–100 CU) + liquidity OHLC (20 CU) +
live liquidity snapshot (5 CU, Solana) + overview (21 CU) + holder chart (30 CU) +
holder profile (21 CU) + security (30 CU) → typical **~176 CU**.

Models:

- `classic` — original 6-component momentum score
- `hybrid` — `classic` plus wallets / volume / pace interval attention on 1h / 4h / 24h
- `momentum_only` — price / volume / liquidity only; holder + security components and gates are dropped and their endpoints are not called

## Core Capabilities

- Momentum decides trending — volume and price carry 55% of the weight; security and liquidity are 10% each
- Security and liquidity also act as continuous gates, not hard cliffs: a low value scales the score down smoothly so junk is filtered while momentum still ranks
- A gate whose input the chain does not report (for example holder breadth on some chains) is left out of the composite and the remaining gate weights are renormalised, so missing data is not counted as a zero
- Liquidity gate uses effective depth — `min(liquidity, exit liquidity)` where reported; exit liquidity is used on Solana
- Liquidity depth is read from the **live snapshot** (`token_overview` + `POST /defi/v3/liquidity/latest/token`), not a stale OHLC close; the OHLC series only supplies trend/stability, and a fallback is labelled with its `ohlc_age_seconds`
- A confirmed honeypot is the only hard stop — it collapses the gate to near zero
- Reports a score-independent `liquidity_health` badge — `DYING` (liquidity down 80–99%) or a red `DEAD` (≥99% down, or either pool below USD 10) — even when the trending score is still high
- Three models: `classic` (momentum baseline, works on any token), `hybrid` (adds the wallets / volume / pace native formula on 1h / 4h / 24h) and `momentum_only` (price / volume / liquidity only)
- `momentum_only` drops the holder + security components **and** their gates, renormalises the remaining weights (volume / swaps / price / liquidity) and never calls the holder / security endpoints; the junk gate reduces to liquidity only
- Scores 8 intervals — 5m · 15m · 30m · 1h · 4h · 6h · 12h · 24h — so short pumps and sustained trends are separated
- Raises `⚠ pipeline_gap` when required upstream data is missing instead of silently degrading
- Runs on `sol` · `bsc` · `base` · `eth`

## Flow

`birdeye-cli token-trending-score …` runs these steps against Birdeye, then composes the score.

| Step | Endpoint | What it checks / produces | Mode |
|---|---|---|---|
| 1 | `GET /defi/token_creation_info` | token age / creation context (35 CU) | always |
| 2 | `GET /defi/v3/ohlcv` | 1m candles (default 5000) for the price / volume / pace series (25–100 CU) | always |
| 3 | `GET /defi/v3/liquidity/ohlc/token` | liquidity drawdown series → stability + `liquidity_health` (20 CU) | always |
| 4 | `POST /defi/v3/liquidity/latest/token` | live **total + exit** liquidity snapshot (5 CU) | Solana |
| 5 | `GET /defi/token_overview` | price, market cap, liquidity, holder count, 24h volume (21 CU) | always |
| 6 | `GET /token/v1/holder/chart` | holder growth series — the **Holder Dynamics** component (30 CU) | `classic` / `hybrid` |
| 7 | `GET /token/v1/holder-profile` | cohort tags / holder health for **Holder Dynamics** (21 CU) | `classic` / `hybrid` |
| 8 | `GET /defi/token_security` | honeypot flag, mint / freeze, tax — the **Security** component + gate (30 CU) | `classic` / `hybrid` |
| 9 | — | classify interval status (`native` / `classic_fallback`), compute the composite `raw × gate`, `is_risky`, `liquidity_health` | always |

Typical total **~176 CU**, up to **~262 CU** when the OHLCV window is large (Solana adds the 5 CU snapshot).
`momentum_only` skips steps 6 / 7 / 8, so it costs **81 CU** less (holder chart 30 + holder profile 21 + security 30).

## Credential Pre-flight (mandatory)

**BEFORE RUNNING ANY COMMAND: run `birdeye-cli config --check`.**

- exit `0` → a key is resolvable, proceed.
- exit `1` → no key. Ask the user for their Birdeye API key, then run
  `birdeye-cli config --apply <KEY>` (writes `~/.config/birdeye/.env`, chmod 600).

Key order: `$BIRDEYE_API_KEY` → `~/.config/birdeye/.env` → `~/.birdeye.env` → `./.env`.
Fallback CLI: `python3 birdeye_cli.py token-trending-score ...` (see the repo `README.md` for install).

## Usage

```bash
birdeye-cli token-trending-score --chain sol --address <MINT> --format plain
birdeye-cli token-trending-score --chain sol --address <MINT> --model hybrid --format json
birdeye-cli token-trending-score --chain sol --address <MINT> --model momentum_only --format plain
birdeye-cli token-trending-score --chain sol --address <MINT> --candles 2000 --nocache --format json
```

## Arguments

| Flag | Default | Notes |
|---|---|---|
| `--chain` | `sol` | `sol` · `bsc` · `base` · `eth` |
| `--address` | — | **required**, token contract |
| `--model` | `classic` | `classic` · `hybrid` · `momentum_only` |
| `--candles` | `5000` | 1m candles (5000 = 100 CU, ~83h) |
| `--nocache` | off | bypass the 24h CSV cache and refetch |
| `--format` | `plain` on the CLI | `ui` · `json` · `telegram` · `plain` · `raw-json` |

## Cost

| Block | CU |
|---|---|
| Creation info (`/defi/token_creation_info`) | 35 |
| OHLCV 1m (`/defi/v3/ohlcv`) | 25–100 (by candle count) |
| Liquidity OHLC (`/defi/v3/liquidity/ohlc/token`) | 20 |
| Liquidity latest (`/defi/v3/liquidity/latest/token`) | 5 (Solana) |
| Token overview (`/defi/token_overview`) | 21 |
| Holder chart (`/token/v1/holder/chart`) | 30 |
| Holder profile (`/token/v1/holder-profile`) | 21 |
| Token security (`/defi/token_security`) | 30 |
| **Typical total** | **~176** |

~262 CU at the largest OHLCV window. Replay from cache (24h) = 0 CU.
`--model momentum_only` skips holder chart + holder profile + security, saving 30 + 21 + 30 = **81 CU** (typical total drops to **~95 CU**).

## Output

Per-interval momentum plus an overall score.

- `plain`: per-interval score table + overall verdict, clean of HTML for bot integration
- `json` / `raw-json`: the full result envelope — score, gate multipliers, per-interval rows, `liquidity_health`, `is_risky`
- `telegram`: compact momentum summary
- `ui`: per-interval score table + gate block + `liquidity_health` badge (console)

Read it in this order:

1. **Overall score + verdict** — the composite `0..100` from `raw × gate`.
2. **Per-interval rows** — each interval (`5m` … `24h`) with its score and status (`native` / `classic_fallback` on `hybrid`).
3. **Gates** — `security` / `liquidity` / `holder` multipliers and their reasons; `is_risky` when the combined gate drops below 0.5.
4. **`liquidity_health`** — independent of the score: `DYING` / `DEAD` can appear on a high trending score.
5. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

`hybrid` only uses the native formula on `1h` / `4h` / `24h`; other intervals are marked `classic_fallback`.
Under `momentum_only` the per-interval rows show only `Vol` / `Swap` / `Price` / `Liq`, the gates block has liquidity only, and the holder / security endpoints are never called.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | re-run `config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
| `pipeline_gap` | a required upstream block was missing | retry; the run is flagged instead of silently degraded |
