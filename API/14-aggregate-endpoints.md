# 14 · Aggregate Composite Endpoints (1-call = full skill payload)

> **Concept source:** User explicit request: "Thiết kế API là task riêng để design ra API cơ không phải làm skill. Có skill đang gọi nhiều API quá tôi muốn làm kiểu module và 1 API là đủ ấy."
>
> Aggregate endpoints live under `/api/v1/*`. Each route = ONE HTTP call from the agent/skill. Internally the Hub fans out to multiple Birdeye micro-APIs in parallel/series, exactly as the existing CLI/skill would, then **shapes + merges + labels the return payload** using the `include[]` selector system from /API/13. Billing is transparent: every response carries `meta.cu_breakdown` (same keys as /API/13) + `meta.cu_billed_total` at the top level.
>
> External callers (LLM agents, 3rd party tools, Telegram bots) **never** talk to Birdeye endpoints directly — they only hit 1 of these 4 aggregate URLs.

---

## 0. Endpoint Inventory (4 routes)

| # | Aggregate URL | Skill powered | CU (min / std / deep) | Internal fan-out Birdeye calls | Include selector support |
|--:|---|---|---:|---|---|
| 1 | `/api/v1/trending/simple` | #1 Trending List (Mode-B) | 30 · 30 · 50 | `/trending/v1` + price batch | ❌ (mode param only) |
| 2 | `/api/v1/trending/v3`   | #1b V3 Reliable List       | 50 · 80 · 120 | `/token/v3/list` + optional price/mc/liq enrichment | ✅ `include=extra_fields,security_shallow` |
| 3 | `/api/v1/token/dd`       | #3 Token DD                | 71 · 122 · 152 | BASE 3 micro-calls + optional list(1) + advsec(3) + hist30d(1) = up to 7 calls → 1 payload | ✅ `include=list,advanced_security,risk_history` |
| 4 | `/api/v1/token/rugcheck` | #17b RugCheck Risk Audit   | 71 · 122 · 152 | **Exact same call graph & bytes as /token/dd** — only the `kind` wrapper differs. Renderer is consumer-side. | ✅ same includes as /token/dd |

> **0-CU format-switch guarantee**: the aggregate layer always returns JSON payload with a **machine-readable** `kind` field. Consumers (CLI / UI / Agent) can re-render as scorecard / 7-card rug / plain / Telegram by reading the same bytes. No second aggregate call is ever needed to change format.

---

## Params

Global query-string parameters shared across all `/api/v1/*` endpoints. Per-endpoint specific params are listed in each endpoint section.

| Name | Scope | Req? | Type | Default | Enum / Range | Notes |
|---|---|:---:|---|---|---|---|
| `chain` | ALL endpoints | ❌ | string | `sol` | `sol` / `bsc` / `base` / `eth` | Chain id lowercase. |
| `limit` | trending-simple / trending-v3 | ❌ | int | `40` | 10…100 | Paginated; 100 max upstream. |
| `sort_by` | trending-* | ❌ | string | endpoint default | `rank` / `volumeUSD` / `mc` / `holders` | Post-filter sort. |
| `platform` | trending-* | ❌ | csv | `` | `pump.fun,raydium,moonshot,…` | Token launch-platform filter. |
| `address` | token-dd / token-rugcheck | ✅ | string | — | Sol base58 32–44 / EVM `0x40` | Target token address. |
| **`include[]`** | trending-v3 / token-dd / token-rugcheck | ❌ | csv string[] | `` | **v3**: `extra_fields` · `security_shallow`; **DD/rug**: `list` · `advanced_security` · `risk_history` | Order-independent. Each valid token triggers a labeled CU adder **AND** materializes the corresponding payload block. Unknown tokens → `include_flags_skipped[]`, not billed, reason string provided. |
| `list_top_n` | token-dd / token-rugcheck (when `include=list`) | ❌ | int | `20` | 10 / 20 / 50 | Holder rows returned by `holder_list[]` block. |
| `history_points` | token-dd / token-rugcheck (when `include=risk_history`) | ❌ | int | `30` | 7 / 14 / 30 | Daily risk-snapshot count (linear-interpolate missing). |
| `tag_cohort_interpolate` | token-dd / token-rugcheck | ❌ | bool | `true` | — | When true each tag-cohort row also includes interpolated USD holding = `pct × MC ÷ 100`. 0 CU. |
| `X-Birdeye-Aggregate: 1` | HTTP header (any) | ❌ | literal | — | — | Optional sentinel header for agent/monitoring. Echoed back in server logs. No behavior change. |

