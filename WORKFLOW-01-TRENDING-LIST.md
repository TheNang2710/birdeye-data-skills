# Workflow · Skill #1 · Trending List (Discovery)

> **Goal:** Discover hot tokens fast, with CU-efficient dual-mode routing (Simple / Advanced). Each step is transparent: preflight checks, exact Birdeye endpoint, CLI command matrix, output columns, and invariant validations with pipeline-gap detection.

---

## 0. Skill Header & Equivalent Birdeye APIs

| Field | Value |
|---|---|
| **Skill id** | `tl` (Simple Mode-B) · `tl_v3` (Advanced Mode-A) |
| **Skill title** | Skill #1 · Trending List · Skill #1b · V3 Token List |
| **Category** | 🔥 Discovery (Group 1/8) |
| **CU cost — Mode-B Simple** | **30 CU** (one call, good for casual browse) |
| **CU cost — Mode-A Advanced** | **50 CU** (enriched, filterable + trade_count / holders) |
| **CLI subcommand** | `trending-list` |
| **UI status** | ✅ LIVE |
| **Equivalent Birdeye endpoints** | See mapping table below |

### Birdeye API ↔ Skill Mode Mapping

| Mode | Birdeye endpoint | CU | Strength | Weakness |
|---|---|---:|---|---|
| **Mode-B · Simple** | `GET /defi/v2/tokens/trending` | 30 | Fast, low CU, works for basic browse | No `min_volume` filter, volume 1h sometimes unreliable for Solana |
| **Mode-A · V3 List** | `GET /defi/v3/token/list` | 50 | Sortable, `min_liquidity` / `min_volume` filter, returns `trade_count` + `holders` | +20 CU extra per call |

### Cross-links
- Low-level endpoint spec → `/API/08-trade-data-aggregates.md` & `/API/01-token-overview.md`
- CLI standalone path → `birdeye-screener/scripts/birdeye_cli.py`
- HUB UI path → choose `🔥 Discovery / Skill #1` or `Skill #1b` in sidebar

---

## 1. Prerequisites

Before any run, these invariants MUST hold (preflight check performed by UI / CLI wrapper at 0 CU):

1. **API key set** — either `BIRDEYE_API_KEY` env var, `~/.birdeye.env` file, or pasted into 🔑 API Key panel → **Apply session**.
2. **Valid chain** — one of `sol | bsc | base | eth` (mapping to `solana / bsc / base / ethereum` on the wire).
3. **Valid interval** — one of `5m | 1h | 4h | 8h | 24h` (UI only; CLI supports subset `1h / 4h / 24h` for API compatibility).
4. **Valid source** — exactly `trending` (Mode-B) or `v3-list` (Mode-A).
5. **Limit in range** — integer between 1–500 inclusive.

Failure on any → **return EARLY with red `🛑` banner**, NO POST to `/api/run`, **0 CU consumed**.

---

## 2. Step-by-Step Checking Workflow

```
START: User picks chain + interval + source + limit
  │
  ▼
STEP 0 · PREFLIGHT (0 CU, client-side)
  ├─ Validate chain ∈ {sol,bsc,base,eth}
  ├─ Validate interval ∈ {5m,1h,4h,8h,24h}
  ├─ Validate source ∈ {trending,v3-list}
  ├─ Validate limit ∈ [1,500]
  └─ Validate API key is present & non-empty after mask
       FAIL → 🛑 red banner, HALT
       PASS → continue
  │
  ▼
STEP 1 · AUTO-ROUTE Mode (0 CU, client-side)
  ├─ If user selected Skill #1b (tl_v3) in catalog     → force source = v3-list (50 CU)
  ├─ If user passed --platform filter OR min_volume/X   → force source = v3-list (50 CU)
  └─ Otherwise (no advanced filter)                     → prefer source = trending (30 CU save)
  │
  ▼
STEP 2 · CALL Birdeye endpoint
  ├─ Mode-B → GET  /defi/v2/tokens/trending
  │           ?chain=X&interval=Y&sort_by=Z&limit=N
  └─ Mode-A → GET  /defi/v3/token/list
              ?chain=X&offset=0&limit=N&sort_by=volumeUSD
              &min_liquidity=1000            (default, avoid dust)
  │
  ▼
STEP 3 · IN-VARIANT Checks (after response, 0 CU extra)
  ├─ ✅ volume_interval_usd ≥ 0  for every row (no negatives)
  ├─ ✅ liquidity ≥ 0            for every row
  ├─ ✅ price_change_pct ∈ [-100, +50000]  (sanity clamp for display)
  ├─ ✅ sum of (buy_count + sell_count) ≈ trade_count when present
  └─ ⚠ pipeline_gap badge if Mode-B volume 1h < $1 AND chain = sol
       (Solana trending v1 often returns trash data; recommend switch to v3-list)
  │
  ▼
STEP 4 · DEDUP + SORT (client-side 0 CU)
  ├─ Drop duplicate address rows
  ├─ Sort by the `--sort-by` the user picked (default rank for Mode-B, volumeUSD for Mode-A)
  └─ Truncate to `limit` rows
  │
  ▼
STEP 5 · RENDER + CACHE + RETURN
  ├─ Wrap in payload envelope with runId / cu_used_total / snapshot_time
  ├─ Persist JSON cache for 24h in ~/.cache/birdeye-skills-runs/
  └─ Render in chosen format (plain / telegram / raw-json / render-html)
       │
       ▼
    DONE → footer shows ⚡NN CU · ΔT ms · #run_id
```

---

## 3. All CLI Commands (Exhaustive)

```bash
# ============================================================
#  WORKDIR:  cd /Users/nguyenthenang/nang/birdeye/app/skills
#  CLI PATH: birdeye-screener/scripts/birdeye_cli.py
#  (always invoke via `python3`; shebang is not assumed chmod +x)
# ============================================================

# ------------------------------------------------------------
#  [A] Mode-B · Simple (30 CU — default for quick browse)
# ------------------------------------------------------------
python3 birdeye-screener/scripts/birdeye_cli.py \
  trending-list \
  --chain sol \
  --interval 1h \
  --source trending \
  --sort-by rank \
  --limit 10

# Solana · 24h interval · 20 rows
python3 birdeye-screener/scripts/birdeye_cli.py \
  trending-list --chain sol --interval 24h --limit 20 --format plain

# BSC chain · telegram output (ready-to-paste markdown)
python3 birdeye-screener/scripts/birdeye_cli.py \
  trending-list --chain bsc --interval 4h --limit 15 \
  --format telegram > /tmp/tg-trending-bsc.md
  cat /tmp/tg-trending-bsc.md   # paste as-is into ``` code block in TG

# Base chain · raw JSON (pipe to jq / bot framework)
python3 birdeye-screener/scripts/birdeye_cli.py \
  trending-list --chain base --limit 30 --format raw-json | jq '.rows[:3]'

# ------------------------------------------------------------
#  [B] Mode-A · V3 Token List (50 CU — filters + enriched)
# ------------------------------------------------------------
# Skill #1b default → forces v3-list source
python3 birdeye-screener/scripts/birdeye_cli.py \
  trending-list --chain sol --source v3-list --sort-by volumeUSD --limit 15

# Filter by launch platform (pump.fun tokens only) — auto-routes to v3-list
python3 birdeye-screener/scripts/birdeye_cli.py \
  trending-list --chain sol --interval 1h --platform pump.fun --limit 25

# Ethereum · 4h interval · V3 list · sort by marketCap
python3 birdeye-screener/scripts/birdeye_cli.py \
  trending-list --chain eth --source v3-list --sort-by marketCap --limit 30 \
  --format telegram

# ------------------------------------------------------------
#  [C] Cache helpers (0 CU — re-render, no API call)
# ------------------------------------------------------------
# Replay a prior run_id from disk cache in different format
python3 birdeye-screener/scripts/birdeye_cli.py \
  replay-run --run-id trending-list_sol_1h_v3_1760000000 --format telegram

# List last 25 runs in cache
python3 birdeye-screener/scripts/birdeye_cli.py history --limit 25 --format plain

# ------------------------------------------------------------
#  [D] API Key management helpers
# ------------------------------------------------------------
# Apply key from CLI (saves to ~/.birdeye.env chmod 600)
python3 birdeye-screener/scripts/birdeye_cli.py config --apply YOUR_BIRDEYE_KEY_HERE

# Check current key status (masked head2****tail2)
python3 birdeye-screener/scripts/birdeye_cli.py config --status
```

### Exit codes
| Exit | Meaning |
|---:|---|
| 0 | Success (rows rendered) |
| 2 | CLI arg invalid (argparse) — no network call, 0 CU |
| 3 | API key missing — no network call, 0 CU |
| 4 | Birdeye HTTP non-200 — partial CU may be debited on 429 by Birdeye upstream, check docs |
| 5 | Preflight invariant failed (e.g. negative volume returned) — treat as `⚠ pipeline_gap` |

---

## 4. Response Output Columns

### Rendered table (both modes — columns differ per source)

| Col | Field | Mode-B<br>trending | Mode-A<br>v3-list | Notes |
|---|---|:---:|:---:|---|
| 1 | `#` rank | ✅ | ✅ | 1..N by sort order |
| 2 | Symbol + (short addr) | ✅ | ✅ | Clickable → opens Next Actions panel |
| 3 | MC (market cap) | ✅ | ✅ | `$M / $B` compact |
| 4 | FDV (fully diluted) | — | ✅ | v3-list only |
| 5 | LIQ (liquidity USD) | ✅ | ✅ | `⚠ pipeline_gap` overlay if < $1 |
| 6 | Price USD | ✅ | ✅ | Compact K/M/B suffixes |
| 7 | Vol (interval USD) | ✅ | ✅ | Volume over the user's chosen `--interval` |
| 8 | ΔV% (volume change) | ✅ | ✅ | Green/red cell formatting |
| 9 | ΔP% (price change) | ✅ | ✅ | Green/red cell formatting |
| 10 | Trades count | — | ✅ | v3-list only (`trade_interval_count`) |
| 11 | Holders count | — | ✅ | v3-list only (`holder_count`) |

### Raw JSON envelope (`kind: "trending-list"`, schemaVersion: 1)
```jsonc
{
  "runId": "trending-list_sol_1h_v3_1760001234",
  "cached": false,
  "cu_used_total": 30,
  "snapshot_time": 1760001234567,
  "latency_ms": 680,
  "params": { "chain":"sol", "interval":"1h", "source":"v3-list",
              "sort_by":"volumeUSD", "limit":10, "offset":0, "platform":null },
  "total_tokens": 10,
  "rows": [ /* 1 row per token, keys snake_case */
    { "rank":1, "address":"So1111...1111", "symbol":"SOL", "name":"Wrapped SOL",
      "marketcap_usd": 1.23e11, "fdv_usd": 1.23e11, "liquidity_usd": 4.5e7,
      "price_usd": 180.5, "volume_interval_usd": 8.9e8,
      "volume_interval_change_pct": +12.4, "price_interval_change_pct": +3.1,
      "trade_interval_count": 482100, "holder_count": 8750000,
      "logoURI":"https://...", "source_row":"" }
  ]
}
```

---

## 5. Invariants & Pipeline Gap Detection (Must Pass Every Run)

| Invariant | Failing behaviour |
|---|---|
| Every row `liquidity_usd ≥ 0` | Flag row with red; report `pipeline_gap` count in footer |
| Every row `volume_interval_usd ≥ 0` | Same as above |
| Mode-B + Solana + ≥ 70% rows have `vol < $1` | Render top banner `⚠ pipeline_gap — Solana Mode-B trending returned trash data. Switch to Skill #1b (v3-list, 50 CU) for reliable results.` |
| Duplicate `address` in response | Dedup and log count; never show duplicate rows to user |
| `price_change_pct > +50000` or `< -100` | Clamp display but preserve raw value in JSON cache |
| `sum(buy_count + sell_count) ≈ trade_count` when all three exist | If ratio off by >15%, attach `⚠ signal_gap` pill to that column header |

---

## 6. Next Actions (From a Trending Row)

When the user clicks any token row in the rendered TL table, the UI prefills these follow-ups
(but **never runs them automatically** — user must click ▶ Run explicitly):

1. 🛡 **Token DD scorecard** (Skill #3, 71 CU) — prefills `address` + `chain` → shows ready banner
2. 👥 **Top 20 Holders** (WIP)
3. 🧠 **Smart Money in this token** (WIP)
4. 🔗 **Same platform tokens** (prefills platform filter on TL page)
5. 📈 **OHLCV 7d** (WIP)
6. 🔐 **Deep Security Audit** (WIP)
7. 🌐 **Open in Birdeye** — opens birdeye.so token page in new tab
