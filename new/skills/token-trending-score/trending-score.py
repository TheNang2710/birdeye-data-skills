#!/usr/bin/env python3
"""trending-score.py — Token Trending Score (0-100) — Skill #22.

Pure-CLI skill module. Two ways to run it:

  1. Standalone (this file is its own executable):

        python3 skills/token-trending-score/trending-score.py \
            --chain sol --address <MINT> --model hybrid --format plain

  2. Imported by the unified CLI (recommended — same cache + History tab):

        python3 birdeye_cli.py token-trending-score \
            --chain sol --address <MINT> --model classic|hybrid

The unified CLI loads this file with importlib (the filename contains dashes, so
a plain `import` is impossible) and only expects three symbols:

    SKILL_NAME                   : str
    add_parser(sub, chains=None) : argparse subparser factory
    run(args)                    : int  (0 = ok)

The scoring engine itself lives in `modules/trending_score.py`; this file is the
self-contained wrapper that talks to Birdeye, assembles the inputs, calls
`compute_trending_score(...)` and renders plain / telegram / json / ui.

--------------------------------------------------------------------------------
SCORING MODEL (see docs/skill-22-token-trending-score.md for the derivation)
--------------------------------------------------------------------------------
Six weighted components combine into one 0-100 score per interval
(5m, 15m, 30m, 1h, 4h, 6h, 12h, 24h):

    component          weight   reads
    -----------------  ------   ------------------------------------------------
    Volume Growth       0.20    per-candle volume momentum (regression) / history
    Swap Activity       0.15    trade count growth / volume proxy
    Price Momentum      0.20    regression slope of log(close) / priceChange%
    Liquidity Health    0.15    liquidity/mcap ratio + recent stability
    Holder Dynamics     0.15    holder growth (chart) + cohort health + sufficiency
    Security            0.15    contract-risk penalties (hard brake if honeypot)

Two models:

  classic — the six-component model above on every interval.

  hybrid  — blends classic with an interval-native "attention" formula on the
            overview-supported intervals (1h / 4h / 24h):

                native_raw(T) = 1.00*log10(1 + wallets_T)
                              + 0.50*log10(1 + volume_T_usd)
                              + 0.25*pace_now_wallets(T)
                              + 0.25*pace_window_volume(T)
                              + 0.25*tanh(price_change_T_pct / 25)

                hybrid_raw(T) = 0.55*native(T) + 0.45*classic_raw(T)

            Intervals the overview does not support (5m/15m/30m/6h/12h) fall back
            to the classic score and are flagged `classic_fallback`.

A security multiplier caps the composite at 10% whenever the security score
drops below 40 (honeypot / active mint / unlocked LP ...).

--------------------------------------------------------------------------------
CU COST (per call)
--------------------------------------------------------------------------------
  /defi/token_creation_info ................ 35
  /defi/v3/ohlcv (1m candles) .............. 25-100  (scales with candle count)
  /defi/v3/liquidity/history/token ......... 20
  /defi/token_overview?includes=money_flow . 21
  /defi/v3/ohlcv (1s candles) .............. 25-100
  /token/v1/holder/chart ................... 30
  /token/v1/holder-profile ................. 21
  /defi/token_security ..................... 30
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SKILL_NAME = "token-trending-score"
SKILL_KIND = "token-trending-score-v1"
SKILL_VERSION = "1.0"

BIRDEYE_BASE = "https://public-api.birdeye.so"
CHAINS = {
    "sol": "solana", "bsc": "bsc", "base": "base",
    "eth": "ethereum", "arc": "arbitrum", "robinhood": "robinhood",
}

CACHE_DIR_DEFAULT = Path(os.environ.get("BIRDEYE_CACHE_DIR") or
                         (Path.home() / ".cache" / "birdeye-skills-runs"))
# Momentum snapshot CSV cache — shared with the collector so existing baseline
# data keeps working (see modules/trending_score.py: median baseline).
CSV_DIR_DEFAULT = Path(os.environ.get("BIRDEYE_TRENDING_CSV_DIR") or
                       (Path.home() / ".cache" / "birdeye-trending-csv"))
SNAPSHOT_DIR = CSV_DIR_DEFAULT / "momentum_snapshots"

FALLBACK_INTERVALS = ["5m", "15m", "30m", "1h", "4h", "6h", "12h", "24h"]


# ===========================================================================
# Scoring engine (single source of truth: modules/trending_score.py)
# ===========================================================================

def _load_engine():
    for base in Path(__file__).resolve().parents:
        cand = base / "modules" / "trending_score.py"
        if cand.is_file():
            name = "_trending_score_engine"
            spec = importlib.util.spec_from_file_location(name, cand)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            return mod
    return None


_ENGINE = _load_engine()
INTERVALS = list(getattr(_ENGINE, "INTERVALS", FALLBACK_INTERVALS))


def compute(ovd, secd, snapshots=None, candles_1m=None, liq_1m=None,
            candles_1s=None, holder_chart=None, holder_profile=None,
            model="classic", chain=None):
    """Delegate to modules/trending_score.compute_trending_score."""
    if _ENGINE is None:
        raise RuntimeError("modules/trending_score.py not found")
    return _ENGINE.compute_trending_score(
        ovd, secd, snapshots, candles_1m, liq_1m,
        candles_1s=candles_1s, holder_chart=holder_chart,
        holder_profile=holder_profile, model=model, chain=chain)


# ===========================================================================
# HTTP layer (stdlib only — zero dependencies)
# ===========================================================================

def _load_key():
    k = (os.environ.get("BIRDEYE_API_KEY") or "").strip()
    if k:
        return k
    cands = [Path.home() / ".config" / "birdeye" / ".env",
             Path.home() / ".birdeye.env"]
    here = Path(__file__).resolve()
    cands += [here.parent.parent.parent / ".env",
              here.parent.parent / ".env"]
    for c in cands:
        try:
            if not c.is_file():
                continue
            for ln in c.read_text().splitlines():
                ln = ln.strip()
                if ln.startswith("BIRDEYE_API_KEY="):
                    v = ln.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
        except OSError:
            continue
    return ""


class Api:
    """Tiny Birdeye client (stdlib urllib). Returns the `data` payload."""

    def __init__(self, key, chain="sol", timeout=25):
        self.key = key
        self.chain = chain
        self.timeout = timeout

    def get(self, path, params):
        label = path.rsplit("/", 1)[-1]
        qs = urllib.parse.urlencode(params)
        url = f"{BIRDEYE_BASE}{path}?{qs}"
        req = urllib.request.Request(url, headers={
            "X-API-KEY": self.key,
            "x-chain": CHAINS.get(self.chain, self.chain),
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            raise RuntimeError(f"[E{e.code}] {label}: {detail or e.reason}")
        except Exception as e:
            raise RuntimeError(f"{label}: {type(e).__name__} {e}")
        if isinstance(body, dict) and body.get("success") is False:
            raise RuntimeError(f"{label}: success=false {str(body)[:160]}")
        return body.get("data") if isinstance(body, dict) and "data" in body else body


# ===========================================================================
# Fetch + normalization helpers
# ===========================================================================

def _ohlcv_v3_cu(n_candles: int) -> int:
    """Birdeye /defi/v3/ohlcv CU cost scales with returned candle count.

    Tiers (items returned): 0-100 -> 25, 101-300 -> 30, 301-1000 -> 40,
    1001-2000 -> 75, 2001-5000 -> 100.
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