### CU Adder Reference (identical to /API/13 for DD/Rug)

| Endpoint family | Flag token | CU adder |
|---|---|---:|
| trending-simple | (no flags — flat tier) | 30 total |
| trending-v3 | `extra_fields` | +12 |
| trending-v3 | `security_shallow` | +18 |
| token-dd / token-rugcheck | `list` (holder distribution top-N) | +30 |
| token-dd / token-rugcheck | `advanced_security` (tags + Δ + liq DD% + bot proxy) | +21 |
| token-dd / token-rugcheck | `risk_history_30d` (daily score series — source Đức) | +30 |
| token-dd / token-rugcheck | BASE block — always billed | 71 floor |

---

## 1. `/api/v1/trending/simple`

### Summary

Mode-B (Simple) trending list. Cheap 30 CU baseline. Default for Hub discovery, quick scans, agent "what's pumping now?" queries. Output identical shape to Skill #1 CLI `--format json`.

### Params

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `chain` | ❌ | string | `sol` | `sol` / `bsc` / `base` / `eth` | Chain id lowercase. |
| `interval` | ❌ | string | `24h` | `5m` / `15m` / `1h` / `4h` / `24h` | Upstream trending window. |
| `limit` | ❌ | int | `40` | 10…100 | Paginated, 40 default / 100 max. |
| `sort_by` | ❌ | string | `rank` | `rank` / `volumeUSD` / `mc` / `holderCount` | Sort applied client aggregate side. |
| `platform` | ❌ | csv string | `` | `pump.fun,raydium,moonshot,…` | Token launch platform filter. |
| `min_liquidity` | ❌ | float | `null` | ≥ 0 | Drop rows below this USD liquidity floor. |

### Response (skeleton)

```json
{
  "api_version": "v1",
  "kind": "trending-simple",
  "fetched_at_unix": 0,
  "meta": {
    "chain": "sol",
    "interval": "24h",
    "limit_requested": 40,
    "rows_returned": 40,
    "cu_billed_total": 30,
    "cu_breakdown": {
      "trending_v1_fetch": 30,
      "include_extra_fields": 0,
      "fanout_parallel_price_batch": 0,
      "client_filter_cull_count": 0
    },
    "include_flags": [],
    "include_flags_skipped": [],
    "pipeline_gap_rows": 0,
    "upstream_birdeye_trace_ids": ["trending_v1:xxx"]
  },
  "rows": [
    {
      "rank": 1,
      "address": "", "symbol": "", "name": "",
      "price_usd": 0, "mc": 0, "liquidity_usd": 0,
      "v_5m_usd": 0, "v_1h_usd": 0, "v_24h_usd": 0,
      "pct_5m": 0, "pct_1h": 0, "pct_24h": 0,
      "trades_1h": 0, "unique_wallets_24h": 0, "holder_count": 0,
      "platform": "raydium",
      "last_trade_unix": 0,
      "pipeline_gap": false
    }
  ]
}
```

### curl example

```bash
curl -s "http://127.0.0.1:8765/api/v1/trending/simple?chain=sol&interval=1h&limit=20" \
  -H "X-Birdeye-Aggregate: 1" \
  | python3 -m json.tool | head -60
```

### Notes

- Always sorts by upstream `rank` first; `sort_by` is a second pass.
- Rows where `v_1h_usd < $1` get flagged `"pipeline_gap": true` and are not removed — it is the consumer's decision to hide or warn.
- CU is flat 30 regardless of window; switching interval does **not** re-bill when replayed from cache.

---

## 2. `/api/v1/trending/v3`

### Summary

Reliable V3 token list with numeric range filters. Preferred over Simple for production sweeps, Smart Money batch DD inputs, rug-audit batch runs. Extra enrichment (security shallow, platform-only) selectable via `include[]`.

### Params

