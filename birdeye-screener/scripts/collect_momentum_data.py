#!/usr/bin/env python3
"""
Momentum Data Collector — ONE-TIME historical data fetch for trending score analysis.

Collects all raw data needed to compute Token Trending Score (Skill #22) and saves
it to CSV files for offline / later analysis. This runs ONCE per token (no polling).

Data collected (all saved to ~/.cache/birdeye-trending-csv/):
  - 1m OHLCV candles  (from creation time, capped at 5000)
  - 1s OHLCV candles  (last 70 min, for 5m/15m/30m intervals)
  - Liquidity history (1m, from creation time)
  - Holder chart      (1m, 100 points)
  - Holder profile    (cohort tags + top holders)
  - Token security    (contract risk)
  - Token overview    (latest snapshot with money_flow)
  - Token creation info (blockUnixTime anchor)

Usage:
  python3 collect_momentum_data.py --chain sol --addresses ADDR1,ADDR2
  python3 collect_momentum_data.py --chain sol --source trending --limit 10
  python3 collect_momentum_data.py --chain sol --source new_listing --limit 20
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import requests

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from birdeye_cli import (  # noqa: E402
    _be, _load_key, CHAINS,
    _ts_csv_path, _ts_csv_fresh,
    _ts_save_ohlcv_csv, _ts_save_liq_csv, _ts_save_security_csv,
    _ts_save_holder_chart_csv, _ts_save_holder_profile_csv,
    _ts_load_ohlcv_csv, _ts_load_liq_csv, _ts_load_security_csv,
    _ts_load_holder_chart_csv, _ts_load_holder_profile_csv,
    _ohlcv_v3_cu,
)

MOMENTUM_CSV_DIR = Path.home() / ".cache" / "birdeye-trending-csv"


def fetch_new_listing(session, key, chain, limit=20):
    """Fetch newly listed tokens."""
    params = {"limit": min(limit, 20)}
    data, _ = _be(session, key, chain, "/defi/v2/tokens/new_listing", params)
    items = (data.get("data") or {}).get("items") or data.get("items") or []
    return [it for it in items if isinstance(it, dict)]


def fetch_trending_list(session, key, chain, limit=20):
    """Fetch trending tokens from v3 list sorted by 1h volume."""
    params = {
        "sort_by": "volume_1h_usd",
        "sort_type": "desc",
        "offset": 0,
        "limit": min(limit, 50),
        "min_volume_1h_usd": 100,
    }
    data, _ = _be(session, key, chain, "/defi/v3/token/list", params)
    items = (data.get("data") or {}).get("items") or data.get("items") or []
    return [it for it in items if isinstance(it, dict)]


def collect_token(session, key, chain, address, n_candles=5000, nocache=False) -> dict:
    """Collect ALL data for one token in a single pass. Returns CU breakdown."""
    cu = 0
    breakdown: dict[str, str] = {}

    # ── 1) Creation time (anchor for OHLCV / liquidity) ──
    creation_ts = None
    try:
        data, _ = _be(session, key, chain, "/defi/token_creation_info", {"address": address})
        creation_ts = (data.get("data") or {}).get("blockUnixTime")
        cu += 35
        breakdown["creation_info"] = "35"
    except RuntimeError:
        breakdown["creation_info"] = "FAIL"

    now = int(time.time())

    # ── 2) 1m OHLCV candles (from creation, capped) ──
    ohlcv_1m_fp = _ts_csv_path(chain, address, "ohlcv_1m")
    if not nocache and _ts_csv_fresh(ohlcv_1m_fp):
        candles_1m = _ts_load_ohlcv_csv(ohlcv_1m_fp)
        breakdown["ohlcv_1m"] = f"0(cached, {len(candles_1m)} pts)"
    else:
        time_from = max(creation_ts or 0, now - n_candles * 60) if creation_ts else now - n_candles * 60
        try:
            raw, _ = _be(session, key, chain, "/defi/v3/ohlcv", {
                "address": address, "type": "1m",
                "time_to": now, "time_from": time_from,
            })
            candles_1m = _extract_ohlcv(raw)
            step = _ohlcv_v3_cu(len(candles_1m))
            cu += step
            breakdown["ohlcv_1m"] = f"{step} ({len(candles_1m)} pts)"
            _ts_save_ohlcv_csv(chain, address, candles_1m)
        except RuntimeError:
            candles_1m = []
            breakdown["ohlcv_1m"] = "FAIL"

    # ── 3) 1s OHLCV candles (last 70 min) ──
    ohlcv_1s_fp = _ts_csv_path(chain, address, "ohlcv_1s")
    if not nocache and _ts_csv_fresh(ohlcv_1s_fp, max_age_hours=1.0):
        candles_1s = _ts_load_ohlcv_csv(ohlcv_1s_fp)
        breakdown["ohlcv_1s"] = f"0(cached, {len(candles_1s)} pts)"
    else:
        try:
            raw, _ = _be(session, key, chain, "/defi/v3/ohlcv", {
                "address": address, "type": "1s",
                "time_to": now, "time_from": now - 70 * 60,
            })
            candles_1s = _extract_ohlcv(raw)
            step = _ohlcv_v3_cu(len(candles_1s))
            cu += step
            breakdown["ohlcv_1s"] = f"{step} ({len(candles_1s)} pts)"
            _ts_save_ohlcv_csv(chain, address, candles_1s, kind="ohlcv_1s")
        except RuntimeError:
            candles_1s = []
            breakdown["ohlcv_1s"] = "FAIL"

    # ── 4) Liquidity history (1m) ──
    liq_fp = _ts_csv_path(chain, address, "liquidity_1m")
    if not nocache and _ts_csv_fresh(liq_fp):
        liq_1m = _ts_load_liq_csv(liq_fp)
        breakdown["liquidity"] = f"0(cached, {len(liq_1m)} pts)"
    else:
        time_from = max(creation_ts or 0, now - n_candles * 60) if creation_ts else now - n_candles * 60
        liq_1m = []
        for path in ["/defi/v3/liquidity/history/token", "/defi/v3/liquidity-ohlc-token"]:
            try:
                raw, _ = _be(session, key, chain, path, {
                    "address": address, "type": "1m",
                    "time_to": now, "time_from": time_from,
                })
                liq_1m = _extract_liq(raw)
                cu += 20
                breakdown["liquidity"] = f"20 ({len(liq_1m)} pts)"
                _ts_save_liq_csv(chain, address, liq_1m)
                break
            except RuntimeError:
                continue
        if not liq_1m:
            breakdown["liquidity"] = "FAIL"

    # ── 5) Holder chart (1m, 100 points) ──
    hc_fp = _ts_csv_path(chain, address, "holder_chart")
    if not nocache and _ts_csv_fresh(hc_fp, max_age_hours=1.0):
        holder_chart = _ts_load_holder_chart_csv(hc_fp)
        breakdown["holder_chart"] = f"0(cached, {len(holder_chart)} pts)"
    else:
        try:
            raw, _ = _be(session, key, chain, "/token/v1/holder/chart", {
                "token_address": address, "chart_type": "1m",
                "count": 100, "mode": "padding",
            })
            holder_chart = (raw.get("data") if isinstance(raw, dict) else []) or []
            cu += 30
            breakdown["holder_chart"] = f"30 ({len(holder_chart)} pts)"
            _ts_save_holder_chart_csv(chain, address, holder_chart)
        except RuntimeError:
            holder_chart = []
            breakdown["holder_chart"] = "FAIL"

    # ── 6) Holder profile ──
    hp_fp = _ts_csv_path(chain, address, "holder_profile")
    if not nocache and _ts_csv_fresh(hp_fp, max_age_hours=24.0):
        holder_profile = _ts_load_holder_profile_csv(hp_fp)
        breakdown["holder_profile"] = "0(cached)"
    else:
        try:
            raw, _ = _be(session, key, chain, "/token/v1/holder-profile", {
                "token_address": address, "limit": 100,
            })
            holder_profile = (raw.get("data") if isinstance(raw, dict) else {}) or {}
            cu += 21
            breakdown["holder_profile"] = "21"
            _ts_save_holder_profile_csv(chain, address, holder_profile)
        except RuntimeError:
            holder_profile = {}
            breakdown["holder_profile"] = "FAIL"

    # ── 7) Token security ──
    sec_fp = _ts_csv_path(chain, address, "security")
    if not nocache and _ts_csv_fresh(sec_fp):
        secd = _ts_load_security_csv(sec_fp)
        breakdown["security"] = "0(cached)"
    else:
        try:
            raw, _ = _be(session, key, chain, "/defi/token_security", {"address": address})
            secd = (raw.get("data") if isinstance(raw, dict) else {}) or {}
            cu += 30
            breakdown["security"] = "30"
            _ts_save_security_csv(chain, address, secd)
        except RuntimeError:
            secd = {}
            breakdown["security"] = "FAIL"

    # ── 8) Token overview (latest snapshot) ──
    try:
        raw, _ = _be(session, key, chain, "/defi/token_overview",
                     {"address": address, "includes": "money_flow"})
        ovd = (raw.get("data") if isinstance(raw, dict) else {}) or {}
        cu += 21
        breakdown["overview"] = "21"
        _save_overview_json(chain, address, ovd)
    except RuntimeError:
        ovd = {}
        breakdown["overview"] = "FAIL"

    return {
        "address": address,
        "symbol": ovd.get("symbol") or "?",
        "creation_ts": creation_ts,
        "n_ohlcv_1m": len(candles_1m),
        "n_ohlcv_1s": len(candles_1s),
        "n_liq": len(liq_1m),
        "n_holder_chart": len(holder_chart),
        "holder_profile": bool(holder_profile),
        "security": bool(secd),
        "overview": bool(ovd),
        "total_cu": cu,
        "breakdown": breakdown,
    }


def _extract_ohlcv(raw: dict) -> list[dict]:
    """Extract OHLCV items from v3 response."""
    data = raw.get("data") or {}
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "t": it.get("unix_time") or it.get("t"),
            "o": it.get("o"), "h": it.get("h"), "l": it.get("l"),
            "c": it.get("c"), "v": it.get("v"), "v_usd": it.get("vUsd") or it.get("v_usd"),
        })
    return out


def _extract_liq(raw: dict) -> list[dict]:
    """Extract liquidity history items from v3 response."""
    data = raw.get("data") or {}
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "t": it.get("unix_time") or it.get("t"),
            "liq": it.get("liquidity") or it.get("liq") or it.get("v"),
        })
    return out


def _save_overview_json(chain: str, address: str, ovd: dict) -> None:
    """Save token overview as JSON for later analysis."""
    MOMENTUM_CSV_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in address[:40])
    fp = MOMENTUM_CSV_DIR / f"{chain}_{safe}_overview.json"
    with fp.open("w", encoding="utf-8") as f:
        json.dump(ovd, f, indent=2, default=str)


def main():
    p = argparse.ArgumentParser(description="One-time collect trending-score raw data to CSV")
    p.add_argument("--chain", default="sol")
    p.add_argument("--source", default="new_listing",
                   choices=["new_listing", "trending", "addresses"])
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--candles", type=int, default=5000, help="max 1m candles to fetch")
    p.add_argument("--nocache", action="store_true", help="force re-fetch, ignore cache")
    p.add_argument("--addresses", default="", help="comma-separated token addresses")
    args = p.parse_args()

    key = _load_key()
    if not key:
        sys.stderr.write("Missing BIRDEYE_API_KEY\n")
        return 2

    chain = args.chain
    with requests.Session() as s:
        if args.source == "new_listing":
            tokens = fetch_new_listing(s, key, chain, args.limit)
            print(f"Fetched {len(tokens)} new-listing tokens")
        elif args.source == "trending":
            tokens = fetch_trending_list(s, key, chain, args.limit)
            print(f"Fetched {len(tokens)} trending tokens")
        else:
            addrs = [a.strip() for a in args.addresses.split(",") if a.strip()]
            tokens = [{"address": a} for a in addrs]
            print(f"Using {len(tokens)} provided addresses")

        if not tokens:
            print("No tokens to collect")
            return 1

        for i, tok in enumerate(tokens, 1):
            addr = tok.get("address")
            sym = tok.get("symbol", "?")
            print(f"\n[{i}/{len(tokens)}] {sym} ({addr[:16]}…)")
            result = collect_token(s, key, chain, addr, args.candles, args.nocache)
            print(f"  symbol={result['symbol']}  creation_ts={result['creation_ts']}")
            print(f"  ohlcv_1m={result['n_ohlcv_1m']}  ohlcv_1s={result['n_ohlcv_1s']}  "
                  f"liq={result['n_liq']}  holder_chart={result['n_holder_chart']}  "
                  f"profile={result['holder_profile']}  sec={result['security']}  "
                  f"overview={result['overview']}")
            print(f"  CU: {result['total_cu']}  ({', '.join(f'{k}={v}' for k, v in result['breakdown'].items())})")

    print(f"\nDone. Data saved to {MOMENTUM_CSV_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