def _snapshot_path(chain: str, address: str) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe_addr = "".join(c if c.isalnum() or c in "-_." else "_" for c in address[:40])
    return SNAPSHOT_DIR / f"{chain}_{safe_addr}_snapshots.csv"


def _load_snapshots(chain: str, address: str, max_age_hours: float = 24.0) -> list[dict]:
    """Load collected overview snapshots for median baseline computation."""
    fp = _snapshot_path(chain, address)
    if not fp.exists():
        return []
    age_h = (time.time() - fp.stat().st_mtime) / 3600.0
    if age_h > max_age_hours:
        return []
    snaps = []
    with fp.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            snaps.append({k: v for k, v in row.items()})
    return snaps


def _fetch_creation_time(api, address) -> int | None:
    d = api.get("/defi/token_creation_info", {"address": address}) or {}
    ts = d.get("blockUnixTime") if isinstance(d, dict) else None
    return int(ts) if ts else None


def _extract_ohlcv(raw) -> list[dict]:
    """Extract normalized candles from an OHLCV v3 payload."""
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
    candles = []
    for e in arr:
        if not isinstance(e, dict):
            continue
        t = (e.get("t") or e.get("time") or e.get("timestamp")
             or e.get("unixTime") or e.get("unix_time"))
        o = e.get("o") or e.get("open")
        h = e.get("h") or e.get("high")
        l = e.get("l") or e.get("low")
        c = e.get("c") or e.get("close")
        v = e.get("v") or e.get("volume")
        v_usd = e.get("v_usd") or e.get("volumeUsd") or e.get("volume_usd")
        if t is None or c is None:
            continue
        candles.append({"t": int(t), "o": float(o or c), "h": float(h or c),
                        "l": float(l or c), "c": float(c),
                        "v": float(v or 0), "v_usd": float(v_usd or 0)})
    candles.sort(key=lambda x: x["t"])
    return candles


def _coerce_ts(v) -> int | None:
    """Coerce epoch seconds (int/float/digit-string) or an ISO-8601 timestamp
    into an int epoch, else `None`.

    The liquidity OHLC endpoint reports `unixTime` as an integer but `time` as
    an ISO string, so a plain `int()` on whichever key is found first can fail.
    """
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if s.isdigit():
            return int(s)
        try:
            return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def _extract_liq(raw) -> list[dict]:
    """Extract normalized liquidity points from a liquidity history payload.

    Captures both total liquidity and — when the source reports it (e.g. the
    Solana liquidity OHLC endpoint) — the *exit* liquidity, which is the
    realistic sell-side depth used by the liquidity gate.
    """
    arr: list = []
    if isinstance(raw, dict):
        for k in ("data", "items", "series", "liquidity", "history"):
            v = raw.get(k)
            if isinstance(v, list):
                arr = v
                break
        if not arr and isinstance(raw.get("data"), dict):
            d2 = raw["data"]
            for k2 in ("items", "series", "data", "history", "liquidity"):
                v2 = d2.get(k2)
                if isinstance(v2, list):
                    arr = v2
                    break
    elif isinstance(raw, list):
        arr = raw
    liq = []
    for e in arr:
        if not isinstance(e, dict):
            continue
        t = None
        for cand in ("unixTime", "unix_time", "t", "time", "timestamp"):
            t = _coerce_ts(e.get(cand))
            if t is not None:
                break
        val = None
        for cand in ("close_liquidity_usd", "liquidity_usd", "liquidityUsd",
                     "liquidityUSD", "valueUsd", "valueUSD", "usdLiquidity",
                     "liquidity", "usd", "liqUsd", "tvlC", "tvlc", "tvl"):
            v = e.get(cand)
            if isinstance(v, (int, float)):
                val = float(v)
                break
        ex = None
        for cand in ("close_exit_liquidity_usd", "exit_liquidity_usd",
                     "exitLiquidityUsd", "exitLiquidity", "exit_liquidity"):
            v = e.get(cand)
            if isinstance(v, (int, float)):
                ex = float(v)
                break
        if t is None:
            continue
        liq.append({"t": int(t), "liq": val, "exit": ex})
    liq.sort(key=lambda x: x["t"])
    return liq