| Name | Req? | Type | Default | Enum / Range | Notes |
|---|:---:|---|---|---|---|
| `chain` | ❌ | string | `sol` | `sol` | V3 is Sol-only today. |
| `min_volume` | ❌ | float | `1000` | ≥ 0 | 24h volume USD floor. |
| `max_mc` / `min_mc` | ❌ | float | `null` | ≥ 0 | Market cap band. |
| `min_holders` | ❌ | int | `null` | ≥ 0 | Holder floor. |
| `min_liq` | ❌ | float | `null` | ≥ 0 | Liquidity floor. |
| `sort_by` | ❌ | string | `volumeUSD` | `volumeUSD` / `mc` / `holders` / `trades_1h` | |
| `limit` | ❌ | int | `40` | 10…100 | |
| `platform` | ❌ | csv | `` | platform filter | |
| `include[]` | ❌ | csv | `` | `extra_fields`, `security_shallow` | `extra_fields` +12 CU · `security_shallow` +18 CU. |

### Response (skeleton header — `meta.cu_breakdown` keys)

```
cu_breakdown: { v3_list_fetch: 50, extra_fields_enrich: 12|0, security_shallow: 18|0, filter_cull: 0 }
```

Body rows carry the same keys as `/simple`, with extras appended per include flag.

### curl example

```bash
curl -s "http://127.0.0.1:8765/api/v1/trending/v3?chain=sol&min_volume=10000&limit=20&include=extra_fields,security_shallow" \
  -H "X-Birdeye-Aggregate: 1"
```

### Notes

- V3 list can return up to 300 items upstream; aggregate applies `limit` post-sort post-filter.
- `include=security_shallow` on V3 is NOT equivalent to Token DD BASE (71 CU) — it is a cheap batch-friendly surface (top-10 holder% + mint authority + freeze). Use it to cull candidates before running full DD.

---

## 3. `/api/v1/token/dd`

### Summary

Core modular Token DD. **The single canonical endpoint for deep-dive analysis on one address.** Follows /API/13 include selector system exactly: BASE(71) · `+list=+30` · `+advanced_security=+21` · `+risk_history=+30`.

### Params (identical to /API/13 Params table)

| Name | Req? | Type | Default | Enum / Range |
|---|:---:|---|---|---|
| `address` | ✅ | string | — | Sol base58 / 0x40 |
| `chain` | ❌ | string | `sol` | sol / bsc / base / eth |
| `include[]` | ❌ | csv | `` | `list` · `advanced_security` · `risk_history` |
| `list_top_n` | ❌ | int | `20` | 10 / 20 / 50 |
| `history_points` | ❌ | int | `30` | 7 / 14 / 30 |
| `tag_cohort_interpolate` | ❌ | bool | `true` | |
| `format` | ❌ | string | `json` | `json` (aggregate ignores — always JSON. Client renders.) |

### Response

Full shape documented in **/API/13 Payload Shapes**. Aggregate layer guarantees every `/token/dd` response has:

