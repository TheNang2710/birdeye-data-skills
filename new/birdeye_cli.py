#!/usr/bin/env python3
"""Birdeye Unified CLI — eight self-contained discovery & insight skills.

Subcommands:

  1. `trending-list`        — Skill #1  · Birdeye hot-token list (selective/classic)
  2. `price-surge`          — Skill #2  · price-surge screener (standard / advanced hydration)
  3. `token-dd-score`       — Skill #24 · 5-pillar due-diligence score 0-100 + A+..F
  4. `wallet-score`         — Skill #13 · wallet quality score (P/C/Q/A components)
  5. `wallet-style`         — Skill #11 · trading-style tagger (freq × P&L grid)
  6. `kline-pattern`        — Skill #21 · candlestick pattern classifier + 0..100 score
  7. `token-trending-score` — Skill #22 · 0..100 momentum score per interval
  8. `junk-predict`         — Skill #23 · ML junk-token classifier (0-100 junk score)
     `junk-quick-test`      — Skill #23 · same model over random tokens from the v3 list

Helpers: `history-list`, `history-render` (0-CU replay of any cached run).

Output formats (all Telegram-pasteable):
  --format plain      : fixed-width ASCII table, monospace-aligned
  --format telegram   : Markdown v2-ish (monospace block + emojis)
  --format ui         : HTML renderer payload for the console app
  --format raw-json   : single-line JSON for piping into bot frameworks

Keys are read from $BIRDEYE_API_KEY, ~/.birdeye.env or ~/.config/birdeye/.env.
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as _dt
import html
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

# --- Modular skill data/logic (pattern, wallet, trending, junk ML) ---
from modules import kline_pattern as _kp
from modules import wallet_data as _wd
from modules import trending_score as _ts
from modules import junk_ml as _jml
from modules import junk_modes as _jm


def _load_external_skill(*rel_parts):
    """Import a skill module whose filename has dashes (e.g. token-dd-score.py).

    Walks up from this CLI file looking for e.g. skills/token-duediligence/token-dd-score.py
    and returns None when the skill folder is not shipped alongside the CLI.
    """
    import importlib.util
    for base in Path(__file__).resolve().parents:
        cand = base.joinpath(*rel_parts)
        if cand.is_file():
            name = "skill_" + "_".join(rel_parts[-2:]).replace("-", "_")
            spec = importlib.util.spec_from_file_location(name, cand)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            return mod
    return None


# Skill #24 — Token Due-Diligence score (skills/token-duediligence/token-dd-score.py)
_dd_score = _load_external_skill("skills", "token-duediligence", "token-dd-score.py")

# Skill #22 — Token Trending score (skills/token-trending-score/trending-score.py)
_trending_score = _load_external_skill("skills", "token-trending-score", "trending-score.py")

BIRDEYE_BASE = "https://public-api.birdeye.so"
CHAINS = {"sol": "solana", "bsc": "bsc", "base": "base", "eth": "ethereum", "arc": "arbitrum", "robinhood": "robinhood", "multi_chain": "multi_chain", "multichain": "multi_chain"}

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


def _canonical_format(fmt: str | None, *, default: str = "ui",
                      allow_compact: bool = False,
                      allow_rugcheck: bool = False) -> str:
    f = str(fmt or default).strip().lower()
    if f in {"ui", "plain", "telegram", "json"}:
        return f
    if f in {"render", "rendered", "scorecard"}:
        return "ui"
    if f == "raw-json":
        return "json"
    if allow_compact and f == "compact":
        return "compact"
    if allow_rugcheck and f == "rugcheck":
        return "rugcheck"
    return default


def _cache_field_for_format(fmt: str | None) -> str | None:
    f = _canonical_format(fmt)
    return {
        "plain": "rendered_plain",
        "telegram": "rendered_telegram",
        "json": "rendered_json",
        "ui": "rendered_ui",
    }.get(f)


def _cache_text_for_format(payload: dict, fmt: str | None) -> str | None:
    field = _cache_field_for_format(fmt)
    legacy_map = {
        "rendered_ui": "rendered_rendered",
        "rendered_json": "rendered_raw-json",
    }
    if field and payload.get(field) is not None:
        return payload.get(field)
    legacy = legacy_map.get(field or "")
    if legacy and payload.get(legacy) is not None:
        return payload.get(legacy)
    return payload.get("out")


def _sanitize_cached_non_ui_payload(payload: dict) -> dict:
    def _clean(value):
        if isinstance(value, dict):
            out = {}
            for key, val in value.items():
                if key in (
                    "html",
                    "rendered_ui",
                    "rendered_plain",
                    "rendered_telegram",
                    "rendered_json",
                    "rendered_raw-json",
                    "rendered_rendered",
                    "out",
                ):
                    continue
                out[key] = _clean(val)
            return out
        if isinstance(value, list):
            return [_clean(v) for v in value]
        return value
    return _clean(json.loads(json.dumps(payload, ensure_ascii=False)))


def _rerender_token_dd_score_from_cache(cached: dict, fmt: str) -> str | None:
    mod = _load_external_skill("skills", "token-duediligence", "token-dd-score.py")
    source = cached.get("result") if isinstance(cached.get("result"), dict) else cached
    source = _sanitize_cached_non_ui_payload(source)
    if mod and hasattr(mod, "render"):
        try:
            return mod.render(source, "raw-json" if fmt == "raw-json" else fmt)
        except Exception:
            pass
    if fmt in ("json", "raw-json"):
        return json.dumps(source, ensure_ascii=False, indent=2 if fmt == "json" else None)
    if fmt == "telegram":
        return cached.get("rendered_telegram") or json.dumps(source, ensure_ascii=False, indent=2)
    return json.dumps(source, ensure_ascii=False, indent=2)


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
    fmt = _canonical_format(fmt)
    if fmt in {"ui", "json"}:
        print(json.dumps({
            "runId": run_id, "cached": True, "cu_used_total": 0,
            "payload": payload,
        }, ensure_ascii=False))
    elif fmt == "telegram":
        _print_trend_telegram(r, inner_args)
    else:
        _print_trend_plain(r, inner_args)


def _render_dd_from_cache(payload: dict, fmt: str, run_id: str):
    source = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    source = _sanitize_cached_non_ui_payload(source)
    # Reconvert lists -> tuples for compatibility with plain/telegram printers that expect tuple unpacking
    d = dict(source)
    d["price_changes"] = [(i, p) for [i, p] in source["price_changes"]]
    d["buy_sell_rows"] = [(i, t2, b, s2, ratio, buys, sells, tr_ratio, wal)
                           for [i, t2, b, s2, ratio, buys, sells, tr_ratio, wal] in source["buy_sell_rows"]]
    d["money_flow_rows"] = [(i, mf) for [i, mf] in source["money_flow_rows"]]

    class _Args:
        chain = source["meta"]["chain"]
        address = source["meta"]["address"]

    if fmt in ("json", "raw-json"):
        print(json.dumps(d, ensure_ascii=False))
    elif fmt in ("ui", "render"):
        ui_payload = {
            "runId": run_id,
            "cached": True,
            "cu_used_total": 0,
            "payload": d,
            "html": _render_dd_ui_html(d, _Args(), cached=True),
        }
        print(json.dumps(ui_payload, ensure_ascii=False))
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


def _mask_key(k: str | None) -> str:
    """Never print a full key — always head2****tail2."""
    if not k:
        return "(none)"
    if len(k) <= 4:
        return "****"
    return f"{k[:2]}****{k[-2:]}"


_KEY_SOURCES = (("~/.config/birdeye/.env", ENV_FILE),
                ("~/.birdeye.env", HOME_ALT_ENV),
                (".env (skill-local)", LOCAL_ENV_FILE))


def _key_source() -> tuple[str | None, str, Path | None]:
    """Return (key, human source label, path) for the first resolvable key."""
    if k := (os.environ.get("BIRDEYE_API_KEY") or "").strip():
        return k, "$BIRDEYE_API_KEY", None
    for label, cand in _KEY_SOURCES:
        if not cand.exists():
            continue
        for ln in cand.read_text().splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if ln.startswith("BIRDEYE_API_KEY="):
                v = ln.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v, label, cand
    return None, "(not found)", None


def _write_key(key: str) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(f"BIRDEYE_API_KEY={key}\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except Exception:
        pass
    return ENV_FILE


def cmd_config(args):
    """Credential onboarding: config --check | --apply <KEY> | --status."""
    action = "check" if getattr(args, "check", False) else (
        "apply" if getattr(args, "apply", None) else "status")

    if action == "apply":
        key = (args.apply or "").strip().strip('"').strip("'")
        if not key:
            print("[E] Empty key — nothing written.")
            return 2
        path = _write_key(key)
        print(f"[OK] BIRDEYE_API_KEY written to {path} (chmod 600)")
        print(f"     mask: {_mask_key(key)}")
        print("     Verify with: birdeye-cli config --check")
        return 0

    key, source, _path = _key_source()
    if action == "check":
        if key:
            print(f"[OK] Birdeye API key found — source: {source}")
            print(f"     mask: {_mask_key(key)}")
            return 0
        print("[E] No Birdeye API key found.")
        print("    Set one with:  birdeye-cli config --apply <YOUR_KEY>")
        print("    Or export:     export BIRDEYE_API_KEY=...")
        return 1

    print("Birdeye CLI — configuration status")
    print(f"  key        : {_mask_key(key) if key else '(missing)'}")
    print(f"  source     : {source}")
    print(f"  config dir : {CONFIG_DIR}")
    print(f"  env file   : {ENV_FILE}  {'(exists)' if ENV_FILE.exists() else '(absent)'}")
    print(f"  alt env    : {HOME_ALT_ENV}  {'(exists)' if HOME_ALT_ENV.exists() else '(absent)'}")
    print("  resolution : $BIRDEYE_API_KEY -> ~/.config/birdeye/.env -> ~/.birdeye.env -> ./.env")
    return 0 if key else 1


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
                    headers={"X-API-KEY": key, "x-chain": CHAINS.get(chain, chain)},
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


# Token-cell interaction, shared by every skill that renders a token row so the
# UX never changes: click the address to copy it, click the icon to open the
# token on the Birdeye web page.
_COPY_JS = ("if(navigator.clipboard){navigator.clipboard.writeText(this.dataset.copy)}"
            "var el=this;el.textContent='\u2713 copied';"
            "setTimeout(function(){el.textContent=el.dataset.label;},900);return false;")
_WEB_CHAIN = {"sol": "solana", "eth": "ethereum", "arc": "arbitrum"}


def _be_token_url(chain, address) -> str:
    c = _WEB_CHAIN.get(str(chain or ""), str(chain or ""))
    return f"https://birdeye.so/{c}/token/{address}"


def _short_addr(address: str) -> str:
    return f"{address[:6]}…{address[-4:]}" if len(address) > 10 else address


def _copy_addr_btn(address: str, color: str = "#7b8794", size: str = "10.5px") -> str:
    short = _short_addr(address)
    return ('<button type="button" data-copy="' + html.escape(address, quote=True) + '"'
            ' data-label="' + html.escape(short, quote=True) + '"'
            ' title="Copy address" onclick="' + _COPY_JS + '"'
            ' style="border:0;background:transparent;padding:0;margin:0;cursor:pointer;'
            'font-weight:500;font-family:ui-monospace;color:' + color + ';font-size:' + size + '">'
            + html.escape(short) + '</button>')


def _be_token_link(chain, address, inner_html: str, title: str = "Open on Birdeye") -> str:
    return (f'<a href="{html.escape(_be_token_url(chain, address), quote=True)}" target="_blank" '
            f'rel="noopener noreferrer" title="{html.escape(title, quote=True)}" '
            f'style="text-decoration:none;color:inherit">{inner_html}</a>')


def _dd_risk_chip(label: str, value: str, tone: str = "neutral") -> str:
    palette = {
        "good": ("rgba(34,197,94,.10)", "#86efac", "rgba(34,197,94,.22)"),
        "warn": ("rgba(250,204,21,.10)", "#fde68a", "rgba(250,204,21,.22)"),
        "bad": ("rgba(239,68,68,.10)", "#fca5a5", "rgba(239,68,68,.22)"),
        "neutral": ("#0f1115", "#cbd5e1", "#202530"),
    }
    bg, fg, bd = palette.get(tone, palette["neutral"])
    return (
        f'<div style="background:{bg};border:1px solid {bd};border-radius:999px;padding:4px 10px;'
        f'font-size:11px;color:{fg}">{html.escape(label)}: <span style="font-weight:700">{html.escape(value)}</span></div>'
    )


def _render_dd_ui_html(d: dict, args_ref=None, cached: bool = False) -> str:
    sec = d.get("security") or {}
    sm = d.get("smart_money") or {}
    sc = d.get("scores") or {}
    chain = (getattr(args_ref, "chain", None) or d.get("params", {}).get("chain") or d.get("chain") or "").upper()
    symbol = d.get("symbol") or "?"
    name = d.get("name") or symbol
    address = d.get("address") or ""
    price = d.get("price_usd")
    verdict = sc.get("verdict") or "N/A"
    final_score = sc.get("final")

    def tone_score(v):
        if not isinstance(v, (int, float)):
            return "neutral"
        if v >= 8:
            return "good"
        if v >= 5:
            return "warn"
        return "bad"

    def tone_low_good(v, ok, warn):
        if not isinstance(v, (int, float)):
            return "neutral"
        if v < ok:
            return "good"
        if v < warn:
            return "warn"
        return "bad"

    dev = sec.get("dev_holding_pct")
    top10 = sec.get("top10_holder_pct")
    honeypot = sec.get("honeypot")
    lp_locked = sec.get("lp_locked")
    price_changes = d.get("price_changes") or []
    buy_sell_rows = d.get("buy_sell_rows") or []
    mf_map = {i: mf for i, mf in (d.get("money_flow_rows") or [])}

    risk_chips = [
        _dd_risk_chip("Dev hold", f"{dev:.1f}%" if isinstance(dev, (int, float)) else "N/A", tone_low_good(dev, 2, 8)),
        _dd_risk_chip("Top10 holders", f"{top10:.1f}%" if isinstance(top10, (int, float)) else "N/A", tone_low_good(top10, 20, 40)),
        _dd_risk_chip("Honeypot", "YES" if honeypot else ("NO" if honeypot is False else "N/A"), "bad" if honeypot is True else ("good" if honeypot is False else "neutral")),
        _dd_risk_chip("LP lock", "YES" if lp_locked else ("NO" if lp_locked is False else "N/A"), "good" if lp_locked is True else ("warn" if lp_locked is False else "neutral")),
    ]
    score_blocks = []
    for key, label in (("sec", "Security"), ("smkt", "Smart Mkt"), ("act", "Activity"), ("vol", "Volume")):
        val = sc.get(key)
        tone = tone_score(val)
        color = "#22c55e" if tone == "good" else "#facc15" if tone == "warn" else "#ef4444" if tone == "bad" else "#e6e8ef"
        score_blocks.append(
            f'<div style="background:#0f1115;border-radius:9px;padding:10px;text-align:center">'
            f'<div style="font-size:10px;color:#94a3b8;text-transform:uppercase">{label}</div>'
            f'<div style="font-size:18px;font-weight:800;color:{color};margin-top:2px">{val:.1f}/10</div>'
            f'</div>' if isinstance(val, (int, float)) else
            f'<div style="background:#0f1115;border-radius:9px;padding:10px;text-align:center">'
            f'<div style="font-size:10px;color:#94a3b8;text-transform:uppercase">{label}</div>'
            f'<div style="font-size:18px;font-weight:800;color:#e6e8ef;margin-top:2px">N/A</div></div>'
        )

    price_change_html = "".join(
        f'<div style="background:#0f1115;border-radius:8px;padding:8px 10px;text-align:center">'
        f'<div style="font-size:10px;color:#94a3b8;text-transform:uppercase">{html.escape(str(win))}</div>'
        f'<div style="font-size:14px;font-weight:800;color:{"#22c55e" if isinstance(pct,(int,float)) and pct>=0 else "#ef4444" if isinstance(pct,(int,float)) else "#e6e8ef"};margin-top:2px">{_fmt_pct(pct)}</div>'
        f'</div>'
        for win, pct in price_changes
    )

    flow_rows_html = ""
    for (i, total_vol, buy_vol, sell_vol, buy_ratio, buys, sells, trade_buy_ratio, wallets) in buy_sell_rows[:5]:
        flow_rows_html += (
            f'<tr>'
            f'<td style="padding:7px 8px;color:#cbd5e1">{html.escape(str(i))}</td>'
            f'<td style="padding:7px 8px;color:#e6e8ef">{_fmt_usd(total_vol)}</td>'
            f'<td style="padding:7px 8px;color:#e6e8ef">{("N/A" if buy_ratio is None else f"{buy_ratio*100:.0f}%")}</td>'
            f'<td style="padding:7px 8px;color:#e6e8ef">{("N/A" if trade_buy_ratio is None else f"{trade_buy_ratio*100:.0f}%")}</td>'
            f'<td style="padding:7px 8px;color:#e6e8ef">{_fmt_usd(mf_map.get(i))}</td>'
            f'<td style="padding:7px 8px;color:#94a3b8">{int(wallets):,}</td>'
            f'</tr>'
        )
    if not flow_rows_html:
        flow_rows_html = '<tr><td colspan="6" style="padding:10px 8px;color:#94a3b8">No buy/sell pressure rows.</td></tr>'

    sm_text = "Request failed"
    if sm.get("batch_join_success") and sm.get("smart_traders_no") is None:
        sm_text = "Not in smart-money top 100 today"
    elif isinstance(sm.get("smart_traders_no"), (int, float)):
        sm_text = f'{int(sm["smart_traders_no"]):,} wallets'
        if sm.get("rank_in_sm_top100"):
            sm_text += f' · rank #{int(sm["rank_in_sm_top100"])}/100'

    final_color = "#22c55e" if isinstance(final_score, (int, float)) and final_score >= 8 else "#facc15" if isinstance(final_score, (int, float)) and final_score >= 5 else "#ef4444"
    verdict_chip = _dd_risk_chip("Verdict", str(verdict), "good" if verdict == "BUY" else "warn" if verdict in {"WATCH", "NEUTRAL"} else "bad")
    cached_chip = ""
    if cached:
        cached_chip = f'<div style="font-size:10px;color:#64748b;margin-top:8px">💾 Cached run · Original API cost ⚡{int(d.get("cu_used_total") or 0)} CU · Re-render = 0 CU</div>'

    return f'''<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0a0e1a;color:#e2e8f0;padding:16px;border-radius:12px;max-width:820px">
  <div style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:14px">
    <div style="min-width:0">
      <div style="font-size:20px;font-weight:800;color:#e6e8ef">🔍 Token DD</div>
      <div style="font-size:12px;color:#94a3b8;margin-top:2px">{html.escape(chain)} · {html.escape(symbol)} · {html.escape(name)}</div>
      <div style="font-size:11px;color:#64748b;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;margin-top:4px">{html.escape(address)}</div>
    </div>
    <div style="text-align:right;flex-shrink:0">
      <div style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.34px">Final DD Score</div>
      <div style="font-size:30px;font-weight:900;color:{final_color}">{f"{final_score:.1f}/10" if isinstance(final_score,(int,float)) else "N/A"}</div>
      {verdict_chip}
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:10px">
    <div style="background:#0f1115;border-radius:9px;padding:10px;text-align:center"><div style="font-size:10px;color:#94a3b8;text-transform:uppercase">Price</div><div style="font-size:15px;font-weight:800;color:#e6e8ef;margin-top:2px">{_fmt_usd(price)}</div></div>
    <div style="background:#0f1115;border-radius:9px;padding:10px;text-align:center"><div style="font-size:10px;color:#94a3b8;text-transform:uppercase">MCap</div><div style="font-size:15px;font-weight:800;color:#e6e8ef;margin-top:2px">{_fmt_usd(d.get("marketcap_usd"))}</div></div>
    <div style="background:#0f1115;border-radius:9px;padding:10px;text-align:center"><div style="font-size:10px;color:#94a3b8;text-transform:uppercase">Liquidity</div><div style="font-size:15px;font-weight:800;color:#e6e8ef;margin-top:2px">{_fmt_usd(d.get("liquidity_usd"))}</div></div>
    <div style="background:#0f1115;border-radius:9px;padding:10px;text-align:center"><div style="font-size:10px;color:#94a3b8;text-transform:uppercase">FDV</div><div style="font-size:15px;font-weight:800;color:#e6e8ef;margin-top:2px">{_fmt_usd(d.get("fdv_usd"))}</div></div>
    <div style="background:#0f1115;border-radius:9px;padding:10px;text-align:center"><div style="font-size:10px;color:#94a3b8;text-transform:uppercase">Holders</div><div style="font-size:15px;font-weight:800;color:#e6e8ef;margin-top:2px">{f"{int(d['holder_count']):,}" if isinstance(d.get("holder_count"), (int,float)) else "N/A"}</div></div>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">{''.join(risk_chips)}</div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px">{''.join(score_blocks)}</div>
  <div style="background:#0f1115;border-radius:10px;padding:12px;margin-bottom:12px">
    <div style="font-size:12px;font-weight:700;color:#e6e8ef;margin-bottom:8px">Price Action</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(92px,1fr));gap:8px">{price_change_html or '<div style="font-size:12px;color:#94a3b8">No price windows.</div>'}</div>
  </div>
  <div style="display:grid;grid-template-columns:minmax(0,1.3fr) minmax(240px,.7fr);gap:12px">
    <div style="background:#0f1115;border-radius:10px;padding:12px">
      <div style="font-size:12px;font-weight:700;color:#e6e8ef;margin-bottom:8px">Buy / Sell Pressure</div>
      <div style="overflow:auto">
        <table style="width:100%;border-collapse:collapse;font-size:12px">
          <thead><tr style="color:#94a3b8;text-align:left"><th style="padding:0 8px 6px">Win</th><th style="padding:0 8px 6px">Vol</th><th style="padding:0 8px 6px">Buy%</th><th style="padding:0 8px 6px">Trade B%</th><th style="padding:0 8px 6px">Net Flow</th><th style="padding:0 8px 6px">Wallets</th></tr></thead>
          <tbody>{flow_rows_html}</tbody>
        </table>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:12px">
      <div style="background:#0f1115;border-radius:10px;padding:12px">
        <div style="font-size:12px;font-weight:700;color:#e6e8ef;margin-bottom:6px">Smart Money</div>
        <div style="font-size:18px;font-weight:800;color:#e6e8ef">{html.escape(sm_text)}</div>
      </div>
      <div style="background:#0f1115;border-radius:10px;padding:12px">
        <div style="font-size:12px;font-weight:700;color:#e6e8ef;margin-bottom:6px">Run Snapshot</div>
        <div style="font-size:12px;color:#cbd5e1">⚡CU cost: {int(d.get("cu_used_total") or 0)}</div>
        <div style="font-size:12px;color:#cbd5e1;margin-top:4px">⏱ {int(d.get("latency_ms") or 0)} ms</div>
        <div style="font-size:12px;color:#94a3b8;margin-top:4px">{html.escape(str(d.get("snapshot_time") or ""))}</div>
        {cached_chip}
      </div>
    </div>
  </div>
  <div style="font-size:10px;color:#475569;margin-top:10px">⚡CU cost: {int(d.get("cu_used_total") or 0)} ({html.escape(str(d.get("cu_breakdown") or ""))})</div>
</div>'''


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

    ph = sub.add_parser("history-list", help="List recent cached runs (default last 25)")
    ph.add_argument("--limit", type=int, default=25)
    ph.add_argument("--format", choices=["plain", "json", "raw-json"], default="plain")
    ph.set_defaults(func=cmd_history_list)

    pr = sub.add_parser("history-render", help="Render a cached run_id with any format (0 API call)")
    pr.add_argument("--run-id", required=True)
    pr.add_argument("--format", choices=["ui", "json", "telegram", "plain", "raw-json", "render", "rendered"], default="ui",
                    help="'ui' returns the renderer payload / HTML envelope used by the console app.")
    pr.set_defaults(func=cmd_history_render)

    ptl = sub.add_parser("trending-list",
                         help="Skill #1 · Trending List — Birdeye /defi/token_trending (30 CU). "
                              "Pure API passthrough: Birdeye's own hot-token ranking, no local "
                              "scoring (use Skill #22 token-trending-score for the momentum score).")
    ptl.add_argument("--chain",
                     choices=["solana", "bsc", "base", "ethereum", "arbitrum", "robinhood", "multi_chain"],
                     default="solana")
    ptl.add_argument("--mode", choices=["selective", "classic"], default="selective")
    ptl.add_argument("--sort-by", dest="sort_by", choices=["rank", "volumeUSD", "liquidity"], default="rank")
    ptl.add_argument("--sort-type", dest="sort_type", choices=["desc", "asc"], default=None)
    ptl.add_argument("--interval", choices=["5m", "30m", "1h", "4h", "24h"], default="24h")
    ptl.add_argument("--offset", type=int, default=0)
    ptl.add_argument("--limit", type=int, default=20, help="Rows to return, 1..50 (default 20).")
    ptl.add_argument("--platform", default=None,
                     help="Best-effort client-side filter by launch platform (e.g. pump.fun).")
    ptl.add_argument("--format", choices=["ui", "json", "telegram", "plain", "raw-json", "rendered"], default="ui")
    ptl.set_defaults(func=cmd_trending_list)

    pps = sub.add_parser("price-surge",
                         help="Skill #2 · Price Surge Screen — scan a chain for price-surge signals "
                              "inside a market-cap range, then auto-filter rug-pull, wash-trade and "
                              "honeypot risk. `standard` = one /defi/v3/token/list call (50 CU); "
                              "`advanced` = that list plus per-token top-traders and holder health; "
                              "`--with-security` adds /defi/token_security per hydrated row.")
    pps.add_argument("--chain",
                     choices=["solana", "bsc", "base", "ethereum", "arbitrum", "robinhood"],
                     default="solana")
    pps.add_argument("--interval",
                     choices=["1m", "5m", "30m", "1h", "2h", "4h", "8h", "24h", "7d", "30d"],
                     default="1h", help="Surge window used for the price / volume / trade filters.")
    pps.add_argument("--mode", choices=["standard", "advanced"], default="standard",
                     help="standard = token list v3 only (cheapest); advanced = hydrate top traders and "
                          "holder health for the top rows.")
    pps.add_argument("--with-security", dest="with_security", action="store_true",
                     help="advanced: also call /defi/token_security per hydrated row (30 CU/token) to "
                          "get honeypot / mint / freeze / LP / tax plus top-10%% concentration.")
    pps.add_argument("--min-price-change", dest="min_price_change", type=float, default=50.0,
                     help="Surge floor: minimum price change %% over --interval (default 50).")
    pps.add_argument("--min-market-cap", dest="min_market_cap", type=float, default=None,
                     help="Lower bound of the market-cap range (server-side).")
    pps.add_argument("--max-market-cap", dest="max_market_cap", type=float, default=None,
                     help="Upper bound of the market-cap range (server-side).")
    pps.add_argument("--min-liquidity", dest="min_liquidity", type=float, default=10000.0)
    pps.add_argument("--max-liquidity", dest="max_liquidity", type=float, default=None)
    pps.add_argument("--min-volume", dest="min_volume", type=float, default=5000.0,
                     help="Minimum traded USD volume over --interval (default 5000).")
    pps.add_argument("--min-trade-count", dest="min_trade_count", type=int, default=None)
    pps.add_argument("--min-holders", dest="min_holders", type=int, default=None)
    pps.add_argument("--platform", default=None, help="Launch platform, e.g. pump.fun.")
    pps.add_argument("--sort-by", dest="sort_by",
                     choices=["price_change", "volume", "market_cap", "liquidity", "trade_count", "holder"],
                     default="price_change")
    pps.add_argument("--sort-type", dest="sort_type", choices=["desc", "asc"], default="desc")
    pps.add_argument("--limit", type=int, default=10, help="Rows to return, 1..100 (default 10).")
    pps.add_argument("--offset", type=int, default=0)
    pps.add_argument("--top", type=int, default=10,
                     help="advanced: hydrate at most this many of the top kept rows (CU bound).")
    pps.add_argument("--no-auto-filter", dest="no_auto_filter", action="store_true",
                     help="Keep every row and switch off the automatic rug / wash-trade exclusion.")
    pps.add_argument("--no-holder-health", dest="no_holder_health", action="store_true",
                     help="advanced: skip the holder-profile call (Solana only, −30 CU/token).")
    pps.add_argument("--max-liq-mcap-ratio", dest="max_liq_mcap_ratio", type=float, default=0.005,
                     help="Exclude when liquidity/market_cap falls below this (rug-pull proxy, default 0.005).")
    pps.add_argument("--max-trades-per-wallet", dest="max_trades_per_wallet", type=float, default=150.0,
                     help="Exclude when 24h trades / 24h unique wallets exceeds this (wash-trade proxy).")
    pps.add_argument("--max-dev-hold-pct", dest="max_dev_hold_pct", type=float, default=None,
                     help="advanced: exclude when dev holds more than this %% of supply.")
    pps.add_argument("--max-top10-pct", dest="max_top10_pct", type=float, default=None,
                     help="advanced + --with-security: exclude when the top-10 holders own more than this %%.")
    pps.add_argument("--min-kol-buyers", dest="min_kol_buyers", type=int, default=None,
                     help="advanced: exclude when the tagged KOL buyer count is below this.")
    pps.add_argument("--format", choices=["ui", "json", "telegram", "plain", "raw-json", "rendered"], default="ui")
    pps.set_defaults(func=cmd_price_surge)

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
    pws.add_argument("--format", choices=["ui", "json", "telegram", "plain", "raw-json", "rendered", "compact"], default="ui",
                     help="ui = HTML renderer payload · plain = ASCII table · telegram = Unicode paste card · "
                          "json = structured envelope · compact = numeric-only blocks (use with --include).")
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
    pwst.add_argument("--format", choices=["ui", "json", "telegram", "plain", "raw-json", "rendered"], default="ui")
    pwst.set_defaults(func=cmd_wallet_style)

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
    pkp.add_argument("--format", choices=["ui", "json", "telegram", "plain", "raw-json", "rendered"], default="ui")
    pkp.set_defaults(func=cmd_kline_pattern)

    # --- Skill #22 — Token Trending Score (external skill module) ---
    if _trending_score is not None:
        _trending_score.add_parser(sub, CHAINS)

    # Skill #23 — Junk Token Prediction (ML classifier)
    pj = sub.add_parser("junk-predict",
                         help="Skill #23 · Junk Token Prediction — ML predicts junk score (0-100) "
                              "from mcap/liquidity/volume/tx/trader + top-holder concentration. "
                              "Fetches /defi/token_overview (21 CU) + /holder/v1/distribution (30 CU) per token. ~51 CU/token.")
    pj.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    pj.add_argument("--tokens", required=True,
                    help="Comma-separated or newline-separated token addresses")
    pj.add_argument("--model", choices=["unsupervised", "function", "supervised"], default="unsupervised",
                    help="Scoring model: unsupervised = LR16, function = tuned heuristic, "
                         "supervised = GBM. Model params are fixed.")
    pj.add_argument("--no-holding", dest="no_holding", action="store_true", default=False,
                    help="Skip /holder/v1/distribution (saves 30 CU/token). The concentration "
                         "contribution to the junk score is dropped (treated as 0).")
    pj.add_argument("--include", default=None,
                    help="Optional include flags. Supported: holding_distribution (now the default).")
    pj.add_argument("--score-b64", default=None,
                    help="0-CU re-score: base64(JSON) of a previous junk-predict run "
                         "(envelope or results[]). Skips every Birdeye call, only re-runs the scorer.")
    pj.add_argument("--format", choices=["ui", "json", "telegram", "plain", "raw-json", "rendered"], default="ui")
    pj.set_defaults(func=cmd_junk_predict)

    pjq = sub.add_parser("junk-quick-test",
                         help="Skill #23 · Junk Quick Test — fetches up to 5000 tokens via "
                              "/defi/v3/token/list/scroll (1 call, 300 CU), randomly picks N tokens, "
                              "runs ML junk prediction on list data (no per-token overview call).")
    pjq.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    pjq.add_argument("--num", type=int, default=30,
                     help="Number of random tokens to evaluate (default 30)")
    pjq.add_argument("--limit", type=int, default=5000,
                     help="Scroll page size 1..5000 (default 5000)")
    pjq.add_argument("--sort-by", default="liquidity",
                     help="Sort field (default liquidity). See Birdeye v3 list docs.")
    pjq.add_argument("--sort-type", choices=["desc", "asc"], default="desc")
    pjq.add_argument("--platform", default=None,
                     help="Filter by platform (e.g. pump.fun, moonshot, raydium)")
    pjq.add_argument("--min-liquidity", type=float, default=None)
    pjq.add_argument("--max-liquidity", type=float, default=None)
    pjq.add_argument("--min-market-cap", type=float, default=None)
    pjq.add_argument("--max-market-cap", type=float, default=None)
    pjq.add_argument("--format", choices=["ui", "json", "telegram", "plain", "raw-json", "rendered"], default="ui")
    pjq.set_defaults(func=cmd_junk_quick_test)

    # Credential onboarding (mirrors `gmgn-cli config` / birdeye-screener `config`)
    pcfg = sub.add_parser("config",
                          help="Credential onboarding — check / apply / status the Birdeye API key. "
                               "`config --check` exits 0 when a key is resolvable, 1 otherwise.")
    gcfg = pcfg.add_mutually_exclusive_group()
    gcfg.add_argument("--check", action="store_true",
                      help="Pre-flight: exit 0 if a key is resolvable, exit 1 if not.")
    gcfg.add_argument("--status", action="store_true",
                      help="Show the masked key (head2****tail2), its source and config paths.")
    gcfg.add_argument("--apply", metavar="KEY", default=None,
                      help="Write KEY to ~/.config/birdeye/.env (chmod 600).")
    pcfg.set_defaults(func=cmd_config)

    # Skill #24 — token-dd-score (external skill module, optional)
    if _dd_score is not None:
        _dd_score.add_parser(sub, CHAINS)

    return p


def cli() -> int:
    """Console-script entrypoint: `birdeye-cli <subcommand> ...`."""
    return main(sys.argv[1:])


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
                # Legacy rows lack the copy-tradeability breakdown — skip so the
                # 5 component cards are not lost on replay.
                if not (r.get("copy_components_json") or "").strip():
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
    """Upsert one wallet row into the 24h CSV cache.

    The file is rewritten with the current header each time so a header
    change (new columns) migrates old rows cleanly instead of shifting
    columns out of alignment.
    """
    fp = _ws_wallet_csv_path(cdir)
    rows = []
    if fp.exists():
        try:
            with fp.open("r", encoding="utf-8", newline="") as fh:
                rows = [dict(r) for r in csv.DictReader(fh)]
        except Exception:
            rows = []
    rows.append(payload)
    try:
        with fp.open("w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=_WS_CSV_HEADER)
            wr.writeheader()
            for r in rows:
                wr.writerow({k: r.get(k, "") for k in _WS_CSV_HEADER})
    except Exception:
        pass


def _ws_total_cu(cu):
    total = 0
    if isinstance(cu, dict):
        for v in cu.values():
            try:
                total += int(v or 0)
            except Exception:
                pass
    return total


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
    fmt = _canonical_format(getattr(args, "format", None), allow_compact=True)
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
        out = _cache_text_for_format(payload, fmt)
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
            try:
                copy_comps_cache = json.loads(cached_csv.get("copy_components_json") or "{}") or None
            except Exception:
                copy_comps_cache = None
            cu_from_cache = {"original_api_cu": int(cached_csv.get("cu_used_total") or 0)}
            minimal_payload = {
                "alpha_score": alpha,
                "tier": {"name": tier_name, "emoji": tier_emoji, "color_hex": tier_color},
                "copy_score": round(copy_score_cache, 2),
                "copy_tier": {"name": copy_tier_cache[0], "emoji": copy_tier_cache[1], "color_hex": copy_tier_cache[2]},
                "copy_components": copy_comps_cache,
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
            elif fmt == "json":
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
            elif fmt == "ui":
                payload = {
                    "schemaVersion": 1, "kind": "wallet-alpha-score-v1",
                    "params": {"chain": chain_short, "wallet": wallet, "duration": duration, "pnl_method": pnl_method,
                               "skip_rug": skip_rug, "skip_portfolio": skip_portfolio, "skip_first_tx": skip_first_tx},
                    "alpha_score": alpha,
                    "copy_score": round(copy_score_cache, 2),
                    "copy_tier": {"name": copy_tier_cache[0], "emoji": copy_tier_cache[1], "color_hex": copy_tier_cache[2]},
                    "copy_components": copy_comps_cache,
                    "copy_formula": None,
                    "components": minimal_payload["components"],
                    "step_checks": minimal_payload["step_checks"],
                    "metrics": minimal_payload["metrics"],
                    "tier": minimal_payload["tier"],
                    "wallet_info": minimal_payload["wallet_info"],
                    "cu_used_total": 0,
                    "cu_breakdown": {"replay_cache": 0, "original_api_cu": int(cached_csv.get("cu_used_total") or 0)},
                    "html": _ws_format_rendered_html(minimal_payload, wallet, chain_short, duration, vars(args), cu_from_cache, rid, cached_flag=True),
                    "format_renderers": ["ui", "plain", "telegram", "json"],
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
            "copy_components_json": json.dumps(result.get("copy_components") or {}, ensure_ascii=False),
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
        "format_renderers": ["ui", "plain", "telegram", "json"],
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
            "rendered_json": out_raw_json,
            "rendered_ui": out_rendered_json,
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
    elif fmt == "json":
        sys.stdout.write(stdout_prefix_line)
        sys.stdout.write(out_raw_json)
    elif fmt == "ui":
        sys.stdout.write(stdout_prefix_line)
        sys.stdout.write(out_rendered_json)
    sys.stdout.write("\n")
    return 0


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
    fmt = _canonical_format(fmt)
    if fmt == "json":
        out = {"runId": run_id, "cached": True, "cu_used_total": payload.get("cu_used_total", 0), "payload": payload}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if fmt == "telegram":
        _print_sw_telegram(payload)
    elif fmt == "ui":
        _print_sw_scorecard(payload)
    else:
        _print_sw_plain(payload)
    return 0


# ============================================================
# History list + render
# ============================================================

def cmd_history_list(args):
    fmt = _canonical_format(getattr(args, "format", None), default="plain")
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
                "token-trending-score-v1": f"TS · {params.get('chain','sol')} · {params.get('address','')[:8]}…",
            }.get(kind, "run")
            extra1 = {
                "trending-list": f"{raw.get('total_tokens', len(raw.get('rows',[])))} tokens",
                "token-dd": f"{raw.get('symbol') or raw.get('address') or ''} · score {raw.get('scores',{}).get('final','?')}",
                "smart-wallets": f"PASS {raw.get('total_pass', len(raw.get('results_pass',[])))} · {raw.get('cu_used_total','?')}CU",
                "token-trending-score-v1": f"{raw.get('symbol') or ''} · overall {raw.get('overall_trending_score','?')}",
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
    if fmt == "json":
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
        _snap = str(it["snapshot_time"]) if it["snapshot_time"] else ""
        info = it["detail"] or (_snap and _snap[-8:]) or it["title"]
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
    fmt = _canonical_format(getattr(args, "format", None))
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
        out = _cache_text_for_format(payload, fmt)
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
        "format_renderers": ["ui", "plain", "telegram", "json"],
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
            "rendered_json": out_raw_json,
            "rendered_ui": out_rendered_json,
            "rendered_raw-json": out_raw_json,
            "rendered_rendered": out_rendered_json,
            "out": out_plain,
        }
        _cache_path(cdir, rid).write_text(json.dumps(file_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    stdout_prefix = f"#RUN_ID {rid}\twallet-style\tcu={cu_total}\n"
    if fmt == "ui":
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


def cmd_history_render(args):
    cdir = _cache_dir(getattr(args, "cache_dir", None))
    cached = _read_cache(cdir, args.run_id)
    if not cached:
        print(f"[E] Cache not found for run_id={args.run_id}")
        return 3
    kind = cached.get("kind")
    fmt = _canonical_format(getattr(args, "format", None))
    # Backward-compat: old wallet-score cache files had no top-level `kind`.
    if not kind and (cached.get("rendered_rendered") or cached.get("alpha_score") is not None):
        kind = "wallet-alpha-score-v1"
    if fmt == "ui":
        if kind in ("wallet-alpha-score-v1", "wallet-style-v1", "kline-pattern-v1", "contract-dd-v1",
                    "wallet-analysis-v1", "smart-money-profile-v1", "token-trending-score-v1",
                    "smart-money-leaderboard-v1", "token-dd-score-v1", "trending-list-v1",
                    "price-surge-v1"):
            # Unwrap the pre-rendered JSON string so UI gets html + metrics directly.
            rendered_raw = _cache_text_for_format(cached, "ui") or _cache_text_for_format(cached, "json") or ""
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
    if kind == "token-dd-score-v1" and fmt in ("plain", "telegram", "json", "raw-json"):
        out_text = _rerender_token_dd_score_from_cache(cached, fmt)
        if out_text is not None:
            print(out_text)
            return 0
    if kind in ("wallet-alpha-score-v1", "wallet-style-v1", "kline-pattern-v1", "contract-dd-v1",
                "wallet-analysis-v1", "smart-money-profile-v1", "token-trending-score-v1",
                "smart-money-leaderboard-v1", "junk-predict-v1", "junk-quick-test-v1",
                "token-dd-score-v1", "trending-list-v1", "price-surge-v1") or any(
                    cached.get(k) is not None for k in ("rendered_plain", "rendered_telegram", "rendered_json", "rendered_ui")
                ):
        # Rendered-cache skills store each format as a pre-rendered string field.
        out_text = _cache_text_for_format(cached, fmt)
        if out_text is not None and fmt in ("json", "raw-json"):
            try:
                out_obj = json.loads(out_text)
            except Exception:
                out_obj = None
            if isinstance(out_obj, dict):
                out_text = json.dumps(
                    _sanitize_cached_non_ui_payload(out_obj),
                    ensure_ascii=False,
                    indent=2 if fmt == "json" else None,
                )
        if out_text is None:
            # Fallback: if requested fmt not cached, try plain or dump raw.
            if fmt in ("json", "raw-json"):
                out_text = json.dumps(_sanitize_cached_non_ui_payload(cached), ensure_ascii=False, indent=2 if fmt == "json" else None)
            else:
                out_text = cached.get("rendered_plain") or json.dumps(_sanitize_cached_non_ui_payload(cached), ensure_ascii=False, indent=2)
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
    fmt = _canonical_format(getattr(args, "format", None))
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

    plain_lines = [
        f"Skill #21 · Kline Pattern — {address[:20]}..",
        f"Pattern : {label}",
        f"Score   : {score}/100",
        f"Candles : {m['n_candles']} ({resolution})",
        f"  trend_up    : {m['trend_up']}",
        f"  slope       : {m['slope']}",
        f"  volatility  : {m['volatility']}",
        f"  drawdown    : {m['drawdown']}",
        f"  vol_ratio   : {m['vol_ratio']}",
        f"  up_from_low : {m['up_from_low']}",
        "Evidence:",
    ]
    plain_lines.extend(f"  - {e}" for e in result["evidence"])
    plain_lines.append("Score deltas:")
    plain_lines.extend(f"  {d}" for d in result["deltas"])
    out_plain = "\n".join(plain_lines)

    tg_lines = [f"*Kline Pattern* `{address[:12]}..`"]
    tg_lines.append(f"Pattern: {label} | Score: {score}/100")
    tg_lines.append(f"Candles: {m['n_candles']} ({resolution})")
    tg_lines.append(f"trend={m['trend_up']} slope={m['slope']} vol={m['volatility']}")
    tg_lines.append(f"dd={m['drawdown']} vol_ratio={m['vol_ratio']} up_from_low={m['up_from_low']}")
    out_telegram = "\n".join(tg_lines)

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
    out_raw_json = json.dumps(result, ensure_ascii=False)
    out_rendered_json = json.dumps(envelope, ensure_ascii=False)
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
        "rendered_plain": out_plain,
        "rendered_telegram": out_telegram,
        "rendered_json": out_raw_json,
        "rendered_ui": out_rendered_json,
        "rendered_raw-json": out_raw_json,
        "rendered_rendered": out_rendered_json,
        "out": out_plain,
    }
    _write_cache(cdir, run_id, file_payload)
    sys.stdout.write(f"#RUN_ID {run_id}\tkline-pattern\tcu={cu}\n")
    if fmt == "plain":
        print(out_plain)
        return 0
    if fmt == "telegram":
        print(out_telegram)
        return 0
    if fmt == "json":
        print(out_raw_json)
        return 0
    print(out_rendered_json)
    return 0


def cmd_trending_score(args):
    """Skill #22 — delegate to the standalone skill module.

    The implementation now lives in
    ``skills/token-trending-score/trending-score.py`` (single source of truth),
    loaded above as ``_trending_score`` and registered by ``build_parser``.
    """
    if _trending_score is None:
        sys.stderr.write("[token-trending-score] skill module not found "
                         "(skills/token-trending-score/trending-score.py).\n")
        return 1
    return _trending_score.run(args)


_TL_INTERVALS = ["5m", "30m", "1h", "4h", "24h"]
_TL_SORT_FIELDS = ["rank", "volumeUSD", "liquidity"]


def cmd_trending_list(args):
    """Skill #1 — Trending List (Birdeye /defi/token_trending).

    A single `/defi/token_trending` call (30 CU) returns Birdeye's own
    hot-token ranking untouched — no local scoring. For the momentum score of a
    specific token use Skill #22 (`token-trending-score`).
    """
    chain = args.chain
    sort_by = str(getattr(args, "sort_by", "rank") or "rank")
    if sort_by not in _TL_SORT_FIELDS:
        sort_by = "rank"
    interval = str(getattr(args, "interval", "24h") or "24h")
    if interval not in _TL_INTERVALS:
        interval = "24h"
    mode = str(getattr(args, "mode", "selective") or "selective").lower()
    if mode not in ("selective", "classic"):
        mode = "selective"
    if mode == "classic" and interval not in ("1h", "4h", "24h"):
        sys.stderr.write("[trending-list] classic mode supports only 1h, 4h, and 24h. "
                         "Use selective for 5m and 30m.\n")
        return 2
    sort_type_raw = getattr(args, "sort_type", None)
    sort_type = str(sort_type_raw or ("asc" if sort_by == "rank" else "desc"))
    offset = max(0, int(getattr(args, "offset", 0) or 0))
    limit = max(1, min(int(getattr(args, "limit", 20) or 20), 50))
    platform = (getattr(args, "platform", None) or "").strip().lower() or None
    fmt = _canonical_format(getattr(args, "format", None))
    key = _load_key()
    if not key:
        sys.stderr.write("[trending-list] missing BIRDEYE_API_KEY.\n")
        return 2

    cu = 0
    breakdown_cu: list[str] = []
    run_id = f"trend_{chain}_{int(time.time())}"

    params: dict[str, Any] = {
        "sort_by": sort_by,
        "mode": mode,
        "sort_type": sort_type,
        "interval": interval,
        "offset": offset,
        "limit": limit,
        "ui_amount_mode": "scaled",
    }
    try:
        with requests.Session() as s:
            raw, _ms = _be(s, key, chain, "/defi/token_trending", params)
    except RuntimeError as e:
        sys.stderr.write(f"[trending-list] {e}\n")
        return 1
    cu += 30
    breakdown_cu.append("token_trending=30")

    data = (raw.get("data") if isinstance(raw, dict) else {}) or {}
    tokens = data.get("tokens") or data.get("items") or []

    def _norm_chain(value: Any) -> str:
        s = str(value or "").strip().lower()
        aliases = {
            "sol": "solana",
            "solana": "solana",
            "bsc": "bsc",
            "binance-smart-chain": "bsc",
            "binance smart chain": "bsc",
            "base": "base",
            "eth": "ethereum",
            "ethereum": "ethereum",
            "arc": "arbitrum",
            "arbitrum": "arbitrum",
            "robinhood": "robinhood",
            "multi": "multi_chain",
            "multi_chain": "multi_chain",
            "multichain": "multi_chain",
        }
        return aliases.get(s, s or chain)

    def _svg_uri(svg: str) -> str:
        payload = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{payload}"

    def _chain_logo_uri(chain_code: str) -> str:
        code = _norm_chain(chain_code)
        svgs = {
            "solana": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop stop-color='#00FFA3'/><stop offset='1' stop-color='#DC1FFF'/></linearGradient></defs>
<circle cx='32' cy='32' r='32' fill='#0b0f14'/><g fill='url(#g)'>
<rect x='14' y='16' width='36' height='8' rx='4' transform='skewX(-18)'/>
<rect x='14' y='28' width='36' height='8' rx='4' transform='skewX(-18)'/>
<rect x='14' y='40' width='36' height='8' rx='4' transform='skewX(-18)'/></g></svg>""",
            "bsc": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<circle cx='32' cy='32' r='32' fill='#0b0f14'/><g fill='#f3ba2f'>