# ===========================================================================
# Render helpers
# ===========================================================================

def _canonical_format(fmt, default="ui"):
    f = str(fmt or default).strip().lower()
    if f in {"ui", "plain", "telegram", "json"}:
        return f
    if f in {"render", "rendered", "scorecard"}:
        return "ui"
    if f == "raw-json":
        return "json"
    return default


def _color(score) -> str:
    if score is None:
        return "#64748b"
    if score >= 70:
        return "#22c55e"
    if score >= 50:
        return "#84cc16"
    if score >= 30:
        return "#f59e0b"
    if score >= 15:
        return "#f97316"
    return "#ef4444"


def _fmt_usd(v):
    if v is None:
        return "N/A"
    sign = "-" if float(v) < 0 else ""
    vv = abs(float(v))
    if vv >= 1_000_000_000:
        return f"{sign}${vv / 1_000_000_000:.2f}B"
    if vv >= 1_000_000:
        return f"{sign}${vv / 1_000_000:.2f}M"
    if vv >= 1_000:
        return f"{sign}${vv / 1_000:.2f}K"
    if vv < 0.01 and vv > 0:
        return f"{sign}${vv:.6f}"
    return f"{sign}${vv:,.2f}"


# ===========================================================================
# Data-availability guard
# ===========================================================================
# hybrid cannot be computed from candles alone: its native formula needs the
# token_overview wallet/volume frames (uniqueWallet*, v*USD). The classic model
# additionally needs OHLCV (price/volume) and liquidity history. When any of
# these are missing the engine degrades silently — these checks make that
# degradation visible instead of returning a "hybrid" label over classic math.
HYBRID_REQUIRED_INTERVALS = ("1h", "4h", "24h")


def _hybrid_ready_intervals(result: dict) -> list[str]:
    ivs = (result or {}).get("intervals") or {}
    return [i for i in HYBRID_REQUIRED_INTERVALS
            if (ivs.get(i) or {}).get("mode") == "hybrid"]


def _collect_warnings(model, result, ovd, candles_1m, candles_1s, liq_1m,
                      snapshots) -> list[dict]:
    """Flag missing/thin upstream data so a silent fallback is never invisible."""
    warns: list[dict] = []

    if not ovd:
        warns.append({
            "code": "overview_missing", "level": "critical",
            "detail": "token_overview unavailable — volume/swaps/holder/price "
                      "fall back to candles only",
        })

    if model == "hybrid":
        ready = _hybrid_ready_intervals(result)
        missing = [i for i in HYBRID_REQUIRED_INTERVALS if i not in ready]
        if missing:
            warns.append({
                "code": "hybrid_not_ready", "level": "critical",
                "detail": "hybrid needs overview wallets (uniqueWallet*) + volume "
                          f"(v*USD); classic fallback on {', '.join(missing)}",
            })

    n1m = len(candles_1m or [])
    n1s = len(candles_1s or [])
    nliq = len(liq_1m or [])

    if n1m < 3:
        warns.append({
            "code": "ohlcv_1m_thin", "level": "critical",
            "detail": f"only {n1m} 1m candles — price/volume regression unusable",
        })
    if n1s < 3:
        warns.append({
            "code": "ohlcv_1s_thin", "level": "warn",
            "detail": f"only {n1s} 1s candles — 5m/15m/30m fall back to 1m candles",
        })
    if nliq < 3:
        warns.append({
            "code": "liquidity_thin", "level": "warn",
            "detail": f"only {nliq} liquidity points — stability sub-score is neutral",
        })
    return warns


def _hybrid_coverage(model, result) -> dict:
    """How many of the hybrid-native intervals actually got overview data."""
    ready = _hybrid_ready_intervals(result) if model == "hybrid" else []
    return {
        "model": model,
        "hybrid_intervals": list(HYBRID_REQUIRED_INTERVALS),
        "hybrid_ready": ready,
        "hybrid_coverage": f"{len(ready)}/{len(HYBRID_REQUIRED_INTERVALS)}",
    }


# ===========================================================================
# Cache (compatible with `birdeye_cli.py history-render`)
# ===========================================================================

def _cache_dir(custom=None) -> Path:
    p = Path(custom) if custom else CACHE_DIR_DEFAULT
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_cache(cdir: Path, run_id: str, payload: dict) -> Path:
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in run_id) + ".json"
    fp = cdir / name
    fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return fp