1. A top-level `kind: "token-dd"` discriminator
2. `meta.cu_breakdown` dictionary with keys exactly: `{ base, list, advanced_security, risk_history, refunded_rollback }`
3. `meta.cu_billed_total = sum(breakdown) - refunded_rollback`
4. `meta.include_flags = ["list","…"]` — flags actually honored
5. `meta.include_flags_skipped` — flags that were requested but **not** billed (e.g., chain doesn't support holder distribution), with a reason label per token.

### curl example (STANDARD tier — list + advanced_security)

```bash
TOKEN="BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK"
curl -s "http://127.0.0.1:8765/api/v1/token/dd?chain=sol&address=${TOKEN}&include=list,advanced_security&list_top_n=20" \
  -H "X-Birdeye-Aggregate: 1" \
  | python3 -c "import sys,json
d=json.load(sys.stdin)
m=d['meta']
print('CU billed total :', m['cu_billed_total'])
print('CU breakdown    :', json.dumps(m['cu_breakdown'], separators=(',',':')))
print('Include flags   :', m['include_flags'])
print('Flags skipped   :', m['include_flags_skipped'])
print('Rating / Score  :', d.get('rating'),'/',d.get('score_final_0_10'))"
```

Expected output:
```
CU billed total : 122
CU breakdown    : {"base":71,"list":30,"advanced_security":21,"risk_history":0,"refunded_rollback":0}
Include flags   : ["list","advanced_security"]
Flags skipped   : []
Rating / Score  : C / 5.4
```

### Notes

- `/api/v1/token/dd` is the **only** route that directly accepts raw `include[]`. All skill internal multi-call logic moves out of skill code into this aggregate handler.
- Chain-unsupported adders trigger a **fair CU rollback**: if EVM chain X has no `/holder/distribution` endpoint, then `include=list` is moved into `include_flags_skipped[]` and `cu_breakdown.list = 0` → `refunded_rollback = 30` explicitly labeled.

---

## 4. `/api/v1/token/rugcheck`

### Summary

RugCheck-equivalent risk audit. **Shares the EXACT same call graph, same payload bytes, same include selectors, same CU price as /token/dd** — only difference: top-level discriminator `kind: "rugcheck-risk-audit"` and a `risk_cards[]` view is materialized (7-card array: Mint / Liq / Honeypot / DevHold / Top10Conc / TagCohort / BotWash).

This exists so agents / CLI users can ask:
```
"Run rugcheck on token X"  →  GET /api/v1/token/rugcheck?include=list,advanced_security
```
…which routes to the same backend cache entry as `/token/dd`. Zero duplication, 0 CU double-charge if the same tuple `(chain,addr,include)` was fetched in last 15 min window.

### Params

Same as `/token/dd`.

### Response

Same payload bytes as `/token/dd` with these additive fields only:

```json
{
  "api_version": "v1",
  "kind": "rugcheck-risk-audit",
  "…identical token-dd payload blocks, fields 100% shared…": "",
  "rug_summary_13_fields": {
    "tier_0_10_label": "CAUTION",
    "rug_score_0_10": 3.6
  },
  "risk_cards": [
    { "id":"Mint", "label":"Mint authority", "level":"ok", "detail":"Renounced" },
    { "id":"Liq", "label":"Liquidity 24h drawdown", "level":"warn", "detail":"DD% -18% min 12k → current 14k" },
    { "id":"Honeypot", "label":"Honeypot check", "level":"crit", "detail":"Sell disabled" },
    { "id":"DevHold", "label":"Dev / creator hold%", "level":"warn", "detail":"Creator 9.2%" },
    { "id":"Top10Conc", "label":"Top-10 holder concentration", "level":"ok", "detail":"Top10 38%" },
    { "id":"TagCohort", "label":"Tag cohort% (Sniper / Smart / KOL / Bundler / Dev)", "level":"warn", "detail":"Sniper 22% interpolated USD 420k of 1.9M MC" },
    { "id":"BotWash", "label":"Bot wash proxy (trades% vs volume%)", "level":"crit", "detail":"Bot% 74 / bot-volume% 81 — >60 threshold" }
  ]
}
```

### curl example (DEEP tier — list + advsec + risk30d)

```bash
TOKEN="BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK"
curl -s "http://127.0.0.1:8765/api/v1/token/rugcheck?chain=sol&address=${TOKEN}&include=list,advanced_security,risk_history" \
  -H "X-Birdeye-Aggregate: 1" \
  | python3 -c "import sys,json
d=json.load(sys.stdin)
m=d['meta']
print('CU  :', m['cu_billed_total'])
print('Tier:', d['rug_summary_13_fields']['tier_0_10_label'])
for c in d['risk_cards']:
  lvl = {'ok':'🟢','warn':'🟡','crit':'🔴'}.get(c['level'],'⚪')
  print(f'{lvl} {c[\"id\"]:12s} {c[\"detail\"]}')"
```

### Notes

- Cache key: `rugcheck:(chain,addr,include)` shares the same underlying raw-byte cache as `token-dd:(chain,addr,include)`. Only the JSON wrapper (kind + risk_cards[] view) is different.
- The 7-card array is a **view** over BASE + list + advsec blocks; it contains no new data, so no extra CU. This is exactly the 0-CU format-switch guarantee consumers rely on.

---

## 5. Global response invariants (all 4 aggregate endpoints)

| Invariant | Assertion on every 2xx response |
|---|---|
| CU integrity | `sum(cu_breakdown.values()) - refunded_rollback == cu_billed_total` |
| Flag honesty | Every token in `include_flags` has a non-zero corresponding `cu_breakdown[key]`; every entry in `include_flags_skipped` has a zero adder and a non-empty reason string. |
| Kind discriminator | `kind` is one of `trending-simple / trending-v3 / token-dd / rugcheck-risk-audit` — never ambiguous. |
| Timestamp monotonic | `fetched_at_unix ≤ now()`. When replayed from cache, `meta.from_cache = true` + `meta.original_cu_billed` (badge: 💾 Cached run · Original API cost ⚡X CU · Re-render = 0 CU). |
| Error friendly | 4xx / 5xx return JSON `{ error:{ code, message, retryable }, meta:{ cu_billed_total:0, fan_out_partial_results:[] }}` — partial upstream results are **never billed** (adder rollback on error). |
