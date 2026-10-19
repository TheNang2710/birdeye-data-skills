#!/usr/bin/env python3
"""Birdeye Token Trending — SIMPLE / CU-efficient version (Version B).

Single endpoint only: GET /defi/token_trending  (30 CU / call).

WHEN TO USE THIS (not birdeye_screener.py):
  - You want the lightest possible CU cost per scan.
  - You don't need platform filters, numeric min/max filters, sort by
    holder/trade_count, or dev-holding / smart-money / buy-imbalance signals.
  - You only need the core dashboard: market cap, liquidity, volume,
    price change %, ranked by volumeUSD / liquidity / trending rank.

WHEN TO SWITCH BACK TO birdeye_screener.py (Version A):
  - "filter by pump.fun / filter by market cap / filter by holder count"
  - "sort by trade count or holder"
  - "show dev holding share / smart money / bundle ratio"

Cost per call: always 30 CU.
Supported chains: sol / bsc / base / eth.
Supported intervals: 1h / 4h / 24h.
Supported sort: volumeUSD / liquidity / rank.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

BIRDEYE_BASE = "https://public-api.birdeye.so"
CHAINS = {"sol": "solana", "bsc": "bsc", "base": "base", "eth": "ethereum", "arc": "arbitrum", "robinhood": "robinhood"}
INTERVALS = ["1h", "4h", "24h"]
CU_CALL = 30  # Birdeye published CU for /defi/token_trending

# Key loader — reuses the same locations as birdeye_screener.py so a single
# `config --apply` feeds both scripts.
CONFIG_DIR = Path.home() / ".config" / "birdeye"
ENV_FILE = CONFIG_DIR / ".env"
LOCAL_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
HOME_ALT_ENV = Path.home() / ".birdeye.env"


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


def _fmt(v, nd=0):
    if v is None:
        return "N/A"
    if not isinstance(v, (int, float)):
        return str(v)
    if v == 0:
        return "0"
    sign = "-" if v < 0 else ""
    av = abs(v)
    suf = ""
    if av >= 1e9:
        av /= 1e9
        suf = "B"
    elif av >= 1e6:
        av /= 1e6
        suf = "M"
    elif av >= 1e3:
        av /= 1e3
        suf = "K"
    if nd == 0:
        return f"{sign}{av:.1f}{suf}" if suf else f"{sign}{av:.0f}"
    return f"{sign}{av:.{nd}f}{suf}"


def cmd_trending(args):
    key = _load_key()
    if not key:
        print("[trending] No BIRDEYE_API_KEY found. Configure via birdeye_screener.py config --apply <KEY> or export env var.")
        return 1
    t0 = time.perf_counter()
    try:
        r = requests.get(
            f"{BIRDEYE_BASE}/defi/token_trending",
            headers={"X-API-KEY": key, "x-chain": CHAINS[args.chain]},
            params={
                "sort_by": args.sort_by,
                "offset": args.offset,
                "limit": args.limit,
                "interval": args.interval,
            },
            timeout=20,
        )
    except Exception as e:
        print(f"[E] network error: {e}")
        return 2
    if r.status_code != 200:
        prefix = {401: "[E401] Unauthorized — bad key.",
                  403: "[E403] Forbidden — tier/route blocked.",
                  429: "[E429] Rate-limited — slow down.",
                  500: "[E500] Birdeye upstream error."}
        print(f"{prefix.get(r.status_code, f'[E{r.status_code}]')}  {r.text[:200]}")
        return 2
    data = r.json()
    if not data.get("success"):
        print(f"[E] success=false: {data}")
        return 2
    d = data["data"]
    tokens = d.get("tokens") or []
    total = d.get("total", 0)
    update_iso = d.get("updateTime") or ""
    ms = int((time.perf_counter() - t0) * 1000)

    iv = args.interval
    vol_k = f"volume{iv}USD"
    vold_k = f"volume{iv}ChangePercent"
    prcd_k = f"price{iv}ChangePercent"

    # Pipeline gap detection — documented per user's transparency preference.
    # Birdeye upstream `sort_by=volumeUSD` can return rows where the
    # interval-specific volume field is ~$1e-9 (effectively zero). If this
    # happens to the majority of the batch, we fall back to client-side
    # `marketcap desc` sort and flag it.
    sort_note = ""
    if args.sort_by == "volumeUSD":
        non_zero_vols = [float(t[vol_k]) for t in tokens if isinstance(t.get(vol_k), (int, float)) and float(t.get(vol_k)) > 1.0]
        if len(non_zero_vols) * 2 < len(tokens):
            tokens = sorted(tokens, key=lambda t: float(t.get("marketcap") or 0), reverse=True)
            sort_note = (
                f"  ⚠ pipeline_gap: Birdeye upstream volumeUSD sort returned mostly "
                f"{iv}-volume < $1; fell back to client-side marketcap desc."
            )
    elif args.sort_by == "liquidity":
        # Sort client-side by liquidity for determinism (upstream rank!=liquidity order sometimes)
        tokens = sorted(tokens, key=lambda t: float(t.get("liquidity") or 0), reverse=True)

    if args.raw:
        rows = []
        for t in tokens:
            rows.append({
                "rank": t.get("rank"),
                "address": t.get("address"),
                "symbol": t.get("symbol"),
                "name": t.get("name"),
                "marketcap": t.get("marketcap"),
                "liquidity": t.get("liquidity"),
                "fdv": t.get("fdv"),
                "price": t.get("price"),
                vol_k: t.get(vol_k),
                vold_k: t.get(vold_k),
                prcd_k: t.get(prcd_k),
            })
        out = {
            "rows": rows, "cu_used_total": CU_CALL, "latency_ms": ms,
            "snapshot_time": update_iso, "total_tokens": total,
            "chain": args.chain, "interval": args.interval, "sort_by": args.sort_by,
            "sort_note": sort_note,
        }
        print(json.dumps(out))
        return 0

    # --- Human table ---
    cols = [
        ("#", 4), ("SYMBOL", 12), ("MCAP", 10), ("LIQ", 10),
        (f"VOL({iv})", 12), (f"ΔVOL%", 9), (f"ΔPRICE%", 10), ("PRICE", 12),
    ]
    header = " ".join(c.ljust(w) for c, w in cols)
    print(header)
    print("-" * (sum(w for _, w in cols) + len(cols) - 1))
    for i, t in enumerate(tokens, 1):
        rnk = t.get("rank")
        sym = t.get("symbol", "")[:11]
        mc = _fmt(t.get("marketcap"), nd=1)
        liq = _fmt(t.get("liquidity"), nd=1)
        v_raw = t.get(vol_k)
        vol = _fmt(float(v_raw) if isinstance(v_raw, (int, float)) else None, nd=2)
        vold_raw = t.get(vold_k)
        vold = f"{float(vold_raw):+.1f}%" if isinstance(vold_raw, (int, float)) else "N/A"
        prcd_raw = t.get(prcd_k)
        prcd = f"{float(prcd_raw):+.1f}%" if isinstance(prcd_raw, (int, float)) else "N/A"
        prc = t.get("price")
        price_s = f"${prc:.6f}" if isinstance(prc, (int, float)) and prc < 1 else (f"${prc:.2f}" if isinstance(prc, (int, float)) else "N/A")
        parts = [
            f"{rnk if rnk is not None else i}".rjust(3).ljust(4),
            sym.ljust(12),
            mc.ljust(10),
            liq.ljust(10),
            vol.ljust(12),
            vold.rjust(8).ljust(9),
            prcd.rjust(9).ljust(10),
            price_s.ljust(12),
        ]
        print(" ".join(parts))

    # Footer — always visible for CU transparency (per user preference)
    print(f"\n⚡CU: {CU_CALL} (fixed /defi/token_trending) | ⏱{ms}ms | 📸{update_iso}")
    print(f"ℹ Chain={args.chain.upper()}  Interval={args.interval}  "
          f"Upstream_sort={args.sort_by}  Rows_shown={len(tokens)}/{total}")
    if sort_note:
        print(sort_note)


def build_parser():
    p = argparse.ArgumentParser(prog="birdeye_trending_simple", description=__doc__)
    p.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    p.add_argument("--interval", choices=INTERVALS, default="1h")
    p.add_argument("--sort-by", choices=["volumeUSD", "liquidity", "rank"], default="volumeUSD",
                   help="Birdeye /defi/token_trending sort enum only. "
                        "(No holder or trade_count here — use Version A for those.)")
    p.add_argument("--limit", type=int, default=30, choices=range(1, 101), metavar="1-100")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--raw", action="store_true", help="Emit single-line JSON for piping.")
    p.set_defaults(func=cmd_trending)
    return p


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