<path d='M32 12l7 7-7 7-7-7 7-7zm-12 12l7 7-7 7-7-7 7-7zm24 0l7 7-7 7-7-7 7-7zm-12 12l7 7-7 7-7-7 7-7zm0-18l14 14-5 5-9-9-9 9-5-5 14-14zm0 18l9 9-9 9-9-9 5-5 4 4 4-4 5 5z'/></g></svg>""",
            "base": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<circle cx='32' cy='32' r='32' fill='#0052ff'/><circle cx='32' cy='32' r='11' fill='#fff'/><path d='M13 32c0-10.5 8.5-19 19-19v9c-5.5 0-10 4.5-10 10z' fill='#fff'/></svg>""",
            "ethereum": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<circle cx='32' cy='32' r='32' fill='#0b0f14'/><g fill='none'><path d='M32 9l13 22-13 7-13-7 13-22z' fill='#8a92b2'/><path d='M32 55l13-19-13 7-13-7 13 19z' fill='#62688f'/><path d='M32 38l13-7-13-6v13z' fill='#c1c7e0'/><path d='M32 38V25l-13 6 13 7z' fill='#8a92b2'/></g></svg>""",
            "arbitrum": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<circle cx='32' cy='32' r='32' fill='#213147'/><path d='M32 12l18 10v20L32 52 14 42V22l18-10z' fill='#fff'/><path d='M32 17l13 7v15l-13 8-13-8V24l13-7z' fill='#28a0f0'/><path d='M38 22h5v17h-5l-8-13-3 2v11h-5V25h5l8 13 3-2z' fill='#fff'/></svg>""",
            "robinhood": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<circle cx='32' cy='32' r='32' fill='#0b0f14'/><path d='M32 12c7 8 10 16 10 23 0 9-5 15-10 17-5-2-10-8-10-17 0-7 3-15 10-23zm-1 9c-3 4-5 8-5 12 0 5 2 9 6 11 4-2 6-6 6-11 0-4-2-8-5-12h-2z' fill='#00c805'/></svg>""",
            "multi_chain": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<circle cx='32' cy='32' r='32' fill='#0b0f14'/><g fill='none' stroke='#7c5bff' stroke-width='4' stroke-linecap='round'>
<circle cx='20' cy='32' r='8' fill='#16203a' stroke='#5b9dff'/><circle cx='44' cy='20' r='8' fill='#1a1326' stroke='#7c5bff'/><circle cx='44' cy='44' r='8' fill='#122018' stroke='#22c55e'/>
<path d='M27 29l10-6M27 35l10 6M44 28v8'/></g></svg>""",
        }
        return _svg_uri(svgs.get(code, svgs["multi_chain"]))

    def _chain_label(chain_code: str) -> str:
        labels = {
            "solana": "Solana",
            "bsc": "BSC",
            "base": "Base",
            "ethereum": "Ethereum",
            "arbitrum": "Arbitrum",
            "robinhood": "Robinhood",
            "multi_chain": "Multi Chain",
        }
        return labels.get(_norm_chain(chain_code), str(chain_code or "").strip() or chain.upper())

    rows: list[dict[str, Any]] = []
    for i, t in enumerate(tokens):
        if not isinstance(t, dict):
            continue
        addr = t.get("address") or t.get("tokenAddress")
        if not addr:
            continue
        row_chain = _norm_chain(
            t.get("chain")
            or t.get("chainName")
            or t.get("chain_name")
            or t.get("network")
            or t.get("networkName")
            or chain
        )
        rows.append({
            "rank": _jml._to_float(t.get("rank")) or (offset + i + 1),
            "address": addr,
            "chain": row_chain,
            "chain_label": _chain_label(row_chain),
            "chain_logo_uri": _chain_logo_uri(row_chain),
            "symbol": (t.get("symbol") or "").strip(),
            "name": (t.get("name") or "").strip(),
            "logo_uri": t.get("logoURI") or t.get("logo_uri") or t.get("logo"),
            "platform": (t.get("platform") or t.get("launchpad") or t.get("source") or "").strip(),
            "source": (t.get("source") or t.get("platform") or t.get("launchpad") or "").strip(),
            "price": _jml._to_float(t.get("price")),
            "fdv": _jml._to_float(t.get("fdv")),
            "marketcap": _jml._to_float(t.get("marketcap") or t.get("marketCap")),
            "liquidity": _jml._to_float(t.get("liquidity")),
            "volume_interval": _jml._to_float(t.get(f"volume{interval}USD") or t.get(f"v{interval}USD")),
            "price_change_interval_pct": _jml._to_float(t.get(f"price{interval}ChangePercent")),
        })

    platform_note = ""
    if platform:
        kept = [r for r in rows
                if platform in {str(r.get("platform") or "").lower(), str(r.get("source") or "").lower()}]
        if len(kept) != len(rows):
            rows = kept
        else:
            platform_note = "platform field not returned by this endpoint — filter not applied"

    model_label = "Birdeye trending"
    sort_note = f"Birdeye sort: {sort_by} {sort_type} @ {interval} · mode {mode}"

    # ── plain ──
    plain_lines = [
        f"Skill #1 · Trending List — {chain.upper()}",
        f"{model_label} · {len(rows)} token(s) · {sort_note}",
    ]
    if platform_note:
        plain_lines.append(f"Note: {platform_note}")
    header = (f"{'#':>3} {'Symbol':<12} {'MC':>11} {'Price':>11} "
              f"{f'Vol({interval})':>12} {'Liq':>12} {f'{interval} %':>9}")
    plain_lines.append(header)
    plain_lines.append("-" * len(header))
    for i, r in enumerate(rows, 1):
        line = (f"{i:>3} {(r.get('symbol') or '?')[:12]:<12} "
                f"{_fmt_usd(r.get('marketcap')):>11} {_fmt_usd(r.get('price')):>11} "
                f"{_fmt_usd(r.get('volume_interval')):>12} "
                f"{_fmt_usd(r.get('liquidity')):>12} "
                f"{_fmt_pct(r.get('price_change_interval_pct')):>9}")
        plain_lines.append(line)
    plain_lines.append("")
    plain_lines.append(f"⚡CU: {cu} ({', '.join(breakdown_cu)})")
    out_plain = "\n".join(plain_lines)

    # ── telegram ──
    tg_lines = [f"🔥 *Trending List* · {chain.upper()}", f"_{model_label}_"]
    for i, r in enumerate(rows, 1):
        tg_lines.append(
            f"{i}. *{r.get('symbol') or '?'}* {_fmt_pct(r.get('price_change_interval_pct'))} · "
            f"vol {_fmt_usd(r.get('volume_interval'))} · liq {_fmt_usd(r.get('liquidity'))}"
        )
    tg_lines.append(f"⚡CU {cu}")
    out_telegram = "\n".join(tg_lines)

    # ── rendered HTML (compact table box) ──
    def _tl_pct_color(v: float | None) -> str:
        if v is None:
            return "#8a93a6"
        return "#2ecc71" if v >= 0 else "#ef4444"

    body = ""
    for i, r in enumerate(rows, 1):
        token_logo = (f'<img src="{html.escape(str(r.get("logo_uri") or ""), quote=True)}" '
                      f'style="width:28px;height:28px;border-radius:999px;object-fit:cover;background:#0f1115" alt=""/>'
                      if r.get("logo_uri") else
                      '<div style="width:28px;height:28px;border-radius:999px;background:#111827;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:11px;font-weight:700">?</div>')
        chain_logo = (f'<img src="{html.escape(str(r.get("chain_logo_uri") or ""), quote=True)}" '
                      f'style="position:absolute;right:-2px;bottom:-2px;width:13px;height:13px;border-radius:999px;'
                      f'background:#0b0f14;border:1px solid rgba(255,255,255,.18);box-shadow:0 0 0 1px rgba(11,15,20,.9)" '
                      f'alt="{html.escape(str(r.get("chain_label") or r.get("chain") or ""))}" '
                      f'title="{html.escape(str(r.get("chain_label") or r.get("chain") or ""))}"/>'
                      if r.get("chain_logo_uri") else "")
        subline_parts = []
        if r.get("name"):
            subline_parts.append(html.escape((r.get("name") or "")[:28]))
        if r.get("chain"):
            subline_parts.append(html.escape(str(r.get("chain") or "").upper()))
        if r.get("platform"):
            subline_parts.append(html.escape(r.get("platform") or ""))
        subline = " · ".join(subline_parts)
        addr = str(r.get("address") or "")
        subline += (" · " if subline else "") + _copy_addr_btn(addr, "#6b7280", "11px")
        body += (
            f'<tr style="border-top:1px solid #1b2130">'
            f'<td style="padding:10px 10px;color:#8a93a6">{i}</td>'
            f'<td style="padding:10px 10px"><div style="display:flex;gap:10px;align-items:center">'
            f'<div style="position:relative;width:28px;height:28px;flex:0 0 auto">'
            f'{_be_token_link(r.get("chain") or chain, addr, token_logo)}{chain_logo}</div>'
            f'<div><div style="font-weight:800;color:#eef2ff">{html.escape(r.get("symbol") or "?")}</div>'
            f'<div style="font-size:11px;color:#6b7280">{subline}</div></div></div></td>'
            f'<td style="padding:10px 10px;text-align:right;color:#a78bfa">{_fmt_usd(r.get("marketcap"))}</td>'
            f'<td style="padding:10px 10px;text-align:right">{_fmt_usd(r.get("price"))}</td>'
            f'<td style="padding:10px 10px;text-align:right">{_fmt_usd(r.get("volume_interval"))}</td>'
            f'<td style="padding:10px 10px;text-align:right">{_fmt_usd(r.get("liquidity"))}</td>'
            f'<td style="padding:10px 10px;text-align:right;color:{_tl_pct_color(r.get("price_change_interval_pct"))}">{_fmt_pct(r.get("price_change_interval_pct"))}</td>'
            f'</tr>'
        )
    platform_html = (f'<div style="font-size:11px;color:#facc15;margin-bottom:6px">{html.escape(platform_note)}</div>'
                     if platform_note else "")
    html_out = (
        '<div style="max-width:1600px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif">'
        '<div style="font-size:24px;font-weight:900;color:#eef2ff;margin-bottom:4px">🔥 Trending Token List</div>'
        f'<div style="font-size:12px;color:#8a93a6;margin-bottom:14px">{chain.upper()} · {len(rows)} token(s) · '
        f'{html.escape(model_label)} · {html.escape(sort_note)} · JSON = raw upstream response</div>'
        f'{platform_html}'
        '<div style="border:1px solid #262b36;border-radius:14px;overflow:hidden;background:#0b0f14">'
        '<div style="overflow:auto">'
        '<table style="width:100%;border-collapse:collapse;font-size:12px;color:#cbd5e1;background:#0b0f14;min-width:900px">'
        '<thead><tr style="background:#0f1115;font-size:10px;text-transform:uppercase;color:#8a93a6">'
        f'<th style="padding:7px 8px;text-align:left">#</th><th style="padding:7px 8px;text-align:left">Token</th>'
        f'<th style="padding:7px 8px;text-align:right">MCap</th>'
        f'<th style="padding:7px 8px;text-align:right">Price</th>'
        f'<th style="padding:7px 8px;text-align:right">{html.escape(f"Vol({interval})")}</th>'
        f'<th style="padding:7px 8px;text-align:right">Liq</th>'
        f'<th style="padding:7px 8px;text-align:right">{html.escape(interval)} %</th></tr></thead>'
        f'<tbody>{body}</tbody></table></div></div>'
        f'<div style="font-size:10px;color:#475569;margin-top:10px">⚡CU cost: {cu} '
        f'({html.escape(", ".join(breakdown_cu))})</div>'
        '</div>'
    )

    envelope = {
        "schemaVersion": 1, "kind": "trending-list-v1", "run_id": run_id,
        "cu_used": cu, "cu_breakdown": breakdown_cu,
        "params": {
            "chain": chain, "mode": mode, "sort_by": sort_by, "sort_type": sort_type,
            "interval": interval, "offset": offset, "limit": limit,
            "platform": platform, "argv": sys.argv[1:],
        },
        "source": "birdeye", "source_label": model_label,
        "sort_note": sort_note, "platform_note": platform_note or None,
        "n_tokens": len(rows), "rows": rows, "raw_response": raw, "html": html_out,
    }

    raw_json_text = json.dumps(raw, ensure_ascii=False, indent=2 if fmt == "json" else None)

    cdir = _cache_dir(getattr(args, "cache_dir", None))
    file_payload = {
        "runId": run_id, "kind": "trending-list-v1", "cached": False,
        "cu_used_total": cu, "cu_breakdown": breakdown_cu,
        "params": envelope["params"], "snapshot_time": int(time.time()),
        "rendered_plain": out_plain,
        "rendered_telegram": out_telegram,
        "rendered_json": json.dumps(raw, ensure_ascii=False, indent=2),
        "rendered_ui": json.dumps(envelope, ensure_ascii=False),
        "rendered_raw-json": json.dumps(raw, ensure_ascii=False),
        "rendered_rendered": json.dumps(envelope, ensure_ascii=False),
        "out": json.dumps(envelope, ensure_ascii=False),
    }
    _write_cache(cdir, run_id, file_payload)
    sys.stdout.write(f"#RUN_ID {run_id}\ttrending-list\tcu={cu}\n")

    if fmt == "plain":
        print(out_plain)
        return 0
    if fmt == "telegram":
        print(out_telegram)
        return 0
    print(raw_json_text if fmt == "json" else json.dumps(envelope, ensure_ascii=False))
    return 0


