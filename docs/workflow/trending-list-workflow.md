# `trending-list` — Public Workflow

The hottest tokens on a chain, straight from Birdeye's trending endpoint. A **pure API
passthrough**: one call, one list, **no local scoring and no re-ranking**.

## High-Level Concept

This skill does not decide what is trending — Birdeye does. The ordering and the rows are
exactly what `/defi/token_trending` returns for the chain and interval you ask for. It is
the cheap discover step you run *before* a scored view.

> Need a scored ranking? Use [`token-trending-score`](token-trending-score-workflow.md) —
> that skill owns the momentum model (`classic` / `hybrid`). This one deliberately stays a
> thin wrapper.

## At a Glance

| Step | Endpoint | What it checks / produces | Mode | CU |
|---|---|---|---:|---:|
| 1 | `GET /defi/token_trending` | the hot-token list for the chain + interval, sorted Birdeye-side | — | 30 |
| 2 | local | optional best-effort `--platform` text filter, then render | — | 0 |

One call only — **30 CU flat**. No holder, security, liquidity or scoring calls.

## Step by Step

### Step 1 — Trending feed
`/defi/token_trending` returns one row per token with rank, address, symbol, name, logo,
price, FDV, market cap, liquidity, interval volume and interval price change. The endpoint
returns **one interval per call**, so the table exposes a single `Vol(<interval>)` and
`<interval> %` column matching your `--interval`.

- `mode=selective` (default) supports all intervals; `mode=classic` supports `1h` / `4h` /
  `24h` only.
- Sorting is Birdeye-side: `rank` (asc), `volumeUSD`, `liquidity`.

### Step 2 — Render
An optional `--platform` text filter is applied client-side as a best-effort. If it cannot
be applied, the response carries a `platform_note` instead of dropping rows silently. The
`ui` format renders a dense screener-style leaderboard with summary cards; token logos carry
a small chain badge (most useful on `multi_chain`).

## Output

- `plain`: compact terminal table — rank, symbol, market cap, price, interval volume,
  liquidity, interval %.
- `json` / `raw-json`: the **upstream Birdeye payload** (`data.tokens[]`), not a wrapped
  local object — bots do not need to undo a local shape.
- `telegram`: lightweight hot-list summary.
- `ui`: screener-style card + compact leaderboard table.

Read it in this order:

1. **Rows** — rank-ordered tokens with price / market cap / liquidity / interval volume.
2. **`params` / `sort_note`** — the echo of your inputs and how the list was ordered.
3. **`⚡CU` footer** — `⚡CU: 30 (token_trending=30)`.

No local scores, gates or heuristics are attached. For a scored view, feed a row into
`token-trending-score` or `token-dd-score`.

## Cost

| Run | CU |
|---|---:|
| Any call | **30** |

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | `birdeye-cli config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |
