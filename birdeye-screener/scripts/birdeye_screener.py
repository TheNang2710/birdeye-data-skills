#!/usr/bin/env python3
"""Birdeye Token Screener CLI.

Entrypoint used by the birdeye-screener Trae skill. Always call through this
script — never use curl/WebFetch directly. The script handles key management,
CU accounting, pipeline-gap invariants, and formatted output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

BIRDEYE_BASE = "https://public-api.birdeye.so"
CHAINS = {"sol": "solana", "bsc": "bsc", "base": "base", "eth": "ethereum", "arc": "arbitrum", "robinhood": "robinhood"}
WINDOWS = ["1m", "5m", "30m", "1h", "4h", "24h"]

# Birdeye published CU costs per endpoint. Keep in sync with SKILL.md.
CU = {
    "token_list_v3": 50,
    "token_security": 30,
    "token_overview": 18,
    "smart_money_list": 20,
}

CONFIG_DIR = Path.home() / ".config" / "birdeye"
ENV_FILE = CONFIG_DIR / ".env"
# Fallback location when ~/.config is sandbox-restricted (e.g. Trae default sandbox).
# Always: try ~/.config first; if that fails use the skill-local env path.
# The loader checks both; the saver tries ~/.config then falls back.
LOCAL_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _iter_env_files() -> Iterable[Path]:
    """Ordered list of env files the loader will try, first match wins."""
    candidates = [ENV_FILE]
    # Home-relative fallback when Path.home()/.config is not writable but
    # Path.home() is. Avoids hitting the sandbox on every load.
    alt = Path.home() / ".birdeye.env"
    candidates.append(alt)
    candidates.append(LOCAL_ENV_FILE)
    return candidates


# ---------------------------------------------------------------------------
# Config / key management
# ---------------------------------------------------------------------------


def _load_key_from_env() -> Optional[str]:
    key = os.environ.get("BIRDEYE_API_KEY")
    if key:
        return key.strip() or None
    for candidate in _iter_env_files():
        if not candidate.exists():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("BIRDEYE_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
                if k:
                    return k
    return None


def _try_write_env(target: Path, key: str) -> bool:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    try:
        if target.exists():
            existing = target.read_text().splitlines()
            replaced = False
            lines = []
            for ln in existing:
                if ln.strip().startswith("BIRDEYE_API_KEY="):
                    lines.append(f"BIRDEYE_API_KEY={key}")
                    replaced = True
                else:
                    lines.append(ln)
            if not replaced:
                lines.append(f"BIRDEYE_API_KEY={key}")
            target.write_text("\n".join(lines) + "\n")
        else:
            target.write_text(f"BIRDEYE_API_KEY={key}\n")
        try:
            os.chmod(target, 0o600)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _save_key(key: str) -> Path:
    """Write the key to the first writable env location. Returns path used, or raises RuntimeError."""
    for candidate in _iter_env_files():
        if _try_write_env(candidate, key):
            return candidate
    raise RuntimeError("Could not write API key to any config location (~/.config/birdeye/.env, ~/.birdeye.env, or skill-local .env).")


def _verify_key(key: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            f"{BIRDEYE_BASE}/defi/v3/token/list",
            headers={"X-API-KEY": key, "x-chain": "solana"},
            params={"sort_by": "liquidity", "sort_type": "desc", "limit": 1},
            timeout=15,
        )
    except Exception as e:
        return False, f"network error: {e}"
    if r.status_code == 200:
        return True, "ok"
    if r.status_code == 401:
        return False, "invalid key (401)"
    if r.status_code == 403:
        return False, "forbidden / plan tier blocked (403)"
    return False, f"upstream {r.status_code}"


def cmd_config(args: argparse.Namespace) -> int:
    if args.check:
        key = _load_key_from_env()
        if not key:
            print("[config] No BIRDEYE_API_KEY found. Provide it via:")
            print(f"  {sys.argv[0]} config --apply <YOUR_KEY>")
            print("Or set env var BIRDEYE_API_KEY before running.")
            return 1
        ok, msg = _verify_key(key)
        masked = key[:6] + "…" + key[-4:] if len(key) > 10 else "***"
        if ok:
            print(f"[config] key={masked} verified — {msg}")
            return 0
        print(f"[config] key={masked} present but FAILED verification — {msg}")
        return 1

    if args.apply:
        ok, msg = _verify_key(args.apply)
        if not ok:
            print(f"[config] key verification failed before save — {msg}")
            print("[config] Refusing to save a non-working key. Confirm key or try again.")
            return 1
        saved_path = _save_key(args.apply)
        masked = args.apply[:6] + "…" + args.apply[-4:] if len(args.apply) > 10 else "***"
        print(f"[config] Saved key={masked} to {saved_path} (mode 0600)")
        return 0

    # Bare `config` — show current status
    key = _load_key_from_env()
    if key:
        masked = key[:6] + "…" + key[-4:] if len(key) > 10 else "***"
        ok, msg = _verify_key(key)
        print(f"[config] key present: {masked} | verify: {ok} ({msg})")
        # Report candidate env files that actually exist
        existing = [str(p) for p in _iter_env_files() if p.exists()]
        print(f"[config] env_file(s): {', '.join(existing) if existing else '(none on disk — using env var)'}")
    else:
        print("[config] no key configured.")
        print(f"[config] save with: {sys.argv[0]} config --apply <YOUR_KEY>")
        print(f"[config] or export BIRDEYE_API_KEY=<YOUR_KEY>")
    return 0


# ---------------------------------------------------------------------------
# HTTP helpers with consistent error format
# ---------------------------------------------------------------------------


@dataclass
class HttpError(Exception):
    status: int
    body: str

    def pretty(self) -> str:
        prefix = {
            401: "[E401] Birdeye rejected the API key (Unauthorized).",
            403: "[E403] Key valid but route/chain blocked by plan tier (Forbidden).",
            429: "[E429] Birdeye rate-limited (Too Many Requests).",
            500: "[E500] Birdeye upstream error.",
        }.get(self.status, f"[E{self.status}]")
        return f"{prefix} Upstream: {self.body[:200]}"


def be_get(key: str, path: str, *, chain: str, params: dict[str, Any]) -> tuple[dict, dict[str, str]]:
    headers = {"X-API-KEY": key, "x-chain": chain}
    r = requests.get(f"{BIRDEYE_BASE}{path}", headers=headers, params=params, timeout=20)
    if r.status_code != 200:
        raise HttpError(r.status_code, r.text)
    try:
        data = r.json()
    except Exception as e:
        raise HttpError(0, f"non-json response: {e}")
    return data, dict(r.headers)


# ---------------------------------------------------------------------------
# Core scan pipeline
# ---------------------------------------------------------------------------


@dataclass
class ScanRow:
    # MVP fields
    address: str
    symbol: str
    name: str
    market_cap: float
    liquidity: float
    volume: float
    trade_count: int
    holder: int
    price_change_pct: float
    price: float
    fdv: float
    platform_name: Optional[str]
    last_trade_unix_time: Optional[int]
    recent_listing_unix_time: Optional[int]
    # Hydrate fields (optional)
    dev_hold_pct: Optional[float] = None
    top10_holder_pct: Optional[float] = None
    smart_money_count: Optional[int] = None
    buy_imbalance_ratio: Optional[float] = None
    unique_wallet_5m: Optional[int] = None
    # Audit
    pipeline_gaps: list[str] = field(default_factory=list)


def _safe(d: dict, *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _fetch_token_list(key: str, params: "ScanArgs") -> tuple[list[dict], str, dict[str, Any]]:
    """Return (items, snapshot_iso, extra_meta). Consumes 50 CU."""
    be_window = params.window  # already in Birdeye suffix format (e.g. "5m")
    sort_map = {
        "volume": f"volume_{be_window}_usd",
        "market_cap": "market_cap",
        "trade_count": f"trade_{be_window}_count",
        "holder": "holder",
    }
    q: dict[str, Any] = {
        "sort_by": sort_map[params.sort_by],
        "sort_type": params.direction,
        "limit": params.limit,
        "offset": params.offset,
    }
    if params.platform:
        q["platform_name"] = params.platform
    if params.min_market_cap is not None:
        q["min_market_cap"] = params.min_market_cap
    if params.max_market_cap is not None:
        q["max_market_cap"] = params.max_market_cap
    if params.min_liquidity is not None:
        q["min_liquidity"] = params.min_liquidity
    if params.max_liquidity is not None:
        q["max_liquidity"] = params.max_liquidity
    if params.min_volume is not None:
        q[f"min_volume_{be_window}_usd"] = params.min_volume
    if params.min_price_change_pct is not None:
        q[f"min_price_change_{be_window}_percent"] = params.min_price_change_pct
    if params.min_trade_count is not None:
        q[f"min_trade_{be_window}_count"] = params.min_trade_count
    if params.min_holder is not None:
        q["min_holder"] = params.min_holder

    resp, _ = be_get(key, "/defi/v3/token/list", chain=CHAINS[params.chain], params=q)
    data = resp.get("data") or {}
    items = data.get("items") or []
    # Birdeye upstream does not always include updateTime (e.g. current production
    # v3 returns items+has_next only). Per the skill's transparency rule, always
    # date-stamp with something; use upstream first, else the current local time.
    snapshot_iso = (
        data.get("updateTime")
        or data.get("update_time")
        or data.get("generated_at")
        or ""
    )
    if not snapshot_iso:
        import datetime as _dt
        snapshot_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + " (local-generated, no upstream timestamp)"
    return items, snapshot_iso, data


def _to_mvp_rows(items: Iterable[dict], snapshot_iso: str, window: str) -> list[ScanRow]:
    rows: list[ScanRow] = []
    vol_key = f"volume{window}_usd" if window else "volume24h_usd"
    # Birdeye naming: volume_5m_usd in sort; payload has volume5mUsd snake/camel? Use fuzzy lookup.
    for it in items:
        # Try various plausible keys
        def v(patterns: list[str]) -> Any:
            for p in patterns:
                if p in it and it[p] is not None:
                    return it[p]
            return None

        vol = v([
            f"volume_{window}_usd", f"volume{window}Usd",
            f"volume{window.replace('m','M').replace('h','H').replace('d','D')}USD",
            "volume24hUSD", "volume24h_usd",
        ])
        trades = v([
            f"trade_{window}_count", f"trade{window}Count",
            f"trade{window}_count", "trade24hCount", "trade24h_count",
        ])
        pc = v([
            f"price_change_{window}_percent", f"priceChange{window}Percent",
            f"price{window}ChangePercent",
            "price24hChangePercent", "price_change_24h_percent",
        ])
        holder = v(["holder", "holderCount", "holder_count"])
        mc = v(["market_cap", "marketCap", "mc"])
        liq = v(["liquidity"])
        price = v(["price"])
        fdv = v(["fdv"])
        symbol = v(["symbol"]) or ""
        name = v(["name"]) or ""
        address = v(["address"]) or ""
        platform = v(["platform_name", "platform"])
        last_trade = v(["last_trade_unix_time", "lastTradeUnixTime"])
        list_time = v(["recent_listing_time", "recent_listing_unix_time", "listingTime"])

        row = ScanRow(
            address=str(address),
            symbol=str(symbol),
            name=str(name),
            market_cap=float(mc) if mc is not None else 0.0,
            liquidity=float(liq) if liq is not None else 0.0,
            volume=float(vol) if vol is not None else 0.0,
            trade_count=int(trades) if trades is not None else 0,
            holder=int(holder) if holder is not None else 0,
            price_change_pct=float(pc) if pc is not None else 0.0,
            price=float(price) if price is not None else 0.0,
            fdv=float(fdv) if fdv is not None else 0.0,
            platform_name=str(platform) if platform else None,
            last_trade_unix_time=int(last_trade) if last_trade else None,
            recent_listing_unix_time=int(list_time) if list_time else None,
        )
        # MVP invariants
        gaps: list[str] = []
        if row.market_cap < 0 or row.liquidity < 0 or row.volume < 0:
            gaps.append("neg_value")
        if row.fdv and row.market_cap and row.market_cap > row.fdv * 1.01:
            gaps.append("mc_gt_fdv")
        if row.holder == 0 and row.trade_count > 0:
            gaps.append("holder0_trade>0")
        row.pipeline_gaps = gaps
        rows.append(row)
    return rows


def _hydrate_security(key: str, chain: str, addr: str) -> tuple[Optional[float], Optional[float]]:
    """Returns (dev_hold_pct, top10_holder_pct) or (None, None) on failure. 30 CU."""
    try:
        resp, _ = be_get(key, "/defi/token_security", chain=CHAINS[chain], params={"address": addr})
    except HttpError:
        return None, None
    d = (resp or {}).get("data") or {}
    cp = d.get("creatorPercentage")
    top10 = d.get("top10UserPercent") or d.get("top10HolderPercent")
    pct1 = float(cp) * 100 if isinstance(cp, (int, float)) else None
    pct2 = float(top10) * 100 if isinstance(top10, (int, float)) else None
    return pct1, pct2


def _hydrate_overview(key: str, chain: str, addr: str) -> tuple[Optional[float], Optional[int]]:
    """Returns (buy_imbalance_ratio, unique_wallet_5m) or (None, None) on failure. 18 CU."""
    try:
        resp, _ = be_get(
            key, "/defi/token_overview",
            chain=CHAINS[chain],
            params={"address": addr, "frames": "5m"},
        )
    except HttpError:
        return None, None
    d = (resp or {}).get("data") or {}

    def g(*keys: str) -> Any:
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return None

    buys = g("buy5m", "buy_5m", "tradeBuy5m")
    sells = g("sell5m", "sell_5m", "tradeSell5m")
    uw = g("uniqueWallet5m", "unique_wallet_5m")
    if isinstance(buys, (int, float)) and isinstance(sells, (int, float)):
        total = float(buys) + float(sells)
        ratio = float(buys) / total if total > 0 else None
    else:
        ratio = None
    u5 = int(uw) if isinstance(uw, (int, float)) else None
    return ratio, u5


def _fetch_smart_money_map(key: str, chain: str) -> dict[str, int]:
    """20 CU batch. Returns {address: smart_traders_no} for top SM-ranked tokens."""
    try:
        resp, _ = be_get(
            key, "/smart-money/v1/token/list",
            chain=CHAINS[chain],
            params={
                "interval": "1d",
                "sort_by": "smart_traders_no",
                "sort_type": "desc",
                "limit": 100,
            },
        )
    except HttpError:
        return {}
    arr = (resp or {}).get("data") or []
    m: dict[str, int] = {}
    for r in arr:
        addr = r.get("token") or r.get("address")
        n = r.get("smart_traders_no")
        if addr and isinstance(n, int):
            m[str(addr)] = n
    return m


@dataclass
class ScanArgs:
    chain: str
    window: str
    sort_by: str
    direction: str
    limit: int
    offset: int
    platform: Optional[str]
    min_market_cap: Optional[float]
    max_market_cap: Optional[float]
    min_liquidity: Optional[float]
    max_liquidity: Optional[float]
    min_volume: Optional[float]
    min_price_change_pct: Optional[float]
    min_trade_count: Optional[int]
    min_holder: Optional[int]
    hydrate: str
    min_smart_money: Optional[int]
    max_dev_hold_pct: Optional[float]
    min_buy_ratio: Optional[float]
    raw: bool


def cmd_scan(args: argparse.Namespace) -> int:
    key = _load_key_from_env()
    if not key:
        print("[scan] No API key configured. Run: screener config --apply <KEY>")
        return 1
    t0 = time.perf_counter()
    sa = ScanArgs(
        chain=args.chain, window=args.window, sort_by=args.sort_by,
        direction=args.direction, limit=args.limit, offset=args.offset,
        platform=args.platform,
        min_market_cap=args.min_market_cap, max_market_cap=args.max_market_cap,
        min_liquidity=args.min_liquidity, max_liquidity=args.max_liquidity,
        min_volume=args.min_volume, min_price_change_pct=args.min_price_change_pct,
        min_trade_count=args.min_trade_count, min_holder=args.min_holder,
        hydrate=args.hydrate,
        min_smart_money=args.min_smart_money,
        max_dev_hold_pct=args.max_dev_hold_pct,
        min_buy_ratio=args.min_buy_ratio,
        raw=args.raw,
    )
    try:
        items, snapshot_iso, meta = _fetch_token_list(key, sa)
    except HttpError as e:
        print(e.pretty())
        return 2
    cu_used = CU["token_list_v3"]
    rows = _to_mvp_rows(items, snapshot_iso, sa.window)

    # Hydrate pass
    if sa.hydrate != "off":
        if sa.hydrate == "top10":
            hyd_n = min(10, len(rows))
        elif sa.hydrate == "top20":
            hyd_n = min(20, len(rows))
        else:  # all
            hyd_n = len(rows)

        # Smart money batch first (20 CU, once)
        sm_map: dict[str, int] = {}
        if (sa.min_smart_money is not None) or (hyd_n > 0):
            sm_map = _fetch_smart_money_map(key, sa.chain)
            cu_used += CU["smart_money_list"]

        for i in range(hyd_n):
            r = rows[i]
            # Security (30 CU)
            if (sa.max_dev_hold_pct is not None) or True:  # always when hydrating
                dev_pct, top10_pct = _hydrate_security(key, sa.chain, r.address)
                cu_used += CU["token_security"]
                r.dev_hold_pct = dev_pct
                r.top10_holder_pct = top10_pct
                if dev_pct is not None and top10_pct is not None:
                    if dev_pct + top10_pct > 105:
                        r.pipeline_gaps.append("dev+top10>105")
            # Overview (18 CU)
            ratio, u5 = _hydrate_overview(key, sa.chain, r.address)
            cu_used += CU["token_overview"]
            r.buy_imbalance_ratio = ratio
            r.unique_wallet_5m = u5
            # Smart money join
            if r.address in sm_map:
                r.smart_money_count = sm_map[r.address]

        # Client-side filters for hydrate-only fields
        before = len(rows)
        filtered: list[ScanRow] = []
        for r in rows:
            if sa.min_smart_money is not None:
                if r.smart_money_count is None or r.smart_money_count < sa.min_smart_money:
                    continue
            if sa.max_dev_hold_pct is not None:
                if r.dev_hold_pct is None or r.dev_hold_pct > sa.max_dev_hold_pct:
                    continue
            if sa.min_buy_ratio is not None:
                if r.buy_imbalance_ratio is None or r.buy_imbalance_ratio < sa.min_buy_ratio:
                    continue
            filtered.append(r)
        rows = filtered

    latency_ms = int((time.perf_counter() - t0) * 1000)

    # Output
    if sa.raw:
        out = {
            "rows": [asdict(r) for r in rows],
            "snapshot_time": snapshot_iso,
            "cu_used_total": cu_used,
            "latency_ms": latency_ms,
            "fetched": len(items),
        }
        print(json.dumps(out))
        return 0

    _print_human_table(rows, snapshot_iso, cu_used, latency_ms, sa)
    return 0


def _fmt_num(v: Optional[float], *, digits: int = 0) -> str:
    if v is None:
        return "N/A"
    if v == 0:
        return "0"
    sign = "-" if v < 0 else ""
    av = abs(v)
    suf = ""
    if av >= 1e9:
        av /= 1e9; suf = "B"
    elif av >= 1e6:
        av /= 1e6; suf = "M"
    elif av >= 1e3:
        av /= 1e3; suf = "K"
    if digits == 0:
        return f"{sign}{av:.1f}{suf}" if suf else f"{sign}{av:.0f}"
    return f"{sign}{av:.{digits}f}{suf}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:+.1f}%"


def _print_human_table(rows: list[ScanRow], snap: str, cu: int, ms: int, sa: ScanArgs) -> None:
    # Define (header, width) pairs so we can iterate cleanly.
    mvp_cols: list[tuple[str, int]] = [
        ("#", 3),
        ("SYMBOL", 12),
        ("MCAP", 10),
        ("LIQ", 10),
        (f"VOL({sa.window})", 12),
        ("TRADES", 9),
        ("HOLD", 10),
        (f"Δ{sa.window}", 10),
        ("PRICE", 11),
    ]
    hyd_cols: list[tuple[str, int]] = [
        ("DEV%", 6),
        ("SM#", 6),
        ("BUY%", 7),
    ]
    cols = mvp_cols + (hyd_cols if sa.hydrate != "off" else [])
    header = " ".join(name.ljust(w) for name, w in cols)
    total_w = sum(w for _, w in cols) + (len(cols) - 1)
    print(header)
    print("-" * total_w)
    for idx, r in enumerate(rows, 1):
        gap = "⚠" if r.pipeline_gaps else ""
        def l(v, w): return str(v).ljust(w)
        def rj(v, w): return str(v).rjust(w)
        trades_s = f"{r.trade_count:,}"
        hold_s = f"{r.holder:,}"
        parts = [
            rj(f"{idx:>2}", 3),
            l((r.symbol[:10] + (" " + gap if gap else "")), 12),
            l(_fmt_num(r.market_cap), 10),
            l(_fmt_num(r.liquidity), 10),
            l(_fmt_num(r.volume), 12),
            rj(trades_s, 9),
            rj(hold_s, 10),
            l(_fmt_pct(r.price_change_pct), 10),
            l((f"${r.price:.6f}" if r.price < 1 else f"${r.price:.2f}"), 11),
        ]
        if sa.hydrate != "off":
            dev = "N/A" if r.dev_hold_pct is None else f"{r.dev_hold_pct:.1f}"
            sm = "N/A" if r.smart_money_count is None else f"{r.smart_money_count}"
            buy = "N/A" if r.buy_imbalance_ratio is None else f"{r.buy_imbalance_ratio*100:.0f}%"
            parts += [rj(dev, 6), rj(sm, 6), rj(buy, 7)]
        print(" ".join(parts))

    hyd_cu = cu - CU["token_list_v3"] - (CU["smart_money_list"] if sa.hydrate != "off" else 0)
    hyd_break = f"Hydrate {hyd_cu}" if (sa.hydrate != "off" and hyd_cu > 0) else None
    sm_break = "SM-batch 20" if sa.hydrate != "off" else None
    breakdown_parts = ["MVP 50"]
    if hyd_break: breakdown_parts.append(hyd_break)
    if sm_break: breakdown_parts.append(sm_break)
    breakdown = " + ".join(breakdown_parts)
    print(f"\n⚡CU: {cu} ({breakdown}) | ⏱{ms}ms | 📸{snap}")
    print(f"ℹ Chain={sa.chain.upper()}  Window={sa.window}  Sort={sa.sort_by}({sa.direction})  Rows={len(rows)}")


# ---------------------------------------------------------------------------
# Single-token hydrate
# ---------------------------------------------------------------------------


def cmd_token(args: argparse.Namespace) -> int:
    key = _load_key_from_env()
    if not key:
        print("[token] No API key configured. Run: screener config --apply <KEY>")
        return 1
    t0 = time.perf_counter()
    cu = 0
    out: dict[str, Any] = {"address": args.address, "chain": args.chain}
    try:
        ov, _ = be_get(
            key, "/defi/token_overview",
            chain=CHAINS[args.chain],
            params={"address": args.address, "frames": args.window},
        )
        cu += CU["token_overview"]
        sec, _ = be_get(
            key, "/defi/token_security",
            chain=CHAINS[args.chain],
            params={"address": args.address},
        )
        cu += CU["token_security"]
        sm_map: dict[str, int] = {}
        if not args.no_smart_money:
            sm_map = _fetch_smart_money_map(key, args.chain)
            cu += CU["smart_money_list"]
    except HttpError as e:
        print(e.pretty())
        return 2
    out["overview"] = ov.get("data")
    out["security"] = sec.get("data")
    out["smart_money_count"] = sm_map.get(args.address)
    out["cu_used_total"] = cu
    out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    if args.raw:
        print(json.dumps(out))
    else:
        od = out["overview"] or {}
        sd = out["security"] or {}
        def g(d, *keys):
            for k in keys:
                if isinstance(d, dict) and k in d and d[k] is not None:
                    return d[k]
            return None
        symbol = g(od, "symbol") or args.address[:8] + "…"
        price = g(od, "price"); mc = g(od, "marketCap", "market_cap")
        liq = g(od, "liquidity"); holder = g(od, "holder")
        devp = g(sd, "creatorPercentage")
        top10 = g(sd, "top10UserPercent", "top10HolderPercent")
        print(f"TOKEN {symbol}  [{args.chain.upper()}] {args.address}")
        print(f"  price        : ${price:.6f}" if isinstance(price, (int, float)) else "  price        : N/A")
        print(f"  market_cap   : {_fmt_num(float(mc)) if isinstance(mc,(int,float)) else 'N/A'}")
        print(f"  liquidity    : {_fmt_num(float(liq)) if isinstance(liq,(int,float)) else 'N/A'}")
        print(f"  holders      : {holder:,}" if isinstance(holder, int) else "  holders      : N/A")
        print(f"  dev_hold_pct : {float(devp)*100:.2f}%" if isinstance(devp,(int,float)) else "  dev_hold_pct : N/A")
        print(f"  top10_hold % : {float(top10)*100:.2f}%" if isinstance(top10,(int,float)) else "  top10_hold % : N/A")
        sm_tail = "" if args.no_smart_money else " + SM 20"
        print(f"  smart_money# : {out['smart_money_count'] if out['smart_money_count'] is not None else 'N/A (not in top100 SM today)'}")
        print(f"\n⚡CU: {cu} (overview 18 + security 30{sm_tail}) | ⏱{out['latency_ms']}ms")
    return 0


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="birdeye_screener", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    # config
    pc = sub.add_parser("config", help="Check/save Birdeye API key")
    pc.add_argument("--check", action="store_true", help="Verify current key")
    pc.add_argument("--apply", metavar="KEY", help="Save and verify a new key")
    pc.set_defaults(func=cmd_config)

    # scan
    ps = sub.add_parser("scan", help="High-volume token screener")
    ps.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    ps.add_argument("--window", choices=WINDOWS, default="5m")
    ps.add_argument("--sort-by", choices=["volume", "market_cap", "trade_count", "holder"], default="volume")
    ps.add_argument("--direction", choices=["asc", "desc"], default="desc")
    ps.add_argument("--limit", type=int, default=50, choices=range(1, 101), metavar="1-100")
    ps.add_argument("--offset", type=int, default=0)
    ps.add_argument("--platform", type=str, default=None)
    ps.add_argument("--min-market-cap", type=float, default=None)
    ps.add_argument("--max-market-cap", type=float, default=None)
    ps.add_argument("--min-liquidity", type=float, default=None)
    ps.add_argument("--max-liquidity", type=float, default=None)
    ps.add_argument("--min-volume", type=float, default=None)
    ps.add_argument("--min-price-change-pct", type=float, default=None)
    ps.add_argument("--min-trade-count", type=int, default=None)
    ps.add_argument("--min-holder", type=int, default=None)
    ps.add_argument("--hydrate", choices=["off", "top10", "top20", "all"], default="off",
                    help="Depth of security/overview/SM hydration (extra CU cost)")
    ps.add_argument("--min-smart-money", type=int, default=None, help="Requires --hydrate >= top10")
    ps.add_argument("--max-dev-hold-pct", type=float, default=None, help="Requires --hydrate >= top10")
    ps.add_argument("--min-buy-ratio", type=float, default=None, help="0-1, requires --hydrate >= top10")
    ps.add_argument("--raw", action="store_true", help="Single-line JSON output")
    ps.set_defaults(func=cmd_scan)

    # token
    pt = sub.add_parser("token", help="Hydrate one token fully (overview + security + SM)")
    pt.add_argument("--chain", choices=list(CHAINS.keys()), default="sol")
    pt.add_argument("--address", required=True)
    pt.add_argument("--window", default="5m")
    pt.add_argument("--no-smart-money", action="store_true")
    pt.add_argument("--raw", action="store_true")
    pt.set_defaults(func=cmd_token)

    return p


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