# ── Skill #2 · Price Surge Screen ────────────────────────────────────────────
_PS_INTERVALS = ["1m", "5m", "30m", "1h", "2h", "4h", "8h", "24h", "7d", "30d"]
_PS_CU = {
    "list_v3": 50,
    "security": 30,
    "top_traders": 30,
    "holder_profile": 30,
}
_PS_RISK_LABELS = {
    "stale_market_cap": "stale market cap",
    "no_liquidity": "no liquidity",
    "zero_holders_with_trades": "0 holders w/ trades",
    "thin_liquidity": "thin liquidity",
    "honeypot_proxy": "no sell side",
    "wash_trade_proxy": "wash-trade churn",
    "honeypot": "honeypot",
    "honeypot_tax": "honeypot tax",
    "high_transfer_tax": "high transfer tax",
    "rug_pull_risk": "rug-pull risk",
    "dev_hold_over_limit": "dev hold > limit",
    "high_dev_hold": "high dev hold",
    "top10_over_limit": "top10 > limit",
    "top10_concentration": "top10 concentration",
    "low_kol_buyers": "low KOL buyers",
}


def _ps_sort_field(sort_by: str, interval: str) -> str:
    return {
        "price_change": f"price_change_{interval}_percent",
        "volume": f"volume_{interval}_usd",
        "trade_count": f"trade_{interval}_count",
        "market_cap": "market_cap",
        "liquidity": "liquidity",
        "holder": "holder",
    }.get(sort_by, f"price_change_{interval}_percent")


