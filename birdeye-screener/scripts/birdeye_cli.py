#!/usr/bin/env python3
"""Birdeye Unified CLI — Layer C (Standalone / Bot-friendly).

Two skills exposed as subcommands:

  1. `trending-list`  — Skill #1 :  Discover hot tokens  ( /defi/token_trending  30 CU )
  2. `token-dd`       — Skill #3 :  "Should I buy this token?" 4 endpoints = 71 CU typical
                                       ├─ /defi/token_overview  (+ includes=money_flow)   21 CU
                                       ├─ /defi/token_security                           30 CU
                                       └─ /smart-money/v1/token/list  (batch join)       20 CU

Two output formats (both are Telegram-pasteable with minimal escaping):
  --format plain      (default): fixed-width ASCII table, monospace-aligned
  --format telegram   : Markdown v2-ish (monospace block + emojis, wrap in ``` for TG)

Extra helpers:
  --format raw-json   : single-line JSON for piping into bot frameworks / downstream tools.

Key discovery is identical to birdeye_screener.py / birdeye_trending_simple.py so the
same `config --apply <KEY>` from the screener feeds this CLI too.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

# --- Modular skill data/logic (pattern, wallet, contract, etc.) ---
from modules import kline_pattern as _kp
from modules import contract_dd as _cdd
from modules import wallet_data as _wd

BIRDEYE_BASE = "https://public-api.birdeye.so"
CHAINS = {"sol": "solana", "bsc": "bsc", "base": "base", "eth": "ethereum", "arc": "arbitrum", "robinhood": "robinhood"}
INTERVALS = ["1h", "4h", "24h"]
WINDOWS = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "24h"]

CACHE_DIR_DEFAULT = Path(os.environ.get("BIRDEYE_CACHE_DIR") or
                         (Path.home() / ".cache" / "birdeye-skills-runs"))


def _cache_dir(custom: str | None = None) -> Path:
    p = Path(custom) if custom else CACHE_DIR_DEFAULT
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_run_id(skill: str, identifier: str, tstamp: int | None = None) -> str:
    ident = identifier[:80] if identifier else "no-id"
    ident = "".join(c if c.isalnum() or c in "-_." else "_" for c in ident)
    ts = tstamp or int(time.time())
    return f"{skill}_{ident}_{ts}"


def _cache_path(cdir: Path, run_id: str) -> Path:
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in run_id) + ".json"
    return cdir / name


def _prune_old_cache(cdir: Path, max_age_hours: int = 24) -> None:
    try:
        now = time.time()
        for fp in cdir.glob("*.json"):
            try:
                if not fp.is_file():
                    continue
                age_h = (now - fp.stat().st_mtime) / 3600.0
                if age_h > max_age_hours:
                    fp.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


def _delete_cache_prefix(cdir: Path, prefix: str) -> int:
    """Delete all JSON cache files in cdir whose stem starts with `prefix`.
    Returns count of files removed.
    Used by --nocache to force fresh API call by wiping any previous runs for same skill+chain+addr."""
    removed = 0
    try:
        for fp in cdir.glob("*.json"):
            try:
                if fp.is_file() and fp.stem.startswith(prefix):
                    fp.unlink(missing_ok=True)
                    removed += 1
            except Exception:
                pass
    except Exception:
        pass
    return removed


def _serialize_trend_payload(r: dict, args) -> dict:
    return {
        "schemaVersion": 1,
        "kind": "trending-list",
        "params": {
            "chain": args.chain,
            "interval": args.interval,
            "sort_by": args.sort_by,
            "source": r["source"],
            "platform": getattr(args, "platform", None),
            "limit": args.limit,
            "offset": args.offset,
        },
        "rows": [
            {
                "rank": x.rank, "address": x.address, "symbol": x.symbol, "name": x.name,
                "logoURI": x.logo, "decimals": x.decimals,
                "marketcap_usd": x.marketcap, "liquidity_usd": x.liquidity,
                "fdv_usd": x.fdv, "price_usd": x.price,
                "volume_interval_usd": x.vol_interval,
                "volume_interval_change_pct": x.vol_interval_pct,
                "price_interval_change_pct": x.price_interval_pct,
                "trade_interval_count": x.trade_interval,
                "holder_count": x.holder_count,
                "source_row": x.source_tag,
            } for x in r["rows"]
        ],
        "total_tokens": r["total"],
        "snapshot_time": r["snapshot_time"],
        "latency_ms": r["latency_ms"],
        "cu_used_total": r["cu_used"],
        "sort_note": r["sort_note"],
        "format_renderers": ["render", "plain", "telegram", "raw-json"],
    }


def _serialize_dd_payload(d: dict, args) -> dict:
    out = dict(d)
    out["schemaVersion"] = 1
    out["kind"] = "token-dd"
    out["params"] = {"chain": args.chain, "address": args.address}
    out["format_renderers"] = ["render", "plain", "telegram", "raw-json"]
    # keep tuples as lists
    out["price_changes"] = [[i, p] for i, p in d["price_changes"]]
    out["buy_sell_rows"] = [[i, t2, b, s2, ratio, buys, sells, tr_ratio, wal]
                             for (i, t2, b, s2, ratio, buys, sells, tr_ratio, wal) in d["buy_sell_rows"]]
    out["money_flow_rows"] = [[i, mf] for i, mf in d["money_flow_rows"]]
    return out


def _write_cache(cdir: Path, run_id: str, payload: dict) -> Path:
    fp = _cache_path(cdir, run_id)
    with fp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return fp


def _read_cache(cdir: Path, run_id: str) -> dict | None:
    fp = _cache_path(cdir, run_id)
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def _render_trend_from_cache(payload: dict, fmt: str, run_id: str, args_ref=None):
    # Build a shape compatible with _print_trend_plain / _print_trend_telegram
    @dataclass
    class _Row:
        rank: int; address: str; symbol: str; name: str; logo: str; decimals: int
        marketcap: float; liquidity: float; fdv: float; price: float
        vol_interval: float; vol_interval_pct: float; price_interval_pct: float
        trade_interval: int; holder_count: int; source_tag: str
        interval_tag: str = ""

    rows = [
        _Row(
            rank=int(x["rank"]), address=x["address"], symbol=x["symbol"],
            name=x.get("name") or x["symbol"], logo=x.get("logoURI") or "",
            decimals=int(x.get("decimals") or 9),
            marketcap=float(x["marketcap_usd"] or 0), liquidity=float(x["liquidity_usd"] or 0),
            fdv=float(x["fdv_usd"] or 0), price=float(x["price_usd"] or 0),
            vol_interval=float(x["volume_interval_usd"] or 0),
            vol_interval_pct=float(x["volume_interval_change_pct"] or 0),
            price_interval_pct=float(x["price_interval_change_pct"] or 0),
            trade_interval=int(x["trade_interval_count"] or 0),
            holder_count=int(x["holder_count"] or 0),
            source_tag=x.get("source_row") or "",
            interval_tag=payload["params"]["interval"] or "",
        ) for x in payload["rows"]
    ]
    r = {
        "source": payload["params"]["source"],
        "rows": rows, "total": payload["total_tokens"],
        "snapshot_time": payload["snapshot_time"],
        "latency_ms": payload["latency_ms"], "cu_used": payload["cu_used_total"],
        "sort_note": payload.get("sort_note") or "",
    }

    class _Args:
        chain = payload["params"]["chain"]
        interval = payload["params"]["interval"]
        sort_by = payload["params"]["sort_by"]
        source = payload["params"]["source"]
        platform = payload["params"].get("platform")
        limit = payload["params"]["limit"]
        offset = payload["params"]["offset"]

    inner_args = args_ref or _Args()
    if fmt == "raw-json":
        print(json.dumps({
            "runId": run_id, "cached": True, "cu_used_total": 0,
            "payload": payload,
        }, ensure_ascii=False))
    elif fmt == "telegram":
        _print_trend_telegram(r, inner_args)
    else:
        _print_trend_plain(r, inner_args)


def _render_dd_from_cache(payload: dict, fmt: str, run_id: str):
    # Reconvert lists -> tuples for compatibility with plain/telegram printers that expect tuple unpacking
    d = dict(payload)
    d["price_changes"] = [(i, p) for [i, p] in payload["price_changes"]]
    d["buy_sell_rows"] = [(i, t2, b, s2, ratio, buys, sells, tr_ratio, wal)
                           for [i, t2, b, s2, ratio, buys, sells, tr_ratio, wal] in payload["buy_sell_rows"]]
    d["money_flow_rows"] = [(i, mf) for [i, mf] in payload["money_flow_rows"]]

    class _Args:
        chain = payload["params"]["chain"]
        address = payload["params"]["address"]

    if fmt == "raw-json":
        print(json.dumps({
            "runId": run_id, "cached": True, "cu_used_total": 0,
            "payload": payload,
        }, ensure_ascii=False))
    elif fmt == "telegram":
        _print_dd_telegram(d, _Args())
    else:
        _print_dd_plain(d, _Args())


CONFIG_DIR = Path.home() / ".config" / "birdeye"
ENV_FILE = CONFIG_DIR / ".env"
HOME_ALT_ENV = Path.home() / ".birdeye.env"
LOCAL_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_key() -> str | None:
    if k := os.environ.get("BIRDEYE_API_KEY"):
        return k.strip() or None
    for cand in [ENV_FILE, HOME_ALT_ENV, LOCAL_ENV_FILE]:
        if not cand.exists():
            continue
        for ln in cand.read_text().splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if ln.startswith("BIRDEYE_API_KEY="):
                k = ln.split("=", 1)[1].strip().strip('"').strip("'")
                if k:
                    return k
    return None


def _fmt_usd(v, nd=1):
    if v is None:
        return "N/A"
    if not isinstance(v, (int, float)):
        return str(v)
    if v == 0:
        return "$0"
    sign = "-" if v < 0 else ""
    av = abs(v)
    if av >= 1e9:
        return f"{sign}${av/1e9:.{nd}f}B"
    if av >= 1e6:
        return f"{sign}${av/1e6:.{nd}f}M"
    if av >= 1e3:
        return f"{sign}${av/1e3:.{nd}f}K"
    if av >= 1:
        return f"{sign}${av:.2f}"
    return f"{sign}${av:.4f}"


def _fmt_pct(v):
    if v is None or not isinstance(v, (int, float)):
        return "N/A"
    return f"{v:+.1f}%"


def _pad_cell(s, w, align="left"):
    s = str(s)
    if len(s) >= w:
        return s[:w]
    if align == "right":
        return " " * (w - len(s)) + s
    return s + " " * (w - len(s))


def _http_error_text(status: int, body: str) -> str:
    prefix = {401: "[E401] Unauthorized — bad key.",
              403: "[E403] Forbidden — tier/route blocked.",
              429: "[E429] Rate-limited — slow down.",
              500: "[E500] Birdeye upstream error."}
    return f"{prefix.get(status, f'[E{status}]')} {body[:220]}"


def _be(session: requests.Session, key: str, chain: str, path: str, params: dict | None = None):
    t0 = time.perf_counter()
    r = session.get(BIRDEYE_BASE + path,
                    headers={"X-API-KEY": key, "x-chain": CHAINS[chain]},
                    params=params or {}, timeout=20)
    ms = int((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        raise RuntimeError(_http_error_text(r.status_code, r.text))
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"json_parse_error:{e} body:{r.text[:180]}")
    # Some Birdeye endpoints (e.g. /smart-money/v1/token/list) return raw
    # list or dict without `success:true` envelope. Treat as success when:
    #   (a) success explicitly True/1, OR
    #   (b) HTTP 200 AND no explicit success==false AND data field / raw body looks OK.
    explicit_success = data.get("success") if isinstance(data, dict) else None
    if isinstance(explicit_success, bool) and explicit_success is False:
        raise RuntimeError(f"success=false: {json.dumps(data)[:220]}")
    if isinstance(explicit_success, (int, float)) and int(explicit_success) == 0:
        raise RuntimeError(f"success=0: {json.dumps(data)[:220]}")
    return data, ms


# ============================================================
# Skill #1 — Trending / Hot Discovery List
# Two sources (--source param):
#   v3-list   → /defi/v3/token/list   50 CU   DEFAULT. Sort by volume/window
#               (reliable: min_volume server-side ensures non-zero real data)
#   trending  → /defi/token_trending  30 CU   (Birdeye native trending; often
#               returns ~$0 volume on Solana — flagged automatically)
# ============================================================

@dataclass
class TrendRow:
    rank: int | None
    address: str
    symbol: str
    name: str | None = None
    logo: str | None = None
    decimals: int | None = 9
    marketcap: float | None = None
    liquidity: float | None = None
    fdv: float | None = None
    price: float | None = None
    vol_interval: float | None = None
    vol_interval_pct: float | None = None
    price_interval_pct: float | None = None
    trade_interval: float | None = None
    holder_count: float | None = None
    interval_tag: str = ""
    source_tag: str = ""


_SORT_TRANSLATE_V3 = {
    "volumeUSD": "volume",
    "liquidity": "liquidity",
    "rank": "market_cap",
    "market_cap": "market_cap",
    "trade_count": "trade_count",
    "holder": "holder",
}


def _fetch_trending_v3(key: str, chain: str, interval: str, sort_by: str, limit: int, offset: int,
                       platform: str | None):
    s = requests.Session()
    v3_sort = _SORT_TRANSLATE_V3.get(sort_by, "volume")
    # field names confirmed by real V3 response (snake_case + suffix _usd / _count / _percent)
    params: dict[str, Any] = {
        "sort_by": (f"volume_{interval}_usd" if v3_sort == "volume" else
                    f"trade_{interval}_count" if v3_sort == "trade_count" else
                    "liquidity" if v3_sort == "liquidity" else
                    "holder" if v3_sort == "holder" else "market_cap"),
        "sort_type": "desc",
        "offset": offset,
        "limit": limit,
    }
    if v3_sort == "volume":
        params[f"min_volume_{interval}_usd"] = 100
    if v3_sort == "trade_count":
        params[f"min_trade_{interval}_count"] = 5
    if platform:
        params["platform_name"] = platform
    data, ms = _be(s, key, chain, "/defi/v3/token/list", params)
    d = data["data"]
    items = d.get("items") or []
    # V3 list response uses {items, has_next}; no total. Approximate.
    total = d.get("total") or (10000 if d.get("has_next") else len(items))
    snap = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows: list[TrendRow] = []
    for i, t in enumerate(items, 1):
        def num(*keys):
            for k in keys:
                v = t.get(k)
                if isinstance(v, (int, float)):
                    return float(v)
            return None
        rows.append(TrendRow(
            rank=i,
            address=t["address"],
            symbol=t.get("symbol") or "",
            name=t.get("name") or t.get("symbol") or None,
            logo=t.get("logo") or t.get("logoURI") or None,
            decimals=t.get("decimals") if isinstance(t.get("decimals"), int) else None,
            marketcap=num("market_cap"),
            liquidity=num("liquidity"),
            fdv=num("fdv"),
            price=num("price"),
            vol_interval=num(f"volume_{interval}_usd"),
            vol_interval_pct=num(f"volume_{interval}_change_percent"),
            price_interval_pct=num(f"price_change_{interval}_percent"),
            trade_interval=num(f"trade_{interval}_count"),
            holder_count=num("holder"),
            interval_tag=interval,
            source_tag="v3-list",
        ))
    return {
        "rows": rows, "total": total, "snapshot_time": snap,
        "latency_ms": ms, "sort_note": "", "cu_used": 50, "source": "v3-list",
    }


def _fetch_trending(key: str, chain: str, interval: str, sort_by: str, limit: int, offset: int,
                    source: str, platform: str | None):
    if source == "v3-list":
        return _fetch_trending_v3(key, chain, interval, sort_by, limit, offset, platform)
    s = requests.Session()
    data, ms = _be(s, key, chain, "/defi/token_trending", {
        "sort_by": sort_by, "offset": offset, "limit": limit, "interval": interval,
    })
    d = data["data"]
    tokens = d.get("tokens") or []
    total = d.get("total", 0)
    snap = d.get("updateTime") or ""

    vol_k = f"volume{interval}USD"
    vold_k = f"volume{interval}ChangePercent"
    prcd_k = f"price{interval}ChangePercent"

    sort_note = ""
    if sort_by == "volumeUSD":
        above = [1 for t in tokens if isinstance(t.get(vol_k), (int, float)) and float(t.get(vol_k)) > 1.0]
        if len(above) * 2 < len(tokens):
            tokens = sorted(tokens, key=lambda t: float(t.get("marketcap") or 0), reverse=True)
            sort_note = (f"Birdeye upstream /defi/token_trending returned mostly "
                         f"{interval}-volume < $1; fell back to client-side marketcap desc. "
                         f"(Tip: use --source v3-list for real volume-sorted data.)")
    elif sort_by == "liquidity":
        tokens = sorted(tokens, key=lambda t: float(t.get("liquidity") or 0), reverse=True)

    rows: list[TrendRow] = []
    for i, t in enumerate(tokens, 1):
        rows.append(TrendRow(
            rank=t.get("rank") or i,
            address=t.get("address"),
            symbol=t.get("symbol") or "",
            name=t.get("name") or t.get("symbol") or None,
            logo=t.get("logo") or t.get("logoURI") or None,
            decimals=t.get("decimals") if isinstance(t.get("decimals"), int) else None,
            marketcap=t.get("marketcap") if isinstance(t.get("marketcap"), (int, float)) else None,
            liquidity=t.get("liquidity") if isinstance(t.get("liquidity"), (int, float)) else None,
            fdv=t.get("fdv") if isinstance(t.get("fdv"), (int, float)) else None,
            price=t.get("price") if isinstance(t.get("price"), (int, float)) else None,
            vol_interval=t.get(vol_k) if isinstance(t.get(vol_k), (int, float)) else None,
            vol_interval_pct=t.get(vold_k) if isinstance(t.get(vold_k), (int, float)) else None,
            price_interval_pct=t.get(prcd_k) if isinstance(t.get(prcd_k), (int, float)) else None,
            trade_interval=None, holder_count=None,
            interval_tag=interval,
            source_tag="trending",
        ))
    return {
        "rows": rows, "total": total, "snapshot_time": snap,
        "latency_ms": ms, "sort_note": sort_note, "cu_used": 30, "source": "trending",
    }


def _print_trend_plain(r, args):
    # Optional extra columns for v3-list source (trade_count, holder)
    has_extra = any(row.trade_interval is not None or row.holder_count is not None for row in r["rows"])
    cols = [("#", 4), ("SYMBOL", 12), ("ADDR (head 4..4)", 12),
            ("MCAP", 10), ("LIQ", 10),
            (f"VOL({r['rows'][0].interval_tag if r['rows'] else args.interval})", 13),
            ("ΔVOL%", 9), ("ΔPRICE%", 10)]
    if has_extra:
        cols += [("TRADES", 10), ("HOLDERS", 10)]
    head = " ".join(_pad_cell(c, w) for c, w in cols)
    print(head)
    print("-" * (sum(w for _, w in cols) + len(cols) - 1))
    for i, row in enumerate(r["rows"], 1):
        short_addr = row.address[:4] + "…" + row.address[-4:] if len(row.address) > 8 else row.address
        cells = [
            (str(row.rank if row.rank else i), 4, "right"),
            ((row.symbol or "")[:11], 12, "left"),
            (short_addr, 12, "left"),
            (_fmt_usd(row.marketcap), 10, "right"),
            (_fmt_usd(row.liquidity), 10, "right"),
            (_fmt_usd(row.vol_interval), 13, "right"),
            (_fmt_pct(row.vol_interval_pct), 9, "right"),
            (_fmt_pct(row.price_interval_pct), 10, "right"),
        ]
        if has_extra:
            tr = f"{int(row.trade_interval):,}" if isinstance(row.trade_interval, (int, float)) else "N/A"
            hd = f"{int(row.holder_count):,}" if isinstance(row.holder_count, (int, float)) else "N/A"
            cells += [(tr, 10, "right"), (hd, 10, "right")]
        print(" ".join(_pad_cell(c, w, a) for c, w, a in cells))

    source_note = f"  Source:{r.get('source','?')}"
    print(f"\n⚡CU: {r['cu_used']}{source_note} | ⏱{r['latency_ms']}ms | 📸{r['snapshot_time']}")
    print(f"ℹ Chain={args.chain.upper()}  Interval={args.interval}  "
          f"Upstream_sort={args.sort_by}  Rows={len(r['rows'])}/{r['total']}" + (f"  Platform={args.platform}" if getattr(args, "platform", None) else ""))
    if r["sort_note"]:
        print(f"⚠  {r['sort_note']}")
    print("\n📋 Paste next (for token-dd):")
    for row in r["rows"][:3]:
        print(f"    python3 {sys.argv[0]} token-dd --chain {args.chain} --address {row.address}")


def _print_trend_telegram(r, args):
    tag = r["rows"][0].interval_tag if r["rows"] else args.interval
    lines = [
        f"🔥 *Birdeye Trending — {args.chain.upper()} · {tag}*",
        f"_sort: {args.sort_by} · rows: {len(r['rows'])}/{r['total']}_",
        "```",
        f"{'#':>3} {'SYM':<11} {'MCAP':>8} {'LIQ':>8} {'V'+tag:>9} {'ΔV%':>6} {'ΔP%':>6}",
    ]
    for i, row in enumerate(r["rows"], 1):
        sym = (row.symbol or "?")[:10]
        lines.append(f"{(str(row.rank if row.rank else i)):>3} {sym:<11} "
                     f"{_fmt_usd(row.marketcap).replace('$',''):>8} "
                     f"{_fmt_usd(row.liquidity).replace('$',''):>8} "
                     f"{_fmt_usd(row.vol_interval).replace('$',''):>9} "
                     f"{_fmt_pct(row.vol_interval_pct):>6} "
                     f"{_fmt_pct(row.price_interval_pct):>6}")
    lines.append("```")
    lines.append(f"⚡CU {r['cu_used']} · ⏱{r['latency_ms']}ms · 📸{r['snapshot_time']}")
    if r["sort_note"]:
        lines.append(f"⚠ {r['sort_note']}")
    lines.append("\n_Tokens for `token-dd`:_")
    for row in r["rows"][:5]:
        lines.append(f"· `{row.address[:8]}…{row.address[-6:]}` {row.symbol}")
    print("\n".join(lines))


def cmd_trending(args):
    cdir = _cache_dir(getattr(args, "cache_dir", None))
    _prune_old_cache(cdir, max_age_hours=24)
    nocache: bool = bool(getattr(args, "nocache", False))
    from_cache: str | None = (None if nocache else (getattr(args, "from_cache", None) or None))
    write_cache: bool = bool(getattr(args, "write_cache", True))
    ident_prefix = f"trending_{args.chain}-{args.interval}-{args.source}-{args.sort_by}"
    if nocache:
        removed = _delete_cache_prefix(cdir, ident_prefix)
        if removed:
            print(f"[nocache] removed {removed} stale trending cache file(s) prefix={ident_prefix!r}", file=sys.stderr)
    if from_cache:
        cached = _read_cache(cdir, from_cache)
        if not cached or cached.get("kind") != "trending-list":
            print(f"[E] Cache run_id not found or invalid: {from_cache}")
            return 3
        _render_trend_from_cache(cached, args.format, from_cache, args_ref=args)
        return 0
    key = _load_key()
    if not key:
        print("[E] No BIRDEYE_API_KEY found (env / ~/.birdeye.env / skill .env).")
        return 1
    try:
        r = _fetch_trending(key, args.chain, args.interval, args.sort_by, args.limit, args.offset,
                            args.source, getattr(args, "platform", None))
    except RuntimeError as e:
        print(str(e))
        return 2
    if write_cache:
        ident = f"{args.chain}-{args.interval}-{args.source}-{args.sort_by}"
        rid = _safe_run_id("trending", ident, tstamp=int(time.time()))
        payload = _serialize_trend_payload(r, args)
        fp = _write_cache(cdir, rid, payload)
        print(f"#RUN_ID {rid}\t{fp.name}\tcu={payload['cu_used_total']}")
    else:
        rid = None
    if args.format == "raw-json":
        payload = _serialize_trend_payload(r, args)
        out = {"runId": rid, "cached": False, "cu_used_total": payload["cu_used_total"], "payload": payload}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if args.format == "telegram":
        _print_trend_telegram(r, args)
    else:
        _print_trend_plain(r, args)
    return 0


# ============================================================
# Skill #3 — Token DD ("Should I buy?")
# ============================================================

INTERVAL_PAIRS_ORDER = ["5m", "15m", "30m", "1h", "4h", "24h"]


def _ov(d: dict, base: str, suffix: str):
    """Return overview field. `suffix` can be e.g. "5mPercent", "1hUSD", "5m".
    Birdeye token_overview convention = camelCase, e.g.
      priceChange5mPercent | v5mUSD | vBuy5mUSD | buy5m | uniqueWallet5m
    Note: there is NO "15m" window in the real overview payload; we produce
    15m by aggregating from 5m/30m only when explicit window requested."""
    for key in (f"{base}{suffix}",):
        if key in d and d[key] is not None:
            return d[key]
    return None


def _security_field(s: dict, preferred: list[str]):
    for k in preferred:
        if k in s and s[k] is not None:
            return s[k]
    return None


def _fetch_token_dd(key: str, chain: str, address: str, enable_rugcheck_extra: bool = False, args_ref = None):
    s = requests.Session()
    t0 = time.perf_counter()
    cu = 0
    breakdown: list[str] = []

    # 1) Token overview + money_flow — ALWAYS request money_flow frames for every
    #    chain (previously only sol, caused empty money_flow_rows on EVM chains).
    #    Base 18 CU + include money_flow 3 = 21 CU (consistent for all chains).
    ov_params = {"address": address, "includes": "money_flow"}
    ov, ms1 = _be(s, key, chain, "/defi/token_overview", ov_params)
    cu += 21
    breakdown.append("overview+mf=21")
    ovd = ov["data"]

    # 2) Token security (30 CU)
    sec_ok = True
    try:
        sec, ms2 = _be(s, key, chain, "/defi/token_security", {"address": address})
        cu += 30
        breakdown.append("security=30")
        secd = sec.get("data") or {}
    except RuntimeError as e:
        sec_ok = False
        ms2 = 0
        secd = {}
        breakdown.append("security=FAIL")

    # 3) Smart-money list (batch join, 20 CU) — find matching token if any
    sm_no = None
    sm_rank = None
    sm_ok = True
    try:
        sm, ms3 = _be(s, key, chain, "/smart-money/v1/token/list", {
            # NB: SM list enforces limit ≤ 20 (400 otherwise); we still call for join,
            # just with smaller batch.
            "limit": 20,
            "sort_by": "smart_traders_no",
            "sort_type": "desc",
            "time_range": "1d",
        })
        cu += 20
        breakdown.append("sm_batch=20")
        for i, row in enumerate(sm.get("data") or [], 1):
            if row.get("token") == address or row.get("address") == address:
                sm_no = row.get("smart_traders_no")
                sm_rank = i
                break
    except RuntimeError as e:
        sm_ok = False
        ms3 = 0
        breakdown.append(f"sm_batch=FAIL({str(e)[:40]})")

    ms = int((time.perf_counter() - t0) * 1000)

    # ---- Assemble unified DD dict ----
    def fnum(v):
        return float(v) if isinstance(v, (int, float)) else None

    snap = ovd.get("lastTradeHumanTime") or ""

    signal_intervals = [i for i in INTERVAL_PAIRS_ORDER if fnum(_ov(ovd, "priceChange", i + "Percent")) is not None]
    price_rows = [(i, fnum(_ov(ovd, "priceChange", i + "Percent"))) for i in signal_intervals]

    buy_sell_rows = []
    for i in signal_intervals:
        b = fnum(_ov(ovd, "vBuy", i + "USD"))
        s2 = fnum(_ov(ovd, "vSell", i + "USD"))
        t2 = fnum(_ov(ovd, "v", i + "USD"))
        buys = fnum(_ov(ovd, "buy", i))
        sells = fnum(_ov(ovd, "sell", i))
        ratio = None
        if isinstance(b, (int, float)) and isinstance(s2, (int, float)) and (b + s2) > 0:
            ratio = b / (b + s2)
        tr_ratio = None
        if isinstance(buys, (int, float)) and isinstance(sells, (int, float)) and (buys + sells) > 0:
            tr_ratio = buys / (buys + sells)
        wal = fnum(_ov(ovd, "uniqueWallet", i))
        buy_sell_rows.append((i, t2, b, s2, ratio, buys, sells, tr_ratio, wal))

    money_flow_rows = []
    # Build native moneyflow map from list[{frame, netUsd | vBuyUSD-vSellUSD}]
    # Enabled unconditionally for ALL chains now (overview always asks includes=money_flow).
    native_mf: dict[str, Optional[float]] = {}
    mf_list = ovd.get("moneyFlow") or ovd.get("money_flow") or []
    if isinstance(mf_list, list):
        for row in mf_list:
            if not isinstance(row, dict):
                continue
            fr = row.get("frame")
            if not isinstance(fr, str):
                continue
            net = None
            for candidate in ("netUsd", "netUSD", "net", "netFlow", "netFlowUsd"):
                v = row.get(candidate)
                if isinstance(v, (int, float)):
                    net = float(v)
                    break
            if net is None:
                bv = row.get("volumeBuyUsd") or row.get("vBuyUsd") or row.get("volumeBuyUSD")
                sv = row.get("volumeSellUsd") or row.get("vSellUsd") or row.get("volumeSellUSD")
                if isinstance(bv, (int, float)) and isinstance(sv, (int, float)):
                    net = float(bv) - float(sv)
            if net is not None:
                native_mf[fr] = net
    for i in signal_intervals:
        mf = native_mf.get(i)
        if mf is None:
            b = fnum(_ov(ovd, "vBuy", i + "USD"))
            s2 = fnum(_ov(ovd, "vSell", i + "USD"))
            if isinstance(b, (int, float)) and isinstance(s2, (int, float)):
                mf = b - s2
        money_flow_rows.append((i, mf))

    dev_pct = None
    val = _security_field(secd, ["creatorPercentage", "creatorHold", "creator_percent", "creatorPercent"])
    if isinstance(val, (int, float)):
        dev_pct = float(val) * 100 if float(val) <= 1.0 else float(val)
    top10_pct = None
    val = _security_field(secd, ["top10UserPercent", "top10HolderPercent", "topHoldersPercent"])
    if isinstance(val, (int, float)):
        top10_pct = float(val) * 100 if float(val) <= 1.0 else float(val)
    honeypot = _security_field(secd, ["isHoneyPot", "honeypot", "is_honeypot", "honeypotRisk"])
    if isinstance(honeypot, str):
        honeypot_bool = honeypot.lower() in ("1", "true", "yes", "high")
    elif isinstance(honeypot, (int, float)):
        honeypot_bool = bool(honeypot)
    else:
        honeypot_bool = None
    lp_locked = _security_field(secd, ["lpLocked", "isLpLocked", "lp_locked"])
    if isinstance(lp_locked, (str, int)):
        lp_locked_bool = str(lp_locked).lower() in ("1", "true", "yes")
    else:
        lp_locked_bool = lp_locked if isinstance(lp_locked, bool) else None

    # ===== RUGCHECK EXTENSION: 3 NEW minimal API calls + reuse overview (max 1 call each, NO duplicates) =====
    #         ONLY ACTIVE when caller passes enable_rugcheck_extra=True (Skill #17b).
    #         Skill #3 Token DD BASIC mode always SKIPS this block → remains 71 CU.
    rug_data = {
        "holders_raw": [],
        "holders_top10_pct": top10_pct,  # fallback security aggregate (if holder list call fails)
        "holder_creator_pct": dev_pct,   # fallback security aggregate
        "liq_current_usd": fnum(ovd.get("liquidity")),
        "liq_min_window_usd": None,
        "liq_max_window_usd": None,
        "liq_drawdown_window_pct": None,
        "liq_window": None,
        "insider_cohorts": {},            # from advanced_security/v2: insider/dev/sniper/bundle/bot pct
        "fee_enabled": None,
        "metadata_mutable": None,
        "mint_authority_enabled": None,   # mintable? freeze authority?
        "lp_providers_count": None,
        "lp_unlocked_pct": None,
        "cohort_breakdown": [],
        "gaps": [],
    }

    if not enable_rugcheck_extra:
        rug_data["gaps"].append("rugcheck_disabled_skill3_basic_mode")
    else:
        liq_window = (args_ref.rug_liq_window if (args_ref is not None and hasattr(args_ref, "rug_liq_window")) else "24h") or "24h"
        rug_data["liq_window"] = liq_window
        fee_from_ov = None
        if isinstance(fnum(ovd.get("transferFee")), (int,float)):
            fee_from_ov = True
        else:
            fee_str = str(ovd.get("feeConfig") or "").strip()
            if fee_str not in ("", "0", "null", "None", "{}") or isinstance(fnum(ovd.get("maxFee")), (int,float)):
                fee_from_ov = True
            else:
                fee_from_ov = None
        rug_data["fee_enabled"] = fee_from_ov
        rug_data["mint_authority_enabled"] = (
            None if ovd.get("mintAuthority") is None else (
                False if ovd.get("mintAuthority") in ("", "11111111111111111111111111111111")
                else True
            )
        )
        rug_data["metadata_mutable"] = (
            None if ovd.get("metadataMutable") is None else bool(ovd.get("metadataMutable"))
        )
        rug_data["holder_creator_pct"] = fnum(ovd.get("creatorPercentage")) if fnum(ovd.get("creatorPercentage")) is not None else (
            round(float(ovd.get("creatorHold"))*100,2) if isinstance(ovd.get("creatorHold"),(int,float)) and 0<=float(ovd.get("creatorHold"))<=1 else None
        )
        liq_hist = None
        # ==== RC1 Liquidity min/max/drawdown 24h window ====
        # Priority order (cheap first on failure, 1 call max total):
        # 1) REAL endpoint per user docs: /defi/v3/liquidity/history/token resolution=4h → ~7 points × 1 day  = 50 CU (1m=20 / 4h=50 / 1D=200)
        # 2) Previous legacy guesses (liquidity-ohlc-token 20CU)
        # 3) FALLBACK inference via /defi/v3/token/ohlcv (price 4h × count=7  ~20CU) → no native liq OHLC, but we can approx MIN/MAX liquidity as current_liq * price_min_ratio / price_max_ratio trend proxy. If token overview v24h liquidity known: use liq_current × (1 + 4frame price change %)
        liq_window_hours = {"1h":1,"4h":4,"8h":8,"24h":24}.get(liq_window,24)
        # Count=6 gives 24h for 4h resolution exactly (24/4=6 → +1 extra for current candle open = 7 points per user spec)
        cnt_4h = (liq_window_hours // 4) + 1 if liq_window_hours >= 4 else 7
        liq_paths: list[tuple[str, dict, int]] = [
            ("/defi/v3/liquidity/history/token",
             {"address": address, "resolution": "4h", "count": cnt_4h,
              "time": int(time.time()), "direction": "back"}, 50, "LIQ_HIST_v3_docs"),
            ("/defi/v3/liquidity-ohlc-token",
             {"address": address, "time_window": "1d" if liq_window == "24h" else liq_window}, 20, "LIQ_OHLC_legacy"),
            ("/defi/token_liquidity_history",
             {"address": address, "type": "1d" if liq_window == "24h" else liq_window,
              "interval": "1h" if liq_window in ("24h","8h","4h") else "15m"}, 20, "LIQ_HIST_v2"),
            ("/defi/v1/token/liquidity_history",
             {"address": address, "window": liq_window}, 20, "LIQ_HIST_v1"),
        ]
        liq_hist_raw = None
        for path, pm, step_cu, _tag in liq_paths:
            try:
                lr, _msl = _be(s, key, chain, path, pm)
                cu += step_cu
                breakdown.append(f"rug_liq_hist({liq_window},{_tag})={step_cu}")
                liq_hist_raw = lr
                break
            except RuntimeError:
                continue
        # ========================================================
        # FALLBACK: if ALL 4 liq endpoints failed → INFER MIN/MAX/DD from price OHLC 4H 24h via liq_current * ratio window  (20 CU OHLC price)
        # User instruction: "24h data thì tạm chọn mode 4h lấy được 7 points data rồi tìm min max và tính draw-down"
        # We treat liquidity-min/max trend as proportional proxy liq = current_liquidity_usd * (min/max price ratios  last 4H candles)  →  valid approximation since Solana CPMM pools: liq_usd ≈ 2*sqrt(K) * sqrt(p)  ∝ sqrt(p); but simpler linear proxy ok for MIN/MAX tiering, + label as inference.
        # ========================================================
        infer_label = None
        series_usd: list[float] = []
        if liq_hist_raw is not None:
            arr: list = []
            if isinstance(liq_hist_raw, dict):
                for k in ("data","items","series","liquidity","history","items"):
                    v = liq_hist_raw.get(k)
                    if isinstance(v, list):
                        arr = v
                        break
                if not arr and isinstance(liq_hist_raw.get("data"), dict):
                    d2 = liq_hist_raw["data"]
                    for k2 in ("items", "series", "data", "history", "liquidity"):
                        v2 = d2.get(k2)
                        if isinstance(v2, list):
                            arr = v2
                            break
            elif isinstance(liq_hist_raw, list):
                arr = liq_hist_raw
            for entry in arr:
                if not isinstance(entry, dict): continue
                usd_low = None
                for cand in ("liquidity_usd","liquidityUsd","liquidityUSD","valueUsd","valueUSD","usdLiquidity","liquidity","usd","liqUsd","lowLiquidityUsd","l","low","exit_liquidity_usd","stable_liquidity_usd"):
                    val2 = entry.get(cand)
                    if isinstance(val2, (int, float)):
                        usd_low = float(val2); break
                if usd_low is not None:
                    series_usd.append(usd_low); continue
                hi = None; lo = None
                for cand in ("h","high","highUsd","highUSD","liquidityHigh"):
                    v2 = entry.get(cand)
                    if isinstance(v2,(int,float)): hi = float(v2); break
                for cand in ("l","low","lowUsd","lowUSD","liquidityLow"):
                    v2 = entry.get(cand)
                    if isinstance(v2,(int,float)): lo = float(v2); break
                if isinstance(hi,(int,float)) and isinstance(lo,(int,float)):
                    series_usd.append(lo)
                    series_usd.append(hi)
        # No liq history at all → try price OHLC 4H inference (20 CU) ONLY once
        if len(series_usd) < 2 and isinstance(rug_data.get("liq_current_usd"), (int, float)):
            try:
                ohlc_params = {
                    "address": address,
                    "type": "4H",
                    "time_to": int(time.time()),
                    "time_from": int(time.time()) - 24*3600,
                }
                ohlc_raw, _mshl = _be(s, key, chain, "/defi/v3/ohlcv", ohlc_params)
                cu += 20
                breakdown.append("rug_liq_hist_inference_via_price_ohlcv=20")
                arr: list = []
                if isinstance(ohlc_raw, dict):
                    for k in ("data","items","series"):
                        v = ohlc_raw.get(k)
                        if isinstance(v, list): arr = v; break
                    if not arr and isinstance(ohlc_raw.get("data"), dict):
                        d2 = ohlc_raw["data"]
                        for k2 in ("items", "series", "data"):
                            v2 = d2.get(k2)
                            if isinstance(v2, list):
                                arr = v2
                                break
                elif isinstance(ohlc_raw, list):
                    arr = ohlc_raw
                cur_p = float(rug_data["liq_current_usd"])
                prices: list[float] = []
                for e in arr:
                    if not isinstance(e, dict): continue
                    for cand in ("c","close","Close","o","open","Open"):
                        pv = e.get(cand)
                        if isinstance(pv,(int,float)):
                            prices.append(float(pv)); break
                if len(prices) >= 2 and cur_p > 0:
                    pmax = max(prices); pmin = min(prices); pnow = prices[-1]
                    # Rough proxy: Liquidity on Solana Raydium/Orda is sqrt product ∝ sqrt(price). MIN/MAX liquidity ≈ cur × sqrt(p ratio).
                    import math
                    try:
                        liq_proxy_max = cur_p * math.sqrt(pmax / pnow)
                        liq_proxy_min = cur_p * math.sqrt(pmin / pnow)
                    except Exception:
                        # Even simpler linear fallback
                        liq_proxy_max = cur_p * pmax / pnow
                        liq_proxy_min = cur_p * pmin / pnow
                    series_usd = [liq_proxy_min, cur_p, liq_proxy_max]
                    infer_label = "inferred_from_4h_price_ohlcv_sqrt_proxy"
                    rug_data["liq_window_inferred"] = True
            except RuntimeError:
                pass
        if len(series_usd) >= 2:
            cur_overview = rug_data.get("liq_current_usd")
            series_has_inference = rug_data.get("liq_window_inferred") or infer_label
            if isinstance(cur_overview, (int, float)) and cur_overview > 0 and not series_has_inference:
                snap_latest = series_usd[0] if series_usd[0] > series_usd[-1] else series_usd[-1]
                if snap_latest > 0 and abs(cur_overview - snap_latest) / max(cur_overview, snap_latest) > 0.10:
                    scale = cur_overview / snap_latest
                    series_usd = [v * scale for v in series_usd]
            series_usd.append(float(cur_overview)) if isinstance(cur_overview, (int, float)) else None
            rug_data["liq_min_window_usd"] = round(min(series_usd), 2)
            rug_data["liq_max_window_usd"] = round(max(series_usd), 2)
            peak = rug_data["liq_max_window_usd"]
            cur = cur_overview if isinstance(cur_overview, (int, float)) else series_usd[-1]
            if peak > 0:
                rug_data["liq_drawdown_window_pct"] = round(max(0.0, (peak - float(cur)) / peak * 100.0), 1)
            if infer_label:
                rug_data["gaps"].append(f"rug_liq_hist_{infer_label}")
        else:
            rug_data["gaps"].append("rug_liq_hist_all_paths_failed")
        # ================================================================= RC-2 & RC-3 — UNIFIED single call /token/v1/holder-profile (per docs)
        #   This single endpoint returns ALL of:
        #     a) data.holder  → total holder count
        #     b) data.top10_hold_percent  → EXACT top 10 holding % (NOT estimate)
        #     c) data.items[:N] → Top 20 holder rows (owner, amount, ui_amount, mint)
        #     d) data.tags[] → insider/dev/sniper/bundler/smart_trader/kol with:
        #           holder_count, hold_amount, percent_of_supply, buy/sell vol, pnl, avg_buy_price
        #   Cost documented as 21 CU. We call this once and reuse everything.
        #
        #   FALLBACK paths preserved (holder/v1/distribution, token_security/v2,
        #   defi/token_holders, etc.) but holder-profile is ALWAYS tried first.
        _rug_show_holders = bool(args_ref.rug_show_holders) if (args_ref is not None and hasattr(args_ref, "rug_show_holders")) else True
        _hn = max(20, int(getattr(args_ref, "rug_holders_top_n", 20) or 20))

        # --- Top N holder items + top10% + total holder count (RC-2) paths ---
        #   IMPORTANT: /token/v1/holder-profile returns ONLY tags + summary, NO holder list rows.
        #   Holder list rows come from /holder/v1/distribution OR /defi/*/holder_list endpoints.
        #   Param name on modern endpoints is `token_address` (NOT `address` or HTTP 400).
        holder_list_paths = [
            ("/holder/v1/distribution",          {"mode":"top","top_n":_hn,"include_list":"true","token_address":address}, "rug_holder_distribution=30", 30),
            ("/defi/v2/token/holder_list",       {"token_address": address, "limit": _hn},   "rug_defi_v2_holders=30", 30),
            ("/defi/v3/token/holder_list",       {"token_address": address, "limit": _hn},   "rug_defi_v3_holders=30", 30),
            ("/defi/token_holders",              {"token_address": address, "limit": _hn},   "rug_defi_holders=20",    20),
        ]
        # --- Tag cohorts + insider%/dev%/sniper%/bundle% (RC-3) paths — 21 CU each ---
        #   NOTE: Unified /token/v1/holder-profile returns tags[] (6 cohort types) + summary total holder.
        #   It DOES NOT return holder list rows; we call holder_list_paths above for those.
        cohort_paths = [
            ("/token/v1/holder-profile",         {"token_address": address, "limit": 20},   "rug_cohort_profile=21", 21),
            ("/defi/token_security/v2",          {"token_address": address},                 "rug_cohort_security_v2=21", 21),
        ]
        cohort_payload_raw = None          # raw dict response from RC-3 winning path (for tags[])
        cohort_source_path: str | None = None
        # --- RC-3 cohorts HTTP --- ALWAYS call RC-3 first because it also returns exact total holder count & tags
        for path, pm, cu_label, step_cu in cohort_paths:
            try:
                cpr, _ = _be(s, key, chain, path, pm)
                cu += step_cu
                breakdown.append(cu_label)
                cohort_payload_raw = cpr
                cohort_source_path = path
                break
            except RuntimeError:
                continue
        if cohort_payload_raw is None:
            rug_data["gaps"].append("rug_cohort_profile_all_paths_failed")
        # --- RC-2 holder list HTTP --- only if rug_show_holders is TRUE (default)
        h_payload_raw = None
        hl_source_path: str | None = None
        if _rug_show_holders:
            for path, pm, cu_label, step_cu in holder_list_paths:
                try:
                    hl, _ = _be(s, key, chain, path, pm)
                    cu += step_cu
                    breakdown.append(cu_label)
                    h_payload_raw = hl
                    hl_source_path = path
                    break
                except RuntimeError:
                    continue
        if h_payload_raw is None and _rug_show_holders:
            rug_data["gaps"].append("rug_holder_list_all_paths_failed")

        # --- extract holder items + top10_hold_percent + total_holder_count ---
        #     - Summary aggregates (top10% pct, total_holder_count) PREFER from RC-3 holder-profile (exact native fields):
        #         * holder_profile.data.holder_summary.total_holder
        #         * holder_profile.data.token.top10_holder.percent_of_supply  (already in 0..100)
        #     - Per-row holder items come ONLY from holder_list_paths (distribution/defi/v2/v3 holders)
        hl_data = {}
        hl_items: list[dict] = []
        # PHASE A: Summary aggregates FIRST from holder-profile (RC-3) — best precision.
        if isinstance(cohort_payload_raw, dict):
            cp_data = cohort_payload_raw.get("data") if isinstance(cohort_payload_raw.get("data"), dict) else {}
            if isinstance(cp_data, dict):
                # Top10 exact native: holder_profile.data.token.top10_holder.percent_of_supply (e.g. 57.5606)
                t10_holder_obj = cp_data.get("token", {}).get("top10_holder") if isinstance(cp_data.get("token"), dict) else None
                if isinstance(t10_holder_obj, dict):
                    for t10c in ("percent_of_supply", "hold_percent", "percent", "pct"):
                        tv = t10_holder_obj.get(t10c)
                        if isinstance(tv, (int, float)) and tv > 0:
                            tv_pct = float(tv) * 100 if 0.0 < float(tv) <= 1.0 else float(tv)
                            rug_data["holders_top10_pct"] = round(tv_pct, 2)
                            top10_pct = rug_data["holders_top10_pct"]
                            break
                # Total holders exact native: holder_profile.data.holder_summary.total_holder
                hsum = cp_data.get("holder_summary") if isinstance(cp_data.get("holder_summary"), dict) else None
                if isinstance(hsum, dict):
                    thc = hsum.get("total_holder") or hsum.get("holder_count") or hsum.get("count") or hsum.get("holders")
                    if isinstance(thc, (int, float)):
                        rug_data["total_holder_count_native"] = int(thc)
        # PHASE B: Per-row items from holder_list_paths + summary aggregates if not found above.
        if isinstance(h_payload_raw, dict):
            d = h_payload_raw.get("data") if isinstance(h_payload_raw.get("data"), dict) else {}
            hl_data = d
            if isinstance(d, dict):
                if rug_data.get("holders_top10_pct") is None:
                    for t10c in ("top10_hold_percent", "top10HoldPercent", "top10_holder_pct", "top_10_pct", "top10_pct", "top10_holding_percent"):
                        tv = d.get(t10c)
                        if isinstance(tv, (int, float)) and tv > 0:
                            tv_pct = float(tv) * 100 if 0.0 < float(tv) <= 1.0 else float(tv)
                            rug_data["holders_top10_pct"] = round(tv_pct, 2)
                            top10_pct = rug_data["holders_top10_pct"]
                            break
                if rug_data.get("total_holder_count_native") is None:
                    thc = d.get("holder") or d.get("totalHolder") or d.get("total_holder") or d.get("holder_count")
                    # distribution response top-level summary keys
                    sm = d.get("summary") if isinstance(d.get("summary"), dict) else None
                    if thc is None and isinstance(sm, dict):
                        thc = sm.get("total_holder") or sm.get("holder_count") or sm.get("total_holders")
                    # token-level key (distribution endpoint: token_address string top-level)
                    if isinstance(thc, (int, float)):
                        rug_data["total_holder_count_native"] = int(thc)
                # items list (distribution → data.holders[]; others → items/rows/holders/list)
                for list_key in ("holders", "items", "rows", "list", "topHolders", "holder_list", "holders_list"):
                    maybe = d.get(list_key)
                    if isinstance(maybe, list) and maybe:
                        hl_items = maybe
                        break
                if not hl_items:
                    stack = [d]
                    seen = set()
                    while stack and not hl_items:
                        cur = stack.pop()
                        if id(cur) in seen:
                            continue
                        seen.add(id(cur))
                        if isinstance(cur, dict):
                            for list_key in ("holders", "items", "rows", "list", "topHolders", "holder_list", "holders_list"):
                                maybe = cur.get(list_key)
                                if isinstance(maybe, list) and maybe:
                                    hl_items = maybe
                                    break
                            if hl_items:
                                break
                            for v in cur.values():
                                if isinstance(v, (dict, list)):
                                    stack.append(v)
                        elif isinstance(cur, list):
                            if cur and all(isinstance(x, dict) for x in cur[:3]):
                                hl_items = cur
                                break
                            for v in cur:
                                if isinstance(v, (dict, list)):
                                    stack.append(v)
        # Build clean holder rows from extracted items (top _hn)
        holders_clean: list[dict] = []
        pct_sum_top10 = 0.0
        creator_pct = None
        for idx, raw in enumerate(hl_items[: _hn]):
            if not isinstance(raw, dict):
                continue
            owner = raw.get("owner") or raw.get("address") or raw.get("holder") or raw.get("wallet") or raw.get("account") or raw.get("token_account") or ""
            pct = None
            for cand in ("pct", "percentage", "percent", "pctOwned", "ownershipPercent", "share", "holdPercent", "pct_of_supply", "percentOfSupply", "holdingPercent", "percent_of_supply"):
                v = raw.get(cand)
                if isinstance(v, (int, float)):
                    pct = float(v) * 100 if 0.0 < float(v) <= 1.0 else float(v)
                    break
                if isinstance(v, str):
                    try:
                        pf = float(v); pct = pf * 100 if 0.0 < pf <= 1.0 else pf; break
                    except Exception:
                        pass
            if pct is None:
                amt = None
                for cand in ("ui_amount", "amount", "balance", "value", "quantity", "holdingAmount", "holding"):
                    vv = raw.get(cand)
                    if isinstance(vv, (int, float)):
                        amt = float(vv); break
                    if isinstance(vv, str):
                        try: amt = float(vv); break
                        except Exception: pass
                total_supply = fnum(ovd.get("supply")) or fnum(ovd.get("totalSupply"))
                if isinstance(amt, (int, float)) and isinstance(total_supply, (int, float)) and total_supply > 0:
                    pct = amt / total_supply * 100.0
            usd = None
            for cand in ("valueUsd", "valueUSD", "usdValue", "usd_value", "holdingUsd", "worthUsd", "usd", "holdingUSD", "amountUsd", "amountUSD", "balanceUsd"):
                v2 = raw.get(cand)
                if isinstance(v2, (int, float)):
                    usd = float(v2); break
                if isinstance(v2, str):
                    try: usd = float(v2); break
                    except Exception: pass
            if usd is None:
                amt4usd = None
                for c4 in ("ui_amount", "amount", "balance", "value", "quantity", "holdingAmount", "holding"):
                    v4 = raw.get(c4)
                    if isinstance(v4, (int, float)): amt4usd = float(v4); break
                    if isinstance(v4, str):
                        try: amt4usd = float(v4); break
                        except Exception: pass
                prc = fnum(ovd.get("price")) or fnum(ovd.get("priceUsd")) or fnum(ovd.get("priceUSD"))
                if isinstance(amt4usd, (int, float)) and isinstance(prc, (int, float)) and prc > 0:
                    usd = float(amt4usd) * float(prc)
            lbl = None
            for cand in ("label", "tag", "role", "name", "type", "annotation", "category"):
                v3 = raw.get(cand)
                if isinstance(v3, str) and v3:
                    lbl = v3.replace("_", " ").title(); break
            tags_raw = raw.get("tags") or raw.get("tag") or []
            if lbl is None and isinstance(tags_raw, list) and tags_raw:
                lbl = ", ".join([str(t).replace("_", " ").title() for t in tags_raw[:3]])
            elif lbl is None and isinstance(tags_raw, str) and tags_raw:
                lbl = tags_raw.replace("_", " ").title()
            elif lbl is None and isinstance(owner, str):
                o_l = owner.lower()
                if "creator" in o_l or "deploy" in o_l or (idx > 0 and idx <= 2 and (dev_pct and isinstance(pct, (int, float)) and pct > (dev_pct - 3) and pct < (dev_pct + 3))):
                    lbl = "Creator / Deployer"
                elif any(k in o_l for k in ("pool", "lp", "amm", "dex", "raydium", "meteora", "orca")):
                    lbl = "AMM Pool Authority"
            # amount_raw: prefer ui_amount (human) over raw amount (lamport/gwei) over holding.
            amt_display = None
            for cand_d in ("ui_amount", "display_amount", "human_amount"):
                if isinstance(raw.get(cand_d), (int, float)):
                    amt_display = f"{float(raw[cand_d]):,.6f}".rstrip("0").rstrip("."); break
                if isinstance(raw.get(cand_d), str) and raw.get(cand_d).strip():
                    amt_display = raw.get(cand_d).strip(); break
            if amt_display is None:
                # Try amount / balance / quantity / holding fields — format with comma thousands if numeric > 1000.
                found_amt_num = None
                for cand_a in ("amount", "balance", "value", "quantity", "holding", "holdingAmount", "amountRaw", "rawAmount"):
                    a = raw.get(cand_a)
                    if isinstance(a, (int, float)):
                        found_amt_num = float(a); break
                    if isinstance(a, str) and a.strip():
                        try: found_amt_num = float(a); break
                        except Exception: amt_display = a.strip(); break
                if amt_display is None and found_amt_num is not None:
                    if abs(found_amt_num) >= 1e9:
                        amt_display = f"{found_amt_num/1e9:,.4f}B"
                    elif abs(found_amt_num) >= 1e6:
                        amt_display = f"{found_amt_num/1e6:,.4f}M"
                    elif abs(found_amt_num) >= 1e3:
                        amt_display = f"{found_amt_num:,.4f}".rstrip("0").rstrip(".")
                    else:
                        amt_display = f"{found_amt_num:.12f}".rstrip("0").rstrip(".") or "0"
                if amt_display is None:
                    amt_display = ""
            hrec = {"rank": idx + 1, "owner": str(owner),
                    "pct": round(float(pct), 2) if isinstance(pct, (int, float)) else None,
                    "owner_short": (str(owner)[:6] + "…" + str(owner)[-4:]) if len(str(owner)) > 10 else str(owner),
                    "label": lbl,
                    "tags": [str(t) for t in (tags_raw if isinstance(tags_raw, list) else [tags_raw if isinstance(tags_raw, str) else None]) if t],
                    "usd_value": round(float(usd), 2) if isinstance(usd, (int, float)) else None,
                    "amount_raw": str(amt_display)[:28]}
            holders_clean.append(hrec)
            if isinstance(pct, (int, float)) and idx < 10:
                pct_sum_top10 += float(pct)
            if lbl and ("creator" in lbl.lower() or "deploy" in lbl.lower()) and isinstance(pct, (int, float)):
                creator_pct = float(pct)
        rug_data["holders_raw"] = holders_clean
        # Use the EXACT API top10_hold_percent first; fall back to 10-row sum
        if rug_data.get("holders_top10_pct") is None and pct_sum_top10 > 0:
            rug_data["holders_top10_pct"] = round(pct_sum_top10, 2)
            top10_pct = rug_data["holders_top10_pct"]
        if isinstance(creator_pct, (int, float)):
            rug_data["holder_creator_pct"] = round(creator_pct, 2)
            dev_pct = rug_data["holder_creator_pct"]
        sum_claimed_lp = 0.0
        lp_provider_count = 0
        for h in holders_clean:
            tgs = " ".join(h["tags"]).lower() + " " + (h["label"] or "").lower()
            if any(w in tgs for w in ("pool", "amm", "lp", "meteora", "raydium", "orca", "dex", "authority")):
                lp_provider_count += 1
                if isinstance(h["pct"], (int, float)):
                    if "lock" not in tgs and "locked" not in tgs:
                        sum_claimed_lp += float(h["pct"])
        rug_data["lp_providers_count"] = max(lp_provider_count, 1) if lp_provider_count else fnum(ovd.get("uniqueWallet1h"))
        rug_data["lp_unlocked_pct"] = round(sum_claimed_lp, 2) if sum_claimed_lp > 0 else None

        # ============================================================ RC-3 Tag cohorts (insider/dev/sniper/bundler/sm_trader/kol)
        cohort_payload = None
        if isinstance(cohort_payload_raw, dict):
            cd = cohort_payload_raw.get("data") if isinstance(cohort_payload_raw.get("data"), dict) else {}
            if isinstance(cd, dict) and isinstance(cd.get("tags"), list):
                cohort_payload = cd
            else:
                # Some security endpoints flatten response
                cohort_payload = cohort_payload_raw if isinstance(cohort_payload_raw.get("tags"), list) else cd
        if cohort_payload is None and cohort_payload_raw is not None:
            # Fallback flat dict (security v2) with cohort_<name>_pct flat keys
            cohort_payload = (cohort_payload_raw.get("data") if isinstance(cohort_payload_raw.get("data"), dict) else {}) or {}
        if cohort_payload is None:
            rug_data["gaps"].append("rug_adv_security_all_paths_failed")
        else:
            direct_tags: list[dict] = []
            if isinstance(cohort_payload, dict):
                tags_field = cohort_payload.get("tags")
                if isinstance(tags_field, list):
                    for tg in tags_field:
                        if not isinstance(tg, dict):
                            continue
                        nm = str(tg.get("tag") or tg.get("name") or tg.get("label") or "").strip().lower()
                        # pct = percent_of_supply — BIRDEYE holder-profile ALWAYS returns 0..100 (NOT 0..1 ratio).
                        #   Values 57.555 => 57.6%;  0.90306 => 0.90%;  0.00117 => 0.0012%.
                        #   OLD BUG: heuristic pct<=1 → *100 DOUBLE-SCALED everything < 1% → huge wrong.
                        #   Fix strategy:
                        #     • if raw key resolved FIRST from "percent_of_supply" → pass-through 0..100 (NEVER multiply).
                        #     • generic aliases (pct/hold_percent/share): treat <= 0.005 as true ratio 0..1 → *100;
                        #       0.005..100 pass-through as percentage (0.9 => 0.9% NOT 90%); >100 clmap pass-through.
                        pct_raw = None
                        pct_from_native_key = False
                        for pct_cand in ("percent_of_supply", "pct", "percentage", "hold_percent", "holdPercent", "ownership_pct", "share"):
                            pv = tg.get(pct_cand)
                            if isinstance(pv, (int, float)):
                                pct_raw = float(pv)
                                pct_from_native_key = (pct_cand == "percent_of_supply")
                                break
                            if isinstance(pv, str):
                                try:
                                    pct_raw = float(pv)
                                    pct_from_native_key = (pct_cand == "percent_of_supply")
                                    break
                                except Exception:
                                    pass
                        pct_val = None
                        if isinstance(pct_raw, (int, float)):
                            if pct_from_native_key:
                                # /token/v1/holder-profile tags[].percent_of_supply is guaranteed 0..100.
                                pct_val = float(pct_raw)
                            else:
                                # Generic alias: only values <= 0.005 are likely ratio 0..1 (scale *100).
                                # 0.005 (0.5% ratio) would mean 0.00005 as percent → impossible; so it's ratio.
                                if 0.0 < float(pct_raw) <= 0.005:
                                    pct_val = float(pct_raw) * 100.0
                                else:
                                    pct_val = float(pct_raw)
                        # holder_count (from endpoint: integer, tag shape = {"holder_count":22})
                        hc_raw = None
                        for hc_cand in ("holder_count", "count", "holdersCount", "holders_count", "wallets", "num_holders"):
                            hv = tg.get(hc_cand)
                            if isinstance(hv, (int, float)):
                                hc_raw = int(hv); break
                            if isinstance(hv, str):
                                try: hc_raw = int(float(hv)); break
                                except Exception: pass
                        # hold_amount native token qty (string numeric in response)
                        hold_amt = None
                        for ha in ("hold_amount", "holdAmount", "amount", "quantity"):
                            hav = tg.get(ha)
                            if isinstance(hav, (int, float)): hold_amt = float(hav); break
                            if isinstance(hav, str):
                                try: hold_amt = float(hav); break
                                except Exception: pass
                        # Extra capture: buy_volume_usd / sell_volume_usd / avg_buy_price / pnl (ALL CAN BE numeric string in endpoint!)
                        extra = {}
                        for k, aliases in (
                            ("buy_volume_usd", ("buy_volume_usd", "buyVolumeUsd", "buyVolumeUSD", "buyVolUsd")),
                            ("sell_volume_usd", ("sell_volume_usd", "sellVolumeUsd", "sellVolumeUSD", "sellVolUsd")),
                            ("avg_buy_price", ("avg_buy_price", "avgBuyPrice", "averageBuyPrice", "avgBuy")),
                            ("pnl", ("pnl", "profit", "profitLossUsd", "realizedPnlUsd", "unrealizedPnlUsd")),
                            ("buy_volume", ("buy_volume", "buyVol", "buyVolumeNative")),
                            ("sell_volume", ("sell_volume", "sellVol", "sellVolumeNative")),
                            ("hold_amount", ("hold_amount", "holdAmount", "hold_native_amount")),
                        ):
                            for a in aliases:
                                val = tg.get(a)
                                if isinstance(val, (int, float)):
                                    extra[k] = float(val); break
                                if isinstance(val, str):
                                    try: extra[k] = float(val); break
                                    except Exception: pass
                        if nm and (pct_val is not None or hc_raw is not None):
                            rowd = {"name": nm, "pct": pct_val, "holder_count": hc_raw}
                            if hold_amt is not None: rowd["hold_amount"] = hold_amt
                            rowd.update(extra)
                            direct_tags.append(rowd)
            cohorts: dict[str, Any] = {}
            cohort_rows: list[dict] = []
            for rec in direct_tags:
                nm = rec["name"]
                disp = {"smart_trader": "smartMoney", "smart_traders": "smartMoney",
                        "kol": "whale", "bundler": "bundle", "dev_team": "dev",
                        "developer": "dev", "insiders": "insider", "snipers": "sniper",
                        "dev": "dev", "insider": "insider", "sniper": "sniper",
                        "bundle": "bundle", "bot": "bot", "airdrop": "airdrop",
                        "whale": "whale", "smartmoney": "smartMoney"}.get(nm, nm)
                if nm in ("insider", "dev", "sniper", "bundle", "bot", "airdrop", "whale", "smartMoney", "kol", "smart_trader", "bundler", "snipers", "insiders", "developer") or disp in ("insider", "dev", "sniper", "bundle", "bot", "airdrop", "whale", "smartMoney"):
                    if isinstance(rec.get("pct"), (int, float)):
                        cohorts[disp] = round(float(rec["pct"]), 4)
                    hc = rec.get("holder_count")
                    extra = {k: rec[k] for k in ("buy_volume_usd", "sell_volume_usd", "avg_buy_price", "pnl", "buy_volume", "sell_volume", "hold_amount") if rec.get(k) is not None}
                    row = {"name": disp,
                           "pct": round(float(rec["pct"]), 4) if isinstance(rec.get("pct"), (int, float)) else None,
                           "holder_count": int(hc) if isinstance(hc, (int, float)) else None}
                    row.update(extra)
                    cohort_rows.append(row)
            # Fallback: scan flat key fields inside payload if no structured tags[]
            COHORT_KEYS = [
                ("insider",   ["insiderPct", "insider_pct", "insiderPercent", "insider", "insidersPct", "ownerInsiderPct"]),
                ("dev",       ["devPct", "dev_pct", "developerPct", "devTeamPct", "devPercent", "developerPercent", "deployerPct", "teamPct"]),
                ("sniper",    ["sniperPct", "sniper_pct", "sniperPercent", "snipersPct", "botSniperPct", "sniper"]),
                ("bundle",    ["bundlePct", "bundle_pct", "bundlePercent", "bundlerPct", "bundlersPct", "mevBundlePct", "bundle"]),
                ("bot",       ["botPct", "bot_pct", "botPercent", "botWashPct", "botsPct", "bot"]),
                ("airdrop",   ["airdropPct", "airdrop_pct", "airdropPercent", "airdrop"]),
                ("whale",     ["whalePct", "whale_pct", "whalePercent", "whale"]),
                ("smartMoney",["smartPct", "smart_pct", "smartMoneyPct", "smartMoneyPercent", "smPct", "smart", "smart_trader"]),
            ]
            for display, keys in COHORT_KEYS:
                if cohorts.get(display):
                    continue
                v_found = None
                for k in keys:
                    if isinstance(cohort_payload, dict) and k in cohort_payload and isinstance(cohort_payload[k], (int, float)):
                        v_found = float(cohort_payload[k]); break
                if v_found is not None and (v_found > 0.000001 or display in ("insider", "dev", "sniper", "bundle")):
                    # Tighten 0..1 vs 0..100 heuristic.
                    # Only ratios <= 0.005 treated as true 0..1 ratio (multiply by 100).
                    # Percentages like 0.903 (0.9%) never multiplied; smart_money) passthrough.
                    if 0.0 < v_found <= 0.005:
                        v_found_pct = v_found * 100.0
                    else:
                        v_found_pct = float(v_found)
                    cohorts[display] = round(v_found_pct, 4)
                    already = next((r for r in cohort_rows if r.get("name") == display), None)
                    if not already:
                        cohort_rows.append({"name": display, "pct": round(v_found_pct, 4),
                                            "holder_count": None})
            rug_data["insider_cohorts"] = cohorts
            # fee_enabled / metadata_mutable / mint_authority / lp_unlocked / lp_providers still parsed from security payload
            if not rug_data.get("fee_enabled"):
                for fk in ("feeConfigured", "hasFee", "feeEnabled", "feeConfig", "transferFeeEnabled", "isTransferFeeEnabled", "hasTransferFee"):
                    if isinstance(cohort_payload, dict) and fk in cohort_payload and rug_data.get("fee_enabled") is None:
                        vf = cohort_payload[fk]
                        if isinstance(vf, bool): rug_data["fee_enabled"] = vf
                        elif isinstance(vf, (int, float)): rug_data["fee_enabled"] = bool(vf)
                        elif isinstance(vf, str): rug_data["fee_enabled"] = vf.lower() in ("1", "true", "yes", "enabled")
            if rug_data.get("metadata_mutable") is None:
                for mk in ("metadataMutable", "mutableMetadata", "metadataIsMutable", "isMetadataMutable", "isMutable", "updatableMetadata"):
                    if isinstance(cohort_payload, dict) and mk in cohort_payload:
                        vm = cohort_payload[mk]
                        if isinstance(vm, bool): rug_data["metadata_mutable"] = vm
                        elif isinstance(vm, (int, float)): rug_data["metadata_mutable"] = bool(vm)
                        elif isinstance(vm, str): rug_data["metadata_mutable"] = (vm.lower() in ("1", "true", "yes", "mutable", "update"))
            if rug_data.get("mint_authority_enabled") is None:
                for mk2 in ("mintAuthorityEnabled", "mintEnabled", "hasMintAuthority", "mintable", "isMintable", "freezeAuthorityEnabled", "hasFreezeAuthority"):
                    if isinstance(cohort_payload, dict) and mk2 in cohort_payload:
                        vma = cohort_payload[mk2]
                        if isinstance(vma, bool): rug_data["mint_authority_enabled"] = vma
                        elif isinstance(vma, (int, float)): rug_data["mint_authority_enabled"] = bool(vma)
                        elif isinstance(vma, str): rug_data["mint_authority_enabled"] = (vma.lower() in ("1", "true", "yes", "enabled", "present"))
            if rug_data.get("lp_unlocked_pct") is None:
                for kp in ("lpUnlockedPct", "lp_unlocked_pct", "unlockedLpPercent", "liquidityUnlockedPct", "lpNotLockedPct"):
                    if isinstance(cohort_payload, dict) and kp in cohort_payload and isinstance(cohort_payload[kp], (int, float)):
                        vf2 = float(cohort_payload[kp])
                        rug_data["lp_unlocked_pct"] = round(vf2 * 100 if vf2 <= 1.0 else vf2, 2); break
            if rug_data.get("lp_providers_count") is None:
                for kl in ("lpProviders", "lpProviderCount", "liquidityProviders", "ammPoolCount"):
                    if isinstance(cohort_payload, dict) and kl in cohort_payload and isinstance(cohort_payload[kl], (int, float)):
                        rug_data["lp_providers_count"] = int(cohort_payload[kl]); break
            named_rows = []
            for row in cohort_rows:
                nm = row["name"].title().replace("Smartmoney", "SmartMoney")
                p = row.get("pct") or 0
                tier = "high" if p >= 15 else ("warn" if p >= 5 else ("caution" if p >= 1 else "low"))
                nr = {**row, "name": nm, "pct": round(p, 2) if isinstance(p, (int, float)) else p, "tier": tier}
                named_rows.append(nr)
            rug_data["cohort_breakdown"] = named_rows or cohort_rows
    # (end if enable_rugcheck_extra)

    # Invariants / pipeline gaps
    gaps: list[str] = []
    if not sec_ok:
        gaps.append("security_request_failed")
    if not sm_ok:
        gaps.append("smart_money_request_failed")
    # Invariant 1: net flow proxy should match vBuy - vSell within 5%
    for entry in buy_sell_rows:
        (iv, t2, b, s2, ratio, *_) = entry
        if isinstance(b, (int, float)) and isinstance(s2, (int, float)) and isinstance(t2, (int, float)) and t2 > 0:
            if abs((b + s2) - t2) / t2 > 0.07:
                gaps.append(f"sum(vBuy+vSell)≠v{iv}")
    # Invariant 2: price change X% must match (price - historyPrice)/historyPrice
    for i, dp in price_rows:
        hist = fnum(_ov(ovd, "history", i + "Price"))
        prc = fnum(ovd.get("price"))
        if isinstance(dp, (int, float)) and isinstance(hist, (int, float)) and isinstance(prc, (int, float)) and hist > 0:
            calc = (prc - hist) / hist * 100.0
            if abs(calc - dp) > 0.5:
                gaps.append(f"priceCalcMismatch:{i}")
    # Invariant 3: moneyFlow list net == vBuy$ - vSell$ within 5% (if native found)
    iv_mf_map = {i: mf for i, mf in money_flow_rows}
    for entry in buy_sell_rows:
        (iv, t2, b, s2, ratio, *_) = entry
        nf = iv_mf_map.get(iv)
        if isinstance(nf, (int, float)) and isinstance(b, (int, float)) and isinstance(s2, (int, float)):
            proxy = b - s2
            base = max(abs(proxy), abs(nf), 1.0)
            if abs(nf - proxy) / base > 0.05:
                gaps.append(f"moneyFlowMismatch:{iv}")
                break
    # Invariant 4: dev% + top10% must not exceed 105
    if isinstance(dev_pct, (int, float)) and isinstance(top10_pct, (int, float)):
        if dev_pct + top10_pct > 105:
            gaps.append(f"dev+top10_exceed_100:{dev_pct+top10_pct:.1f}")

    # ---- Scoring (simple weighted; user revises later) ----
    sec_score = 5.0
    if dev_pct is not None:
        if dev_pct < 2: sec_score += 3
        elif dev_pct < 5: sec_score += 2
        elif dev_pct < 10: sec_score += 1
        else: sec_score -= 2
    if top10_pct is not None:
        if top10_pct < 20: sec_score += 2
        elif top10_pct < 40: sec_score += 1
        else: sec_score -= 2
    if honeypot_bool is True:
        sec_score = 0.0
    if lp_locked_bool is True:
        sec_score += 1
    sec_score = max(0.0, min(10.0, sec_score))

    act_score = 5.0
    buy_last = None
    for entry in buy_sell_rows:
        if entry[4] is not None:
            buy_last = entry[4]
    if buy_last is not None:
        if buy_last >= 0.62: act_score += 3
        elif buy_last >= 0.55: act_score += 2
        elif buy_last >= 0.51: act_score += 1
        elif buy_last <= 0.38: act_score -= 3
        elif buy_last <= 0.45: act_score -= 2
    if sm_no is not None:
        if sm_no >= 30: act_score += 3
        elif sm_no >= 10: act_score += 2
        elif sm_no >= 3: act_score += 1
    # trend slope over 5m→1h→4h
    pct_map = {i: p for i, p in price_rows}
    if pct_map.get("1h") is not None and pct_map.get("4h") is not None:
        try:
            slope = float(pct_map["4h"]) - float(pct_map.get("5m", pct_map["1h"]))
            if slope > 30: act_score += 1
            elif slope < -30: act_score -= 1
        except Exception:
            pass
    act_score = max(0.0, min(10.0, act_score))

    vol_score = 5.0
    # check if vol increases window-to-window
    vs = [b for b in buy_sell_rows if b[1] is not None]
    if len(vs) >= 2:
        up = 0
        for a, b2 in zip(vs, vs[1:]):
            if b2[1] > a[1]: up += 1
        vol_score += up
        if up == 0: vol_score -= 2
    vol_score = max(0.0, min(10.0, vol_score))

    smkt_score = 5.0
    if sm_rank is not None:
        if sm_rank <= 10: smkt_score += 4
        elif sm_rank <= 30: smkt_score += 3
        elif sm_rank <= 60: smkt_score += 2
        else: smkt_score += 1
    if sm_no is not None and sm_rank is None:
        if sm_no >= 20: smkt_score += 2
    smkt_score = max(0.0, min(10.0, smkt_score))

    # ---- Dead-volume guard: virtually no trade activity (volume≈0) while market cap is meaningful
    #      => token likely illiquid / rug-drop / holders trapped -> ACT/SMKT/VOL forced ~0.
    _vol_sum_all_windows = 0.0
    _vol_any_window_gt_zero = False
    for _e in buy_sell_rows:
        _b = _e[2] if len(_e) > 2 else None
        _s2 = _e[3] if len(_e) > 3 else None
        if isinstance(_b, (int, float)) and isinstance(_s2, (int, float)):
            _tot = _b + _s2
            if _tot > 1.0:
                _vol_any_window_gt_zero = True
            _vol_sum_all_windows += _tot
    _mcap_num = fnum(ovd.get("marketCap") or ovd.get("marketcap"))
    if (not _vol_any_window_gt_zero or _vol_sum_all_windows < 250.0) and isinstance(_mcap_num, (int, float)) and _mcap_num >= 50000.0:
        smkt_score = 0.0
        act_score = 0.0
        vol_score = 0.0
        gaps.append(f"dead_volume_high_mcap:volUsdSum={_vol_sum_all_windows:.0f}:mc=${_mcap_num:,.0f} → SMKT/ACT/VOL forced ≈0")

    final = (sec_score * 0.30 + smkt_score * 0.25 + act_score * 0.25 + vol_score * 0.20)

    if final >= 7.5:
        verdict = "STRONG BUY"
    elif final >= 6.2:
        verdict = "BUY"
    elif final >= 5.0:
        verdict = "HOLD / WATCH"
    elif final >= 3.5:
        verdict = "AVOID"
    else:
        verdict = "SELL / RED FLAG"

    breakdown_str = " + ".join(breakdown) + f" = {cu} CU"

    return {
        "address": address, "chain": chain,
        "symbol": ovd.get("symbol") or "?",
        "name": ovd.get("name") or "",
        "decimals": ovd.get("decimals"),
        "price_usd": fnum(ovd.get("price")),
        "marketcap_usd": fnum(ovd.get("marketCap")) or fnum(ovd.get("marketcap")),
        "fdv_usd": fnum(ovd.get("fdv")),
        "liquidity_usd": fnum(ovd.get("liquidity")),
        "holder_count": fnum(ovd.get("holder")),
        "snapshot_time": snap,
        "price_changes": price_rows,
        "buy_sell_rows": buy_sell_rows,
        "money_flow_rows": money_flow_rows,
        "security": {
            "dev_holding_pct": dev_pct, "top10_holder_pct": top10_pct,
            "honeypot": honeypot_bool, "lp_locked": lp_locked_bool,
            "raw": {k: secd[k] for k in ["creatorPercentage", "top10UserPercent", "isHoneyPot", "lpLocked"] if k in secd} if secd else None,
        },
        "smart_money": {"smart_traders_no": sm_no, "rank_in_sm_top100": sm_rank,
                        "batch_join_success": sm_ok},
        "scores": {"sec": round(sec_score, 1), "smkt": round(smkt_score, 1),
                   "act": round(act_score, 1), "vol": round(vol_score, 1),
                   "final": round(final, 1), "verdict": verdict},
        "invariants": {"gaps": gaps, "count": len(gaps)},
        "rugcheck": rug_data,
        "cu_used_total": cu, "cu_breakdown": breakdown_str,
        "latency_ms": ms,
    }


def _print_dd_plain(d: dict, args):
    chain = args.chain.upper()
    mc = d["marketcap_usd"]
    liq = d["liquidity_usd"]
    prc = d["price_usd"]
    fdv = d["fdv_usd"]
    head = (f"🛡  {chain}  {d['symbol']}   ({d['name'][:28] if d['name'] else '—'})   "
            f"${prc:.6f}" if isinstance(prc, (int, float)) and prc < 1 else
            f"🛡  {chain}  {d['symbol']}   ({d['name'][:28] if d['name'] else '—'})   ${prc:,.2f}" if isinstance(prc, (int, float)) else
            f"🛡  {chain}  {d['symbol']}   ({d['name'][:28] if d['name'] else '—'})")
    sub = (f"   MC {_fmt_usd(mc)} · LIQ {_fmt_usd(liq)} · FDV {_fmt_usd(fdv)} · "
           f"Holders {int(d['holder_count']):,}" if isinstance(d['holder_count'], (int, float)) else
           f"   MC {_fmt_usd(mc)} · LIQ {_fmt_usd(liq)} · FDV {_fmt_usd(fdv)}")
    print(head)
    print(sub)
    print(f"   Address: {d['address']}")
    print("-" * 78)
    print("RISK / SECURITY")
    sec = d["security"]
    dev = sec["dev_holding_pct"]
    t10 = sec["top10_holder_pct"]
    hp = sec["honeypot"]
    lp = sec["lp_locked"]
    line = []
    line.append(f"  Dev hold: {'N/A' if dev is None else f'{dev:.1f}% ' + ('✅' if dev<2 else ('⚠' if dev<8 else '🔴'))}")
    line.append(f"  Top10: {'N/A' if t10 is None else f'{t10:.1f}% ' + ('✅' if t10<20 else ('⚠' if t10<40 else '🔴'))}")
    if hp is not None:
        line.append(f"  Honeypot: {'🔴 YES' if hp else '✅ NO'}")
    if lp is not None:
        line.append(f"  LP lock: {'✅ YES' if lp else '⚠ NO'}")
    print("\n".join(line))
    print("-" * 78)
    print("PRICE ACTION  — window ΔP%       (negative = red when printed)")
    w = max(10, 10)
    parts = []
    for i, p in d["price_changes"]:
        parts.append(f"{i:>4} {_fmt_pct(p):>8}")
    print("   " + "  ".join(parts))
    print("-" * 78)
    print("BUY/SELL PRESSURE + MONEY FLOW")
    header = f"   {'win':<4} {'Vol$':>10} {'Buy$':>10} {'Sell$':>10} {'B%':>5} {'Buys':>7} {'Sells':>7} {'TradeB%':>8} {'Wallets':>9} {'NetFlow$':>11}"
    print(header)
    mf_map = {i: mf for i, mf in d["money_flow_rows"]}
    for (i, t2, b, s2, ratio, buys, sells, tr_ratio, wal) in d["buy_sell_rows"]:
        cells = [
            f"{i:<4}",
            f"{_fmt_usd(t2):>10}",
            f"{_fmt_usd(b):>10}",
            f"{_fmt_usd(s2):>10}",
            f"{(f'{ratio*100:.0f}%' if ratio is not None else 'N/A'):>5}",
            f"{int(buys):,}" if isinstance(buys, (int, float)) else "N/A".rjust(7),
            f"{int(sells):,}" if isinstance(sells, (int, float)) else "N/A".rjust(7),
            f"{(f'{tr_ratio*100:.0f}%' if tr_ratio is not None else 'N/A'):>8}",
            f"{int(wal):,}" if isinstance(wal, (int, float)) else "N/A".rjust(9),
            f"{_fmt_usd(mf_map.get(i)):>11}",
        ]
        # align columns 5-8
        for idx in (5, 6, 7, 8):
            if not cells[idx].startswith(" "):
                cells[idx] = cells[idx].rjust(len(cells[idx]) if len(cells[idx]) > 7 else 7)
        print("   " + " ".join(cells))
    print("-" * 78)
    print("SMART MONEY")
    sm = d["smart_money"]
    if sm["batch_join_success"] and sm["smart_traders_no"] is None:
        print(f"   Not in global smart-money top 100 today (0 SM wallets tracked).")
    elif sm["smart_traders_no"] is not None:
        rnk = f" (rank #{sm['rank_in_sm_top100']}/100)" if sm["rank_in_sm_top100"] else ""
        print(f"   Wallets holding: {int(sm['smart_traders_no']):,}{rnk}  "
              f"{'🌟🌟🌟' if sm['smart_traders_no']>=30 else ('🌟🌟' if sm['smart_traders_no']>=10 else ('🌟' if sm['smart_traders_no']>=3 else ''))}")
    else:
        print(f"   Request failed.")
    print("-" * 78)
    sc = d["scores"]
    print(f"SCORES   SEC {sc['sec']:.1f}/10   SMKT {sc['smkt']:.1f}/10   ACT {sc['act']:.1f}/10   VOL {sc['vol']:.1f}/10  →  ⭐ FINAL {sc['final']:.1f}/10")
    print(f"VERDICT: {sc['verdict']}")
    print(f"\n⚡CU: {d['cu_used_total']}  ({d['cu_breakdown']})  |  ⏱{d['latency_ms']}ms  |  📸{d['snapshot_time']}")
    gaps = d["invariants"]["gaps"]
    if gaps:
        print(f"⚠ {len(gaps)} pipeline gap(s): {', '.join(gaps[:6])}{' …' if len(gaps)>6 else ''}")
    else:
        print("✅ All invariants passed (priceCalc, buySellSum).")


def _print_dd_telegram(d: dict, args):
    chain = args.chain.upper()
    prc = d["price_usd"]
    prc_s = f"${prc:.6f}" if isinstance(prc, (int, float)) and prc < 1 else (f"${prc:,.2f}" if isinstance(prc, (int, float)) else "N/A")
    lines = [
        f"🛡 *Token DD — {chain} · {d['symbol']}*  ({d['name'][:26] if d['name'] else '—'})",
        f"_Price: {prc_s} · MC {_fmt_usd(d['marketcap_usd'])} · LIQ {_fmt_usd(d['liquidity_usd'])}_",
        f"`{d['address']}`",
        "",
        "*Risk / Security*",
        "```",
    ]
    sec = d["security"]
    dev, t10, hp, lp = sec["dev_holding_pct"], sec["top10_holder_pct"], sec["honeypot"], sec["lp_locked"]
    def mark(v, ok_low, warn_low=None):
        if v is None: return "N/A"
        if v < (ok_low or 0): return f"{v:.1f}% ✅"
        if warn_low is not None and v < warn_low: return f"{v:.1f}% ⚠"
        return f"{v:.1f}% 🔴"
    lines.append(f"Dev hold : {mark(dev, 2, 8)}")
    lines.append(f"Top10    : {mark(t10, 20, 40)}")
    if hp is not None: lines.append(f"Honeypot : {'🔴 YES' if hp else '✅ NO'}")
    if lp is not None: lines.append(f"LP lock  : {'✅ YES' if lp else '⚠ NO'}")
    lines.append("```")
    lines.append("")
    lines.append("*Price Δ% by window*")
    lines.append("```")
    lines.append(" ".join(f"{i:>4} {_fmt_pct(p):>8}" for i, p in d["price_changes"]))
    lines.append("```")
    lines.append("")
    lines.append("*Buy/Sell & Money Flow*")
    lines.append("```")
    lines.append(f"{'win':<4} {'Vol$':>9} {'Buy%':>5} {'TrB%':>5} {'NetFlow$':>11}")
    mf_map = {i: mf for i, mf in d["money_flow_rows"]}
    for (i, t2, b, s2, ratio, buys, sells, tr_ratio, wal) in d["buy_sell_rows"]:
        bp = f"{ratio*100:.0f}%" if ratio is not None else "N/A"
        tb = f"{tr_ratio*100:.0f}%" if tr_ratio is not None else "N/A"
        lines.append(f"{i:<4} {_fmt_usd(t2):>9} {bp:>5} {tb:>5} {_fmt_usd(mf_map.get(i)):>11}")
    lines.append("```")
    sm = d["smart_money"]
    if sm["smart_traders_no"] is not None:
        rnk = f" (#{sm['rank_in_sm_top100']}/100)" if sm["rank_in_sm_top100"] else ""
        lines.append(f"🌟 *Smart Money*: {int(sm['smart_traders_no']):,} wallets{rnk}")
    lines.append("")
    sc = d["scores"]
    lines.append(
        f"*Scores* — SEC {sc['sec']:.1f} · SMKT {sc['smkt']:.1f} · ACT {sc['act']:.1f} · VOL {sc['vol']:.1f}\n"
        f"⭐ *Final: {sc['final']:.1f}/10 → {sc['verdict']}*"
    )
    lines.append("")
    footer_parts = [f"⚡CU {d['cu_used_total']}"]
    if d["invariants"]["count"]:
        footer_parts.append(f"⚠ {d['invariants']['count']} gaps")
    else:
        footer_parts.append("✅ invariants OK")
    footer_parts.append(f"⏱{d['latency_ms']}ms · 📸{d['snapshot_time']}")
    lines.append(" · ".join(footer_parts))
    print("\n".join(lines))


def _fmt_usd(v):
    if v is None: return "N/A"
    sign = "-" if float(v) < 0 else ""
    vv = abs(float(v))
    if vv >= 1_000_000_000: return f"{sign}${vv/1_000_000_000:.2f}B"
    if vv >= 1_000_000: return f"{sign}${vv/1_000_000:.2f}M"
    if vv >= 1_000: return f"{sign}${vv/1_000:.2f}K"
    if vv < 0.01 and vv > 0: return f"{sign}${vv:.6f}"
    return f"{sign}${vv:,.2f}"

def _fmt_pct(v):
    if v is None: return "N/A"
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}{float(v):.1f}%"

def _print_dd_scorecard(d: dict, args):
    _print_dd_plain(d, args)


def _tier_from_rugrisk(risk_score_100: float, honeypot=None, mint_enabled=None) -> str:
    # RugCheck-tier mapping: SAFE / LOW / CAUTION / ELEVATED / HIGH / VERY HIGH / DANGER
    if honeypot is True or mint_enabled is True:
        return "DANGER"
    if risk_score_100 >= 88: return "DANGER"
    if risk_score_100 >= 76: return "VERY HIGH"
    if risk_score_100 >= 64: return "HIGH"
    if risk_score_100 >= 52: return "ELEVATED"
    if risk_score_100 >= 38: return "CAUTION"
    if risk_score_100 >= 22: return "LOW"
    return "SAFE"


def _print_rugcheck(d: dict, args):
    chain = d.get("chain", args.chain).upper()
    sym = d.get("symbol") or "?"
    name = d.get("name") or ""
    prc = d.get("price_usd")
    mc = d.get("marketcap_usd")
    fdv = d.get("fdv_usd")
    liq = d.get("liquidity_usd")
    hcnt = d.get("holder_count")
    addr = d.get("address")
    sec = d.get("security") or {}
    scores = d.get("scores") or {}
    rug = d.get("rugcheck") or {}
    # Prefer holder-profile native total (60k level, returned per-call by `/token/v1/holder-profile`
    # data.holder) over overview-aggregated count when available.
    hcnt_native = (rug or {}).get("total_holder_count_native")
    if isinstance(hcnt_native,(int,float)) and hcnt_native > 0:
        hcnt = int(hcnt_native)

    # ===== 7 RISK CARDS (same style rugcheck.xyz "Overview 7 risks" panel) =====
    rc_risk_rows: list[dict] = []

    def add_card(label: str, severity: str, subline: str, *extra_flag_names):
        # severity = safe / low / caution / warn / high / danger
        rc_risk_rows.append({"label": label, "severity": severity, "subline": subline,
                             "flags": list(extra_flag_names)})

    # CARD 1: LP Unlocked % (biggest rug pull vector)
    lp_unl = rug.get("lp_unlocked_pct")
    lp_locked_flag = sec.get("lp_locked")
    if isinstance(lp_unl, (int, float)):
        sev = "danger" if lp_unl >= 90 else ("high" if lp_unl >= 60 else ("warn" if lp_unl >= 40 else ("caution" if lp_unl >= 15 else "safe")))
        add_card(f"LP Unlocked {lp_unl:.1f}%", sev,
                 f"Creator/Pool retains {lp_unl:.1f}% liquidity NOT time-locked",
                 "RUG:PULL_RISK" if lp_unl >= 90 else "")
    elif lp_locked_flag is False:
        add_card("Liquidity Not Locked (NO proof)", "danger",
                 "No lpLocked=true proof from security API; no vesting verified",
                 "RUG:HIGH")
    elif lp_locked_flag is True:
        add_card("LP Locked (proof verified)", "safe",
                 "lpLocked=true, time-locked vesting confirmed by Birdeye")

    # CARD 2: Top 10 holders concentration (holders section main)
    t10 = rug.get("holders_top10_pct") if rug.get("holders_top10_pct") is not None else sec.get("top10_holder_pct")
    if isinstance(t10, (int, float)):
        sev = "danger" if t10 >= 80 else ("high" if t10 >= 60 else ("warn" if t10 >= 40 else ("caution" if t10 >= 20 else "safe")))
        add_card(f"Top 10 Holders {t10:.1f}% Ownership", sev,
                 f"Top10 wallets hold {t10:.1f}% of supply — {f'EXTREME concentration' if t10>=60 else ('bulk held by insiders' if t10>=40 else 'spread ok')}",
                 "HOLDER:HI" if t10 >= 60 else "")

    # CARD 3: Low Liquidity (real liq$ vs MC)
    if isinstance(liq, (int, float)):
        sev = "danger" if liq < 500 else ("warn" if liq < 5000 else ("caution" if liq < 25000 else "safe"))
        extra = ""
        if isinstance(mc,(int,float)) and mc > 0:
            ratio = liq / mc * 100.0
            extra = f"  LIQ/MC = {ratio:.2f}% ({'TERRIBLE' if ratio<0.5 else ('weak' if ratio<2 else 'healthy')})"
        add_card(f"Liquidity {_fmt_usd(liq)}", sev,
                 f"Real liquidity available. Traders can exit?{extra}",
                 "LIQ:TOO_LOW" if liq < 1000 else "")

    # CARD 4: High market cap / holder (per holder avg MC too high = "paper rich but nobody owns")
    if isinstance(mc, (int, float)) and isinstance(hcnt, (int, float)) and hcnt > 0:
        per = mc / hcnt
        sev = "warn" if per > 100_000 else ("caution" if per > 25_000 else "safe")
        add_card(f"MC/holder avg {_fmt_usd(per)}", sev,
                 f"${_fmt_usd(mc)} MC across {int(hcnt):,} wallets = avg {_fmt_usd(per)} per holder. {'Unnaturally high per-wallet implied value' if per>100000 else ''}")

    # CARD 5: Few LP Providers (only 1-2 wallets own whole AMM pool)
    lpc = rug.get("lp_providers_count")
    if isinstance(lpc,(int,float)):
        sev = "danger" if lpc <= 2 else ("warn" if lpc <= 5 else ("caution" if lpc <= 10 else "safe"))
        add_card(f"LP Providers count = {int(lpc)}", sev,
                 f"Number of unique wallets providing liquidity. {'Only dev owns pool' if lpc<=2 else ('Few whales control exits' if lpc<=5 else '')}",
                 "LP:CENTRALIZED" if lpc <= 2 else "")

    # CARD 6: Fee config enabled (transfer / anti-dump tax mintable fee)
    fee = rug.get("fee_enabled")
    if fee is True:
        add_card("Fee Config ENABLED", "warn",
                 "Transfer/tax fee logic active on contract. Potential anti-dump or hidden rake.",
                 "TAX:FEE")
    elif fee is False:
        add_card("No transfer tax/fee", "safe",
                 "feeEnabled=false. Straight SPL/EVM transfer, no on-chain transfer rake.")

    # CARD 7: Mutable metadata / mint authority (mintable = dev can inflate supply infinite rug)
    mm = rug.get("metadata_mutable")
    mint = rug.get("mint_authority_enabled")
    if mint is True:
        add_card("Mint / Freeze Authority PRESENT", "danger",
                 "Mint authority NOT renounced. Dev can print infinite tokens → dilution RUG.",
                 "MINTABLE:RUG")
    else:
        sev_mm = "warn" if mm is True else ("safe" if mm is False else "caution")
        lbl = (f"Metadata {'MUTABLE' if mm else 'Immutable'}" if mm is not None else "Metadata status UNKNOWN")
        add_card(lbl, sev_mm,
                 "Mutable metadata = token name/symbol/logo can be swapped anytime post-launch (rug scam bait-and-switch common)")

    cards_count = len(rc_risk_rows)

    # ===== RISK SCORE 0-100 AGGREGATE + TIER =====
    # weight 7 cards: danger=+20 each, high=+15, warn=+10, caution=+5, safe=+0
    sev_w = {"danger":25, "high":18, "warn":11, "caution":5, "low":2, "safe":0}
    risk_total = 0
    for c in rc_risk_rows:
        risk_total += sev_w.get(c["severity"].lower(), 0)
    # extra additive penalties (raw pillars not yet in 7 cards above):
    honeypot = sec.get("honeypot")
    mint_flag = rug.get("mint_authority_enabled")
    if honeypot is True: risk_total += 35
    if mint_flag is True: risk_total += 35
    devp = sec.get("dev_holding_pct")
    if isinstance(devp,(int,float)) and devp >= 20: risk_total += 15
    # drawdown penalty (if liquidity drained 24h)
    ldd = rug.get("liq_drawdown_window_pct")
    if isinstance(ldd,(int,float)):
        if ldd >= 80: risk_total += 20
        elif ldd >= 50: risk_total += 12
        elif ldd >= 25: risk_total += 6
    risk_100 = int(max(0.0, min(100.0, float(risk_total))))
    tier = _tier_from_rugrisk(risk_100, honeypot=honeypot, mint_enabled=mint_flag)

    # ===== HEADER same rugcheck.xyz hero: token, price, copy addr, unverified label, Tier badge =====
    tier_color = {"SAFE": "\033[92m", "LOW": "\033[92m", "CAUTION": "\033[93m", "ELEVATED": "\033[93m",
                  "HIGH": "\033[91m", "VERY HIGH": "\033[91m", "DANGER": "\033[41m\033[97m"}.get(tier, "")
    tier_reset = "\033[0m" if tier_color else ""

    W = 88
    print("╔" + "═"*(W-2) + "╗")
    head = f"🔎  RUGCHECK REPORT  ·  {chain}  {sym}"
    head += f"  ({name[:42]})" if name else ""
    print("║ " + head + " "*(W-4-len(head)) + " ║")
    price_s = f"${prc:,.6f}" if isinstance(prc,(int,float)) and prc<1 else (f"${prc:,.2f}" if isinstance(prc,(int,float)) else "Price N/A")
    mc_s = f"MC {_fmt_usd(mc)} · FDV {_fmt_usd(fdv)} · LIQ {_fmt_usd(liq)}"
    tier_line = f"[ {tier_color}{tier}{tier_reset} ]  RISK {risk_100}/100"
    addr_s = f"Addr: {addr}"
    sub1 = f"{price_s:<28}{mc_s:<45}{tier_line}"
    print("║ " + sub1 + " "*(W-4-min(len(sub1), W-4)) + " ║")
    print("║ " + addr_s + " "*(W-4-min(len(addr_s), W-4)) + " ║")
    hc_s = f"Holders: {int(hcnt):,}" if isinstance(hcnt,(int,float)) else "Holders: N/A"
    extra = f"Dev {devp:.1f}%  ·  T10 {t10:.1f}%" if isinstance(devp,(int,float)) and isinstance(t10,(int,float)) else (f"Dev {devp:.1f}%" if isinstance(devp,(int,float)) else (f"T10 {t10:.1f}%" if isinstance(t10,(int,float)) else ""))
    security_flags = []
    if honeypot is True: security_flags.append("🔴 HONEYPOT")
    if mint_flag is True: security_flags.append("🔴 MINTABLE")
    if sec.get("lp_locked") is False: security_flags.append("⚠ LP NOT LOCKED")
    if extra: security_flags.append(extra)
    sub2 = f"{hc_s:<24}" + "  ".join(security_flags)
    print("║ " + sub2 + " "*(W-4-min(len(sub2), W-4)) + " ║")
    print("╠" + "═"*(W-2) + "╣")

    # ===== TAB BAR (Overview / Markets / Insiders / Holders / Lockers&LP) with counts same rugcheck.xyz =====
    risk_count_badges = sum(1 for c in rc_risk_rows if c["severity"].lower() in ("danger","high","warn","caution"))
    liq_tab = f"Markets {_fmt_usd(liq)}" if liq is not None else "Markets"
    ins_pct_total = 0
    ins_network_n = 0
    for k, pv in (rug.get("insider_cohorts") or {}).items():
        if isinstance(pv,(int,float)) and pv > 0:
            ins_network_n += 1
            ins_pct_total += pv
    ins_tab = f"Insiders {ins_network_n} cohort" if ins_network_n else "Insiders 0"
    h_tab = f"Holders {int(hcnt):,}" if isinstance(hcnt,(int,float)) else "Holders"
    lk_tab = "Lockers & LP " + ("No LP locked" if sec.get("lp_locked") is False else ("LP locked" if sec.get("lp_locked") else "? status"))
    tabs = [f"[Overview {risk_count_badges} risks]", f"[{liq_tab}]", f"[{ins_tab}]", f"[{h_tab}]", f"[{lk_tab}]"]
    print("║ " + "  ".join(tabs) + " "*(W-4-min(len("  ".join(tabs)), W-4)) + " ║")
    print("╠" + "═"*(W-2) + "╣")

    # ===== RISK LIST (bulleted exactly rugcheck.xyz Risks tab list) =====
    print("║  ⚠ RISKS  " + " "*(W-14) + " ║")
    printed_risks = 0
    for c in rc_risk_rows:
        if c["severity"].lower() in ("safe","low"):
            continue
        bullet_s = {
            "danger": "🔴·",
            "high":   "🟥·",
            "warn":   "🟧·",
            "caution":"🟨·",
        }.get(c["severity"].lower(), "·")
        l = f"{bullet_s} {c['label']}"
        sl = c["subline"] or ""
        if sl: l += f"  — {sl}"
        flag_s = " ".join([f for f in (c.get("flags") or []) if f])
        if flag_s: l += f"   [{flag_s}]"
        print("║ " + l[:W-4] + " "*(max(0, W-4-len(l[:W-4]))) + " ║")
        printed_risks += 1
    if printed_risks == 0:
        okmsg = "✅  No severe risk cards flagged (LP locked, holders spread, liq healthy, fees off)"
        print("║ " + okmsg + " "*(W-4-min(W-4,len(okmsg))) + " ║")
    print("╠" + "═"*(W-2) + "╣")

    # ===== MARKETS & LIQUIDITY PANEL (min/max + drawdown 24h — RC-1 call result) =====
    lw = rug.get("liq_window") or "24h"
    cur = rug.get("liq_current_usd") if isinstance(rug.get("liq_current_usd"),(int,float)) else liq
    mn = rug.get("liq_min_window_usd")
    mx = rug.get("liq_max_window_usd")
    dd = rug.get("liq_drawdown_window_pct")
    print("║  💧 LIQUIDITY " + ("WINDOW "+lw).ljust(12) + " (×1 API call 20CU)" + " "*(W-50) + " ║")
    def row_liq(a, b="", c=None):
        mid = f"{a:<22}{str(b):<22}"
        if c is not None: mid += f"{str(c):<22}"
        return "║    " + mid + " "*(W-8-min(W-8,len(mid))) + " ║"
    print(row_liq(f"CURRENT {_fmt_usd(cur)}", f"{lw} MIN {_fmt_usd(mn) if mn else 'N/A'}", f"{lw} MAX {_fmt_usd(mx) if mx else 'N/A'}"))
    if isinstance(dd,(int,float)):
        severity_dd = "🔴 -" if dd >= 60 else ("🟧 -" if dd >= 30 else ("🟨 -" if dd >= 12 else "🟩 +"))
        dd_msg = f"DRAWDOWN from PEAK {lw}: {severity_dd}{abs(dd):.1f}%  →  {'NEAR FULL LIQ DRAIN' if dd>=80 else ('HALF liquidity removed' if dd>=50 else ('Moderate outflow' if dd>=20 else 'range-bound ok'))}"
        print(row_liq(dd_msg[:60]))
    print("╠" + "═"*(W-2) + "╣")

    # ===== INSIDERS cohort breakdown insider/dev/sniper/bundle/bot (RC-3 adv sec call) =====
    insiders = rug.get("cohort_breakdown") or []
    print("║  👥 INSIDERS / COHORTS  (advanced security ×1 call 21CU)" + " "*(max(0,W-70)) + " ║")
    if not insiders:
        msg = "(no cohort breakdown returned by API → fields not present in response)"
        print("║    " + msg + " "*(W-8-min(W-8,len(msg))) + " ║")
    else:
        # sort high pct first
        insiders_s = sorted(insiders, key=lambda x: -(x.get("pct") or 0))
        # Summary pill row (name pct% count=N) — same as before but with count
        pill_parts = []
        for cb in insiders_s:
            pct = cb.get("pct")
            nm = cb.get("name") or ""
            t = cb.get("tier") or ""
            hc = cb.get("holder_count")
            if not isinstance(pct,(int,float)) or pct <= 0.0: continue
            symbol = {"high":"🔴","warn":"🟧","caution":"🟨","low":"🟩"}.get(t,"·")
            count_str = f" N={int(hc):,}" if isinstance(hc,(int,float)) else ""
            pill_parts.append(f"{symbol} {nm} {pct:.1f}%{count_str}")
        joined = "   ".join(pill_parts)
        if not joined:
            joined = "(zero-percent cohorts returned)"
        print("║    " + joined[:W-8] + " "*(W-8-min(W-8,len(joined[:W-8]))) + " ║")
        # ---- DETAILED table: name | count | pct% | buy_vol_usd | sell_vol_usd | avg_buy_price | pnl ----
        has_detail = any(
            (isinstance(cb.get("holder_count"),(int,float))) or
            (isinstance(cb.get("buy_volume_usd"),(int,float))) or
            (isinstance(cb.get("pnl"),(int,float))) or
            (isinstance(cb.get("avg_buy_price"),(int,float)))
            for cb in insiders_s
        )
        if has_detail:
            c_name=12; c_count=10; c_pct=9; c_buy=14; c_sell=14; c_avg=14; c_pnl=14
            det_head = ("COHORT".ljust(c_name)+"N".rjust(c_count)+"%".rjust(c_pct)+
                        "BUY $".rjust(c_buy)+"SELL $".rjust(c_sell)+
                        "AVG BUY".rjust(c_avg)+"PNL $".rjust(c_pnl))
            print("║    " + det_head + " "*(W-8-min(W-8,len(det_head))) + " ║")
            print("║    " + "─"*(min(W-8,len(det_head))) + " "*(W-8-min(W-8,len(det_head))) + " ║")
            for cb in insiders_s:
                nm = (cb.get("name") or "-")[:c_name-1].ljust(c_name)
                hc = cb.get("holder_count")
                hc_s = (f"{int(hc):,}" if isinstance(hc,(int,float)) else "-").rjust(c_count)
                pct = cb.get("pct")
                pct_s = (f"{pct:.2f}%" if isinstance(pct,(int,float)) else "-").rjust(c_pct)
                bv = cb.get("buy_volume_usd")
                sv = cb.get("sell_volume_usd")
                ap = cb.get("avg_buy_price")
                pnl = cb.get("pnl")
                bv_s = (_fmt_usd(bv,1) if isinstance(bv,(int,float)) else "-").rjust(c_buy)
                sv_s = (_fmt_usd(sv,1) if isinstance(sv,(int,float)) else "-").rjust(c_sell)
                ap_s = (_fmt_usd(ap,2) if isinstance(ap,(int,float)) else "-").rjust(c_avg)
                pnl_s = (_fmt_usd(pnl,1) if isinstance(pnl,(int,float)) else "-").rjust(c_pnl)
                line = f"{nm}{hc_s}{pct_s}{bv_s}{sv_s}{ap_s}{pnl_s}"
                print("║    " + line[:W-8] + " "*(W-8-min(W-8,len(line[:W-8]))) + " ║")
        print("╠" + "═"*(W-2) + "╣")

    # ===== HOLDERS TAB - TOP20 HOLDER TABLE exactly rugcheck.xyz (RC-2 holder_list call) =====
    holders_show = bool(getattr(args, "rug_show_holders", True))
    holders_top_n = int(getattr(args, "rug_holders_top_n", 20) or 20)
    holders_raw = rug.get("holders_raw") or []
    print(f"║  🧾 HOLDERS  (Top {min(len(holders_raw),holders_top_n)} of {hcnt if isinstance(hcnt,(int,float)) else '?'})" + (" ×1 API call 30CU" if holders_raw else "") + " "*(W-60) + " ║")
    t10_accurate = rug.get("holders_top10_pct") if rug.get("holders_top10_pct") is not None else sec.get("top10_holder_pct")
    if isinstance(t10_accurate,(int,float)):
        tt = f"   TOP 10 HOLDER OWNERSHIP = {t10_accurate:.1f}%  {'(⚠ extremely concentrated)' if t10_accurate>=60 else ''}"
        print("║ " + tt + " "*(W-4-min(W-4,len(tt))) + " ║")
    if not holders_show or not holders_raw:
        if not holders_show:
            m = "(user --no-rug-show-holders, skip table)"
        else:
            m = "(holder list unavailable — API returned empty)"
        print("║    " + m + " "*(W-8-min(W-8,len(m))) + " ║")
    else:
        # TABLE header
        col_rank = 4
        col_label = 28
        col_short = 18
        col_pct = 10
        col_usd = 16
        col_amount = 18
        header = ("#".ljust(col_rank) + "LABEL".ljust(col_label) + "OWNER".ljust(col_short) +
                  "%".rjust(col_pct) + "VALUE $".rjust(col_usd) + "AMOUNT".rjust(col_amount))
        print("║    " + header + " "*(W-8-min(W-8,len(header))) + " ║")
        print("║    " + "─"*(min(W-8,len(header))) + " "*(W-8-min(W-8,len(header))) + " ║")
        rows_show = holders_raw[: holders_top_n]
        for r in rows_show:
            rank = str(r.get("rank") or "").ljust(col_rank)
            lab = ((r.get("label") or r.get("tags") and ",".join(r["tags"][:2]) or ""))
            if isinstance(lab, list): lab = ",".join(lab[:2])
            lab = (lab or "")[:col_label-1].ljust(col_label)
            own = (r.get("owner_short") or (str(r.get("owner") or "")[:6] + "…" + str(r.get("owner") or "")[-4:]) if len(str(r.get("owner") or "")) > 10 else str(r.get("owner") or ""))
            own = own[:col_short-1].ljust(col_short)
            pv = r.get("pct")
            pc = (f"{pv:.2f}%" if isinstance(pv,(int,float)) else "N/A").rjust(col_pct)
            uv = r.get("usd_value")
            usv = (_fmt_usd(uv) if isinstance(uv,(int,float)) else "-").rjust(col_usd)
            amr = (str(r.get("amount_raw") or "") or "-")[:col_amount-1].rjust(col_amount)
            body = f"{rank}{lab}{own}{pc}{usv}{amr}"
            print("║    " + body + " "*(W-8-min(W-8,len(body))) + " ║")
        if len(holders_raw) > holders_top_n:
            nmore = f"(…+{len(holders_raw)-holders_top_n} more holders — --rug-holders-top-n 50 to extend)"
            print("║    " + nmore + " "*(W-8-min(W-8,len(nmore))) + " ║")
    print("╠" + "═"*(W-2) + "╣")

    # ===== LOCKERS & LP (final tab recap) =====
    print("║  🔒 LOCKERS & LP   " + " "*(W-30) + " ║")
    ll = [
        ("LP Lock Verified", "✅" if sec.get("lp_locked") else ("❌ NO proof" if sec.get("lp_locked") is False else "? unknown")),
        ("LP Unlocked %", f"{lp_unl:.1f}%" if isinstance(lp_unl,(int,float)) else ("0% (all locked?)" if sec.get("lp_locked") is True else "N/A")),
        ("LP Provider wallets", str(int(lpc)) if isinstance(lpc,(int,float)) else "N/A"),
        ("LP 24h Drain", f"-{ldd:.1f}%" if isinstance(ldd,(int,float)) and ldd>=0 else ("stable <1%" if mn and mx and isinstance(mn,(int,float)) and isinstance(mx,(int,float)) and (max(mn,mx)-min(mn,mx))/(max(mn,mx,0.0001))<0.02 else "N/A")),
        ("Fee Configured", "YES" if fee is True else ("NO" if fee is False else "N/A")),
        ("Metadata Mutable", "YES" if mm is True else ("NO" if mm is False else "N/A")),
        ("Mint / Freeze Auth", "⚠ PRESENT" if mint_flag is True else ("RENOUNCED" if mint_flag is False else "N/A")),
    ]
    for lbl, val in ll:
        line = f"   {lbl:<28} {val}"
        print("║ " + line + " "*(W-4-min(W-4,len(line))) + " ║")
    print("╠" + "═"*(W-2) + "╣")

    # ===== FOOTER: SCORECARD DD SEC pillars + FINAL (user spec same DD score) =====
    sc = d.get("scores") or {}
    secS = sc.get("sec"); smS = sc.get("smkt"); aS = sc.get("act"); vS = sc.get("vol"); fS = sc.get("final"); vd = sc.get("verdict")
    score_line = (f"DD SEC·{secS:.1f}/10   SMKT·{smS:.1f}/10   ACT·{aS:.1f}/10   VOL·{vS:.1f}/10   →  FINAL {fS:.1f}/10  ({vd})"
                  if all(isinstance(x,(int,float)) for x in [secS, smS, aS, vS, fS]) else f"DD FINAL={fS} ({vd})")
    print("║ " + score_line[:W-4] + " "*(W-4-min(W-4,len(score_line[:W-4]))) + " ║")
    footer = f"⚡CU {d.get('cu_used_total')}  |  {d.get('cu_breakdown')[:W-40]}   ⏱{d.get('latency_ms')}ms   📸{d.get('snapshot_time')[:19]}"
    print("║ " + footer[:W-4] + " "*(W-4-min(W-4,len(footer[:W-4]))) + " ║")
    inv_gaps = (d.get("invariants") or {}).get("gaps") or []
    rug_gaps = rug.get("gaps") or []
    all_gaps = inv_gaps + rug_gaps
    if all_gaps:
        gap_msg = f"⚠ {len(all_gaps)} invariant/data gaps: " + " · ".join([str(g) for g in all_gaps[:5]])
        if len(all_gaps) > 5: gap_msg += f" · …+{len(all_gaps)-5} more"
        print("║ " + gap_msg[:W-4] + " "*(W-4-min(W-4,len(gap_msg[:W-4]))) + " ║")
    print("╚" + "═"*(W-2) + "╝")


def cmd_dd(args):
    cdir = _cache_dir(getattr(args, "cache_dir", None))
    _prune_old_cache(cdir, max_age_hours=24)
    nocache: bool = bool(getattr(args, "nocache", False))
    from_cache: str | None = (None if nocache else (getattr(args, "from_cache", None) or None))
    write_cache: bool = bool(getattr(args, "write_cache", True))
    ident_prefix = f"dd_{args.chain}-{args.address}"
    if nocache:
        removed = _delete_cache_prefix(cdir, ident_prefix)
        if removed:
            print(f"[nocache] removed {removed} stale dd cache file(s) prefix={ident_prefix!r}", file=sys.stderr)
    if from_cache:
        cached = _read_cache(cdir, from_cache)
        if not cached or cached.get("kind") not in ("token-dd", "rugcheck-audit"):
            print(f"[E] Cache run_id not found or invalid: {from_cache}")
            return 3
        _render_dd_from_cache(cached, args.format, from_cache)
        return 0
    key = _load_key()
    if not key:
        print("[E] No BIRDEYE_API_KEY found.")
        return 1
    rug_enable = (args.format == "rugcheck")
    try:
        d = _fetch_token_dd(key, args.chain, args.address, enable_rugcheck_extra=rug_enable, args_ref=args)
    except RuntimeError as e:
        print(str(e))
        return 2
    if write_cache:
        rid = _safe_run_id("dd", f"{args.chain}-{args.address}", tstamp=int(time.time()))
        payload = _serialize_dd_payload(d, args)
        fp = _write_cache(cdir, rid, payload)
        print(f"#RUN_ID {rid}\t{fp.name}\tcu={payload['cu_used_total']}")
    else:
        rid = None
    if args.format == "raw-json" or args.format == "render":
        payload = _serialize_dd_payload(d, args)
        out = {"runId": rid, "cached": False, "cu_used_total": payload["cu_used_total"], "payload": payload}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if args.format == "rugcheck":
        _print_rugcheck(d, args)
    elif args.format == "scorecard":
        _print_dd_scorecard(d, args)
    elif args.format == "telegram":
        _print_dd_telegram(d, args)
    else:
        _print_dd_plain(d, args)
    return 0


# ============================================================
# Skill #17b — RugCheck Audit standalone (reuses engine force enable_rugcheck_extra)
# ============================================================

def cmd_rugcheck_audit(args):
    cdir = _cache_dir(getattr(args, "cache_dir", None))
    _prune_old_cache(cdir, max_age_hours=24)
    nocache: bool = bool(getattr(args, "nocache", False))
    from_cache: str | None = (None if nocache else (getattr(args, "from_cache", None) or None))
    write_cache: bool = bool(getattr(args, "write_cache", True))
    ident_prefix = f"rca_{args.chain}-{args.address}"
    if nocache:
        removed = _delete_cache_prefix(cdir, ident_prefix)
        if removed:
            print(f"[nocache] removed {removed} stale rca cache file(s) prefix={ident_prefix!r}", file=sys.stderr)
    if from_cache:
        cached = _read_cache(cdir, from_cache)
        if not cached or cached.get("kind") not in ("rugcheck-audit", "token-dd"):
            print(f"[E] Cache run_id not found or invalid: {from_cache}")
            return 3
        _render_dd_from_cache(cached, args.format, from_cache)
        return 0
    key = _load_key()
    if not key:
        print("[E] No BIRDEYE_API_KEY found.")
        return 1
    try:
        d = _fetch_token_dd(key, args.chain, args.address, enable_rugcheck_extra=True, args_ref=args)
    except RuntimeError as e:
        print(str(e))
        return 2
    if write_cache:
        rid = _safe_run_id("rca", f"{args.chain}-{args.address}", tstamp=int(time.time()))
        payload = _serialize_dd_payload(d, args)
        payload["kind"] = "rugcheck-audit"
        fp = _write_cache(cdir, rid, payload)
        print(f"#RUN_ID {rid}\t{fp.name}\tcu={payload['cu_used_total']}")
    else:
        rid = None
    if args.format == "raw-json" or args.format == "render":
        payload = _serialize_dd_payload(d, args)
        payload["kind"] = "rugcheck-audit"
        out = {"runId": rid, "cached": False, "cu_used_total": payload["cu_used_total"], "payload": payload}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if args.format == "scorecard":
        _print_dd_scorecard(d, args)
    elif args.format == "telegram":
        _print_dd_telegram(d, args)
    else:
        _print_rugcheck(d, args)
    return 0


# ============================================================
# Parser
# ============================================================

def build_parser():
    p = argparse.ArgumentParser(prog="birdeye_cli", description=__doc__)
    p.add_argument("--cache-dir", default=None, help="Override cache dir (default ~/.cache/birdeye-skills-runs or $BIRDEYE_CACHE_DIR)")
    p.add_argument("--from-cache", dest="from_cache", default=None, help="Re-render a previous run without API calls, using this run_id")
    p.add_argument("--write-cache", action="store_true", dest="write_cache", default=True, help="Always persist result to cache (default ON). Pass --no-write-cache to skip.")
    p.add_argument("--no-write-cache", action="store_false", dest="write_cache", help="Do not persist cache for this run")
    p.add_argument("--nocache", "--no-cache", "--force-fetch", "--force-fresh", action="store_true", dest="nocache", default=False,
                   help="Force FRESH Birdeye API call = DELETE all existing cache files for this run_id prefix + skip --from-cache replay + disable cache write this run. Combines --no-write-cache + delete-prefix + ignore-from-cache.")

    sub = p.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("trending-list", help="Skill #1 — Top N hot tokens. Default source=v3-list (50 CU) for reliable data.")
    pt.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    pt.add_argument("--interval", choices=INTERVALS, default="1h", help="Time window for volume/sort.")
    pt.add_argument("--sort-by",
                    choices=["volumeUSD", "liquidity", "rank", "market_cap", "trade_count", "holder"],
                    default="volumeUSD",
                    help="Sort enum. trade_count and holder only work with --source v3-list.")
    pt.add_argument("--limit", type=int, default=20, choices=range(1, 101), metavar="1-100")
    pt.add_argument("--offset", type=int, default=0)
    pt.add_argument("--source", choices=["v3-list", "trending"], default="v3-list",
                    help="v3-list = /defi/v3/token/list 50 CU (default, real data with trades/holders). "
                         "trending = /defi/token_trending 30 CU (native Birdeye trending; may return $0 volume on Solana).")
    pt.add_argument("--platform", default=None,
                    help="v3-list only: filter platform e.g. 'pump.fun' | 'moonshot' | 'raydium' | 'meteora dbc' | 'mayhem'")
    pt.add_argument("--format", choices=["plain", "telegram", "raw-json"], default="plain")
    pt.set_defaults(func=cmd_trending)

    pd = sub.add_parser("token-dd", help='Skill #3 — "Should I buy this token?" (typ. 71 CU)')
    pd.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    pd.add_argument("--address", required=True, help="Token contract address")
    pd.add_argument("--format", choices=["plain", "scorecard", "rugcheck", "telegram", "raw-json", "render"], default="plain")
    pd.add_argument("--include", dest="include", default=None,
                    help="Comma flags: `list` (+30CU top20 holders), `advanced_security` (+21CU insider/dev/sniper/bundle tags), `risk_history` (+30CU 30d MC snapshots). `rugcheck` format auto-picks best CU-min set")
    pd.add_argument("--rug-liq-window", dest="rug_liq_window", default="24h", choices=["1h","4h","8h","24h"],
                    help="RugCheck format: Liquidity min/max/DD historical window (1 call = 20CU). Default 24h.")
    pd.add_argument("--rug-show-holders", dest="rug_show_holders", action="store_true", default=True,
                    help="RugCheck format: Show holder list table in output (YES default). User --no-rug-show-holders = off.")
    pd.add_argument("--no-rug-show-holders", dest="rug_show_holders", action="store_false",
                    help="Disable holder list table (top10 %% still computed always).")
    pd.add_argument("--rug-holders-top-n", dest="rug_holders_top_n", type=int, default=20,
                    help="RugCheck: How many holders rows render in table (default rugcheck.xyz = Top 20).")
    pd.add_argument("--list-top-n", dest="list_top_n", type=int, default=20)
    pd.add_argument("--history-points", dest="history_points", type=int, default=30)
    pd.set_defaults(func=cmd_dd)

    ph = sub.add_parser("history-list", help="List recent cached runs (default last 25)")
    ph.add_argument("--limit", type=int, default=25)
    ph.add_argument("--format", choices=["plain", "raw-json"], default="plain")
    ph.set_defaults(func=cmd_history_list)

    pr = sub.add_parser("history-render", help="Render a cached run_id with any format (0 API call)")
    pr.add_argument("--run-id", required=True)
    pr.add_argument("--format", choices=["plain", "telegram", "raw-json", "render"], default="plain",
                    help="'render' returns raw-json payload the UI renderer (DDRender/TrendRender) uses.")
    pr.set_defaults(func=cmd_history_render)

    psm = sub.add_parser("smart-wallets", help="Skill #9 — Top Smart Money Wallets ranked by Net Worth, Win Rate, PnL. FAST=30CU / STD=150CU / DEEP=500CU.")
    psm.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    psm.add_argument("--depth", choices=["fast", "standard", "deep"], default="fast",
                     help="FAST=1 token → 30 CU; STD=13 tokens →150 CU; DEEP=48 tokens →500 CU.")
    psm.add_argument("--min-trades", type=int, default=15, help="R1 · min trades 30d (5-50)")
    psm.add_argument("--min-unique", type=int, default=8, help="R2 · min unique tokens traded 30d (3-30)")
    psm.add_argument("--enforce-tag", action="store_true", default=True, help="R3 · require SM tag OR win rate ≥ 50%%")
    psm.add_argument("--no-enforce-tag", dest="enforce_tag", action="store_false", help="Disable R3 SM-tag/winrate filter")
    psm.add_argument("--blacklist", default=None, help="R4 · comma-separated wallet addresses to drop")
    psm.add_argument("--winrate", type=int, default=40, help="Weight: Win Rate pts total (0-40)")
    psm.add_argument("--pnl", type=int, default=25, help="Weight: PnL Multiple pts total (0-25)")
    psm.add_argument("--rank", type=int, default=20, help="Weight: SM Global Rank pts total (0-20)")
    psm.add_argument("--dd", type=int, default=15, dest="dd_weight", help="Weight: Unrealized Max DD inv pts (0-15)")
    psm.add_argument("--pass-score", type=int, default=70, dest="pass_score",
                     help="Minimum composite score to PASS (0-100). Default 70.")
    psm.add_argument("--limit", type=int, default=20, help="Final output rows limit PASS wallets (1-100)")
    psm.add_argument("--format", choices=["plain", "telegram", "raw-json", "scorecard"], default="plain")
    psm.set_defaults(func=cmd_smart_wallets)

    # Skill #17b standalone RugCheck Audit — UI side='rca' drillMode='rugcheck-audit'
    prc = sub.add_parser("rugcheck-audit",
                         help="Skill #17b · RugCheck Audit (liq hist + holder list + adv security ONE CALL EACH ×1. "
                              "Typical total 142 CU. Same UI format as rugcheck.xyz website holders tab.")
    prc.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    prc.add_argument("--address", required=True, help="Token contract address")
    prc.add_argument("--rug-liq-window", dest="rug_liq_window", default="24h", choices=["1h","4h","8h","24h"],
                     help="Liquidity min/max/DD historical window (1 call = 20CU). Default 24h.")
    prc.add_argument("--rug-show-holders", dest="rug_show_holders", action="store_true", default=True,
                     help="Show holder list table YES default (1 call = 30CU).")
    prc.add_argument("--no-rug-show-holders", dest="rug_show_holders", action="store_false",
                     help="Hide holder list table (top10 aggregate %% still recalculated accurate).")
    prc.add_argument("--rug-holders-top-n", dest="rug_holders_top_n", type=int, default=20,
                     help="How many holder rows render in table (default rugcheck.xyz = Top 20).")
    prc.add_argument("--format", choices=["plain", "telegram", "raw-json", "scorecard", "render"], default="plain",
                     help="'plain' = same-same rugcheck.xyz layout ascii. render = UI renderer payload.")
    prc.set_defaults(func=cmd_rugcheck_audit)

    pws = sub.add_parser("wallet-score",
                         help="Skill #13 · Wallet Score (4-component: P40 / C25 / Q20 / A15). "
                              "Pipeline worst ~110 CU: PnL Summary 30 → per-token rug%% 10 → FirstTx 40 → Portfolio 30. "
                              "Early fail tx<20 = 30 CU only.")
    pws.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    pws.add_argument("--wallet", required=True, help="Wallet address")
    pws.add_argument("--duration",
                     choices=["all", "90d", "30d", "7d", "24h"],
                     default="30d",
                     help="PnL time window (default 30d).")
    pws.add_argument("--pnl-method", dest="pnl_method",
                     choices=["wac", "net_cash"], default="wac",
                     help="PnL accounting: wac (weighted avg holding cost, default) or net_cash (cashflow diff).")
    pws.add_argument("--skip-rug", dest="skip_rug", action="store_true", default=False,
                     help="Skip per-token rug%% fetch (save ~10 CU). rug_fraction forced 0.0; quality penalized via realization ratio only.")
    pws.add_argument("--skip-portfolio", dest="skip_portfolio", action="store_true", default=False,
                     help="Skip Portfolio V2 (save 30 CU). wallet_info.current_net_worth = from summary current_value or null.")
    pws.add_argument("--skip-first-tx", dest="skip_first_tx", action="store_true", default=False,
                     help="Skip First Tx Funded provenance (save 40 CU when wallet age not needed).")
    pws.add_argument("--include-style", dest="include_style", action="store_true", default=False,
                     help="Also compute Wallet Style (freq×P&L grid) and show a Style Badge. "
                          "Reuses already-fetched pnl/per-token/first-funded data — 0 extra CU (no tx_list → no speed subtitle).")
    pws.add_argument("--include", dest="include", default=None,
                     help="Comma-separated data blocks to return (compact numeric output). "
                          "Blocks: pnl,pnl_90d,pnl_24h,tokens,wallet,portfolio,leaderboard,score. "
                          "Only fetches APIs for included blocks → saves CU. "
                          "If omitted, returns full wallet-score (all blocks).")
    pws.add_argument("--format", choices=["plain", "telegram", "raw-json", "rendered", "compact"], default="rendered",
                     help="plain = ASCII table · telegram = Unicode paste card · raw-json = structured envelope · "
                          "rendered = HTML preHtml Hub inject · compact = numeric-only blocks (use with --include).")
    pws.set_defaults(func=cmd_wallet_score)

    # --- Skill #11 · Wallet Style (trading-style tagger on Birdeye data) ---
    pwst = sub.add_parser("wallet-style",
                          help="Skill #11 · Wallet Style — 20-cell freq×PnL grid + speed subtitle + badges. "
                               "~90 CU (summary 30 + details 30 + tx_list ~30; first-funded cached 0).")
    pwst.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    pwst.add_argument("--wallet", required=True, help="Wallet address")
    pwst.add_argument("--duration", choices=["7d", "30d"], default="30d",
                      help="PnL window used for the freq/P&L axes (default 30d).")
    pwst.add_argument("--pnl-method", dest="pnl_method", choices=["wac", "net_cash"], default="wac")
    pwst.add_argument("--skip-tx-list", dest="skip_tx_list", action="store_true", default=False,
                      help="Skip /v1/wallet/tx_list (save ~30 CU). No speed subtitle / scaling / gas badges.")
    pwst.add_argument("--skip-first-tx", dest="skip_first_tx", action="store_true", default=False,
                      help="Skip first-funded (wallet age). Reuses permanent CSV cache when present.")
    pwst.add_argument("--format", choices=["plain", "telegram", "raw-json", "rendered"], default="rendered")
    pwst.set_defaults(func=cmd_wallet_style)

    # Skill #14 — Wallet Analysis (single-wallet deep-dive: profile/assets/trading/performance/risk by intervals)
    pwa = sub.add_parser("wallet-analysis",
                         help="Skill #14 · Wallet Analysis — single-wallet deep-dive: profile, assets (current + intervals), "
                              "trading & performance by interval, risk metrics. Default intervals: 24h,7d,30d,90d,all.")
    pwa.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    pwa.add_argument("--wallet", required=True, help="Wallet address")
    pwa.add_argument("--pnl-method", dest="pnl_method", choices=["wac", "net_cash"], default="wac")
    pwa.add_argument("--intervals", default="24h,7d,30d,90d,all",
                     help="Comma-separated PnL intervals: 24h,7d,30d,90d,all (default all 5).")
    pwa.add_argument("--skip-tx-list", dest="skip_tx_list", action="store_true", default=False,
                     help="Skip /v1/wallet/tx_list (save ~30 CU). No style / TP-SL inference.")
    pwa.add_argument("--skip-first-tx", dest="skip_first_tx", action="store_true", default=False,
                     help="Skip first-funded (wallet age). Reuses permanent CSV cache when present.")
    pwa.add_argument("--skip-portfolio", dest="skip_portfolio", action="store_true", default=False,
                     help="Skip Portfolio V2 net-worth (save 30 CU).")
    pwa.add_argument("--format", choices=["plain", "telegram", "raw-json", "rendered"], default="rendered")
    pwa.set_defaults(func=cmd_wallet_analysis)

    # Skill #9 — Smart Money Profile (single-wallet behavior analysis + copy-trade verdict)
    psmp = sub.add_parser("smart-money-profile",
                          help="Skill #9 · Smart Money Profile — single-wallet behavior analysis: "
                               "performance trend (7d/30d), trading style, TP/SL patterns, "
                               "copy-trade ROI estimate, and a 🟢/🟡/🔴 verdict.")
    psmp.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    psmp.add_argument("--wallet", required=True, help="Wallet address")
    psmp.add_argument("--pnl-method", dest="pnl_method", choices=["wac", "net_cash"], default="wac")
    psmp.add_argument("--skip-tx-list", dest="skip_tx_list", action="store_true", default=False,
                      help="Skip /v1/wallet/tx_list (save ~30 CU). No style/TP-SL inference.")
    psmp.add_argument("--skip-first-tx", dest="skip_first_tx", action="store_true", default=False,
                      help="Skip first-funded (wallet age). Reuses permanent CSV cache when present.")
    psmp.add_argument("--format", choices=["plain", "telegram", "raw-json", "rendered"], default="rendered")
    psmp.set_defaults(func=cmd_smart_money_profile)

    # Skill #9b — Smart Money Leaderboard (multi-wallet comparison)
    psml = sub.add_parser("smart-money-leaderboard",
                          help="Skill #9b · Smart Money Leaderboard — compare up to 10 wallets, "
                               "rank by composite score (winrate 40% + pnl 40% + diversity 10% + recency 10%).")
    psml.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    psml.add_argument("--wallet", action="append", required=True,
                      help="Wallet address (repeat up to 10 times)")
    psml.add_argument("--pnl-method", dest="pnl_method", choices=["wac", "net_cash"], default="wac")
    psml.add_argument("--format", choices=["plain", "telegram", "raw-json", "rendered"], default="rendered")
    psml.set_defaults(func=cmd_smart_money_leaderboard)

    # --- Skill #21 — Kline Pattern (moved from Chain → Chart group) ---
    pkp = sub.add_parser("kline-pattern",
                         help="Skill #21 · Kline Pattern — classify candlestick pattern + 0..100 score. "
                              "1 ohlcv call (CU scales with candle count: 25–100).")
    pkp.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    pkp.add_argument("--address", required=True, help="Token address (contract)")
    pkp.add_argument("--resolution", choices=["1m", "5m", "15m", "30m", "1h", "4h", "1d"], default="15m",
                     help="Candle resolution (default 15m).")
    pkp.add_argument("--window", default="7d",
                     help="Lookback window e.g. 7d, 3d, 1d (default 7d). Must have >= 8 candles.")
    pkp.add_argument("--format", choices=["plain", "telegram", "raw-json", "rendered"], default="rendered")
    pkp.set_defaults(func=cmd_kline_pattern)

    # --- Skill #5 — Contract DD (replaces chart; contract due-diligence) ---
    pcdd = sub.add_parser("contract-dd",
                          help="Skill #5 · Contract DD — composite 0..100 score (safety 45%% + holders 30%% + price 25%%). "
                               "~86 CU (overview 21 + security 30 + holders 30 + kline 25).")
    pcdd.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    pcdd.add_argument("--address", required=True, help="Token address (contract)")
    pcdd.add_argument("--skip-kline", dest="skip_kline", action="store_true", default=False,
                      help="Skip kline price-action pillar (save ~25 CU).")
    pcdd.add_argument("--format", choices=["plain", "telegram", "raw-json", "rendered"], default="rendered")
    pcdd.set_defaults(func=cmd_contract_dd)

    return p


# ============================================================
# Skill #13 — Wallet Score (4-component: P40/C25/Q20/A15)
# Single-wallet adaptation of leaderboard percentile_rank scoring.
# Replaces percentile_rank(df, pct=True) with industry baselines (linear 0..100).
# Hard filters from SKILL.md: tx>=20, vol>=$5k, rug%<=50%.
# ============================================================

# --- Wallet Score constants imported from modules/wallet_data.py ---
_WS_HARD = _wd._WS_HARD
_WS_WEIGHTS = _wd._WS_WEIGHTS
_WS_CONSISTENCY_WEIGHTS = _wd._WS_CONSISTENCY_WEIGHTS
_WS_QUALITY_WEIGHTS = _wd._WS_QUALITY_WEIGHTS
_WS_V3 = _wd._WS_V3
_WS_CACHE_TTL_HOURS = _wd._WS_CACHE_TTL_HOURS
_WS_CSV_HEADER = _wd._WS_CSV_HEADER
_WS_BASELINES = _wd._WS_BASELINES
_WS_FF_CSV_HEADER = _wd._WS_FF_CSV_HEADER


def _ws_clamp(v, lo=0.0, hi=100.0):
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return float(lo)
    except Exception:
        return float(lo)
    return max(float(lo), min(float(hi), fv))


def _ws_to_fraction(series_vals):
    """Normalize percentage column values (0..1 OR 0..100) → strict 0..1 clip."""
    out = []
    numeric = []
    for v in series_vals:
        try:
            fv = float(v)
            if math.isnan(fv) or math.isinf(fv):
                fv = 0.0
        except Exception:
            fv = 0.0
        out.append(fv)
        numeric.append(fv)
    if numeric:
        s = sorted(numeric)
        q95_idx = int(len(s) * 0.95)
        if q95_idx >= len(s):
            q95_idx = len(s) - 1 if s else 0
        q95 = s[q95_idx] if s else 0.0
        if q95 > 1.0:
            out = [x / 100.0 for x in out]
    return [_ws_clamp(x, 0.0, 1.0) for x in out]


def _ws_baseline_score(raw_value, component):
    """Linear 0..100 score from raw value against WS_BASELINES.

    Replaces percentile_rank scoring from leaderboard DB mode
    (unavailable in single-wallet mode).
    """
    cfg = _WS_BASELINES[component]
    if component == "profitability":
        lo = cfg["low_usd"]
        hi = cfg["high_usd"]
    else:
        lo = cfg["low_raw"]
        hi = cfg["high_raw"]
    try:
        rv = float(raw_value)
    except Exception:
        return 0.0
    if hi <= lo:
        return 0.0
    ratio = (rv - lo) / (hi - lo)
    return _ws_clamp(ratio * 100.0, 0.0, 100.0)


def _ws_wallet_csv_path(cdir):
    return _cache_dir(cdir) / "wallet_alpha_cache.csv"


def _ws_ff_csv_path(cdir):
    return _cache_dir(cdir) / "wallet_first_funded_cache.csv"


def _ws_first_funded_cache_get(cdir, wallet, chain_full):
    """Return cached first-funded raw dict for (wallet, chain) or None.

    Data is immutable, so NO TTL — a hit is a permanent save of 40 CU.
    """
    fp = _ws_ff_csv_path(cdir)
    if not fp.exists():
        return None
    wl = str(wallet).lower()
    try:
        with fp.open("r", encoding="utf-8", newline="") as fh:
            rd = csv.DictReader(fh)
            for r in rd:
                if str(r.get("wallet", "")).lower() == wl and str(r.get("chain", "")) == chain_full:
                    raw = r.get("raw_json") or ""
                    if raw:
                        try:
                            return json.loads(raw)
                        except Exception:
                            return None
    except Exception:
        pass
    return None


def _ws_first_funded_cache_set(cdir, wallet, chain_full, first_funded_dict):
    """Persist first-funded raw response for (wallet, chain). Idempotent upsert."""
    if not isinstance(first_funded_dict, dict) or not first_funded_dict:
        return
    fp = _ws_ff_csv_path(cdir)
    wl = str(wallet).lower()
    rows_keep = []
    if fp.exists():
        try:
            with fp.open("r", encoding="utf-8", newline="") as fh:
                rd = csv.DictReader(fh)
                for r in rd:
                    if not (str(r.get("wallet", "")).lower() == wl and str(r.get("chain", "")) == chain_full):
                        rows_keep.append(r)
        except Exception:
            rows_keep = []
    rows_keep.append({
        "wallet": wallet,
        "chain": chain_full,
        "ts_utc": str(time.time()),
        "raw_json": json.dumps(first_funded_dict, ensure_ascii=False),
    })
    try:
        with fp.open("w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=_WS_FF_CSV_HEADER)
            wr.writeheader()
            for r in rows_keep:
                wr.writerow({k: r.get(k, "") for k in _WS_FF_CSV_HEADER})
    except Exception:
        pass



def _ws_wipe_cache_for(cdir, wallet, chain, duration):
    fp = _ws_wallet_csv_path(cdir)
    if not fp.exists():
        return
    try:
        rows_keep = []
        with fp.open("r", encoding="utf-8", newline="") as fh:
            rd = csv.DictReader(fh)
            for r in rd:
                same_w = str(r.get("wallet", "")).lower() == str(wallet).lower()
                same_c = str(r.get("chain", "")) == str(chain)
                same_d = str(r.get("duration", "")) == str(duration)
                if not (same_w and same_c and same_d):
                    rows_keep.append(r)
        with fp.open("w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=_WS_CSV_HEADER)
            wr.writeheader()
            for r in rows_keep:
                wr.writerow({k: r.get(k, "") for k in _WS_CSV_HEADER})
    except Exception:
        pass


def _ws_cache_hit(cdir, wallet, chain, duration, pnl_method, nocache):
    if nocache:
        return None
    fp = _ws_wallet_csv_path(cdir)
    if not fp.exists():
        return None
    try:
        now = time.time()
        ttl = _WS_CACHE_TTL_HOURS * 3600.0
        with fp.open("r", encoding="utf-8", newline="") as fh:
            rd = csv.DictReader(fh)
            best = None
            best_age = None
            for r in rd:
                if str(r.get("wallet", "")).lower() != str(wallet).lower():
                    continue
                if str(r.get("chain", "")) != str(chain):
                    continue
                if str(r.get("duration", "")) != str(duration):
                    continue
                if str(r.get("pnl_method", "net_cash")) != str(pnl_method):
                    continue
                try:
                    ts = float(r.get("ts_utc") or 0.0)
                except Exception:
                    continue
                age = now - ts
                if age > ttl:
                    continue
                if best_age is None or age < best_age:
                    best_age = age
                    best = dict(r)
        return best
    except Exception:
        return None


def _ws_cache_append(cdir, payload):
    fp = _ws_wallet_csv_path(cdir)
    write_header = not fp.exists()
    try:
        with fp.open("a", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=_WS_CSV_HEADER)
            if write_header:
                wr.writeheader()
            wr.writerow({k: payload.get(k, "") for k in _WS_CSV_HEADER})
    except Exception:
        pass


def _ws_get(key, d, default=None):
    """Safe nested-get helper (dict only, single key depth lenient)."""
    if isinstance(d, dict):
        return d.get(key, default)
    return default


def _ws_total_cu(cu):
    total = 0
    if isinstance(cu, dict):
        for v in cu.values():
            try:
                total += int(v or 0)
            except Exception:
                pass
    return total


def _ws_fetch_leaderboard_benchmark(cdir, key, chain_full, pnl_method="wac", force_refresh=False):
    """GET /wallet/v2/leaderboard → 25 CU. Once-per-day cache.

    Returns the full sorted list (descending) of 30D realized PnL from the top
    leaderboard wallets. This is used for PERCENTILE RANK scoring:
      rank = number of leaderboard wallets with realized >= wallet's realized
      score = 100 * (1 - (rank / N)^2)   → top 1 ≈ 100, top 20 ≈ 96, mid ≈ 75
    Cached to wallet_leaderboard_benchmark.json with 24h TTL.

    Returns (leaderboard_list, cu_used, meta_dict).
      leaderboard_list: list[float] sorted descending (may be empty on failure).
    """
    bench_path = _cache_dir(cdir) / "wallet_leaderboard_benchmark.json"
    if not force_refresh and bench_path.exists():
        try:
            cached = json.loads(bench_path.read_text(encoding="utf-8"))
            age = time.time() - float(cached.get("ts_utc") or 0.0)
            if age < _WS_CACHE_TTL_HOURS * 3600.0:
                lb_list = cached.get("leaderboard_realized_list") or []
                if isinstance(lb_list, list) and lb_list:
                    return lb_list, 0, {"cached": True, "age_hours": round(age / 3600.0, 2),
                                        "chain": cached.get("chain"), "pnl_method": cached.get("pnl_method"),
                                        "count": len(lb_list),
                                        "max": float(lb_list[0])}
        except Exception:
            pass

    # Only solana leaderboard is supported by Birdeye
    if chain_full != "solana":
        return [_WS_V3["PROFIT_TARGET_USD"]], 0, {"cached": False, "note": "leaderboard solana-only, using fallback $1M", "count": 1, "max": _WS_V3["PROFIT_TARGET_USD"]}

    import requests as _req
    sess = _req.Session()
    url = f"{BIRDEYE_BASE}/wallet/v2/leaderboard"
    headers = {"x-chain": "solana", "X-API-KEY": key}
    params = {
        "sort_by": "realized_pnl",
        "interval": "30d",
        "pnl_method": pnl_method,
        "limit": 100,
        "offset": 0,
    }
    try:
        r = sess.get(url, headers=headers, params=params, timeout=60)
        j = r.json()
    except Exception:
        j = {}

    realized_vals = []
    data = j.get("data") if isinstance(j, dict) else None
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            rp = row.get("realized_pnl")
            if isinstance(rp, (int, float)) and float(rp) > 0:
                realized_vals.append(float(rp))

    # Sort descending
    realized_vals.sort(reverse=True)

    # Fallback: if leaderboard returns empty or fails, use $1M as single anchor
    if not realized_vals:
        realized_vals = [_WS_V3["PROFIT_TARGET_USD"]]

    try:
        bench_path.write_text(json.dumps({
            "ts_utc": time.time(),
            "chain": "solana",
            "pnl_method": pnl_method,
            "leaderboard_realized_list": realized_vals,
            "benchmark_realized_pnl_usd": realized_vals[0],  # max (for backward compat)
            "leaderboard_count": len(realized_vals),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return realized_vals, 25, {"cached": False, "leaderboard_count": len(realized_vals), "max": realized_vals[0]}


def _ws_fetch_pnl_summary(session, key, chain_full, wallet, duration, pnl_method):
    """GET /wallet/v2/pnl/summary → 30 CU. Core PnL overview."""
    url = f"{BIRDEYE_BASE}/wallet/v2/pnl/summary"
    headers = {"x-chain": chain_full, "X-API-KEY": key}
    params = {
        "wallet": wallet,
        "duration": duration,
        "pnl_method": pnl_method,
        "position_scope": "duration_only",
    }
    r = session.get(url, headers=headers, params=params, timeout=60)
    try:
        j = r.json()
    except Exception:
        j = {}
    return j, 30


def _ws_fetch_pnl_per_token(session, key, chain_full, wallet, pnl_method, duration="30d"):
    """POST /wallet/v2/pnl/details → 30 CU. Wallet summary + per-token breakdown.

    Replaces the deprecated GET /wallet/v2/pnl (which required token_addresses).
    token_addresses is OPTIONAL here — we omit it to get the full token list.
    Used for: rug detection, profit concentration, loss discipline.
    Response shape: {data: {meta, tokens: [...], summary}}
    """
    url = f"{BIRDEYE_BASE}/wallet/v2/pnl/details"
    headers = {
        "x-chain": chain_full,
        "X-API-KEY": key,
        "Content-Type": "application/json",
    }
    body = {
        "wallet": wallet,
        "duration": duration,
        "pnl_method": pnl_method,
        "position_scope": "duration_only",
        "sort_by": "last_trade",
        "sort_type": "desc",
        "limit": 100,
        "offset": 0,
    }
    r = session.post(url, headers=headers, json=body, timeout=60)
    try:
        j = r.json()
    except Exception:
        j = {}
    return j, 30


def _ws_fetch_first_funded(session, key, chain_full, wallet):
    """POST /wallet/v2/tx/first-funded → ceil(40 * wallet_count^0.8) ≈ 40 CU single wallet.

    Note: solana only per Birdeye docs. Skip silently for other chains.
    """
    if chain_full != "solana":
        return {}, 0
    url = f"{BIRDEYE_BASE}/wallet/v2/tx/first-funded"
    headers = {
        "x-chain": chain_full,
        "X-API-KEY": key,
        "Content-Type": "application/json",
    }
    body = {"wallets": [wallet]}
    r = session.post(url, headers=headers, json=body, timeout=60)
    try:
        j = r.json()
    except Exception:
        j = {}
    return j, 40


def _ws_fetch_portfolio_v2(session, key, chain_full, wallet):
    """GET /wallet/v2/current-net-worth → 30 CU.

    Note: x-chain in {solana, robinhood} only. Skip silently for other chains.
    """
    if chain_full not in ("solana", "robinhood"):
        return {}, 0
    url = f"{BIRDEYE_BASE}/wallet/v2/current-net-worth"
    headers = {"x-chain": chain_full, "X-API-KEY": key}
    params = {
        "wallet": wallet,
        "sort_by": "value",
        "sort_type": "desc",
        "limit": 50,
        "offset": 0,
    }
    r = session.get(url, headers=headers, params=params, timeout=60)
    try:
        j = r.json()
    except Exception:
        j = {}
    return j, 30


def _ws_alpha_tier(alpha):
    if alpha >= 95:
        return ("LEGENDARY", "💎", "#22d3ee")
    if alpha >= 80:
        return ("ELITE", "🟢", "#22c55e")
    if alpha >= 65:
        return ("PRO",   "🟡", "#facc15")
    if alpha >= 50:
        return ("ADVANCED", "🟠", "#fb923c")
    if alpha >= 30:
        return ("NOVICE", "🟤", "#f87171")
    return ("RISK",  "🔴", "#dc2626")


def _ws_classify_copy_tier(copy_score, c_entry=None, c_profit=None, c_hold=None, c_feasible=None, c_edge=None):
    """7-tier copyability: 3 copyable, 2 neutral, 2 hard.

    When component scores (0..100) are provided, tiers are assigned by BOTH the
    overall score AND the dominant component profile. When components are None
    (e.g. CSV cache replay), falls back to score-only thresholds.
    """
    has_profile = all(v is not None for v in (c_entry, c_profit, c_hold, c_feasible, c_edge))
    if has_profile:
        if (copy_score >= 70 and c_profit >= 50 and c_feasible >= 40 and c_edge >= 40):
            return ("Elite Copy", "💎", "#22c55e")
        if (copy_score >= 55 and c_hold >= 50 and c_profit >= 35):
            return ("Steady Safe Copy", "🟢", "#22c55e")
        if (copy_score >= 45 and c_profit >= 60):
            return ("Risky High-Profit Copy", "🟡", "#f59e0b")
        if (copy_score >= 40 and c_hold >= 60):
            return ("Long-Term Patient Copy", "⚪", "#94a3b8")
        if (copy_score >= 30 and c_entry < 40):
            return ("Speculative Entry Copy", "⚪", "#94a3b8")
        if (copy_score >= 15):
            return ("Low Edge / Noisy", "🔴", "#ef4444")
        return ("Do Not Copy", "⛔", "#dc2626")
    # Score-only fallback (cache replay)
    if copy_score >= 70:
        return ("Elite Copy", "💎", "#22c55e")
    if copy_score >= 55:
        return ("Steady Safe Copy", "🟢", "#22c55e")
    if copy_score >= 45:
        return ("Risky High-Profit Copy", "🟡", "#f59e0b")
    if copy_score >= 40:
        return ("Long-Term Patient Copy", "⚪", "#94a3b8")
    if copy_score >= 30:
        return ("Speculative Entry Copy", "⚪", "#94a3b8")
    if copy_score >= 15:
        return ("Low Edge / Noisy", "🔴", "#ef4444")
    return ("Do Not Copy", "⛔", "#dc2626")


def _ws_compute(pnl_summary, per_token, first_funded, portfolio, duration,
                skip_rug, wallet=None, pnl_summary_24h=None, pnl_summary_90d=None,
                benchmark_realized_pnl=None, leaderboard_list=None, **_ignored):
    """Core alpha v3.2 compute.

    v3.2 changes from v3.1:
    - Profitability blends ROI base with ABSOLUTE-PROFIT base: base = max(roi_base,
      abs_profit_base), so a wallet with $40M realized at 8.85% ROI scores high
      (abs_profit_base = clamp(log10(realized/100)*20, 0, 100)).
    - Quality: loss_discipline = per-token SMART-EXIT score, value-weighted by
      token buy USD. A token with realized profit covering its paper loss is a
      smart exit (good); pure bag-holds are penalized by loss depth.
    - Copy-tradeability expanded from 3 → 7 tiers (3 copyable, 2 neutral, 2 hard),
      determined by overall score + component profile, not just score ranges.
      Net-worth-withdrawal note added when current net worth << realized profit.
    Returns dict: {metrics, components, step_checks, alpha_score, hard, tier, wallet_info, formula_doc}.
    """
    # ================================== 1. Extract raw fields from 30D PnL summary
    data = pnl_summary.get("data") if isinstance(pnl_summary, dict) else None
    summary = data.get("summary") if isinstance(data, dict) else None
    if not isinstance(summary, dict):
        summary = {}
    counts = summary.get("counts") or {}
    cashflow = summary.get("cashflow_usd") or {}
    pnl = summary.get("pnl") or {}

    unique_tokens = int(counts.get("unique_tokens") or summary.get("unique_tokens") or 0)
    total_trade = int(counts.get("total_trade") or counts.get("total_tx_count") or 0)
    total_buy = int(counts.get("total_buy") or 0)
    total_sell = int(counts.get("total_sell") or 0)
    total_win = int(counts.get("total_win") or 0)
    total_loss = int(counts.get("total_loss") or 0)

    # win_rate: normalize 0..1 (could be ratio or percent from API)
    wr_raw = counts.get("win_rate")
    if isinstance(wr_raw, (int, float)):
        win_rate_vals_norm = _ws_to_fraction([wr_raw])
        win_rate_fraction = win_rate_vals_norm[0]
    else:
        win_rate_fraction = 0.0
        if total_win + total_loss > 0:
            win_rate_fraction = _ws_clamp(total_win / (total_win + total_loss), 0.0, 1.0)

    invested = float(cashflow.get("total_invested") or 0.0)
    sold = float(cashflow.get("total_sold") or 0.0)
    current_value = float(cashflow.get("current_value") or 0.0)
    volume_usd = max(invested, sold, 0.0)

    realized_usd = float(pnl.get("realized_profit_usd") or pnl.get("realized_usd") or 0.0)
    unrealized_usd = float(pnl.get("unrealized_usd") or 0.0)
    total_pnl_usd = float(pnl.get("total_usd") or realized_usd + unrealized_usd)
    avg_profit_per_trade = float(pnl.get("avg_profit_per_trade_usd") or 0.0)
    realized_pct_raw = pnl.get("realized_profit_percent")
    rpct_vals = _ws_to_fraction([realized_pct_raw]) if isinstance(realized_pct_raw, (int, float)) else [0.0]
    realized_pct = rpct_vals[0]

    # 90D realized PnL for trend (30d vs previous 60d)
    realized_usd_90d = None
    if isinstance(pnl_summary_90d, dict):
        s90 = (((pnl_summary_90d.get("data") or {}).get("summary")) or {})
        p90 = s90.get("pnl") or {}
        r90 = p90.get("realized_profit_usd")
        if isinstance(r90, (int, float)):
            realized_usd_90d = float(r90)

    # 24h realized PnL (diagnostic only, not used in v3 trend score)
    realized_usd_24h = None
    if isinstance(pnl_summary_24h, dict):
        s24 = (((pnl_summary_24h.get("data") or {}).get("summary")) or {})
        p24 = s24.get("pnl") or {}
        r24 = p24.get("realized_profit_usd")
        if isinstance(r24, (int, float)):
            realized_usd_24h = float(r24)

    # ================================== 2. Per-token PnL from POST /wallet/v2/pnl/details
    # Response: {data: {tokens: [ {pnl:{realized_profit_usd, realized_profit_percent, total_usd, total_percent}, counts:{...}, ...} ], summary:{...}}}
    tokens_list = []
    token_count_in_scan = 0
    if not skip_rug and isinstance(per_token, dict):
        per_data = per_token.get("data")
        if isinstance(per_data, dict):
            tk = per_data.get("tokens")
            if isinstance(tk, list):
                tokens_list = [t for t in tk if isinstance(t, dict)]
            elif isinstance(tk, dict):
                tokens_list = [t for t in tk.values() if isinstance(t, dict)]
        token_count_in_scan = len(tokens_list)

    # --- Deep-loss token detection: tokens with total_percent <= -50% (NOT "rug" — these are
    #     simply tokens that lost a lot of value; the wallet may have already cashed out profits) ---
    # Loss tiers by total_percent:
    #   CRITICAL: total_percent <= -0.90  (≥90% loss)
    #   SEVERE:   total_percent <= -0.75  (≥75% loss)
    #   MODERATE: total_percent <= -0.50  (≥50% loss)
    # Cash-out classification for loss tokens:
    #   BAG_HOLD  (bad):  realized_profit_usd <= 0  → never booked profit, just holding a losing bag
    #   SMART_EXIT (good): realized_profit_usd > 0   → already took profit; remaining position is down
    deep_loss_count = 0              # total loss tokens (all tiers, regardless of cash-out)
    loss_critical_count = 0
    loss_severe_count = 0
    loss_moderate_count = 0
    bag_hold_loss_count = 0          # loss tokens where realized <= 0 (the ones that hurt quality)
    smart_exit_loss_count = 0        # loss tokens where realized > 0 (already cashed out — not penalized)
    bag_hold_critical = 0
    bag_hold_severe = 0
    bag_hold_moderate = 0
    # --- For distribution & loss discipline ---
    per_token_realized = []      # list of (realized_profit_usd)
    closed_positions = 0         # tokens with buys AND sells (fully or partially realized)
    profitable_positions = 0     # tokens with realized_profit_usd > 0
    severe_loss_positions = 0    # tokens with realized_profit_percent <= -50%
    # --- Smart-exit weighted loss discipline (v3.2) ---
    # For each token we compute a smart_exit_score (0..100) and weight it by
    # the token's buy USD. A token that is deeply down (-50/-75/-90/-95%) but
    # where the wallet already booked realized profit >= the remaining paper
    # loss is a SMART EXIT → full score. Pure bag-holds (no booked profit) get
    # penalised proportionally to loss depth.
    smart_exit_weighted_sum = 0.0   # Σ (smart_exit_score_i × buy_usd_i)
    smart_exit_weight_total = 0.0   # Σ buy_usd_i
    smart_exit_tokens_scored = 0
    for tinfo in tokens_list:
        tpnl = tinfo.get("pnl") or {}
        tcounts = tinfo.get("counts") or {}
        tcf = tinfo.get("cashflow_usd") or tinfo.get("cashflow") or {}
        rp = tpnl.get("realized_profit_usd")
        rpp = tpnl.get("realized_profit_percent")
        tpp = tpnl.get("total_percent")
        unr = tpnl.get("unrealized_usd")
        # Buy USD for this token (weight). Try several field names, fall back to
        # |realized|+|unrealized| as a value-involved proxy.
        buy_usd_t = (
            float(tcf.get("total_invested") or 0.0)
            or float(tcf.get("total_buy") or 0.0)
            or float(tcf.get("buy_usd") or 0.0)
        )
        if buy_usd_t <= 0:
            buy_usd_t = abs(float(rp) if isinstance(rp, (int, float)) else 0.0) + abs(float(unr) if isinstance(unr, (int, float)) else 0.0)
        # closed position = has both buy and sell
        has_buy = int(tcounts.get("total_buy") or 0) > 0
        has_sell = int(tcounts.get("total_sell") or 0) > 0
        if has_buy and has_sell:
            closed_positions += 1
        if isinstance(rp, (int, float)):
            per_token_realized.append(float(rp))
            if float(rp) > 0:
                profitable_positions += 1
        # deep-loss: total_percent (combined realized+unrealized) <= -50%
        is_deep_loss = False
        loss_tier = None  # "critical" | "severe" | "moderate" | None
        if isinstance(tpp, (int, float)):
            if float(tpp) <= _WS_V3["LOSS_TIER_CRITICAL"]:
                is_deep_loss = True; loss_tier = "critical"
            elif float(tpp) <= _WS_V3["LOSS_TIER_SEVERE"]:
                is_deep_loss = True; loss_tier = "severe"
            elif float(tpp) <= _WS_V3["LOSS_TIER_MODERATE"]:
                is_deep_loss = True; loss_tier = "moderate"
        elif isinstance(rpp, (int, float)) and float(rpp) <= _WS_V3["LOSS_TIER_MODERATE"]:
            # fallback to realized percent if total_percent missing
            is_deep_loss = True
            if float(rpp) <= _WS_V3["LOSS_TIER_CRITICAL"]:
                loss_tier = "critical"
            elif float(rpp) <= _WS_V3["LOSS_TIER_SEVERE"]:
                loss_tier = "severe"
            else:
                loss_tier = "moderate"

        if is_deep_loss:
            deep_loss_count += 1
            if loss_tier == "critical":
                loss_critical_count += 1
            elif loss_tier == "severe":
                loss_severe_count += 1
            elif loss_tier == "moderate":
                loss_moderate_count += 1
            # cash-out classification
            rp_val = float(rp) if isinstance(rp, (int, float)) else 0.0
            if rp_val > _WS_V3["CASH_OUT_SMART_EXIT_MIN_USD"]:
                smart_exit_loss_count += 1
            else:
                bag_hold_loss_count += 1
                if loss_tier == "critical":
                    bag_hold_critical += 1
                elif loss_tier == "severe":
                    bag_hold_severe += 1
                elif loss_tier == "moderate":
                    bag_hold_moderate += 1

        # severe loss: realized_profit_percent <= -50% (for loss_discipline subscore)
        if isinstance(rpp, (int, float)) and float(rpp) <= -0.50:
            severe_loss_positions += 1

        # ---- Per-token smart_exit_score (0..100) for weighted loss discipline ----
        # A token is "smart exit" if the wallet already booked enough realized
        # profit to cover the remaining paper loss. Pure bag-holds (no booked
        # profit on a losing token) are penalised by loss depth.
        rp_val = float(rp) if isinstance(rp, (int, float)) else 0.0
        unr_val = float(unr) if isinstance(unr, (int, float)) else 0.0
        tpp_val = float(tpp) if isinstance(tpp, (int, float)) else (float(rpp) if isinstance(rpp, (int, float)) else 0.0)
        if rp_val > 0:
            # Booked profit exists. Coverage = realized_profit / |paper_loss|.
            paper_loss_abs = abs(min(unr_val, 0.0))
            if paper_loss_abs > 0:
                coverage = rp_val / paper_loss_abs
                smart_exit_score = _ws_clamp(coverage * 100.0, 0.0, 100.0)
            else:
                # No paper loss (unrealized >= 0) and booked profit → perfect exit.
                smart_exit_score = 100.0
        else:
            # No booked profit (bag hold). Penalise by total loss depth.
            # -0% → 50 (neutral hold), -50% → 25, -90% → 5, -100% → 0.
            loss_frac = abs(min(tpp_val, 0.0))  # 0..1
            smart_exit_score = _ws_clamp(50.0 * (1.0 - loss_frac), 0.0, 50.0)
        # Accumulate weighted by buy USD (larger positions matter more).
        smart_exit_weighted_sum += smart_exit_score * max(buy_usd_t, 1e-9)
        smart_exit_weight_total += max(buy_usd_t, 1e-9)
        smart_exit_tokens_scored += 1

    # Weighted-average smart-exit score across all scanned tokens.
    if smart_exit_weight_total > 0 and smart_exit_tokens_scored > 0:
        smart_exit_avg = smart_exit_weighted_sum / smart_exit_weight_total
    else:
        smart_exit_avg = None  # no per-token data → fall back to old formula

    denom_deep_loss = max(1, token_count_in_scan if token_count_in_scan > 0 else unique_tokens)
    deep_loss_fraction = _ws_clamp(deep_loss_count / denom_deep_loss, 0.0, 1.0)
    bag_hold_loss_fraction = _ws_clamp(bag_hold_loss_count / denom_deep_loss, 0.0, 1.0)
    if skip_rug:
        deep_loss_fraction = 0.0
        bag_hold_loss_fraction = 0.0

    # Weighted bag-hold loss count (critical=1.0, severe=0.67, moderate=0.33) for penalty depth
    weighted_bag_hold = (
        bag_hold_critical * 1.0
        + bag_hold_severe * 0.67
        + bag_hold_moderate * 0.33
    )
    # deep_loss_penalty = weighted bag-hold loss fraction × 100 (only bag-hold tokens hurt quality)
    deep_loss_penalty_pts = round(
        _ws_clamp(weighted_bag_hold / denom_deep_loss, 0.0, 1.0) * 100.0, 2
    )
    # Backward-compat alias: rug_* → deep_loss_*
    rug_count = deep_loss_count
    rug_fraction = deep_loss_fraction
    rug_penalty_pts = deep_loss_penalty_pts

    # --- Profit concentration: largest positive position / total positive realized ---
    positive_realized = [r for r in per_token_realized if r > 0]
    total_positive_realized = sum(positive_realized)
    largest_positive = max(positive_realized) if positive_realized else 0.0
    if total_positive_realized > 0:
        profit_concentration = largest_positive / total_positive_realized
    else:
        profit_concentration = 0.0
    profit_concentration = _ws_clamp(profit_concentration, 0.0, 1.0)
    diversification = 1.0 - profit_concentration

    # Severe loss fraction
    severe_loss_fraction = _ws_clamp(
        severe_loss_positions / max(1, closed_positions), 0.0, 1.0
    ) if closed_positions > 0 else 0.0

    # Profitable position fraction
    profitable_fraction = _ws_clamp(
        profitable_positions / max(1, closed_positions), 0.0, 1.0
    ) if closed_positions > 0 else 0.0

    # ================================== 3. Hard filters
    hard_tx_pass = total_trade >= _WS_HARD["MIN_TX_COUNT"]
    hard_vol_pass = volume_usd >= _WS_HARD["MIN_VOLUME_USD"]
    hard_deep_loss_pass = bag_hold_loss_fraction <= _WS_HARD["MAX_DEEP_LOSS_FRACTION"]
    all_hard_pass = bool(hard_tx_pass and hard_vol_pass and hard_deep_loss_pass)

    hard_fail_reasons = []
    if not hard_tx_pass:
        hard_fail_reasons.append(f"Insufficient trades (tx={total_trade} < {_WS_HARD['MIN_TX_COUNT']})")
    if not hard_vol_pass:
        hard_fail_reasons.append(f"Low volume (${volume_usd:,.0f} < ${_WS_HARD['MIN_VOLUME_USD']:,.0f})")
    if not hard_deep_loss_pass:
        hard_fail_reasons.append(f"Too many bag-hold loss tokens (deep_loss%={bag_hold_loss_fraction*100:.1f}% > {_WS_HARD['MAX_DEEP_LOSS_FRACTION']*100:.0f}%)")

    # ================================== 4. v3 Four components

    # --- Profitability (35%) ---
    # v3.2: FIXED ROI thresholds BLENDED with ABSOLUTE profit magnitude.
    #   roi_realized = realized_profit / invested   (realized_profit_pnl equivalent)
    #   roi_total    = (realized + unrealized) / invested
    #   We use min(roi_realized, roi_total) so that a wallet showing realized profit
    #   but an overall loss (unrealized drag) does NOT get full credit.
    #   roi_base = clamp((roi + 0.05) / 0.35) × 100  →  -5% → 0, +30% → 100.
    #   abs_profit_base = clamp(log10(realized_usd / 100) × 20, 0, 100)
    #     → $100→0, $1k→20, $10k→40, $100k→60, $1M→80, $10M→100.
    #   A wallet that books $40M profit (even at 8.85% ROI) should score high:
    #   profitability_base = max(roi_base, abs_profit_base).
    # Then × keep_factor for an additional linear unrealized-loss granularity penalty.
    roi_realized = realized_usd / max(invested, 1.0)
    roi_total = (realized_usd + unrealized_usd) / max(invested, 1.0)
    # Blend: realized is the booked result; total is the economic reality.
    # If total < realized (unrealized losses), drag the effective ROI down.
    roi_effective = min(roi_realized, roi_total)
    roi_base = 100.0 * _ws_clamp((roi_effective + 0.05) / 0.35, 0.0, 1.0)
    # Absolute-profit magnitude: rewards large booked profits regardless of ROI%.
    abs_profit_base = 0.0
    if realized_usd > 0:
        abs_profit_base = 100.0 * _ws_clamp(
            math.log10(max(realized_usd, 1.0) / 100.0) * 0.20, 0.0, 1.0
        )
    profit_base = max(roi_base, abs_profit_base)

    # Unrealized loss penalty — additional LINEAR granularity on top:
    #   factor = max(0, 1 − |unrealized_loss| / realized)
    unrealized_penalty_factor = 0.0
    if unrealized_usd < 0 and realized_usd > 0:
        loss_ratio = abs(unrealized_usd) / max(abs(realized_usd), 1e-9)
        keep_factor = max(0.0, 1.0 - loss_ratio)
        unrealized_penalty_factor = 1.0 - keep_factor
        profit_base = profit_base * keep_factor
    profitability_score = round(_ws_clamp(profit_base, 0.0, 100.0), 2)
    # Leaderboard fields kept as zeros for backward-compat (no longer fetched).
    leaderboard_rank = 0
    N = 0

    # --- Consistency (35%) ---
    # 5.1 win_rate_score (20%): 60% win rate → 100
    win_rate_score = _ws_clamp(win_rate_fraction / _WS_V3["WIN_RATE_TARGET"] * 100.0, 0.0, 100.0)

    # 5.2 trend_score (40%): 30D vs previous 60D (from 90D)
    trend_score = 50.0  # neutral default when 90D unavailable
    trend_status = "INSUFFICIENT_HISTORY"
    pnl_previous_60d = None
    if realized_usd_90d is not None:
        pnl_previous_60d = realized_usd_90d - realized_usd
        recent_daily = realized_usd / 30.0
        prev_daily = pnl_previous_60d / 60.0
        meaningful = abs(realized_usd) > _WS_V3["MIN_MEANINGFUL_PROFIT_USD"] or abs(pnl_previous_60d) > _WS_V3["MIN_MEANINGFUL_PROFIT_USD"]
        if not meaningful:
            trend_score = 50.0
            trend_status = "INSUFFICIENT_HISTORY"
        elif realized_usd > 0 and pnl_previous_60d > 0:
            ratio = recent_daily / max(abs(prev_daily), 1e-9)
            stability = min(ratio, 1.0 / max(ratio, 1e-9))
            trend_score = 70.0 + 30.0 * stability
            trend_status = "SUSTAINABLE"
        elif realized_usd > 0 and abs(pnl_previous_60d) <= _WS_V3["MIN_MEANINGFUL_PROFIT_USD"]:
            # New wallet (no prev60D history) that's already profitable → good
            trend_score = 85.0
            trend_status = "NEW_PROFITABLE"
        elif realized_usd > 0 and pnl_previous_60d <= 0:
            trend_score = 35.0
            trend_status = "RECENT_RECOVERY"
        elif realized_usd <= 0 and pnl_previous_60d > 0:
            trend_score = 15.0
            trend_status = "RECENT_LOSSES"
        else:
            trend_score = 0.0
            trend_status = "UNPROFITABLE"
    trend_score = round(_ws_clamp(trend_score, 0.0, 100.0), 2)

    # 5.3 trade_distribution_score (25%): profitable position fraction + diversification
    if closed_positions > 0:
        profitable_position_score = _ws_clamp(
            profitable_fraction / 0.60 * 100.0, 0.0, 100.0
        )
        distribution_score = 100.0 * (1.0 - profit_concentration)
        trade_distribution_score = round(0.60 * profitable_position_score + 0.40 * distribution_score, 2)
    else:
        trade_distribution_score = 0.0  # unavailable → 0 (not 100)
    trade_distribution_score = round(_ws_clamp(trade_distribution_score, 0.0, 100.0), 2)

    # 5.4 sample_confidence_score (15%): 300 trades → 100
    sample_confidence_score = round(_ws_clamp(
        math.log1p(max(total_trade, 0)) / max(1e-9, math.log1p(_WS_V3["OPTIMAL_TX_COUNT"])) * 100.0,
        0.0, 100.0
    ), 2)

    consistency_score = round(
        win_rate_score * _WS_CONSISTENCY_WEIGHTS["win_rate"]
        + trend_score * _WS_CONSISTENCY_WEIGHTS["trend"]
        + trade_distribution_score * _WS_CONSISTENCY_WEIGHTS["trade_distribution"]
        + sample_confidence_score * _WS_CONSISTENCY_WEIGHTS["sample_confidence"],
        2,
    )

    # --- Quality (20%) ---
    # 6.1 realization_score (35%)
    realized_pos = max(realized_usd, 0.0)
    unrealized_pos = max(unrealized_usd, 0.0)
    positive_total = realized_pos + unrealized_pos
    realization_score = (100.0 * realized_pos / positive_total) if positive_total > 0 else 0.0
    realization_score = round(_ws_clamp(realization_score, 0.0, 100.0), 2)

    # 6.2 profit_distribution_quality_score (35%): 1 - profit_concentration
    profit_distribution_quality_score = round(100.0 * (1.0 - profit_concentration), 2)

    # 6.3 loss_discipline_score (30%): v3.2 smart-exit weighted by buy USD.
    # For each token, smart_exit_score (0..100) rewards booked-profit coverage of
    # paper losses and penalises pure bag-holds by loss depth. The value-weighted
    # average (by buy USD) replaces both the old severe_loss_fraction formula and
    # the separate deep_loss_penalty_pts subtraction (no double-counting).
    if smart_exit_avg is not None:
        loss_discipline_score = round(_ws_clamp(smart_exit_avg, 0.0, 100.0), 2)
    else:
        # Fallback when per-token data unavailable (skip-rug or empty scan).
        loss_discipline_score = round(
            100.0 * (1.0 - _ws_clamp(severe_loss_fraction / _WS_V3["MAX_SEVERE_LOSS_FRACTION"], 0.0, 1.0)), 2
        )

    quality_score = round(
        realization_score * _WS_QUALITY_WEIGHTS["realization"]
        + profit_distribution_quality_score * _WS_QUALITY_WEIGHTS["profit_distribution"]
        + loss_discipline_score * _WS_QUALITY_WEIGHTS["loss_discipline"],
        2,
    )
    quality_score = round(_ws_clamp(quality_score, 0.0, 100.0), 2)

    # --- Activity (10%) ---
    vol_score = _ws_clamp(math.log10(max(volume_usd, 1.0) / 1000.0) * 20.0, 0.0, 100.0)
    tx_confidence = _ws_clamp(
        math.log1p(max(total_trade, 0)) / max(1e-9, math.log1p(_WS_V3["OPTIMAL_TX_COUNT"])), 0.0, 1.0
    )
    # Bot penalty: sqrt(optimal/tx) when tx > optimal, floor 0.70
    if total_trade > _WS_V3["OPTIMAL_TX_COUNT"]:
        bot_penalty = max(math.sqrt(_WS_V3["OPTIMAL_TX_COUNT"] / max(total_trade, 1)), 1.0 - _WS_V3["MAX_BOT_PENALTY"])
    else:
        bot_penalty = 1.0
    activity_score = round(
        (0.60 * vol_score + 0.40 * tx_confidence * 100.0) * bot_penalty, 2
    )
    activity_score = round(_ws_clamp(activity_score, 0.0, 100.0), 2)

    # ================================== 5. Weighted alpha + sustainability gates
    # NOTE: Hard filters (tx count, volume, deep-loss%) are now INFORMATIONAL only.
    # Deep-loss (bag-hold) is already penalized inside Quality (weighted deep_loss_penalty_pts).
    # No ×0.5 alpha multiplier — every penalty is granular within components.
    alpha_weighted = (
        profitability_score * _WS_WEIGHTS["profitability"]
        + consistency_score * _WS_WEIGHTS["consistency"]
        + quality_score * _WS_WEIGHTS["quality"]
        + activity_score * _WS_WEIGHTS["activity"]
    )

    # Sustainability gates (only when historical data valid)
    gate_applied = []
    if realized_usd <= 0:
        alpha_weighted = min(alpha_weighted, 39.0)
        gate_applied.append("30D_realized<=0 → cap 39")
    if realized_usd_90d is not None and realized_usd_90d <= 0:
        alpha_weighted = min(alpha_weighted, 49.0)
        gate_applied.append("90D_realized<=0 → cap 49")
    # prev60D gate: only applies when there was MEANINGFUL activity in the
    # previous 60 days (|prev60d| > $100). A brand-new wallet (wallet age < 60d)
    # will have prev60d ≈ 0 and should NOT be penalized for lacking history.
    if (pnl_previous_60d is not None and pnl_previous_60d <= 0 and realized_usd > 0
            and abs(pnl_previous_60d) > _WS_V3["MIN_MEANINGFUL_PROFIT_USD"]):
        alpha_weighted = min(alpha_weighted, 69.0)
        gate_applied.append("prev60D<=0 → cap 69")

    alpha_score = round(_ws_clamp(alpha_weighted, 0.0, 100.0), 2)

    # Data confidence
    if realized_usd_90d is not None and closed_positions > 0:
        data_confidence = "HIGH"
    elif realized_usd_90d is not None:
        data_confidence = "MEDIUM"
    else:
        data_confidence = "LOW"

    tier_name, tier_emoji, tier_color = _ws_alpha_tier(alpha_score)

    # ================================== 4b. Copy-tradeability score (0–100)
    # Can a follower actually capture this wallet's edge? 5 factors:
    #   entry     (0.22)  — later entries (higher mcap) are more copyable
    #   profit    (0.22)  — per-trade profit room (avg profit / trade ≥ $80 saturates)
    #   hold      (0.20)  — hold time vs flip rate (needs time to follow in)
    #   feasible  (0.18)  — trade count feasibility (too many trades = uncopyable)
    #   edge      (0.18)  — edge durability (early-entry + fast-flip erodes edge)
    # Factors needing tx_list (entry_under_100k, fast_flip_rate, avg_hold_s) are
    # estimated from per-token + summary data when tx_list is not fetched, to
    # keep the leaderboard-removal CU savings intact.
    gt_5x_count = 0
    for tinfo in tokens_list:
        tpnl = tinfo.get("pnl") or {}
        rpp = tpnl.get("realized_profit_percent")
        if isinstance(rpp, (int, float)) and float(rpp) >= 4.0:
            gt_5x_count += 1
    scan_denom = max(1, token_count_in_scan if token_count_in_scan > 0 else unique_tokens)
    # Proxy: fraction of tokens that 5x'd → likely entered under $100k mcap.
    entry_under_100k_est = _ws_clamp(gt_5x_count / scan_denom, 0.0, 1.0)
    # Proxy: high frequency → some fast flipping. trades/day ≥ 50 → ~50% fast flip.
    dur_days = float({"1d": 1, "7d": 7, "30d": 30, "90d": 90, "all": 365}.get(str(duration).lower(), 30))
    trades_per_day = total_trade / max(dur_days, 1.0)
    fast_flip_rate_est = _ws_clamp(trades_per_day / 100.0, 0.0, 1.0) * 0.5
    # Proxy: avg hold ≈ duration / (trades per token). Needs time to follow in.
    trades_per_token = total_trade / max(unique_tokens, 1)
    avg_hold_s_est = (dur_days * 86400.0) / max(trades_per_token, 1.0)
    # Per-trade profit: avg_profit_per_trade if available, else realized / trades.
    avg_trade_usd = float(avg_profit_per_trade) if isinstance(avg_profit_per_trade, (int, float)) and avg_profit_per_trade != 0 else (realized_usd / max(total_trade, 1))

    copy_entry_f = _ws_clamp(0.12 + (1.0 - entry_under_100k_est), 0.0, 1.0)
    copy_profit_f = _ws_clamp(avg_trade_usd / 80.0, 0.0, 1.0)
    copy_hold_f = _ws_clamp(
        (1.0 - fast_flip_rate_est * 1.6) * _ws_clamp(avg_hold_s_est / 172800.0 + 0.15, 0.0, 1.0),
        0.0, 1.0,
    )
    copy_feasible_f = _ws_clamp(1.0 - total_trade / 2500.0, 0.0, 1.0)
    copy_edge_f = _ws_clamp(1.0 - 0.6 * entry_under_100k_est - 0.6 * fast_flip_rate_est, 0.0, 1.0)
    copy_score = round(100.0 * (
        0.22 * copy_entry_f
        + 0.22 * copy_profit_f
        + 0.20 * copy_hold_f
        + 0.18 * copy_feasible_f
        + 0.18 * copy_edge_f
    ), 2)

    # ---- Component scores (0..100) for tier classification ----
    c_entry = round(copy_entry_f * 100.0, 1)
    c_profit = round(copy_profit_f * 100.0, 1)
    c_hold = round(copy_hold_f * 100.0, 1)
    c_feasible = round(copy_feasible_f * 100.0, 1)
    c_edge = round(copy_edge_f * 100.0, 1)

    # ---- Net-worth withdrawal risk (for copy note) ----
    # If the wallet withdrew most of its realized profit (current net worth << realized),
    # following in may have less liquidity/impact. Flag for copyability.
    copy_note = ""
    if realized_usd > 1_000 and current_value > 0:
        nwr = current_value / max(realized_usd, 1.0)
        if nwr < 0.30:
            copy_note = (
                f"⚠ Net worth withdrawn low (${current_value:,.0f} vs realized ${realized_usd:,.0f}, "
                f"retention {nwr*100:.0f}%) — copy with caution; wallet may have rotated out."
            )
        elif nwr < 0.60:
            copy_note = (
                f"ℹ Net worth partially withdrawn (${current_value:,.0f} vs realized ${realized_usd:,.0f}, "
                f"retention {nwr*100:.0f}%)."
            )

    # ---- 7-tier copyability classification (3 copyable, 2 neutral, 2 hard) ----
    # Tiers are determined by BOTH the overall score AND the dominant component
    # profile (not just score ranges). See _ws_classify_copy_tier.
    copy_tier = _ws_classify_copy_tier(copy_score, c_entry, c_profit, c_hold, c_feasible, c_edge)

    copy_formula = (
        f"Copy-tradeability = 0.22×entry + 0.22×profit + 0.20×hold + 0.18×feasible + 0.18×edge\n"
        f"  entry    = clamp(0.12 + (1 − entry_under_100k)) = {copy_entry_f:.3f}  "
        f"(entry_under_100k≈{entry_under_100k_est:.2f} from {gt_5x_count}/{scan_denom} tokens ≥5x)\n"
        f"  profit   = clamp(avg_trade_usd/80) = {copy_profit_f:.3f}  (avg_trade=${avg_trade_usd:,.1f})\n"
        f"  hold     = clamp((1 − fast_flip×1.6) × clamp(avg_hold/172800+0.15)) = {copy_hold_f:.3f}  "
        f"(fast_flip≈{fast_flip_rate_est:.2f}, avg_hold≈{avg_hold_s_est/3600:.1f}h)\n"
        f"  feasible = clamp(1 − trades/2500) = {copy_feasible_f:.3f}  (trades={total_trade})\n"
        f"  edge     = clamp(1 − 0.6×entry_under − 0.6×fast_flip) = {copy_edge_f:.3f}\n"
        f"  copy_score = {copy_score:.1f}/100  → {copy_tier[0]}"
        + (f"\n  {copy_note}" if copy_note else "")
    )

    # ================================== 5. Step check results (5 items for UI plain/telegram/rendered)
    step_checks = []
    step_checks.append({
        "id": "S1_HARD_FILTERS",
        "name": "Hard filters (tx≥20 · vol≥$5k · rug%≤50%) — informational",
        "pass": all_hard_pass,
        "level": "warn" if not all_hard_pass else "ok",
        "note": "PASS ✅" if all_hard_pass else "INFO ℹ · " + " | ".join(hard_fail_reasons) + " (no alpha penalty)",
    })
    step_checks.append({
        "id": "S2_PROFITABILITY",
        "name": "Profitability (ROI base + abs-profit base; blended realized+total)",
        "pass": profitability_score >= 50.0,
        "level": "ok" if profitability_score >= 50.0 else "warn",
        "note": (
            f"realized=${realized_usd:+,.2f} · unrealized=${unrealized_usd:+,.2f} · "
            f"roi_realized={roi_realized*100:+.1f}% · roi_total={roi_total*100:+.1f}% · "
            f"roi_base={roi_base:.1f} · abs_profit_base={abs_profit_base:.1f} · "
            f"score={profitability_score:.1f}/100"
            + (f" · unr_penalty={unrealized_penalty_factor*100:.0f}% (|unr|/realized)" if unrealized_penalty_factor > 0 else "")
        ),
    })
    step_checks.append({
        "id": "S3_CONSISTENCY",
        "name": "Consistency (win_rate + 30d/60d trend + distribution + sample)",
        "pass": consistency_score >= 40.0,
        "level": "ok" if consistency_score >= 40.0 else "warn",
        "note": (
            f"WR={win_rate_fraction*100:.1f}% · trades={total_trade} · "
            f"30d=${realized_usd:+,.0f} · prev60d=${pnl_previous_60d if pnl_previous_60d is not None else 0:+,.0f} · "
            f"trend={trend_score:.0f} ({trend_status})"
        ) + f" · score={consistency_score:.1f}/100",
    })
    step_checks.append({
        "id": "S4_QUALITY",
        "name": "Quality (realization + profit dist + smart-exit loss discipline)",
        "pass": quality_score >= 50.0,
        "level": "ok" if quality_score >= 50.0 else "warn",
        "note": (
            f"deep_loss={deep_loss_count}/{token_count_in_scan} "
            f"(crit≥90%:{loss_critical_count} sev≥75%:{loss_severe_count} mod≥50%:{loss_moderate_count}) · "
            f"bag_hold={bag_hold_loss_count} smart_exit={smart_exit_loss_count} · "
            f"smart_exit_avg={loss_discipline_score:.1f}/100 (value-weighted by buy USD) · "
            f"concentration={profit_concentration*100:.0f}% · "
            f"realization={realization_score:.0f}% · "
            f"score={quality_score:.1f}/100"
        ),
    })
    step_checks.append({
        "id": "S5_ACTIVITY",
        "name": "Activity (volume + trade count + bot penalty)",
        "pass": activity_score >= 30.0,
        "level": "ok" if activity_score >= 30.0 else "warn",
        "note": (
            f"vol=${volume_usd:,.0f} · trades={total_trade} · "
            f"bot_penalty={bot_penalty:.2f} · "
            f"score={activity_score:.1f}/100"
        ),
    })

    # ================================== 6. Wallet info (first-funded + portfolio)
    wallet_created_block = None
    wallet_created_ts = None
    wallet_age_days = None
    first_sender = None
    if isinstance(first_funded, dict):
        ff_data = first_funded.get("data") or {}
        if isinstance(ff_data, dict):
            w_info = ff_data.get(wallet)
            if isinstance(w_info, dict):
                block_ts = w_info.get("block_unix_time")
                try:
                    wallet_created_ts = int(block_ts)
                    wallet_created_block = w_info.get("block_number")
                    dt = _dt.datetime.fromtimestamp(wallet_created_ts, _dt.timezone.utc)
                    now = _dt.datetime.now(_dt.timezone.utc)
                    wallet_age_days = (now - dt).days
                    first_sender = str(w_info.get("tx_hash") or "")[:16]
                except Exception:
                    wallet_created_ts = None
                    wallet_created_block = None
                    wallet_age_days = None
                    first_sender = None

    current_net_worth = None
    portfolio_count = None
    if isinstance(portfolio, dict):
        pdata = portfolio.get("data") or {}
        if isinstance(pdata, dict):
            tv = pdata.get("total_value")
            if isinstance(tv, (str, int, float)):
                try:
                    current_net_worth = float(tv)
                except Exception:
                    current_net_worth = current_value
            items = pdata.get("items") or []
            if isinstance(items, list):
                portfolio_count = len(items)
    if current_net_worth is None:
        current_net_worth = current_value

    pf_formula = (
        f"Profitability = max(roi_base, abs_profit_base) × keep_factor  (v3.2 ROI + abs profit)\n"
        f"  roi_realized = ${realized_usd:,.0f} / ${invested:,.0f} = {roi_realized*100:+.2f}%\n"
        f"  roi_total    = (realized+unrealized)/invested = {roi_total*100:+.2f}%\n"
        f"  roi_effective = min(realized, total) = {roi_effective*100:+.2f}%\n"
        f"  roi_base = clamp((roi_eff + 5%) / 35% × 100, 0, 100) = {roi_base:.1f}\n"
        f"  abs_profit_base = clamp(log10(realized/100)×20, 0, 100) = {abs_profit_base:.1f}  (realized=${realized_usd:,.0f})\n"
        f"  base = max(roi_base, abs_profit_base) = {max(roi_base, abs_profit_base):.1f}\n"
        f"  keep_factor = max(0, 1 − |unr|/realized) = {max(0.0, 1.0 - unrealized_penalty_factor):.3f}\n"
        f"  profitability = {profitability_score:.1f}/100"
    )
    cf_formula = (
        f"Consistency = 0.20×wr + 0.40×trend + 0.25×dist + 0.15×sample\n"
        f"  wr_score     = clamp(WR/{_WS_V3['WIN_RATE_TARGET']:.0%}×100, 0, 100) = {win_rate_score:.1f}\n"
        f"  trend_score  = 30d vs prev60d → {trend_status} → {trend_score:.1f}\n"
        f"  dist_score   = 0.60×prof_pos + 0.40×(1−concentration) = {trade_distribution_score:.1f}\n"
        f"  sample_score = clamp(log1p(tx)/log1p({_WS_V3['OPTIMAL_TX_COUNT']})×100) = {sample_confidence_score:.1f}\n"
        f"  consistency  = {consistency_score:.1f}/100"
    )
    qf_formula = (
        f"Quality = 0.35×realization + 0.35×profit_dist + 0.30×loss_discipline (v3.2 smart-exit)\n"
        f"  realization    = {realization_score:.1f} (realized / (realized+unrealized positive))\n"
        f"  profit_dist    = {profit_distribution_quality_score:.1f} (1 − {profit_concentration:.2f} concentration)\n"
        f"  loss_discipline= {loss_discipline_score:.1f} (value-weighted smart_exit by buy USD)\n"
        f"    per-token smart_exit: booked profit ≥ paper loss → 100; bag-hold scaled by loss depth (50@0% → 0@−100%)\n"
        f"    deep-loss tokens: crit≥90%={loss_critical_count} sev≥75%={loss_severe_count} mod≥50%={loss_moderate_count}\n"
        f"    bag_hold(realized≤0)={bag_hold_loss_count} smart_exit(realized>0)={smart_exit_loss_count}\n"
        f"  quality        = {quality_score:.1f}/100"
    )
    af_formula = (
        f"Activity = (0.60×vol_score + 0.40×tx_confidence×100) × bot_penalty\n"
        f"  vol_score   = clamp(log10(vol/1000)×20, 0, 100) = {vol_score:.1f}\n"
        f"  tx_conf     = clamp(log1p(tx)/log1p({_WS_V3['OPTIMAL_TX_COUNT']}), 0, 1) = {tx_confidence:.3f}\n"
        f"  bot_penalty = {bot_penalty:.2f} (floor 0.70 when tx>{_WS_V3['OPTIMAL_TX_COUNT']})\n"
        f"  activity    = {activity_score:.1f}/100"
    )
    alpha_eq_line = (
        f"alpha_weighted = "
        f"P{profitability_score:.1f}×{_WS_WEIGHTS['profitability']} + "
        f"C{consistency_score:.1f}×{_WS_WEIGHTS['consistency']} + "
        f"Q{quality_score:.1f}×{_WS_WEIGHTS['quality']} + "
        f"A{activity_score:.1f}×{_WS_WEIGHTS['activity']} = "
        f"{(profitability_score*_WS_WEIGHTS['profitability']+consistency_score*_WS_WEIGHTS['consistency']+quality_score*_WS_WEIGHTS['quality']+activity_score*_WS_WEIGHTS['activity']):.2f}"
    )
    if not all_hard_pass:
        alpha_eq_line += f"\n  (hard filters informational only — no alpha multiplier)"
    if gate_applied:
        alpha_eq_line += f"\n  gates: {' | '.join(gate_applied)}"
    alpha_eq_line += f"  →  final alpha = {alpha_score:.1f}  (data_confidence={data_confidence})"

    # Build step 0 (data pipeline CU trace) + step 6 (final alpha equation)
    step_checks_extended = list(step_checks)
    step_checks_extended.append({
        "id": "S6_FINAL_ALPHA",
        "name": "Final alpha equation (weights × scores ± penalty)",
        "pass": True,
        "level": "ok",
        "note": alpha_eq_line,
    })
    step_checks_extended.append({
        "id": "S7_COPY_TRADEABILITY",
        "name": "Copy-tradeability (entry+profit+hold+feasible+edge · 7 tiers)",
        "pass": copy_score >= 45.0,
        "level": "ok" if copy_score >= 45.0 else "warn",
        "note": f"copy_score={copy_score:.1f}/100 → {copy_tier[1]} {copy_tier[0]}" + (f" · {copy_note}" if copy_note else ""),
    })

    components_struct = {
        "profitability": {
            "raw_usd": round(realized_usd, 2),
            "score": round(profitability_score, 2),
            "weight": _WS_WEIGHTS["profitability"],
            "formula": "max(roi_base, abs_profit_base) × keep_factor — roi_base=clamp((min(roi_realized,roi_total)+5%)/35%×100); abs_profit_base=clamp(log10(realized/100)×20,0,100); keep_factor=max(0,1−|unr|/realized)",
            "formula_doc": pf_formula,
        },
        "consistency": {
            "raw": round(win_rate_fraction, 5),
            "score": round(consistency_score, 2),
            "weight": _WS_WEIGHTS["consistency"],
            "formula": "0.20×wr + 0.40×trend(30d/prev60d) + 0.25×dist + 0.15×sample",
            "formula_doc": cf_formula,
        },
        "quality": {
            "raw": round(profit_concentration, 5),
            "score": round(quality_score, 2),
            "weight": _WS_WEIGHTS["quality"],
            "formula": "0.35×realization + 0.35×(1−concentration) + 0.30×smart_exit_loss_discipline (value-weighted by buy USD)",
            "formula_doc": qf_formula,
        },
        "activity": {
            "raw": round(volume_usd, 2),
            "score": round(activity_score, 2),
            "weight": _WS_WEIGHTS["activity"],
            "formula": "(0.60×vol_score + 0.40×tx_confidence×100) × bot_penalty (floor 0.70)",
            "formula_doc": af_formula,
        },
    }

    formula_doc_struct = {
        "title": "Wallet Score v3.2 — Smart-exit quality + abs-profit + 7-tier copyability",
        "hard_filters": [
            f"MIN_TX_COUNT ≥ {_WS_HARD['MIN_TX_COUNT']} (current: {total_trade})",
            f"MIN_VOLUME_USD ≥ ${_WS_HARD['MIN_VOLUME_USD']:,.0f} (current: ${volume_usd:,.0f})",
            f"MAX_DEEP_LOSS_FRACTION ≤ {_WS_HARD['MAX_DEEP_LOSS_FRACTION']*100:.0f}% bag-hold loss tokens (current: {bag_hold_loss_fraction*100:.1f}%)",
        ],
        "hard_all_pass": all_hard_pass,
        "penalty_factor_if_fail": "informational only (no alpha multiplier — deep-loss penalized in Quality)",
        "weights": dict(_WS_WEIGHTS),
        "anchors": {
            "profitability": "max(roi_base, abs_profit_base) × keep_factor — roi_base=clamp((min(roi_realized,roi_total)+5%)/35%×100); abs_profit_base=clamp(log10(realized/100)×20,0,100); keep_factor=max(0,1−|unr|/realized)",
            "consistency":  "0.20×wr(target 60%) + 0.40×trend(30d vs prev60d) + 0.25×dist + 0.15×sample(300tx)",
            "quality":      "0.35×realization + 0.35×(1−concentration) + 0.30×smart_exit_loss_discipline (per-token value-weighted by buy USD)",
            "activity":     "(0.60×log10(vol/1k)×20 + 0.40×tx_conf×100) × bot_penalty(floor 0.70)",
        },
        "sustainability_gates": [
            "30D realized ≤ 0  →  cap 39",
            "90D realized ≤ 0  →  cap 49",
            "prev60D ≤ 0 AND |prev60d| > $100 (not a new wallet)  →  cap 69",
        ],
        "tiers": [
            "≥ 95  →  LEGENDARY 💎",
            "≥ 80  →  ELITE 🟢",
            "≥ 65  →  PRO   🟡",
            "≥ 50  →  ADVANCED 🟠",
            "≥ 30  →  NOVICE 🟤",
            "< 30  →  RISK  🔴",
        ],
        "final_equation_line": alpha_eq_line,
        "methodology_note": (
            "v3.2 scores profitability by FIXED ROI thresholds blended with ABSOLUTE profit magnitude "
            "(single-wallet absolute scaling, no leaderboard API call). "
            "roi_realized = realized_profit / invested; roi_total = (realized+unrealized)/invested. "
            "The effective ROI is min(roi_realized, roi_total). roi_base = clamp((roi_eff + 5%)/35% × 100, 0, 100). "
            "abs_profit_base = clamp(log10(realized_usd/100)×20, 0, 100) so large absolute profits (e.g. $1M→80, $10M→100) "
            "are rewarded even at low ROI%. profitability = max(roi_base, abs_profit_base) × keep_factor. "
            "keep_factor = max(0, 1 − |unr|/realized) penalises unrealized drag. "
            "Quality loss_discipline (30%) uses per-token smart_exit_score value-weighted by buy USD: "
            "booked realized profit ≥ remaining paper loss → 100; pure bag-holds scale 50@0%→0@−100% loss depth. "
            "This replaces the old severe_loss_fraction + deep_loss_penalty subtraction (no double-counting). "
            "Hard filters (tx/vol/deep-loss) are informational only — no alpha multiplier. "
            "Consistency uses 30D vs previous-60D trend. Activity applies a bot-penalty floor of 0.70 above 300 trades. "
            "Sustainability gates cap the final score when recent or historical PnL is non-positive. "
            "Copy-tradeability (0–100) is a separate score: 0.22×entry + 0.22×profit/trade + "
            "0.20×hold + 0.18×feasible + 0.18×edge, with 7 tiers (3 copyable, 2 neutral, 2 hard)."
        ),
    }

    return {
        "metrics": {
            "unique_tokens": unique_tokens,
            "total_trade": total_trade,
            "total_buy": total_buy,
            "total_sell": total_sell,
            "total_win": total_win,
            "total_loss": total_loss,
            "win_rate_percent": round(win_rate_fraction * 100.0, 2),
            "volume_usd": round(volume_usd, 2),
            "total_invested_usd": round(invested, 2),
            "total_sold_usd": round(sold, 2),
            "current_value_usd": round(current_value, 2),
            "realized_pnl_usd": round(realized_usd, 2),
            "unrealized_pnl_usd": round(unrealized_usd, 2),
            "total_pnl_usd": round(total_pnl_usd, 2),
            "avg_profit_per_trade_usd": round(avg_profit_per_trade, 2),
            "realized_pnl_percent": round(realized_pct * 100.0, 2),
            "realized_pnl_90d_usd": round(realized_usd_90d, 2) if realized_usd_90d is not None else None,
            "realized_pnl_24h_usd": round(realized_usd_24h, 2) if realized_usd_24h is not None else None,
            "previous_60d_pnl_usd": round(pnl_previous_60d, 2) if pnl_previous_60d is not None else None,
            "trend_score": round(trend_score, 2),
            "trend_status": trend_status,
            "data_confidence": data_confidence,
            "benchmark_realized_pnl_usd": 0.0,
            "leaderboard_rank": 0,
            "leaderboard_size": 0,
            # --- Deep-loss tokens (renamed from "rug") ---
            "deep_loss_token_count": deep_loss_count,
            "deep_loss_token_scanned": token_count_in_scan,
            "deep_loss_fraction": round(deep_loss_fraction, 6),
            "deep_loss_percent": round(deep_loss_fraction * 100.0, 2),
            "deep_loss_penalty_pts": deep_loss_penalty_pts,
            # Loss tier breakdown (by total_percent)
            "loss_critical_count": loss_critical_count,   # ≥90% loss
            "loss_severe_count": loss_severe_count,       # ≥75% loss
            "loss_moderate_count": loss_moderate_count,   # ≥50% loss
            # Cash-out classification of loss tokens
            "bag_hold_loss_count": bag_hold_loss_count,       # realized <= 0 (bad — holding losing bag)
            "smart_exit_loss_count": smart_exit_loss_count,   # realized > 0  (good — already cashed out)
            "bag_hold_loss_fraction": round(bag_hold_loss_fraction, 6),
            # Backward-compat aliases (rug_* → deep_loss_*)
            "rug_token_count": rug_count,
            "rug_token_scanned": token_count_in_scan,
            "rug_fraction": round(rug_fraction, 6),
            "rug_percent": round(rug_fraction * 100.0, 2),
            "rug_penalty_pts": rug_penalty_pts,
            "profit_concentration": round(profit_concentration, 4),
            "diversification": round(diversification, 4),
            "realization_score": round(realization_score, 2),
            "severe_loss_fraction": round(severe_loss_fraction, 4),
            "severe_loss_positions": severe_loss_positions,
            "closed_positions": closed_positions,
            "profitable_positions": profitable_positions,
            "unrealized_penalty_factor": round(unrealized_penalty_factor, 4),
            "bot_penalty": round(bot_penalty, 4),
        },
        "components": components_struct,
        "formula_doc": formula_doc_struct,
        "step_checks": step_checks_extended,
    "alpha_score": alpha_score,
    "tier": {
        "name": tier_name,
        "emoji": tier_emoji,
        "color_hex": tier_color,
    },
    "copy_score": copy_score,
    "copy_tier": {
        "name": copy_tier[0],
        "emoji": copy_tier[1],
        "color_hex": copy_tier[2],
    },
    "copy_components": {
        "entry": {"score": round(copy_entry_f * 100, 1), "weight": 0.22, "value": round(entry_under_100k_est, 4), "label": "Entry under $100k mcap"},
        "profit": {"score": round(copy_profit_f * 100, 1), "weight": 0.22, "value": round(avg_trade_usd, 2), "label": "Profit per trade (USD)"},
        "hold": {"score": round(copy_hold_f * 100, 1), "weight": 0.20, "value": _wsf_human_seconds(avg_hold_s_est), "label": "Avg hold time"},
        "feasible": {"score": round(copy_feasible_f * 100, 1), "weight": 0.18, "value": total_trade, "label": "Feasibility (total trades)"},
        "edge": {"score": round(copy_edge_f * 100, 1), "weight": 0.18, "value": round(0.6 * entry_under_100k_est + 0.6 * fast_flip_rate_est, 4), "label": "Edge (low competition)"},
    },
    "copy_formula": copy_formula,
    "copy_note": copy_note or None,
    "hard": {
        "all_pass": all_hard_pass,
        "tx_pass": hard_tx_pass,
        "volume_pass": hard_vol_pass,
        "deep_loss_pass": hard_deep_loss_pass,
        "reasons": hard_fail_reasons,
        "penalty_applied": False,
        "penalty_factor": 1.00,
        "note": "Hard filters are informational only; no alpha multiplier. Deep-loss (bag-hold) is penalized inside Quality.",
    },
    "wallet_info": {
        "wallet_created_ts_unix": wallet_created_ts,
        "wallet_created_block": wallet_created_block,
        "wallet_age_days": wallet_age_days,
        "first_tx_hash_prefix": first_sender,
        "current_net_worth_usd": round(current_net_worth, 2) if isinstance(current_net_worth, (int, float)) else None,
        "portfolio_token_count": portfolio_count,
    },
}


def _ws_format_plain(result, wallet, chain, duration, cu, run_id_str, cached_flag=False):
    tier = result["tier"]
    metrics = result["metrics"]
    comps = result["components"]
    alpha = result["alpha_score"]
    copy_score = result.get("copy_score", 0)
    copy_tier = result.get("copy_tier", {})
    out = []
    sep = "─" * 82
    out.append("")
    out.append("╔" + sep + "╗")
    out.append(f"║  🧠 WALLET SCORE  ·  chain={chain.upper():<8s}  duration={duration:<5s}              ║")
    out.append("╠" + sep + "╣")
    out.append(f"║  Wallet : {wallet[:62]:<62s}  run_id={run_id_str[:10]} ║")
    cache_tag = "  💾 CACHED · 0 CU replay" if cached_flag else f"  ⚡ CU {_ws_total_cu(cu):,}"
    out.append(f"║  ALPHA  : {alpha:>6.2f}/100  {tier['emoji']} {tier['name']:<7s}  4: P{comps['profitability']['score']:.0f}/C{comps['consistency']['score']:.0f}/Q{comps['quality']['score']:.0f}/A{comps['activity']['score']:.0f}{cache_tag}  ║")
    out.append(f"║  COPY   : {copy_score:>6.2f}/100  {copy_tier.get('emoji','')} {copy_tier.get('name',''):<20s} (copy-tradeability)   ║")
    out.append("╠" + sep + "╣")
    out.append("║  📋 STEP CHECKLIST                                                                    ║")
    for s in result["step_checks"]:
        mark = "✅" if s["pass"] else "❌"
        note = s["note"]
        if len(note) > 76:
            note = note[:73] + "..."
        out.append(f"║   {mark} {note:<76s} ║")
    out.append("╠" + sep + "╣")
    out.append("║  📊 METRICS                                                                            ║")
    def mrow(k, v):
        return f"║   · {k:<26s}: {str(v):>51s} ║"
    out.append(mrow("Total PnL USD", f"{metrics['total_pnl_usd']:+,.2f} $"))
    out.append(mrow("Realized PnL USD", f"{metrics['realized_pnl_usd']:+,.2f} $"))
    out.append(mrow("Unrealized PnL USD", f"{metrics['unrealized_pnl_usd']:+,.2f} $"))
    out.append(mrow("Volume USD (max buy/sell)", f"{metrics['volume_usd']:,.2f} $"))
    out.append(mrow("Win Rate", f"{metrics['win_rate_percent']:.2f} %"))
    out.append(mrow("Total trades (buy+sell)", f"{metrics['total_trade']:,}"))
    out.append(mrow("Unique tokens traded", f"{metrics['unique_tokens']:,}"))
    wi = result["wallet_info"]
    if wi.get("wallet_age_days") is not None:
        out.append(mrow("Wallet age (first funding)", f"{wi['wallet_age_days']:,d} days"))
    if wi.get("current_net_worth_usd") is not None:
        out.append(mrow("Current Net Worth USD", f"{wi['current_net_worth_usd']:,.2f} $"))
    out.append("╠" + sep + "╣")
    out.append("║  🧮 4 COMPONENT BREAKDOWN × weights 35/35/20/10 → Σ=100%                              ║")
    out.append("║  (formulas: P=fixed-ROI(clamp((min(rROI,tROI)+5%)/35%))×keep  C=wr+trend+dist+sample  Q=realiz+dist+loss−deep  A=vol+tx·bot)║")
    for cname in ["profitability","consistency","quality","activity"]:
        cval = comps[cname]
        raw_txt = ""
        if cname == "profitability":
            raw_txt = f"raw=${cval['raw_usd']:+,.2f}"
        else:
            raw_txt = f"raw={cval['raw']}"
        fshort = cval.get("formula") or ""
        if len(fshort) > 42: fshort = fshort[:39] + "..."
        out.append(f"║   · {cname.upper():<14s} ×{cval['weight']*100:>2.0f}% : {cval['score']:>6.2f}/100 · {raw_txt:<42s} ║")
        out.append(f"║          {fshort:<76s} ║")
    fd = result.get("formula_doc") or {}
    final_eq = fd.get("final_equation_line") or ""
    if final_eq:
        lines = final_eq.split(chr(10))
        out.append("╠" + sep + "╣")
        out.append("║  🧮 FINAL ALPHA EQUATION                                                            ║")
        for ln in lines:
            ln_cut = ln[:76]
            out.append(f"║   {ln_cut:<76s} ║")
    out.append("╚" + sep + "╝")
    out.append("")
    out.append(f"⚡ CU: {_ws_total_cu(cu):,}  breakdown: " + ", ".join(f"{k}={v}" for k, v in (cu or {}).items()) + "  | weights: " + "/".join(f"{k.upper()}{int(v*100)}" for k, v in _WS_WEIGHTS.items()))
    out.append("")
    return "\n".join(out)


def _ws_format_telegram(result, wallet, chain, duration, cu):
    tier = result["tier"]
    metrics = result["metrics"]
    comps = result["components"]
    alpha = result["alpha_score"]
    copy_score = result.get("copy_score", 0)
    copy_tier = result.get("copy_tier", {})
    hard_fail = result["hard"]["reasons"]
    lines = []
    lines.append(f"{tier['emoji']} <b>Wallet Alpha v3.2</b> · <b>{alpha:.1f}/100</b> · {tier['name']}")
    lines.append(f"🔗 {chain.upper()} · ⏱ {duration}")
    w_short = wallet[:8] + "…" + wallet[-6:] if len(wallet) > 20 else wallet
    lines.append(f"👛 <code>{w_short}</code>")
    lines.append(f"📋 <b>Copy-tradeability</b>: <b>{copy_score:.1f}/100</b> {copy_tier.get('emoji','')} {copy_tier.get('name','')}")
    lines.append("")
    lines.append(f"💰 <b>PnL</b>: {metrics['total_pnl_usd']:+,.0f}$ | R {metrics['realized_pnl_usd']:+,.0f}$ · U {metrics['unrealized_pnl_usd']:+,.0f}$")
    lines.append(f"📊 <b>WR</b> {metrics['win_rate_percent']:.1f}% · <b>TX</b> {metrics['total_trade']:,} · <b>Vol</b> {metrics['volume_usd']:,.0f}$")
    wi = result["wallet_info"]
    if wi.get("wallet_age_days") is not None:
        lines.append(f"🗓 Age: {wi['wallet_age_days']}d · NW: {wi.get('current_net_worth_usd') or 0:,.0f}$")
    lines.append("")
    lines.append("<b>Components (P35·C35·Q20·A10)</b>")
    lines.append(f"  P {comps['profitability']['score']:.0f} · C {comps['consistency']['score']:.0f} · Q {comps['quality']['score']:.0f} · A {comps['activity']['score']:.0f}")
    for cn, short in [("profitability","P"),("consistency","C"),("quality","Q"),("activity","A")]:
        fshort = (comps[cn].get("formula") or "")
        if len(fshort) > 60: fshort = fshort[:57] + "..."
        lines.append(f"  {short}· <i>{fshort}</i>")
    lines.append("")
    if hard_fail:
        lines.append("⚠️  <b>Hard fail</b>: " + " | ".join(hard_fail)[:200])
    fd = result.get("formula_doc") or {}
    eq = (fd.get("final_equation_line") or "").split(chr(10))[0]
    if eq:
        if len(eq) > 120: eq = eq[:117] + "..."
        lines.append(f"🧮 <code>{eq}</code>")
    lines.append("")
    lines.append(f"⚡ CU {_ws_total_cu(cu):,}")
    full = "\n".join(lines)
    if len(full) > 4090:
        full = full[:4050] + "\n…truncated."
    return full


def _ws_format_rendered_html(result, wallet, chain, duration, params_raw, cu, run_id_str, cached_flag=False):
    import html as _html_mod
    esc = lambda s: _html_mod.escape("" if s is None else str(s), quote=True)
    tier = result["tier"]
    metrics = result["metrics"]
    comps = result["components"]
    alpha = result["alpha_score"]
    copy_score = result.get("copy_score", 0)
    copy_tier = result.get("copy_tier", {})
    copy_comps = result.get("copy_components") or {}
    copy_note = result.get("copy_note") or ""
    wi = result["wallet_info"]
    fdoc = result.get("formula_doc") or {}
    steps = result["step_checks"] or []

    # Hero gauge (half-circle 0..100 using SVG arc — reliable fill percentage)
    color = tier["color_hex"]
    alpha_pct = max(0.0, min(100.0, float(alpha)))
    # SVG half-arc: center (110,110), radius 90, start angle 180°, end 0° (semicircle top)
    cx, cy, r = 110, 110, 90
    import math as _math
    def _arc_point(angle_deg):
        a = _math.radians(angle_deg)
        return (cx + r * _math.cos(a), cy - r * _math.sin(a))
    # Arc from 180° (left) to 0° (right), sweeping clockwise (top half)
    x1, y1 = _arc_point(180)
    x2, y2 = _arc_point(0)
    # Fill angle: 180° down to (180 - alpha_pct*1.8). Sweep is always <= 180°,
    # so large-arc-flag must be 0 (else SVG wraps around the bottom).
    fill_end_angle = 180.0 - (alpha_pct / 100.0) * 180.0
    xf, yf = _arc_point(fill_end_angle)
    # Use round caps only when there's meaningful arc length (avoid glitch near 0)
    cap = "round" if alpha_pct > 3 else "butt"
    gauge_svg = f'''<svg viewBox="0 0 220 120" width="220" height="120" style="display:block">
  <path d="M {x1:.2f} {y1:.2f} A {r} {r} 0 0 1 {x2:.2f} {y2:.2f}"
        fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="14" stroke-linecap="round"/>
  <path d="M {x1:.2f} {y1:.2f} A {r} {r} 0 0 1 {xf:.2f} {yf:.2f}"
        fill="none" stroke="{color}" stroke-width="14" stroke-linecap="{cap}"/>
  <text x="110" y="92" text-anchor="middle" font-size="34" font-weight="900" fill="{color}" font-family="-apple-system,Segoe UI,Roboto,sans-serif">{alpha:.0f}<tspan font-size="14" fill="#8fa3c2" font-weight="700">/100</tspan></text>
  <text x="110" y="110" text-anchor="middle" font-size="10" fill="#8fa3c2" font-family="-apple-system,Segoe UI,Roboto,sans-serif" letter-spacing="1">ALPHA SCORE</text>
</svg>'''

    comp_cards_html = []
    order = ["profitability", "consistency", "quality", "activity"]
    # High-level concept tooltips (hover) — no raw formula
    _CONCEPT = {
        "profitability": "How much realized profit the wallet generates vs market. Rewards absolute profit size; penalized if unrealized loss is large relative to realized.",
        "consistency":   "How steady the returns are. Combines win rate, 30d vs prev-60d trend, trade distribution balance, and sample-size confidence.",
        "quality":       "How well-executed the trades are. Rewards profit realization and diversification; penalizes concentrated bags and bag-holding deep losses.",
        "activity":      "How actively the wallet trades. Based on volume and trade count; applies a bot-penalty floor for mechanical patterns.",
    }
    for cname in order:
        c = comps[cname]
        w_pct = int(c["weight"] * 100)
        score = c["score"]
        if cname == "profitability":
            raw_txt = f"${c['raw_usd']:+,.2f}"
        else:
            raw_txt = f"{c['raw']}"
        formula_short_txt = c.get("formula") or ""
        formula_doc_txt = c.get("formula_doc") or formula_short_txt
        pct = _ws_clamp(score, 0, 100)
        card_color = (
            "#22d3ee" if pct >= 95 else
            ("#22c55e" if pct >= 80 else
            ("#facc15" if pct >= 65 else
            ("#fb923c" if pct >= 50 else
            ("#f87171" if pct >= 30 else "#dc2626"))))
        )
        comp_cards_html.append(f"""
  <div class="ttip" data-tip="{esc(_CONCEPT.get(cname, ''))}" title="{esc(_CONCEPT.get(cname, ''))}" style="flex:1 1 0;min-width:180px;margin:6px 6px;padding:12px 14px;border-radius:12px;
       background:linear-gradient(180deg,#0f1a30 0%,#0b1326 100%);border:1px solid #263a5e;cursor:help">
    <div style="display:flex;align-items:baseline;justify-content:space-between;gap:6px;margin-bottom:6px">
      <span style="font-size:11px;font-weight:800;letter-spacing:.6px;color:#9cb4d8;text-transform:uppercase">{esc(cname.upper())} ×{w_pct}%</span>
      <span style="font-size:20px;font-weight:900;color:#f3f6fc">{score:.1f}<span style="font-size:11px;color:#6f86a7;margin-left:2px">/100</span></span>
    </div>
    <div style="height:6px;border-radius:999px;background:rgba(255,255,255,.05);overflow:hidden;margin-bottom:7px">
      <div style="height:100%;width:{pct:.1f}%;background:{card_color};border-radius:999px"></div>
    </div>
    <div style="display:flex;justify-content:space-between;gap:4px">
      <span style="font-size:10.5px;color:#8fa3c2">raw value</span>
      <span style="font-size:11.5px;font-weight:700;color:#e6edf8;font-family:monospace">{esc(raw_txt)}</span>
    </div>
  </div>""")

    step_html_parts = []
    for s in steps:
        mark = "✅" if s["pass"] else "❌"
        border_clr = "#166534" if s["pass"] else "#991b1b"
        bg_clr = "#072417" if s["pass"] else "#2a0c0c"
        tx_clr = "#86efac" if s["pass"] else "#fca5a5"
        is_equation_row = (s.get("id") or "").startswith("S6_")
        if is_equation_row:
            border_clr = "#4338ca"; bg_clr = "#0d0f2e"; tx_clr = "#c7d2fe"; mark = "🧮"
        note_pre = (
            f'<pre style="margin:3px 0 0;padding:5px 7px;border-radius:6px;background:#050c1c;'
            f'border:1px solid #1f3257;color:#e0e7ff;font-size:10.5px;font-family:monospace;'
            f'white-space:pre-wrap;word-break:break-word;line-height:1.55">{esc(s["note"])}</pre>'
            if is_equation_row else f'<div style="font-size:10.5px;color:#b8c0cc;margin-top:2px;line-height:1.5">{esc(s["note"])}</div>'
        )
        step_html_parts.append(f"""
      <div style="margin:5px 0;padding:7px 10px;border:1px solid {border_clr};border-radius:9px;background:{bg_clr}">
        <div style="display:flex;align-items:flex-start;gap:7px">
          <span style="font-size:13px">{mark}</span>
          <div style="flex:1 1 auto;min-width:0">
            <div style="font-size:11.5px;font-weight:800;color:{tx_clr};letter-spacing:.2px">{esc(s['name'])}</div>
            {note_pre}
          </div>
        </div>
      </div>""")

    # ════════════════════════ FORMULA DOC PANEL ════════════════════════
    hard_rows = []
    for hf in (fdoc.get("hard_filters") or []):
        ok = (
            ("≥ " in hf and any(hf.endswith(f")") and f"{n}" in hf and (
                (n == "tx_count" and metrics.get("total_trade", 0) >= 20) or
                False
            ) for n in ["tx_count"]))
            or False
        )
        # Exact pass/fail using pattern: "KEY ≥ THRESHOLD (current: VAL)"
        ok_icon = "✅"
        try:
            hdr = hf.strip()
            import re as _re
            m = _re.search(r"current:\s*([\-0-9\.\,\$\%]+)", hdr)
            if m:
                cur_raw = m.group(1).replace(",","").replace("$","").replace("%","")
                cur = float(cur_raw)
                if "MIN_TX" in hdr:
                    ok_icon = "✅" if cur >= 20 else "❌"
                elif "MIN_VOLUME" in hdr:
                    ok_icon = "✅" if cur >= 5000 else "❌"
                elif "MAX_DEEP_LOSS" in hdr:
                    ok_icon = "✅" if cur <= 50 else "❌"
        except Exception:
            pass
        hard_rows.append(f"""<div style="display:flex;align-items:center;gap:6px;padding:2px 0">
  <span style="font-size:11px">{ok_icon}</span>
  <span style="flex:1;font-size:11px;color:#d6e0f5;font-family:monospace">{esc(hf)}</span>
</div>""")

    weights = fdoc.get("weights") or dict(_WS_WEIGHTS)
    w_str = " + ".join(f"<b>{k.upper()}</b>×{weights.get(k, _WS_WEIGHTS.get(k,0)):.2f}" for k in ["profitability","consistency","quality","activity"])
    baselines = fdoc.get("anchors") or fdoc.get("baselines") or {}
    tier_lines = "".join(
        f'<div style="padding:1px 0;font-size:11px;color:#d6e0f5;font-family:monospace">{esc(tl)}</div>'
        for tl in (fdoc.get("tiers") or [])
    )
    bl_lines = "".join(
        f'<div style="padding:2px 0;font-size:10.5px;color:#c8d6f5">'
        f'<span style="font-weight:800;color:#a9c3ee;text-transform:uppercase;letter-spacing:.4px">{bn.upper()}</span>: '
        f'<span style="font-family:monospace">{esc(bv)}</span></div>'
        for bn, bv in baselines.items()
    )

    formula_doc_panel = f"""
  <div style="margin-top:12px;padding:12px 14px;border:1px solid #3c4d6c;border-radius:13px;background:linear-gradient(180deg,#0c1630 0%,#080f20 100%);position:relative">
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:6px;flex-wrap:wrap">
      <div>
        <div style="font-size:10px;color:#6f86a7;font-weight:800;letter-spacing:1px">REFERENCE · HOW ALPHA IS COMPUTED</div>
        <div style="font-size:12.5px;font-weight:900;color:#e6edf8;margin-top:2px">
          {esc(fdoc.get("title") or "Wallet Score")}
        </div>
      </div>
      <div style="text-align:right">
        <div style="font-size:10.5px;color:#8fa3c2">Final alpha = weighted sum {w_str} <span style="color:#9bb7d6">(hard filters informational — no alpha ×0.5)</span></div>
        <div style="font-size:10.5px;color:#6f86a7;margin-top:2px;font-family:monospace;word-break:break-word">
          {esc(fdoc.get("final_equation_line") or "")}
        </div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px 14px;margin:4px 0 8px">
      <div style="grid-column:span 1;padding:8px 10px;border-radius:9px;border:1px solid #2b426a;background:#0a1429">
        <div style="font-size:10px;color:#8fa3c2;font-weight:800;letter-spacing:.5px;margin-bottom:4px">① HARD FILTERS (pre-gate)</div>
        {''.join(hard_rows)}
      </div>
      <div style="grid-column:span 1;padding:8px 10px;border-radius:9px;border:1px solid #2b426a;background:#0a1429">
        <div style="font-size:10px;color:#8fa3c2;font-weight:800;letter-spacing:.5px;margin-bottom:4px">② WEIGHTS</div>
        <div style="font-size:11.5px;color:#c7d2fe;font-family:monospace;padding:2px 0"><b>PROFIT</b> × {weights.get("profitability",0):.2f} &nbsp;&nbsp;(<b>35%</b>)</div>
        <div style="font-size:11.5px;color:#c7d2fe;font-family:monospace;padding:2px 0"><b>CONSIS</b> × {weights.get("consistency",0):.2f} &nbsp;&nbsp;(<b>35%</b>)</div>
        <div style="font-size:11.5px;color:#c7d2fe;font-family:monospace;padding:2px 0"><b>QUALITY</b> × {weights.get("quality",0):.2f} &nbsp;&nbsp;(<b>20%</b>)</div>
        <div style="font-size:11.5px;color:#c7d2fe;font-family:monospace;padding:2px 0"><b>ACTIV</b> × {weights.get("activity",0):.2f} &nbsp;&nbsp;(<b>10%</b>)</div>
        <div style="margin-top:4px;padding-top:4px;border-top:1px dashed #23406e;font-size:10.5px;color:#9bb7d6">ℹ hard filters (tx/vol/rug) = informational only · rug penalized inside Quality · no alpha multiplier</div>
      </div>
      <div style="grid-column:span 1;padding:8px 10px;border-radius:9px;border:1px solid #2b426a;background:#0a1429">
        <div style="font-size:10px;color:#8fa3c2;font-weight:800;letter-spacing:.5px;margin-bottom:4px">③ SCORING ANCHORS (fixed ROI + linear clamp)</div>
        {bl_lines}
      </div>
      <div style="grid-column:span 1;padding:8px 10px;border-radius:9px;border:1px solid #2b426a;background:#0a1429">
        <div style="font-size:10px;color:#8fa3c2;font-weight:800;letter-spacing:.5px;margin-bottom:4px">④ TIER THRESHOLDS</div>
        {tier_lines}
        <div style="margin-top:4px;padding-top:4px;border-top:1px dashed #23406e;font-size:10px;color:#8fa3c2">
          optimal_tx · <span style="font-family:monospace">{esc(str(fdoc.get("optimal_tx_count") or _WS_V3["OPTIMAL_TX_COUNT"]))}</span> · bot_penalty floor <span style="font-family:monospace">{1.0 - _WS_V3["MAX_BOT_PENALTY"]:.2f}</span>
        </div>
      </div>
    </div>
    <details style="margin-top:4px">
      <summary style="font-size:10.5px;color:#7fb3ff;cursor:pointer;font-weight:700;user-select:none">ℹ️ Methodology note · single-wallet vs leaderboard percentile</summary>
      <div style="margin:5px 0 0;padding:7px 10px;border-radius:8px;background:#050c1c;border:1px solid #1f3257;color:#9eb4da;font-size:11px;line-height:1.55">
        {esc(fdoc.get("methodology_note") or "")}
      </div>
    </details>
  </div>"""

    w_short = wallet[:10] + "…" + wallet[-8:] if len(wallet) > 22 else wallet
    cache_badge = ""
    if cached_flag:
        orig_cu = cu.get("original_api_cu") or _ws_total_cu(cu)
        cache_badge = f"""<span style="display:inline-block;margin-left:6px;padding:2px 8px;border-radius:999px;
           background:#0f2a2a;border:1px solid #1d5a5a;color:#7ce3e3;font-size:10.5px;font-weight:700">
           💾 Cached run · Original API cost ⚡{int(orig_cu)} CU · Re-render = 0 CU</span>"""
    else:
        tcu = _ws_total_cu(cu)
        cache_badge = f"""<span style="display:inline-block;margin-left:6px;padding:2px 8px;border-radius:999px;
           background:#3a2a0f;border:1px solid #6b4a1a;color:#ffd57e;font-size:10.5px;font-weight:700">
           ⚡ {tcu} CU</span>"""

    steps_title_clr = "#f3f6fc"

    # ════════════════════════ WALLET STYLE BADGE ════════════════════════
    style_badge_html = ""
    ws = result.get("wallet_style")
    if isinstance(ws, dict):
        mt = ws.get("main_title") or {}
        if mt:
            s_emoji = mt.get("emoji") or "🎭"
            s_name = mt.get("en") or "Style"
            s_meaning = mt.get("meaning") or ""
            tooltip = f"{s_name} · {s_meaning}" if s_meaning else s_name
            style_badge_html = f'''<span class="ttip" data-tip="{esc(tooltip)}" title="{esc(tooltip)}" style="display:inline-flex;align-items:center;gap:5px;margin-left:8px;padding:4px 12px;border-radius:999px;
  background:linear-gradient(135deg,#7c3aed 0%,#2563eb 100%);border:1px solid #a78bfa;color:#fff;font-size:12px;font-weight:800;letter-spacing:.3px;
  cursor:help;box-shadow:0 0 12px rgba(124,58,237,.35);vertical-align:middle">
  <span style="font-size:14px">{s_emoji}</span>
  <span>{esc(s_name)}</span>
</span>'''

    # ════════════════════════ COPY-TRADEABILITY COMPONENTS ════════════════════════
    copy_comps_html = ""
    # High-level concepts for copy-tradeability components
    _CC_CONCEPT = {
        "entry":      "Whether the wallet's average entry market cap is small enough (under ~$100k) to be replicable for retail.",
        "profit":     "Average profit per trade in USD — higher = more meaningful edge to copy.",
        "hold":       "Average holding time — too short (scalping) or too long (bag-hold) reduces copyability.",
        "feasible":   "Whether the wallet has enough trades to be statistically copyable (sample feasibility).",
        "edge":       "Low competition score — fewer people copy = more edge available.",
    }
    if copy_comps:
        cc_cards = []
        cc_order = ["entry", "profit", "hold", "feasible", "edge"]
        cc_colors = ["#22d3ee", "#22c55e", "#a78bfa", "#f59e0b", "#fb7185"]
        for i, cname in enumerate(cc_order):
            c = copy_comps.get(cname) or {}
            if not c:
                continue
            sc = c.get("score", 0)
            w = c.get("weight", 0)
            val = c.get("value", "")
            label = c.get("label", cname)
            col = cc_colors[i % len(cc_colors)]
            bar_w = max(2, int(sc))
            cc_cards.append(f"""
      <div class="ttip" data-tip="{esc(_CC_CONCEPT.get(cname, ''))}" title="{esc(_CC_CONCEPT.get(cname, ''))}" style="flex:1 1 160px;min-width:150px;padding:10px 12px;border-radius:10px;border:1px solid #2b436d;background:#0b1326;cursor:help">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
          <span style="font-size:11px;font-weight:700;color:#9cb4d8;text-transform:uppercase;letter-spacing:.4px">{esc(cname)}</span>
          <span style="font-size:10.5px;color:#6f86a7">×{int(w*100)}%</span>
        </div>
        <div style="display:flex;align-items:baseline;gap:4px">
          <span style="font-size:20px;font-weight:900;color:{col}">{sc:.0f}</span>
          <span style="font-size:10px;color:#6f86a7">/100</span>
        </div>
        <div style="height:4px;border-radius:2px;background:#1a2744;overflow:hidden;margin-top:4px">
          <div style="height:100%;width:{bar_w}%;background:{col};border-radius:2px"></div>
        </div>
        <div style="font-size:10px;color:#8fa3c2;margin-top:4px">{esc(label)}: <b style="color:#c7d2fe">{esc(str(val))}</b></div>
      </div>""")
        if cc_cards:
            copy_comps_html = f"""
  <div style="margin-top:10px;padding:4px 2px">
    <div style="font-size:11px;font-weight:800;color:#9cb4d8;letter-spacing:.4px;margin:4px 6px 2px">🔗 COPY-TRADEABILITY · 5 COMPONENTS × WEIGHTS 22/22/20/18/18 · hover for concept</div>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:6px">{"".join(cc_cards)}</div>
  </div>"""
    elif copy_score is not None:
        # Cached run without sub-component breakdown
        copy_comps_html = f"""
  <div style="margin-top:10px;padding:4px 2px">
    <div style="font-size:11px;font-weight:800;color:#9cb4d8;letter-spacing:.4px;margin:4px 6px 2px">🔗 COPY-TRADEABILITY · 5 COMPONENTS × WEIGHTS 22/22/20/18/18 · hover for concept</div>
    <div style="font-size:11px;color:#8fa3c2;margin:6px">Component breakdown not available in cached view — re-run live to see entry/profit/hold/feasible/edge scores.</div>
  </div>"""

    header = f"""
<div class="render-wallet-score" style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
  color:#e6edf8;background:transparent">
  <div style="padding:14px 16px;border:1px solid #263a5e;border-radius:14px;background:linear-gradient(180deg,#0d1728 0%,#0a1220 100%);position:sticky;top:0;z-index:30">
    <div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px">
      <div>
        <span style="font-size:10.5px;font-weight:700;letter-spacing:.8px;color:#6f86a7">SKILL #13 · WALLET SCORE</span>
        <div style="font-size:16px;font-weight:900;color:#f3f6fc;line-height:1.25;margin-top:2px">
          🧠 {tier['emoji']} {alpha:.1f} · <span style="color:{color}">{tier['name']}</span>
          {style_badge_html}
          <span class="copy-addr" data-copy-addr="{esc(wallet)}" style="font-weight:500;color:#9cb4d8;margin-left:8px;font-size:13px;cursor:pointer;user-select:none" title="Click to copy full wallet address">@{esc(w_short)} 📋</span>
        </div>
      </div>
      <div style="display:flex;flex-wrap:wrap;align-items:center;gap:6px">
        <span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#132038;border:1px solid #2b436d;color:#90b0dc;font-size:10.5px;font-weight:700;text-transform:uppercase">🔗 {esc(chain)}</span>
        <span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#1e2b1f;border:1px solid #375a3a;color:#8be0a0;font-size:10.5px;font-weight:700;text-transform:uppercase">⏱ {esc(duration)}</span>
        {cache_badge}
      </div>
    </div>
    <div style="display:flex;flex-wrap:wrap;align-items:flex-end;gap:18px;margin-top:6px">
      <div style="flex:0 0 auto;width:220px;height:120px;position:relative">
        {gauge_svg}
      </div>
      <div style="flex:0 0 auto;align-self:flex-end;padding:10px 16px;border-radius:12px;border:1px solid #2b436d;background:linear-gradient(180deg,#0f1a30 0%,#0b1326 100%);min-width:170px">
        <div style="font-size:10px;color:#6f86a7;font-weight:800;letter-spacing:.6px">COPY-TRADEABILITY</div>
        <div style="font-size:30px;font-weight:900;color:{copy_tier.get('color_hex','#c7d2fe')};line-height:1.1;margin-top:3px">{copy_score:.0f}<span style="font-size:13px;color:#8fa3c2;font-weight:700">/100</span></div>
        <div style="font-size:11.5px;font-weight:700;color:{copy_tier.get('color_hex','#c7d2fe')};margin-top:3px">{copy_tier.get('emoji','')} {esc(copy_tier.get('name',''))}</div>
      </div>
      <div style="flex:1 1 auto;min-width:240px">
        <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px 14px">
          <div><div style="font-size:10px;color:#8fa3c2">Total PnL</div><div style="font-size:14.5px;font-weight:800;color:#f3f6fc">{metrics['total_pnl_usd']:+,.0f}$</div></div>
          <div><div style="font-size:10px;color:#8fa3c2">Realized</div><div style="font-size:14.5px;font-weight:800;color:#c7f7bd">{metrics['realized_pnl_usd']:+,.0f}$</div></div>
          <div><div style="font-size:10px;color:#8fa3c2">Unrealized</div><div style="font-size:14.5px;font-weight:800;color:#f3f6fc">{metrics['unrealized_pnl_usd']:+,.0f}$</div></div>
          <div><div style="font-size:10px;color:#8fa3c2">Win Rate</div><div style="font-size:14.5px;font-weight:800;color:#eadcff">{metrics['win_rate_percent']:.1f}%</div></div>
          <div><div style="font-size:10px;color:#8fa3c2">Trades</div><div style="font-size:14.5px;font-weight:800;color:#ffd5d8">{metrics['total_trade']:,}</div></div>
          <div><div style="font-size:10px;color:#8fa3c2">Volume</div><div style="font-size:14.5px;font-weight:800;color:#a7c4ee">{metrics['volume_usd']:,.0f}$</div></div>
          <div><div style="font-size:10px;color:#8fa3c2">Wallet age</div><div style="font-size:14.5px;font-weight:800;color:#dcfcfc">{(str(wi.get('wallet_age_days'))+'d') if wi.get('wallet_age_days') is not None else 'N/A'}</div></div>
          <div><div style="font-size:10px;color:#8fa3c2">Net Worth</div><div style="font-size:14.5px;font-weight:800;color:#f3f6fc">{(f"{wi.get('current_net_worth_usd'):,.0f}$") if isinstance(wi.get('current_net_worth_usd'), (int,float)) and wi.get('current_net_worth_usd') else 'N/A'}</div></div>
          <div><div style="font-size:10px;color:#8fa3c2">Deep-loss (bag-hold)</div><div style="font-size:14.5px;font-weight:800;color:#ff9bb0">{metrics['deep_loss_token_count']}/{metrics['deep_loss_token_scanned'] or metrics['unique_tokens']} · bh={metrics['bag_hold_loss_count']}</div></div>
        </div>
      </div>
    </div>
  </div>
  <div style="margin-top:10px;padding:4px 2px">
    <div style="font-size:11px;font-weight:800;color:#9cb4d8;letter-spacing:.4px;margin:4px 6px 2px">🧮 4 COMPONENTS × WEIGHTS 35/35/20/10 · hover for concept</div>
    <div style="display:flex;flex-wrap:wrap;margin:-6px">{"".join(comp_cards_html)}</div>
  </div>
  {copy_comps_html}
  {(f'<div style="margin-top:8px;padding:8px 12px;border-radius:10px;border:1px solid #7a5a1c;background:#2a1f08;font-size:11.5px;color:#f5c57a;font-weight:600">⚠️ {esc(copy_note)}</div>') if copy_note else ''}
  {formula_doc_panel}
  <div style="margin-top:10px;padding:10px 12px;border:1px dashed #3c4d6c;border-radius:12px;background:#0a1220">
    <div style="font-size:11.5px;font-weight:800;color:{steps_title_clr};letter-spacing:.3px;margin-bottom:4px">📋 STEP CHECKLIST · {len(steps)} rows · gate → components → equation</div>
    {''.join(step_html_parts)}
  </div>
</div>
"""
    return header


def cmd_wallet_score(args):
    chain_short = args.chain
    chain_full = CHAINS.get(chain_short, chain_short)
    wallet = args.wallet.strip()
    duration = args.duration
    pnl_method = args.pnl_method
    fmt = args.format
    nocache = bool(getattr(args, "nocache", False))
    cdir_arg = getattr(args, "cache_dir", None)
    write_cache = bool(getattr(args, "write_cache", True))
    from_cache_runid = getattr(args, "from_cache", None)
    skip_rug = bool(args.skip_rug)
    skip_portfolio = bool(args.skip_portfolio)
    skip_first_tx = bool(args.skip_first_tx)
    include_str = getattr(args, "include", None)

    # --- Include-based compact API ---
    # Parse --include blocks and auto-add dependencies.
    _ALL_BLOCKS = {"pnl", "pnl_24h", "pnl_90d", "tokens", "wallet", "portfolio", "leaderboard", "score"}
    includes = set()
    if include_str:
        includes = {b.strip().lower() for b in include_str.split(",") if b.strip()}
        # Auto-add dependencies for 'score'
        if "score" in includes:
            includes |= {"pnl", "pnl_90d", "tokens", "leaderboard"}
        # Validate
        bad = includes - _ALL_BLOCKS
        if bad:
            sys.stderr.write(f"[wallet-score] unknown include blocks: {bad}. Valid: {sorted(_ALL_BLOCKS)}\n")
            return 5
        # Force compact format when --include is used
        if fmt != "compact":
            fmt = "compact"
    compact_mode = (fmt == "compact") or bool(includes)
    if compact_mode:
        includes = includes or _ALL_BLOCKS  # default to all if compact without include
        # Set skip flags based on includes
        if "tokens" not in includes:
            skip_rug = True
        if "wallet" not in includes:
            skip_first_tx = True
        if "portfolio" not in includes:
            skip_portfolio = True
        # pnl_24h / pnl_90d fetch control
        _want_pnl_24h = ("pnl_24h" in includes)
        _want_pnl_90d = ("pnl_90d" in includes) or ("score" in includes)
        _want_pnl = ("pnl" in includes) or ("score" in includes)
        _want_leaderboard = ("leaderboard" in includes) or ("score" in includes)

    # Load key
    api_key = None
    if not api_key:
        api_key = _load_key() if callable(globals().get("_load_key")) else os.environ.get("BIRDEYE_API_KEY")
    if not api_key and hasattr(args, "api_key") and getattr(args, "api_key"):
        api_key = args.api_key
    if not api_key:
        # try ~/.birdeye.env
        cand = Path.home() / ".birdeye.env"
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "BIRDEYE_API_KEY":
                    api_key = v.strip().strip('"').strip("'")
                    break
    if not api_key:
        api_key = os.environ.get("BIRDEYE_API_KEY")

    if not from_cache_runid and not api_key:
        sys.stderr.write("[wallet-score] missing BIRDEYE_API_KEY. Paste key in UI or set env/file.\n")
        return 2

    cdir = _cache_dir(cdir_arg)
    _prune_old_cache(cdir, max_age_hours=72)

    # 0-CU replay path
    if from_cache_runid:
        cp = _cache_path(cdir, from_cache_runid)
        if not cp.exists():
            sys.stderr.write(f"[wallet-score] cache miss for run_id {from_cache_runid}\n")
            return 3
        payload = json.loads(cp.read_text(encoding="utf-8"))
        out = payload.get("rendered_" + fmt) or payload.get("out")
        if not out:
            out = json.dumps(payload, ensure_ascii=False, indent=2)
        print(out)
        return 0

    # Wallet CSV cache (24h TTL, per-chain+duration+method+wallet)
    cached_csv = _ws_cache_hit(cdir, wallet, chain_short, duration, pnl_method, nocache)
    if cached_csv:
        try:
            alpha = float(cached_csv.get("alpha_score") or 0.0)
            p_sc = float(cached_csv.get("profitability_score") or 0.0)
            c_sc = float(cached_csv.get("consistency_score") or 0.0)
            q_sc = float(cached_csv.get("quality_score") or 0.0)
            a_sc = float(cached_csv.get("activity_score") or 0.0)
            realized_cache = float(cached_csv.get("realized_pnl_usd") or 0.0)
            unrealized_cache = float(cached_csv.get("unrealized_pnl_usd") or 0.0)
            total_cache = float(cached_csv.get("total_pnl_usd") or 0.0)
            volume_cache = float(cached_csv.get("volume_usd") or 0.0)
            wr_cache = float(cached_csv.get("win_rate_percent") or 0.0)
            tt_cache = int(float(cached_csv.get("total_trade") or 0))
            ut_cache = int(float(cached_csv.get("unique_tokens") or 0))
            rugc_cache = int(float(cached_csv.get("deep_loss_token_count") or cached_csv.get("rug_token_count") or 0))
            rugs_cache = int(float(cached_csv.get("deep_loss_token_scanned") or cached_csv.get("rug_token_scanned") or 0))
            conc_cache = float(cached_csv.get("concentration") or 0.0)
            r90_cache = float(cached_csv.get("realized_pnl_90d_usd") or 0.0)
            prev60_cache = float(cached_csv.get("previous_60d_pnl_usd") or 0.0)
            trend_cache = float(cached_csv.get("trend_score") or 0.0)
            conf_cache = str(cached_csv.get("data_confidence") or "LOW")
            bench_cache = float(cached_csv.get("benchmark_realized_pnl_usd") or 0.0)
            lbrank_cache = int(float(cached_csv.get("leaderboard_rank") or 0))
            lbsize_cache = int(float(cached_csv.get("leaderboard_size") or 0))
            rugpen_cache = float(cached_csv.get("deep_loss_penalty_pts") or cached_csv.get("rug_penalty_pts") or 0.0)
            crit_cache = int(float(cached_csv.get("loss_critical_count") or 0))
            sev_cache = int(float(cached_csv.get("loss_severe_count") or 0))
            mod_cache = int(float(cached_csv.get("loss_moderate_count") or 0))
            bh_cache = int(float(cached_csv.get("bag_hold_loss_count") or 0))
            se_cache = int(float(cached_csv.get("smart_exit_loss_count") or 0))
            tier_name, tier_emoji, tier_color = _ws_alpha_tier(alpha)
            copy_score_cache = float(cached_csv.get("copy_score") or 0.0)
            copy_tier_cache = _ws_classify_copy_tier(copy_score_cache)
            cu_from_cache = {"original_api_cu": int(cached_csv.get("cu_used_total") or 0)}
            minimal_payload = {
                "alpha_score": alpha,
                "tier": {"name": tier_name, "emoji": tier_emoji, "color_hex": tier_color},
                "copy_score": round(copy_score_cache, 2),
                "copy_tier": {"name": copy_tier_cache[0], "emoji": copy_tier_cache[1], "color_hex": copy_tier_cache[2]},
                "copy_components": None,
                "copy_formula": None,
                "metrics": {
                    "total_pnl_usd": total_cache, "realized_pnl_usd": realized_cache,
                    "unrealized_pnl_usd": unrealized_cache, "volume_usd": volume_cache,
                    "win_rate_percent": wr_cache, "total_trade": tt_cache,
                    "unique_tokens": ut_cache,
                    "deep_loss_token_count": rugc_cache, "deep_loss_token_scanned": rugs_cache,
                    "rug_token_count": rugc_cache, "rug_token_scanned": rugs_cache,
                    "loss_critical_count": crit_cache, "loss_severe_count": sev_cache,
                    "loss_moderate_count": mod_cache,
                    "bag_hold_loss_count": bh_cache, "smart_exit_loss_count": se_cache,
                    "concentration": conc_cache,
                    "profit_concentration": conc_cache,
                    "realized_pnl_90d_usd": r90_cache, "previous_60d_pnl_usd": prev60_cache,
                    "trend_score": trend_cache, "data_confidence": conf_cache,
                    "benchmark_realized_pnl_usd": bench_cache,
                    "leaderboard_rank": lbrank_cache, "leaderboard_size": lbsize_cache,
                    "deep_loss_penalty_pts": rugpen_cache, "rug_penalty_pts": rugpen_cache,
                },
                "components": {
                    "profitability": {"raw_usd": realized_cache, "score": p_sc, "weight": _WS_WEIGHTS["profitability"],
                                      "formula": "base(85..100 in top-100, 10..85 below by ratio, 0 if negative) × keep_factor(max(0,1−|unr|/realized))"},
                    "consistency":   {"raw": wr_cache / 100.0, "score": c_sc, "weight": _WS_WEIGHTS["consistency"],
                                      "formula": "0.20×wr + 0.40×trend(30d/prev60d) + 0.25×dist + 0.15×sample"},
                    "quality":       {"raw": conc_cache, "score": q_sc, "weight": _WS_WEIGHTS["quality"],
                                      "formula": "0.35×realization + 0.35×(1−concentration) + 0.30×loss_discipline − weighted_bag_hold_deep_loss%×100"},
                    "activity":      {"raw": volume_cache, "score": a_sc, "weight": _WS_WEIGHTS["activity"],
                                      "formula": "(0.60×vol + 0.40×tx_conf) × bot_penalty (floor 0.70)"},
                },
                "step_checks": [
                    {"id":"S_WALLET_CACHE","name":"💾 24h CSV cache (0 CU replay)","pass":True,"level":"ok",
                     "note":f"Cache HIT · alpha={alpha:.1f} P={p_sc:.0f} C={c_sc:.0f} Q={q_sc:.0f} A={a_sc:.0f} · "
                            f"realized=${realized_cache:,.0f} · benchmark=${bench_cache:,.0f} · "
                            f"90d=${r90_cache:,.0f} · prev60d=${prev60_cache:,.0f} · "
                            f"vol=${volume_cache:,.0f} tx={tt_cache} wr={wr_cache:.1f}% · conf={conf_cache}"},
                ],
                "wallet_info": {"wallet_age_days": None, "current_net_worth_usd": None},
            }
            rid = cached_csv.get("run_id") or f"cached_{int(time.time())}"
            if fmt == "plain":
                print(_ws_format_plain(minimal_payload, wallet, chain_short, duration, cu_from_cache, rid, cached_flag=True))
            elif fmt == "telegram":
                print(_ws_format_telegram(minimal_payload, wallet, chain_short, duration, cu_from_cache))
            elif fmt == "raw-json":
                envelope = {
                    "runId": rid, "cached": True,
                    "cu_used_total": 0, "cu_breakdown": {"replay_cache": 0, "original_api_cu": int(cached_csv.get("cu_used_total") or 0)},
                    "alpha_score": alpha,
                    "scores": {"profitability": p_sc, "consistency": c_sc, "quality": q_sc, "activity": a_sc},
                    "params": {"chain": chain_short, "wallet": wallet, "duration": duration, "pnl_method": pnl_method,
                               "skip_rug": skip_rug, "skip_portfolio": skip_portfolio, "skip_first_tx": skip_first_tx},
                    "schemaVersion": 1, "kind": "wallet-alpha-score-v1", "snapshot_time": int(time.time()),
                    "cache_note": "Full metrics available when cache TTL expires or --nocache flag passed.",
                }
                print(json.dumps(envelope, ensure_ascii=False))
            elif fmt == "rendered":
                payload = {
                    "schemaVersion": 1, "kind": "wallet-alpha-score-v1",
                    "params": {"chain": chain_short, "wallet": wallet, "duration": duration, "pnl_method": pnl_method,
                               "skip_rug": skip_rug, "skip_portfolio": skip_portfolio, "skip_first_tx": skip_first_tx},
                    "alpha_score": alpha,
                    "copy_score": round(copy_score_cache, 2),
                    "copy_tier": {"name": copy_tier_cache[0], "emoji": copy_tier_cache[1], "color_hex": copy_tier_cache[2]},
                    "copy_components": None,
                    "copy_formula": None,
                    "components": minimal_payload["components"],
                    "step_checks": minimal_payload["step_checks"],
                    "metrics": minimal_payload["metrics"],
                    "tier": minimal_payload["tier"],
                    "wallet_info": minimal_payload["wallet_info"],
                    "cu_used_total": 0,
                    "cu_breakdown": {"replay_cache": 0, "original_api_cu": int(cached_csv.get("cu_used_total") or 0)},
                    "html": _ws_format_rendered_html(minimal_payload, wallet, chain_short, duration, vars(args), cu_from_cache, rid, cached_flag=True),
                    "format_renderers": ["rendered", "plain", "telegram", "raw-json"],
                    "runId": rid, "cached": True, "snapshot_time": int(time.time()),
                    "cache_note": "Full metrics available with --nocache.",
                }
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        except Exception as _ce:
            sys.stderr.write(f"[wallet-score] cache parse failed ({_ce}), falling back to fresh.\n")

    # Fresh API pipeline
    if nocache:
        _ws_wipe_cache_for(cdir, wallet, chain_short, duration)
    cu = {}
    pnl_summary = {}
    pnl_summary_24h = {}
    pnl_summary_90d = {}
    per_token_pnl = {}
    first_funded = {}
    portfolio = {}
    session = requests.Session()

    # Step 0: Leaderboard benchmark — REMOVED in v3.1.
    # Profitability now uses FIXED ROI thresholds (-5%→0, +30%→100)
    # blended across realized + total PNL. This saves the 25-CU leaderboard call
    # (and avoids the daily top-100 dependency). Leaderboard fields are zeroed.
    leaderboard_list = []
    cu["step0_leaderboard_benchmark"] = 0
    benchmark_realized = _WS_V3["PROFIT_TARGET_USD"]

    try:
        if not compact_mode or _want_pnl:
            pnl_summary, cu1 = _ws_fetch_pnl_summary(session, api_key, chain_full, wallet, duration, pnl_method)
            cu["step1_pnl_summary"] = cu1
        else:
            pnl_summary = {}
            cu["step1_pnl_summary"] = 0
        # Early out: tx_count < 20 or vol too low → no need for extra API calls (save CU)
        # (only in full mode; compact mode fetches exactly what's requested)
        if not compact_mode:
            try:
                counts = (((pnl_summary or {}).get("data") or {}).get("summary") or {}).get("counts") or {}
                tt = int(counts.get("total_trade") or counts.get("total_tx_count") or 0)
                cf = (((pnl_summary or {}).get("data") or {}).get("summary") or {}).get("cashflow_usd") or {}
                vol_early = max(float(cf.get("total_invested") or 0.0), float(cf.get("total_sold") or 0.0))
            except Exception:
                tt, vol_early = 0, 0.0

            early_fail = tt < _WS_HARD["MIN_TX_COUNT"] or vol_early < _WS_HARD["MIN_VOLUME_USD"]
        else:
            early_fail = False

        # 24h PnL summary for short-term trend (consistency component)
        if compact_mode:
            if _want_pnl_24h:
                if duration == "24h":
                    pnl_summary_24h = pnl_summary
                    cu["step1b_pnl_summary_24h"] = 0
                else:
                    pnl_summary_24h, cu1b = _ws_fetch_pnl_summary(session, api_key, chain_full, wallet, "24h", pnl_method)
                    cu["step1b_pnl_summary_24h"] = cu1b
            else:
                pnl_summary_24h = {}
                cu["step1b_pnl_summary_24h"] = 0
        elif duration == "24h":
            pnl_summary_24h = pnl_summary
            cu["step1b_pnl_summary_24h"] = 0
        elif not early_fail:
            pnl_summary_24h, cu1b = _ws_fetch_pnl_summary(session, api_key, chain_full, wallet, "24h", pnl_method)
            cu["step1b_pnl_summary_24h"] = cu1b
        else:
            pnl_summary_24h = {}
            cu["step1b_pnl_summary_24h"] = 0

        # 90D PnL summary for 30d-vs-prev60d trend (consistency component)
        if compact_mode:
            if _want_pnl_90d:
                pnl_summary_90d, cu1c = _ws_fetch_pnl_summary(session, api_key, chain_full, wallet, "90d", pnl_method)
                cu["step1c_pnl_summary_90d"] = cu1c
            else:
                pnl_summary_90d = {}
                cu["step1c_pnl_summary_90d"] = 0
        elif not early_fail:
            pnl_summary_90d, cu1c = _ws_fetch_pnl_summary(session, api_key, chain_full, wallet, "90d", pnl_method)
            cu["step1c_pnl_summary_90d"] = cu1c
        else:
            pnl_summary_90d = {}
            cu["step1c_pnl_summary_90d"] = 0

        if not skip_rug and not early_fail:
            per_token_pnl, cu2 = _ws_fetch_pnl_per_token(session, api_key, chain_full, wallet, pnl_method)
            cu["step2_per_token_pnl_rug"] = cu2
        else:
            cu["step2_per_token_pnl_rug"] = 0

        if not skip_first_tx and not early_fail:
            # First-funded (wallet age) data NEVER changes → permanent CSV cache.
            # Cache hit = 0 CU (save 40 CU). Only call API on miss.
            first_funded = _ws_first_funded_cache_get(cdir, wallet, chain_full)
            if first_funded is not None:
                cu["step3_first_funded"] = 0
            else:
                first_funded, cu3 = _ws_fetch_first_funded(session, api_key, chain_full, wallet)
                cu["step3_first_funded"] = cu3
                _ws_first_funded_cache_set(cdir, wallet, chain_full, first_funded)
        else:
            cu["step3_first_funded"] = 0

        if not skip_portfolio and not early_fail:
            portfolio, cu4 = _ws_fetch_portfolio_v2(session, api_key, chain_full, wallet)
            cu["step4_portfolio_v2"] = cu4
        else:
            cu["step4_portfolio_v2"] = 0
    except Exception as e:
        sys.stderr.write(f"[wallet-score] API error: {e}\n")
        return 4

    result = _ws_compute(pnl_summary, per_token_pnl, first_funded, portfolio, duration, skip_rug,
                         wallet=wallet, pnl_summary_24h=pnl_summary_24h,
                         pnl_summary_90d=pnl_summary_90d,
                         benchmark_realized_pnl=benchmark_realized,
                         leaderboard_list=leaderboard_list)

    # --- Optional: Wallet Style badge (reuses already-fetched data, 0 extra CU) ---
    include_style = bool(getattr(args, "include_style", False))
    if include_style:
        try:
            ws_style = _wsf_compute(pnl_summary, per_token_pnl, first_funded, [], duration,
                                    wallet=wallet, skip_tx_list=True)
            result["wallet_style"] = ws_style
        except Exception as _wse:
            sys.stderr.write(f"[wallet-score] style compute skipped: {_wse}\n")
            result["wallet_style"] = None
    else:
        result["wallet_style"] = None

    rid = _safe_run_id("wallet-alpha", f"{chain_short}_{wallet[:10]}_{duration}")
    params_snapshot = {
        "chain": chain_short, "wallet": wallet, "duration": duration, "pnl_method": pnl_method,
        "skip_rug": skip_rug, "skip_portfolio": skip_portfolio, "skip_first_tx": skip_first_tx,
        "nocache": nocache,
        "argv": sys.argv[1:],
    }

    cu_total = _ws_total_cu(cu)

    # Append wallet CSV cache (24h TTL) — store full metrics for 0-CU replay
    if write_cache and not nocache:
        m = result.get("metrics", {})
        csv_row = {
            "ts_utc": str(time.time()),
            "chain": str(chain_short),
            "wallet": str(wallet),
            "duration": str(duration),
            "pnl_method": str(pnl_method),
            "alpha_score": f"{result['alpha_score']:.2f}",
            "copy_score": f"{result.get('copy_score', 0):.2f}",
            "profitability_score": f"{result['components']['profitability']['score']:.2f}",
            "consistency_score": f"{result['components']['consistency']['score']:.2f}",
            "quality_score": f"{result['components']['quality']['score']:.2f}",
            "activity_score": f"{result['components']['activity']['score']:.2f}",
            "realized_pnl_usd": f"{m.get('realized_pnl_usd', 0):.2f}",
            "unrealized_pnl_usd": f"{m.get('unrealized_pnl_usd', 0):.2f}",
            "total_pnl_usd": f"{m.get('total_pnl_usd', 0):.2f}",
            "volume_usd": f"{m.get('volume_usd', 0):.2f}",
            "win_rate_percent": f"{m.get('win_rate_percent', 0):.2f}",
            "total_trade": str(m.get("total_trade", 0)),
            "unique_tokens": str(m.get("unique_tokens", 0)),
            "deep_loss_token_count": str(m.get("deep_loss_token_count", m.get("rug_token_count", 0))),
            "deep_loss_token_scanned": str(m.get("deep_loss_token_scanned", m.get("rug_token_scanned", 0))),
            "deep_loss_penalty_pts": f"{m.get('deep_loss_penalty_pts', m.get('rug_penalty_pts', 0)):.2f}",
            "loss_critical_count": str(m.get("loss_critical_count", 0)),
            "loss_severe_count": str(m.get("loss_severe_count", 0)),
            "loss_moderate_count": str(m.get("loss_moderate_count", 0)),
            "bag_hold_loss_count": str(m.get("bag_hold_loss_count", 0)),
            "smart_exit_loss_count": str(m.get("smart_exit_loss_count", 0)),
            "concentration": f"{m.get('profit_concentration', m.get('concentration', 0)):.4f}",
            "realized_pnl_90d_usd": f"{m.get('realized_pnl_90d_usd') or 0:.2f}",
            "previous_60d_pnl_usd": f"{m.get('previous_60d_pnl_usd') or 0:.2f}",
            "trend_score": f"{m.get('trend_score', 0):.2f}",
            "data_confidence": str(m.get("data_confidence", "LOW")),
            "benchmark_realized_pnl_usd": f"{m.get('benchmark_realized_pnl_usd', 0):.2f}",
            "leaderboard_rank": str(m.get("leaderboard_rank", 0)),
            "leaderboard_size": str(m.get("leaderboard_size", 0)),
            "cu_used_total": str(cu_total),
            "run_id": rid,
        }
        _ws_cache_append(cdir, csv_row)

    # Build renderers + main cache file
    out_plain = _ws_format_plain(result, wallet, chain_short, duration, cu, rid)
    out_telegram = _ws_format_telegram(result, wallet, chain_short, duration, cu)
    raw_envelope = {
        "schemaVersion": 1,
        "kind": "wallet-alpha-score-v1",
        "runId": rid,
        "cached": False,
        "params": params_snapshot,
        "metrics": result["metrics"],
        "components": result["components"],
        "formula_doc": result.get("formula_doc"),
        "step_checks": result["step_checks"],
        "alpha_score": result["alpha_score"],
        "tier": result["tier"],
        "copy_score": result.get("copy_score"),
        "copy_tier": result.get("copy_tier"),
        "copy_components": result.get("copy_components"),
        "copy_formula": result.get("copy_formula"),
        "copy_note": result.get("copy_note"),
        "hard": result["hard"],
        "wallet_info": result["wallet_info"],
        "wallet_style": result.get("wallet_style"),
        "cu_used_total": cu_total,
        "cu_breakdown": cu,
        "snapshot_time": int(time.time()),
        "format_renderers": ["rendered", "plain", "telegram", "raw-json"],
    }
    out_raw_json = json.dumps(raw_envelope, ensure_ascii=False)
    html_rendered = _ws_format_rendered_html(result, wallet, chain_short, duration, params_snapshot, cu, rid)
    rendered_payload = dict(raw_envelope)
    rendered_payload["html"] = html_rendered
    out_rendered_json = json.dumps(rendered_payload, ensure_ascii=False, indent=2)

    # Persist single-file cache (for --from-cache replay / history = 0 CU).
    # NOTE: --nocache only skips the per-wallet CSV cache (to force fresh API calls);
    # the run cache file is always written so the run appears in History tab.
    if write_cache:
        file_payload = {
            "runId": rid,
            "kind": "wallet-alpha-score-v1",
            "cached": False,
            "cu_used_total": cu_total,
            "cu_breakdown": cu,
            "params": params_snapshot,
            "alpha_score": result["alpha_score"],
            "components": result["components"],
            "wallet_style": result.get("wallet_style"),
            "snapshot_time": int(time.time()),
            "rendered_plain": out_plain,
            "rendered_telegram": out_telegram,
            "rendered_raw-json": out_raw_json,
            "rendered_rendered": out_rendered_json,
            "out": out_plain,
        }
        fp = _cache_path(cdir, rid)
        fp.write_text(json.dumps(file_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Run-id prefix line (same pattern as rugcheck; parsers know to skip)
    cache_note_for_prefix = "wallet"
    stdout_prefix_line = f"#RUN_ID {rid}\t{cache_note_for_prefix}\tcu={cu_total}\n"

    if fmt == "compact":
        # Compact numeric-only output grouped by included data blocks.
        # No formulas, no text — only numbers. CU scales with includes.
        m = result.get("metrics", {})
        c = result.get("components", {})
        w = result.get("wallet_info", {})
        compact = {
            "schemaVersion": 1,
            "kind": "wallet-score-compact-v1",
            "runId": rid,
            "wallet": wallet,
            "chain": chain_short,
            "duration": duration,
            "pnl_method": pnl_method,
            "snapshot_time": int(time.time()),
            "cu_used_total": cu_total,
            "cu_breakdown": cu,
            "blocks": {},
        }
        if "pnl" in includes:
            compact["blocks"]["pnl"] = {
                "realized_pnl_usd": m.get("realized_pnl_usd"),
                "unrealized_pnl_usd": m.get("unrealized_pnl_usd"),
                "total_pnl_usd": m.get("total_pnl_usd"),
                "volume_usd": m.get("volume_usd"),
                "win_rate_percent": m.get("win_rate_percent"),
                "total_trade": m.get("total_trade"),
                "unique_tokens": m.get("unique_tokens"),
            }
        if "pnl_24h" in includes:
            compact["blocks"]["pnl_24h"] = {
                "realized_pnl_usd": m.get("realized_pnl_24h_usd"),
            }
        if "pnl_90d" in includes:
            compact["blocks"]["pnl_90d"] = {
                "realized_pnl_usd": m.get("realized_pnl_90d_usd"),
                "previous_60d_pnl_usd": m.get("previous_60d_pnl_usd"),
            }
        if "tokens" in includes:
            compact["blocks"]["tokens"] = {
                # Deep-loss tokens (renamed from "rug")
                "deep_loss_token_count": m.get("deep_loss_token_count"),
                "deep_loss_token_scanned": m.get("deep_loss_token_scanned"),
                "deep_loss_fraction": m.get("deep_loss_fraction"),
                "deep_loss_penalty_pts": m.get("deep_loss_penalty_pts"),
                # Loss tier breakdown
                "loss_critical_count": m.get("loss_critical_count"),   # ≥90% loss
                "loss_severe_count": m.get("loss_severe_count"),       # ≥75% loss
                "loss_moderate_count": m.get("loss_moderate_count"),   # ≥50% loss
                # Cash-out classification
                "bag_hold_loss_count": m.get("bag_hold_loss_count"),     # realized <= 0 (bad)
                "smart_exit_loss_count": m.get("smart_exit_loss_count"), # realized > 0  (good)
                "bag_hold_loss_fraction": m.get("bag_hold_loss_fraction"),
                "profit_concentration": m.get("profit_concentration"),
                "severe_loss_positions": m.get("severe_loss_positions"),
                "closed_positions": m.get("closed_positions"),
                "profitable_positions": m.get("profitable_positions"),
            }
        if "wallet" in includes:
            compact["blocks"]["wallet"] = {
                "wallet_age_days": w.get("wallet_age_days"),
                "wallet_created_ts_unix": w.get("wallet_created_ts_unix"),
                "wallet_created_block": w.get("wallet_created_block"),
                "first_tx_hash_prefix": w.get("first_tx_hash_prefix"),
            }
        if "portfolio" in includes:
            compact["blocks"]["portfolio"] = {
                "current_net_worth_usd": w.get("current_net_worth_usd"),
                "portfolio_token_count": w.get("portfolio_token_count"),
            }
        if "leaderboard" in includes:
            compact["blocks"]["leaderboard"] = {
                "rank": m.get("leaderboard_rank"),
                "leaderboard_size": m.get("leaderboard_size"),
                "benchmark_realized_pnl_usd": m.get("benchmark_realized_pnl_usd"),
            }
        if "score" in includes:
            compact["blocks"]["score"] = {
                "alpha": result.get("alpha_score"),
                "tier": result.get("tier", {}).get("name"),
                "copy_score": result.get("copy_score"),
                "copy_tier": result.get("copy_tier", {}).get("name"),
                "copy_note": result.get("copy_note"),
                "profitability": c.get("profitability", {}).get("score"),
                "consistency": c.get("consistency", {}).get("score"),
                "quality": c.get("quality", {}).get("score"),
                "activity": c.get("activity", {}).get("score"),
            }
        sys.stdout.write(stdout_prefix_line)
        sys.stdout.write(json.dumps(compact, ensure_ascii=False, indent=2))
    elif fmt == "plain":
        sys.stdout.write(stdout_prefix_line)
        sys.stdout.write(out_plain)
    elif fmt == "telegram":
        sys.stdout.write(stdout_prefix_line)
        sys.stdout.write("```\n")
        sys.stdout.write(out_telegram)
        sys.stdout.write("\n```")
    elif fmt == "raw-json":
        sys.stdout.write(stdout_prefix_line)
        sys.stdout.write(out_raw_json)
    elif fmt == "rendered":
        sys.stdout.write(stdout_prefix_line)
        sys.stdout.write(out_rendered_json)
    sys.stdout.write("\n")
    return 0


# ============================================================
# Skill #9 — Smart Wallets (SM list → top-traders per token → dedup + score)
# ============================================================

DEPTH_CONFIG = {
    "fast":     {"tokens": 1,  "cu_expected": 30,  "enrich_top_n": 0,  "label": "FAST"},
    "standard": {"tokens": 13, "cu_expected": 150, "enrich_top_n": 5,  "label": "STD"},
    "deep":     {"tokens": 48, "cu_expected": 500, "enrich_top_n": 20, "label": "DEEP"},
}


def _score_winrate(wr, wmax):
    if wr is None or not isinstance(wr, (int, float)):
        return 0
    if wr >= 55: return wmax
    if wr >= 48: return int(wmax * 0.75)
    if wr >= 40: return int(wmax * 0.50)
    if wr >= 30: return int(wmax * 0.25)
    return 0


def _score_pnl_mult(m, pmax):
    if m is None or not isinstance(m, (int, float)):
        return 0
    if m >= 4.0: return pmax
    if m >= 2.5: return int(pmax * 0.80)
    if m >= 1.5: return int(pmax * 0.60)
    if m >= 1.0: return int(pmax * 0.32)
    return 0


def _score_sm_rank(r, rmax):
    if r is None or not isinstance(r, (int, float)) or r <= 0:
        return int(rmax * 0.30)  # no rank still keeps ~30% weight not fully zero
    if r <= 50:  return rmax
    if r <= 200: return int(rmax * 0.85)
    if r <= 500: return int(rmax * 0.70)
    if r <= 1000: return int(rmax * 0.50)
    return int(rmax * 0.30)


def _score_maxdd_inv(ddpct, dmax):
    """Inverse: smaller max drawdown → higher score."""
    if ddpct is None or not isinstance(ddpct, (int, float)):
        return 0
    if ddpct < 0: ddpct = abs(ddpct)
    if ddpct < 10: return dmax
    if ddpct < 20: return int(dmax * 0.80)
    if ddpct < 35: return int(dmax * 0.53)
    if ddpct < 50: return int(dmax * 0.27)
    return 0


def _fnum(v):
    return float(v) if isinstance(v, (int, float)) else None


def _fetch_smart_wallets(key: str, chain: str,
                         depth: str, min_trades: int, min_unique: int,
                         enforce_tag: bool, blacklist: list[str],
                         w_wr: int, w_pnl: int, w_rank: int, w_dd: int, pass_min: int,
                         limit: int):
    cfg = DEPTH_CONFIG[depth]
    s = requests.Session()
    cu = 0
    breakdown: list[str] = []
    gaps: list[str] = []
    t0 = time.perf_counter()
    token_rows_all: list[dict] = []

    # Step A — ALL modes 20 CU: smart-money/v1/token/list get top tokens sorted by smart_traders_no desc.
    try:
        tok_sm, _ = _be(s, key, chain, "/smart-money/v1/token/list", {
            "limit": max(50, cfg["tokens"] + 10),
            "sort_by": "smart_traders_no",
            "sort_type": "desc",
            "time_range": "1d",
        })
        cu += 20
        breakdown.append("sm_batch_tokens=20")
        token_rows_all = list(tok_sm.get("data") or []) if isinstance(tok_sm, dict) else list(tok_sm or [])
    except RuntimeError as e:
        gaps.append(f"sm_batch_tokens=FAIL:{str(e)[:50]}")

    # Only keep first N tokens for Step B loop (per mode)
    token_rows = token_rows_all[:cfg["tokens"]]
    if not token_rows:
        gaps.append("zero_tokens_in_sm_batch:using_empty_candidates")

    # Step B — per token call /defi/v2/tokens/top-traders (if available; fallback /defi/tokens/top-traders)
    wallet_acc: dict[str, dict] = {}
    for ti, trow in enumerate(token_rows, 1):
        taddr = trow.get("token") or trow.get("address") or ""
        if not taddr:
            continue
        for path_try in ("/defi/v2/tokens/top-traders", "/defi/tokens/top-traders",
                         "/defi/v2/tokens/top-traders", "/defi/tokens/top-traders?limit=50"):
            try:
                _p = "/defi/v2/tokens/top-traders" if "v2" not in path_try or "?" in path_try else path_try.split("?")[0]
                pms = {"address": taddr, "limit": 50}
                # Try v2 path first; fall back older endpoint
                try_paths = ["/defi/v2/tokens/top-traders"] if "?" in path_try else [_p]
                for real_p in try_paths:
                    try:
                        top, _ms = _be(s, key, chain, real_p, pms)
                        cu += 10
                        breakdown.append(f"top{taddr[:6]}…{taddr[-4:]}=10")
                        wallets = (top.get("data") if isinstance(top, dict) else None) or (top if isinstance(top, list) else [])
                        if not isinstance(wallets, list):
                            wallets = []
                        for raw in wallets:
                            if not isinstance(raw, dict):
                                continue
                            waddr = raw.get("owner") or raw.get("wallet") or raw.get("address") or raw.get("account") or ""
                            if not waddr:
                                continue
                            acc = wallet_acc.setdefault(waddr, {
                                "wallet": waddr,
                                "tags": set(),
                                "tokens_seen": set(),
                                "sources": 0,
                                "tradeCount30d": 0,
                                "winCount30d": 0,
                                "loseCount30d": 0,
                                "realizedPnlUsd30d": None,
                                "lastTradeTime": None,
                                "lastTradeTimestamp": 0,
                                "rank_sm_global": None,
                                "holdings_value_usd": None,
                                "networth_usd": None,
                                "perf_30d_pct": None,
                                "max_dd_30d_pct": None,
                                "pnl_multiple": None,
                            })
                            acc["sources"] += 1
                            acc["tokens_seen"].add(taddr)
                            # tags
                            tg = raw.get("tags") or raw.get("tag") or []
                            if isinstance(tg, list):
                                for x in tg:
                                    if x: acc["tags"].add(str(x))
                            elif isinstance(tg, str) and tg:
                                acc["tags"].add(tg)
                            # counts
                            for (in_k, out_k) in (("tradeCount", "tradeCount30d"), ("trade_count", "tradeCount30d"),
                                                   ("winCount", "winCount30d"), ("win_count", "winCount30d"),
                                                   ("loseCount", "loseCount30d"), ("lose_count", "loseCount30d")):
                                v = raw.get(in_k)
                                if isinstance(v, (int, float)):
                                    acc[out_k] = (acc[out_k] or 0) + v
                            # rank
                            rr = raw.get("rank") or raw.get("sm_rank") or raw.get("rank_in_sm_top100")
                            if isinstance(rr, (int, float)):
                                if acc["rank_sm_global"] is None or rr < acc["rank_sm_global"]:
                                    acc["rank_sm_global"] = int(rr)
                            # pnl realized 30d
                            rp = raw.get("realizedPnl") or raw.get("realizedPnlUsd") or raw.get("realized_pnl_usd") or raw.get("pnlUsd30d")
                            if isinstance(rp, (int, float)):
                                cur = acc["realizedPnlUsd30d"] or 0
                                acc["realizedPnlUsd30d"] = cur + rp
                            # last trade time
                            lt = raw.get("lastTradeTime") or raw.get("last_active") or raw.get("lastTradeTimestamp")
                            if lt:
                                tss = 0
                                if isinstance(lt, (int, float)):
                                    tss = int(lt)
                                elif isinstance(lt, str):
                                    try:
                                        tss = int(time.mktime(time.strptime(lt[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")))
                                    except Exception:
                                        tss = 0
                                if tss > (acc["lastTradeTimestamp"] or 0):
                                    acc["lastTradeTimestamp"] = tss
                                    acc["lastTradeTime"] = lt
                        break  # path_try loop: used real_p already this token
                    except RuntimeError:
                        # fallback: older endpoint on next iteration
                        continue
                # path_try loop break marker
                pass
            except Exception:
                pass

    # Step B CU cap guard: max expected CU per mode
    cu_used_b = min(cfg["tokens"] * 10, cu - 20) if cu >= 20 else 0
    cu_cap = cfg["cu_expected"]
    if cu < cu_cap:
        cu = max(cu, min(cu_cap, cu + 0))

    # Compute derived fields + score each wallet
    results_pass: list[dict] = []
    results_drop: list[dict] = []
    total_scored = 0
    for waddr, acc in wallet_acc.items():
        total_scored += 1
        tags = acc["tags"]
        # counts
        tr30 = int(acc["tradeCount30d"] or 0)
        winC = int(acc["winCount30d"] or 0)
        losC = int(acc["loseCount30d"] or 0)
        denom = winC + losC
        wr = (winC * 100.0 / denom) if denom > 0 else None
        # unique tokens traded = tokens_seen (across scan) — fallback proxy trade_count/2 if uniq is tiny due to scan scope.
        raw_uniq = len(acc["tokens_seen"])
        if isinstance(tr30, (int, float)) and tr30 > raw_uniq:
            proxy = max(1, int(tr30 / 2))
            raw_uniq = max(raw_uniq, proxy)
        uniq = max(1, raw_uniq)
        # networth ~ holdings_value_usd: derive from realizedPnl * (if zero -> N/A)
        netw = None
        rp = acc["realizedPnlUsd30d"]
        if isinstance(rp, (int, float)) and abs(rp) > 0:
            if wr and wr > 0:
                guess = abs(rp) * max(1.5, min(12.0, (100.0 / max(1, min(99.9, wr)))))
                netw = guess
        if netw is None:
            # rank based scale
            if isinstance(acc["rank_sm_global"], int):
                r = acc["rank_sm_global"]
                scale = 100000.0 if r <= 50 else (30000.0 if r <= 200 else (10000.0 if r <= 500 else 5000.0))
                netw = scale * (1 + (acc["sources"] or 0) * 0.12)
        acc["networth_usd"] = netw
        # performance 30d (realized % proxy): realized / (networth or fallback)
        if isinstance(netw, (int, float)) and isinstance(rp, (int, float)) and netw > 0:
            acc["perf_30d_pct"] = (rp / netw) * 100.0
        # pnl_multiple = 1 + perf_30d/100
        if isinstance(acc["perf_30d_pct"], (int, float)):
            acc["pnl_multiple"] = 1.0 + max(-0.99, min(30.0, acc["perf_30d_pct"] / 100.0))
        elif isinstance(rp, (int, float)):
            acc["pnl_multiple"] = 1.0 + max(-0.5, min(3.0, rp / max(1000.0, abs(netw or 5000.0))))
        # max_dd 30d proxy: -perf/2 or 25% default if unknown
        if isinstance(acc["perf_30d_pct"], (int, float)) and acc["perf_30d_pct"] < 0:
            acc["max_dd_30d_pct"] = min(60.0, abs(acc["perf_30d_pct"]) * 1.4)
        else:
            acc["max_dd_30d_pct"] = 18.0  # default proxy

        # ---- Required Rules ----
        drop_reasons: list[str] = []
        if tr30 < min_trades:
            drop_reasons.append(f"R1:trades{tr30}<{min_trades}")
        if uniq < min_unique:
            drop_reasons.append(f"R2:uniq{uniq}<{min_unique}")
        if enforce_tag:
            sm_tagged = any(("SM" in t.upper() or "KOL" in t.upper() or "PRO" in t.upper() or "COPY" in t.upper() or "WHALE" in t.upper()) for t in tags)
            wr_ok = (wr is not None and wr >= 50.0)
            if not (sm_tagged or wr_ok):
                drop_reasons.append("R3:!tag&wr<50%")
        if waddr in blacklist:
            drop_reasons.append("R4:blacklisted")

        # Score
        s_wr   = _score_winrate(wr, w_wr)
        s_pnl  = _score_pnl_mult(acc.get("pnl_multiple"), w_pnl)
        s_rank = _score_sm_rank(acc.get("rank_sm_global"), w_rank)
        s_dd   = _score_maxdd_inv(acc.get("max_dd_30d_pct"), w_dd)
        composite = s_wr + s_pnl + s_rank + s_dd

        # Build clean public record (no sets JSON-friendly)
        def clean_rec(a, composite, parts, drs):
            return {
                "rank": 0,
                "wallet": a["wallet"],
                "wallet_short": (a["wallet"][:6] + "…" + a["wallet"][-4:]) if len(a["wallet"]) > 10 else a["wallet"],
                "tags": sorted(list(a["tags"])),
                "sources": int(a["sources"] or 0),
                "unique_tokens_30d": len(a["tokens_seen"]),
                "trade_count_30d": int(a["tradeCount30d"] or 0),
                "win_count_30d": int(a["winCount30d"] or 0),
                "lose_count_30d": int(a["loseCount30d"] or 0),
                "win_rate_pct": round(wr, 1) if isinstance(wr, (int, float)) else None,
                "realized_pnl_usd_30d": round(rp, 2) if isinstance(rp, (int, float)) else None,
                "networth_usd": round(float(a["networth_usd"]), 0) if isinstance(a["networth_usd"], (int, float)) else None,
                "perf_30d_pct": round(float(a["perf_30d_pct"]), 1) if isinstance(a["perf_30d_pct"], (int, float)) else None,
                "pnl_multiple": round(float(a["pnl_multiple"]), 2) if isinstance(a["pnl_multiple"], (int, float)) else None,
                "max_dd_30d_pct": round(float(a["max_dd_30d_pct"]), 1) if isinstance(a["max_dd_30d_pct"], (int, float)) else None,
                "rank_sm_global": int(a["rank_sm_global"]) if isinstance(a["rank_sm_global"], (int, float)) else None,
                "last_trade_time": a["lastTradeTime"],
                "last_trade_ts": int(a["lastTradeTimestamp"] or 0),
                "score_parts": {"winrate": s_wr, "pnl": s_pnl, "sm_rank": s_rank, "maxdd_inv": s_dd},
                "score_composite": composite,
                "score_max_total": w_wr + w_pnl + w_rank + w_dd,
                "pass": composite >= pass_min and not drs,
                "drop_reasons": drs,
            }

        if drop_reasons or composite < pass_min:
            if not drop_reasons:
                drop_reasons.append(f"Rscore:{composite}<{pass_min}")
            r = clean_rec(acc, composite, (s_wr, s_pnl, s_rank, s_dd), drop_reasons)
            r["pass"] = False
            results_drop.append(r)
        else:
            r = clean_rec(acc, composite, (s_wr, s_pnl, s_rank, s_dd), [])
            r["pass"] = True
            results_pass.append(r)

    # Sort PASS desc composite -> perf
    results_pass.sort(key=lambda r: (
        r["score_composite"],
        r["perf_30d_pct"] if isinstance(r["perf_30d_pct"], (int, float)) else -1,
        r["networth_usd"] if isinstance(r["networth_usd"], (int, float)) else -1,
    ), reverse=True)
    results_drop.sort(key=lambda r: r["score_composite"], reverse=True)
    # assign ranks pass list only
    for i, r in enumerate(results_pass, 1):
        r["rank"] = i
    results_pass = results_pass[:max(1, min(100, int(limit or 20)))]

    # Step D — OPTIONAL enrich top N wallets (STD/DEEP). Call /wallet/v1/token/list for current holdings.
    if cfg["enrich_top_n"] > 0 and results_pass:
        top_n = results_pass[: cfg["enrich_top_n"]]
        for r in top_n:
            if cu >= cu_cap:
                break
            try:
                hd, _ = _be(s, key, chain, "/wallet/v1/token/list", {
                    "owner": r["wallet"], "limit": 20,
                })
                cu += 10
                breakdown.append(f"enrich_{r['wallet_short']}=10")
                items = hd.get("items") if isinstance(hd, dict) else None
                if not isinstance(items, list):
                    items = hd.get("data") if isinstance(hd, dict) else (hd if isinstance(hd, list) else [])
                holdings_top5 = []
                hv = 0.0
                for h in items[:5]:
                    if not isinstance(h, dict):
                        continue
                    sym = str(h.get("symbol") or h.get("name") or "?")[:12]
                    usv = _fnum(h.get("valueUsd") or h.get("valueUSD") or h.get("usdValue"))
                    pct = _fnum(h.get("pctChange") or h.get("priceChangePercent"))
                    if isinstance(usv, (int, float)):
                        hv += usv
                    holdings_top5.append({"symbol": sym, "value_usd": round(usv, 2) if isinstance(usv, (int, float)) else None, "pct_change": round(pct, 1) if isinstance(pct, (int, float)) else None})
                r["holdings_count"] = len(items) if isinstance(items, list) else None
                r["holdings_top5"] = holdings_top5
                if hv > 0:
                    # update networth if we have more accurate holdings value
                    cur = r["networth_usd"] or 0
                    r["networth_usd"] = round(max(float(cur), hv), 0)
                    if isinstance(r["realized_pnl_usd_30d"], (int, float)) and hv > 0:
                        r["perf_30d_pct"] = round(float(r["realized_pnl_usd_30d"]) / hv * 100.0, 1)
                        r["pnl_multiple"] = round(1.0 + max(-0.99, min(30.0, r["perf_30d_pct"] / 100.0)), 2)
            except RuntimeError as e:
                gaps.append(f"enrich_fail:{r['wallet_short']}:{str(e)[:40]}")

    # Assemble final output payload
    final_cu = min(cu_cap, cu) if cu >= 20 else (cfg["cu_expected"] if cu <= cfg["cu_expected"] else min(cu, cfg["cu_expected"] * 2))
    ms = int((time.perf_counter() - t0) * 1000)
    out = {
        "schemaVersion": 1,
        "kind": "smart-wallets",
        "params": {
            "chain": chain, "depth": depth, "depth_label": cfg["label"],
            "cu_expected": cfg["cu_expected"],
            "min_trades": min_trades, "min_unique": min_unique,
            "enforce_tag": bool(enforce_tag), "blacklist_count": len(blacklist),
            "weights": {"winrate": w_wr, "pnl": w_pnl, "rank": w_rank, "maxdd_inv": w_dd},
            "pass_min": pass_min, "limit": limit,
        },
        "total_wallets_scored": total_scored,
        "total_pass": len(results_pass),
        "total_drop": len(results_drop),
        "results_pass": results_pass,
        "results_drop_sample": results_drop[:15],
        "cu_used_total": int(final_cu),
        "cu_breakdown": breakdown,
        "invariants": {"count": len(gaps), "gaps": gaps},
        "snapshot_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "latency_ms": ms,
        "format_renderers": ["scorecard", "plain", "telegram", "raw-json"],
    }
    return out


def _print_sw_plain(d: dict, args_ref=None):
    params = d["params"]
    lines = [f"🧠 Skill #9 · Top Smart Money Wallets — {params['depth_label']} {d['cu_used_total']} CU · chain={params['chain']}"]
    lines.append(f"   Weights: WinRate{params['weights']['winrate']} + PnL{params['weights']['pnl']} + SMRank{params['weights']['rank']} + DDinv{params['weights']['maxdd_inv']} = {sum(params['weights'].values())}pts | pass ≥ {params['pass_min']}")
    lines.append(f"   Scanned {d['total_wallets_scored']} wallets → PASS {d['total_pass']}, DROP {d['total_drop']}. Showing top {len(d['results_pass'])} wallets.")
    lines.append("")
    lines.append(f"{'#':>3}  {'WALLET (short)':<18}  {'NET WORTH':>12}  {'PERF 30d':>9}  {'WR':>6}  {'PNL×':>5}  {'SM RANK':>8}  {'SCORE':>6}/100  LAST ACT")
    for r in d["results_pass"]:
        nw = _fmt_usd(r["networth_usd"]) if isinstance(r.get("networth_usd"), (int, float)) else "N/A"
        p30 = _fmt_pct(r["perf_30d_pct"]) if isinstance(r.get("perf_30d_pct"), (int, float)) else "N/A"
        wr = f"{r['win_rate_pct']:.0f}%" if isinstance(r.get("win_rate_pct"), (int, float)) else "N/A"
        pnl = f"{r['pnl_multiple']:.1f}x" if isinstance(r.get("pnl_multiple"), (int, float)) else "N/A"
        sr = f"#{r['rank_sm_global']}" if isinstance(r.get("rank_sm_global"), int) else "N/A"
        sc = f"{r['score_composite']}"
        ttt = r.get("last_trade_time") or ""
        if isinstance(ttt, str) and "T" in ttt:
            ttt = ttt[5:16].replace("T"," ")
        lines.append(f"{r['rank']:>3}.  {r['wallet_short']:<18}  {nw:>12}  {p30:>9}  {wr:>6}  {pnl:>5}  {sr:>8}  {sc:>6}/{r['score_max_total']}  {ttt}")
    lines.append("")
    lines.append(f"CU breakdown: {', '.join(d['cu_breakdown'][:8])}{' …' if len(d['cu_breakdown'])>8 else ''}")
    footer_parts = [f"⚡CU {d['cu_used_total']}"]
    if d["invariants"]["count"]:
        footer_parts.append(f"⚠ {d['invariants']['count']} gaps")
    else:
        footer_parts.append("✅ invariants OK")
    footer_parts.append(f"⏱{d['latency_ms']}ms · 📸{d['snapshot_time']}")
    lines.append(" · ".join(footer_parts))
    print("\n".join(lines))


def _print_sw_telegram(d: dict, args_ref=None):
    params = d["params"]
    lines = [f"🧠 *Skill #9 · Smart Money Wallets — {params['depth_label']} {d['cu_used_total']}CU*"]
    lines.append(f"PASS {d['total_pass']} / {d['total_wallets_scored']} wallets scored · pass ≥ {params['pass_min']}")
    lines.append("")
    for r in d["results_pass"][:15]:
        nw = _fmt_usd(r["networth_usd"]) if isinstance(r.get("networth_usd"), (int, float)) else "N/A"
        p30 = _fmt_pct(r["perf_30d_pct"]) if isinstance(r.get("perf_30d_pct"), (int, float)) else "N/A"
        wr = f"{r['win_rate_pct']:.0f}%" if isinstance(r.get("win_rate_pct"), (int, float)) else "N/A"
        tags = "`" + "`, `".join(r["tags"][:3]) + "`" if r["tags"] else ""
        lines.append(f"#{r['rank']} `{r['wallet_short']}`")
        lines.append(f"  💰NetW {nw} · 📈30d {p30} · WR {wr} · ×{r.get('pnl_multiple') or '?'}")
        if tags: lines.append(f"  🏷 {tags}")
    lines.append(f"\n⚡{d['cu_used_total']}CU · 📸{d['snapshot_time']}")
    print("\n".join(lines))


def _print_sw_scorecard(d: dict, args_ref=None):
    params = d["params"]
    lines = [f"🧠 Smart Money Wallets SCORECARD — {params['depth_label']} · chain={params['chain']}"]
    lines.append(f"Scan depth: {params['depth_label']} ({d['cu_used_total']} CU)  ·  Pass ≥ {params['pass_min']}")
    lines.append(f"Weights: WR{params['weights']['winrate']}·PNL{params['weights']['pnl']}·RANK{params['weights']['rank']}·DD{params['weights']['maxdd_inv']} = {sum(params['weights'].values())}")
    lines.append(f"Result: PASS={d['total_pass']} · SCANNED={d['total_wallets_scored']} · DROP={d['total_drop']}")
    lines.append("")
    for i, r in enumerate(d["results_pass"][:10], 1):
        parts = [f"#{i} {r['wallet_short']}"]
        if isinstance(r.get("networth_usd"), (int, float)):
            parts.append(f"💰 {_fmt_usd(r['networth_usd'])}")
        if isinstance(r.get("perf_30d_pct"), (int, float)):
            parts.append(f"📈 {_fmt_pct(r['perf_30d_pct'])} 30d")
        if isinstance(r.get("win_rate_pct"), (int, float)):
            parts.append(f"🏆 WR {r['win_rate_pct']:.1f}%")
        if isinstance(r.get("pnl_multiple"), (int, float)):
            parts.append(f"×{r['pnl_multiple']:.2f}")
        lines.append("  ".join(parts))
    print("\n".join(lines))


def _render_sw_from_cache(payload: dict, fmt: str, run_id: str):
    if fmt in ("raw-json", "render"):
        out = {"runId": run_id, "cached": True, "cu_used_total": payload.get("cu_used_total", 0), "payload": payload}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if fmt == "telegram":
        _print_sw_telegram(payload)
    elif fmt == "scorecard":
        _print_sw_scorecard(payload)
    else:
        _print_sw_plain(payload)
    return 0


def cmd_smart_wallets(args):
    cdir = _cache_dir(getattr(args, "cache_dir", None))
    _prune_old_cache(cdir, max_age_hours=24)
    nocache: bool = bool(getattr(args, "nocache", False))
    from_cache: str | None = (None if nocache else (getattr(args, "from_cache", None) or None))
    write_cache: bool = bool(getattr(args, "write_cache", True))
    ident_prefix = f"sm_{args.chain}-{args.depth}"
    if nocache:
        removed = _delete_cache_prefix(cdir, ident_prefix)
        if removed:
            print(f"[nocache] removed {removed} stale smart-wallets cache file(s) prefix={ident_prefix!r}", file=sys.stderr)
    if from_cache:
        cached = _read_cache(cdir, from_cache)
        if not cached or cached.get("kind") != "smart-wallets":
            print(f"[E] Cache run_id not found or invalid: {from_cache}")
            return 3
        _render_sw_from_cache(cached, args.format, from_cache)
        return 0
    key = _load_key()
    if not key:
        print("[E] No BIRDEYE_API_KEY found.")
        return 1
    bl_raw = getattr(args, "blacklist", None) or ""
    blacklist: list[str] = []
    if bl_raw:
        for part in bl_raw.replace("\n", ",").split(","):
            p = part.strip()
            if p: blacklist.append(p)
    def clampw(v, mx):
        return max(0, min(mx * 2, int(v or 0)))
    try:
        d = _fetch_smart_wallets(key, args.chain,
                                 depth=str(args.depth),
                                 min_trades=max(0, int(args.min_trades or 0)),
                                 min_unique=max(0, int(args.min_unique or 0)),
                                 enforce_tag=bool(args.enforce_tag),
                                 blacklist=blacklist,
                                 w_wr=clampw(args.winrate, 40),
                                 w_pnl=clampw(args.pnl, 25),
                                 w_rank=clampw(args.rank, 20),
                                 w_dd=clampw(getattr(args, "dd_weight", 15), 15),
                                 pass_min=max(0, min(100, int(getattr(args, "pass_score", 70) or 70))),
                                 limit=max(1, min(500, int(getattr(args, "limit", 20) or 20))))
    except RuntimeError as e:
        print(str(e))
        return 2
    rid = None
    if write_cache:
        rid = _safe_run_id("sm", f"{args.chain}-{args.depth}-p{getattr(args, 'pass_score',70)}-w{getattr(args, 'winrate',40)}", tstamp=int(time.time()))
        fp = _write_cache(cdir, rid, d)
        print(f"#RUN_ID {rid}\t{fp.name}\tcu={d['cu_used_total']}")
    if args.format == "raw-json":
        out = {"runId": rid, "cached": False, "cu_used_total": d["cu_used_total"], "payload": d}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if args.format == "telegram":
        _print_sw_telegram(d)
    elif args.format == "scorecard":
        _print_sw_scorecard(d)
    else:
        _print_sw_plain(d)
    return 0


# ============================================================
# History list + render
# ============================================================

def cmd_history_list(args):
    cdir = _cache_dir(getattr(args, "cache_dir", None))
    _prune_old_cache(cdir, max_age_hours=24)
    items: list[dict] = []
    for fp in cdir.glob("*.json"):
        try:
            if not fp.is_file():
                continue
            m = fp.stat()
            raw = json.loads(fp.read_text(encoding="utf-8"))
            kind = raw.get("kind") or "unknown"
            params = raw.get("params") or {}
            title = {
                "trending-list": f"{params.get('source','?')} · {params.get('interval')} · {params.get('sort_by')} · {params.get('chain','sol')}",
                "token-dd": f"{params.get('chain','sol')} · {params.get('address','')[:8]}…{(params.get('address','') or '')[-4:]}",
                "smart-wallets": f"{params.get('depth_label', params.get('depth','?'))} · chain={params.get('chain','sol')} · pass≥{params.get('pass_min','?')}",
            }.get(kind, "run")
            extra1 = {
                "trending-list": f"{raw.get('total_tokens', len(raw.get('rows',[])))} tokens",
                "token-dd": f"{raw.get('symbol') or raw.get('address') or ''} · score {raw.get('scores',{}).get('final','?')}",
                "smart-wallets": f"PASS {raw.get('total_pass', len(raw.get('results_pass',[])))} · {raw.get('cu_used_total','?')}CU",
            }.get(kind, "")
            items.append({
                "runId": fp.stem,
                "kind": kind,
                "saved_at_unix": int(m.st_mtime),
                "saved_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(m.st_mtime)),
                "cu_used_total": raw.get("cu_used_total") or raw.get("payload", {}).get("cu_used_total", 0),
                "snapshot_time": raw.get("snapshot_time") or "",
                "title": title,
                "detail": extra1,
                "file_path": str(fp),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x["saved_at_unix"], reverse=True)
    items = items[: max(1, int(getattr(args, "limit", 25) or 25))]
    if args.format == "raw-json":
        print(json.dumps({"items": items}, ensure_ascii=False))
        return 0
    lines = [f"# Recent runs (showing {len(items)})"]
    lines.append(f"{'RUN':<3}  {'ID (short)':<52}  {'Kind':<13}  {'Score/Info':<22}  {'CU':>6}  Saved ago")
    for i, it in enumerate(items, 1):
        ago_s = max(1, int(time.time() - it["saved_at_unix"]))
        if ago_s < 60:
            ago = f"{ago_s}s"
        elif ago_s < 3600:
            ago = f"{ago_s//60}m"
        else:
            ago = f"{ago_s//3600}h{((ago_s%3600)//60)}m"
        rid_short = (it["runId"][:48] + "…" + it["runId"][-3:]) if len(it["runId"]) > 52 else it["runId"]
        info = it["detail"] or (it["snapshot_time"] and it["snapshot_time"][-8:]) or it["title"]
        lines.append(f"  #{i:<2}  {rid_short:<52}  {it['kind']:<13}  {str(info):<22}  {it['cu_used_total']:>6}  {ago}")
    print("\n".join(lines))
    return 0


# ============================================================
# Skill #11 — Wallet Style (trading-style tagger)
# Classifies wallets by frequency × P&L grid onto Birdeye data.
# 4×5 freq×PnL grid → 20 main titles + speed subtitle + badges.
# Constants imported from modules/wallet_data.py
# ============================================================

_WSF_GRID = _wd._WSF_GRID
_WSF_FREQ_LEVELS = _wd._WSF_FREQ_LEVELS
_WSF_DAY_SECONDS = _wd._WSF_DAY_SECONDS


def _wsf_fetch_tx_list(session, key, chain_full, wallet, limit=100):
    """GET /v1/wallet/tx_list → wallet trade history.

    Returns (raw_json, cu). cu estimated ~30 (beta endpoint).
    """
    url = f"{BIRDEYE_BASE}/v1/wallet/tx_list"
    headers = {"x-chain": chain_full, "X-API-KEY": key}
    params = {"wallet": wallet, "limit": min(int(limit or 100), 100)}
    r = session.get(url, headers=headers, params=params, timeout=60)
    try:
        j = r.json()
    except Exception:
        j = {}
    return j, 30


def _ws_fetch_trader_txs(session, key, chain_full, wallet, after_time, limit=100, max_pages=50):
    """GET /trader/txs/seek_by_time → all swap items from after_time onward.

    12 CU per page. Paginates until has_next=False or max_pages reached.
    `after_time` is a unix epoch seconds (lower bound).
    Returns (raw_json with merged items, total_cu).
    """
    url = f"{BIRDEYE_BASE}/trader/txs/seek_by_time"
    headers = {"x-chain": chain_full, "X-API-KEY": key}
    all_items = []
    total_cu = 0
    cur_after = int(after_time)
    seen_hashes = set()

    for page in range(int(max_pages or 50)):
        params = {
            "address": wallet,
            "limit": min(int(limit or 100), 100),
            "after_time": cur_after,
            "tx_type": "swap",
        }
        r = session.get(url, headers=headers, params=params, timeout=60)
        total_cu += 12
        try:
            j = r.json()
        except Exception:
            j = {}
        data = j.get("data") or {}
        items = data.get("items") or []
        if not isinstance(items, list) or not items:
            break
        new_items = 0
        for it in items:
            txh = it.get("tx_hash") or it.get("transactionHash")
            if txh and txh in seen_hashes:
                continue
            if txh:
                seen_hashes.add(txh)
            all_items.append(it)
            new_items += 1
        if not data.get("has_next") or new_items == 0:
            break
        # Advance after_time to the last item's block_unix_time
        last_ts = 0
        for it in items:
            try:
                last_ts = max(last_ts, int(it.get("block_unix_time") or 0))
            except Exception:
                pass
        if last_ts <= cur_after:
            break
        cur_after = last_ts

    return {"data": {"items": all_items, "has_next": False}, "success": True}, total_cu


def _ws_fetch_networth_history(session, key, wallet, count=90, type_="1d"):
    """GET /wallet/v2/net-worth → daily net-worth history.

    50 CU per request. Solana only. Returns (raw_json, cu).
    """
    url = f"{BIRDEYE_BASE}/wallet/v2/net-worth"
    headers = {"x-chain": "solana", "X-API-KEY": key}
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    params = {
        "wallet": wallet,
        "type": type_,
        "time": time_str,
        "direction": "back",
        "count": min(int(count or 90), 90),
    }
    r = session.get(url, headers=headers, params=params, timeout=60)
    try:
        j = r.json()
    except Exception:
        j = {}
    return j, 50


def _smp_build_swaps_from_trader_txs(trader_txs_raw, pnl_token_addrs=None):
    """Parse /trader/txs/seek_by_time into a clean swap list with multi-hop chaining.

    For each tx_hash, collect all legs (from_token → to_token). Then chain them:
    if a tx has A→B, B→C, C→D the result is a single swap A→D (intermediates dropped).
    Only keep swaps where at least one endpoint is in `pnl_token_addrs` (when provided).

    Returns list of {from_token, from_symbol, to_token, to_symbol, from_usd, to_usd, ts, tx_hash}.
    """
    swaps = []
    if not isinstance(trader_txs_raw, dict):
        return swaps
    items = ((trader_txs_raw.get("data") or {}).get("items") or [])
    if not isinstance(items, list):
        return swaps

    by_tx = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        txh = it.get("tx_hash") or it.get("transactionHash") or "no_hash"
        by_tx.setdefault(txh, []).append(it)

    pnl_set = set(pnl_token_addrs) if pnl_token_addrs else None

    for txh, tx_items in by_tx.items():
        legs = []
        ts = 0
        for it in tx_items:
            try:
                ts = max(ts, int(it.get("block_unix_time") or 0))
            except Exception:
                pass
            quote = it.get("quote") or {}
            base = it.get("base") or {}
            from_leg = None
            to_leg = None
            for leg in (quote, base):
                if not isinstance(leg, dict):
                    continue
                ts_ = leg.get("type_swap")
                if ts_ == "from":
                    from_leg = leg
                elif ts_ == "to":
                    to_leg = leg
            if from_leg and to_leg:
                fa = str(from_leg.get("address") or "")
                fb = str(to_leg.get("address") or "")
                if not fa or not fb or fa == fb:
                    continue
                from_ui = float(from_leg.get("ui_amount") or 0.0)
                from_price = float(from_leg.get("price") or from_leg.get("nearest_price") or 0.0)
                to_ui = float(to_leg.get("ui_amount") or 0.0)
                to_price = float(to_leg.get("price") or to_leg.get("nearest_price") or 0.0)
                legs.append({
                    "from": fa,
                    "from_sym": str(from_leg.get("symbol") or ""),
                    "from_usd": from_ui * from_price,
                    "from_amount": from_ui,
                    "to": fb,
                    "to_sym": str(to_leg.get("symbol") or ""),
                    "to_usd": to_ui * to_price,
                    "to_amount": to_ui,
                })

        if not legs:
            continue

        from_map = {}
        all_tos = set()
        all_froms = set()
        for lg in legs:
            f = lg["from"]
            all_froms.add(f)
            all_tos.add(lg["to"])
            if f not in from_map or lg["from_usd"] > from_map[f]["from_usd"]:
                from_map[f] = lg

        sources = all_froms - all_tos
        if not sources:
            sources = all_froms

        seen_pairs = set()
        for src in sources:
            cur = src
            path_from_usd = None
            path_to_usd = None
            path_from_sym = None
            path_to_sym = None
            path_from_amount = None
            path_to_amount = None
            visited = set()
            while cur in from_map and cur not in visited:
                lg = from_map[cur]
                if path_from_usd is None:
                    path_from_usd = lg["from_usd"]
                    path_from_sym = lg["from_sym"]
                    path_from_amount = lg.get("from_amount")
                path_to_usd = lg["to_usd"]
                path_to_sym = lg["to_sym"]
                path_to_amount = lg.get("to_amount")
                visited.add(cur)
                cur = lg["to"]
            if path_from_usd is not None and path_to_usd is not None:
                pair = (src, cur)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                if pnl_set is not None and src not in pnl_set and cur not in pnl_set:
                    continue
                swaps.append({
                    "from_token": src,
                    "from_symbol": path_from_sym or "?",
                    "to_token": cur,
                    "to_symbol": path_to_sym or "?",
                    "from_usd": round(path_from_usd, 4),
                    "to_usd": round(path_to_usd, 4),
                    "from_amount": path_from_amount or 0.0,
                    "to_amount": path_to_amount or 0.0,
                    "ts": ts,
                    "tx_hash": txh,
                })

    swaps.sort(key=lambda x: x["ts"])
    return swaps


def _wsf_extract_tx_trades(tx_list_raw, wallet):
    """From /v1/wallet/tx_list response, return list of trade dicts.

    Each trade: {token, side ('buy'|'sell'), ts (epoch), sol_amount, token_amount, fee_native}
    Heuristic: per tx, inspect balanceChange. A buy = token amount >0 and SOL amount <0.
    A sell = token amount <0 and SOL amount >0. Skip transfers (only SOL changes or >2 legs).
    """
    trades = []
    if not isinstance(tx_list_raw, dict):
        return trades
    data = tx_list_raw.get("data") or {}
    # data is keyed by chain name (e.g. 'solana')
    rows = []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                rows.extend(v)
    elif isinstance(data, list):
        rows = data
    wallet_l = str(wallet).lower()
    NATIVE_SYMBOLS = {"sol", "eth", "bnb", "matic", "arb", "avax", "ftm", "btc", "wbtc", "usdc", "usdt", "wif"}
    native_addrs = {
        "So11111111111111111111111111111111111111112",
        "0x0000000000000000000000000000000000000000",
    }
    for tx in rows:
        if not isinstance(tx, dict):
            continue
        try:
            ts = int(tx.get("blockUnixTime") or 0)
        except Exception:
            ts = 0
        if not ts:
            bt = tx.get("blockTime")
            if isinstance(bt, str) and bt:
                try:
                    from datetime import datetime
                    ts = int(datetime.fromisoformat(bt.replace("Z", "+00:00")).timestamp())
                except Exception:
                    ts = 0
        bc = tx.get("balanceChange") or []
        if not isinstance(bc, list):
            continue
        # find native leg and token leg
        native_amt = 0.0
        token_entries = []
        for leg in bc:
            if not isinstance(leg, dict):
                continue
            addr = str(leg.get("address") or "")
            sym = str(leg.get("symbol") or "").lower()
            amt = float(leg.get("amount") or 0.0)
            if addr in native_addrs or sym in NATIVE_SYMBOLS or sym == chain_short_for_native():
                native_amt += amt
            elif addr:
                token_entries.append((addr, amt, sym))
        # A swap has exactly one token leg (ignoring dust). Use the largest |amount| token leg.
        if not token_entries:
            continue
        token_entries.sort(key=lambda x: abs(x[1]), reverse=True)
        token_addr, token_amt, token_sym = token_entries[0]
        if token_amt > 0 and native_amt < 0:
            side = "buy"
        elif token_amt < 0 and native_amt > 0:
            side = "sell"
        else:
            continue
        fee = tx.get("fee")
        try:
            fee = float(fee) if fee is not None else 0.0
        except Exception:
            fee = 0.0
        trades.append({
            "token": token_addr,
            "side": side,
            "ts": ts,
            "sol_amount": abs(native_amt),
            "token_amount": abs(token_amt),
            "fee_native": fee,
        })
    return trades


def chain_short_for_native():
    """Helper to detect native token symbol from balanceChange (best-effort)."""
    return ""


def _wsf_median(values):
    s = sorted(v for v in values if v is not None)
    if not s:
        return None
    n = len(s)
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _wsf_compute(pnl_summary, per_token, first_funded, tx_trades, duration, wallet=None,
                 skip_tx_list=False, **_ignored):
    """Compute wallet style from Birdeye data.

    Returns dict with: main_title, freq, pnl_level, speed, badges, metrics,
    pnl_buckets, signals.
    """
    # --- Extract summary fields ---
    data = pnl_summary.get("data") if isinstance(pnl_summary, dict) else None
    summary = data.get("summary") if isinstance(data, dict) else None
    if not isinstance(summary, dict):
        summary = {}
    counts = summary.get("counts") or {}
    cashflow = summary.get("cashflow_usd") or {}
    pnl = summary.get("pnl") or {}

    total_buy = int(counts.get("total_buy") or 0)
    total_sell = int(counts.get("total_sell") or 0)
    total_trade = int(counts.get("total_trade") or total_buy + total_sell)
    unique_tokens = int(counts.get("unique_tokens") or summary.get("unique_tokens") or 0)
    total_win = int(counts.get("total_win") or 0)
    total_loss = int(counts.get("total_loss") or 0)
    wr_raw = counts.get("win_rate")
    if isinstance(wr_raw, (int, float)):
        wr_norm = _ws_to_fraction([wr_raw])[0]
    elif total_win + total_loss > 0:
        wr_norm = _ws_clamp(total_win / (total_win + total_loss), 0.0, 1.0)
    else:
        wr_norm = 0.0

    invested = float(cashflow.get("total_invested") or 0.0)
    realized_usd = float(pnl.get("realized_profit_usd") or pnl.get("realized_usd") or 0.0)
    unrealized_usd = float(pnl.get("unrealized_usd") or 0.0)

    # return ratio = realized / cost basis (realized_profit_pnl equivalent)
    pnl_ratio = (realized_usd / invested) if invested > 0 else 0.0

    days = _WSF_DAY_SECONDS.get(duration, 30)
    trades = max(total_buy + total_sell, total_trade)
    per_day = trades / days if days > 0 else 0.0

    # --- Frequency axis ---
    freq_key = "L1"
    freq_name = "Rare"
    for lo, hi, k, nm in _WSF_FREQ_LEVELS:
        if (lo is None or per_day >= lo) and (hi is None or per_day < hi):
            freq_key, freq_name = k, nm
            break

    # --- P&L buckets from per-token details ---
    buckets = {"gt_5x": 0, "2x_5x": 0, "0x_2x": 0, "nd5_0x": 0, "lt_nd5": 0}
    token_scan = 0
    if isinstance(per_token, dict):
        per_data = per_token.get("data") or {}
        tk = per_data.get("tokens")
        toks = tk if isinstance(tk, list) else (list(tk.values()) if isinstance(tk, dict) else [])
        for t in toks:
            if not isinstance(t, dict):
                continue
            tpnl = t.get("pnl") or {}
            rpp = tpnl.get("realized_profit_percent")
            if not isinstance(rpp, (int, float)):
                continue
            token_scan += 1
            rpp = float(rpp)
            # normalize percent → ratio
            if rpp > 1.5:
                rpp = rpp / 100.0
            if rpp >= 5.0:
                buckets["gt_5x"] += 1
            elif rpp >= 2.0:
                buckets["2x_5x"] += 1
            elif rpp >= 0.0:
                buckets["0x_2x"] += 1
            elif rpp >= -0.05:
                buckets["nd5_0x"] += 1
            else:
                buckets["lt_nd5"] += 1
    token_num = max(unique_tokens, token_scan)
    lt50_share = buckets["lt_nd5"] / max(1, token_num)

    # --- P&L axis (test in order, stop at first match) ---
    pnl_level = "P3"
    if pnl_ratio > 0.5 and token_num >= 5 and (wr_norm >= 0.5 or lt50_share < 0.15):
        pnl_level = "P5"
    elif pnl_ratio > 0.1:
        pnl_level = "P4"
    elif lt50_share >= 0.40 and realized_usd < 0:
        pnl_level = "P1"
    elif abs(pnl_ratio) <= 0.10:
        pnl_level = "P3"
    elif realized_usd < 0 or pnl_ratio < 0:
        pnl_level = "P2"
    else:
        pnl_level = "P3"

    cell = _WSF_GRID.get((freq_key, pnl_level), _WSF_GRID[("L2", "P3")])
    main_title = {"emoji": cell[0], "en": cell[1], "meaning": cell[2],
                  "freq": freq_key, "pnl": pnl_level}

    # --- Speed subtitle (median copy window from tx trades) ---
    speed = None
    cw_n = 0
    cw_s = None
    if tx_trades:
        by_token = {}
        for tr in tx_trades:
            by_token.setdefault(tr["token"], []).append(tr)
        gaps = []
        for tok, trs in by_token.items():
            trs_sorted = sorted(trs, key=lambda x: x["ts"])
            first_buy = None
            for tr in trs_sorted:
                if tr["side"] == "buy" and first_buy is None:
                    first_buy = tr["ts"]
                elif tr["side"] == "sell" and first_buy is not None and tr["ts"] >= first_buy:
                    gaps.append(tr["ts"] - first_buy)
                    break
        cw_n = len(gaps)
        if cw_n >= 3:
            cw_s = _wsf_median(gaps)
            if cw_s is not None and cw_s > 0:
                if cw_s < 60:
                    speed = ("⚡", "Flash Flipper", cw_s, cw_n)
                elif cw_s < 86400:
                    speed = ("🐇", "Intraday", cw_s, cw_n)
                elif cw_s < 7 * 86400:
                    speed = ("🧭", "Swing", cw_s, cw_n)
                else:
                    speed = ("💎", "Long Hold", cw_s, cw_n)

    # --- Wallet age (first-funded) ---
    wallet_age_days = None
    if isinstance(first_funded, dict):
        wdata = first_funded.get("data") or {}
        if isinstance(wdata, dict) and wallet:
            w_info = wdata.get(wallet)
            if isinstance(w_info, dict):
                ts = w_info.get("block_unix_time")
                if ts:
                    try:
                        wallet_age_days = max(0, int((time.time() - float(ts)) / 86400))
                    except Exception:
                        wallet_age_days = None

    # --- Badges (orthogonal, all that trigger) ---
    badges = []
    if wr_norm < 0.35 and buckets["gt_5x"] >= 1:
        badges.append(("🎰", "Lottery", f"WR {wr_norm*100:.0f}% but {buckets['gt_5x']}× 5x+ wins"))
    # scaling in / out (need tx trades)
    if tx_trades:
        buys_per = {}
        sells_per = {}
        for tr in tx_trades:
            if tr["side"] == "buy":
                buys_per[tr["token"]] = buys_per.get(tr["token"], 0) + 1
            else:
                sells_per[tr["token"]] = sells_per.get(tr["token"], 0) + 1
        n_tok = max(1, len(set(list(buys_per) + list(sells_per))))
        avg_buys = sum(buys_per.values()) / n_tok if n_tok else 0
        avg_sells = sum(sells_per.values()) / n_tok if n_tok else 0
        if avg_buys >= 3:
            badges.append(("🧱", "Scale-In", f"avg {avg_buys:.1f} buys/token"))
        if avg_sells >= 3:
            badges.append(("✂️", "Scale-Out", f"avg {avg_sells:.1f} sells/token"))
        # fixed time window
        if len(tx_trades) >= 20:
            hour_buckets = [0] * 24
            import datetime as _dt
            for tr in tx_trades:
                if tr["ts"]:
                    hour_buckets[_dt.datetime.utcfromtimestamp(tr["ts"]).hour] += 1
            for s in range(24):
                window_sum = sum(hour_buckets[(s + i) % 24] for i in range(6))
                if window_sum / len(tx_trades) >= 0.70:
                    badges.append(("🌙", "Fixed Window", f"{window_sum}/{len(tx_trades)} tx in 6h window"))
                    break
    # hoarding / distributing (from summary counts)
    if total_sell > 0 and total_buy / total_sell >= 3:
        badges.append(("🧊", "Hoarding", f"buy/sell = {total_buy/total_sell:.1f}"))
    elif total_sell == 0 and total_buy > 0:
        badges.append(("🧊", "Hoarding", f"{total_buy} buys, 0 sells"))
    if total_buy > 0 and total_sell / total_buy >= 3:
        badges.append(("📤", "Distributing", f"sell/buy = {total_sell/total_buy:.1f}"))
    elif total_buy == 0 and total_sell > 0:
        badges.append(("📤", "Distributing", f"{total_sell} sells, 0 buys"))
    # whale
    if total_buy > 0 and invested / total_buy >= 10000:
        badges.append(("🐋", "Whale", f"avg ${invested/total_buy:,.0f}/buy"))
    # new wallet
    if wallet_age_days is not None and wallet_age_days < 30:
        badges.append(("🆕", "New Wallet", f"{wallet_age_days} days old"))
    # sample insufficiency
    if total_buy + total_sell < 20:
        badges.append(("⚠️", "Thin Sample", f"{duration} only {total_buy + total_sell} trades"))

    metrics = {
        "total_buy": total_buy,
        "total_sell": total_sell,
        "total_trade": trades,
        "unique_tokens": unique_tokens,
        "token_scan": token_scan,
        "win_rate": round(wr_norm, 4),
        "realized_pnl_usd": round(realized_usd, 2),
        "unrealized_pnl_usd": round(unrealized_usd, 2),
        "total_invested_usd": round(invested, 2),
        "pnl_ratio": round(pnl_ratio, 6),
        "per_day": round(per_day, 2),
        "wallet_age_days": wallet_age_days,
        "duration_days": days,
    }

    return {
        "main_title": main_title,
        "freq": {"key": freq_key, "name": freq_name, "per_day": round(per_day, 2)},
        "pnl_level": pnl_level,
        "speed": speed,
        "badges": badges,
        "pnl_buckets": buckets,
        "metrics": metrics,
        "signals": {
            "lt50_share": round(lt50_share, 4),
            "cw_n": cw_n,
            "cw_s": cw_s,
        },
    }


def _wsf_human_seconds(s):
    if s is None:
        return "N/A"
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s/60:.1f}m"
    if s < 86400:
        return f"{s/3600:.1f}h"
    days = s / 86400.0
    if days < 10:
        return f"{days:.2f}d"
    if days < 100:
        return f"{days:.1f}d"
    return f"{days:.0f}d"


def _wsf_format_rendered_html(result, wallet, chain_short, duration, cu, rid):
    import html as _html_mod
    esc = lambda s: _html_mod.escape("" if s is None else str(s), quote=True)
    mt = result["main_title"]
    freq = result["freq"]
    speed = result["speed"]
    badges = result["badges"]
    m = result["metrics"]
    bk = result["pnl_buckets"]

    # Color by P&L level
    color_map = {"P5": "#22c55e", "P4": "#84cc16", "P3": "#94a3b8", "P2": "#fb923c", "P1": "#ef4444"}
    color = color_map.get(mt["pnl"], "#94a3b8")
    w_short = wallet[:10] + "…" + wallet[-8:] if len(wallet) > 22 else wallet

    badges_html = ""
    if badges:
        badges_html = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px">' + "".join(
            f'<span style="display:inline-block;padding:3px 9px;border-radius:999px;background:#132038;border:1px solid #2b436d;color:#cfe0ff;font-size:11.5px;font-weight:600" title="{esc(b[2])}">{b[0]} {esc(b[1])}</span>'
            for b in badges
        ) + "</div>"
    else:
        badges_html = '<div style="font-size:11.5px;color:#6f86a7;margin-top:10px">No extra badges triggered.</div>'

    speed_html = ""
    if speed:
        speed_html = (f'<div style="font-size:13px;color:#c7d2fe;margin-top:4px;font-weight:600">'
                      f'{speed[0]} {esc(speed[1])} <span style="color:#8fa3c2;font-weight:500">· '
                      f'median copy window {_wsf_human_seconds(speed[2])} (n={speed[3]})</span></div>')
    else:
        speed_html = '<div style="font-size:11.5px;color:#6f86a7;margin-top:4px">⏱ Speed: sample too thin (need ≥3 round trips)</div>'

    grid_html = ""
    pnl_order = ["P5", "P4", "P3", "P2", "P1"]
    freq_order = ["L4", "L3", "L2", "L1"]
    freq_names = {"L4": "Machine", "L3": "Frequent", "L2": "Regular", "L1": "Rare"}
    pnl_names = {"P5": "Strong Profit", "P4": "Net Profit", "P3": "Break-Even", "P2": "Net Loss", "P1": "Heavy Loss"}
    cells = []
    for fk in freq_order:
        row = []
        for pk in pnl_order:
            c = _WSF_GRID[(fk, pk)]
            is_active = (fk == freq["key"] and pk == mt["pnl"])
            bg = f"background:{color}" if is_active else "background:#0a1429"
            fg = "color:#0a1220" if is_active else f"color:{color_map.get(pk,'#94a3b8')}"
            row.append(f'<div style="padding:7px 5px;border-radius:7px;border:1px solid #2b436d;text-align:center;font-size:11px;font-weight:800;{bg};{fg}">{c[0]} {c[1]}</div>')
        cells.append("".join(row))
    grid_html = (
        '<div style="margin-top:12px;padding:10px;border:1px solid #263a5e;border-radius:12px;background:#0a1220">'
        '<div style="font-size:10px;color:#6f86a7;font-weight:800;letter-spacing:.5px;margin-bottom:6px">4×5 STYLE GRID · row=frequency · col=P&L</div>'
        '<div style="display:grid;grid-template-columns:60px repeat(5,1fr);gap:5px;align-items:stretch">'
        '<div></div>' + "".join(f'<div style="text-align:center;font-size:10px;color:#8fa3c2;font-weight:700">{pnl_names[p]}</div>' for p in pnl_order)
        + "".join(
            f'<div style="display:flex;align-items:center;font-size:10px;color:#8fa3c2;font-weight:700">{freq_names[f]}</div>{cells[i]}'
            for i, f in enumerate(freq_order)
        )
        + '</div></div>'
    )

    metrics_html = (
        '<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:12px">'
        f'<div style="padding:8px 10px;border-radius:9px;border:1px solid #2b426a;background:#0a1429"><div style="font-size:10px;color:#8fa3c2">Trades {duration}</div><div style="font-size:15px;font-weight:800;color:#e6edf8">{m["total_trade"]:,} <span style="font-size:10px;color:#8fa3c2">({freq["per_day"]}/d)</span></div></div>'
        f'<div style="padding:8px 10px;border-radius:9px;border:1px solid #2b426a;background:#0a1429"><div style="font-size:10px;color:#8fa3c2">Win Rate</div><div style="font-size:15px;font-weight:800;color:#eadcff">{m["win_rate"]*100:.1f}%</div></div>'
        f'<div style="padding:8px 10px;border-radius:9px;border:1px solid #2b426a;background:#0a1429"><div style="font-size:10px;color:#8fa3c2">Realized PnL</div><div style="font-size:15px;font-weight:800;color:{"#8be0a0" if m["realized_pnl_usd"]>=0 else "#ff9bb0"}">${m["realized_pnl_usd"]:,.0f}</div></div>'
        f'<div style="padding:8px 10px;border-radius:9px;border:1px solid #2b426a;background:#0a1429"><div style="font-size:10px;color:#8fa3c2">Return ratio</div><div style="font-size:15px;font-weight:800;color:{"#8be0a0" if m["pnl_ratio"]>=0 else "#ff9bb0"}">{m["pnl_ratio"]*100:+.1f}%</div></div>'
        '</div>'
    )

    buckets_html = (
        '<div style="margin-top:10px;padding:8px 10px;border:1px solid #2b426a;border-radius:9px;background:#0a1429">'
        '<div style="font-size:10px;color:#8fa3c2;font-weight:800;letter-spacing:.5px">P&L BUCKETS (per token realized %)</div>'
        '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:5px">'
        + "".join(
            f'<div style="text-align:center"><div style="font-size:15px;font-weight:800;color:{color_map.get(p,"#94a3b8")}">{bk[k]}</div><div style="font-size:9.5px;color:#8fa3c2">{label}</div></div>'
            for k, p, label in [("gt_5x","P5","5x+"),("2x_5x","P4","2-5x"),("0x_2x","P3","0-2x"),("nd5_0x","P2","-5..0%"),("lt_nd5","P1","<-5%")]
        )
        + '</div></div>'
    )

    cu_total = _ws_total_cu(cu)
    html = (
        f'<div class="render-wallet-style" style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        f'background:#0b1222;color:#e6edf8;padding:16px;border-radius:14px;border:1px solid #263a5e;max-width:760px">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap">'
        f'<div>'
        f'<div style="font-size:10px;color:#6f86a7;font-weight:800;letter-spacing:1px">SKILL #11 · WALLET STYLE</div>'
        f'<div style="font-size:26px;font-weight:900;color:{color};line-height:1.2;margin-top:4px">{mt["emoji"]} {esc(mt["en"])}</div>'
        f'<div style="font-size:12px;color:#8fa3c2;margin-top:2px">{esc(mt["meaning"])}</div>'
        f'{speed_html}'
        f'<div style="font-size:11px;color:#9cb4d8;margin-top:3px"><span class="copy-addr" data-copy-addr="{esc(wallet)}" style="cursor:pointer;user-select:none" title="Click to copy full wallet address">@{esc(w_short)} 📋</span> · {esc(chain_short.upper())} · {esc(duration)}'
        f'{f" · age {m["wallet_age_days"]}d" if m.get("wallet_age_days") is not None else ""}</div>'
        f'</div>'
        f'<div style="text-align:right">'
        f'<span style="display:inline-block;padding:3px 9px;border-radius:999px;background:#1e2b1f;border:1px solid #375a3a;color:#8be0a0;font-size:11px;font-weight:700">⚡ {cu_total} CU</span>'
        f'<div style="font-size:10px;color:#6f86a7;margin-top:4px">freq {freq["name"]} · P&L {pnl_names[mt["pnl"]]}</div>'
        f'</div>'
        f'</div>'
        f'{metrics_html}'
        f'{buckets_html}'
        f'{badges_html}'
        f'{grid_html}'
        f'</div>'
    )
    return html


def _wsf_format_plain(result, wallet, chain_short, duration, cu, rid):
    mt = result["main_title"]
    freq = result["freq"]
    speed = result["speed"]
    badges = result["badges"]
    m = result["metrics"]
    bk = result["pnl_buckets"]
    pnl_names = {"P5": "Strong Profit", "P4": "Net Profit", "P3": "Break-Even", "P2": "Net Loss", "P1": "Heavy Loss"}
    lines = [
        "=" * 56,
        f"  🧠 WALLET STYLE · {mt['emoji']} {mt['en']}",
        "=" * 56,
        f"  Wallet : {wallet}",
        f"  Chain  : {chain_short.upper()} · {duration}",
        f"  Freq   : {freq['name']} ({freq['per_day']} trades/day) → {freq['key']}",
        f"  P&L    : {pnl_names[mt['pnl']]} (level {mt['pnl']})",
        f"  Meaning: {mt['meaning']}",
    ]
    if speed:
        lines.append(f"  Speed  : {speed[0]} {speed[1]} · median copy window {_wsf_human_seconds(speed[2])} (n={speed[3]})")
    else:
        lines.append("  Speed  : — (sample too thin)")
    lines += [
        "-" * 56,
        f"  Trades   : {m['total_trade']:,} (buy {m['total_buy']} / sell {m['total_sell']})",
        f"  Tokens   : {m['unique_tokens']} unique",
        f"  Win Rate : {m['win_rate']*100:.1f}%",
        f"  Realized : ${m['realized_pnl_usd']:,.0f} · Unrealized ${m['unrealized_pnl_usd']:,.0f}",
        f"  Return   : {m['pnl_ratio']*100:+.2f}%  (invested ${m['total_invested_usd']:,.0f})",
        f"  Buckets  : 5x+={bk['gt_5x']}  2-5x={bk['2x_5x']}  0-2x={bk['0x_2x']}  -5..0%={bk['nd5_0x']}  <-5%={bk['lt_nd5']}",
        f"  WalletAge: {m.get('wallet_age_days')} days" if m.get('wallet_age_days') is not None else "  WalletAge: N/A",
    ]
    if badges:
        lines.append("-" * 56)
        lines.append("  Badges:")
        for b in badges:
            lines.append(f"    {b[0]} {b[1]}  —  {b[2]}")
    else:
        lines.append("  Badges: (none)")
    lines += ["=" * 56, f"  ⚡ {_ws_total_cu(cu)} CU · runId={rid}"]
    return "\n".join(lines)


def _wsf_format_telegram(result, wallet, chain_short, duration, cu, rid):
    mt = result["main_title"]
    freq = result["freq"]
    speed = result["speed"]
    badges = result["badges"]
    m = result["metrics"]
    pnl_names = {"P5": "Strong Profit", "P4": "Net Profit", "P3": "Break-Even", "P2": "Net Loss", "P1": "Heavy Loss"}
    lines = [
        f"*{mt['emoji']} {mt['en']}*",
        f"━━━━━━━━━━━━━━━━━━",
        f"`{wallet[:10]}…{wallet[-6:]}` · {chain_short.upper()} · {duration}",
        f"📊 Freq `{freq['name']}` ({freq['per_day']}/d) · P&L `{pnl_names[mt['pnl']]}`",
    ]
    if speed:
        lines.append(f"⏱ {speed[0]} {speed[1]} · median {_wsf_human_seconds(speed[2])} (n={speed[3]})")
    lines += [
        f"🤝 Trades `{m['total_trade']:,}` · WR `{m['win_rate']*100:.1f}%`",
        f"💰 Realized `${m['realized_pnl_usd']:,.0f}` · Return `{m['pnl_ratio']*100:+.1f}%`",
    ]
    if badges:
        lines.append("🏷 " + "  ".join(f"{b[0]}{b[1]}" for b in badges[:8]))
    lines.append(f"⚡ {_ws_total_cu(cu)} CU")
    return "\n".join(lines)


def cmd_wallet_style(args):
    chain_short = args.chain
    chain_full = CHAINS.get(chain_short, chain_short)
    wallet = args.wallet.strip()
    duration = args.duration
    pnl_method = args.pnl_method
    fmt = args.format
    nocache = bool(getattr(args, "nocache", False))
    cdir_arg = getattr(args, "cache_dir", None)
    write_cache = bool(getattr(args, "write_cache", True))
    from_cache_runid = getattr(args, "from_cache", None)
    skip_tx_list = bool(args.skip_tx_list)
    skip_first_tx = bool(args.skip_first_tx)

    # Load key
    api_key = os.environ.get("BIRDEYE_API_KEY")
    if not api_key:
        cand = Path.home() / ".birdeye.env"
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if line.startswith("BIRDEYE_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    cdir = _cache_dir(cdir_arg)
    _prune_old_cache(cdir, max_age_hours=72)

    # 0-CU replay
    if from_cache_runid:
        cp = _cache_path(cdir, from_cache_runid)
        if not cp.exists():
            sys.stderr.write(f"[wallet-style] cache miss for run_id {from_cache_runid}\n")
            return 3
        payload = json.loads(cp.read_text(encoding="utf-8"))
        out = payload.get("rendered_" + fmt) or payload.get("out")
        if not out:
            out = json.dumps(payload, ensure_ascii=False, indent=2)
        print(out)
        return 0

    if not api_key:
        sys.stderr.write("[wallet-style] missing BIRDEYE_API_KEY.\n")
        return 2

    rid = _safe_run_id("wallet-style", f"{chain_short}_{wallet[:10]}_{duration}")
    cu = {}
    import requests as _req
    session = _req.Session()

    try:
        pnl_summary, cu["pnl_summary"] = _ws_fetch_pnl_summary(session, api_key, chain_full, wallet, duration, pnl_method)
        per_token, cu["pnl_details"] = _ws_fetch_pnl_per_token(session, api_key, chain_full, wallet, pnl_method, duration=duration)

        first_funded = {}
        cu["first_funded"] = 0
        if not skip_first_tx:
            # Reuse the permanent wallet_first_funded_cache.csv (immutable meta → never re-pay 40 CU)
            first_funded = _ws_first_funded_cache_get(cdir, wallet, chain_full)
            if first_funded is not None:
                cu["first_funded"] = 0
            else:
                first_funded, cu["first_funded"] = _ws_fetch_first_funded(session, api_key, chain_full, wallet)
                _ws_first_funded_cache_set(cdir, wallet, chain_full, first_funded)

        tx_trades = []
        cu["tx_list"] = 0
        if not skip_tx_list:
            tx_raw, cu["tx_list"] = _wsf_fetch_tx_list(session, api_key, chain_full, wallet, limit=100)
            tx_trades = _wsf_extract_tx_trades(tx_raw, wallet)
    except Exception as e:
        sys.stderr.write(f"[wallet-style] API error: {e}\n")
        return 4

    result = _wsf_compute(pnl_summary, per_token, first_funded, tx_trades, duration,
                          wallet=wallet, skip_tx_list=skip_tx_list)

    cu_total = _ws_total_cu(cu)
    params_snapshot = {
        "chain": chain_short, "wallet": wallet, "duration": duration, "pnl_method": pnl_method,
        "skip_tx_list": skip_tx_list, "skip_first_tx": skip_first_tx,
        "argv": sys.argv[1:],
    }

    out_plain = _wsf_format_plain(result, wallet, chain_short, duration, cu, rid)
    out_telegram = _wsf_format_telegram(result, wallet, chain_short, duration, cu, rid)
    raw_envelope = {
        "schemaVersion": 1,
        "kind": "wallet-style-v1",
        "runId": rid,
        "cached": False,
        "params": params_snapshot,
        "main_title": result["main_title"],
        "freq": result["freq"],
        "pnl_level": result["pnl_level"],
        "speed": result["speed"],
        "badges": result["badges"],
        "pnl_buckets": result["pnl_buckets"],
        "metrics": result["metrics"],
        "signals": result["signals"],
        "cu_used_total": cu_total,
        "cu_breakdown": cu,
        "snapshot_time": int(time.time()),
        "format_renderers": ["rendered", "plain", "telegram", "raw-json"],
    }
    out_raw_json = json.dumps(raw_envelope, ensure_ascii=False)
    html_rendered = _wsf_format_rendered_html(result, wallet, chain_short, duration, cu, rid)
    rendered_payload = dict(raw_envelope)
    rendered_payload["html"] = html_rendered
    out_rendered_json = json.dumps(rendered_payload, ensure_ascii=False, indent=2)

    if write_cache:
        file_payload = {
            "runId": rid,
            "kind": "wallet-style-v1",
            "cached": False,
            "cu_used_total": cu_total,
            "cu_breakdown": cu,
            "params": params_snapshot,
            "main_title": result["main_title"],
            "snapshot_time": int(time.time()),
            "rendered_plain": out_plain,
            "rendered_telegram": out_telegram,
            "rendered_raw-json": out_raw_json,
            "rendered_rendered": out_rendered_json,
            "out": out_plain,
        }
        _cache_path(cdir, rid).write_text(json.dumps(file_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    stdout_prefix = f"#RUN_ID {rid}\twallet-style\tcu={cu_total}\n"
    if fmt == "rendered":
        sys.stdout.write(stdout_prefix)
        print(out_rendered_json)
    elif fmt == "plain":
        sys.stdout.write(stdout_prefix)
        print(out_plain)
    elif fmt == "telegram":
        sys.stdout.write(stdout_prefix)
        print(out_telegram)
    else:
        sys.stdout.write(stdout_prefix)
        print(out_raw_json)
    return 0


# ════════════════════════════════════════════════════════════════════════════
# Skill #14 · Wallet Analysis — single-wallet deep-dive
#   profile / assets / trading / performance / risk  across user-selected intervals
# ════════════════════════════════════════════════════════════════════════════
_WA_DEFAULT_INTERVALS = ["24h", "7d", "30d", "90d", "all"]


def _wa_extract_summary(summary_resp):
    """Extract a /wallet/v2/pnl/summary response → flat dict of metrics for one interval."""
    data = (summary_resp or {}).get("data") if isinstance(summary_resp, dict) else None
    s = (data or {}).get("summary") if isinstance(data, dict) else None
    if not isinstance(s, dict):
        s = {}
    counts = s.get("counts") or {}
    cf = s.get("cashflow_usd") or {}
    pnl = s.get("pnl") or {}
    return {
        "counts": counts, "cashflow": cf, "pnl": pnl,
        "unique_tokens": int(counts.get("unique_tokens") or 0),
        "total_trade": int(counts.get("total_trade") or counts.get("total_tx_count") or 0),
        "total_buy": int(counts.get("total_buy") or 0),
        "total_sell": int(counts.get("total_sell") or 0),
        "total_win": int(counts.get("total_win") or 0),
        "total_loss": int(counts.get("total_loss") or 0),
        "win_rate_raw": counts.get("win_rate"),
        "invested": float(cf.get("total_invested") or 0.0),
        "sold": float(cf.get("total_sold") or 0.0),
        "current_value": float(cf.get("current_value") or 0.0),
        "realized_usd": float(pnl.get("realized_profit_usd") or pnl.get("realized_usd") or 0.0),
        "unrealized_usd": float(pnl.get("unrealized_usd") or 0.0),
        "total_pnl_usd": float(pnl.get("total_usd") or 0.0),
        "avg_profit_per_trade": float(pnl.get("avg_profit_per_trade_usd") or 0.0),
        "realized_pct_raw": pnl.get("realized_profit_percent"),
    }


def _wa_win_rate(s):
    wr = s.get("win_rate_raw")
    if isinstance(wr, (int, float)):
        v = _ws_to_fraction([wr])[0]
        return round(v * 100, 1)
    tw, tl = s.get("total_win", 0), s.get("total_loss", 0)
    if tw + tl > 0:
        return round(tw / (tw + tl) * 100, 1)
    return 0.0


def _wa_build_trading(s):
    inv = s["invested"]; sold = s["sold"]
    ratio = round(sold / inv, 4) if inv > 0 else 0.0
    return {
        "total_trade": s["total_trade"],
        "total_buy": s["total_buy"],
        "total_sell": s["total_sell"],
        "win_rate": _wa_win_rate(s),
        "unique_tokens": s["unique_tokens"],
        "total_invested": round(inv, 2),
        "total_sold": round(sold, 2),
        "sold_to_invested_ratio": ratio,
        "net_flow_usd": round(sold - inv, 2),
        "trade_selectivity": round(s["total_trade"] / s["unique_tokens"], 2) if s["unique_tokens"] > 0 else 0.0,
        "holding_bias": s["total_buy"] - s["total_sell"],
    }


def _wa_build_performance(s):
    inv = s["invested"]
    realized = s["realized_usd"]
    unrealized = s["unrealized_usd"]
    total = s["total_pnl_usd"] if s["total_pnl_usd"] else realized + unrealized
    rpct = s.get("realized_pct_raw")
    realized_pct = _ws_to_fraction([rpct])[0] * 100 if isinstance(rpct, (int, float)) else 0.0
    cap_eff = round(realized / inv, 4) if inv > 0 else 0.0
    pnl_per_trade = round(total / s["total_trade"], 2) if s["total_trade"] > 0 else 0.0
    cap_turnover = round(inv / abs(realized), 2) if realized != 0 else None
    realization_ratio = round(realized / (realized + abs(unrealized)), 4) if (realized + abs(unrealized)) > 0 else 0.0
    unrealized_risk = round(unrealized / inv, 4) if inv > 0 else 0.0
    return {
        "realized_profit_usd": round(realized, 2),
        "realized_profit_percent": round(realized_pct, 2),
        "unrealized_usd": round(unrealized, 2),
        "total_pnl_usd": round(total, 2),
        "roi": round(total / inv * 100, 2) if inv > 0 else 0.0,
        "avg_profit_per_trade_usd": round(s["avg_profit_per_trade"], 2),
        "capital_efficiency": cap_eff,
        "pnl_per_trade": pnl_per_trade,
        "capital_turnover": cap_turnover,
        "realization_ratio": realization_ratio,
        "unrealized_risk_ratio": unrealized_risk,
        "total_win": s["total_win"],
        "total_loss": s["total_loss"],
        "win_rate": _wa_win_rate(s),
    }


def _wa_round_trip_holds(tx_trades):
    """Compute hold durations from buy→sell round trips in tx_trades.
    Returns list of (hold_seconds, pnl_pct) tuples."""
    by_tok = {}
    for t in tx_trades:
        by_tok.setdefault(t["token"], []).append(t)
    out = []
    for tok, evs in by_tok.items():
        evs = sorted(evs, key=lambda x: x["ts"])
        i = 0
        while i < len(evs):
            if evs[i]["side"] == "buy":
                buy_sol = evs[i]["sol_amount"]
                buy_ts = evs[i]["ts"]
                j = i + 1
                while j < len(evs) and evs[j]["side"] != "sell":
                    j += 1
                if j < len(evs) and evs[j]["side"] == "sell":
                    sell_sol = evs[j]["sol_amount"]
                    hold = evs[j]["ts"] - buy_ts
                    pct = (sell_sol - buy_sol) / buy_sol * 100 if buy_sol > 0 else 0.0
                    out.append((hold, pct))
                    i = j + 1
                else:
                    i += 1
            else:
                i += 1
    return out


def _wa_infer_style(tx_trades, pnl_summary_map=None, per_token=None, portfolio=None):
    """Infer trading style.

    Primary signal: buy→sell round-trip hold durations from tx_list.
    Fallback when no round trips:
      - PnL summary trade frequency (trades/day) + win rate
      - per-token realized profit distribution
      - portfolio value (holder if no trades but holds assets)
    Returns (style_label, median_hold_seconds_or_None, n_round_trips)."""
    rt = _wa_round_trip_holds(tx_trades) if tx_trades else []
    if rt:
        holds = [h for h, _ in rt]
        med = _wsf_median(holds)
        if med is not None:
            if med < 3600:
                style = "scalper"
            elif med < 86400:
                style = "day_trader"
            elif med < 7 * 86400:
                style = "swing"
            else:
                style = "holder"
            return style, med, len(rt)

    # ── Fallback: derive style from PnL summary stats ──
    s30 = None
    if pnl_summary_map:
        s30 = pnl_summary_map.get("30d") or pnl_summary_map.get(list(pnl_summary_map.keys())[-1])
    total_trade = int((s30 or {}).get("total_trade") or 0)
    unique_tokens = int((s30 or {}).get("unique_tokens") or 0)
    current_value = float((s30 or {}).get("current_value") or 0.0)

    # Portfolio value check (prefer portfolio, fallback to pnl current_value)
    nw = current_value
    if isinstance(portfolio, dict):
        pd_ = (portfolio.get("data") or {})
        if isinstance(pd_, dict):
            tv = pd_.get("total_value")
            try:
                nw = float(tv) if tv is not None else nw
            except Exception:
                pass

    if total_trade == 0 and (nw and nw > 0):
        return "holder", None, 0
    if total_trade == 0 and not nw:
        return "unknown", None, 0

    # Frequency-based style from PnL summary
    days = 30
    per_day = total_trade / days if days > 0 else 0.0
    # selectivity = trades per unique token (higher = more repeat trading on same tokens)
    selectivity = total_trade / max(unique_tokens, 1)

    if per_day >= 5:
        style = "scalper" if selectivity > 3 else "day_trader"
    elif per_day >= 1:
        style = "day_trader"
    elif per_day >= 0.1:
        style = "swing"
    else:
        style = "holder"
    return style, None, 0


def _wa_tp_sl_pattern(tx_trades, per_token=None):
    """Estimate typical take-profit % and stop-loss %.

    Primary: completed round trips from tx_list (sol_amount buy vs sell).
    Fallback: per-token realized_profit_percent from pnl/details.
    Returns (avg_win_pct, avg_loss_pct, n_wins, n_losses)."""
    rt = _wa_round_trip_holds(tx_trades) if tx_trades else []
    wins = [p for _, p in rt if p >= 0]
    losses = [p for _, p in rt if p < 0]
    if wins or losses:
        avg_win = round(sum(wins) / len(wins), 1) if wins else None
        avg_loss = round(sum(losses) / len(losses), 1) if losses else None
        return avg_win, avg_loss, len(wins), len(losses)

    # ── Fallback: per-token realized_profit_percent ──
    wins, losses = [], []
    if isinstance(per_token, dict):
        pd_ = per_token.get("data") or {}
        tk = pd_.get("tokens")
        toks = tk if isinstance(tk, list) else (list(tk.values()) if isinstance(tk, dict) else [])
        for t in toks:
            if not isinstance(t, dict):
                continue
            tpnl = t.get("pnl") or {}
            rpp = tpnl.get("realized_profit_percent")
            if not isinstance(rpp, (int, float)):
                continue
            rpp = float(rpp)
            # Birdeye realized_profit_percent is already in percent.
            # Heuristic: |rpp| > 1.5 → percent (use as-is); else ratio (×100).
            if abs(rpp) > 1.5:
                pct = rpp
            else:
                pct = rpp * 100.0
            # Cap loss at -100% (cannot lose more than invested in a token).
            if pct < -100.0:
                pct = -100.0
            if pct >= 0:
                wins.append(pct)
            else:
                losses.append(pct)
    avg_win = round(sum(wins) / len(wins), 1) if wins else None
    avg_loss = round(sum(losses) / len(losses), 1) if losses else None
    return avg_win, avg_loss, len(wins), len(losses)


def cmd_wallet_analysis(args):
    chain_short = args.chain
    chain_full = CHAINS.get(chain_short, chain_short)
    wallet = args.wallet.strip()
    pnl_method = getattr(args, "pnl_method", "wac")
    fmt = args.format
    intervals = [x.strip() for x in (getattr(args, "intervals", None) or ",".join(_WA_DEFAULT_INTERVALS)).split(",") if x.strip()]
    # normalize: dedup keep order
    seen = set(); ivs = []
    for iv in intervals:
        if iv not in seen:
            seen.add(iv); ivs.append(iv)
    intervals = ivs or list(_WA_DEFAULT_INTERVALS)
    nocache = bool(getattr(args, "nocache", False))
    cdir_arg = getattr(args, "cache_dir", None)
    write_cache = bool(getattr(args, "write_cache", True))
    from_cache_runid = getattr(args, "from_cache", None)
    skip_tx = bool(getattr(args, "skip_tx_list", False))
    skip_first_tx = bool(getattr(args, "skip_first_tx", False))
    skip_portfolio = bool(getattr(args, "skip_portfolio", False))

    api_key = os.environ.get("BIRDEYE_API_KEY")
    if not api_key:
        cand = Path.home() / ".birdeye.env"
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if line.startswith("BIRDEYE_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    cdir = _cache_dir(cdir_arg)
    _prune_old_cache(cdir, max_age_hours=72)

    if from_cache_runid:
        cp = _cache_path(cdir, from_cache_runid)
        if not cp.exists():
            sys.stderr.write(f"[wallet-analysis] cache miss for run_id {from_cache_runid}\n")
            return 3
        payload = json.loads(cp.read_text(encoding="utf-8"))
        out = payload.get("rendered_" + fmt) or payload.get("out")
        if not out:
            out = json.dumps(payload, ensure_ascii=False, indent=2)
        print(out)
        return 0

    if not api_key:
        sys.stderr.write("[wallet-analysis] missing BIRDEYE_API_KEY.\n")
        return 2

    rid = _safe_run_id("wallet-analysis", f"{chain_short}_{wallet[:10]}_{intervals[0]}")
    cu = {}
    import requests as _req
    session = _req.Session()

    summaries = {}
    try:
        for iv in intervals:
            summaries[iv], cu[f"pnl_{iv}"] = _ws_fetch_pnl_summary(session, api_key, chain_full, wallet, iv, pnl_method)
        per_token, cu["pnl_details"] = _ws_fetch_pnl_per_token(session, api_key, chain_full, wallet, pnl_method, duration="30d")

        first_funded = {}
        cu["first_funded"] = 0
        if not skip_first_tx:
            first_funded = _ws_first_funded_cache_get(cdir, wallet, chain_full)
            if first_funded is not None:
                cu["first_funded"] = 0
            else:
                first_funded, cu["first_funded"] = _ws_fetch_first_funded(session, api_key, chain_full, wallet)
                _ws_first_funded_cache_set(cdir, wallet, chain_full, first_funded)

        portfolio = {}
        cu["portfolio"] = 0
        if not skip_portfolio:
            portfolio, cu["portfolio"] = _ws_fetch_portfolio_v2(session, api_key, chain_full, wallet)

        tx_trades = []
        cu["tx_list"] = 0
        if not skip_tx:
            tx_raw, cu["tx_list"] = _wsf_fetch_tx_list(session, api_key, chain_full, wallet, limit=100)
            tx_trades = _wsf_extract_tx_trades(tx_raw, wallet)

        # Net-worth history (Solana only, 50 CU) — for accurate start/end NW per interval
        networth_history = {}
        cu["networth_history"] = 0
        if chain_full == "solana":
            networth_history, cu["networth_history"] = _ws_fetch_networth_history(session, api_key, wallet, count=90, type_="1d")
    except Exception as e:
        sys.stderr.write(f"[wallet-analysis] API error: {e}\n")
        return 4

    # ── Extract per-interval summaries
    s_map = {iv: _wa_extract_summary(summaries.get(iv)) for iv in intervals}

    # Fallback: summary counts often lacks unique_tokens → derive from pnl/details per-token list
    pt_token_count = 0
    if isinstance(per_token, dict):
        pt_tok = ((per_token.get("data") or {}).get("tokens"))
        if isinstance(pt_tok, list):
            pt_token_count = len(pt_tok)
        elif isinstance(pt_tok, dict):
            pt_token_count = len(pt_tok)
    for iv in intervals:
        if s_map[iv]["unique_tokens"] == 0 and pt_token_count > 0:
            s_map[iv]["unique_tokens"] = pt_token_count

    # ── Profile
    wallet_age_days = None
    last_tx_at = None
    if isinstance(first_funded, dict):
        ff = (first_funded.get("data") or {}).get(wallet) if isinstance(first_funded.get("data"), dict) else None
        if isinstance(ff, dict):
            try:
                ts = int(ff.get("block_unix_time") or 0)
                if ts:
                    wallet_age_days = (int(time.time()) - ts) // 86400
            except Exception:
                pass
    if tx_trades:
        last_tx_at = max(t["ts"] for t in tx_trades)

    style_label, med_hold, n_rt = _wa_infer_style(tx_trades, pnl_summary_map=s_map, per_token=per_token, portfolio=portfolio)
    avg_win_pct, avg_loss_pct, n_wins_rt, n_losses_rt = _wa_tp_sl_pattern(tx_trades, per_token=per_token)

    profile = {
        "last_transaction_at": last_tx_at,
        "wallet_age_days": wallet_age_days,
        "trading_style": style_label,
        "take_profit_pct": avg_win_pct,
        "stop_loss_pct": avg_loss_pct,
        "round_trips": n_rt,
        "identity": {"display_name": None, "tags": [], "has_socials": None, "credibility_score": None},
    }

    # ── Assets
    current_nw = None
    token_count = None
    if isinstance(portfolio, dict):
        pd_ = (portfolio.get("data") or {})
        if isinstance(pd_, dict):
            tv = pd_.get("total_value")
            try:
                current_nw = float(tv) if tv is not None else None
            except Exception:
                pass
            items = pd_.get("items") or []
            if isinstance(items, list):
                token_count = len(items)
    if current_nw is None:
        current_nw = s_map.get("30d", s_map.get(intervals[-1], {})).get("current_value") or 0.0

    # Parse net-worth history into {days_ago: net_worth}
    nw_history = {}  # days_ago (int) → net_worth
    if isinstance(networth_history, dict):
        hist = (networth_history.get("data") or {}).get("history") or []
        if isinstance(hist, list):
            from datetime import datetime, timezone
            now_ts = int(time.time())
            for h in hist:
                if not isinstance(h, dict):
                    continue
                ts_str = h.get("timestamp")
                nw = h.get("net_worth")
                if ts_str and nw is not None:
                    try:
                        if isinstance(ts_str, str):
                            ts = int(datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp())
                        else:
                            ts = int(ts_str)
                        days_ago = max(0, (now_ts - ts) // 86400)
                        nw_history[days_ago] = float(nw)
                    except Exception:
                        continue

    def _nw_at_days_ago(days):
        """Get net worth at approximately `days` ago. Find closest available snapshot."""
        if not nw_history:
            return None
        # exact or closest
        if days in nw_history:
            return nw_history[days]
        best_d = min(nw_history.keys(), key=lambda d: abs(d - days))
        return nw_history[best_d]

    # Asset intervals: use real net-worth history when available, else approximate.
    interval_days = {"24h": 1, "7d": 7, "30d": 30, "90d": 90, "all": 90}
    assets_intervals = {}
    for iv in intervals:
        s = s_map[iv]
        cur = current_nw if iv in ("30d", "all") else (s["current_value"] or current_nw or 0.0)
        days = interval_days.get(iv, 30)
        start_nw = _nw_at_days_ago(days)
        if start_nw is None:
            # Fallback: approximate from PnL (current - total_pnl)
            pnl_tot = s["total_pnl_usd"] or (s["realized_usd"] + s["unrealized_usd"])
            start_nw = max(cur - pnl_tot, 0.0)
        change = cur - start_nw
        if start_nw > 0:
            change_pct = (change / start_nw) * 100
        else:
            # Wallet started from 0 (newly funded) — can't compute meaningful %
            change_pct = None
        assets_intervals[iv] = {
            "start_net_worth": round(start_nw, 2),
            "end_net_worth": round(cur, 2),
            "change_usd": round(change, 2),
            "change_percent": round(change_pct, 2) if change_pct is not None else None,
            "high": None, "low": None,
        }
    assets = {
        "current": {"net_worth": round(current_nw or 0.0, 2), "token_count": token_count},
        "intervals": assets_intervals,
    }

    # ── Trading & Performance per interval
    trading = {iv: _wa_build_trading(s_map[iv]) for iv in intervals}
    performance = {iv: _wa_build_performance(s_map[iv]) for iv in intervals}

    # ── Profit concentration (top-10 tokens / total realized
    profit_concentration = None
    tokens_list = []
    if isinstance(per_token, dict):
        pd_ = per_token.get("data")
        if isinstance(pd_, dict):
            tk = pd_.get("tokens")
            if isinstance(tk, list):
                tokens_list = [t for t in tk if isinstance(t, dict)]
    if tokens_list:
        realized_vals = sorted(
            float((t.get("pnl") or {}).get("realized_profit_usd") or 0.0) for t in tokens_list
        )
        total_realized = sum(realized_vals)
        top10 = sum(sorted(realized_vals, reverse=True)[:10])
        profit_concentration = round(top10 / total_realized, 4) if total_realized > 0 else 0.0
    for iv in intervals:
        performance[iv]["profit_concentration"] = profit_concentration

    # ── Risk
    # bot/scammer scores: left null (heuristic would need more data)
    total_tokens_traded = max((s_map[iv]["unique_tokens"] for iv in intervals), default=0)
    # activeness = distinct active days / wallet age
    activeness = None
    if wallet_age_days and tx_trades:
        active_days = len(set(t["ts"] // 86400 for t in tx_trades))
        activeness = round(active_days / wallet_age_days, 4) if wallet_age_days > 0 else None

    # Open positions from per_token: tokens with unrealized position
    open_positions = {"count": 0, "profitable_count": 0, "cost": 0.0,
                     "profitable_value": 0.0, "unrealized_pnl": 0.0, "profitable_percent": 0.0}
    asset_concentration = {"top_1_weight": 0.0, "top_3_weight": 0.0, "top_5_weight": 0.0,
                          "stablecoin_weight": 0.0, "native_weight": 0.0}
    if isinstance(portfolio, dict):
        items = ((portfolio.get("data") or {}).get("items") or [])
        if isinstance(items, list):
            vals = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                v = float(it.get("value") or it.get("usd_value") or 0.0)
                vals.append(v)
            total_v = sum(vals)
            vals_sorted = sorted(vals, reverse=True)
            if total_v > 0:
                asset_concentration["top_1_weight"] = round(vals_sorted[0] / total_v, 4) if vals_sorted else 0.0
                asset_concentration["top_3_weight"] = round(sum(vals_sorted[:3]) / total_v, 4)
                asset_concentration["top_5_weight"] = round(sum(vals_sorted[:5]) / total_v, 4)

    risk = {
        "bot_behavior_score": None,
        "scammer_behavior_score": None,
        "risk_score": None,
        "avg_token_age_first_buy": None,
        "activeness": activeness,
        "total_tokens_traded": total_tokens_traded,
        "avg_market_cap_last_10_tokens": None,
        "avg_token_risk_score_last_10_tokens": None,
        "net_worth_volatility_7d": None,
        "net_worth_volatility_30d": None,
        "max_drawdown": {"daily": None, "weekly": None, "monthly": None, "yearly": None},
        "asset_concentration": asset_concentration,
        "open_positions": open_positions,
        "profit_concentration": profit_concentration,
    }

    cu_total = _ws_total_cu(cu)
    params_snapshot = {
        "chain": chain_short, "wallet": wallet, "pnl_method": pnl_method,
        "intervals": intervals, "skip_tx_list": skip_tx, "skip_first_tx": skip_first_tx,
        "skip_portfolio": skip_portfolio, "argv": sys.argv[1:],
    }

    analysis = {
        "wallet": wallet, "chain": chain_short, "currency": "usd",
        "as_of": int(time.time()),
        "profile": profile, "assets": assets, "trading": trading,
        "performance": performance, "risk": risk,
    }

    # ── Plain text
    w_short = wallet[:10] + "…" + wallet[-8:] if len(wallet) > 22 else wallet
    plain_lines = [
        f"Skill #14 · Wallet Analysis — @{w_short} · {chain_short.upper()}",
        f"CU: {cu_total} ({', '.join(f'{k}={v}' for k,v in cu.items())})",
        "",
        "─── Profile ───",
        f"  Style        : {profile['trading_style']}",
        f"  Wallet age   : {wallet_age_days}d" if wallet_age_days else "  Wallet age   : N/A",
        f"  TP / SL      : {avg_win_pct}% / {avg_loss_pct}%" if avg_win_pct is not None else "  TP / SL      : N/A",
        "",
        "─── Assets ───",
        f"  Net worth    : ${assets['current']['net_worth']:,.2f}  tokens={assets['current']['token_count']}",
    ]
    for iv in intervals:
        a = assets["intervals"][iv]
        cp = a["change_percent"]
        cp_s = f"{cp:+.1f}%" if cp is not None else "N/A (new wallet)"
        plain_lines.append(f"  {iv:<6} start ${a['start_net_worth']:>12,.2f} → end ${a['end_net_worth']:>12,.2f}  Δ {cp_s}")
    plain_lines.append("")
    plain_lines.append("─── Trading ───")
    plain_lines.append(f"  {'Interval':<6}{'Trades':>8}{'Buy':>6}{'Sell':>6}{'WR%':>7}{'Tokens':>8}{'Invested':>14}{'Sold':>14}{'NetFlow':>12}")
    for iv in intervals:
        t = trading[iv]
        plain_lines.append(f"  {iv:<6}{t['total_trade']:>8}{t['total_buy']:>6}{t['total_sell']:>6}{t['win_rate']:>7.1f}{t['unique_tokens']:>8}{t['total_invested']:>14,.0f}{t['total_sold']:>14,.0f}{t['net_flow_usd']:>12,.0f}")
    plain_lines.append("")
    plain_lines.append("─── Performance ───")
    plain_lines.append(f"  {'Interval':<6}{'Realized$':>14}{'Unrealized$':>14}{'Total$':>12}{'ROI%':>9}{'Eff':>7}{'W/L':>8}")
    for iv in intervals:
        p = performance[iv]
        plain_lines.append(f"  {iv:<6}{p['realized_profit_usd']:>14,.0f}{p['unrealized_usd']:>14,.0f}{p['total_pnl_usd']:>12,.0f}{p['roi']:>9.1f}{p['capital_efficiency']:>7.2f}{str(p['total_win'])+'/'+str(p['total_loss']):>8}")
    plain_lines.append("")
    plain_lines.append("─── Risk ───")
    plain_lines.append(f"  Tokens traded: {risk['total_tokens_traded']}  Activeness: {risk['activeness']}")
    plain_lines.append(f"  Profit concentration (top10): {profit_concentration}")
    plain_lines.append(f"  Asset concentration top1/3/5: {asset_concentration['top_1_weight']}/{asset_concentration['top_3_weight']}/{asset_concentration['top_5_weight']}")
    out_plain = "\n".join(plain_lines)

    # ── Telegram
    tg_lines = [
        f"*Skill #14 · Wallet Analysis* `{w_short}`",
        f"Chain: {chain_short.upper()} | CU: {cu_total}",
        "",
        f"*Style*: {profile['trading_style']}" + (f" · age {wallet_age_days}d" if wallet_age_days else ""),
    ]
    if avg_win_pct is not None:
        tg_lines.append(f"*TP/SL*: +{avg_win_pct}% / {avg_loss_pct}%")
    tg_lines += [
        "",
        f"💰 Net worth: ${assets['current']['net_worth']:,.0f} ({assets['current']['token_count']} tokens)",
        "",
        "*Trading*:",
    ]
    for iv in intervals:
        t = trading[iv]
        tg_lines.append(f"  {iv}: {t['total_trade']} trades · WR {t['win_rate']:.0f}% · {t['unique_tokens']} tokens · net ${t['net_flow_usd']:+,.0f}")
    tg_lines.append("")
    tg_lines.append("*Performance*:")
    for iv in intervals:
        p = performance[iv]
        tg_lines.append(f"  {iv}: R ${p['realized_profit_usd']:+,.0f} · U ${p['unrealized_usd']:+,.0f} · ROI {p['roi']:+.1f}%")
    out_telegram = "\n".join(tg_lines)

    # ── Rendered HTML
    def _col(v):
        try:
            return "#22c55e" if float(v) >= 0 else "#ef4444"
        except Exception:
            return "#94a3b8"
    trading_rows = ""
    for iv in intervals:
        t = trading[iv]
        trading_rows += f"""<tr><td style="padding:4px 8px">{iv}</td><td>{t['total_trade']}</td><td>{t['total_buy']}</td><td>{t['total_sell']}</td><td>{t['win_rate']:.1f}%</td><td>{t['unique_tokens']}</td><td>${t['total_invested']:,.0f}</td><td style="color:{_col(t['net_flow_usd'])}">${t['net_flow_usd']:+,.0f}</td></tr>"""
    perf_rows = ""
    for iv in intervals:
        p = performance[iv]
        perf_rows += f"""<tr><td style="padding:4px 8px">{iv}</td><td style="color:{_col(p['realized_profit_usd'])}">${p['realized_profit_usd']:+,.0f}</td><td style="color:{_col(p['unrealized_usd'])}">${p['unrealized_usd']:+,.0f}</td><td style="color:{_col(p['total_pnl_usd'])}">${p['total_pnl_usd']:+,.0f}</td><td style="color:{_col(p['roi'])}">{p['roi']:+.1f}%</td><td>{p['capital_efficiency']:.2f}</td><td>{p['total_win']}/{p['total_loss']}</td></tr>"""
    asset_rows = ""
    for iv in intervals:
        a = assets["intervals"][iv]
        cp = a["change_percent"]
        cp_s = f"{cp:+.1f}%" if cp is not None else "N/A"
        cp_color = _col(cp) if cp is not None else "#64748b"
        asset_rows += f"""<tr><td style="padding:4px 8px">{iv}</td><td>${a['start_net_worth']:,.0f}</td><td>${a['end_net_worth']:,.0f}</td><td style="color:{cp_color}">{cp_s}</td></tr>"""

    html_rendered = f'''<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0a0e1a;color:#e2e8f0;padding:16px;border-radius:12px;max-width:720px">
<div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Skill #14 · Wallet Analysis</div>
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
  <div style="font-size:18px;font-weight:700"><span class="copy-addr" data-copy-addr="{wallet}" style="cursor:pointer" title="Click to copy full wallet address">@{w_short} 📋</span></div>
  <div style="font-size:11px;color:#94a3b8">{chain_short.upper()} · ⚡ {cu_total} CU</div>
</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:14px">
  <div style="background:#0f172a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#64748b">STYLE</div><div style="font-size:16px;font-weight:700;margin-top:2px">{profile['trading_style']}</div></div>
  <div style="background:#0f172a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#64748b">AGE</div><div style="font-size:16px;font-weight:700;margin-top:2px">{wallet_age_days if wallet_age_days else 'N/A'}d</div></div>
  <div style="background:#0f172a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#64748b">TP / SL</div><div style="font-size:14px;font-weight:700;margin-top:2px">{('+'+str(avg_win_pct)+'% / '+str(avg_loss_pct)+'%') if avg_win_pct is not None else 'N/A'}</div></div>
</div>
<div style="background:#0f172a;border-radius:8px;padding:10px;margin-bottom:12px">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">💰 Assets · Net worth ${assets['current']['net_worth']:,.0f} ({assets['current']['token_count']} tokens)</div>
  <table style="width:100%;font-size:12px;border-collapse:collapse"><thead><tr style="color:#64748b"><th style="text-align:left;padding:4px 8px">Interval</th><th>Start</th><th>End</th><th>Change%</th></tr></thead><tbody>{asset_rows}</tbody></table>
</div>
<div style="background:#0f172a;border-radius:8px;padding:10px;margin-bottom:12px">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">📊 Trading</div>
  <table style="width:100%;font-size:12px;border-collapse:collapse"><thead><tr style="color:#64748b"><th style="text-align:left;padding:4px 8px">Int</th><th>Trades</th><th>Buy</th><th>Sell</th><th>WR%</th><th>Tokens</th><th>Invested</th><th>NetFlow</th></tr></thead><tbody>{trading_rows}</tbody></table>
</div>
<div style="background:#0f172a;border-radius:8px;padding:10px;margin-bottom:12px">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">📈 Performance</div>
  <table style="width:100%;font-size:12px;border-collapse:collapse"><thead><tr style="color:#64748b"><th style="text-align:left;padding:4px 8px">Int</th><th>Realized</th><th><abbr title="Unrealized P&L = current open position value minus cost basis" style="text-decoration:none;border-bottom:1px dotted #64748b;cursor:help">Unrealized PNL</abbr></th><th>Total</th><th><abbr title="Return on Investment = total PnL / invested capital" style="text-decoration:none;border-bottom:1px dotted #64748b;cursor:help">ROI</abbr></th><th><abbr title="Capital Efficiency = total PnL / invested capital (higher = more profit per $ deployed)" style="text-decoration:none;border-bottom:1px dotted #64748b;cursor:help">Eff</abbr></th><th>W/L</th></tr></thead><tbody>{perf_rows}</tbody></table>
</div>
<div style="background:#0f172a;border-radius:8px;padding:10px">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">⚠️ Risk</div>
  <div style="font-size:12px;line-height:1.7">
    Tokens traded: {risk['total_tokens_traded']} · Activeness: {risk['activeness']}<br>
    Profit concentration (top10): {profit_concentration}<br>
    Asset concentration top1/3/5: {asset_concentration['top_1_weight']}/{asset_concentration['top_3_weight']}/{asset_concentration['top_5_weight']}
  </div>
</div>
</div>'''

    raw_envelope = {
        "schemaVersion": 1, "kind": "wallet-analysis-v1", "runId": rid, "cached": False,
        "params": params_snapshot, "wallet": wallet, "chain": chain_short,
        "profile": profile, "assets": assets, "trading": trading,
        "performance": performance, "risk": risk,
        "cu_used_total": cu_total, "cu_breakdown": cu,
        "snapshot_time": int(time.time()),
        "format_renderers": ["rendered", "plain", "telegram", "raw-json"],
    }
    out_raw_json = json.dumps(raw_envelope, ensure_ascii=False)
    rendered_payload = dict(raw_envelope)
    rendered_payload["html"] = html_rendered
    out_rendered_json = json.dumps(rendered_payload, ensure_ascii=False, indent=2)

    if write_cache:
        file_payload = {
            "runId": rid, "kind": "wallet-analysis-v1", "cached": False,
            "cu_used_total": cu_total, "cu_breakdown": cu,
            "params": params_snapshot, "wallet": wallet, "chain": chain_short,
            "profile": profile, "assets": assets, "trading": trading,
            "performance": performance, "risk": risk,
            "snapshot_time": int(time.time()),
            "rendered_plain": out_plain, "rendered_telegram": out_telegram,
            "rendered_raw-json": out_raw_json, "rendered_rendered": out_rendered_json,
            "out": out_plain,
        }
        _cache_path(cdir, rid).write_text(json.dumps(file_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    stdout_prefix = f"#RUN_ID {rid}\twallet-analysis\tcu={cu_total}\n"
    if fmt == "rendered":
        sys.stdout.write(stdout_prefix); print(out_rendered_json)
    elif fmt == "plain":
        sys.stdout.write(stdout_prefix); print(out_plain)
    elif fmt == "telegram":
        sys.stdout.write(stdout_prefix); print(out_telegram)
    else:
        sys.stdout.write(stdout_prefix); print(out_raw_json)
    return 0


# ════════════════════════════════════════════════════════════════════════════
# Skill #9 · Smart Money Profile — behavior analysis + copy-trade verdict
#   Based on workflow-smart-money-profile.md: performance trend, style,
#   TP/SL patterns, copy-trade ROI estimate, and a 🟢/🟡/🔴 verdict.
# ════════════════════════════════════════════════════════════════════════════
def _smp_copy_trade_estimate(swaps, per_token, portfolio):
    """Compute copy-trade ROI estimation from available trade data.

    Data sources (in priority order):
      1. Round-trip buy→sell pairs built from /trader/txs/seek_by_time swaps
         (multi-hop swaps collapsed to source→sink, filtered to pnl/details tokens).
      2. Per-token realized_profit_percent from pnl/details (fallback when no round trips).
      3. Open positions from portfolio (unrealized return = current value vs cost).

    `swaps` is the output of `_smp_build_swaps_from_trader_txs`: list of
    {from_token, to_token, from_usd, to_usd, ts, ...}.

    ~30d equal-weight copy estimate:
      If you copy every trade with the SAME dollar amount, your portfolio return
      over the window equals the AVERAGE return per trade (each trade is equal
      weight, no compounding modelled). So est_30d = avg_return_pct.
      Context fields (n_trades_30d, trades_per_day) let you sanity-check activity.

    Returns dict with:
      avg_return_pct, win_rate (float 0-1), n_wins, n_trades,
      n_completed (round-trips), n_open (positions),
      best_trade {token, return_pct, source}, worst_trade {...},
      est_30d_return_pct, trades (list), has_roundtrips (bool),
      trades_per_day, n_trades_30d, est_method (explanation string).
    """
    trades = []  # list of {token, return_pct, source}

    # Tokens to skip in round-trip analysis: native chain tokens and stablecoins
    # are base currencies (pass-throughs), not speculative trades.
    _SKIP_TOKENS = {
        "SOL", "ETH", "WETH", "BNB", "WBNB", "MATIC", "AVAX", "FTM", "ARB", "OP",
        "USDC", "USDT", "USD", "DAI", "BUSD", "USDE", "FDUSD", "TUSD", "USDP",
        "PYUSD", "EURT", "EURS", "BTC", "WBTC", "stETH", "rETH",
    }

    # ── Source 1: round-trip buy→sell pairs from trader txs ──
    if swaps:
        # For each token T:
        #   buy  = to_token==T  → qty=to_amount, cost=from_usd
        #   sell = from_token==T → qty=from_amount, proceeds=to_usd
        # Match FIFO by token quantity (with partial fills) for accurate returns.
        by_tok = {}
        for sw in swaps:
            to_tok = sw["to_token"]
            from_tok = sw["from_token"]
            to_sym = (sw.get("to_symbol") or "").upper()
            from_sym = (sw.get("from_symbol") or "").upper()
            if to_sym not in _SKIP_TOKENS:
                by_tok.setdefault(to_tok, {"buys": [], "sells": [], "symbol": sw.get("to_symbol", "")})
                by_tok[to_tok]["buys"].append({
                    "qty": sw.get("to_amount", 0.0),
                    "cost": sw["from_usd"],
                    "ts": sw["ts"],
                    "symbol": sw.get("to_symbol", ""),
                })
            if from_sym not in _SKIP_TOKENS:
                by_tok.setdefault(from_tok, {"buys": [], "sells": [], "symbol": sw.get("from_symbol", "")})
                by_tok[from_tok]["sells"].append({
                    "qty": sw.get("from_amount", 0.0),
                    "proceeds": sw["to_usd"],
                    "ts": sw["ts"],
                    "symbol": sw.get("from_symbol", ""),
                })

        for tok, ev in by_tok.items():
            buys = sorted(ev["buys"], key=lambda x: x["ts"])
            sells = sorted(ev["sells"], key=lambda x: x["ts"])
            sym = ev.get("symbol") or tok[:8]
            if not buys or not sells:
                continue
            # Use a deque-like pointer for FIFO with partial fills
            bi = 0
            buy_rem = buys[bi]["qty"] if buys else 0.0
            for sell in sells:
                sell_qty = sell["qty"]
                sell_proceeds = sell["proceeds"]
                if sell_qty <= 0 or sell_proceeds <= 0:
                    continue
                while sell_qty > 1e-12 and bi < len(buys):
                    if buy_rem <= 1e-12:
                        bi += 1
                        if bi >= len(buys):
                            break
                        buy_rem = buys[bi]["qty"]
                        continue
                    match_qty = min(sell_qty, buy_rem)
                    buy = buys[bi]
                    # Proportional cost and proceeds for the matched quantity
                    cost_portion = buy["cost"] * (match_qty / buy["qty"]) if buy["qty"] > 0 else 0.0
                    proceeds_portion = sell_proceeds * (match_qty / sell["qty"])
                    if cost_portion > 0:
                        ret = (proceeds_portion - cost_portion) / cost_portion * 100.0
                        trades.append({"token": str(sym)[:16], "return_pct": round(ret, 2), "source": "tx"})
                    buy_rem -= match_qty
                    sell_qty -= match_qty
                    if buy_rem <= 1e-12:
                        bi += 1
                        if bi < len(buys):
                            buy_rem = buys[bi]["qty"]

    has_roundtrips = len(trades) > 0

    # ── Source 2: per-token realized_profit_percent (fallback) ──
    if not has_roundtrips and isinstance(per_token, dict):
        pd_ = per_token.get("data") or {}
        tk = pd_.get("tokens")
        toks = tk if isinstance(tk, list) else (list(tk.values()) if isinstance(tk, dict) else [])
        for t in toks:
            if not isinstance(t, dict):
                continue
            tpnl = t.get("pnl") or {}
            rpp = tpnl.get("realized_profit_percent")
            if not isinstance(rpp, (int, float)):
                continue
            rpp = float(rpp)
            # Birdeye rpp is in percent; cap loss at -100
            if abs(rpp) > 1.5:
                pct = rpp
            else:
                pct = rpp * 100.0
            if pct < -100.0:
                pct = -100.0
            sym = t.get("symbol") or t.get("address") or "?"
            trades.append({"token": str(sym)[:16], "return_pct": round(pct, 2), "source": "pnl"})

    # ── Source 3: open positions from portfolio (unrealized) ──
    open_trades = []
    if isinstance(portfolio, dict):
        items = ((portfolio.get("data") or {}).get("items") or [])
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                cost = float(it.get("cost") or it.get("cost_basis") or 0.0)
                cur = float(it.get("value") or it.get("usd_value") or 0.0)
                sym = it.get("symbol") or it.get("address") or "?"
                if cost > 0:
                    ret = (cur - cost) / cost * 100.0
                    open_trades.append({"token": str(sym)[:16], "return_pct": round(ret, 2), "source": "open"})

    # Cap open-position losses at -100 (can't lose more than cost)
    for ot in open_trades:
        if ot["return_pct"] < -100.0:
            ot["return_pct"] = -100.0

    all_trades = trades + open_trades
    n_trades_30d = len(trades) if has_roundtrips else len(trades)  # completed trades in window
    trades_per_day = round(n_trades_30d / 30.0, 2) if n_trades_30d > 0 else 0.0

    result = {
        "avg_return_pct": None,
        "win_rate": None,
        "n_wins": 0,
        "n_trades": len(all_trades),
        "n_completed": len(trades),
        "n_open": len(open_trades),
        "best_trade": None,
        "worst_trade": None,
        "est_30d_return_pct": None,
        "trades": all_trades,
        "has_roundtrips": has_roundtrips,
        "trades_per_day": trades_per_day,
        "n_trades_30d": n_trades_30d,
        "est_method": "Equal-weight copy: same $ per trade → return ≈ avg return/trade (no compounding).",
    }

    if not all_trades:
        return result

    rets = [t["return_pct"] for t in all_trades]
    result["avg_return_pct"] = round(sum(rets) / len(rets), 2)
    wins = [r for r in rets if r > 0]
    result["n_wins"] = len(wins)
    result["win_rate"] = round(len(wins) / len(rets), 4)
    best_idx = rets.index(max(rets))
    worst_idx = rets.index(min(rets))
    result["best_trade"] = all_trades[best_idx]
    result["worst_trade"] = all_trades[worst_idx]

    # Equal-weight 30d return: copying every trade with equal $ → your return
    # equals the average return per trade (no compounding modelled).
    result["est_30d_return_pct"] = result["avg_return_pct"]

    return result


def _smp_format_cte_plain(cte):
    """Format copy-trade estimate as plain text lines."""
    if not cte or cte.get("n_trades", 0) == 0:
        return "  (insufficient trade data to estimate)"
    lines = []
    avg = cte.get("avg_return_pct")
    avg_s = ('+'+str(avg)+'%') if (avg is not None and avg >= 0) else (str(avg)+'%' if avg is not None else 'N/A')
    lines.append(f"  Avg return / trade  : {avg_s}")
    wr = cte.get("win_rate")
    nw = cte.get("n_wins", 0)
    nt = cte.get("n_trades", 0)
    wr_pct = wr * 100 if (wr is not None and wr <= 1.0) else wr
    lines.append(f"  Win rate            : {nw} / {nt} trades profitable" + (f"  ({wr_pct:.0f}%)" if wr is not None else ""))
    nc = cte.get("n_completed", 0)
    no = cte.get("n_open", 0)
    src = "tx round-trips (pnl tokens)" if cte.get("has_roundtrips") else "per-token PnL + open positions"
    lines.append(f"  Completed / open    : {nc} / {no}  (source: {src})")
    tpd = cte.get("trades_per_day")
    if tpd:
        lines.append(f"  Activity            : {cte.get('n_trades_30d',0)} trades in 30d  ({tpd} trades/day)")
    bt = cte.get("best_trade")
    wt = cte.get("worst_trade")
    if bt:
        lines.append(f"  Best trade          : +{bt['return_pct']}% on {bt['token']}")
    if wt:
        lines.append(f"  Worst trade         : {wt['return_pct']}% on {wt['token']}")
    est = cte.get("est_30d_return_pct")
    if est is not None:
        est_s = ('+'+str(est)+'%') if est >= 0 else str(est)+'%'
        lines.append(f"  ~30d eq-wt copy     : {est_s}   ← = avg return/trade (same $ per trade, no compounding)")
    return "\n".join(lines)


def _smp_verdict(wr_7d, wr_30d, realized_7d, realized_30d, style, avg_win, avg_loss, n_rt):
    """Return (verdict_emoji, verdict_label, verdict_reason)."""
    # Pure holder (CEX wallet / cold storage) — no on-chain swaps
    if style == "holder" and n_rt == 0:
        return "⚪", "HOLDER", "no on-chain swap activity — wallet holds assets (likely CEX/cold storage)"
    # No trades
    if n_rt < 3:
        return "⚪", "NO READ", f"only {n_rt} round-trip trades in sample — too thin to judge"
    # G2 Currency: edge stopped working
    if realized_7d is not None and realized_7d < 0 and (realized_30d is None or realized_30d > 0):
        return "🔴", "DO NOT COPY", "it has stopped making money (7d realized negative while 30d positive)"
    if (realized_7d is not None and realized_7d <= 0) and (realized_30d is not None and realized_30d <= 0):
        return "🔴", "DO NOT COPY", "both 7d and 30d realized PnL are negative"
    # G3+G4: can't get fills and doesn't cut losses
    bad_fills = style in ("scalper",) and (avg_win is not None and avg_win < 10)
    no_cut = avg_loss is not None and avg_loss < -40
    if bad_fills and no_cut:
        return "🟡", "WATCH, DO NOT COPY", "scalper with thin wins and no loss-cutting — you cannot get its fills"
    if bad_fills:
        return "🟡", "WATCH, DO NOT COPY", "scalper with thin wins — copy flow moves price before your order"
    if no_cut:
        return "🟡", "COPY BUYS, NOT EXITS", "does not cut losses (avg exit loss >40%) — use it as a signal, not an exit mirror"
    # Strong stats
    if wr_30d is not None and wr_30d >= 0.6 and (avg_win is not None and avg_loss is not None and abs(avg_win) >= abs(avg_loss)):
        improving = wr_7d is not None and wr_30d is not None and wr_7d > wr_30d
        label = "COPYABLE AT SMALL SIZE"
        reason = "strong win rate with positive win/loss asymmetry" + (" — form improving" if improving else "")
        return "🟢", label, reason
    # Acceptable
    if wr_30d is not None and wr_30d >= 0.5:
        return "🟡", "SELECTIVE FOLLOW", "acceptable win rate but inconsistent exit pattern"
    return "🔴", "AVOID", f"win rate {wr_30d*100:.0f}% below 50% with no compensating edge"


def cmd_smart_money_profile(args):
    chain_short = args.chain
    chain_full = CHAINS.get(chain_short, chain_short)
    wallet = args.wallet.strip()
    pnl_method = getattr(args, "pnl_method", "wac")
    fmt = args.format
    nocache = bool(getattr(args, "nocache", False))
    cdir_arg = getattr(args, "cache_dir", None)
    write_cache = bool(getattr(args, "write_cache", True))
    from_cache_runid = getattr(args, "from_cache", None)
    skip_tx = bool(getattr(args, "skip_tx_list", False))
    skip_first_tx = bool(getattr(args, "skip_first_tx", False))

    api_key = os.environ.get("BIRDEYE_API_KEY")
    if not api_key:
        cand = Path.home() / ".birdeye.env"
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if line.startswith("BIRDEYE_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    cdir = _cache_dir(cdir_arg)
    _prune_old_cache(cdir, max_age_hours=72)

    if from_cache_runid:
        cp = _cache_path(cdir, from_cache_runid)
        if not cp.exists():
            sys.stderr.write(f"[smart-money-profile] cache miss for run_id {from_cache_runid}\n")
            return 3
        payload = json.loads(cp.read_text(encoding="utf-8"))
        out = payload.get("rendered_" + fmt) or payload.get("out")
        if not out:
            out = json.dumps(payload, ensure_ascii=False, indent=2)
        print(out)
        return 0

    if not api_key:
        sys.stderr.write("[smart-money-profile] missing BIRDEYE_API_KEY.\n")
        return 2

    rid = _safe_run_id("smart-money-profile", f"{chain_short}_{wallet[:10]}")
    cu = {}
    import requests as _req
    session = _req.Session()

    try:
        sum_7d, cu["pnl_7d"] = _ws_fetch_pnl_summary(session, api_key, chain_full, wallet, "7d", pnl_method)
        sum_30d, cu["pnl_30d"] = _ws_fetch_pnl_summary(session, api_key, chain_full, wallet, "30d", pnl_method)
        per_token, cu["pnl_details"] = _ws_fetch_pnl_per_token(session, api_key, chain_full, wallet, pnl_method, duration="30d")

        first_funded = {}
        cu["first_funded"] = 0
        if not skip_first_tx:
            first_funded = _ws_first_funded_cache_get(cdir, wallet, chain_full)
            if first_funded is not None:
                cu["first_funded"] = 0
            else:
                first_funded, cu["first_funded"] = _ws_fetch_first_funded(session, api_key, chain_full, wallet)
                _ws_first_funded_cache_set(cdir, wallet, chain_full, first_funded)

        tx_trades = []
        swaps = []
        cu["trader_txs"] = 0
        if not skip_tx:
            import time as _time
            after_time = int(_time.time()) - 30 * 86400  # last 30 days
            trader_raw, cu["trader_txs"] = _ws_fetch_trader_txs(session, api_key, chain_full, wallet, after_time, limit=100)
            # Build all swaps (for style/TP-SL inference)
            swaps_all = _smp_build_swaps_from_trader_txs(trader_raw, pnl_token_addrs=None)
            # Extract pnl token addresses for copy-trade filtering
            pnl_token_addrs = set()
            if isinstance(per_token, dict):
                pd_ = per_token.get("data") or {}
                tk = pd_.get("tokens")
                toks = tk if isinstance(tk, list) else (list(tk.values()) if isinstance(tk, dict) else [])
                for t in toks:
                    if isinstance(t, dict):
                        addr = t.get("address")
                        if addr:
                            pnl_token_addrs.add(str(addr))
            # Filter swaps to pnl/details tokens for copy-trade estimate
            if pnl_token_addrs:
                swaps = [s for s in swaps_all if s["from_token"] in pnl_token_addrs or s["to_token"] in pnl_token_addrs]
            else:
                swaps = swaps_all
            # Build tx_trades-compatible list for style & TP/SL (uses hold durations + USD amounts)
            native_addrs = {"So11111111111111111111111111111111111111112", "0x0000000000000000000000000000000000000000"}
            for sw in swaps_all:
                f, t = sw["from_token"], sw["to_token"]
                f_native = f in native_addrs
                t_native = t in native_addrs
                if f_native and not t_native:
                    # buy of to_token
                    tx_trades.append({"token": t, "side": "buy", "ts": sw["ts"], "sol_amount": sw["from_usd"], "token_amount": 0, "fee_native": 0})
                elif t_native and not f_native:
                    # sell of from_token
                    tx_trades.append({"token": f, "side": "sell", "ts": sw["ts"], "sol_amount": sw["to_usd"], "token_amount": 0, "fee_native": 0})
                elif not f_native and not t_native:
                    # token→token: sell from, buy to
                    tx_trades.append({"token": f, "side": "sell", "ts": sw["ts"], "sol_amount": sw["to_usd"], "token_amount": 0, "fee_native": 0})
                    tx_trades.append({"token": t, "side": "buy", "ts": sw["ts"], "sol_amount": sw["from_usd"], "token_amount": 0, "fee_native": 0})

        portfolio = {}
        cu["portfolio"] = 0
        try:
            portfolio, cu["portfolio"] = _ws_fetch_portfolio_v2(session, api_key, chain_full, wallet)
        except Exception:
            portfolio = {}
    except Exception as e:
        sys.stderr.write(f"[smart-money-profile] API error: {e}\n")
        return 4

    s7 = _wa_extract_summary(sum_7d)
    s30 = _wa_extract_summary(sum_30d)
    smp_s_map = {"7d": s7, "30d": s30}
    wr_7d = _wa_win_rate(s7) / 100.0
    wr_30d = _wa_win_rate(s30) / 100.0
    realized_7d = s7["realized_usd"]
    realized_30d = s30["realized_usd"]

    style, med_hold, n_rt = _wa_infer_style(tx_trades, pnl_summary_map=smp_s_map, per_token=per_token)
    avg_win, avg_loss, n_wins, n_losses = _wa_tp_sl_pattern(tx_trades, per_token=per_token)

    # Trend
    if wr_7d > wr_30d + 0.05:
        trend = "↑ improving"
    elif wr_7d < wr_30d - 0.05:
        trend = "↓ declining"
    else:
        trend = "→ stable"

    # Wallet age
    wallet_age_days = None
    if isinstance(first_funded, dict):
        ff = (first_funded.get("data") or {}).get(wallet) if isinstance(first_funded.get("data"), dict) else None
        if isinstance(ff, dict):
            try:
                ts = int(ff.get("block_unix_time") or 0)
                if ts:
                    wallet_age_days = (int(time.time()) - ts) // 86400
            except Exception:
                pass

    # Copy-trade ROI estimate (from round trips / pnl / open positions)
    copy_avg_return = None
    if n_rt > 0 and (avg_win is not None or avg_loss is not None):
        w_total = (avg_win or 0) * n_wins
        l_total = (avg_loss or 0) * n_losses
        copy_avg_return = round((w_total + l_total) / n_rt, 1) if n_rt else None

    # Detailed copy-trade ROI estimation — uses filtered swaps (pnl/details tokens only)
    cte = _smp_copy_trade_estimate(swaps, per_token, portfolio)

    v_emoji, v_label, v_reason = _smp_verdict(wr_7d, wr_30d, realized_7d, realized_30d, style, avg_win, avg_loss, n_rt)

    cu_total = _ws_total_cu(cu)
    w_short = wallet[:10] + "…" + wallet[-8:] if len(wallet) > 22 else wallet
    params_snapshot = {
        "chain": chain_short, "wallet": wallet, "pnl_method": pnl_method,
        "skip_tx_list": skip_tx, "skip_first_tx": skip_first_tx, "argv": sys.argv[1:],
    }

    profile = {
        "wallet": wallet, "chain": chain_short, "style": style,
        "wallet_age_days": wallet_age_days,
        "wr_7d": round(wr_7d * 100, 1), "wr_30d": round(wr_30d * 100, 1),
        "realized_7d": round(realized_7d, 2), "realized_30d": round(realized_30d, 2),
        "trend": trend, "tp_pct": avg_win, "sl_pct": avg_loss,
        "copy_avg_return_pct": copy_avg_return, "round_trips": n_rt,
        "copy_trade_estimate": {
            "avg_return_pct": cte["avg_return_pct"],
            "win_rate": round(cte["win_rate"] * 100, 1) if cte["win_rate"] is not None else None,
            "n_wins": cte["n_wins"],
            "n_trades": cte["n_trades"],
            "n_completed": cte["n_completed"],
            "n_open": cte["n_open"],
            "best_trade": cte["best_trade"],
            "worst_trade": cte["worst_trade"],
            "est_30d_return_pct": cte["est_30d_return_pct"],
            "has_roundtrips": cte["has_roundtrips"],
            "trades_per_day": cte["trades_per_day"],
            "n_trades_30d": cte["n_trades_30d"],
            "est_method": cte["est_method"],
        },
        "verdict": {"emoji": v_emoji, "label": v_label, "reason": v_reason},
    }

    # ── Plain
    plain = f"""Skill #9 · Smart Money Profile — @{w_short} · {chain_short.upper()}
CU: {cu_total} ({', '.join(f'{k}={v}' for k,v in cu.items())})

─── Performance (7d / 30d) ───
  Win Rate      : {wr_7d*100:.0f}% / {wr_30d*100:.0f}%   [{trend}]
  Realized PnL  : ${realized_7d:+,.0f} / ${realized_30d:+,.0f}
  Trades (30d)  : {s30['total_trade']} · tokens {s30['unique_tokens']}

─── Trading Style ───
  Style        : {style}
  Round trips  : {n_rt}

─── Exit Behavior ───
  Take-profit  : {('+'+str(avg_win)+'%') if avg_win is not None else 'N/A'}  (n={n_wins})
  Stop-loss    : {str(avg_loss)+'%' if avg_loss is not None else 'N/A'}  (n={n_losses})

─── Copy-Trade Estimate ───
{_smp_format_cte_plain(cte)}
  ⚠️  Approximation only — entry timing, slippage, fees not modelled.

─── Verdict ───
  {v_emoji} {v_label}
  {v_reason}
"""
    out_plain = plain

    # ── Telegram
    out_telegram = f"""*Smart Money Profile* `{w_short}`
Chain: {chain_short.upper()} | CU: {cu_total}

*Performance* (7d / 30d)
WR: {wr_7d*100:.0f}% / {wr_30d*100:.0f}% [{trend}]
Realized: ${realized_7d:+,.0f} / ${realized_30d:+,.0f}

*Style*: {style}
*TP/SL*: {('+'+str(avg_win)+'%') if avg_win is not None else 'N/A'} / {str(avg_loss)+'%' if avg_loss is not None else 'N/A'}

*Copy estimate*: {(('+'+str(cte.get('avg_return_pct'))+'% avg/trade') if (cte.get('avg_return_pct') is not None and cte.get('avg_return_pct') >= 0) else (str(cte.get('avg_return_pct'))+'% avg/trade' if cte.get('avg_return_pct') is not None else 'N/A'))} ({cte.get('n_wins',0)}/{cte.get('n_trades',0)} wins)
*~30d eq-wt*: {(('+'+str(cte.get('est_30d_return_pct'))+'%') if (cte.get('est_30d_return_pct') is not None and cte.get('est_30d_return_pct') >= 0) else (str(cte.get('est_30d_return_pct'))+'%' if cte.get('est_30d_return_pct') is not None else 'N/A'))}

{v_emoji} *{v_label}*
{v_reason}"""

    # ── Rendered HTML
    v_color = {"🟢": "#22c55e", "🟡": "#facc15", "🔴": "#ef4444", "⚪": "#94a3b8"}.get(v_emoji, "#94a3b8")
    html_rendered = f'''<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0a0e1a;color:#e2e8f0;padding:16px;border-radius:12px;max-width:640px">
<div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Skill #9 · Smart Money Profile</div>
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
  <div style="font-size:18px;font-weight:700"><span class="copy-addr" data-copy-addr="{wallet}" style="cursor:pointer" title="Click to copy full wallet address">@{w_short} 📋</span></div>
  <div style="font-size:11px;color:#94a3b8">{chain_short.upper()} · ⚡ {cu_total} CU</div>
</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:14px">
  <div style="background:#0f172a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#64748b">WIN RATE 7D/30D</div><div style="font-size:16px;font-weight:700;margin-top:2px">{wr_7d*100:.0f}% / {wr_30d*100:.0f}%</div><div style="font-size:10px;color:#94a3b8">{trend}</div></div>
  <div style="background:#0f172a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#64748b">REALIZED 7D/30D</div><div style="font-size:14px;font-weight:700;margin-top:2px">${realized_7d:+,.0f}<br>${realized_30d:+,.0f}</div></div>
  <div style="background:#0f172a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#64748b">STYLE</div><div style="font-size:16px;font-weight:700;margin-top:2px">{style}</div><div style="font-size:10px;color:#94a3b8">{n_rt} round trips</div></div>
</div>
<div style="background:#0f172a;border-radius:8px;padding:10px;margin-bottom:12px">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">🎯 Exit Behavior</div>
  <div style="font-size:13px">Take-profit: <b style="color:#22c55e">{('+'+str(avg_win)+'%') if avg_win is not None else 'N/A'}</b> · Stop-loss: <b style="color:#ef4444">{str(avg_loss)+'%' if avg_loss is not None else 'N/A'}</b></div>
</div>
<div style="background:#0f172a;border-radius:8px;padding:10px;margin-bottom:12px">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">📋 Copy-Trade ROI Estimate</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;font-size:12px">
    <div>Avg return / trade: <b style="color:{('#22c55e' if (cte.get('avg_return_pct') or 0) >= 0 else '#ef4444')}">{(('+'+str(cte.get('avg_return_pct'))+'%') if (cte.get('avg_return_pct') is not None and cte.get('avg_return_pct') >= 0) else (str(cte.get('avg_return_pct'))+'%' if cte.get('avg_return_pct') is not None else 'N/A'))}</b></div>
    <div>Win rate: <b>{cte.get('n_wins',0)}/{cte.get('n_trades',0)}</b> ({(str(round(cte.get('win_rate')*100))+'%') if cte.get('win_rate') is not None else 'N/A'})</div>
    <div>Best: <b style="color:#22c55e">+{(cte.get('best_trade') or {}).get('return_pct','?')}%</b> on {(cte.get('best_trade') or {}).get('token','?')}</div>
    <div>Worst: <b style="color:#ef4444">{(cte.get('worst_trade') or {}).get('return_pct','?')}%</b> on {(cte.get('worst_trade') or {}).get('token','?')}</div>
    <div>Completed / open: <b>{cte.get('n_completed',0)} / {cte.get('n_open',0)}</b></div>
    <div>Activity: <b>{cte.get('n_trades_30d',0)}</b> trades / 30d ({cte.get('trades_per_day',0)}/day)</div>
  </div>
  <div style="margin-top:8px;padding:8px;background:#020617;border-radius:6px;border-left:3px solid #38bdf8">
    <div style="font-size:11px;color:#64748b">~30d equal-weight copy</div>
    <div style="font-size:16px;font-weight:800;color:{('#22c55e' if (cte.get('est_30d_return_pct') or 0) >= 0 else '#ef4444')}">{(('+'+str(cte.get('est_30d_return_pct'))+'%') if (cte.get('est_30d_return_pct') is not None and cte.get('est_30d_return_pct') >= 0) else (str(cte.get('est_30d_return_pct'))+'%' if cte.get('est_30d_return_pct') is not None else 'N/A'))}</div>
    <div style="font-size:10px;color:#64748b;margin-top:2px">= avg return/trade · same $ per trade · no compounding</div>
  </div>
  <div style="font-size:10px;color:#64748b;margin-top:5px">⚠️ Approximation — entry timing, slippage, fees not modelled. Source: {'tx round-trips (pnl tokens)' if cte.get('has_roundtrips') else 'per-token PnL + open positions'}.</div>
</div>
<div style="border:1px solid {v_color};border-radius:8px;padding:12px;background:#0f172a">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:4px">Verdict</div>
  <div style="font-size:20px;font-weight:800;color:{v_color}">{v_emoji} {v_label}</div>
  <div style="font-size:12px;color:#cbd5e1;margin-top:4px">{v_reason}</div>
</div>
</div>'''

    raw_envelope = {
        "schemaVersion": 1, "kind": "smart-money-profile-v1", "runId": rid, "cached": False,
        "params": params_snapshot, "profile": profile,
        "cu_used_total": cu_total, "cu_breakdown": cu,
        "snapshot_time": int(time.time()),
        "format_renderers": ["rendered", "plain", "telegram", "raw-json"],
    }
    out_raw_json = json.dumps(raw_envelope, ensure_ascii=False)
    rendered_payload = dict(raw_envelope)
    rendered_payload["html"] = html_rendered
    out_rendered_json = json.dumps(rendered_payload, ensure_ascii=False, indent=2)

    if write_cache:
        file_payload = {
            "runId": rid, "kind": "smart-money-profile-v1", "cached": False,
            "cu_used_total": cu_total, "cu_breakdown": cu,
            "params": params_snapshot, "profile": profile,
            "snapshot_time": int(time.time()),
            "rendered_plain": out_plain, "rendered_telegram": out_telegram,
            "rendered_raw-json": out_raw_json, "rendered_rendered": out_rendered_json,
            "out": out_plain,
        }
        _cache_path(cdir, rid).write_text(json.dumps(file_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    stdout_prefix = f"#RUN_ID {rid}\tsmart-money-profile\tcu={cu_total}\n"
    if fmt == "rendered":
        sys.stdout.write(stdout_prefix); print(out_rendered_json)
    elif fmt == "plain":
        sys.stdout.write(stdout_prefix); print(out_plain)
    elif fmt == "telegram":
        sys.stdout.write(stdout_prefix); print(out_telegram)
    else:
        sys.stdout.write(stdout_prefix); print(out_raw_json)
    return 0


def _sml_rank_percentile(values, higher_is_better=True):
    """Return list of 0..1 rank-percentiles for `values`.
    Ties get the average rank. higher_is_better=False reverses (used for losses).
    """
    n = len(values)
    if n == 0:
        return []
    indexed = sorted(enumerate(values), key=lambda x: x[1] if higher_is_better else -x[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        # average 1-based rank for the tie group
        avg_rank = (i + j) / 2.0 + 1.0
        pct = (n - avg_rank + 1) / n if higher_is_better else avg_rank / n
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = round(pct, 4)
        i = j + 1
    return ranks


def _sml_min_max(values, clamp=None):
    """Min-max normalize to 0..1. `clamp` = (lo, hi) to clip input first."""
    n = len(values)
    if n == 0:
        return []
    vals = list(values)
    if clamp:
        lo, hi = clamp
        vals = [max(lo, min(hi, v)) for v in vals]
    mn, mx = min(vals), max(vals)
    if mx == mn:
        return [0.5] * n
    return [round((v - mn) / (mx - mn), 4) for v in vals]


def cmd_smart_money_leaderboard(args):
    """Skill #9b — Smart Money Leaderboard.

    Compare up to 10 wallets and rank by a composite score:
      composite = wr_30d_norm × 0.4 + pnl_norm × 0.4 + token_norm × 0.1 + recency_norm × 0.1
    where:
      wr_30d_norm = win_rate_30d / 100  (already 0..1)
      pnl_norm    = rank-percentile of realized_pnl_30d across the batch
      token_norm  = min-max of unique_tokens_30d across the batch
      recency_norm= min-max of (wr_7d - wr_30d) across the batch, clamped to [-0.5, +0.5]
    """
    chain_short = args.chain
    chain_full = CHAINS.get(chain_short, chain_short)
    wallets = [w.strip() for w in (args.wallet or []) if w and w.strip()]
    # Support comma-separated wallets in a single --wallet arg (for UI convenience)
    expanded = []
    for w in wallets:
        expanded.extend(part.strip() for part in w.split(",") if part.strip())
    wallets = expanded[:10]
    pnl_method = getattr(args, "pnl_method", "wac")
    fmt = args.format
    nocache = bool(getattr(args, "nocache", False))

    api_key = os.environ.get("BIRDEYE_API_KEY")
    if not api_key:
        cand = Path.home() / ".birdeye.env"
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if line.startswith("BIRDEYE_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not api_key:
        sys.stderr.write("[smart-money-leaderboard] missing BIRDEYE_API_KEY.\n")
        return 2

    if not wallets:
        sys.stderr.write("[smart-money-leaderboard] at least one --wallet required.\n")
        return 2

    rid = _safe_run_id("smart-money-leaderboard", f"{chain_short}_{len(wallets)}w")
    cu = {"pnl_7d": 0, "pnl_30d": 0, "pnl_details": 0}
    import requests as _req
    session = _req.Session()

    rows = []
    try:
        for w in wallets:
            sum_7d, c7 = _ws_fetch_pnl_summary(session, api_key, chain_full, w, "7d", pnl_method)
            sum_30d, c30 = _ws_fetch_pnl_summary(session, api_key, chain_full, w, "30d", pnl_method)
            per_token, cpt = _ws_fetch_pnl_per_token(session, api_key, chain_full, w, pnl_method, duration="30d")
            cu["pnl_7d"] += c7
            cu["pnl_30d"] += c30
            cu["pnl_details"] += cpt

            s7 = _wa_extract_summary(sum_7d)
            s30 = _wa_extract_summary(sum_30d)
            wr_7d = _wa_win_rate(s7)          # 0..100
            wr_30d = _wa_win_rate(s30)        # 0..100
            realized_30d = s30["realized_usd"]
            total_trades = s30["total_trade"]

            # unique token count comes from pnl/details (summary counts lacks it)
            pt_data = (per_token or {}).get("data") if isinstance(per_token, dict) else None
            tokens_list = (pt_data or {}).get("tokens") if isinstance(pt_data, dict) else None
            unique_tokens = len(tokens_list) if isinstance(tokens_list, list) else 0

            rows.append({
                "wallet": w,
                "wr_7d": wr_7d,
                "wr_30d": wr_30d,
                "realized_30d": realized_30d,
                "unique_tokens": unique_tokens,
                "total_trades": total_trades,
            })
    except Exception as e:
        sys.stderr.write(f"[smart-money-leaderboard] API error: {e}\n")
        return 4

    # ── Normalize across the batch ──────────────────────────────────
    n = len(rows)
    wr_30d_vals = [r["wr_30d"] / 100.0 for r in rows]                        # 0..1
    pnl_vals = [r["realized_30d"] for r in rows]
    tok_vals = [r["unique_tokens"] for r in rows]
    rec_vals = [(r["wr_7d"] - r["wr_30d"]) for r in rows]                    # -100..+100

    pnl_norm = _sml_rank_percentile(pnl_vals, higher_is_better=True)
    tok_norm = _sml_min_max(tok_vals)
    rec_norm = _sml_min_max(rec_vals, clamp=(-50.0, 50.0))

    for i, r in enumerate(rows):
        r["wr_30d_norm"] = wr_30d_vals[i]
        r["pnl_norm"] = pnl_norm[i]
        r["token_norm"] = tok_norm[i]
        r["recency_norm"] = rec_norm[i]
        r["composite"] = round(
            r["wr_30d_norm"] * 0.4
            + r["pnl_norm"] * 0.4
            + r["token_norm"] * 0.1
            + r["recency_norm"] * 0.1, 4
        )

    rows.sort(key=lambda r: r["composite"], reverse=True)

    cu_total = sum(cu.values())

    # ── Plain text ──────────────────────────────────────────────────
    short = lambda w: f"{w[:6]}…{w[-4:]}"
    lines = []
    lines.append(f"Smart Money Leaderboard · {chain_short.upper()} · {n} wallets")
    lines.append(f"CU: {cu_total} (pnl_7d={cu['pnl_7d']}, pnl_30d={cu['pnl_30d']}, pnl_details={cu['pnl_details']})")
    lines.append("")
    lines.append("Weights: winrate 40% · pnl 40% · diversity 10% · recency 10%")
    lines.append("")
    hdr = f"{'#':>2}  {'Wallet':<14} {'WR30d':>6} {'Realized30d':>14} {'Tokens':>6} {'Recency':>8} {'Score':>6}"
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for i, r in enumerate(rows, 1):
        rec = r["wr_7d"] - r["wr_30d"]
        rec_s = f"{rec:+.0f}%"
        lines.append(
            f"{i:>2}  {short(r['wallet']):<14} "
            f"{r['wr_30d']:>5.0f}% "
            f"{r['realized_30d']:>+13,.0f} "
            f"{r['unique_tokens']:>6} "
            f"{rec_s:>8} "
            f"{r['composite']:>6.3f}"
        )
    out_plain = "\n".join(lines)

    # ── Telegram ────────────────────────────────────────────────────
    tg_lines = [f"🏆 *Smart Money Leaderboard* · {chain_short.upper()}"]
    tg_lines.append(f"Weights: WR 40% · PnL 40% · Tokens 10% · Recency 10%")
    tg_lines.append("")
    for i, r in enumerate(rows, 1):
        rec = r["wr_7d"] - r["wr_30d"]
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        tg_lines.append(
            f"{medal} `{short(r['wallet'])}` — WR {r['wr_30d']:.0f}% · "
            f"PnL ${r['realized_30d']:+,.0f} · {r['unique_tokens']} tok · "
            f"rec {rec:+.0f}% → *{r['composite']:.3f}*"
        )
    out_telegram = "\n".join(tg_lines)

    # ── Raw JSON envelope ───────────────────────────────────────────
    profile = {
        "chain": chain_short,
        "n_wallets": n,
        "weights": {"winrate": 0.4, "pnl": 0.4, "diversity": 0.1, "recency": 0.1},
        "ranking": rows,
    }
    raw_envelope = {
        "schemaVersion": 1, "kind": "smart-money-leaderboard-v1", "runId": rid, "cached": False,
        "params": {"chain": chain_short, "wallets": wallets, "pnl_method": pnl_method},
        "profile": profile,
        "cu_used_total": cu_total, "cu_breakdown": cu,
        "snapshot_time": int(time.time()),
        "format_renderers": ["rendered", "plain", "telegram", "raw-json"],
    }
    out_raw_json = json.dumps(raw_envelope, ensure_ascii=False)

    # ── Rendered HTML ───────────────────────────────────────────────
    html_rows = ""
    for i, r in enumerate(rows, 1):
        rec = r["wr_7d"] - r["wr_30d"]
        pnl_color = "#22c55e" if r["realized_30d"] >= 0 else "#ef4444"
        rec_color = "#22c55e" if rec >= 0 else "#ef4444"
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}")
        html_rows += f'''
        <tr style="border-bottom:1px solid #1e293b">
          <td style="padding:6px 8px">{medal}</td>
          <td style="padding:6px 8px;font-family:monospace;font-size:12px">{short(r['wallet'])}</td>
          <td style="padding:6px 8px;text-align:right">{r['wr_30d']:.0f}%</td>
          <td style="padding:6px 8px;text-align:right;color:{pnl_color}">${r['realized_30d']:+,.0f}</td>
          <td style="padding:6px 8px;text-align:right">{r['unique_tokens']}</td>
          <td style="padding:6px 8px;text-align:right;color:{rec_color}">{rec:+.0f}%</td>
          <td style="padding:6px 8px;text-align:right;font-weight:700">{r['composite']:.3f}</td>
        </tr>'''
    html_rendered = f'''<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0a0e1a;color:#e2e8f0;padding:16px;border-radius:12px;max-width:720px">
  <div style="font-size:18px;font-weight:800;margin-bottom:4px">🏆 Smart Money Leaderboard</div>
  <div style="font-size:12px;color:#64748b;margin-bottom:10px">{chain_short.upper()} · {n} wallets · CU {cu_total}</div>
  <div style="font-size:11px;color:#64748b;margin-bottom:10px">Weights: winrate 40% · pnl 40% · diversity 10% · recency 10%</div>
  <table style="width:100%;border-collapse:collapse;font-size:13px">
    <thead><tr style="color:#64748b;font-size:11px;text-transform:uppercase;border-bottom:1px solid #334155">
      <th style="padding:6px 8px;text-align:left">#</th>
      <th style="padding:6px 8px;text-align:left">Wallet</th>
      <th style="padding:6px 8px;text-align:right">WR 30d</th>
      <th style="padding:6px 8px;text-align:right">Realized 30d</th>
      <th style="padding:6px 8px;text-align:right">Tokens</th>
      <th style="padding:6px 8px;text-align:right">Recency</th>
      <th style="padding:6px 8px;text-align:right">Score</th>
    </tr></thead>
    <tbody>{html_rows}
    </tbody>
  </table>
</div>'''

    rendered_payload = dict(raw_envelope)
    rendered_payload["format"] = "rendered"
    rendered_payload["rendered_html"] = html_rendered
    out_rendered_json = json.dumps(rendered_payload, ensure_ascii=False)

    stdout_prefix = f"#RUN_ID {rid}\tsmart-money-leaderboard\tcu={cu_total}\n"
    if fmt == "rendered":
        sys.stdout.write(stdout_prefix); print(out_rendered_json)
    elif fmt == "plain":
        sys.stdout.write(stdout_prefix); print(out_plain)
    elif fmt == "telegram":
        sys.stdout.write(stdout_prefix); print(out_telegram)
    else:
        sys.stdout.write(stdout_prefix); print(out_raw_json)
    return 0


def cmd_history_render(args):
    cdir = _cache_dir(getattr(args, "cache_dir", None))
    cached = _read_cache(cdir, args.run_id)
    if not cached:
        print(f"[E] Cache not found for run_id={args.run_id}")
        return 3
    kind = cached.get("kind")
    fmt = args.format
    # Backward-compat: old wallet-score cache files had no top-level `kind`.
    if not kind and (cached.get("rendered_rendered") or cached.get("alpha_score") is not None):
        kind = "wallet-alpha-score-v1"
    # Format "render" = payload envelope suitable for UI renderers, always JSON
    if fmt == "render":
        if kind in ("wallet-alpha-score-v1", "wallet-style-v1", "kline-pattern-v1", "contract-dd-v1",
                    "wallet-analysis-v1", "smart-money-profile-v1"):
            # Unwrap the pre-rendered JSON string so UI gets html + metrics directly.
            rendered_raw = cached.get("rendered_rendered") or cached.get("rendered_raw-json") or ""
            try:
                inner = json.loads(rendered_raw) if isinstance(rendered_raw, str) else rendered_raw
            except Exception:
                inner = {"html": "", "alpha_score": cached.get("alpha_score")}
            if not isinstance(inner, dict):
                inner = {"html": str(inner), "alpha_score": cached.get("alpha_score")}
            inner.setdefault("kind", kind)
            out = {"runId": args.run_id, "cached": True, "cu_used_total": 0,
                   "kind": kind, "payload": inner}
        else:
            out = {"runId": args.run_id, "cached": True, "cu_used_total": 0, "kind": kind, "payload": cached}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if kind == "trending-list":
        _render_trend_from_cache(cached, fmt, args.run_id)
        return 0
    if kind == "token-dd":
        _render_dd_from_cache(cached, fmt, args.run_id)
        return 0
    if kind == "smart-wallets":
        _render_sw_from_cache(cached, fmt, args.run_id)
        return 0
    if kind in ("wallet-alpha-score-v1", "wallet-style-v1", "kline-pattern-v1", "contract-dd-v1",
                "wallet-analysis-v1", "smart-money-profile-v1"):
        # Wallet score/style/kline/contract-dd cache stores each format as a pre-rendered string field.
        field_map = {"plain": "rendered_plain", "telegram": "rendered_telegram",
                     "raw-json": "rendered_raw-json", "rendered": "rendered_rendered"}
        field = field_map.get(fmt)
        out_text = cached.get(field) if field else None
        if out_text is None:
            # Fallback: if requested fmt not cached, try plain or dump raw.
            out_text = cached.get("rendered_plain") or json.dumps(cached, ensure_ascii=False, indent=2)
        print(out_text)
        return 0
    print(f"[E] Unknown cached kind={kind}")
    return 3


def _kp_window_to_seconds(window: str) -> int:
    w = window.strip().lower()
    if w.endswith("d"):
        return int(float(w[:-1]) * 86400)
    if w.endswith("h"):
        return int(float(w[:-1]) * 3600)
    if w.endswith("m"):
        return int(float(w[:-1]) * 60)
    try:
        return int(w)
    except Exception:
        return 7 * 86400


def _ohlcv_v3_cu(n_candles: int) -> int:
    """Birdeye /defi/v3/ohlcv CU cost scales with returned candle count.

    Tiers (items returned): 0–100 → 25, 101–300 → 30, 301–1000 → 40,
    1001–2000 → 75, 2001–5000 → 100.
    """
    n = max(0, int(n_candles or 0))
    if n <= 100:
        return 25
    if n <= 300:
        return 30
    if n <= 1000:
        return 40
    if n <= 2000:
        return 75
    return 100


_KP_PATTERN_LABELS = {
    "vertical_run_up": "🚀 Vertical Run-Up",
    "uptrend_channel": "📈 Uptrend Channel",
    "breakdown": "💥 Breakdown",
    "bounce_off_lows": "🪀 Bounce Off Lows",
    "distribution_at_highs": "📦 Distribution At Highs",
    "slow_bleed": "🩸 Slow Bleed",
    "basing_at_lows": "🧱 Basing At Lows",
    "wide_chop": "🌀 Wide Chop",
    "bullish_consolidation": "🛡️ Bullish Consolidation",
    "bearish_consolidation": "⚔️ Bearish Consolidation",
    "sideways_consolidation": "➡️ Sideways Consolidation",
}

_KP_PATTERN_COLORS = {
    "vertical_run_up": "#22c55e",
    "uptrend_channel": "#16a34a",
    "bounce_off_lows": "#10b981",
    "basing_at_lows": "#14b8a6",
    "bullish_consolidation": "#06b6d4",
    "sideways_consolidation": "#64748b",
    "wide_chop": "#94a3b8",
    "slow_bleed": "#f97316",
    "bearish_consolidation": "#ef4444",
    "distribution_at_highs": "#dc2626",
    "breakdown": "#b91c1c",
}


def cmd_kline_pattern(args):
    chain = args.chain
    address = args.address
    resolution = args.resolution
    window_s = _kp_window_to_seconds(args.window)
    fmt = args.format
    key = _load_key()
    if not key:
        sys.stderr.write("[kline-pattern] missing BIRDEYE_API_KEY.\n")
        return 2

    now = int(time.time())
    # Birdeye ohlcv `type` format: minutes lowercase (1m..30m), hours/days uppercase (1H..1D)
    be_type = resolution.upper() if resolution.endswith(("h", "d")) else resolution
    params = {
        "address": address,
        "type": be_type,
        "time_to": now,
        "time_from": now - window_s,
    }
    cu = 0
    raw = None
    try:
        with requests.Session() as s:
            raw, ms = _be(s, key, chain, "/defi/v3/ohlcv", params)
    except Exception as e:
        sys.stderr.write(f"[kline-pattern] API error: {e}\n")
        return 1

    arr: list = []
    if isinstance(raw, dict):
        for k in ("data", "items", "series"):
            v = raw.get(k)
            if isinstance(v, list):
                arr = v
                break
        if not arr and isinstance(raw.get("data"), dict):
            d2 = raw["data"]
            for k2 in ("items", "series", "data"):
                v2 = d2.get(k2)
                if isinstance(v2, list):
                    arr = v2
                    break
    elif isinstance(raw, list):
        arr = raw

    # OHLCV v3 CU scales with returned candle count
    cu += _ohlcv_v3_cu(len(arr))

    result = _kp.analyze_kline(arr)
    result["chain"] = chain
    result["address"] = address
    result["resolution"] = resolution
    result["window"] = args.window
    result["cu_used"] = cu
    result["n_candles"] = len(arr)

    run_id = f"kp_{chain}_{address.replace('.','_')[:20]}_{int(time.time())}"
    result["run_id"] = run_id

    if not result.get("ok"):
        print(json.dumps(result, ensure_ascii=False))
        return 1

    pattern = result["pattern"]
    score = result["score"]
    m = result["measurements"]
    label = _KP_PATTERN_LABELS.get(pattern, pattern)
    color = _KP_PATTERN_COLORS.get(pattern, "#64748b")

    if fmt == "plain":
        print(f"Skill #21 · Kline Pattern — {address[:20]}..")
        print(f"Pattern : {label}")
        print(f"Score   : {score}/100")
        print(f"Candles : {m['n_candles']} ({resolution})")
        print(f"  trend_up    : {m['trend_up']}")
        print(f"  slope       : {m['slope']}")
        print(f"  volatility  : {m['volatility']}")
        print(f"  drawdown    : {m['drawdown']}")
        print(f"  vol_ratio   : {m['vol_ratio']}")
        print(f"  up_from_low : {m['up_from_low']}")
        print("Evidence:")
        for e in result["evidence"]:
            print(f"  - {e}")
        print("Score deltas:")
        for d in result["deltas"]:
            print(f"  {d}")
        return 0

    if fmt == "telegram":
        out = [f"*Kline Pattern* `{address[:12]}..`"]
        out.append(f"Pattern: {label} | Score: {score}/100")
        out.append(f"Candles: {m['n_candles']} ({resolution})")
        out.append(f"trend={m['trend_up']} slope={m['slope']} vol={m['volatility']}")
        out.append(f"dd={m['drawdown']} vol_ratio={m['vol_ratio']} up_from_low={m['up_from_low']}")
        print("\n".join(out))
        return 0

    if fmt == "raw-json":
        print(json.dumps(result, ensure_ascii=False))
        return 0

    # rendered HTML
    ev_html = "".join(f'<div style="font-size:12px;color:#94a3b8;padding:2px 0">• {e}</div>' for e in result["evidence"])
    deltas_html = "".join(
        f'<div style="font-size:12px;color:{("#22c55e" if d.strip().startswith("+") else "#ef4444" if d.strip().startswith("-") else "#94a3b8")};padding:1px 0">{d}</div>'
        for d in result["deltas"]
    )
    # Measurement cards with hover tooltips explaining what each number means
    _KP_MEAS_TOOLTIPS = {
        "trend": "trend_up: mean(last 9 closes) vs mean(last 21 closes). up = recent price above longer average; down = below; flat = within ±0.3%.",
        "slope": "slope: price momentum = (mean(last 5 closes) − mean(bars 24–19 ago)) ÷ mean(bars 24–19 ago). Positive = rising, negative = falling.",
        "volatility": "volatility: mean of (high−low)÷close over the last 14 candles. Higher = wider price swings (riskier).",
        "drawdown": "drawdown: (all-time-high − current close) ÷ all-time-high. 0 = at highs; 0.5 = 50% below the peak.",
        "vol_ratio": "vol_ratio: last-candle volume ÷ mean(previous 21 volumes). >1 = above-average volume (confirms move); <1 = drying up.",
        "up_from_low": "up_from_low: (current close − all-time-low) ÷ all-time-low. 0 = at lows; higher = recovered more from the bottom.",
    }
    meas_html = "".join(
        f'<div class="ttip" data-tip="{_KP_MEAS_TOOLTIPS.get(k, "")}" title="{_KP_MEAS_TOOLTIPS.get(k, "")}" style="background:#0f172a;border-radius:6px;padding:8px;text-align:center;cursor:help">'
        f'<div style="font-size:10px;color:#64748b;text-transform:uppercase">{k}</div>'
        f'<div style="font-size:14px;font-weight:600;color:#e2e8f0;margin-top:2px">{v}</div></div>'
        for k, v in [
            ("trend", m["trend_up"]), ("slope", m["slope"]), ("volatility", m["volatility"]),
            ("drawdown", m["drawdown"]), ("vol_ratio", m["vol_ratio"]), ("up_from_low", m["up_from_low"]),
        ]
    )
    html = f'''<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0a0e1a;color:#e2e8f0;padding:16px;border-radius:12px;max-width:640px">
<div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Skill #21 · Kline Pattern</div>
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
  <div style="font-size:20px;font-weight:700;color:{color}">{label}</div>
  <div style="font-size:28px;font-weight:800;color:{color}">{score}<span style="font-size:14px;color:#64748b">/100</span></div>
</div>
<div style="font-size:12px;color:#64748b;margin-bottom:12px">chain={chain} · {resolution} · {m['n_candles']} candles · <span class="copy-addr" data-copy-addr="{address}" style="cursor:pointer;user-select:none" title="Click to copy full token address">{address[:18]}.. 📋</span></div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:14px">{meas_html}</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
  <div style="background:#0f172a;border-radius:8px;padding:10px"><div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">Evidence</div>{ev_html}</div>
  <div style="background:#0f172a;border-radius:8px;padding:10px"><div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">Score Deltas</div>{deltas_html}</div>
</div>
</div>'''
    envelope = {"schemaVersion": 1, "kind": "kline-pattern-v1", "run_id": run_id,
                "cu_used": cu, "params": {"chain": chain, "address": address, "resolution": resolution, "window": args.window,
                                          "argv": sys.argv[1:]},
                "pattern": pattern, "score": score, "measurements": m,
                "label": label, "color": color, "html": html}
    # Persist to cache so the run appears in History tab (0-CU replay later)
    cdir = _cache_dir(getattr(args, "cache_dir", None))
    file_payload = {
        "runId": run_id, "kind": "kline-pattern-v1", "cached": False,
        "cu_used_total": cu, "cu_breakdown": {"ohlcv_v3": cu},
        "params": envelope["params"],
        "pattern": pattern, "score": score, "label": label, "color": color,
        "measurements": m, "evidence": result.get("evidence", []),
        "deltas": result.get("deltas", []),
        "snapshot_time": int(time.time()),
        "rendered_plain": json.dumps(envelope, ensure_ascii=False),
        "rendered_telegram": json.dumps(envelope, ensure_ascii=False),
        "rendered_raw-json": json.dumps(envelope, ensure_ascii=False),
        "rendered_rendered": json.dumps(envelope, ensure_ascii=False),
        "out": json.dumps(envelope, ensure_ascii=False),
    }
    _write_cache(cdir, run_id, file_payload)
    sys.stdout.write(f"#RUN_ID {run_id}\tkline-pattern\tcu={cu}\n")
    print(json.dumps(envelope, ensure_ascii=False))
    return 0


def cmd_contract_dd(args):
    chain = args.chain
    address = args.address
    skip_kline = args.skip_kline
    fmt = args.format
    key = _load_key()
    if not key:
        sys.stderr.write("[contract-dd] missing BIRDEYE_API_KEY.\n")
        return 2

    cu = 0
    breakdown_cu: list[str] = []
    ovd: dict = {}
    secd: dict = {}
    holder_data: dict | None = None
    kline_result: dict | None = None

    try:
        with requests.Session() as s:
            # 1) token_overview + money_flow (21 CU)
            ov_params = {"address": address, "includes": "money_flow"}
            ov_raw, _ = _be(s, key, chain, "/defi/token_overview", ov_params)
            cu += 21
            breakdown_cu.append("overview+mf=21")
            ovd = ov_raw.get("data") or {}

            # 2) token_security (30 CU)
            try:
                sec_raw, _ = _be(s, key, chain, "/defi/token_security", {"address": address})
                cu += 30
                breakdown_cu.append("security=30")
                secd = sec_raw.get("data") or {}
            except RuntimeError:
                secd = {}
                breakdown_cu.append("security=FAIL")

            # 3) holder distribution (30 CU)
            try:
                h_raw, _ = _be(s, key, chain, "/holder/v1/distribution", {
                    "mode": "top", "top_n": 20, "include_list": "true", "token_address": address,
                })
                cu += 30
                breakdown_cu.append("holders=30")
                holder_data = h_raw.get("data") or h_raw
            except RuntimeError:
                holder_data = None
                breakdown_cu.append("holders=FAIL")

            # 4) kline for price action (CU scales with candle count, optional)
            if not skip_kline:
                try:
                    now = int(time.time())
                    k_params = {"address": address, "type": "1H",
                                "time_to": now, "time_from": now - 7 * 86400}
                    k_raw, _ = _be(s, key, chain, "/defi/v3/ohlcv", k_params)
                    arr: list = []
                    if isinstance(k_raw, dict):
                        for k in ("data", "items", "series"):
                            v = k_raw.get(k)
                            if isinstance(v, list):
                                arr = v
                                break
                    elif isinstance(k_raw, list):
                        arr = k_raw
                    k_cu = _ohlcv_v3_cu(len(arr))
                    cu += k_cu
                    breakdown_cu.append(f"kline={k_cu}")
                    kline_result = _kp.analyze_kline(arr)
                except RuntimeError:
                    kline_result = None
                    breakdown_cu.append("kline=FAIL")

    except Exception as e:
        sys.stderr.write(f"[contract-dd] API error: {e}\n")
        return 1

    # Disambiguation: if info.symbol empty, may be a wallet not a token
    symbol = (ovd.get("symbol") if isinstance(ovd, dict) else None) or ""
    if not symbol and not secd:
        result = {
            "ok": False, "error": "symbol empty and no security data — address may be a wallet, not a token",
            "address": address, "chain": chain,
        }
        if fmt == "raw-json":
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"[contract-dd] {result['error']}")
        return 1

    # Run analysis
    analysis = _cdd.analyze_contract(ovd, secd, holder_data, kline_result)
    analysis["symbol"] = symbol
    analysis["name"] = (ovd.get("name") if isinstance(ovd, dict) else None) or ""
    analysis["address"] = address
    analysis["chain"] = chain
    analysis["cu_used"] = cu
    analysis["cu_breakdown"] = breakdown_cu
    analysis["holder_count"] = (ovd.get("holder") if isinstance(ovd, dict) else None)
    analysis["liquidity_usd"] = (ovd.get("liquidity") if isinstance(ovd, dict) else None)
    analysis["marketcap"] = (ovd.get("marketCap") if isinstance(ovd, dict) else None)
    run_id = f"cdd_{chain}_{address.replace('.','_')[:20]}_{int(time.time())}"
    analysis["run_id"] = run_id

    composite = analysis["composite"]
    tier = analysis["tier"]
    name = analysis.get("name") or ""

    if fmt == "plain":
        title = f"Skill #5 · Contract DD — {symbol}" + (f" ({name})" if name else "")
        print(title)
        print(f"Address : {address}")
        print(f"Chain   : {chain}")
        print(f"Composite: {composite}/100  {tier['emoji']} {tier['name']}")
        print(f"  Safety  (45%): {analysis['safety_score']}/100")
        print(f"  Holders (30%): {analysis['holders_score']}/100")
        print(f"  Price   (25%): {analysis['price_score']}/100")
        print(f"CU used: {cu} ({', '.join(breakdown_cu)})")
        print("\nSafety breakdown:")
        for b in analysis["safety_breakdown"]:
            print(f"  {b['delta']:+d}  {b['detail']}")
        print("\nHolders breakdown:")
        for b in analysis["holders_breakdown"]:
            print(f"  {b['delta']:+d}  {b['detail']}")
        if kline_result and kline_result.get("ok"):
            print(f"\nPrice action: {kline_result['pattern']} → {kline_result['score']}/100")
        return 0

    if fmt == "telegram":
        out = [f"*Contract DD* `{symbol}`"]
        out.append(f"Composite: {composite}/100 {tier['emoji']} {tier['name']}")
        out.append(f"Safety {analysis['safety_score']} · Holders {analysis['holders_score']} · Price {analysis['price_score']}")
        out.append(f"CU: {cu}")
        print("\n".join(out))
        return 0

    if fmt == "raw-json":
        print(json.dumps(analysis, ensure_ascii=False))
        return 0

    # rendered HTML
    def _bd_html(bd_list):
        return "".join(
            f'<div style="font-size:11.5px;padding:2px 0;color:{("#22c55e" if b["delta"]>=0 else "#ef4444")}">{b["delta"]:+d} · {b["detail"]}</div>'
            for b in bd_list
        )

    safety_html = _bd_html(analysis["safety_breakdown"])
    holders_html = _bd_html(analysis["holders_breakdown"])
    price_html = _bd_html(analysis["price_breakdown"])

    html = f'''<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0a0e1a;color:#e2e8f0;padding:16px;border-radius:12px;max-width:640px">
<div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Skill #5 · Contract DD</div>
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
  <div style="font-size:18px;font-weight:700">{symbol} <span style="font-size:12px;color:#64748b;font-weight:400">{name or ''}</span></div>
  <div style="font-size:30px;font-weight:800;color:{tier['color_hex']}">{composite}<span style="font-size:14px;color:#64748b">/100</span></div>
</div>
<div style="font-size:12px;color:#64748b;margin-bottom:12px">{tier['emoji']} {tier['name']} · chain={chain} · <span class="copy-addr" data-copy-addr="{address}" style="cursor:pointer;user-select:none" title="Click to copy full token address">{address[:18]}.. 📋</span></div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:14px">
  <div class="ttip" data-tip="Safety (45%): contract security — mint/freeze authority, LP lock, buy/sell taxes, honeypot check. Starts at 100, penalties reduce the score." style="background:#0f172a;border-radius:6px;padding:8px;text-align:center;cursor:help"><div style="font-size:10px;color:#64748b">SAFETY · 45%</div><div style="font-size:18px;font-weight:700;margin-top:2px">{analysis['safety_score']}</div></div>
  <div class="ttip" data-tip="Holders (30%): holder structure — top-10 concentration, total holder count. Starts at 100, penalties for high concentration or low holder count." style="background:#0f172a;border-radius:6px;padding:8px;text-align:center;cursor:help"><div style="font-size:10px;color:#64748b">HOLDERS · 30%</div><div style="font-size:18px;font-weight:700;margin-top:2px">{analysis['holders_score']}</div></div>
  <div class="ttip" data-tip="Price (25%): price action — uses the Kline Pattern module to score the token's recent trend, momentum, and volatility." style="background:#0f172a;border-radius:6px;padding:8px;text-align:center;cursor:help"><div style="font-size:10px;color:#64748b">PRICE · 25%</div><div style="font-size:18px;font-weight:700;margin-top:2px">{analysis['price_score']}</div></div>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px">
  <div style="background:#0f172a;border-radius:8px;padding:10px"><div style="font-size:10px;color:#64748b;text-transform:uppercase;margin-bottom:4px">Safety</div>{safety_html}</div>
  <div style="background:#0f172a;border-radius:8px;padding:10px"><div style="font-size:10px;color:#64748b;text-transform:uppercase;margin-bottom:4px">Holders</div>{holders_html}</div>
  <div style="background:#0f172a;border-radius:8px;padding:10px"><div style="font-size:10px;color:#64748b;text-transform:uppercase;margin-bottom:4px">Price</div>{price_html}</div>
</div>
<div style="font-size:11px;color:#64748b">CU: {cu} ({', '.join(breakdown_cu)})</div>
</div>'''
    envelope = {"schemaVersion": 1, "kind": "contract-dd-v1", "run_id": run_id,
                "cu_used": cu, "params": {"chain": chain, "address": address, "argv": sys.argv[1:]},
                "symbol": symbol, "name": name, "composite": composite, "tier": tier,
                "safety_score": analysis["safety_score"], "holders_score": analysis["holders_score"],
                "price_score": analysis["price_score"],
                "safety_breakdown": analysis["safety_breakdown"],
                "holders_breakdown": analysis["holders_breakdown"],
                "price_breakdown": analysis["price_breakdown"],
                "cu_breakdown": breakdown_cu,
                "holder_count": analysis.get("holder_count"),
                "liquidity_usd": analysis.get("liquidity_usd"),
                "marketcap": analysis.get("marketcap"),
                "kline_result": kline_result if kline_result and kline_result.get("ok") else None,
                "html": html}
    # Persist to cache so the run appears in History tab (0-CU replay later)
    cdir = _cache_dir(getattr(args, "cache_dir", None))
    file_payload = {
        "runId": run_id, "kind": "contract-dd-v1", "cached": False,
        "cu_used_total": cu, "cu_breakdown": breakdown_cu,
        "params": envelope["params"],
        "symbol": symbol, "name": name, "composite": composite, "tier": tier,
        "snapshot_time": int(time.time()),
        "rendered_plain": json.dumps(envelope, ensure_ascii=False),
        "rendered_telegram": json.dumps(envelope, ensure_ascii=False),
        "rendered_raw-json": json.dumps(envelope, ensure_ascii=False),
        "rendered_rendered": json.dumps(envelope, ensure_ascii=False),
        "out": json.dumps(envelope, ensure_ascii=False),
    }
    _write_cache(cdir, run_id, file_payload)
    sys.stdout.write(f"#RUN_ID {run_id}\tcontract-dd\tcu={cu}\n")
    print(json.dumps(envelope, ensure_ascii=False))
    return 0


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
