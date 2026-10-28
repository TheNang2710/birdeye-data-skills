# `price-surge` — Public Workflow

Find tokens **surging right now inside a market-cap band**, then automatically remove the
ones carrying obvious rug / wash / honeypot risk.

## High-Level Concept

The feed is Birdeye's **token list v3** (`/defi/v3/token/list`). That endpoint already
accepts the surge, liquidity, volume and market-cap filters **server-side**, so the cheap
tier is a single call. On top of it the skill runs a **two-pass risk screen** and, in
`advanced` mode, hydrates a bounded number of rows with per-token top-trader and
holder-health data — plus an optional per-token security check (`--with-security`).

The caller only chooses the chain, the surge window, the market-cap band and the caps;
the CLI decides what to fetch and what to exclude.

## At a Glance

| Step | Endpoint | What it checks / produces | Mode | CU |
|---|---|---|---:|---:|
| 1 | `GET /defi/v3/token/list` | the surge feed: price change, market cap, liquidity, volume, trades, holders for the band | both | 50 |
| 2 | local | pass-1 structural screen on the list rows | both | 0 |
| 3 | `GET /defi/v2/tokens/top_traders` | KOL buyer count + profitable-wallet ratio per hydrated row | advanced | 30/row |
| 4 | `GET /token/v1/holder-profile` | cohort tag distribution (dev · bundler · sniper · insider) per hydrated row — Solana only | advanced | 30/row |
| 5 | `GET /defi/token_security` | confirmed honeypot, tax, rug proxies, dev-hold / top-10 concentration per hydrated row | advanced + `--with-security` | 30/row |
| 6 | local | render kept rows + an *Auto-filtered* table carrying each `exclude_reason` | both | 0 |

`--top` bounds how many rows Step 3–5 hydrate, so advanced spend is predictable.

## Step by Step

### Step 1 — Surge feed
One call returns the tokens that match your surge, market-cap, liquidity, volume, trade and
holder filters, with price, market cap, FDV, liquidity, holders, interval volume, interval
price change and trade count. Because the band and thresholds are applied server-side, the
market-cap range costs nothing extra.

### Step 2 — Pass-1 structural screen (always on)
Cheap rug / wash proxies computed from the list row itself:

| Reason | Checks |
|---|---|
| `stale_market_cap` | market cap above FDV (inconsistent snapshot) |
| `no_liquidity` / `thin_liquidity` | zero or thin liquidity vs market cap (`--max-liq-mcap-ratio`) |
| `zero_holders_with_trades` | holders = 0 while trades > 0 |
| `honeypot_proxy` | buys present but **no sell side** in 24h |
| `wash_trade_proxy` | 24h trades / 24h unique wallets above `--max-trades-per-wallet` |

### Step 3 — Top traders (advanced)
Per hydrated row: KOL buyer count and profitable-wallet ratio from `/defi/v2/tokens/top_traders`.
KOL is not a native Birdeye tag, so the counter is best-effort and reports *n/a* rather than
a misleading `0`.

### Step 4 — Holder profile (advanced, Solana)
Cohort tag distribution (dev · bundler · sniper · insider) plus the profitable-wallet share.
Solana-only; skipped and flagged on other chains (`--no-holder-health` to opt out).

### Step 5 — Security check (advanced, `--with-security`)
Per hydrated row: confirmed honeypot, mint / freeze renouncement, metadata open-source
status, LP lock, buy/sell tax and top-10 concentration. Security doubles as the top-10%
source on every chain, so no separate holder-distribution call is needed.

### Step 6 — Pass-2 advanced checks + render
For hydrated rows only:

| Reason | Checks |
|---|---|
| `honeypot` / `honeypot_tax` / `high_transfer_tax` | confirmed honeypot or transfer fee above threshold |
| `rug_pull_risk` | LP not locked while mint / freeze / metadata authority is still live |
| `dev_hold_over_limit` / `high_dev_hold` | dev holding above `--max-dev-hold-pct` |
| `top10_over_limit` / `top10_concentration` | top-10 above `--max-top10-pct` |
| `low_kol_buyers` | KOL buyer count below `--min-kol-buyers` |

Every excluded row keeps its **reason** and is listed in the *Auto-filtered* table, so the
screen is reversible (`--no-auto-filter`) and auditable.

## Scoring (high level)

There is no composite score — the skill is a **filter**: rows that pass every active cap are
kept and carry `risk_flags`; rows that fail are moved to *Auto-filtered* with an
`exclude_reason`. Dev-hold and top-10 caps only fire when `--with-security` supplied the
values; otherwise those fields stay empty.

## Output

- `plain`: compact terminal table.
- `json` / `raw-json`: the full envelope — `params`, scan counts (`n_scanned` / `n_rows` /
  `n_excluded` / `n_hydrated`), every `dropped` row with its reason, plus `raw_response`.
- `telegram`: per-token guard summary.
- `ui`: compact list-row table + a stat strip + one collapsed *health* cell and one collapsed
  *security* cell + the *Auto-filtered* table.

Read it in this order:

1. **Kept rows** — with `risk_flags` and the basic/security/holder fields filled where hydrated.
2. **Auto-filtered table** — each excluded row with its `exclude_reason`.
3. **Counts** — `n_hydrated` (how many rows paid for advanced data) and `n_excluded`.
4. **`⚡CU` footer** — `⚡CU: <total> (<breakdown>)`.

## Cost

| Tier | Calls | CU |
|---|---|---:|
| `standard` | token list v3 | **50** flat |
| `advanced` | list + per hydrated row: top traders, and on Solana holder profile | 50 + 60 × hydrated (30 on non-Solana) |
| `advanced --with-security` | as above + security per hydrated row | 50 + 90 × hydrated (60 on non-Solana) |

`--top` bounds the hydrated row count; holder profile is Solana-only.

## Errors

| Message | Meaning | Action |
|---|---|---|
| `[E401]` | bad key | `birdeye-cli config --apply <KEY>` |
| `[E403]` | tier / route blocked | key lacks access to the endpoint |
| `[E429]` | rate-limited | back off and retry |
| `[E500]` | Birdeye upstream | retry later |

Holder profile is Solana-only; on other chains it is skipped and flagged.