# ===========================================================================
# Command
# ===========================================================================

def cmd_trending_score(args) -> int:
    chain = getattr(args, "chain", "sol")
    address = args.address
    model = str(getattr(args, "model", "classic") or "classic").strip().lower()
    if model not in {"classic", "hybrid"}:
        model = "classic"
    n_candles = max(100, min(5000, int(getattr(args, "candles", 5000) or 5000)))
    fmt = _canonical_format(getattr(args, "format", None))
    key = _load_key()
    if not key:
        sys.stderr.write("[token-trending-score] missing BIRDEYE_API_KEY.\n")
        return 2

    api = Api(key, chain)
    cu = 0
    breakdown_cu: list[str] = []
    run_id = f"ts_{chain}_{address.replace('.', '_')[:20]}_{int(time.time())}"

    # -- 0) Token creation time (anchor for OHLCV / liquidity) --
    creation_ts = None
    try:
        creation_ts = _fetch_creation_time(api, address)
        cu += 35
        breakdown_cu.append("creation_info=35")
    except Exception:
        breakdown_cu.append("creation_info=FAIL")

    # -- 0b) Load collected snapshots for median baseline --
    snapshots = _load_snapshots(chain, address)
    if snapshots:
        breakdown_cu.append(f"snapshots={len(snapshots)}(loaded)")

    # -- 1) OHLCV v3 (1m candles) — from creation time (capped at n_candles) --
    now = int(time.time())
    time_from = max(creation_ts, now - n_candles * 60) if creation_ts and creation_ts > 0 \
        else now - n_candles * 60
    try:
        raw = api.get("/defi/v3/ohlcv", {
            "address": address, "type": "1m",
            "time_to": now, "time_from": time_from,
        })
        candles_1m = _extract_ohlcv(raw)
        step_cu = _ohlcv_v3_cu(len(candles_1m))
        cu += step_cu
        breakdown_cu.append(f"ohlcv_v3_1m={step_cu}")
    except Exception as e:
        sys.stderr.write(f"[token-trending-score] OHLCV error: {e}\n")
        return 1

    # -- 2) Liquidity history (1m) — from creation time --
    liq_1m: list[dict] = []
    now = int(time.time())
    time_from = max(creation_ts, now - n_candles * 60) if creation_ts and creation_ts > 0 \
        else now - n_candles * 60
    # 1st choice: liquidity OHLC — it also reports *exit* liquidity (the
    # realistic sell-side depth used by the liquidity gate when available).
    liq_attempts = [
        ("/defi/v3/liquidity/ohlc/token",
         {"address": address, "resolution": "1m", "direction": "back", "count": 100},
         "liq_ohlc_exit"),
        ("/defi/v3/liquidity/history/token",
         {"address": address, "type": "1m", "time_to": now, "time_from": time_from},
         "liq_hist_v3"),
        ("/defi/v3/liquidity-ohlc-token",
         {"address": address, "type": "1m", "time_to": now, "time_from": time_from},
         "liq_hist_v3b"),
    ]
    for path, params, tag in liq_attempts:
        try:
            raw_liq = api.get(path, params)
            points = _extract_liq(raw_liq)
            if points:
                liq_1m = points
                cu += 20
                breakdown_cu.append(f"{tag}=20")
                break
        except RuntimeError:
            continue
    if not liq_1m:
        breakdown_cu.append("liq=FAIL")

    # -- 3) Token overview (includes=money_flow for wallet dynamics) --
    ovd: dict = {}
    try:
        ovd = api.get("/defi/token_overview",
                      {"address": address, "includes": "money_flow"}) or {}
        if not isinstance(ovd, dict):
            ovd = {}
        cu += 21
        breakdown_cu.append("overview+mf=21")
    except RuntimeError as e:
        breakdown_cu.append(f"overview=FAIL({str(e)[:30]})")

    # -- 3b) 1s OHLCV candles (short-interval price/volume: 5m/15m/30m) --
    candles_1s: list[dict] = []
    now = int(time.time())
    time_from = now - 70 * 60  # last 70 min (covers 2x the 30m window)
    try:
        raw1s = api.get("/defi/v3/ohlcv", {
            "address": address, "type": "1s",
            "time_to": now, "time_from": time_from,
        })
        candles_1s = _extract_ohlcv(raw1s)
        step_cu = _ohlcv_v3_cu(len(candles_1s))
        cu += step_cu
        breakdown_cu.append(f"ohlcv_1s={step_cu}")
    except Exception as e:
        sys.stderr.write(f"[token-trending-score] OHLCV 1s error: {e}\n")
        breakdown_cu.append("ohlcv_1s=FAIL")

    # -- 3c) Holder chart 1m (holder growth across all intervals) --
    holder_chart: list[dict] = []
    try:
        hc = api.get("/token/v1/holder/chart", {
            "token_address": address, "chart_type": "1m",
            "count": 100, "mode": "padding",
        })
        if isinstance(hc, list):
            holder_chart = hc
        elif isinstance(hc, dict):
            holder_chart = hc.get("data") or []
        holder_chart = holder_chart or []
        cu += 30
        breakdown_cu.append("holder_chart=30")
    except RuntimeError as e:
        breakdown_cu.append(f"holder_chart=FAIL({str(e)[:30]})")

    # -- 3d) Holder profile (holder health / cohort analysis) --
    holder_profile: dict = {}
    try:
        hp = api.get("/token/v1/holder-profile", {"token_address": address, "limit": 20})
        holder_profile = hp if isinstance(hp, dict) else {}
        cu += 21
        breakdown_cu.append("holder_profile=21")
    except RuntimeError as e:
        breakdown_cu.append(f"holder_profile=FAIL({str(e)[:30]})")

    # -- 4) Token security --
    secd: dict = {}
    try:
        sec = api.get("/defi/token_security", {"address": address})
        secd = sec if isinstance(sec, dict) else {}
        cu += 30
        breakdown_cu.append("security=30")
    except RuntimeError as e:
        breakdown_cu.append(f"security=FAIL({str(e)[:30]})")

    # -- 5) Compute --
    result = compute(
        ovd, secd, snapshots, candles_1m, liq_1m,
        candles_1s=candles_1s, holder_chart=holder_chart,
        holder_profile=holder_profile, model=model, chain=chain,
    )

    symbol = ovd.get("symbol") or ""
    name = ovd.get("name") or symbol or address[:12]
    overall = result["overall_trending_score"]
    intervals = result["intervals"]
    holder_count = result["meta"]["holder_count"]
    market_cap = result["meta"]["market_cap"]

    # -- data-availability guard (hybrid needs overview; classic needs ohlcv+liq) --
    warnings = _collect_warnings(model, result, ovd, candles_1m, candles_1s,
                                 liq_1m, snapshots)
    pipeline_gap = any(x["level"] == "critical" for x in warnings)
    coverage = _hybrid_coverage(model, result)

    # ---- plain ----
    plain_lines = [
        f"Skill #22 · Token Trending Score — {symbol or address[:16]}",
        f"Model: {model}",
        (f"Overall: {overall}/100" if overall is not None else "Overall: N/A"),
        f"Junk gate: {'TRIGGERED' if result['is_risky'] else 'clear'}  "
        f"Holders: {holder_count}  MCap: {_fmt_usd(market_cap)}",
    ]
    if model == "hybrid":
        plain_lines.append("Hybrid: classic 6-component core + wallets/volume/pace "
                           "native blend on 1h/4h/24h")
    _g = result.get("gates") or {}
    plain_lines.append(
        "Gates: security x{:.2f} ({}) · liquidity x{:.2f} ({}) · holder x{:.2f} ({}) "
        "→ combined x{:.2f}".format(
            _g.get("security", {}).get("multiplier", 1.0),
            _g.get("security", {}).get("reason", "-"),
            _g.get("liquidity", {}).get("multiplier", 1.0),
            _g.get("liquidity", {}).get("reason", "-"),
            _g.get("holder", {}).get("multiplier", 1.0),
            _g.get("holder", {}).get("reason", "-"),
            _g.get("combined_multiplier", 1.0)))
    plain_lines.append("")
    plain_lines.append(f"{'Interval':<10} {'Score':>8} {'Vol':>6} {'Swap':>6} "
                       f"{'Price':>7} {'Liq':>6} {'Hold':>6} {'Sec':>6}")
    plain_lines.append("-" * 64)
    for iv in INTERVALS:
        d = intervals.get(iv, {})
        sc = d.get("trending_score")
        if sc is None:
            plain_lines.append(f"{iv:<10} {'N/A':>8}")
            continue
        c = d.get("components", {})
        plain_lines.append(f"{iv:<10} {sc:>8.1f} "
                           f"{c.get('volume', {}).get('score', 0):>6.0f} "
                           f"{c.get('swaps', {}).get('score', 0):>6.0f} "
                           f"{c.get('price', {}).get('score', 0):>7.0f} "
                           f"{c.get('liquidity', {}).get('score', 0):>6.0f} "
                           f"{c.get('holder', {}).get('score', 0):>6.0f} "
                           f"{c.get('security', {}).get('score', 0):>6.0f}")
    plain_lines.append("")
    for x in warnings:
        mark = ("⚠ pipeline_gap" if x["level"] == "critical"
                else "⚠ warn" if x["level"] == "warn" else "· note")
        plain_lines.append(f"{mark}  {x['code']} — {x['detail']}")
    if warnings:
        plain_lines.append("")
    plain_lines.append(f"⚡CU: {cu} ({', '.join(breakdown_cu)})")
    plain_lines.append(f"CSV cache: {CSV_DIR_DEFAULT}")
    out_plain = "\n".join(plain_lines)

    # ---- telegram ----
    tg_lines = [f"*Token Trending Score* `{symbol or address[:12]}`",
                f"Mode: *{model}*",
                (f"Overall: *{overall}/100*" if overall is not None else "Overall: N/A")]
    if result["is_risky"]:
        tg_lines.append("⚠️ *JUNK GATE* — weighted security/liquidity/holder penalty active")
    tg_lines.append("```")
    tg_lines.append(f"{'IV':<6}{'Score':>7}{'Vol':>6}{'Swp':>6}{'Px':>6}"
                    f"{'Liq':>6}{'Hld':>6}{'Sec':>6}")
    for iv in INTERVALS:
        d = intervals.get(iv, {})
        sc = d.get("trending_score")
        if sc is None:
            tg_lines.append(f"{iv:<6}{'N/A':>7}")
            continue
        c = d.get("components", {})
        tg_lines.append(f"{iv:<6}{sc:>7.1f}"
                        f"{c.get('volume', {}).get('score', 0):>6.0f}"
                        f"{c.get('swaps', {}).get('score', 0):>6.0f}"
                        f"{c.get('price', {}).get('score', 0):>6.0f}"
                        f"{c.get('liquidity', {}).get('score', 0):>6.0f}"
                        f"{c.get('holder', {}).get('score', 0):>6.0f}"
                        f"{c.get('security', {}).get('score', 0):>6.0f}")
    tg_lines.append("```")
    for x in warnings:
        if x["level"] == "critical":
            tg_lines.append(f"⚠ pipeline_gap `{x['code']}` — {x['detail']}")
        elif x["level"] == "warn":
            tg_lines.append(f"⚠ warn `{x['code']}` — {x['detail']}")
    tg_lines.append(f"⚡CU {cu} · Holders {holder_count} · MCap {_fmt_usd(market_cap)}")
    out_telegram = "\n".join(tg_lines)

    # ---- rendered HTML (ui) ----
    iv_cards = ""
    for iv in INTERVALS:
        d = intervals.get(iv, {})
        sc = d.get("trending_score")
        if sc is None:
            iv_cards += (f'<div style="background:#0f172a;border-radius:10px;padding:14px 12px;text-align:center">'
                         f'<div style="font-size:12px;color:#64748b;text-transform:uppercase">{iv}</div>'
                         f'<div style="font-size:24px;color:#64748b;margin-top:6px">N/A</div></div>')
            continue
        color = _color(sc)
        c = d.get("components", {})
        iv_cards += (f'<div style="background:#0f172a;border-radius:10px;padding:14px 12px;text-align:center;border:1px solid {color}33">'
                     f'<div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.4px">{iv}</div>'
                     f'<div style="font-size:34px;line-height:1.1;font-weight:800;color:{color};margin:2px 0 8px">{sc}<span style="font-size:14px;color:#64748b">/100</span></div>'
                     f'<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:6px;font-size:11px;color:#94a3b8">'
                     f'<div>V<br><b style="color:#e2e8f0;font-size:14px">{c.get("volume", {}).get("score", 0):.0f}</b></div>'
                     f'<div>S<br><b style="color:#e2e8f0;font-size:14px">{c.get("swaps", {}).get("score", 0):.0f}</b></div>'
                     f'<div>P<br><b style="color:#e2e8f0;font-size:14px">{c.get("price", {}).get("score", 0):.0f}</b></div>'
                     f'<div>L<br><b style="color:#e2e8f0;font-size:14px">{c.get("liquidity", {}).get("score", 0):.0f}</b></div>'
                     f'<div>H<br><b style="color:#e2e8f0;font-size:14px">{c.get("holder", {}).get("score", 0):.0f}</b></div>'
                     f'<div>Sec<br><b style="color:#e2e8f0;font-size:14px">{c.get("security", {}).get("score", 0):.0f}</b></div>'
                     f'</div></div>')

    overall_color = _color(overall)
    _gm = _g.get("combined_multiplier", 1.0)
    if result["is_risky"]:
        risky_badge = (f'<div style="display:inline-block;background:#ef444422;color:#ef4444;padding:2px 8px;'
                       f'border-radius:6px;font-size:11px;font-weight:700;border:1px solid #ef4444">'
                       f'⚠ JUNK GATE ×{_gm:.2f}</div>')
    elif _gm < 0.999:
        risky_badge = (f'<div style="display:inline-block;background:#f59e0b22;color:#f59e0b;padding:2px 8px;'
                       f'border-radius:6px;font-size:11px;font-weight:700;border:1px solid #f59e0b">'
                       f'gate ×{_gm:.2f}</div>')
    else:
        risky_badge = ('<div style="display:inline-block;background:#22c55e22;color:#22c55e;padding:2px 8px;'
                       'border-radius:6px;font-size:11px;font-weight:700;border:1px solid #22c55e">✓ clean</div>')

    # -- data-availability badge + panel (hybrid needs overview; classic needs ohlcv+liq) --
    data_badge = ('<div style="display:inline-block;background:#ef444422;color:#ef4444;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700;border:1px solid #ef4444">⚠ pipeline_gap</div>'
                  if pipeline_gap else
                  '<div style="display:inline-block;background:#22c55e22;color:#22c55e;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700;border:1px solid #22c55e">✓ data ok</div>')
    model_meta = f'<span>Model: <b style="color:#e2e8f0">{model}</b></span>'
    # Only surface actionable (critical/warn) pipeline issues — info-level notes
    # (e.g. snapshot-baseline provenance) are noise and are dropped from the UI.
    notable = [x for x in warnings if x["level"] in ("critical", "warn")]
    if notable:
        w_rows = ""
        for x in notable:
            if x["level"] == "critical":
                col, mk = "#ef4444", "⚠ pipeline_gap"
            else:
                col, mk = "#f59e0b", "⚠ warn"
            w_rows += (f'<div style="font-size:11px;color:{col};padding:1px 0">'
                       f'{mk} <b style="color:#e2e8f0">{x["code"]}</b> — {x["detail"]}</div>')
        warn_html = (f'<div style="background:#0f172a;border-radius:8px;padding:10px;margin-bottom:14px;'
                     f'border:1px solid {"#ef444455" if pipeline_gap else "#f59e0b33"}">'
                     f'<div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">'
                     f'Pipeline</div>{w_rows}</div>')
    else:
        warn_html = ""

    # -- Gates + security detail panel --
    _sec_g = _g.get("security", {})
    _liq_g = _g.get("liquidity", {})
    _hol_g = _g.get("holder", {})
    _liq_eff = _liq_g.get("effective_liquidity")
    _exit_used = _liq_g.get("used_exit_liquidity")
    gate_rows = (
        f'<div style="font-size:11px;color:#94a3b8;padding:1px 0">Security gate (35%) '
        f'<b style="color:#e2e8f0">×{_sec_g.get("multiplier", 1.0):.2f}</b> '
        f'<span style="color:#64748b">({_sec_g.get("reason", "-")} · score {_sec_g.get("score", 0):.0f})</span></div>'
        f'<div style="font-size:11px;color:#94a3b8;padding:1px 0">Liquidity gate (50%) '
        f'<b style="color:#e2e8f0">×{_liq_g.get("multiplier", 1.0):.2f}</b> '
        f'<span style="color:#64748b">({_liq_g.get("reason", "-")})</span></div>'
        f'<div style="font-size:11px;color:#94a3b8;padding:1px 0">Holder gate (15%) '
        f'<b style="color:#e2e8f0">×{_hol_g.get("multiplier", 1.0):.2f}</b> '
        f'<span style="color:#64748b">({_hol_g.get("reason", "-")} · holders {int(_hol_g.get("holder_count") or 0)})</span></div>'
        f'<div style="font-size:11px;color:#94a3b8;padding:1px 0">Combined gate '
        f'<b style="color:#e2e8f0">×{_g.get("combined_multiplier", 1.0):.2f}</b> '
        f'<span style="color:#64748b">({_g.get("reason", "-")})</span></div>'
        f'<div style="font-size:11px;color:#94a3b8;padding:1px 0">Effective depth '
        f'<b style="color:#e2e8f0">{_fmt_usd(_liq_eff)}</b>'
        + (f' <span style="color:#64748b">· exit liquidity {_fmt_usd(_liq_g.get("exit_liquidity"))} (used)</span>'
           if _exit_used else '')
        + '</div>')

    sec_penalties = result["security"].get("penalties", [])
    if sec_penalties:
        sec_html = gate_rows + "".join(
            f'<div style="font-size:11px;color:#f97316;padding:1px 0">'
            f'{p["delta"]} {p["name"]} — {p["detail"]}</div>' for p in sec_penalties)
    else:
        sec_html = gate_rows + '<div style="font-size:11px;color:#22c55e">No security penalties</div>'

    w_ = result["weights"]
    html = f'''<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0a0e1a;color:#e2e8f0;padding:16px;border-radius:12px;max-width:720px">
<div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Skill #22 · Token Trending Score</div>
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
  <div style="font-size:20px;font-weight:700">{name} <span style="color:#64748b;font-size:14px">${symbol}</span></div>
  <div style="text-align:right">
    <div style="font-size:30px;font-weight:800;color:{overall_color}">{overall if overall is not None else 'N/A'}<span style="font-size:14px;color:#64748b">/100</span></div>
    <div style="font-size:10px;color:#64748b">overall</div>
  </div>
</div>
<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;font-size:11px;color:#64748b;flex-wrap:wrap">
  {risky_badge}
  {data_badge}
  {model_meta}
  <span>Holders: <b style="color:#e2e8f0">{holder_count}</b></span>
  <span>MCap: <b style="color:#e2e8f0">{_fmt_usd(market_cap)}</b></span>
  <span class="copy-addr" data-copy-addr="{address}" style="cursor:pointer;user-select:none" title="Click to copy">{address[:18]}.. 📋</span>
</div>
{warn_html}
<div style="display:grid;grid-template-columns:repeat(8,1fr);gap:8px;margin-bottom:14px">{iv_cards}</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
  <div style="background:#0f172a;border-radius:8px;padding:10px">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">Weights</div>
    <div style="font-size:11px;color:#94a3b8">Vol {int(w_['volume']*100)}% · Swap {int(w_['swaps']*100)}% · Price {int(w_['price']*100)}% · Liq {int(w_['liquidity']*100)}% · Hold {int(w_['holder']*100)}% · Sec {int(w_['security']*100)}%</div>
  </div>
  <div style="background:#0f172a;border-radius:8px;padding:10px">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px">Gates &amp; Security</div>
    {sec_html}
  </div>
</div>
<div style="font-size:10px;color:#475569;margin-top:10px">Momentum decides the score (Vol 30 · Swap 15 · Price 25 · Hold 10) · Junk gate = 35% security + 50% liquidity + 15% holder · Security gate = security score/100 · Liquidity gate ramps 0 (&lt;USD 1k) → 50% (4k) → 80% (10k) → 100% (50k) · Holder gate ramps 0 (≤100) → 90% (1k) → 100% (2k) · Liquidity gate uses effective depth (min of liquidity &amp; exit liquidity where reported) · Growth Score: G=(cur+ε)/(baseline+ε) · score=100·ln(1+G)/ln(16) · Short intervals (5m/15m/30m) use 1s OHLCV candles</div>
</div>'''

    # -- public json contract (never carries the UI html) --
    envelope = {
        "schemaVersion": 1, "kind": SKILL_KIND, "run_id": run_id,
        "cu_used": cu,
        "params": {"chain": chain, "address": address, "candles": n_candles,
                   "model": model, "argv": sys.argv[1:]},
        "symbol": symbol, "name": name,
        "model": model,
        "overall_trending_score": overall,
        "intervals": intervals,
        "is_risky": result["is_risky"],
        "gates": result.get("gates") or {},
        "security": result["security"],
        "weights": result["weights"],
        "meta": result["meta"],
        "coverage": coverage,
        "pipeline_gap": pipeline_gap,
        "warnings": warnings,
        "cu_breakdown": breakdown_cu,
    }
    out_json = json.dumps(envelope, ensure_ascii=False, indent=2)
    out_raw_json = json.dumps(envelope, ensure_ascii=False)

    # -- UI payload (mirrors token-dd-score._ui_envelope) -------------------
    # Every format is pre-rendered here so the local console can flip between
    # the ui / json / telegram / plain tabs without re-running the skill.
    format_renderers = ["ui", "json", "plain", "telegram", "raw-json"]
    ui_payload = {
        "schemaVersion": 1, "kind": SKILL_KIND,
        "skill": SKILL_NAME, "skill_version": SKILL_VERSION,
        "format_renderers": format_renderers,
        "payload": envelope,
        "rendered_plain": out_plain,
        "rendered_telegram": out_telegram,
        "rendered_json": out_json,
        "rendered_raw-json": out_raw_json,
        "rendered_ui": html,
        "html": html,
        "overall_trending_score": overall,
        "model": model, "symbol": symbol, "name": name,
        "intervals": intervals,
        "is_risky": result["is_risky"],
        "security": result["security"],
        "weights": result["weights"],
        "meta": result["meta"],
        "coverage": coverage,
        "pipeline_gap": pipeline_gap,
        "warnings": warnings,
    }
    out_ui = json.dumps(ui_payload, ensure_ascii=False)

    payload = {
        "runId": run_id, "kind": SKILL_KIND, "cached": False,
        "cu_used_total": cu, "cu_breakdown": breakdown_cu,
        "params": envelope["params"],
        "symbol": symbol, "name": name,
        "overall_trending_score": overall,
        "snapshot_time": int(time.time()),
        "format_renderers": format_renderers,
        "rendered_plain": out_plain,
        "rendered_telegram": out_telegram,
        "rendered_json": out_json,
        "rendered_ui": out_ui,
        "rendered_raw-json": out_raw_json,
        "rendered_rendered": out_ui,
        "out": out_plain,
    }
    if getattr(args, "write_cache", True):
        try:
            _write_cache(_cache_dir(getattr(args, "cache_dir", None)), run_id, payload)
        except OSError:
            pass
    sys.stdout.write(f"#RUN_ID {run_id}\t{SKILL_NAME}\tcu={cu}\n")

    if fmt == "plain":
        print(out_plain)
        return 0
    if fmt == "telegram":
        print(out_telegram)
        return 0
    if fmt == "json":
        # json must stay free of the UI payload (project hard rule, same guard
        # as token-dd-score._safe_render_output).
        print(out_json)
        return 0
    print(out_ui)
    return 0