def _ps_fee_pct(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ("percent", "pct", "value", "fee", "rate", "amount"):
            v = value.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except Exception:
            return None
    return None


def _ps_num(obj: dict, *keys: str) -> float | None:
    for k in keys:
        v = obj.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.strip())
            except Exception:
                continue
    return None


def _ps_map_row(item: dict, interval: str, chain: str) -> dict:
    """Normalise one `/defi/v3/token/list` row into the price-surge row shape."""
    price = _ps_num(item, "price")
    mcap = _ps_num(item, "market_cap")
    fdv = _ps_num(item, "fdv")
    liq = _ps_num(item, "liquidity")
    holder = _ps_num(item, "holder")
    tc_w = _ps_num(item, f"trade_{interval}_count")
    tc_24h = _ps_num(item, "trade_24h_count")
    uw_24h = _ps_num(item, "unique_wallet_24h")
    buy_24h = _ps_num(item, "buy_24h")
    sell_24h = _ps_num(item, "sell_24h")
    ext = item.get("extensions") if isinstance(item.get("extensions"), dict) else {}
    return {
        "address": item.get("address"),
        "symbol": item.get("symbol") or item.get("symbols") or "",
        "name": item.get("name") or "",
        "logo_uri": item.get("logo_uri"),
        "chain": chain,
        "decimals": item.get("decimals"),
        "platform": ext.get("platform") or item.get("platform_name") or None,
        "price": price,
        "market_cap": mcap,
        "fdv": fdv,
        "liquidity": liq,
        "holder": int(holder) if holder is not None else None,
        "volume_interval": _ps_num(item, f"volume_{interval}_usd"),
        "volume_24h": _ps_num(item, "volume_24h_usd"),
        "price_change_interval_pct": _ps_num(item, f"price_change_{interval}_percent"),
        "price_change_24h_pct": _ps_num(item, "price_change_24h_percent"),
        "trade_interval_count": int(tc_w) if tc_w is not None else None,
        "trade_24h_count": int(tc_24h) if tc_24h is not None else None,
        "unique_wallet_24h": int(uw_24h) if uw_24h is not None else None,
        "buy_24h": int(buy_24h) if buy_24h is not None else None,
        "sell_24h": int(sell_24h) if sell_24h is not None else None,
        "volume_buy_24h_usd": _ps_num(item, "volume_buy_24h_usd"),
        "volume_sell_24h_usd": _ps_num(item, "volume_sell_24h_usd"),
        "liq_mcap_ratio": (liq / mcap) if (liq is not None and mcap and mcap > 0) else None,
        "trades_per_wallet_24h": (tc_24h / uw_24h) if (tc_24h is not None and uw_24h and uw_24h > 0) else None,
        "recent_listing_time": item.get("recent_listing_time"),
        "global_fees_paid": _ps_num(item, "global_fees_paid"),
        "socials": {k: ext.get(k) for k in ("website", "twitter", "telegram") if ext.get(k)} or None,
        # advanced-only, filled by hydration
        "dev_hold_pct": None,
        "top10_holder_pct": None,
        "kol_buyer_count": None,
        "profitable_wallet_ratio": None,
        "top_traders_n": None,
        "security": None,
        "holder_tags": None,
        "hydrated": False,
        "excluded": False,
        "exclude_reason": None,
        "risk_flags": [],
    }


def _ps_apply_list_filters(row: dict, cfg: dict) -> str | None:
    """Structural + proxy checks available from the v3 token list alone."""
    flags: list[str] = row["risk_flags"]
    mcap = row.get("market_cap") or 0.0
    fdv = row.get("fdv") or 0.0
    if fdv and mcap and mcap > fdv * 1.01:
        flags.append("stale_market_cap")
        return "stale_market_cap"
    liq = row.get("liquidity")
    if liq is not None and liq <= 0:
        flags.append("no_liquidity")
        return "no_liquidity"
    if row.get("holder") == 0 and (row.get("trade_interval_count") or 0) > 0:
        flags.append("zero_holders_with_trades")
        return "zero_holders_with_trades"
    ratio = row.get("liq_mcap_ratio")
    thr = cfg.get("max_liq_mcap_ratio")
    if ratio is not None and thr is not None and mcap > 0 and ratio < thr:
        flags.append("thin_liquidity")
        return "thin_liquidity"
    buy_24h, sell_24h = row.get("buy_24h"), row.get("sell_24h")
    if buy_24h is not None and sell_24h is not None and buy_24h >= 20 and sell_24h == 0:
        flags.append("honeypot_proxy")
        return "honeypot_proxy"
    tpw = row.get("trades_per_wallet_24h")
    tmax = cfg.get("max_trades_per_wallet")
    if tpw is not None and tmax is not None and tpw > tmax:
        flags.append("wash_trade_proxy")
        return "wash_trade_proxy"
    return None


def _ps_apply_advanced_filters(row: dict, cfg: dict) -> str | None:
    """Holder-health checks that require the advanced hydration pass."""
    flags: list[str] = row["risk_flags"]
    dev = row.get("dev_hold_pct")
    if dev is not None:
        limit = cfg.get("max_dev_hold_pct")
        if limit is not None and dev > limit:
            flags.append("dev_hold_over_limit")
            return "dev_hold_over_limit"
        if dev >= 10:
            flags.append("high_dev_hold")
    t10 = row.get("top10_holder_pct")
    if t10 is not None:
        limit = cfg.get("max_top10_pct")
        if limit is not None and t10 > limit:
            flags.append("top10_over_limit")
            return "top10_over_limit"
        if t10 >= 50:
            flags.append("top10_concentration")
    min_kol = cfg.get("min_kol_buyers")
    kol = row.get("kol_buyer_count")
    if min_kol is not None and kol is not None and kol < min_kol:
        flags.append("low_kol_buyers")
        return "low_kol_buyers"
    return None


def _ps_hydrate_security(session, key: str, chain: str, addr: str, row: dict) -> bool:
    """Token security for one token (all chains).

    Also the source of top-10 holder concentration, which Birdeye exposes on
    every chain — so no separate holder-distribution call is needed.
    """
    try:
        raw, _ = _be(session, key, chain, "/defi/token_security", {"address": addr})
    except RuntimeError:
        return False
    d = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(d, dict) or not d:
        return False
    cp = _ps_num(d, "creatorPercentage", "creatorPercent")
    t10 = _ps_num(d, "top10HolderPercent", "top10UserPercent")
    owner = d.get("ownerAddress")
    freeze = d.get("freezeAuthority")
    mutable = d.get("mutableMetadata")
    lp_locked = d.get("lpLocked")
    honeypot = d.get("isHoneypot")
    metadata_immutable = (mutable is False) if isinstance(mutable, bool) else None
    # Solana (Token-2022) reports the transfer fee under `transferFeeData`.
    fee = _ps_fee_pct(d.get("transferFee"))
    if fee is None:
        fee = _ps_fee_pct(d.get("transferFeeData"))
    row["security"] = {
        "honeypot": bool(honeypot) if isinstance(honeypot, bool) else None,
        "mint_renounced": (owner is None) if "ownerAddress" in d else None,
        "freeze_renounced": (freeze is None) if "freezeAuthority" in d else None,
        "metadata_immutable": metadata_immutable,
        "open_source_status": ("immutable" if metadata_immutable else "mutable")
        if metadata_immutable is not None else ("immutable" if mutable is None else None),
        "lp_locked": bool(lp_locked) if isinstance(lp_locked, bool) else None,
        "transfer_fee_pct": fee,
    }
    if t10 is not None:
        row["top10_holder_pct"] = round(t10 * 100 if t10 <= 1 else t10, 4)
    if cp is not None and row.get("dev_hold_pct") is None:
        row["dev_hold_pct"] = round(cp * 100 if cp <= 1 else cp, 4)
    return True


def _ps_hydrate_top_traders(session, key: str, chain: str, addr: str, row: dict) -> bool:
    """Top traders for one token.

    Live shape: rows at ``data.items[]``; wallet address under ``owner`` (not
    ``wallet``); ``sort_by`` must be snake_case (``volume_usd``).
    """
    try:
        raw, _ = _be(session, key, chain, "/defi/v2/tokens/top_traders",
                     {"address": addr, "time_frame": "24h", "sort_by": "volume_usd",
                      "offset": 0, "limit": 10})
    except RuntimeError:
        return False
    d = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(d, dict):
        rows = d.get("items") or d.get("rows") or []
    elif isinstance(d, list):
        rows = d
    else:
        return False
    if not isinstance(rows, list):
        return False
    wallets: list[str] = []
    kol = 0
    profitable = 0
    for t in rows:
        if not isinstance(t, dict):
            continue
        w = t.get("owner") or t.get("wallet")
        if w:
            wallets.append(str(w))
        tags = t.get("tags")
        if isinstance(tags, list) and tags:
            low = {str(x).lower() for x in tags}
            if "kol" in low or "kol_wallet" in low:
                kol += 1
        pnl = t.get("realizedPnl", t.get("totalPnl"))
        win, lose = t.get("winCount"), t.get("loseCount")
        if isinstance(pnl, (int, float)) and not isinstance(pnl, bool) and pnl > 0:
            profitable += 1
        elif isinstance(win, (int, float)) and isinstance(lose, (int, float)) and win >= lose:
            profitable += 1
    row["top_traders_n"] = len(rows)
    row["top_trader_wallets"] = wallets
    # Birdeye's tag vocabulary has no KOL tag — keep the counter best-effort and
    # surface "n/a" (None) when nothing matched rather than a misleading 0.
    row["kol_buyer_count"] = kol if kol else None
    row["profitable_wallet_ratio"] = round(profitable / len(rows) * 100, 2) if rows else None
    return True


def _ps_hydrate_holder_profile(session, key: str, addr: str, row: dict) -> bool:
    """Holder profile tags (Solana only).

    Live shape: ``data.tags`` is a LIST of ``{tag, holder_count, percent_of_supply,
    avg_buy_price, pnl, ...}`` — not a dict keyed by tag name.
    """
    try:
        raw, _ = _be(session, key, "solana", "/token/v1/holder-profile",
                     {"token_address": addr, "include_zero_balance": "false"})
    except RuntimeError:
        return False
    d = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(d, dict):
        return False
    tags = d.get("tags")
    out: dict[str, dict] = {}
    if isinstance(tags, list):
        for t in tags:
            if not isinstance(t, dict):
                continue
            name = str(t.get("tag") or "").lower()
            if not name:
                continue
            out[name] = {
                "percent_of_supply": _ps_num(t, "percent_of_supply"),
                "holder_count": t.get("holder_count"),
                "avg_buy_price": _ps_num(t, "avg_buy_price"),
                "pnl_usd": _ps_num(t, "pnl", "pnl_usd"),
            }
    elif isinstance(tags, dict):
        for name, t in tags.items():
            if isinstance(t, dict):
                out[str(name).lower()] = {
                    "percent_of_supply": _ps_num(t, "percent_of_supply"),
                    "holder_count": t.get("holder_count"),
                    "avg_buy_price": _ps_num(t, "avg_buy_price"),
                    "pnl_usd": _ps_num(t, "pnl", "pnl_usd"),
                }
    if not out:
        return False
    row["holder_tags"] = out
    if row.get("dev_hold_pct") is None:
        dev_pct = (out.get("dev") or {}).get("percent_of_supply")
        if isinstance(dev_pct, (int, float)):
            row["dev_hold_pct"] = round(float(dev_pct), 4)
    return True


def _ps_fmt_int(v) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except Exception:
        return str(v)
    if abs(n) >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if abs(n) >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{int(n)}" if n == int(n) else f"{n:.2f}"


def _ps_ratio(v) -> str:
    return f"{float(v):.4f}" if isinstance(v, (int, float)) else "—"


def _ps_kv(label: str, value: str, tone: str = "neutral") -> str:
    fg = {"good": "#86efac", "warn": "#fde68a", "bad": "#fca5a5"}.get(tone, "#e2e8f0")
    return (f'<div style="background:#0b0f14;border:1px solid #1b222d;border-radius:9px;padding:5px 8px">'
            f'<div style="font-size:9.5px;color:#7b8794;text-transform:uppercase;letter-spacing:.05em">'
            f'{html.escape(label)}</div>'
            f'<div style="font-size:13px;font-weight:700;color:{fg}">{html.escape(value)}</div></div>')


def cmd_price_surge(args):
    """Skill #2 — Price Surge Screen.

    Two cost tiers over the same surge feed:

      * ``min``      — a single ``/defi/v3/token/list`` call (50 CU). The market-cap
                       range and the surge / liquidity / volume floors are applied
                       server-side, then structural rug + wash proxies are applied
                       locally.
      * ``advanced`` — the same list plus per-token hydration: ``/defi/token_security``,
                       ``/defi/v2/tokens/top_traders``, ``/smart-money/v1/token/list``
                       and (Solana only) ``/holder/v1/distribution`` +
                       ``/token/v1/holder-profile``.

    High-risk rows (rug-pull proxies, wash-trade churn, honeypots) are excluded
    automatically; pass ``--no-auto-filter`` to keep them.
    """
    chain = str(getattr(args, "chain", "solana") or "solana")
    chain_norm = CHAINS.get(chain, chain)
    is_solana = chain_norm == "solana"
    interval = str(getattr(args, "interval", "1h") or "1h")
    if interval not in _PS_INTERVALS:
        interval = "1h"
    mode = str(getattr(args, "mode", "standard") or "standard").lower()
    if mode not in ("standard", "advanced"):
        mode = "standard"
    sort_by = str(getattr(args, "sort_by", "price_change") or "price_change")
    sort_type = str(getattr(args, "sort_type", "desc") or "desc")
    limit = max(1, min(int(getattr(args, "limit", 10) or 10), 100))
    offset = max(0, int(getattr(args, "offset", 0) or 0))
    top = max(0, int(getattr(args, "top", 10) or 0))
    auto_filter = not bool(getattr(args, "no_auto_filter", False))
    holder_health = not bool(getattr(args, "no_holder_health", False))
    with_security = bool(getattr(args, "with_security", False)) and mode == "advanced"
    fmt = _canonical_format(getattr(args, "format", None))
    key = _load_key()
    if not key:
        sys.stderr.write("[price-surge] missing BIRDEYE_API_KEY.\n")
        return 2

    cfg = {
        "max_liq_mcap_ratio": getattr(args, "max_liq_mcap_ratio", 0.005),
        "max_trades_per_wallet": getattr(args, "max_trades_per_wallet", 150.0),
        "max_dev_hold_pct": getattr(args, "max_dev_hold_pct", None),
        "max_top10_pct": getattr(args, "max_top10_pct", None),
        "min_kol_buyers": getattr(args, "min_kol_buyers", None),
    }
    min_mc = getattr(args, "min_market_cap", None)
    max_mc = getattr(args, "max_market_cap", None)

    cu = 0
    breakdown_cu: list[str] = []
    run_id = f"psurge_{chain_norm}_{interval}_{int(time.time())}"

    params: dict[str, Any] = {
        "sort_by": _ps_sort_field(sort_by, interval),
        "sort_type": sort_type,
        "offset": offset,
        "limit": limit,
        "ui_amount_mode": "scaled",
    }
    for pkey, pval in (
        (f"min_price_change_{interval}_percent", getattr(args, "min_price_change", 50.0)),
        ("min_market_cap", min_mc),
        ("max_market_cap", max_mc),
        ("min_liquidity", getattr(args, "min_liquidity", 10000.0)),
        ("max_liquidity", getattr(args, "max_liquidity", None)),
        (f"min_volume_{interval}_usd", getattr(args, "min_volume", 5000.0)),
        (f"min_trade_{interval}_count", getattr(args, "min_trade_count", None)),
        ("min_holder", getattr(args, "min_holders", None)),
    ):
        if pval is not None:
            params[pkey] = pval
    platform = (getattr(args, "platform", None) or "").strip() or None
    if platform:
        params["platform_name"] = platform

    n_hydrated = 0
    hydration_note = None
    try:
        with requests.Session() as session:
            raw, _ms = _be(session, key, chain_norm, "/defi/v3/token/list", params)
            cu += _PS_CU["list_v3"]
            breakdown_cu.append(f"token_list_v3={_PS_CU['list_v3']}")
            data = raw.get("data") if isinstance(raw, dict) else None
            items = (data.get("items") if isinstance(data, dict) else None) or []

            rows = [_ps_map_row(it, interval, chain_norm) for it in items if isinstance(it, dict)]

            # Pass 1 — everything the token list alone can already tell us.
            for row in rows:
                if auto_filter:
                    reason = _ps_apply_list_filters(row, cfg)
                    if reason:
                        row["excluded"] = True
                        row["exclude_reason"] = reason

            # Pass 2 — hydrate the top kept rows (CU bounded by --top).
            if mode == "advanced" and top > 0:
                counters = {"security": 0, "top_traders": 0, "holder_profile": 0}
                targets = [r for r in rows if not r["excluded"]][:top]
                if not is_solana:
                    hydration_note = "holder profile is Solana-only"
                for row in targets:
                    addr = str(row.get("address") or "")
                    if not addr:
                        continue
                    if with_security and _ps_hydrate_security(session, key, chain_norm, addr, row):
                        counters["security"] += 1
                    if _ps_hydrate_top_traders(session, key, chain_norm, addr, row):
                        counters["top_traders"] += 1
                    if is_solana and holder_health:
                        if _ps_hydrate_holder_profile(session, key, addr, row):
                            counters["holder_profile"] += 1
                    row["hydrated"] = True
                    n_hydrated += 1
                    row.pop("top_trader_wallets", None)
                    if auto_filter:
                        reason = _ps_apply_advanced_filters(row, cfg)
                        if reason:
                            row["excluded"] = True
                            row["exclude_reason"] = reason
                for label in ("security", "top_traders", "holder_profile"):
                    n = counters[label]
                    if n:
                        cu += _PS_CU[label] * n
                        breakdown_cu.append(f"{label}={_PS_CU[label]}x{n}")
            elif mode == "advanced" and top == 0:
                hydration_note = "--top 0: advanced mode ran without hydrating any row"
    except RuntimeError as e:
        sys.stderr.write(f"[price-surge] {e}\n")
        return 1

    kept = [r for r in rows if not r["excluded"]]
    dropped = [r for r in rows if r["excluded"]]
    for i, r in enumerate(kept, 1):
        r["rank"] = i

    chain_label = {
        "solana": "Solana", "bsc": "BSC", "base": "Base",
        "ethereum": "Ethereum", "arbitrum": "Arbitrum", "robinhood": "Robinhood",
    }.get(chain_norm, chain_norm)
    mcap_range = " · ".join(
        [f"≥{_fmt_usd(min_mc)}" if min_mc is not None else "", f"≤{_fmt_usd(max_mc)}" if max_mc is not None else ""]
    ).strip(" ·") or "no bound"
    mode_label = "advanced+security" if with_security else mode
    sort_note = f"{params['sort_by']} {sort_type}"

    # ── plain ────────────────────────────────────────────────────────────────
    header_cells = [("#", 3), ("SYMBOL", 12), ("PRICE", 12), (f"Δ{interval}%", 9),
                    ("MCAP", 10), ("LIQ", 10), (f"VOL({interval})", 12), ("TRADES", 9),
                    ("HLDRS", 8), ("KOL", 5), ("DEV%", 7), ("T10%", 7), ("FLAGS", 18)]
    lines = [
        f"💹 Price Surge Screen · {chain_label} · {interval} · mode={mode_label} · auto-filter="
        f"{'on' if auto_filter else 'off'}",
        f"   mcap range: {mcap_range} · liquidity ≥ {_fmt_usd(params.get('min_liquidity'))} · "
        f"vol({interval}) ≥ {_fmt_usd(params.get(f'min_volume_{interval}_usd'))} · "
        f"surge ≥ {params.get(f'min_price_change_{interval}_percent')}% · sort {sort_note}",
        "",
        " ".join(_pad_cell(c, w) for c, w in header_cells),
        "-" * (sum(w for _, w in header_cells) + len(header_cells) - 1),
    ]
    for r in kept:
        addr = str(r.get("address") or "")
        short = f"{addr[:4]}…{addr[-4:]}" if len(addr) > 8 else addr
        flags = ",".join(_PS_RISK_LABELS.get(f, f) for f in r["risk_flags"]) or "-"
        lines.append(" ".join([
            _pad_cell(str(r.get("rank") or ""), 3, "right"),
            _pad_cell(str(r.get("symbol") or short)[:12], 12),
            _pad_cell(_fmt_usd(r.get("price")), 12, "right"),
            _pad_cell(_fmt_pct(r.get("price_change_interval_pct")), 9, "right"),
            _pad_cell(_fmt_usd(r.get("market_cap")), 10, "right"),
            _pad_cell(_fmt_usd(r.get("liquidity")), 10, "right"),
            _pad_cell(_fmt_usd(r.get("volume_interval")), 12, "right"),
            _pad_cell(_ps_fmt_int(r.get("trade_interval_count")), 9, "right"),
            _pad_cell(_ps_fmt_int(r.get("holder")), 8, "right"),
            _pad_cell(_ps_fmt_int(r.get("kol_buyer_count")), 5, "right"),
            _pad_cell(f"{r['dev_hold_pct']:.1f}" if r.get("dev_hold_pct") is not None else "—", 7, "right"),
            _pad_cell(f"{r['top10_holder_pct']:.1f}" if r.get("top10_holder_pct") is not None else "—", 7, "right"),
            _pad_cell(flags[:18], 18),
        ]))
    if not kept:
        lines.append("(no token survived the screen — loosen --min-price-change / the mcap range)")
    if dropped:
        lines += ["", f"⛔ filtered out ({len(dropped)}):"]
        for r in dropped:
            lines.append(f"   - {str(r.get('symbol') or r.get('address'))[:14]:<14} "
                         f"{r['exclude_reason']:<24} {str(r.get('address'))[:6]}…")
    lines += ["", f"⚡CU cost: {cu} ({', '.join(breakdown_cu)}) · "
                  f"scanned {len(rows)} · kept {len(kept)} · filtered {len(dropped)} · hydrated {n_hydrated}"]
    if hydration_note:
        lines.append(f"   note: {hydration_note}")
    out_plain = "\n".join(lines)

    # ── telegram ─────────────────────────────────────────────────────────────
    tlines = [
        "💹 *Price Surge Screen*",
        f"`{chain_label}` · `{interval}` · mode `{mode_label}` · auto-filter `{'on' if auto_filter else 'off'}`",
        f"mcap range `{mcap_range}` · surge ≥ `{params.get(f'min_price_change_{interval}_percent')}%` · "
        f"liq ≥ `{_fmt_usd(params.get('min_liquidity'))}`",
        "",
    ]
    for r in kept:
        addr = str(r.get("address") or "")
        tlines.append(f"*#{r.get('rank')} {r.get('symbol') or addr[:6]}*  `{_fmt_pct(r.get('price_change_interval_pct'))}`")
        tlines.append(f"  price `{_fmt_usd(r.get('price'))}` · mc `{_fmt_usd(r.get('market_cap'))}` · "
                      f"liq `{_fmt_usd(r.get('liquidity'))}` · vol({interval}) `{_fmt_usd(r.get('volume_interval'))}`")
        if mode == "advanced":
            tlines.append(f"  dev `{_fmt_pct(r.get('dev_hold_pct'))}` · top10 `{_fmt_pct(r.get('top10_holder_pct'))}` · "
                          f"KOL `{_ps_fmt_int(r.get('kol_buyer_count'))}`")
        if r["risk_flags"]:
            tlines.append(f"  ⚠ {' · '.join(_PS_RISK_LABELS.get(f, f) for f in r['risk_flags'])}")
        tlines.append(f"  `{addr}`")
    if not kept:
        tlines.append("_no token survived the screen_")
    if dropped:
        tlines += ["", f"⛔ filtered out: {len(dropped)}"]
    tlines += ["", f"⚡CU {cu} · scanned {len(rows)} · kept {len(kept)}"]
    out_telegram = "\n".join(tlines)

    # ── ui (list rows) ───────────────────────────────────────────────────────
    _TONE_FG = {"good": "#86efac", "warn": "#fde68a", "bad": "#fca5a5"}
    _TEXT = "#cbd5e1"
    _MUTED = "#7b8794"
    _TD = "padding:7px 9px;border-top:1px solid #171e28;white-space:nowrap"

    def _num(value: str, tone: str | None = None, bold: bool = False) -> str:
        fg = _TONE_FG.get(tone or "", _TEXT)
        weight = "800" if bold else "600"
        return (f'<td style="{_TD};text-align:right;color:{fg};'
                f'font-weight:{weight}">{html.escape(value)}</td>')

    def _tag(label: str, value: str, tone: str = "neutral") -> str:
        fg = _TONE_FG.get(tone, _MUTED)
        return (f'<span style="white-space:nowrap;color:{_MUTED}">{html.escape(label)} '
                f'<b style="color:{fg}">{html.escape(value)}</b></span>')

    def _health_cell(r: dict) -> str:
        parts: list[str] = []
        prof = r.get("profitable_wallet_ratio")
        if prof is not None:
            parts.append(_tag("prof", _fmt_pct(prof), "good" if prof >= 50 else "warn"))
        tags = r.get("holder_tags") or {}
        for name in ("dev", "bundler", "sniper", "insider"):
            t = tags.get(name)
            if not t:
                continue
            pct = t.get("percent_of_supply")
            pct_txt = _fmt_pct(pct) if isinstance(pct, (int, float)) else "—"
            tone = "warn" if isinstance(pct, (int, float)) and pct > 20 else "neutral"
            parts.append(_tag(name, f"{_ps_fmt_int(t.get('holder_count'))}·{pct_txt}", tone))
        return " · ".join(parts) or "—"

    _BADGE_BG = {
        "good": ("rgba(34,197,94,.16)", "rgba(34,197,94,.38)", "#86efac"),
        "warn": ("rgba(250,204,21,.16)", "rgba(250,204,21,.38)", "#fde68a"),
        "bad": ("rgba(239,68,68,.16)", "rgba(239,68,68,.38)", "#fca5a5"),
        "neutral": ("#0f1115", "#202530", "#7b8794"),
    }

    def _badge(icon: str, tone: str, tip: str) -> str:
        bg, bd, fg = _BADGE_BG.get(tone, _BADGE_BG["neutral"])
        return (f'<span title="{html.escape(tip, quote=True)}" '
                f'style="display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;'
                f'border-radius:6px;background:{bg};border:1px solid {bd};color:{fg};font-size:10.5px;'
                f'line-height:1;cursor:default">{icon}</span>')

    def _security_cell(r: dict) -> str:
        sec = r.get("security")
        if not isinstance(sec, dict) or not sec:
            return f'<span style="color:{_MUTED}">—</span>'
        hp = sec.get("honeypot")
        badges = [_badge("🍯", "neutral" if hp is None else ("bad" if hp else "good"),
                         f"Honeypot: {'n/a' if hp is None else ('yes' if hp else 'no')}")]
        mint = sec.get("mint_renounced")
        badges.append(_badge("🔑", "neutral" if mint is None else ("good" if mint else "warn"),
                             f"Mint authority: {'n/a' if mint is None else ('renounced' if mint else 'live')}"))
        frz = sec.get("freeze_renounced")
        badges.append(_badge("❄", "neutral" if frz is None else ("good" if frz else "warn"),
                             f"Freeze authority: {'n/a' if frz is None else ('renounced' if frz else 'live')}"))
        oss = sec.get("open_source_status")
        badges.append(_badge("📝", "neutral" if oss is None else ("good" if oss == "immutable" else "warn"),
                             f"Metadata: {oss or 'n/a'}"))
        lp = sec.get("lp_locked")
        badges.append(_badge("💧", "neutral" if lp is None else ("good" if lp else "warn"),
                             f"LP: {'n/a' if lp is None else ('locked' if lp else 'unlocked')}"))
        fee = sec.get("transfer_fee_pct")
        badges.append(_badge("💸", "neutral" if fee is None else ("bad" if fee >= 10 else "good"),
                             f"Transfer tax: {_fmt_pct(fee) if fee is not None else 'n/a'}"))
        t10 = r.get("top10_holder_pct")
        badges.append(_badge("👥", "neutral" if t10 is None else ("warn" if t10 >= 50 else "good"),
                             f"Top-10 holders: {_fmt_pct(t10) if t10 is not None else 'n/a'}"))
        return f'<div style="display:flex;gap:3px;align-items:center">{"".join(badges)}</div>'

    def _token_cell(r: dict) -> str:
        addr = str(r.get("address") or "")
        logo = r.get("logo_uri") or ""
        if logo:
            icon_img = (f'<img src="{html.escape(logo)}" alt="" style="width:22px;height:22px;border-radius:50%;'
                        'background:#161c26;object-fit:cover;display:block" '
                        'onerror="this.style.visibility=\'hidden\'"/>')
        else:
            icon_img = f'<span style="color:{_MUTED};font-size:12px">↗</span>'
        icon = (f'<span style="flex:0 0 auto;line-height:0">'
                f'{_be_token_link(chain_norm, addr, icon_img)}</span>')
        return (
            f'<td style="{_TD}"><div style="display:flex;align-items:center;gap:8px;min-width:0">'
            + icon
            + '<div style="min-width:0"><div style="font-weight:700;color:#f1f5f9;font-size:12.5px">'
            + html.escape(str(r.get("symbol") or "?"))
            + '<span style="font-weight:500;font-size:10.5px;color:' + _MUTED + '"> · </span>'
            + _copy_addr_btn(addr, _MUTED)
            + '</div><div style="color:' + _MUTED + ';font-size:10px;max-width:210px;overflow:hidden;'
            'text-overflow:ellipsis">' + html.escape(str(r.get("name") or ""))
            + (' · ' + html.escape(str(r.get("platform"))) if r.get("platform") else "")
            + '</div></div></div></td>'
        )

    def _row(r: dict) -> str:
        delta = r.get("price_change_interval_pct")
        avg_vol = None
        if r.get("volume_interval") and r.get("trade_interval_count"):
            avg_vol = r["volume_interval"] / r["trade_interval_count"]
        cells = [
            f'<td style="{_TD};color:{_MUTED};font-weight:700;text-align:right">'
            f'{html.escape(str(r.get("rank") or ""))}</td>',
            _token_cell(r),
            _num(_fmt_pct(delta), "good" if (delta or 0) >= 0 else "bad", bold=True),
            _num(_fmt_usd(r.get("price"))),
            _num(_fmt_usd(r.get("market_cap"))),
            _num(_fmt_usd(r.get("liquidity"))),
            _num(_fmt_usd(r.get("volume_interval"))),
            _num(_ps_fmt_int(r.get("trade_interval_count"))),
            _num(_ps_fmt_int(r.get("holder"))),
        ]
        if mode == "advanced":
            dev = r.get("dev_hold_pct")
            tw = r.get("trades_per_wallet_24h")
            cells += [
                _num(_fmt_pct(dev), "neutral" if dev is None else ("bad" if dev >= 10 else "good")),
                _num(_ps_fmt_int(r.get("kol_buyer_count"))),
                _num(_fmt_usd(avg_vol) if avg_vol is not None else "—"),
                _num(f"{tw:.1f}" if tw is not None else "—",
                     "warn" if tw is not None and tw > (cfg.get("max_trades_per_wallet") or 1e9) * 0.6 else None),
                _num(_ps_ratio(r.get("liq_mcap_ratio"))),
                f'<td style="{_TD}">{_health_cell(r)}</td>',
            ]
        if with_security:
            cells.append(f'<td style="{_TD}">{_security_cell(r)}</td>')
        flags = " · ".join(_tag("", _PS_RISK_LABELS.get(f, f), "warn") for f in r["risk_flags"])
        cells.append(f'<td style="{_TD}">{flags or _tag("", "clean", "good")}</td>')
        return "<tr>" + "".join(cells) + "</tr>"

    top_surge = max((r.get("price_change_interval_pct") or 0) for r in kept) if kept else None
    stat = lambda label, value, tone="neutral": _ps_kv(label, value, tone)
    stats_html = "".join([
        stat("Scanned", str(len(rows))),
        stat("Kept", str(len(kept)), "good" if kept else "bad"),
        stat("Filtered out", str(len(dropped)), "warn" if dropped else "neutral"),
        stat("Hydrated", str(n_hydrated)),
        stat("Interval", interval),
        stat("Min surge", f"{params.get(f'min_price_change_{interval}_percent')}%"),
        stat("MCap range", mcap_range),
        stat("Top surge", _fmt_pct(top_surge) if top_surge is not None else "—", "good"),
    ])
    dropped_html = ""
    if dropped:
        d_rows = "".join(
            '<tr>'
            f'<td style="padding:5px 8px;color:#cbd5e1">{html.escape(str(r.get("symbol") or "?"))}</td>'
            f'<td style="padding:5px 8px;color:#7b8794;font-family:ui-monospace">{html.escape(str(r.get("address") or "")[:10])}…</td>'
            f'<td style="padding:5px 8px;color:#fca5a5">{html.escape(_PS_RISK_LABELS.get(str(r.get("exclude_reason")), str(r.get("exclude_reason"))))}</td>'
            f'<td style="padding:5px 8px;text-align:right;color:#cbd5e1">{html.escape(_fmt_usd(r.get("market_cap")))}</td>'
            f'<td style="padding:5px 8px;text-align:right;color:#cbd5e1">{html.escape(_fmt_usd(r.get("liquidity")))}</td>'
            f'<td style="padding:5px 8px;text-align:right;color:#cbd5e1">{html.escape(_fmt_pct(r.get("price_change_interval_pct")))}</td>'
            '</tr>'
            for r in dropped)
        dropped_html = (
            '<div style="margin-top:14px">'
            '<div style="font-size:12px;font-weight:800;color:#fca5a5;margin-bottom:6px">'
            f'⛔ Auto-filtered ({len(dropped)})</div>'
            '<div style="overflow:auto;border:1px solid #1e2530;border-radius:10px">'
            '<table style="min-width:620px;width:100%;border-collapse:collapse;font-size:11.5px">'
            '<thead><tr style="background:#121821;color:#94a3b8;text-align:left">'
            '<th style="padding:6px 8px">Token</th><th style="padding:6px 8px">Address</th>'
            '<th style="padding:6px 8px">Reason</th><th style="padding:6px 8px;text-align:right">MCap</th>'
            '<th style="padding:6px 8px;text-align:right">Liquidity</th>'
            f'<th style="padding:6px 8px;text-align:right">Δ{html.escape(interval)}%</th></tr></thead>'
            f'<tbody>{d_rows}</tbody></table></div></div>'
        )
    note_html = (f'<div style="font-size:10.5px;color:#fde68a;margin-top:8px">note: '
                 f'{html.escape(hydration_note)}</div>') if hydration_note else ""
    _TH = 'padding:7px 9px;font-weight:700;white-space:nowrap'
    head_cells = [
        f'<th style="{_TH};text-align:right">#</th>',
        f'<th style="{_TH};text-align:left">Token</th>',
        f'<th style="{_TH};text-align:right">Δ{html.escape(interval)}%</th>',
        f'<th style="{_TH};text-align:right">Price</th>',
        f'<th style="{_TH};text-align:right">MCap</th>',
        f'<th style="{_TH};text-align:right">Liq</th>',
        f'<th style="{_TH};text-align:right">Vol({html.escape(interval)})</th>',
        f'<th style="{_TH};text-align:right">Trades</th>',
        f'<th style="{_TH};text-align:right">Holders</th>',
    ]
    if mode == "advanced":
        head_cells += [
            f'<th style="{_TH};text-align:right">Dev %</th>',
            f'<th style="{_TH};text-align:right">KOL</th>',
            f'<th style="{_TH};text-align:right">Avg trade</th>',
            f'<th style="{_TH};text-align:right">Tx/Wallet</th>',
            f'<th style="{_TH};text-align:right">Liq/MCap</th>',
            f'<th style="{_TH};text-align:left">Health</th>',
        ]
    if with_security:
        head_cells.append(
            f'<th style="{_TH};text-align:left" '
            f'title="Hover a badge: honeypot · mint · freeze · metadata · LP · tax · top-10">'
            f'Security</th>')
    head_cells.append(f'<th style="{_TH};text-align:left">Flags</th>')
    table_head = f'<thead><tr style="background:#121821;color:#94a3b8;text-align:left">{"".join(head_cells)}</tr></thead>'
    body_rows = "".join(_row(r) for r in kept)
    table_html = (
        '<div style="overflow:auto;border:1px solid #1e2530;border-radius:10px;margin-top:12px">'
        '<table style="min-width:960px;width:100%;border-collapse:collapse;font-size:11.5px">'
        + table_head + f'<tbody>{body_rows}</tbody></table></div>'
    ) if kept else (
        '<div style="color:#94a3b8;font-size:12px;padding:10px">No token survived the screen — '
        'loosen the surge floor or the market-cap range.</div>'
    )
    html_out = (
        '<div style="font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;'
        'background:#0b0f14;color:#e2e8f0;padding:14px;border-radius:14px">'
        '<div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap">'
        '<div style="font-size:16px;font-weight:800">💹 Price Surge Screen</div>'
        f'<div style="font-size:11.5px;color:#94a3b8">{html.escape(chain_label)} · {html.escape(interval)} · '
        f'mode {html.escape(mode_label)} · auto-filter {"on" if auto_filter else "off"} · sort '
        f'{html.escape(sort_note)}</div></div>'
        f'<div style="font-size:11px;color:#7b8794;margin-top:4px">market cap {html.escape(mcap_range)} · '
        f'liquidity ≥ {html.escape(_fmt_usd(params.get("min_liquidity")))} · '
        f'vol({html.escape(interval)}) ≥ {html.escape(_fmt_usd(params.get(f"min_volume_{interval}_usd")))} · '
        f'surge ≥ {html.escape(str(params.get(f"min_price_change_{interval}_percent")))}%</div>'
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:7px;margin-top:10px">'
        f'{stats_html}</div>'
        + table_html
        + dropped_html + note_html
        + '<div style="font-size:10px;color:#475569;margin-top:10px">⚡CU cost: '
        + html.escape(str(cu)) + ' (' + html.escape(", ".join(breakdown_cu)) + ')</div>'
        '</div>'
    )

    envelope = {
        "schemaVersion": 1, "kind": "price-surge-v1", "run_id": run_id,
        "cu_used": cu, "cu_breakdown": breakdown_cu,
        "params": {
            "chain": chain_norm, "interval": interval, "mode": mode,
            "sort_by": params.get("sort_by"), "sort_type": sort_type,
            "offset": offset, "limit": limit, "top": top, "platform": platform,
            "min_price_change": params.get(f"min_price_change_{interval}_percent"),
            "min_market_cap": min_mc, "max_market_cap": max_mc,
            "min_liquidity": params.get("min_liquidity"), "max_liquidity": params.get("max_liquidity"),
            "min_volume": params.get(f"min_volume_{interval}_usd"),
            "min_trade_count": params.get(f"min_trade_{interval}_count"),
            "min_holders": params.get("min_holder"),
            "auto_filter": auto_filter, "holder_health": holder_health,
            "with_security": with_security,
            "caps": {"max_liq_mcap_ratio": cfg["max_liq_mcap_ratio"],
                     "max_trades_per_wallet": cfg["max_trades_per_wallet"],
                     "max_dev_hold_pct": cfg["max_dev_hold_pct"],
                     "max_top10_pct": cfg["max_top10_pct"],
                     "min_kol_buyers": cfg["min_kol_buyers"]},
            "argv": sys.argv[1:],
        },
        "source": "birdeye", "source_label": "Birdeye /defi/v3/token/list",
        "chain_label": chain_label, "mcap_range": mcap_range, "sort_note": sort_note,
        "auto_filter": auto_filter, "holder_health": holder_health,
        "n_scanned": len(rows), "n_rows": len(kept), "n_excluded": len(dropped),
        "n_hydrated": n_hydrated, "hydration_note": hydration_note,
        "dropped": [{"symbol": r.get("symbol"), "address": r.get("address"),
                     "reason": r.get("exclude_reason"), "flags": r["risk_flags"]} for r in dropped],
        "rows": kept, "raw_response": raw, "html": html_out,
    }

    raw_json_text = json.dumps(raw, ensure_ascii=False, indent=2 if fmt == "json" else None)

    cdir = _cache_dir(getattr(args, "cache_dir", None))
    file_payload = {
        "runId": run_id, "kind": "price-surge-v1", "cached": False,
        "cu_used_total": cu, "cu_breakdown": breakdown_cu,
        "params": envelope["params"], "snapshot_time": int(time.time()),
        "rendered_plain": out_plain,
        "rendered_telegram": out_telegram,
        "rendered_json": json.dumps(raw, ensure_ascii=False, indent=2),
        "rendered_ui": json.dumps(envelope, ensure_ascii=False),
        "rendered_raw-json": json.dumps(raw, ensure_ascii=False),
        "rendered_rendered": json.dumps(envelope, ensure_ascii=False),
        "out": json.dumps(envelope, ensure_ascii=False),
    }
    _write_cache(cdir, run_id, file_payload)
    sys.stdout.write(f"#RUN_ID {run_id}\tprice-surge\tcu={cu}\n")

    if fmt == "plain":
        print(out_plain)
        return 0
    if fmt == "telegram":
        print(out_telegram)
        return 0
    print(raw_json_text if fmt == "json" else json.dumps(envelope, ensure_ascii=False))
    return 0