# ===========================================================================
# CLI wiring
# ===========================================================================

def add_parser(sub, chains=None):
    chain_ids = list((chains or CHAINS).keys())
    p = sub.add_parser(
        "token-trending-score",
        help="Skill #22 · Token Trending Score — 0..100 momentum score per interval "
             "(5m/15m/30m/1h/4h/6h/12h/24h) from OHLCV + liquidity + holders + security. "
             "Typical ~171 CU (ohlcv 100 + liq 20 + overview 21 + security 30 + extras).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Six weighted components (volume/swaps/price/liquidity/holder/security)\n"
            "combined per interval, capped by a security multiplier.\n"
            "classic = original 6-component model on every interval.\n"
            "hybrid  = blend classic with a wallets/volume/pace native formula on 1h/4h/24h."
        ))
    p.add_argument("--chain", choices=chain_ids, default="sol")
    p.add_argument("--address", required=True, help="Token contract address")
    p.add_argument("--model", choices=["classic", "hybrid"], default="classic",
                   help="classic = original 6-component momentum model; "
                        "hybrid = blend classic with wallets/volume/pace interval formula.")
    p.add_argument("--candles", type=int, default=5000,
                   help="Number of 1m OHLCV candles (default 5000 = 100 CU, covers ~83h).")
    p.add_argument("--nocache", dest="nocache", action="store_true", default=False,
                   help="Bypass the 24h CSV cache and fetch fresh data.")
    p.add_argument("--format", choices=["ui", "json", "telegram", "plain", "raw-json", "rendered"],
                   default="ui")
    p.set_defaults(func=run)
    return p


def run(args) -> int:
    """Entry point used by the unified CLI: `birdeye_cli.py token-trending-score ...`."""
    return cmd_trending_score(args)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(
        prog="token-trending-score",
        description="Token Trending Score (0-100) — standalone entry point.")
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--no-write-cache", dest="write_cache", action="store_false", default=True)
    sub = p.add_subparsers(dest="cmd")
    add_parser(sub)
    # Two invocation shapes are accepted:
    #   trending-score.py --chain sol --address X --model hybrid
    #   trending-score.py token-trending-score --chain sol --address X
    if "token-trending-score" not in argv:
        argv = ["token-trending-score"] + argv
    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