def cmd_junk_predict(args):
    """Skill #23 — Junk Token Prediction (ML classifier).

    Fetches /defi/token_overview + /holder/v1/distribution (top 20) for each
    token → extracts mcap/fdv/liquidity/v24hUSD/tx/trader + top-holder supply
    share → runs the trained LR/GBM model → junk score, then adds a continuous
    supply-concentration penalty (internal — the formula is never surfaced).
    """
    chain = args.chain
    raw_tokens = (args.tokens or "").strip()
    fmt = str(getattr(args, "format", "ui") or "ui").strip().lower()
    if fmt in {"render", "rendered", "ui"}:
        fmt = "ui"
    elif fmt in {"raw-json", "json"}:
        fmt = "json"
    mode = _jm.normalize_mode(getattr(args, "model", None))
    include_raw = str(getattr(args, "include", "") or "")
    include_flags = {
        part.strip().lower().replace(" ", "_")
        for part in include_raw.replace("\n", ",").split(",")
        if part.strip()
    }
    model_payload = _jm.merge_mode_payload(mode)
    threshold = _jm.threshold_points(mode, model_payload)
    model_name = _jm.model_label(mode, model_payload)
    mode_label = {
        "unsupervised": "Unsupervised",
        "function": "Function",
        "supervised": "Supervised",
    }.get(mode, mode.title())
    # Holder distribution is part of the score, not an optional extra: the
    # concentration rule needs the supply share of the top holders (top 1/3/10)
    # to run, so it is fetched by default for BOTH models. --no-holding opts out
    # (saves 30 CU/token but drops the concentration contribution to 0).
    want_holding = not bool(getattr(args, "no_holding", False))
    web_chain = {
        "sol": "solana",
        "eth": "ethereum",
        "bsc": "bsc",
        "base": "base",
        "arc": "arbitrum",
        "robinhood": "robinhood",
    }.get(chain, chain)
    key = _load_key()
    # 0-CU re-score: --score-b64 carries base64(JSON) of a previous junk-predict
    # envelope (or its results[] rows). Nothing is fetched from Birdeye here.
    score_only_rows: dict[str, dict[str, Any]] = {}
    score_b64 = str(getattr(args, "score_b64", None) or "").strip()
    if score_b64:
        try:
            payload = json.loads(base64.b64decode(score_b64.encode("ascii")).decode("utf-8"))
        except Exception as e:
            sys.stderr.write(f"[junk-predict] invalid --score-b64 payload: {e}\n")
            return 2
        rows = payload.get("results") if isinstance(payload, dict) else payload
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("address"):
                score_only_rows[str(row["address"])] = row
        if not score_only_rows:
            sys.stderr.write("[junk-predict] --score-b64 payload has no token rows.\n")
            return 2
    if not key and not score_only_rows:
        sys.stderr.write("[junk-predict] missing BIRDEYE_API_KEY.\n")
        return 2
    if not raw_tokens and not score_only_rows:
        sys.stderr.write("[junk-predict] --tokens is required.\n")
        return 2

    # Parse token list: comma, newline, tab, or whitespace separated
    if score_only_rows:
        addresses = list(score_only_rows.keys())
    else:
        addresses: list[str] = []
        for chunk in raw_tokens.replace("\n", ",").split(","):
            for addr in chunk.strip().split():
                if addr:
                    addresses.append(addr)
        if not addresses:
            sys.stderr.write("[junk-predict] no valid token addresses found.\n")
            return 2

    cu = 0
    breakdown_cu: list[str] = []
    results: list[dict] = []
    overview_calls = 0
    holder_dist_calls = 0
    search_fallback_calls = 0

    HOLDING_TOP1_SUSP_PCT = 99.0
    HOLDING_TOP3_EXCLUDE_PCT = 99.5
    HOLDING_TOP_MIN_PCT = 0.1
    HOLDING_TOP5_MIN_PCT = 0.05

    def _fetch_holder_distribution(session: requests.Session, address: str) -> dict[str, float] | None:
        dist_raw, _ms = _be(
            session,
            key,
            chain,
            "/holder/v1/distribution",
            {
                "address_type": "wallet",
                "mode": "top",
                "top_n": 20,
                "include_list": "true",
                "limit": 20,
                "token_address": address,
            },
        )
        dist_data = (dist_raw or {}).get("data") or {}
        holders = dist_data.get("holders") or []
        summary_pct = _jml._to_float((dist_data.get("summary") or {}).get("percent_of_supply"))
        raw_pcts: list[float] = []
        for holder in holders[:20]:
            val = _jml._to_float(holder.get("percentOfSupply"))
            if val is None:
                val = _jml._to_float(holder.get("percent_of_supply"))
            if val is None:
                continue
            raw_pcts.append(val)
        if not raw_pcts:
            return None
        # The whole holder list shares ONE scale: the API returns either fractions (0..1) or
        # percentages (0..100). Decide once for the list, never per-holder -- a holder under 1%
        # (e.g. 0.262) must NOT be inflated by x100. summary.percent_of_supply is the tie-breaker.
        total = sum(raw_pcts)
        if summary_pct is not None:
            scale = 100.0 if abs(total * 100.0 - summary_pct) < abs(total - summary_pct) else 1.0
        else:
            scale = 100.0 if total <= 1.0 else 1.0
        pcts: list[float] = [v * scale for v in raw_pcts]
        return {
            "top1_pct": round(sum(pcts[:1]), 6),
            "top3_pct": round(sum(pcts[:3]), 6),
            "top4_pct": round(sum(pcts[:4]), 6),
            "top5_pct": round(sum(pcts[:5]), 6),
            "top10_pct": round(sum(pcts[:10]), 6),
            "top20_pct": round(sum(pcts[:20]), 6),
        }

    def _holding_rule_alerts(row: dict[str, Any]) -> dict[str, Any]:
        top1 = _jml._to_float(row.get("top1_pct"))
        top3 = _jml._to_float(row.get("top3_pct"))
        top4 = _jml._to_float(row.get("top4_pct"))
        top5 = _jml._to_float(row.get("top5_pct"))
        reasons: list[str] = []
        tags: list[str] = []
        if top1 is not None and top1 >= HOLDING_TOP1_SUSP_PCT:
            tags.append("Top1 concentration")
            reasons.append(f"top1 {top1:.3f}% >= {HOLDING_TOP1_SUSP_PCT:.1f}%")
        if top3 is not None and top3 > HOLDING_TOP3_EXCLUDE_PCT:
            tags.append("Top3 illiquid")
            reasons.append(f"top3 {top3:.3f}% > {HOLDING_TOP3_EXCLUDE_PCT:.1f}%")
        dust_parts: list[str] = []
        if top3 is not None and top3 < HOLDING_TOP_MIN_PCT:
            dust_parts.append(f"top3 {top3:.3f}%")
        if top4 is not None and top4 < HOLDING_TOP_MIN_PCT:
            dust_parts.append(f"top4 {top4:.3f}%")
        if top5 is not None and top5 < HOLDING_TOP5_MIN_PCT:
            dust_parts.append(f"top5 {top5:.3f}%")
        if dust_parts:
            tags.append("Dust holders")
            reasons.append("dust holders (" + ", ".join(dust_parts) + ")")
        return {
            "triggered": bool(reasons),
            "tags": tags,
            "reasons": reasons,
            "exclude_by_top1": bool(top1 is not None and top1 >= HOLDING_TOP1_SUSP_PCT),
            "exclude_by_top3": bool(top3 is not None and top3 > HOLDING_TOP3_EXCLUDE_PCT),
            "exclude_by_low_conc": bool(dust_parts),
        }

    def _has_meaningful_metrics(row: dict[str, Any]) -> bool:
        for key_name in ("mcap", "fdv", "liquidity", "price", "vol_24h", "tx_24h", "trader_24h", "holder"):
            value = _jml._to_float(row.get(key_name))
            if value is not None and value != 0:
                return True
        return False

    def _search_exact_row(session: requests.Session, address: str) -> dict[str, Any] | None:
        raw, _ms = _be(session, key, chain, "/defi/v3/search", {"keyword": address})
        data = (raw.get("data") if isinstance(raw, dict) else {}) or {}
        best: dict[str, Any] | None = None
        for item in data.get("items") or []:
            row_type = str(item.get("type") or "").strip().lower()
            for row in item.get("result") or []:
                if not isinstance(row, dict):
                    continue
                out = dict(row)
                out["_search_type"] = row_type
                if str(row.get("address") or "") == address:
                    return out
                if best is None and row_type in {"token", "market"}:
                    best = out
        return best

    def _fill_from_search(entry: dict[str, Any], row: dict[str, Any]) -> None:
        row_type = str(row.get("_search_type") or "").strip().lower()
        entry["address_kind"] = row_type or entry.get("address_kind") or "token"
        entry["fallback_source"] = "search"
        entry["name"] = (row.get("name") or entry.get("name") or entry["short_address"]).strip()
        icon_url = row.get("logo_uri") or row.get("logoURI") or row.get("logo")
        if icon_url:
            entry["icon_url"] = icon_url
        symbol = (row.get("symbol") or "").strip()
        if symbol:
            entry["symbol"] = symbol
        elif row_type == "market" and entry.get("symbol") == entry["address"][:6]:
            entry["symbol"] = "PAIR"
        entry["mcap"] = entry.get("mcap") if entry.get("mcap") is not None else _jml._to_float(row.get("market_cap"))
        entry["fdv"] = entry.get("fdv") if entry.get("fdv") is not None else _jml._to_float(row.get("fdv"))
        entry["liquidity"] = entry.get("liquidity") if entry.get("liquidity") is not None else _jml._to_float(row.get("liquidity"))
        entry["vol_24h"] = _jml._to_float(row.get("volume_24h_usd")) if _jml._to_float(row.get("volume_24h_usd")) is not None else entry.get("vol_24h")
        entry["tx_24h"] = _jml._to_float(row.get("trade_24h")) if _jml._to_float(row.get("trade_24h")) is not None else entry.get("tx_24h")
        entry["trader_24h"] = _jml._to_float(row.get("unique_wallet_24h")) if _jml._to_float(row.get("unique_wallet_24h")) is not None else entry.get("trader_24h")
        entry["holder"] = _jml._to_float(row.get("holder")) if _jml._to_float(row.get("holder")) is not None else entry.get("holder")
        entry["price"] = entry.get("price") if entry.get("price") is not None else _jml._to_float(row.get("price"))
        entry["price_change_24h_pct"] = _jml._to_float(row.get("price_change_24h_percent")) if _jml._to_float(row.get("price_change_24h_percent")) is not None else entry.get("price_change_24h_pct")
        entry["vol_change_24h_pct"] = _jml._to_float(row.get("volume_24h_change_percent")) if _jml._to_float(row.get("volume_24h_change_percent")) is not None else entry.get("vol_change_24h_pct")
        if row_type == "market":
            entry["base_mint"] = row.get("base_mint")
            entry["quote_mint"] = row.get("quote_mint")
            entry["market_name"] = row.get("name")
            entry["market_source"] = row.get("source")

    def _raw_token_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
        raw_token: dict[str, Any] = {
            "chain": CHAINS.get(chain, chain),
            "mcap_usd": entry.get("mcap"),
            "fdv_usd": entry.get("fdv"),
            "liquidity_usd": entry.get("liquidity"),
            "vol_24h_usd": entry.get("vol_24h"),
            "tx_24h": entry.get("tx_24h"),
            "trader_24h": entry.get("trader_24h"),
            "holder_count": entry.get("holder"),
            "price_change_24h": entry.get("price_change_24h_pct"),
            "vol_30d_usd": None,
        }
        for hk in ("top1_pct", "top3_pct", "top4_pct", "top5_pct", "top10_pct", "top20_pct"):
            if entry.get(hk) is not None:
                raw_token[hk] = entry[hk]
        return raw_token

    def _score_entry(entry: dict[str, Any], raw_token: dict[str, Any]) -> None:
        pred = _jm.score_token(raw_token, mode=mode)
        entry["junk_score"] = pred["score"]
        entry["is_junk"] = pred["is_junk"]
        entry["threshold"] = pred.get("threshold", threshold)
        entry["mode"] = pred.get("mode", mode)
        entry["model_name"] = model_name
        entry["proba"] = pred.get("proba")
        entry["holding_rule_alerts"] = (
            _holding_rule_alerts(entry) if want_holding
            else {"triggered": False, "tags": [], "reasons": []}
        )

    for addr in addresses:
        short_addr = f"{addr[:6]}...{addr[-4:]}" if len(addr) > 12 else addr
        entry: dict[str, Any] = {
            "address": addr,
            "short_address": short_addr,
            "symbol": "",
            "name": short_addr,
            "error": None,
            "icon_url": None,
            "birdeye_url": f"https://birdeye.so/{web_chain}/token/{addr}",
            "address_kind": "token",
        }
        if addr in score_only_rows:
            # 0-CU path: reuse the metrics captured by the previous run.
            entry.update(score_only_rows[addr])
            entry["short_address"] = short_addr
            entry["birdeye_url"] = entry.get("birdeye_url") or f"https://birdeye.so/{web_chain}/token/{addr}"
            entry["error"] = None
            entry.pop("holding_distribution_error", None)
            _score_entry(entry, _raw_token_from_entry(entry))
            results.append(entry)
            continue
        try:
            with requests.Session() as s:
                ov_raw, _ms = _be(s, key, chain, "/defi/token_overview",
                                  {"address": addr})
            ovd = (ov_raw.get("data") if isinstance(ov_raw, dict) else {}) or {}
            ext = (ovd.get("extensions") if isinstance(ovd, dict) else {}) or {}
            cu += 21
            overview_calls += 1
            entry["symbol"] = (ovd.get("symbol") or ext.get("symbol") or addr[:6]).strip()
            entry["name"] = (ovd.get("name") or ext.get("name") or short_addr).strip()
            entry["icon_url"] = (
                ovd.get("logoURI")
                or ovd.get("logo_uri")
                or ovd.get("logo")
                or ext.get("logoURI")
                or ext.get("logo_uri")
                or ext.get("logo")
            )
            entry["mcap"] = _jml._to_float(ovd.get("marketCap"))
            entry["fdv"] = _jml._to_float(ovd.get("fdv"))
            entry["liquidity"] = _jml._to_float(ovd.get("liquidity"))
            entry["vol_24h"] = _jml._to_float(ovd.get("v24hUSD"))
            # tx_24h: prefer trade24h (list/overview field), fallback to buy24h+sell24h
            trade24 = _jml._to_float(ovd.get("trade24h"))
            if trade24 is not None:
                entry["tx_24h"] = trade24
            else:
                buy24 = _jml._to_float(ovd.get("buy24h")) or 0.0
                sell24 = _jml._to_float(ovd.get("sell24h")) or 0.0
                entry["tx_24h"] = buy24 + sell24 if (buy24 or sell24) else None
            entry["trader_24h"] = _jml._to_float(ovd.get("uniqueWallet24h"))
            # Extra display fields
            entry["price"] = _jml._to_float(ovd.get("price"))
            entry["holder"] = _jml._to_float(ovd.get("holder"))
            entry["number_markets"] = _jml._to_float(ovd.get("numberMarkets"))
            entry["price_change_24h_pct"] = _jml._to_float(ovd.get("priceChange24hPercent"))
            entry["vol_change_24h_pct"] = _jml._to_float(ovd.get("v24hChangePercent"))
            if not _has_meaningful_metrics(entry):
                with requests.Session() as s:
                    search_row = _search_exact_row(s, addr)
                if search_row:
                    _fill_from_search(entry, search_row)
                    search_fallback_calls += 1
            if not _has_meaningful_metrics(entry):
                entry["error"] = "No Birdeye token or market data found for this address"
                entry["junk_score"] = None
                entry["is_junk"] = None
                results.append(entry)
                continue
            raw_token: dict[str, Any] = {
                "chain": CHAINS.get(chain, chain),
                "mcap_usd": entry["mcap"],
                "fdv_usd": entry["fdv"],
                "liquidity_usd": entry["liquidity"],
                "vol_24h_usd": entry["vol_24h"],
                "tx_24h": entry["tx_24h"],
                "trader_24h": entry["trader_24h"],
                "holder_count": entry["holder"],
                "price_change_24h": entry["price_change_24h_pct"],
                "vol_30d_usd": None,
            }
            if want_holding and entry.get("address_kind") == "token":
                try:
                    with requests.Session() as s:
                        dist = _fetch_holder_distribution(s, addr)
                    if dist:
                        raw_token.update(dist)
                        entry.update(dist)
                    cu += 30
                    holder_dist_calls += 1
                except Exception:
                    entry["holding_distribution_error"] = "holder distribution unavailable"
            pred = _jm.score_token(raw_token, mode=mode)
            entry["junk_score"] = pred["score"]
            entry["is_junk"] = pred["is_junk"]
            entry["threshold"] = pred.get("threshold", threshold)
            entry["mode"] = pred.get("mode", mode)
            entry["model_name"] = model_name
            entry["proba"] = pred.get("proba")
            entry["holding_rule_alerts"] = _holding_rule_alerts(entry) if want_holding else {"triggered": False, "tags": [], "reasons": []}
        except Exception as e:
            entry["error"] = str(e)[:200]
            entry["junk_score"] = None
            entry["is_junk"] = None
        results.append(entry)

    breakdown_cu.append(f"overview=21x{overview_calls}")
    if holder_dist_calls:
        breakdown_cu.append(f"holder_distribution=30x{holder_dist_calls}")
    if search_fallback_calls:
        breakdown_cu.append(f"search_fallback=auxx{search_fallback_calls}")

    run_id = f"junk_{chain}_{int(time.time())}"

    plain_lines = [
        f"Skill #23 · Junk Token Prediction — {chain.upper()}",
        f"Mode: {mode_label} · {model_name}",
    ]
    if not want_holding:
        plain_lines.append("Include: holding_distribution OFF (--no-holding)")
    plain_lines.append(f"{'#':>3} {'Symbol':<12} {'JunkProb':>8} {'Verdict':>8} {'MCap':>12} {'Liq':>12} {'Vol24h':>12} {'Tx24h':>8} {'Trader':>8}")
    plain_lines.append("-" * 95)
    for i, r in enumerate(results, 1):
        if r.get("error"):
            plain_lines.append(f"{i:>3} {r['address'][:12]:<12} ERROR: {r['error']}")
            continue
        sym = (r.get("symbol") or "?")[:12]
        sc = f"{r['junk_score']:.1f}" if r["junk_score"] is not None else "N/A"
        junk = "JUNK" if r.get("is_junk") else "OK"
        mc = _fmt_usd(r.get("mcap"))
        liq = _fmt_usd(r.get("liquidity"))
        vol = _fmt_usd(r.get("vol_24h"))
        tx = f"{int(r['tx_24h']):,}" if r.get("tx_24h") is not None else "N/A"
        tr = f"{int(r['trader_24h']):,}" if r.get("trader_24h") is not None else "N/A"
        plain_lines.append(f"{i:>3} {sym:<12} {sc:>8} {junk:>8} {mc:>12} {liq:>12} {vol:>12} {tx:>8} {tr:>8}")
    plain_lines.append("")
    plain_lines.append(f"⚡CU: {cu} ({', '.join(breakdown_cu)})")
    out_plain = "\n".join(plain_lines)

    tg_lines = [
        "🗑️ Junk Token Prediction",
        f"Chain: {chain.upper()} · Mode: {mode_label}",
        f"Model: {model_name}",
    ]
    if not want_holding:
        tg_lines.append("Include: holding_distribution OFF (--no-holding)")
    for r in results:
        if r.get("error"):
            tg_lines.append(f"• {r['address'][:16]}… → ERROR: {r['error']}")
            continue
        verdict = "🚫 JUNK" if r.get("is_junk") else "✅ OK"
        tg_lines.append(
            f"• {r.get('name') or r.get('symbol') or r['address'][:12]} "
            f"({r.get('symbol') or '?'})\n"
            f"  Junk Probability: {r.get('junk_score', 0):.1f}/100 · {verdict}"
        )
        alerts = (r.get("holding_rule_alerts") or {}).get("reasons") or []
        if alerts:
            tg_lines.append("  Holding alerts: " + "; ".join(alerts))
    tg_lines.append(f"⚡CU: {cu} ({', '.join(breakdown_cu)})")
    out_telegram = "\n".join(tg_lines)

    if fmt == "plain":
        print(out_plain)
        return 0
    if fmt == "telegram":
        print(out_telegram)
        return 0

    # ── Build envelope ──
    n_junk = sum(1 for r in results if r.get("is_junk"))
    envelope = {
        "schemaVersion": 1, "kind": "junk-predict-v1", "run_id": run_id,
        "cu_used": cu, "params": {"chain": chain, "tokens": addresses,
                                  "mode": mode, "include": sorted(include_flags),
                                  "threshold": threshold, "argv": sys.argv[1:]},
        "threshold": threshold,
        "mode": mode,
        "mode_label": mode_label,
        "model_name": model_name,
        "n_tokens": len(results),
        "n_junk": n_junk,
        "results": results,
        "cu_breakdown": breakdown_cu,
    }

    # ── Rendered HTML ──
    def _junk_prob_color(score_value: float | int | None) -> str:
        score_value = 0.0 if score_value is None else float(score_value)
        if score_value < 25:
            return "#22c55e"  # green
        if score_value < 50:
            return "#facc15"  # yellow
        if score_value < 75:
            return "#fb923c"  # orange
        return "#ef4444"      # red

    def _state_label(obj: dict[str, Any], key: str) -> tuple[str, Any]:
        if key not in obj:
            return "missing", None
        return ("null", None) if obj.get(key) is None else ("value", obj.get(key))

    def _fmt_usd_field(obj: dict[str, Any], key: str) -> str:
        state, value = _state_label(obj, key)
        if state != "value":
            return state
        num = _jml._to_float(value)
        if num is None:
            return str(value)
        if num == 0:
            return "0"
        return _fmt_usd(num)

    def _fmt_int_field(obj: dict[str, Any], key: str) -> str:
        state, value = _state_label(obj, key)
        if state != "value":
            return state
        num = _jml._to_float(value)
        if num is None:
            return str(value)
        if num == 0:
            return "0"
        return f"{int(num):,}"

    def _fmt_pct_field(obj: dict[str, Any], key: str) -> str:
        state, value = _state_label(obj, key)
        if state != "value":
            return state
        num = _jml._to_float(value)
        if num is None:
            return str(value)
        if num == 0:
            return "0"
        return f"{'+' if num >= 0 else ''}{num:.2f}%"

    def _fmt_price_field(obj: dict[str, Any], key: str) -> str:
        state, value = _state_label(obj, key)
        if state != "value":
            return state
        num = _jml._to_float(value)
        if num is None:
            return str(value)
        if num == 0:
            return "0"
        if num >= 1:
            return f"${num:,.4f}"
        return f"${num:.8f}"

    def _fmt_conc_field(obj: dict[str, Any], key: str) -> str:
        state, value = _state_label(obj, key)
        if state != "value":
            return state
        num = _jml._to_float(value)
        if num is None:
            return str(value)
        if num == 0:
            return "0"
        return f"{num:.2f}%"

    cards_html = ""
    for r in results:
        if r.get("error"):
            logo_html = ""
            if r.get("icon_url"):
                logo_html = (
                    f'<img class="junkIcon" src="{html.escape(r.get("icon_url") or "", quote=True)}" '
                    f'alt="{html.escape(r.get("symbol") or r.get("short_address") or "token")}"/>'
                )
            cards_html += (
                f'<div class="junkCard junkErrorCard">'
                f'<div class="junkTop">'
                f'<div class="junkIdentityWrap">'
                f'{logo_html}'
                f'<div class="junkIdentity">'
                f'<div class="junkNameRow"><span class="junkName">{html.escape(r.get("name") or r.get("short_address") or "Unknown token")}</span><span class="junkSymbol">{html.escape(r.get("symbol") or "")}</span><a class="junkLinkBtn" href="{html.escape(r.get("birdeye_url") or f"https://birdeye.so/{web_chain}/token/{r["address"]}", quote=True)}" target="_blank" rel="noopener noreferrer" title="Open on Birdeye">↗</a></div>'
                f'<button class="junkAddrBtn" data-copy="{html.escape(r["address"], quote=True)}" data-label="{html.escape(r.get("short_address") or r["address"], quote=True)}" onclick="if(navigator.clipboard)navigator.clipboard.writeText(this.dataset.copy);const el=this;el.textContent=\'✓ copied\';setTimeout(function(){{el.textContent=el.dataset.label;}},900);return false;">{html.escape(r.get("short_address") or r["address"])}</button>'
                f'</div></div>'
                f'<div class="junkScoreWrap">'
                f'<div class="junkScoreLabel">Status</div>'
                f'<div class="junkScoreValue junkScoreBad">Error</div>'
                f'</div></div>'
                f'<div class="junkErrText">Error: {html.escape(r["error"])}</div>'
                f'</div>'
            )
            continue
        sym = r.get("symbol") or "?"
        name = r.get("name") or sym
        logo_html = ""
        if r.get("icon_url"):
            logo_html = (
                f'<img class="junkIcon" src="{html.escape(r.get("icon_url") or "", quote=True)}" '
                f'alt="{html.escape(sym)}"/>'
            )
        is_junk = r.get("is_junk", False)
        score = r.get("junk_score", 0) or 0
        score_color = _junk_prob_color(score)
        badge_color = "#ef4444" if is_junk else "#2ecc71"
        badge_text = "🚫 JUNK" if is_junk else "✅ OK"

        # Color helper for % changes
        def _pct_color(v):
            if v is None:
                return "#8a93a6"
            return "#2ecc71" if v >= 0 else "#ef4444"

        status_tags: list[str] = []
        holder_rule_alerts = r.get("holding_rule_alerts") or {}
        for tag in holder_rule_alerts.get("tags") or []:
            if tag not in status_tags:
                status_tags.append(tag)
        if r.get("holding_distribution_error"):
            status_tags.append("Holder API unavailable")
        status_html = "".join(
            f'<div style="font-size:11px;background:#0f1115;padding:3px 10px;border-radius:999px;color:#94a3b8">{html.escape(tag)}</div>'
            for tag in status_tags
        )

        holding_warn_html = ""
        alert_reasons = holder_rule_alerts.get("reasons") or []
        if alert_reasons:
            holding_warn_html = "".join(
                f'<div style="font-size:11px;background:rgba(239,68,68,.08);padding:4px 10px;border-radius:999px;color:#fca5a5;border:1px solid rgba(239,68,68,.25)">{html.escape(reason)}</div>'
                for reason in alert_reasons
            )
            holding_warn_html = f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">{holding_warn_html}</div>'

        holding_html = ""
        if any(r.get(k) is not None for k in ("top1_pct", "top3_pct", "top4_pct", "top5_pct", "top10_pct", "top20_pct")):
            holding_html = (
                f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">'
                f'<div style="font-size:11px;background:#0f1115;padding:3px 10px;border-radius:999px;color:#94a3b8">top1: <span style="color:#e6e8ef;font-weight:700">{_fmt_conc_field(r, "top1_pct")}</span></div>'
                f'<div style="font-size:11px;background:#0f1115;padding:3px 10px;border-radius:999px;color:#94a3b8">top3: <span style="color:#e6e8ef;font-weight:700">{_fmt_conc_field(r, "top3_pct")}</span></div>'
                f'<div style="font-size:11px;background:#0f1115;padding:3px 10px;border-radius:999px;color:#94a3b8">top4: <span style="color:#e6e8ef;font-weight:700">{_fmt_conc_field(r, "top4_pct")}</span></div>'
                f'<div style="font-size:11px;background:#0f1115;padding:3px 10px;border-radius:999px;color:#94a3b8">top5: <span style="color:#e6e8ef;font-weight:700">{_fmt_conc_field(r, "top5_pct")}</span></div>'
                f'<div style="font-size:11px;background:#0f1115;padding:3px 10px;border-radius:999px;color:#94a3b8">top10: <span style="color:#e6e8ef;font-weight:700">{_fmt_conc_field(r, "top10_pct")}</span></div>'
                f'<div style="font-size:11px;background:#0f1115;padding:3px 10px;border-radius:999px;color:#94a3b8">top20: <span style="color:#e6e8ef;font-weight:700">{_fmt_conc_field(r, "top20_pct")}</span></div>'
                f'</div>'
            )

        cards_html += f'''<div class="junkCard" style="border-color:{'#ef4444' if is_junk else '#262b36'}">
  <div class="junkTop">
    <div class="junkIdentityWrap">
      {logo_html}
      <div class="junkIdentity">
        <div class="junkNameRow"><span class="junkName">{html.escape(name)}</span><span class="junkSymbol">{html.escape(sym)}</span><a class="junkLinkBtn" href="{html.escape(r.get("birdeye_url") or f"https://birdeye.so/{web_chain}/token/{r["address"]}", quote=True)}" target="_blank" rel="noopener noreferrer" title="Open on Birdeye">↗</a></div>
        <button class="junkAddrBtn" data-copy="{html.escape(r["address"], quote=True)}" data-label="{html.escape(r.get("short_address") or r["address"], quote=True)}" onclick="if(navigator.clipboard)navigator.clipboard.writeText(this.dataset.copy);const el=this;el.textContent='✓ copied';setTimeout(function(){{el.textContent=el.dataset.label;}},900);return false;">{html.escape(r.get("short_address") or r["address"])}</button>
      </div>
    </div>
    <div class="junkScoreWrap">
      <div class="junkScoreLabel">Junk Probability</div>
      <div class="junkScoreValue" style="color:{score_color}">{score:.1f}<span class="junkScoreUnit">/100</span></div>
      <div class="junkVerdict" style="background:{badge_color};color:#000">{badge_text}</div>
    </div>
  </div>
  <div class="junkMiniGrid">
    <div class="junkMiniStat"><span class="junkMiniLabel">MCap</span><span class="junkMiniValue">{_fmt_usd_field(r, "mcap")}</span></div>
    <div class="junkMiniStat"><span class="junkMiniLabel">Liquidity</span><span class="junkMiniValue">{_fmt_usd_field(r, "liquidity")}</span></div>
    <div class="junkMiniStat"><span class="junkMiniLabel">Vol 24h</span><span class="junkMiniValue">{_fmt_usd_field(r, "vol_24h")}</span></div>
    <div class="junkMiniStat"><span class="junkMiniLabel">Price</span><span class="junkMiniValue">{_fmt_price_field(r, "price")}</span></div>
    <div class="junkMiniStat"><span class="junkMiniLabel">Holders</span><span class="junkMiniValue">{_fmt_int_field(r, "holder")}</span></div>
    <div class="junkMiniStat"><span class="junkMiniLabel">Tx 24h</span><span class="junkMiniValue">{_fmt_int_field(r, "tx_24h")}</span></div>
    <div class="junkMiniStat"><span class="junkMiniLabel">Price Δ24h</span><span class="junkMiniValue" style="color:{_pct_color(_jml._to_float(r.get('price_change_24h_pct')))}">{_fmt_pct_field(r, "price_change_24h_pct")}</span></div>
    <div class="junkMiniStat"><span class="junkMiniLabel">Vol Δ24h</span><span class="junkMiniValue" style="color:{_pct_color(_jml._to_float(r.get('vol_change_24h_pct')))}">{_fmt_pct_field(r, "vol_change_24h_pct")}</span></div>
  </div>
  <div class="junkFeatureChips">
    {status_html}
  </div>
  {holding_warn_html}
  {holding_html}
</div>'''

    summary_badge = ""
    if n_junk > 0:
        summary_badge = (f'<div style="background:#1a1a2e;border:1px solid #ef4444;border-radius:10px;padding:12px;margin-bottom:14px">'
                         f'<span style="color:#ef4444;font-weight:800">⚠ {n_junk}/{len(results)} token(s) flagged as JUNK</span></div>')
    else:
        summary_badge = (f'<div style="background:#0f1f15;border:1px solid #2ecc71;border-radius:10px;padding:12px;margin-bottom:14px">'
                         f'<span style="color:#2ecc71;font-weight:800">✅ {len(results)}/{len(results)} token(s) OK</span></div>')

    include_note = "" if want_holding else " · holder distribution OFF"
    html_out = (f'<div style="max-width:1100px;margin:0 auto">'
                f'<style>'
                f'.junkGrid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}'
                f'.junkCard{{background:#171a21;border:1px solid #262b36;border-radius:12px;padding:12px;min-width:0}}'
                f'.junkErrorCard{{border-color:#ef4444}}'
                f'.junkTop{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:10px}}'
                f'.junkIdentityWrap{{display:flex;gap:10px;min-width:0;flex:1;align-items:flex-start}}'
                f'.junkIcon{{width:38px;height:38px;border-radius:10px;background:#0f1115;border:1px solid #262b36;object-fit:cover;display:block;flex:0 0 38px}}'
                f'.junkIdentity{{min-width:0;display:flex;flex-direction:column;gap:4px}}'
                f'.junkNameRow{{display:flex;gap:6px;align-items:center;flex-wrap:wrap}}'
                f'.junkName{{font-size:15px;font-weight:800;color:#e6e8ef;line-height:1.15}}'
                f'.junkSymbol{{font-size:11px;color:#8a93a6;font-weight:700;background:#0f1115;border:1px solid #262b36;border-radius:999px;padding:2px 7px}}'
                f'.junkLinkBtn{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;border:1px solid #262b36;background:#0f1115;color:#8fb8ff;text-decoration:none;font-size:12px;font-weight:800}}'
                f'.junkLinkBtn:hover{{border-color:#5b9dff;color:#d6e6ff}}'
                f'.junkAddrBtn{{padding:0;border:0;background:none;color:#94a3b8;font:11px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}'
                f'.junkAddrBtn:hover{{color:#e6e8ef}}'
                f'.junkScoreWrap{{text-align:right;flex:0 0 auto}}'
                f'.junkScoreLabel{{font-size:10px;color:#8a93a6;letter-spacing:.34px;text-transform:uppercase}}'
                f'.junkScoreValue{{font-size:24px;font-weight:900;line-height:1.05}}'
                f'.junkScoreUnit{{font-size:11px;color:#8a93a6}}'
                f'.junkScoreBad{{color:#ef4444}}'
                f'.junkVerdict{{display:inline-block;font-weight:800;font-size:10px;padding:2px 8px;border-radius:999px;margin-top:4px}}'
                f'.junkMiniGrid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}}'
                f'.junkMiniStat{{background:#0f1115;border-radius:8px;padding:7px 8px;min-width:0}}'
                f'.junkMiniLabel{{display:block;font-size:10px;color:#8a93a6;text-transform:uppercase;margin-bottom:3px}}'
                f'.junkMiniValue{{display:block;font-size:12px;font-weight:700;color:#e6e8ef;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}'
                f'.junkFeatureChips{{display:flex;gap:8px;flex-wrap:wrap}}'
                f'.junkChip{{font-size:11px;background:#0f1115;padding:3px 10px;border-radius:999px;color:#94a3b8}}'
                f'.junkErrText{{font-size:12px;color:#fca5a5;margin-top:6px}}'
                f'@media(max-width:900px){{.junkGrid{{grid-template-columns:1fr}}.junkMiniGrid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}'
                f'@media(max-width:620px){{.junkTop{{flex-direction:column;align-items:stretch}}.junkScoreWrap{{text-align:left}}}}'
                f'</style>'
                f'<div style="font-size:20px;font-weight:800;color:#e6e8ef;margin-bottom:4px">🗑️ Junk Token Prediction</div>'
                f'<div style="font-size:12px;color:#8a93a6;margin-bottom:14px">{chain.upper()} · {len(results)} token(s) · {mode_label} · {html.escape(model_name)}{include_note}</div>'
                f'{summary_badge}'
                f'<div class="junkGrid">{cards_html}</div>'
                f'<div style="font-size:10px;color:#475569;margin-top:10px">⚡CU cost: {cu} ({html.escape(", ".join(breakdown_cu))})</div>'
                f'</div>')

    envelope["html"] = html_out

    # Persist to cache
    cdir = _cache_dir(getattr(args, "cache_dir", None))
    file_payload = {
        "runId": run_id, "kind": "junk-predict-v1", "cached": False,
        "cu_used_total": cu, "cu_breakdown": breakdown_cu,
        "params": envelope["params"],
        "snapshot_time": int(time.time()),
        "rendered_plain": out_plain,
        "rendered_telegram": out_telegram,
        "rendered_json": json.dumps(envelope, ensure_ascii=False),
        "rendered_ui": json.dumps(envelope, ensure_ascii=False),
        "rendered_raw-json": json.dumps(envelope, ensure_ascii=False),
        "rendered_rendered": json.dumps(envelope, ensure_ascii=False),
        "out": json.dumps(envelope, ensure_ascii=False),
    }
    _write_cache(cdir, run_id, file_payload)
    sys.stdout.write(f"#RUN_ID {run_id}\tjunk-predict\tcu={cu}\n")

    if fmt == "json":
        print(json.dumps(envelope, ensure_ascii=False))
        return 0

    print(json.dumps(envelope, ensure_ascii=False))
    return 0


def cmd_junk_quick_test(args):
    """Skill #23 — Junk Quick Test (1 scroll call → random N tokens → ML).

    Fetches up to 5000 tokens via /defi/v3/token/list/scroll (300 CU), randomly
    picks N tokens, runs the trained LR model directly on the list fields
    (market_cap, fdv, liquidity, volume_24h_usd, trade_24h_count, holder).
    No per-token /defi/token_overview call → very cheap for bulk screening.
    """
    chain = args.chain
    n_pick = max(1, min(int(getattr(args, "num", 30)), 500))
    scroll_limit = max(1, min(int(getattr(args, "limit", 5000)), 5000))
    sort_by = getattr(args, "sort_by", "liquidity")
    sort_type = getattr(args, "sort_type", "desc")
    platform = getattr(args, "platform", None)
    min_liq = getattr(args, "min_liquidity", None)
    max_liq = getattr(args, "max_liquidity", None)
    min_mcap = getattr(args, "min_market_cap", None)
    max_mcap = getattr(args, "max_market_cap", None)
    # Threshold is decided by the model (lr_params.json), not by the user.
    threshold = float(_jml._get_model().get("threshold", 95.0))
    fmt = _canonical_format(getattr(args, "format", None))
    key = _load_key()
    if not key:
        sys.stderr.write("[junk-quick-test] missing BIRDEYE_API_KEY.\n")
        return 2

    run_id = f"junkqt_{chain}_{int(time.time())}"
    cu = 0
    breakdown_cu: list[str] = []

    # 1) Single scroll call → up to 5000 tokens
    params: dict[str, Any] = {
        "limit": scroll_limit,
        "sort_by": sort_by,
        "sort_type": sort_type,
    }
    if platform:
        params["platform_name"] = platform
    if min_liq is not None:
        params["min_liquidity"] = min_liq
    if max_liq is not None:
        params["max_liquidity"] = max_liq
    if min_mcap is not None:
        params["min_market_cap"] = min_mcap
    if max_mcap is not None:
        params["max_market_cap"] = max_mcap

    try:
        with requests.Session() as s:
            data, _ms = _be(s, key, chain, "/defi/v3/token/list/scroll", params)
    except Exception as e:
        sys.stderr.write(f"[junk-quick-test] scroll fetch failed: {e}\n")
        return 1
    cu += 300
    breakdown_cu.append(f"scroll=300x1")

    d = data.get("data") if isinstance(data, dict) else {}
    items = (d.get("items") if isinstance(d, dict) else None) or []
    total = len(items)
    if total == 0:
        sys.stderr.write("[junk-quick-test] no tokens returned from scroll.\n")
        return 1

    # 2) Randomly pick N tokens
    pick_count = min(n_pick, total)
    picked = random.sample(items, pick_count) if pick_count < total else items

    # 3) Run ML on each token using list data
    results: list[dict] = []
    n_junk = 0
    for t in picked:
        addr = t.get("address", "")
        entry: dict[str, Any] = {
            "address": addr,
            "symbol": t.get("symbol") or t.get("symbols") or "",
            "name": t.get("name") or t.get("symbol") or addr[:12],
            "error": None,
        }
        try:
            mcap = _jml._to_float(t.get("market_cap"))
            fdv = _jml._to_float(t.get("fdv"))
            liq = _jml._to_float(t.get("liquidity"))
            vol24 = _jml._to_float(t.get("volume_24h_usd"))
            tx24 = _jml._to_float(t.get("trade_24h_count"))
            holder = _jml._to_float(t.get("holder"))
            price = _jml._to_float(t.get("price"))
            price_chg24 = _jml._to_float(t.get("price_change_24h_percent"))
            vol_chg24 = _jml._to_float(t.get("volume_24h_change_percent"))
            list_time = t.get("recent_listing_time")

            entry["mcap"] = mcap
            entry["fdv"] = fdv
            entry["liquidity"] = liq
            entry["vol_24h"] = vol24
            entry["tx_24h"] = tx24
            entry["trader_24h"] = holder
            entry["price"] = price
            entry["price_change_24h"] = price_chg24
            entry["volume_change_24h"] = vol_chg24
            entry["holder"] = holder
            entry["number_markets"] = _jml._to_float(t.get("numberMarkets") or t.get("number_markets"))
            entry["recent_listing_time"] = list_time

            pred = _jml.predict(
                mcap=mcap, fdv=fdv, liquidity=liq, vol_24h=vol24,
                tx_24h=tx24, trader_24h=holder, threshold=threshold,
            )
            entry["junk_score"] = pred["score"]
            entry["is_junk"] = pred["is_junk"]
            if pred["is_junk"]:
                n_junk += 1
        except Exception as e:
            entry["error"] = str(e)
        results.append(entry)

    # ── Output ──
    envelope: dict[str, Any] = {
        "schemaVersion": 1, "kind": "junk-quick-test-v1", "run_id": run_id,
        "cu_used": cu, "params": {
            "chain": chain, "n_pick": pick_count, "scroll_total": total,
            "scroll_limit": scroll_limit, "sort_by": sort_by, "sort_type": sort_type,
            "platform": platform, "min_liquidity": min_liq, "max_liquidity": max_liq,
            "min_market_cap": min_mcap, "max_market_cap": max_mcap,
            "threshold": threshold,
        },
        "threshold": threshold,
        "n_tokens": len(results), "n_junk": n_junk,
        "scroll_total": total,
        "results": results,
        "cu_breakdown": breakdown_cu,
    }

    # ── Plain table ──
    if fmt == "plain":
        lines = [f"Skill #23 · Junk Quick Test — {chain.upper()}",
                 f"Scroll: {total} tokens → picked {pick_count} random · ngưỡng {threshold}/100",
                 f"  # {'Symbol':<12} {'Score':>6} {'Junk?':>6} {'MCap':>12} {'Liq':>12} {'Vol24h':>12} {'Tx24h':>9} {'Holder':>9}",
                 "-" * 95]
        for i, r in enumerate(results, 1):
            if r.get("error"):
                lines.append(f"  {i:<3} {r['address'][:12]:<12}  ERROR: {r['error'][:40]}")
                continue
            tx_s = f"{int(r['tx_24h']):,}" if r.get("tx_24h") is not None else "N/A"
            hd_s = f"{int(r['holder']):,}" if r.get("holder") is not None else "N/A"
            lines.append(
                f"  {i:<3} {(r.get('symbol') or '?')[:12]:<12} "
                f"{r.get('junk_score', 0):>6.1f} "
                f"{'JUNK' if r.get('is_junk') else 'ok':>6} "
                f"{_fmt_usd(r.get('mcap')):>12} "
                f"{_fmt_usd(r.get('liquidity')):>12} "
                f"{_fmt_usd(r.get('vol_24h')):>12} "
                f"{tx_s:>9} "
                f"{hd_s:>9}"
            )
        lines.append("")
        lines.append(f"⚡CU: {cu} (scroll=300x1)")
        sys.stdout.write("\n".join(lines) + "\n")
        cdir = _cache_dir(getattr(args, "cache_dir", None))
        _write_cache(cdir, run_id, {
            "runId": run_id, "kind": "junk-quick-test-v1", "cached": False,
            "cu_used_total": cu, "cu_breakdown": breakdown_cu,
            "params": envelope["params"], "snapshot_time": int(time.time()),
            "rendered_json": json.dumps(envelope, ensure_ascii=False),
            "rendered_ui": json.dumps(envelope, ensure_ascii=False),
            "rendered_raw-json": json.dumps(envelope, ensure_ascii=False),
            "rendered_rendered": json.dumps(envelope, ensure_ascii=False),
            "out": json.dumps(envelope, ensure_ascii=False),
        })
        sys.stdout.write(f"#RUN_ID {run_id}\tjunk-quick-test\tcu={cu}\n")
        return 0
    if fmt == "telegram":
        lines = [
            "🗑️ Junk Quick Test",
            f"Chain: {chain.upper()} · Sample: {pick_count}/{total}",
        ]
        if platform:
            lines.append(f"Platform: {platform}")
        lines.append(f"Flagged JUNK: {n_junk}/{len(results)}")
        for r in results[:20]:
            if r.get("error"):
                lines.append(f"• {r['address'][:16]}… → ERROR: {r['error']}")
                continue
            verdict = "🚫 JUNK" if r.get("is_junk") else "✅ OK"
            lines.append(
                f"• {r.get('name') or r.get('symbol') or r['address'][:12]} "
                f"({r.get('symbol') or '?'})\n"
                f"  Junk Probability: {r.get('junk_score', 0):.1f}/100 · {verdict}"
            )
        lines.append(f"⚡CU: {cu} ({', '.join(breakdown_cu)})")
        sys.stdout.write("\n".join(lines) + "\n")
        return 0

    # ── Rendered HTML ──
    def _fmt(v):
        if v is None:
            return "N/A"
        return _fmt_usd(v)

    def _fmt_int(v):
        if v is None:
            return "N/A"
        try:
            return f"{int(v):,}"
        except (ValueError, TypeError):
            return "N/A"

    def _fmt_pct(v):
        if v is None:
            return "N/A"
        sign = "+" if v > 0 else ""
        color = "#2ecc71" if v > 0 else ("#ef4444" if v < 0 else "#94a3b8")
        return f'<span style="color:{color};font-weight:700">{sign}{v:.2f}%</span>'

    def _junk_prob_color(score_value: float | int | None) -> str:
        score_value = 0.0 if score_value is None else float(score_value)
        if score_value < 25:
            return "#22c55e"  # green
        if score_value < 50:
            return "#facc15"  # yellow
        if score_value < 75:
            return "#fb923c"  # orange
        return "#ef4444"      # red

    cards_html = ""
    for r in results:
        if r.get("error"):
            cards_html += (f'<div style="background:#1a1a2e;border:1px solid #ef4444;border-radius:12px;padding:14px;margin-bottom:10px">'
                           f'<div style="font-weight:700;color:#ef4444">{r["address"][:16]}…</div>'
                           f'<div style="font-size:12px;color:#94a3b8;margin-top:4px">Error: {r["error"]}</div></div>')
            continue
        sym = r.get("symbol") or "?"
        name = r.get("name") or sym
        is_junk = r.get("is_junk", False)
        score = r.get("junk_score", 0) or 0
        score_color = _junk_prob_color(score)
        badge_color = "#ef4444" if is_junk else "#2ecc71"
        badge_text = "🚫 JUNK" if is_junk else "✅ OK"

        cards_html += f'''<div style="background:#171a21;border:1px solid {'#ef4444' if is_junk else '#262b36'};border-radius:12px;padding:14px;margin-bottom:10px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
    <div style="min-width:0">
      <div style="font-size:16px;font-weight:800;color:#e6e8ef;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:320px">{html.escape(name)} <span style="color:#8a93a6;font-weight:600;font-size:13px">${html.escape(sym)}</span></div>
      <div style="font-size:10px;color:#64748b;font-family:ui-monospace,monospace;margin-top:2px">{r["address"]}</div>
    </div>
    <div style="text-align:right;flex-shrink:0;margin-left:10px">
      <div style="font-size:26px;font-weight:900;color:{score_color}">{score:.1f}<span style="font-size:11px;color:#8a93a6">/100</span></div>
      <div style="display:inline-block;background:{badge_color};color:#000;font-weight:800;font-size:11px;padding:2px 10px;border-radius:999px;margin-top:3px">{badge_text}</div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:8px">
    <div style="background:#0f1115;border-radius:7px;padding:7px;text-align:center">
      <div style="font-size:9px;color:#8a93a6;text-transform:uppercase">MCap</div>
      <div style="font-size:13px;font-weight:700;color:#e6e8ef;margin-top:2px">{_fmt(r.get("mcap"))}</div>
    </div>
    <div style="background:#0f1115;border-radius:7px;padding:7px;text-align:center">
      <div style="font-size:9px;color:#8a93a6;text-transform:uppercase">FDV</div>
      <div style="font-size:13px;font-weight:700;color:#e6e8ef;margin-top:2px">{_fmt(r.get("fdv"))}</div>
    </div>
    <div style="background:#0f1115;border-radius:7px;padding:7px;text-align:center">
      <div style="font-size:9px;color:#8a93a6;text-transform:uppercase">Liquidity</div>
      <div style="font-size:13px;font-weight:700;color:#e6e8ef;margin-top:2px">{_fmt(r.get("liquidity"))}</div>
    </div>
    <div style="background:#0f1115;border-radius:7px;padding:7px;text-align:center">
      <div style="font-size:9px;color:#8a93a6;text-transform:uppercase">Vol 24h</div>
      <div style="font-size:13px;font-weight:700;color:#e6e8ef;margin-top:2px">{_fmt(r.get("vol_24h"))}</div>
    </div>
    <div style="background:#0f1115;border-radius:7px;padding:7px;text-align:center">
      <div style="font-size:9px;color:#8a93a6;text-transform:uppercase">Price</div>
      <div style="font-size:13px;font-weight:700;color:#e6e8ef;margin-top:2px">{('$' + format(r["price"], '.8g')) if r.get("price") is not None else 'N/A'}</div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px">
    <div style="background:#0f1115;border-radius:7px;padding:6px;text-align:center">
      <div style="font-size:9px;color:#8a93a6;text-transform:uppercase">Tx 24h</div>
      <div style="font-size:12px;font-weight:700;color:#e6e8ef;margin-top:2px">{_fmt_int(r.get("tx_24h"))}</div>
    </div>
    <div style="background:#0f1115;border-radius:7px;padding:6px;text-align:center">
      <div style="font-size:9px;color:#8a93a6;text-transform:uppercase">Holders</div>
      <div style="font-size:12px;font-weight:700;color:#e6e8ef;margin-top:2px">{_fmt_int(r.get("holder"))}</div>
    </div>
    <div style="background:#0f1115;border-radius:7px;padding:6px;text-align:center">
      <div style="font-size:9px;color:#8a93a6;text-transform:uppercase">Price Δ24h</div>
      <div style="font-size:12px;font-weight:700;margin-top:2px">{_fmt_pct(r.get("price_change_24h"))}</div>
    </div>
    <div style="background:#0f1115;border-radius:7px;padding:6px;text-align:center">
      <div style="font-size:9px;color:#8a93a6;text-transform:uppercase">Vol Δ24h</div>
      <div style="font-size:12px;font-weight:700;margin-top:2px">{_fmt_pct(r.get("volume_change_24h"))}</div>
    </div>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap">
    <div style="font-size:10px;background:#0f1115;padding:3px 9px;border-radius:999px;color:#94a3b8">listed: <span style="color:#e6e8ef;font-weight:700">{_dt.datetime.utcfromtimestamp(r["recent_listing_time"]).strftime("%Y-%m-%d") if r.get("recent_listing_time") else 'N/A'}</span></div>
  </div>
</div>'''

    if n_junk > 0:
        summary_badge = (f'<div style="background:#1a1a2e;border:1px solid #ef4444;border-radius:10px;padding:11px;margin-bottom:12px">'
                         f'<span style="color:#ef4444;font-weight:800">⚠ {n_junk}/{len(results)} token JUNK</span> '
                         f'(ngưỡng {threshold}/100) · scroll {total} tokens</div>')
    else:
        summary_badge = (f'<div style="background:#0f1f15;border:1px solid #2ecc71;border-radius:10px;padding:11px;margin-bottom:12px">'
                         f'<span style="color:#2ecc71;font-weight:800">✅ {len(results)}/{len(results)} token OK</span> '
                         f'(ngưỡng {threshold}/100) · scroll {total} tokens</div>')

    filter_info = ""
    parts = []
    if platform: parts.append(f"platform={platform}")
    if min_liq is not None: parts.append(f"liq≥{_fmt_usd(min_liq)}")
    if max_liq is not None: parts.append(f"liq≤{_fmt_usd(max_liq)}")
    if min_mcap is not None: parts.append(f"mcap≥{_fmt_usd(min_mcap)}")
    if max_mcap is not None: parts.append(f"mcap≤{_fmt_usd(max_mcap)}")
    if parts:
        filter_info = f'<div style="font-size:11px;color:#64748b;margin-bottom:10px">Filters: {", ".join(parts)} · sort_by={sort_by} {sort_type}</div>'

    html_out = (
        f'<div style="max-width:860px;margin:0 auto">'
        f'<div style="font-size:20px;font-weight:800;color:#e6e8ef;margin-bottom:3px">🗑️ Junk Quick Test</div>'
        f'<div style="font-size:12px;color:#8a93a6;margin-bottom:10px">{chain.upper()} · {pick_count} random / {total} tokens · ngưỡng {threshold}/100 · model: Logistic Regression (16 features) · data: /defi/v3/token/list/scroll</div>'
        f'{filter_info}'
        f'{summary_badge}'
        f'{cards_html}'
        f'<div style="font-size:10px;color:#475569;margin-top:8px">Note: trade_24h_count & holder used as proxies for tx_24h & uniqueWallet24h (list endpoint). For exact per-token data use junk-predict with --tokens.</div>'
        f'</div>'
    )
    envelope["html"] = html_out

    cdir = _cache_dir(getattr(args, "cache_dir", None))
    file_payload = {
        "runId": run_id, "kind": "junk-quick-test-v1", "cached": False,
        "cu_used_total": cu, "cu_breakdown": breakdown_cu,
        "params": envelope["params"], "snapshot_time": int(time.time()),
        "rendered_json": json.dumps(envelope, ensure_ascii=False),
        "rendered_ui": json.dumps(envelope, ensure_ascii=False),
        "rendered_raw-json": json.dumps(envelope, ensure_ascii=False),
        "rendered_rendered": json.dumps(envelope, ensure_ascii=False),
        "out": json.dumps(envelope, ensure_ascii=False),
    }
    _write_cache(cdir, run_id, file_payload)
    sys.stdout.write(f"#RUN_ID {run_id}\tjunk-quick-test\tcu={cu}\n")

    if fmt == "json":
        print(json.dumps(envelope, ensure_ascii=False))
        return 0

    print(json.dumps(envelope, ensure_ascii=False))
    return 0


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
