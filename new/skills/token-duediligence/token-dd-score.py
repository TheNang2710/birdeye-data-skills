#!/usr/bin/env python3
"""token-dd-score.py — Token Due-Diligence Score (0-100) — Skill #24.

Pure-CLI skill module. Two ways to run it:

  1. Standalone (this file is its own executable):

        python3 skills/token-duediligence/token-dd-score.py \
            --chain sol --address <MINT> --mode advanced

  2. Imported by the unified CLI (recommended, gives cache + history-render):

        python3 birdeye_cli.py token-dd-score \
            --chain sol --address <MINT> --mode standard|advanced

The unified CLI loads this file with importlib (the filename contains dashes,
so a plain `import` is impossible) and only expects three symbols:

    SKILL_NAME            : str
    add_parser(sub)       : argparse subparser factory
    run(args)             : int  (0 = ok)

--------------------------------------------------------------------------------
SCORING MODEL (see docs/token-dd-score-workflow.md for the full derivation)
--------------------------------------------------------------------------------

Five pillars, every pillar is a WEIGHTED MEAN of sub-scores (0-100). Absent
sub-signals are dropped AND their weight is removed from the denominator, so a
missing field lowers the pillar coverage instead of silently scoring as a pass
(GMGN contract-dd rule).

    pillar           sol wt  std wt   sub-signals
    ---------------- ------  ------   -----------------------------------------
    Security           0.17    0.189  mint/freeze/metadata/LP/creator/checks
    Holders            0.28    0.311  top1/3/10, holder base, cohorts, snipers
    Activity           0.20    0.222  engagement, buy pressure, momentum, drawdown
    Liquidity          0.25    0.278  depth, stability, valuation, trend, pairs
    Smart Money        0.10    0.000  SM presence/flow/quality, whales, KOLs

The weights above are the Solana ones. On Solana the Security pillar gives up
6 points — 3 to Holders and 3 to Liquidity — because renounced mint/freeze and
locked LP are the launchpad default there, so contract flags carry less
information than the holder/liquidity risk they proxy. On other chains the
unshifted preset is used (Security 0.23 / Holders 0.25 / Activity 0.20 /
Liquidity 0.22). The shift is applied to every preset before the weights are
re-normalised, so the declared percentages always sum to 1.0.

Standard mode only calls token_overview + token_security, therefore the cohorts,
snipers, exit-liquidity, stability, trend and smart-money sub-signals are
unavailable -> the remaining weights are re-normalised and the response carries
a `coverage` figure per pillar plus a ⚠ coverage_caveat.

After the weighted mean, a smooth discount gate reacts to liquidity
*deterioration*, not to absolute depth. Absolute depth is already scored by the
Liquidity pillar, so gating on it as well penalised one weakness twice (a $5k
exit pool scored low on depth AND lost another ~25% of its total score). The
gate therefore only reads how far liquidity has fallen from its recent peak:

    liq_pen  = 0.10 * smoothstep(ramp(liquidity_drawdown_from_peak,      20%, 70%))
    exit_pen = 0.15 * smoothstep(ramp(exit_liquidity_drawdown_from_peak, 20%, 70%))
    gate     = 1 - max(liq_pen, exit_pen)      # worst deterioration binds, capped at -15%

    FINAL = weighted_mean * gate

A future build will add multi-interval holder change as a second deterioration
input; until that data is available it contributes nothing.
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import html as _html
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SKILL_NAME = "token-dd-score"
SKILL_KIND = "token-dd-score-v1"
SKILL_VERSION = "1.0"

BIRDEYE_BASE = "https://public-api.birdeye.so"
CHAINS = {
    "sol": "solana", "bsc": "bsc", "base": "base",
    "eth": "ethereum", "arc": "arbitrum", "robinhood": "robinhood",
}
SOL_ONLY = {"sol"}

CACHE_DIR_DEFAULT = Path(os.environ.get("BIRDEYE_CACHE_DIR") or
                         (Path.home() / ".cache" / "birdeye-skills-runs"))

# The 8 token_overview frames we consume (single call covers all of them).
FRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "24h"]
# Frames used by the momentum sub-signal. Nested windows from 15m to 24h, so a
# real move stays visible across several horizons instead of one snapshot;
# longer windows carry more weight because they are less noisy.
MOMENTUM_FRAMES = [("15m", 0.10), ("1h", 0.20), ("4h", 0.30), ("24h", 0.40)]
# Buy-pressure frames + weights.
BUY_FRAMES = [("5m", 0.15), ("1h", 0.25), ("4h", 0.25), ("24h", 0.35)]
# Smart-money cohort flow frames + weights (used by the multi-interval score).
SM_FLOW_FRAMES = [("5m", 0.15), ("1h", 0.25), ("4h", 0.25), ("24h", 0.35)]
# The four intervals surfaced for price change and money flow.
KEY_FRAMES = [f for f, _ in BUY_FRAMES]
UI_KEY_FRAMES = ["15m", "1h", "4h", "24h"]
# Money-flow cohorts present in token_overview.moneyFlow[].tag
_MF_TAGS = ["all", "smart_money", "whales", "kol"]

# ---------------------------------------------------------------------------
# Pillar weights per mode. Standard re-normalises to 1.0 across 4 pillars.
# ---------------------------------------------------------------------------
WEIGHT_PRESETS = {
    "default": {
        "security": 0.23, "holders": 0.25, "activity": 0.20,
        "liquidity": 0.22, "smart_money": 0.10,
    },
    "strict-liquidity": {
        "security": 0.18, "holders": 0.19, "activity": 0.13,
        "liquidity": 0.38, "smart_money": 0.12,
    },
    "security-first": {
        "security": 0.34, "holders": 0.21, "activity": 0.12,
        "liquidity": 0.23, "smart_money": 0.10,
    },
}

PILLAR_ORDER = ["security", "holders", "activity", "liquidity", "smart_money"]
PILLAR_LABEL = {
    "security": "Security", "holders": "Holders", "activity": "Activity",
    "liquidity": "Liquidity", "smart_money": "Smart Money",
}

# Solana-only rebalance applied on top of every preset (see the module docstring
# for the rationale). Deltas sum to 0 so the declared weights still add to 1.0.
SOL_WEIGHT_SHIFT = {"security": -0.06, "holders": 0.03, "liquidity": 0.03}


def apply_chain_weight_shift(weights, chain):
    """Return (weights, applied_shift_or_None) for the chain-specific rebalance."""
    if str(chain or "").lower() not in SOL_ONLY:
        return dict(weights), None
    out = dict(weights)
    applied = {}
    for key, delta in SOL_WEIGHT_SHIFT.items():
        if key in out:
            out[key] = round(out[key] + delta, 6)
            applied[key] = delta
    return out, applied


# Sub-weights (advanced / complete-data coverage).
SUB_W = {
    "security": {
        "mint_authority": 0.20, "freeze_authority": 0.18, "metadata": 0.08,
        "lp_lock": 0.14, "creator_dump": 0.20,
        "not_freezable": 0.05, "not_lst": 0.03, "not_fake": 0.02,
    },
    "holders": {
        "conc_top1": 0.23, "conc_top3": 0.15,
        "conc_top10": 0.17, "holder_base": 0.20,
        "cohort_risk": 0.10, "sniper_density": 0.15,
    },
    "activity": {
        "engagement": 0.40, "buy_pressure": 0.10, "momentum": 0.30,
        "drawdown": 0.20,
        "pace": 0.10,  # only counted when --pace is on
    },
    "liquidity": {
        "depth": 0.30, "stability": 0.25, "valuation": 0.20,
        "trend": 0.15, "pairs": 0.10,
    },
    "smart_money": {
        "sm_presence": 0.25, "sm_flow": 0.30, "sm_quality": 0.20,
        "whale": 0.15, "kol": 0.10,
    },
}

RATING_BANDS = [("A+", 95), ("A", 85), ("B+", 80), ("B", 70), ("C+", 65),
                ("C", 55), ("D", 40), ("E", 20), ("F", 0)]
# Each band gets a distinct risk label — deliberately NON-advisory (no buy/sell
# language). Bands are ordered most -> least attractive, so the wording also
# grades monotonically.
RATING_VERDICT = {
    "A+": "🔥 HOT", "A": "🟢 STRONG", "B+": "🟢 OK", "B": "🟢 FAIR",
    "C+": "🟡 WATCH", "C": "🟡 CAUTION", "D": "🟠 RISKY",
    "E": "🔴 HIGH RISK", "F": "⛔ CRITICAL",
}

# Solana-only named checks ("flags are always false on EVM" -> N/A, not scored).
LST_SYMBOLS = {"wsol", "msol", "jupsol", "jitosol", "bsol", "inf", "hsol",
               "lst", "stsol", "scnsol", "bnsol", "vsol", "dsol"}
KNOWN_MINTS = {
    "So11111111111111111111111111111111111111112": "SOL",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "mSOL",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "WIF",
    "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": "POPCAT",
}


# ===========================================================================
# small helpers
# ===========================================================================

def _f(v, default=None):
    try:
        if v is None or v == "" or isinstance(v, bool):
            return default
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return default
        return fv
    except (TypeError, ValueError):
        return default


def _clamp01(x):
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _ramp(x, lo, hi):
    """Linear ramp lo->hi mapped to 0..1 (clamped)."""
    if hi == lo:
        return 0.0
    return _clamp01((x - lo) / (hi - lo))


def _smooth(t):
    """smoothstep — C1 continuous, no visible kink (smooth penalty ramping)."""
    t = _clamp01(t)
    return t * t * (3.0 - 2.0 * t)


def _ramp_s(x, lo, hi):
    return _smooth(_ramp(x, lo, hi))


def _ramp_log(x, lo, hi):
    """Log10 ramp lo->hi mapped to 0..1 (clamped).

    Liquidity / market-cap magnitudes span 3+ orders of magnitude, so a linear
    ramp would saturate almost immediately (e.g. every $20k-$1M token pinned at
    max). Log spacing spreads the score evenly across the realistic range.
    """
    if not x or x <= 0 or lo <= 0 or hi <= 0 or hi == lo:
        return 0.0
    return _clamp01((math.log10(x) - math.log10(lo)) /
                    (math.log10(hi) - math.log10(lo)))


def _ramp_log_s(x, lo, hi):
    return _smooth(_ramp_log(x, lo, hi))


def _r1(x):
    return round(float(x), 1)


def _wmean(pairs):
    """Weighted mean that drops None scores and removes their weight.

    pairs: list of (weight, score_or_None)
    returns (score_or_None, coverage_0_1)
    """
    num = 0.0
    den = 0.0
    total = 0.0
    for w, s in pairs:
        total += w
        if s is None:
            continue
        num += w * float(s)
        den += w
    if den <= 0:
        return None, 0.0
    return num / den, (den / total if total else 0.0)


def _quantile(sorted_vals, p):
    """Linear-interpolated quantile on an already-sorted list."""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return sorted_vals[0]
    idx = max(0.0, min(1.0, float(p))) * (n - 1)
    lo = int(math.floor(idx))
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def _series_stats(vals):
    """Summary statistics for one liquidity series (1 value per candle).

    `vals` is ordered oldest -> newest, so `current` = last value.
    Returns the min / high / current / drawdown block plus dispersion and
    trend used by the UI liquidity panel.
    """
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    cur, first = vals[-1], vals[0]
    mn, mx = s[0], s[-1]
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    std = math.sqrt(var)
    return {
        "current": _r1(cur),
        "first": _r1(first),
        "min": _r1(mn),
        "max": _r1(mx),
        "median": _r1(_quantile(s, 0.50)),
        "mean": _r1(mean),
        "std": _r1(std),
        "std_pct_of_mean": _r1(100.0 * std / mean) if mean > 0 else None,
        # (max - min) / max — how far the pool swung inside the window
        "drawdown_pct": _r1(100.0 * (mx - mn) / mx) if mx > 0 else None,
        # (max - current) / max — how far below the window peak we sit now
        "drawdown_from_peak_pct": _r1(100.0 * (mx - cur) / mx) if mx > 0 else None,
        "trend_pct": _r1(100.0 * (cur - first) / first) if first > 0 else None,
        "candles": n,
    }


_RESOLUTION_HOURS = {"1m": 1 / 60.0, "5m": 5 / 60.0, "15m": 0.25, "30m": 0.5,
                     "1h": 1.0, "2h": 2.0, "4h": 4.0, "6h": 6.0, "8h": 8.0,
                     "12h": 12.0, "1d": 24.0, "1D": 24.0, "1w": 168.0}


def _span_hours(resolution, count):
    return _r1(_RESOLUTION_HOURS.get(str(resolution), 0.25) * int(count or 0))


def _fmt_usd(v, nd=1):
    if v is None:
        return "N/A"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e9:
        return f"{sign}${a/1e9:.{nd}f}B"
    if a >= 1e6:
        return f"{sign}${a/1e6:.{nd}f}M"
    if a >= 1e3:
        return f"{sign}${a/1e3:.{nd}f}K"
    if a >= 1:
        return f"{sign}${a:.2f}"
    if 0 < a < 1e-7:
        return f"{sign}${a:.2e}"
    if 0 < a < 1e-4:
        return f"{sign}${a:.7f}".rstrip("0").rstrip(".")
    return f"{sign}${a:.6f}".rstrip("0").rstrip(".")


def _fmt_usd_short(v):
    """USD for the UI: K/M/B above `$1 000`, 1 decimal below."""
    if v is None:
        return "N/A"
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return str(v)
    return _fmt_usd(fv, 1) if abs(fv) >= 1e3 else f"{'-' if fv < 0 else ''}${abs(fv):.1f}"


def _web_chain(chain):
    return CHAINS.get(str(chain or "").lower(), str(chain or "solana"))


def _birdeye_token_url(chain, address, tab="holders"):
    return f"https://birdeye.so/{_web_chain(chain)}/token/{address}?tab={tab}&trades_layout=table"


def _birdeye_wallet_url(chain, wallet, tab="pnl"):
    return f"https://birdeye.so/{_web_chain(chain)}/wallet-analyzer/{wallet}?tab={tab}"


def _pct(v, nd=1):
    if v is None:
        return "N/A"
    return f"{float(v):.{nd}f}%"


def _num(v, nd=1):
    if v is None:
        return "N/A"
    return f"{float(v):,.{nd}f}"


def _clean_urlish(v):
    if v is None:
        return ""
    s = str(v).strip().strip("`").strip('"').strip("'").strip()
    return s if s.startswith(("http://", "https://")) else s


def rating_of(score):
    if score is None:
        return "F"
    for name, floor in RATING_BANDS:
        if score >= floor:
            return name
    return "F"


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
    """Tiny Birdeye client that also accumulates CU cost."""

    def __init__(self, key, chain="sol", timeout=25):
        self.key = key
        self.chain = chain
        self.timeout = timeout
        self.calls = []          # [(path, cu, ok, note)]

    def get(self, path, params, cu):
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
        self.calls.append((path, cu, True, ""))
        if isinstance(body, dict) and body.get("success") is False:
            raise RuntimeError(f"{label}: success=false {str(body)[:160]}")
        return body.get("data") if isinstance(body, dict) and "data" in body else body

    def post(self, path, payload, cu):
        label = path.rsplit("/", 1)[-1]
        url = f"{BIRDEYE_BASE}{path}"
        body_raw = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body_raw, method="POST", headers={
            "X-API-KEY": self.key,
            "x-chain": CHAINS.get(self.chain, self.chain),
            "Accept": "application/json",
            "Content-Type": "application/json",
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
        self.calls.append((path, cu, True, ""))
        if isinstance(body, dict) and body.get("success") is False:
            raise RuntimeError(f"{label}: success=false {str(body)[:160]}")
        return body.get("data") if isinstance(body, dict) and "data" in body else body


# ===========================================================================
# Fetch layer
# ===========================================================================

def fetch_overview(api, address):
    return api.get("/defi/token_overview",
                   {"address": address, "includes": "money_flow"}, 21) or {}


def fetch_security(api, address):
    return api.get("/defi/token_security", {"address": address}, 30) or {}


def fetch_distribution(api, address, top_n=20):
    return api.get("/holder/v1/distribution",
                   {"token_address": address, "mode": "top",
                    "top_n": top_n, "include_list": "true"}, 30) or {}


def fetch_holder_profile(api, address):
    return api.get("/token/v1/holder-profile",
                   {"token_address": address, "include_zero_balance": "false"}, 30) or {}


def fetch_top_holders(api, address, limit=100, offset=0, get_holder_infos=True):
    return api.get("/defi/v3/token/holder",
                   {"address": address, "mode": "wallet",
                    "limit": min(int(limit), 100), "offset": max(int(offset), 0),
                    "get_holder_infos": "true" if get_holder_infos else "false",
                    "ui_amount_mode": "raw"}, 30) or {}


def fetch_token_money_flow(api, address, frames=None, wallet_tags=None):
    frames = list(frames or KEY_FRAMES)
    wallet_tags = list(wallet_tags or ["smart_money", "whales", "kol"])
    return api.post("/defi/v3/token/money-flow",
                    {"token_address": address, "frames": frames,
                     "wallet_tags": wallet_tags}, 10) or {}


def fetch_top_traders(api, address, limit=10, sort_by="volume"):
    # /defi/v2/tokens/top_traders accepts only sort_by=volume|trade and limit 1-10.
    d = api.get("/defi/v2/tokens/top_traders",
                {"address": address, "time_frame": "24h", "sort_by": sort_by,
                 "limit": min(int(limit), 10)}, 30)
    if isinstance(d, dict):
        return d.get("items") or d.get("rows") or d.get("traders") or []
    return d or []


def fetch_smart_money(api, address):
    d = api.get("/smart-money/v1/token/list",
                {"limit": 20, "sort_by": "smart_traders_no",
                 "sort_type": "desc", "time_range": "1d"}, 20)
    rows = d if isinstance(d, list) else (d or {}).get("items") or (d or {}).get("rows") or []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        if row.get("address") == address or row.get("token") == address:
            row = dict(row)
            row.setdefault("_list_rank", i)
            return row
    return {}


def fetch_liquidity_ohlc(api, address, resolution="15m", count=96):
    d = api.get("/defi/v3/liquidity/ohlc/token",
                {"address": address, "resolution": resolution,
                 "direction": "back", "count": count}, 30) or {}
    items = d.get("items") if isinstance(d, dict) else d
    return _normalize_liquidity_ohlc(items or [], resolution=resolution, count=count)


def fetch_liquidity_latest(api, address):
    """Live total / exit / stable liquidity + price for one Solana token.

    `POST /defi/v3/liquidity/latest/token` (Solana only, CU = ceil(5 * n^0.8)).
    Unlike the OHLC endpoint this is a true snapshot, so the *current* liquidity
    no longer has to be inferred from the last bar close.
    """
    d = api.post("/defi/v3/liquidity/latest/token", {"addresses": [address]}, 5) or {}
    items = d.get("items") if isinstance(d, dict) else d
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    return {}


# ===========================================================================
# overview accessors
# ===========================================================================

def ov_get(ovd, base, frame):
    """Read `{base}{frame}...` tolerating the casing quirks of token_overview."""
    if not isinstance(ovd, dict):
        return None
    for suffix in (f"{frame}USD", f"{frame}Usd", frame):
        for key in (f"{base}{suffix}", f"{base}_{suffix}"):
            if key in ovd:
                return _f(ovd.get(key))
    return None


def pc_get(ovd, frame):
    if not isinstance(ovd, dict):
        return None
    for key in (f"priceChange{frame}Percent", f"priceChange_{frame}_percent",
                f"priceChange{frame}"):
        if key in ovd:
            return _f(ovd.get(key))
    return None


def _change_pct_get(ovd, stems, frame):
    """Read `foo{frame}ChangePercent` with a few tolerated naming variants."""
    if not isinstance(ovd, dict):
        return None
    if isinstance(stems, str):
        stems = [stems]
    suffixes = (
        f"{frame}ChangePercent", f"{frame}_change_percent",
        f"{frame}ChangePct", f"{frame}_change_pct",
    )
    for stem in stems:
        for suffix in suffixes:
            for key in (
                f"{stem}{suffix}",
                f"{stem}_{suffix}",
                f"{suffix}{stem[:1].upper()}{stem[1:]}" if stem else None,
            ):
                if key and key in ovd:
                    return _f(ovd.get(key))
    return None


def vol_change_get(ovd, frame):
    return _change_pct_get(ovd, ["v", "volume"], frame)


def wallet_change_get(ovd, frame):
    return _change_pct_get(ovd, ["uniqueWallet", "wallet"], frame)


def trade_change_get(ovd, frame):
    return _change_pct_get(ovd, ["trade", "tx", "totalTx"], frame)


def trade_count_get(ovd, frame):
    direct = ov_get(ovd, "trade", frame)
    if direct is not None:
        return direct
    buy = ov_get(ovd, "buy", frame)
    sell = ov_get(ovd, "sell", frame)
    if buy is not None or sell is not None:
        return (buy or 0.0) + (sell or 0.0)
    return None


def _frame_minutes(frame):
    return {"1m": 1, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "24h": 1440}.get(str(frame))


def _candle_unix_ts(c):
    if not isinstance(c, dict):
        return None
    for key in ("unix_time", "unixTime", "time"):
        v = _f(c.get(key))
        if v is not None:
            return int(v)
    ts = c.get("timestamp")
    if ts is None:
        return None
    try:
        return int(_dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def _normalize_liquidity_ohlc(candles, resolution="15m", count=96):
    """Keep the latest contiguous OHLC window ordered oldest -> newest.

    Birdeye liquidity OHLC may arrive newest -> oldest and can include sparse
    older candles beyond the intended recent window. We normalize order and
    discard older discontinuous rows so `current`, drawdown, and frame changes
    are computed from the actual latest window instead of stale tail rows.
    """
    rows = [c for c in (candles or []) if isinstance(c, dict)]
    if len(rows) <= 1:
        return rows
    rows_with_ts = [(c, _candle_unix_ts(c)) for c in rows]
    if not any(ts is not None for _, ts in rows_with_ts):
        return rows
    rows_sorted = [c for c, _ in sorted(
        rows_with_ts,
        key=lambda it: (-1 if it[1] is None else it[1],)
    )]
    step_mins = _frame_minutes(resolution) or 15
    step_sec = step_mins * 60
    max_gap_sec = int(step_sec * 2.5)
    keep = []
    prev_ts = None
    for c in reversed(rows_sorted):
        ts = _candle_unix_ts(c)
        if ts is None:
            if not keep:
                keep.append(c)
            continue
        if prev_ts is not None and (prev_ts - ts) > max_gap_sec:
            break
        keep.append(c)
        prev_ts = ts
        if len(keep) >= max(1, int(count or 0)):
            break
    keep.reverse()
    return keep or rows_sorted[-max(1, int(count or len(rows_sorted))):]


def _liquidity_changes_from_candles(candles, resolution, frames):
    """Approximate liquidity % change over target windows from OHLC closes."""
    candles = _effective_liquidity_candles(candles)
    vals = []
    for c in candles or []:
        if not isinstance(c, dict):
            continue
        v = _f(c.get("close_liquidity_usd"))
        if v is not None:
            vals.append(v)
    step_mins = _frame_minutes(resolution)
    if len(vals) < 2 or not step_mins:
        return {f: None for f in frames}
    out = {}
    for frame in frames:
        mins = _frame_minutes(frame)
        if not mins or mins < step_mins:
            out[frame] = None
            continue
        steps = max(1, int(round(mins / step_mins)))
        prev = vals[0] if steps >= len(vals) else vals[-(steps + 1)]
        cur = vals[-1]
        out[frame] = _r1(100.0 * (cur - prev) / prev) if prev and prev > 0 else None
    return out


def _effective_liquidity_candles(candles):
    rows = [c for c in (candles or []) if isinstance(c, dict)]
    if not rows:
        return rows
    start = 0
    for i, c in enumerate(rows):
        liq = _f(c.get("close_liquidity_usd"))
        ex = _f(c.get("close_exit_liquidity_usd"))
        if (liq is not None and liq > 0) or (ex is not None and ex > 0):
            start = i
            break
    return rows[start:]


def _ohlc_last(candles, key):
    """Last non-null numeric value for `key` in an ordered candle list."""
    out = None
    for c in candles or []:
        if not isinstance(c, dict):
            continue
        v = _f(c.get(key))
        if v is not None:
            out = v
    return out


def _last_candle_age_seconds(candles, resolution, request_time):
    """Seconds between the last OHLC bar close and the request time.

    Liquidity OHLC timestamps mark the bar *open*, so the close is one step
    later. Returns None when the timestamps are missing.
    """
    rows = [c for c in (candles or []) if isinstance(c, dict)]
    if not rows:
        return None
    ts = _candle_unix_ts(rows[-1])
    if ts is None:
        return None
    step_sec = (_frame_minutes(resolution) or 15) * 60
    return max(0, int(int(request_time or time.time()) - (int(ts) + step_sec)))


def _liq_snapshot(ovd, latest, candles, resolution="15m", request_time=None):
    """Resolve the *current* liquidity + exit liquidity for the score and UI.

    Total liquidity : token_overview.liquidity -> liquidity/latest -> OHLC close
    Exit liquidity  : liquidity/latest.exit_liquidity_usd -> OHLC close

    `token_overview` is the live snapshot every chain exposes, so the score stops
    comparing a live overview figure against a stale OHLC close. `liquidity/latest`
    adds live exit liquidity on Solana. The OHLC bar close is only a fallback and,
    when used, its staleness (seconds before the request) is recorded so the UI can
    label the value "N s/m ago (OHLC close)" instead of presenting it as live.
    """
    req = int(request_time or time.time())
    latest = latest or {}
    ov_liq = _f((ovd or {}).get("liquidity"))
    snap_liq = _f(latest.get("liquidity_usd"))
    snap_exit = _f(latest.get("exit_liquidity_usd"))
    rows = _effective_liquidity_candles(candles)
    ohlc_liq = _ohlc_last(rows, "close_liquidity_usd")
    ohlc_exit = _ohlc_last(rows, "close_exit_liquidity_usd")
    age = _last_candle_age_seconds(rows, resolution, req)

    if ov_liq is not None:
        liq, liq_src = ov_liq, "token_overview"
    elif snap_liq is not None:
        liq, liq_src = snap_liq, "liquidity/latest"
    elif ohlc_liq is not None:
        liq, liq_src = ohlc_liq, "ohlc_close"
    else:
        liq, liq_src = None, None

    if snap_exit is not None:
        ex, ex_src = snap_exit, "liquidity/latest"
    elif ohlc_exit is not None:
        ex, ex_src = ohlc_exit, "ohlc_close"
    else:
        ex, ex_src = None, None

    return {
        "liquidity": liq,
        "liquidity_source": liq_src,
        "liquidity_age_seconds": age if liq_src == "ohlc_close" else None,
        "exit_liquidity": ex,
        "exit_liquidity_source": ex_src,
        "exit_liquidity_age_seconds": age if ex_src == "ohlc_close" else None,
        "stable_liquidity": _f(latest.get("stable_liquidity_usd")),
        "request_time": req,
    }


def _merge_money_flow_maps(primary, fallback):
    out = json.loads(json.dumps(primary or {}, ensure_ascii=False))
    extra = fallback or {}
    for tag, frames in extra.items():
        if not isinstance(frames, dict):
            continue
        tgt = out.setdefault(tag, {})
        for frame, cell in frames.items():
            if not isinstance(cell, dict):
                continue
            cur = tgt.setdefault(frame, {})
            for k, v in cell.items():
                if cur.get(k) is None and v is not None:
                    cur[k] = v
    return out


def frames_coverage(ovd):
    got = [f for f in FRAMES if pc_get(ovd, f) is not None
           or ov_get(ovd, "v", f) is not None]
    return got


def _flow_block(ovd, candles=None, liq_resolution="15m", liq_snapshot=None):
    """Price change + money flow per frame, straight from the overview payload.

    `moneyFlow[]` is a (frame × tag) grid where tag splits the flow by cohort —
    `all`, `smart_money`, `whales`, `kol`. Returns the `flow` block the UI/JSON
    expose (key_intervals = 5m/1h/4h/24h plus every frame), and stashes the 24 h
    net flow back onto `ovd` (`_mf_net_24h` for all traders, `_mf_tag_net_24h`
    per cohort) so the Activity and Smart-Money pillars reuse it at 0 extra CU.
    """
    rows = ovd.get("moneyFlow") or ovd.get("money_flow") or []
    by_tag = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("frame"), str):
            continue
        tag = str(row.get("tag") or "all")
        frame = row["frame"]
        b = _f(row.get("totalValueBuy") if row.get("totalValueBuy") is not None
               else row.get("volumeBuyUsd") if row.get("volumeBuyUsd") is not None
               else row.get("buyVolumeUsd") if row.get("buyVolumeUsd") is not None
               else row.get("buy_usd"))
        s = _f(row.get("totalValueSell") if row.get("totalValueSell") is not None
               else row.get("volumeSellUsd") if row.get("volumeSellUsd") is not None
               else row.get("sellVolumeUsd") if row.get("sellVolumeUsd") is not None
               else row.get("sell_usd"))
        by_tag.setdefault(tag, {})[frame] = {
            "buy_usd": b, "sell_usd": s,
            "net_usd": (b - s) if (b is not None and s is not None) else None,
            "tx_buy": _f(row.get("totalTxBuy") if row.get("totalTxBuy") is not None
                         else row.get("txBuy") if row.get("txBuy") is not None
                         else row.get("buyTxCount") if row.get("buyTxCount") is not None
                         else row.get("tx_buy") if row.get("tx_buy") is not None
                         else row.get("buy_count")),
            "tx_sell": _f(row.get("totalTxSell") if row.get("totalTxSell") is not None
                          else row.get("txSell") if row.get("txSell") is not None
                          else row.get("sellTxCount") if row.get("sellTxCount") is not None
                          else row.get("tx_sell") if row.get("tx_sell") is not None
                          else row.get("sell_count")),
            "traders": _f(row.get("uniqTrader") if row.get("uniqTrader") is not None
                          else row.get("traderCount") if row.get("traderCount") is not None
                          else row.get("uniqueTrader") if row.get("uniqueTrader") is not None
                          else row.get("traders")),
        }
    cells = {t: ((by_tag.get(t) or {}).get("24h") or {}) for t in _MF_TAGS}
    ovd["_mf_tag_24h"] = cells
    ovd["_mf_net_24h"] = (cells.get("all") or {}).get("net_usd")
    ovd["_mf_tag_net_24h"] = {t: c.get("net_usd") for t, c in cells.items()}
    # Full (tag × frame) grid so the Smart-Money cohort scoring can read every
    # interval instead of only 24 h. Frames come straight from the overview.
    ovd["_mf_tag_frames"] = {t: dict(frames) for t, frames in by_tag.items()}
    vol_change = {f: vol_change_get(ovd, f) for f in UI_KEY_FRAMES}
    wallet_change = {f: wallet_change_get(ovd, f) for f in UI_KEY_FRAMES}
    trade_change = {f: trade_change_get(ovd, f) for f in UI_KEY_FRAMES}
    liq_change = _liquidity_changes_from_candles(candles, liq_resolution, UI_KEY_FRAMES)
    ovd["_vol_change_pct"] = vol_change
    ovd["_wallet_change_pct"] = wallet_change
    ovd["_trade_change_pct"] = trade_change
    ovd["_liq_change_pct"] = liq_change
    order = _MF_TAGS + [t for t in by_tag if t not in _MF_TAGS]
    snap = liq_snapshot or _liq_snapshot(ovd, None, candles, liq_resolution)
    return {
        "key_intervals": UI_KEY_FRAMES,
        "price_change_pct": {f: pc_get(ovd, f) for f in FRAMES},
        "volume_change_pct": vol_change,
        "wallet_change_pct": wallet_change,
        "trade_change_pct": trade_change,
        "liquidity_change_pct": liq_change,
        "liquidity_now": snap["liquidity"],
        "liquidity_now_source": snap["liquidity_source"],
        "liquidity_now_age_seconds": snap["liquidity_age_seconds"],
        "exit_liquidity_now": snap["exit_liquidity"],
        "exit_liquidity_now_source": snap["exit_liquidity_source"],
        "exit_liquidity_now_age_seconds": snap["exit_liquidity_age_seconds"],
        "volume_value": {f: ov_get(ovd, "v", f) for f in FRAMES},
        "wallet_value": {f: ov_get(ovd, "uniqueWallet", f) for f in FRAMES},
        "trade_value": {f: trade_count_get(ovd, f) for f in FRAMES},
        "money_flow": {t: by_tag[t] for t in order if t in by_tag},
    }


# ===========================================================================
# PILLAR 1 — Security (contract + creator dump power)
# ===========================================================================

def _creator_dump_factors(sec, ovd):
    """creator holding% x transfer/exit power -> (f_hold, f_power, creator_pct)."""
    pct = None
    for k in ("creatorPercentage", "creator_percent", "creatorPercent"):
        v = _f(sec.get(k))
        if v is not None:
            pct = v * 100 if v <= 1.0 else v
            break
    n_auth = 0
    if sec.get("ownerAddress") not in (None, "", "null"):
        n_auth += 1
    if sec.get("freezeAuthority") not in (None, "", "null"):
        n_auth += 1
    if sec.get("mutableMetadata") is True:
        n_auth += 1
    if pct is None:
        return None, None, None
    f_hold = _ramp_s(pct, 5.0, 30.0)
    f_power = 0.6 + 0.4 * (min(n_auth, 3) / 3.0)
    return f_hold, f_power, pct


def score_security(sec, ovd, address="", chain="sol"):
    """Security pillar. Every sub-score is 0..100; None = not measurable."""
    bd = []
    sub = {}

    def put(name, score, detail):
        sub[name] = score
        bd.append({"name": name, "score": None if score is None else _r1(score),
                   "weight": SUB_W["security"][name], "detail": detail})

    is_sol = chain in SOL_ONLY
    honeypot = sec.get("isHoneypot")

    # mint authority -------------------------------------------------------
    owner = sec.get("ownerAddress")
    mintable_evm = sec.get("mintable")
    if owner is not None and not is_sol:
        sc = 0.0 if mintable_evm is True else 100.0
        put("mint_authority", sc, "EVM mintable=" + str(mintable_evm))
    elif owner is not None:
        live = owner not in ("", "null", "0x0000000000000000000000000000000000000000")
        put("mint_authority", 0.0 if live else 100.0,
            ("mint authority LIVE " + str(owner)[:16]) if live else "mint renounced (ownerAddress null)")
    else:
        put("mint_authority", None, "ownerAddress absent -> not measurable")

    # freeze authority -----------------------------------------------------
    if not is_sol:
        put("freeze_authority", None, "Solana only — N/A on EVM")
    else:
        fa = sec.get("freezeAuthority")
        if fa is None and "freezeAuthority" not in sec:
            put("freeze_authority", None, "freezeAuthority absent")
        else:
            live = fa not in (None, "", "null")
            put("freeze_authority", 0.0 if live else 100.0,
                ("freeze LIVE " + str(fa)[:16]) if live else "freeze renounced (null)")

    # mutable metadata -----------------------------------------------------
    mm = sec.get("mutableMetadata")
    if isinstance(mm, bool):
        put("metadata", 100.0 if not mm else 40.0,
            "metadata immutable" if not mm else "metadata mutable — team can rewrite name/logo/socials")
    else:
        put("metadata", None, "mutableMetadata absent")

    # LP lock --------------------------------------------------------------
    lp = sec.get("lpLocked")
    if isinstance(lp, bool):
        put("lp_lock", 100.0 if lp else 0.0,
            "LP locked" if lp else "LP NOT locked — rug by LP pull possible")
    else:
        put("lp_lock", None, "lpLocked absent")

    # creator dump power ---------------------------------------------------
    f_hold, f_power, c_pct = _creator_dump_factors(sec, ovd)
    if f_hold is None:
        put("creator_dump", None, "creatorPercentage absent")
    else:
        sc = 100.0 * (1.0 - f_hold * f_power)
        put("creator_dump", sc,
            f"creator {_pct(c_pct)} x dump-power {f_power:.2f} "
            f"(f_hold={f_hold:.3f}) -> {_r1(sc)}")

    # named checks ---------------------------------------------------------
    if not is_sol:
        put("not_freezable", None, "Solana only — N/A on EVM")
    else:
        ok = (sec.get("freezeAuthority") in (None, "", "null")
              and sec.get("ownerAddress") in (None, "", "null"))
        put("not_freezable", 100.0 if ok else 0.0,
            "not freezable/mintable" if ok else "freeze or mint authority still live")

    sym = str(ovd.get("symbol") or "").strip().lower()
    if not is_sol:
        put("not_lst", None, "Solana only — N/A on EVM")
    elif not sym:
        put("not_lst", None, "symbol absent")
    else:
        put("not_lst", 0.0 if sym in LST_SYMBOLS else 100.0,
            "LST detected — DD flags not meaningful" if sym in LST_SYMBOLS
            else "not a liquid-staking token")

    if address and sym and sym in {v.lower() for v in KNOWN_MINTS.values()} \
            and KNOWN_MINTS.get(address, "").lower() != sym:
        put("not_fake", 0.0, f"symbol '{sym}' impersonates a canonical mint")
    elif not sym:
        put("not_fake", None, "symbol absent")
    else:
        put("not_fake", 100.0, "no impersonation match")

    score, coverage = _wmean([(SUB_W["security"][k], sub.get(k))
                              for k in SUB_W["security"]])

    hard = []
    if honeypot is True:
        hard.append({"name": "honeypot", "detail": "isHoneypot=true (EVM)"})
        score = 0.0
    return {"score": None if score is None else _r1(score),
            "coverage": round(coverage, 3),
            "breakdown": bd, "hard_blocks": hard}


# ===========================================================================
# PILLAR 2 — Holders (concentration + cohort risk)
# ===========================================================================

def _concentration(dist, sec, top_n=20):
    """Return dict of top1/top3/top5/top10/top20 pct using ONE list-wide scale."""
    out = {k: None for k in ("top1", "top3", "top5", "top10", "top20")}
    rows = ((dist or {}).get("holders") or (dist or {}).get("rows")
            or (dist or {}).get("items") or [])
    pcts = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = _f(r.get("percent_of_supply"))
        if v is None:
            v = _f(r.get("percentage"))
            v = v * 100 if v is not None and v <= 1.0 else v
        if v is not None:
            pcts.append(v)
    if pcts:
        pcts.sort(reverse=True)
        # single scale for the whole list — never per-row (documented bug fix)
        out["top1"] = pcts[0]
        out["top3"] = sum(pcts[:3])
        out["top5"] = sum(pcts[:5])
        out["top10"] = sum(pcts[:10])
        out["top20"] = sum(pcts[:min(top_n, len(pcts))])

    agg = {("top5", "top5_pct"), ("top10", "top10_pct"), ("top20", "top20_pct")}
    for key, field in agg:
        if out[key] is None:
            v = _f((dist or {}).get(field))
            if v is not None:
                out[key] = v * 100 if v <= 1.0 else v
    if out["top10"] is None:
        v = None
        for k in ("top10UserPercent", "top10HolderPercent", "topHoldersPercent"):
            v = _f(sec.get(k)) if sec else None
            if v is not None:
                break
        if v is not None:
            out["top10"] = v * 100 if v <= 1.0 else v
            out["top10_source"] = "token_security.top10HolderPercent"
    return out


def _tags_map(profile):
    """holder-profile returns `tags` as a LIST of {tag:...} rows (not a dict)."""
    raw = (profile or {}).get("tags") if isinstance(profile, dict) else None
    if isinstance(raw, dict):
        return raw
    out = {}
    for row in raw if isinstance(raw, list) else []:
        if isinstance(row, dict) and row.get("tag"):
            out[row["tag"]] = row
    return out


def score_holders(conc, ovd, profile, top_holders):
    bd = []
    sub = {}

    def put(name, score, detail):
        sub[name] = score
        bd.append({"name": name, "score": None if score is None else _r1(score),
                   "weight": SUB_W["holders"][name], "detail": detail})

    ramps = {"conc_top1": (10, 95), "conc_top3": (20, 98),
             "conc_top10": (20, 100)}
    for key, (lo, hi) in ramps.items():
        v = conc.get(key.replace("conc_", ""))
        if v is None:
            put(key, None, "not available in this mode")
            continue
        sc = 100.0 * (1.0 - _ramp_s(v, lo, hi))
        put(key, sc, f"{_pct(v)} held (penalty ramp {lo}%->{hi}%)")

    hc = _f(ovd.get("holder") if isinstance(ovd, dict) else None)
    if hc is None or hc <= 0:
        put("holder_base", None, "holder count absent")
    else:
        sc = 100.0 * _ramp_s(math.log10(hc), 1.7, 3.7)
        put("holder_base", sc, f"{hc:,.0f} holders (log10 ramp 50->5000)")

    tags = _tags_map(profile)
    if not tags:
        put("cohort_risk", None, "holder-profile absent (advanced only)")
        put("sniper_density", None, "holder-profile absent (advanced only)")
    else:
        def tag_pct(name):
            t = tags.get(name) or {}
            v = _f(t.get("percent_of_supply"))
            return v if v is not None else 0.0

        risk_share = tag_pct("dev") + tag_pct("sniper") + tag_pct("bundler")
        isinsider = tag_pct("insider")
        sc = 100.0 * (1.0 - _ramp_s(risk_share, 5.0, 35.0))
        put("cohort_risk", sc,
            f"dev+sniper+bundler={_pct(risk_share)} insider={_pct(isinsider)} "
            f"(ramp 5%->35%)")
        snipers = _f((tags.get("sniper") or {}).get("holder_count"))
        if snipers is None:
            put("sniper_density", None, "sniper.holder_count absent")
        else:
            sc = 100.0 * (1.0 - _ramp_s(snipers, 5.0, 20.0))
            put("sniper_density", sc, f"{snipers:,.0f} sniper wallets (ramp 5->20)")

    weights = dict(SUB_W["holders"])
    score, coverage = _wmean([(weights[k], sub.get(k)) for k in weights])

    cohorts = {}
    if tags:
        for t in ("dev", "bundler", "sniper", "insider", "smart_trader", "kol"):
            row = tags.get(t) or {}
            cohorts[t] = {
                "pct_of_supply": _f(row.get("percent_of_supply")),
                "holder_count": _f(row.get("holder_count")),
                "pnl_usd": _f(row.get("pnl_usd") if row.get("pnl_usd") is not None
                              else row.get("pnl")),
            }
    return {"score": None if score is None else _r1(score), "coverage": round(coverage, 3),
            "breakdown": bd, "top": conc, "cohorts": cohorts,
            "hard_blocks": []}


# ===========================================================================
# PILLAR 3 — Activity (token_overview only)
# ===========================================================================

def score_activity(ovd, pace_on=False):
    bd = []
    sub = {}

    def put(name, score, detail):
        sub[name] = score
        bd.append({"name": name, "score": None if score is None else _r1(score),
                   "weight": SUB_W["activity"][name], "detail": detail})

    v24 = _f(ovd.get("v24hUSD"))
    mc = _f(ovd.get("marketCap"))
    liq = _f(ovd.get("liquidity"))
    trades = _f(ovd.get("trade24h"))
    wallets24 = _f(ovd.get("uniqueWallet24h"))

    # --- engagement ------------------------------------------------------
    # Ramp anchors are percentile-calibrated on the filtered ALIVE cohort of
    # new_solana.csv:
    #   liquidity >= $1k, marketCap/liquidity <= 10, volume_30d > 0,
    #   plus junk/dead trimming: volume_24h >= $1 and liquidity >= $100
    #   (n = 18,101).
    # Anchors use p50 -> p95 of the non-zero subset, so the median active token
    # only starts contributing and the top 5% saturate the ramp.
    parts = []
    if trades is not None:
        parts.append(("trades 24h", _ramp_log_s(trades, 20.0, 15000.0)))
    if v24 is not None and liq:
        parts.append(("vol/liquidity", _ramp_s(v24 / liq, 0.01, 3.0)))
    if v24 is not None and mc:
        parts.append(("mcap turnover", _ramp_s(v24 / mc, 0.0075, 1.62)))
    if wallets24 is not None:
        parts.append(("unique wallets 24h", _ramp_s(wallets24, 3.0, 353.0)))
    if parts:
        sc = 100.0 * sum(v for _, v in parts) / len(parts)
        detail = []
        if trades is not None:
            detail.append(f"trades24h={_num(trades, 0)}")
        if v24 is not None and liq:
            detail.append(f"vol/liquidity={v24 / liq:.2f}x")
        if v24 is not None and mc:
            detail.append(f"vol/mcap={v24 / mc * 100:.2f}%")
        if wallets24 is not None:
            detail.append(f"unique wallets 24h={_num(wallets24, 0)}")
        put("engagement", sc, " | ".join(detail) + f" -> {sc:.0f}/100")
    else:
        put("engagement", None, "volume/trade/liquidity fields absent")

    # --- buy pressure ----------------------------------------------------
    bp_pairs = []
    for frame, w in BUY_FRAMES:
        b = ov_get(ovd, "vBuy", frame)
        s = ov_get(ovd, "vSell", frame)
        if b is None or s is None or (b + s) <= 0:
            continue
        bp = b / (b + s)
        bp_pairs.append((w, 100.0 * _clamp01((bp - 0.43) / 0.24), bp))
    mf_net = _f(ovd.get("_mf_net_24h"))
    if not bp_pairs:
        put("buy_pressure", None, "vBuy*USD / vSell*USD absent")
    else:
        # optional money-flow tilt (from moneyFlow frames, same call)
        flow_sc = None
        if mf_net is not None and v24:
            flow_sc = 100.0 * _ramp_s(mf_net / v24, -0.10, 0.15)
        wsum = sum(w for w, _, _ in bp_pairs)
        press = sum(w * s for w, s, _ in bp_pairs) / wsum
        note = "buy-ratio " + ", ".join(
            f"{frame}={bp_pairs[i][2]:.3f}" for i, (frame, _) in enumerate(BUY_FRAMES)
            if i < len(bp_pairs))
        if flow_sc is None:
            sc = press
        else:
            sc = 0.90 * press + 0.10 * flow_sc
            note += f" | net-flow24h={_fmt_usd(mf_net)}"
        put("buy_pressure", sc, note)

    # --- momentum (price + vol + wallets + liquidity changes) -------------
    m_parts = []
    comp_w = {"price": 0.30, "volume": 0.35, "wallets": 0.25, "liquidity": 0.10}
    for frame, w in MOMENTUM_FRAMES:
        comps = []
        pc = pc_get(ovd, frame)
        vc = (ovd.get("_vol_change_pct") or {}).get(frame)
        wc = (ovd.get("_wallet_change_pct") or {}).get(frame)
        lc = (ovd.get("_liq_change_pct") or {}).get(frame)
        if pc is not None:
            comps.append(("price", comp_w["price"], math.tanh(pc / 35.0), pc))
        if vc is not None:
            comps.append(("volume", comp_w["volume"], math.tanh(vc / 90.0), vc))
        if wc is not None:
            comps.append(("wallets", comp_w["wallets"], math.tanh(wc / 60.0), wc))
        if lc is not None:
            comps.append(("liquidity", comp_w["liquidity"], math.tanh(lc / 40.0), lc))
        if not comps:
            continue
        c_wsum = sum(cw for _, cw, _, _ in comps)
        m_parts.append((frame, w,
                        sum(cw * t for _, cw, t, _ in comps) / c_wsum,
                        comps))
    if not m_parts:
        put("momentum", None, "price / volume / wallet / liquidity change absent")
    else:
        wsum = sum(w for _, w, _, _ in m_parts)
        m = sum(w * t for _, w, t, _ in m_parts) / wsum
        note = []
        short = {"price": "p", "volume": "v", "wallets": "w", "liquidity": "l"}
        for frame, _, t, comps in m_parts:
            comp_note = " ".join(
                f"{short[name]}={value:+.1f}%->{tone:+.3f}"
                for name, _, tone, value in comps
            )
            note.append(f"{frame}[{comp_note}]=>{t:+.3f}")
        put("momentum", 50.0 + 50.0 * m, " | ".join(note))

    # --- drawdown (price risk across nested windows) ---------------------
    # token_overview only exposes % change per window, so the drawdown proxy is
    # the gap between a longer window and a shorter one nested inside it:
    #   giveback = pc_long - pc_short   (percentage points)
    # A positive gap means the token already gave back part of a longer-window
    # run; a sharp fall inside the shortest window is risk on its own. Both are
    # smooth ramps, and the worst of them drives the sub-score.
    dd = []
    for long_f, short_f in (("24h", "1h"), ("24h", "4h"), ("4h", "1h")):
        pl, ps = pc_get(ovd, long_f), pc_get(ovd, short_f)
        if pl is None or ps is None:
            continue
        giveback = max(0.0, pl - ps)
        dd.append((f"giveback {long_f}->{short_f}", giveback,
                   _ramp_s(giveback, 12.0, 65.0)))
    pc_short = pc_get(ovd, "1h")
    if pc_short is not None:
        dd.append(("1h sell-off", -pc_short, _ramp_s(-pc_short, 15.0, 60.0)))
    if not dd:
        put("drawdown", None, "price change frames absent")
    else:
        risk = max(r for _, _, r in dd)
        put("drawdown", 100.0 * (1.0 - risk),
            " | ".join(f"{label}={value:+.1f}%->risk {r:.2f}" for label, value, r in dd)
            + f" -> worst risk {risk:.2f}")

    # --- pace (Phase 2 — OFF by default) ---------------------------------
    weights = dict(SUB_W["activity"])
    if pace_on:
        pace_parts = []
        for label, short, long in (("1h", "5m", "30m"), ("4h", "30m", "1h"),
                                   ("24h", "1h", "4h")):
            ws, wl = ov_get(ovd, "uniqueWallet", short), ov_get(ovd, "uniqueWallet", long)
            vs, vl = ov_get(ovd, "v", short), ov_get(ovd, "v", long)
            mins = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60,
                    "2h": 120, "4h": 240, "24h": 1440}
            score_pair = []
            if ws and wl:
                score_pair.append((ws / mins[short]) / (wl / mins[long]))
            if vs and vl:
                score_pair.append((vs / mins[short]) / (vl / mins[long]))
            if score_pair:
                r = sum(score_pair) / len(score_pair)
                pace_parts.append(_clamp01((r - 0.8) / 1.2))
        if pace_parts:
            put("pace", 100.0 * sum(pace_parts) / len(pace_parts),
                f"{len(pace_parts)} pace windows (short-vs-long per-min rate)")
        else:
            put("pace", None, "pace windows unavailable")
    else:
        weights.pop("pace", None)

    score, coverage = _wmean([(weights[k], sub.get(k)) for k in weights])
    return {"score": None if score is None else _r1(score), "coverage": round(coverage, 3),
            "breakdown": bd, "hard_blocks": []}


# ===========================================================================
# PILLAR 4 — Liquidity (depth / stability / valuation / trend / pairs)
# ===========================================================================

def score_liquidity(ovd, candles, resolution="15m", latest=None, request_time=None):
    bd = []
    sub = {}

    def put(name, score, detail):
        sub[name] = score
        bd.append({"name": name, "score": None if score is None else _r1(score),
                   "weight": SUB_W["liquidity"][name], "detail": detail})

    mc = _f(ovd.get("marketCap"))

    rows = _effective_liquidity_candles(candles)
    closes, exits, pairs = [], [], []
    for c in rows:
        if not isinstance(c, dict):
            continue
        v = _f(c.get("close_liquidity_usd"))
        e = _f(c.get("close_exit_liquidity_usd"))
        if v is not None:
            closes.append(v)
        if e is not None:
            exits.append(e)
        p = _f(c.get("total_pairs"))
        if p is not None:
            pairs.append(p)

    # `current` comes from the live snapshot (overview / liquidity-latest); the
    # OHLC series is only used for the time-series reads below (stability, trend).
    snap = _liq_snapshot(ovd, latest, candles, resolution, request_time)
    liq_now = snap["liquidity"]
    exit_now = snap["exit_liquidity"]

    # --- depth -----------------------------------------------------------
    depth = []
    if liq_now is not None:
        depth.append((0.45, 100.0 * _ramp_log_s(liq_now, 1500.0, 800000.0),
                      f"liquidity {_fmt_usd(liq_now)} (log ramp 1.5K->800K)"))
    if exit_now is not None:
        depth.append((0.55, 100.0 * _ramp_log_s(exit_now, 1000.0, 400000.0),
                      f"exit liquidity {_fmt_usd(exit_now)} (log ramp 1K->400K)"))
    if depth:
        wsum = sum(w for w, _, _ in depth)
        sc = sum(w * s for w, s, _ in depth) / wsum
        put("depth", sc, " | ".join(d for _, _, d in depth))
        if exit_now is None:
            sub["_depth_note"] = "exit liquidity unavailable — depth from total liquidity only"
    else:
        put("depth", None, "liquidity absent")

    # --- stability (24h OHLC series) -------------------------------------
    if len(closes) >= 8 and len(exits) >= 8:
        dd_liq = (max(closes) - min(closes)) / max(closes) if max(closes) > 0 else 0.0
        dd_exit = (max(exits) - min(exits)) / max(exits) if max(exits) > 0 else 0.0
        floor_r = (min(exits) / exits[-1]) if exits[-1] > 0 else 0.0
        s_ddliq = 100.0 * (1.0 - _ramp_s(dd_liq, 0.10, 0.60))
        s_ddexit = 100.0 * (1.0 - _ramp_s(dd_exit, 0.10, 0.60))
        s_floor = 100.0 * _ramp_s(floor_r, 0.20, 0.90)
        put("stability", 0.35 * s_ddliq + 0.40 * s_ddexit + 0.25 * s_floor,
            f"drawdown_liquidity={dd_liq*100:.1f}% drawdown_exit={dd_exit*100:.1f}% "
            f"exit_floor={floor_r*100:.1f}% of current exit liquidity ({len(closes)} candles)")
    else:
        put("stability", None, "liquidity OHLC series not available (needs >=8 candles)")

    # --- valuation (mcap vs liquidity) -----------------------------------
    val = []
    if liq_now and mc:
        ratio = mc / liq_now
        val.append((0.45, 100.0 * (1.0 - _ramp_log_s(ratio, 20.0, 500.0)),
                    f"mcap/liquidity={ratio:.1f} (log ramp 20->500)"))
    if exit_now and mc:
        ratio = mc / exit_now
        val.append((0.55, 100.0 * (1.0 - _ramp_log_s(ratio, 40.0, 1000.0)),
                    f"mcap/exit={ratio:.1f} (log ramp 40->1K)"))
    if val:
        wsum = sum(w for w, _, _ in val)
        put("valuation", sum(w * s for w, s, _ in val) / wsum,
            " | ".join(d for _, _, d in val))
    else:
        put("valuation", None, "marketCap or liquidity absent")

    # --- trend -----------------------------------------------------------
    if len(closes) >= 8 and closes[0] > 0:
        slope = (closes[-1] - closes[0]) / closes[0]
        put("trend", 100.0 * (0.5 + 0.5 * math.tanh(slope / 0.30)),
            f"liquidity moved {slope*100:+.1f}% over window")
    else:
        put("trend", None, "liquidity OHLC series not available")

    # --- pair diversity --------------------------------------------------
    if pairs:
        put("pairs", 100.0 * _ramp_s(max(pairs), 1.0, 5.0),
            f"{max(pairs):.0f} pair(s) contributing")
    else:
        put("pairs", None, "total_pairs absent")

    score, coverage = _wmean([(SUB_W["liquidity"][k], sub.get(k))
                              for k in SUB_W["liquidity"]])
    stats = None
    if closes:
        stats = {
            "window": {
                "resolution": resolution,
                "candles": len(closes),
                "span_hours": _span_hours(resolution, len(closes)),
                "source": "liquidity/token/ohlc",
            },
            "liquidity": _series_stats(closes),
            "exit_liquidity": _series_stats(exits) if exits else None,
        }
    return {"score": None if score is None else _r1(score), "coverage": round(coverage, 3),
            "breakdown": bd, "stats": stats, "liq_now": liq_now, "exit_now": exit_now,
            "snapshot": snap, "hard_blocks": []}


GATE_LIQ_MAX_PENALTY = 0.10   # liquidity drawdown can cost at most 10 % of the total
GATE_EXIT_MAX_PENALTY = 0.15  # exit-liquidity drawdown at most 15 % (realistic sell side)
GATE_DD_LO = 0.20             # 20 % below the window peak — penalty starts here
GATE_DD_HI = 0.70             # 70 % below the peak — penalty saturates


def liquidity_gate(liquidity_stats=None):
    """Drawdown-driven discount gate — reacts to deterioration, not to size.

    Absolute depth is already scored by the Liquidity pillar, so gating on it too
    penalised the same weakness twice: a token with e.g. $5k exit liquidity scored
    low on `depth` and then lost a further ~25 % of its *total* score. The gate now
    only reads how far liquidity has fallen from its recent peak over the OHLC
    window, and the penalty is deliberately modest (<= 15 % of the total).

    The worst of the two deterioration penalties binds — they are not summed — so a
    thin-but-stable pool keeps its full score and only genuinely bleeding pools are
    discounted.

    Reserved: a future build adds multi-interval holder change as a second
    deterioration input (`holder_change_penalty`); with no data it is None.
    """
    stats = liquidity_stats or {}
    liq = stats.get("liquidity") or {}
    ex = stats.get("exit_liquidity") or {}

    liq_dd = liq.get("drawdown_from_peak_pct")
    exit_dd = ex.get("drawdown_from_peak_pct")

    liq_pen = (GATE_LIQ_MAX_PENALTY * _ramp_s(liq_dd / 100.0, GATE_DD_LO, GATE_DD_HI)
               if liq_dd is not None else 0.0)
    exit_pen = (GATE_EXIT_MAX_PENALTY * _ramp_s(exit_dd / 100.0, GATE_DD_LO, GATE_DD_HI)
                if exit_dd is not None else 0.0)

    pen = max(liq_pen, exit_pen)
    gate = 1.0 - pen
    if pen <= 0.0:
        binding = "none"
    elif exit_dd is not None and exit_pen >= liq_pen:
        binding = "exit_drawdown"
    else:
        binding = "liquidity_drawdown"

    return gate, {
        "gate": round(gate, 3),
        "liquidity_drawdown_pct": _r1(liq_dd) if liq_dd is not None else None,
        "exit_drawdown_pct": _r1(exit_dd) if exit_dd is not None else None,
        "liquidity_penalty": round(liq_pen, 3),
        "exit_penalty": round(exit_pen, 3),
        "binding": binding,
        "holder_change_penalty": None,        # reserved for multi-interval holder change
    }


# --- liquidity health labels (independent of the score) ----------------------
# A pool can legitimately score ~30/100 (band E) while the exit side has been
# pulled dry. These labels exist to say that plainly; they never change the
# score, they only override the verdict rendering with an explicit warning.
LIQ_HEALTH_DYING_DD = 0.80    # >= 80 % below the window peak — bleeding out
LIQ_HEALTH_DEAD_DD = 0.99     # >= 99 % below the peak — drained
LIQ_HEALTH_DEAD_USD = 10.0    # either pool below 10 USD — unsellable


def liquidity_health(gate_detail=None, liq_now=None, exit_now=None):
    """Post-score liquidity health label — `DYING` / `DEAD` — decoupled from the score.

    The gate already discounts the score for deterioration, but a modest discount is
    not enough to communicate that the pool is (nearly) gone. This label is emitted
    regardless of the score so a token sitting at ~30/100 can still be flagged DEAD.

    DEAD  -> drawdown >= 99 %, or either pool below 10 USD (unsellable).
    DYING -> drawdown in [80 %, 99 %).
    Otherwise LIQ_OK (no label rendered).

    Worst-of is used on both axes: the deepest drawdown between total and exit
    liquidity, and the thinner of the two pools (`min`, matching the exit-liquidity
    convention used elsewhere — the sell side is what actually binds).
    """
    g = gate_detail or {}
    dds = [d for d in (g.get("liquidity_drawdown_pct"), g.get("exit_drawdown_pct"))
           if isinstance(d, (int, float))]
    dd = max(dds) if dds else None
    depths = [d for d in (liq_now, exit_now) if isinstance(d, (int, float))]
    depth = min(depths) if depths else None

    thin = depth is not None and depth < LIQ_HEALTH_DEAD_USD
    if thin or (dd is not None and dd >= LIQ_HEALTH_DEAD_DD * 100.0):
        reason = (f"pool {_fmt_usd(depth)} below the 10 USD floor — unsellable" if thin
                  else f"liquidity down {dd:.1f}% from peak — pool drained")
        return {"code": "LIQ_DEAD", "label": "DEAD", "tone": "bad", "color": "#ef4444",
                "drawdown_pct": _r1(dd) if dd is not None else None,
                "depth_usd": _r1(depth) if depth is not None else None,
                "reason": reason}
    if dd is not None and dd >= LIQ_HEALTH_DYING_DD * 100.0:
        return {"code": "LIQ_DYING", "label": "DYING", "tone": "warn", "color": "#f59e0b",
                "drawdown_pct": _r1(dd),
                "depth_usd": _r1(depth) if depth is not None else None,
                "reason": f"liquidity down {dd:.1f}% from peak — bleeding out"}
    return {"code": "LIQ_OK", "label": None, "tone": "neutral", "color": None,
            "drawdown_pct": _r1(dd) if dd is not None else None,
            "depth_usd": _r1(depth) if depth is not None else None,
            "reason": None}


# ===========================================================================
# PILLAR 5 — Smart Money (advanced only)
# ===========================================================================

KOL_PNL_FLOOR = 20000.0   # KOL-proxy: unrealized PnL >= $20k


def _money_flow_map(flow_raw):
    if isinstance(flow_raw, list):
        rows = flow_raw
    else:
        rows = ((flow_raw or {}).get("items") or (flow_raw or {}).get("rows")
                or (flow_raw or {}).get("data") or [])
    out = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        tag = str(row.get("tag") or row.get("wallet_tag") or "")
        frame = str(row.get("frame") or "")
        if not tag or not frame:
            continue
        buy = _f(row.get("totalValueBuy") if row.get("totalValueBuy") is not None
                 else row.get("volumeBuyUsd") if row.get("volumeBuyUsd") is not None
                 else row.get("buyVolumeUsd") if row.get("buyVolumeUsd") is not None
                 else row.get("buy_usd"))
        sell = _f(row.get("totalValueSell") if row.get("totalValueSell") is not None
                  else row.get("volumeSellUsd") if row.get("volumeSellUsd") is not None
                  else row.get("sellVolumeUsd") if row.get("sellVolumeUsd") is not None
                  else row.get("sell_usd"))
        out.setdefault(tag, {})[frame] = {
            "buy_usd": buy,
            "sell_usd": sell,
            "net_usd": (buy - sell) if (buy is not None and sell is not None) else None,
            "tx_buy": _f(row.get("totalTxBuy") if row.get("totalTxBuy") is not None
                         else row.get("txBuy") if row.get("txBuy") is not None
                         else row.get("buyTxCount") if row.get("buyTxCount") is not None
                         else row.get("tx_buy") if row.get("tx_buy") is not None
                         else row.get("buy_count")),
            "tx_sell": _f(row.get("totalTxSell") if row.get("totalTxSell") is not None
                          else row.get("txSell") if row.get("txSell") is not None
                          else row.get("sellTxCount") if row.get("sellTxCount") is not None
                          else row.get("tx_sell") if row.get("tx_sell") is not None
                          else row.get("sell_count")),
            "traders": _f(row.get("uniqTrader") if row.get("uniqTrader") is not None
                          else row.get("traderCount") if row.get("traderCount") is not None
                          else row.get("uniqueTrader") if row.get("uniqueTrader") is not None
                          else row.get("traders")),
        }
    return out


def _cohort_flow_score(frames_grid, tag, ovd, lo, hi):
    """Multi-interval net-flow score for one wallet cohort tag.

    Every window contributes `net_flow / volume(window)`, mapped through the
    same `lo -> hi` ramp to a 0-100 score. The windows are nested (5m ⊂ 1h ⊂
    4h ⊂ 24h), so a durable accumulation keeps the same sign across all of
    them. The weighted mean is then pulled toward neutral when the windows
    disagree with each other, which smooths the trend instead of letting one
    snapshot decide the pillar.

    Returns (score|None, consistency|None, per_frame_rows).
    """
    per = []
    for frame, weight in SM_FLOW_FRAMES:
        cell = (((frames_grid or {}).get(tag) or {}).get(frame) or {})
        net = _f(cell.get("net_usd"))
        vol = _f(ov_get(ovd, "v", frame))
        if net is None or not vol or vol <= 0:
            continue
        pct = net / vol
        per.append({"frame": frame, "weight": weight, "net_usd": net, "vol_usd": vol,
                    "pct_of_vol": pct, "score": 100.0 * _ramp_s(pct, lo, hi)})
    if not per:
        return None, None, []
    wsum = sum(p["weight"] for p in per)
    mean = sum(p["weight"] * p["score"] for p in per) / wsum
    agree = sum(p["weight"] for p in per
                if (p["score"] - 50.0) * (mean - 50.0) >= 0) / wsum
    score = 50.0 + (mean - 50.0) * (0.75 + 0.25 * agree)
    return score, agree, per


def score_smart_money(flow_raw, top_holders, conc, ovd, profile):
    bd = []
    sub = {}

    def put(name, score, detail):
        sub[name] = score
        bd.append({"name": name, "score": None if score is None else _r1(score),
                   "weight": SUB_W["smart_money"][name], "detail": detail})

    flow_map = _money_flow_map(flow_raw)
    ov_flow_map = (ovd.get("_mf_tag_24h") or {}) if isinstance(ovd, dict) else {}
    # Nested-window grid for the multi-interval cohort flow score. Cached or
    # legacy payloads without a frame grid fall back to the 24h overview cells,
    # which degrades the multi-window score to the old single-snapshot value.
    frames_grid = (ovd.get("_mf_tag_frames") or {}) if isinstance(ovd, dict) else {}
    if not frames_grid:
        frames_grid = {t: {"24h": c} for t, c in ov_flow_map.items()
                       if isinstance(c, dict) and c}
    tags = _tags_map(profile)
    holder_rows = ((top_holders or {}).get("items") or (top_holders or {}).get("rows")
                   or (top_holders or {}).get("holders") or [])
    if not flow_map and not tags and not holder_rows:
        return {"score": None, "coverage": 0.0,
                "breakdown": [{"name": k, "score": None,
                               "weight": SUB_W["smart_money"][k],
                               "detail": "smart-money data absent (advanced only)"}
                              for k in SUB_W["smart_money"]],
                "signals": {}, "hard_blocks": []}

    v24 = _f(ovd.get("v24hUSD")) or 0.0
    smart_tag = tags.get("smart_trader") or {}
    whale_tag = tags.get("whales") or {}
    kol_tag = tags.get("kol") or {}
    hold_ratio = None
    whale_sell_ratio = None

    # --- presence --------------------------------------------------------
    n_sm = _f(smart_tag.get("holder_count"))
    sm_supply = _f(smart_tag.get("percent_of_supply"))
    presence = []
    if n_sm is not None:
        presence.append((0.55, 100.0 * _ramp_s(n_sm, 0.0, 25.0),
                         f"smart-trader wallets={n_sm:.0f} (ramp 0->25)"))
    if sm_supply is not None:
        presence.append((0.45, 100.0 * _ramp_s(sm_supply, 0.0, 8.0),
                         f"smart-trader holds {_pct(sm_supply)} of supply"))
    if presence:
        wsum = sum(w for w, _, _ in presence)
        put("sm_presence", sum(w * s for w, s, _ in presence) / wsum,
            " | ".join(d for _, _, d in presence))
    else:
        put("sm_presence", None, "smart-trader cohort absent")

    # --- flow ------------------------------------------------------------
    flow = []
    def _merge_flow_cells(primary, fallback):
        primary = primary or {}
        fallback = fallback or {}
        keys = ("buy_usd", "sell_usd", "net_usd", "tx_buy", "tx_sell", "traders")
        return {k: (primary.get(k) if primary.get(k) is not None else fallback.get(k)) for k in keys}

    sm_cell = _merge_flow_cells((flow_map.get("smart_money") or {}).get("24h"), ov_flow_map.get("smart_money"))
    whale_cell = _merge_flow_cells((flow_map.get("whales") or {}).get("24h"), ov_flow_map.get("whales"))
    kol_cell = _merge_flow_cells((flow_map.get("kol") or {}).get("24h"), ov_flow_map.get("kol"))
    net = _f(sm_cell.get("net_usd"))
    net_src = "token_money_flow" if net is not None else None
    if net is None:
        net = _f((ovd.get("_mf_tag_net_24h") or {}).get("smart_money"))
        net_src = "token_overview.cohort" if net is not None else None
    sm_multi, sm_agree, sm_per_frame = _cohort_flow_score(
        frames_grid, "smart_money", ovd, -0.05, 0.12)
    if sm_multi is not None:
        flow.append((0.55, sm_multi,
                     "smart-money net flow " + ", ".join(
                         f"{p['frame']}={p['pct_of_vol'] * 100:+.1f}% of vol"
                         for p in sm_per_frame)
                     + f" (consistency {sm_agree:.0%} over {len(sm_per_frame)} window(s))"))
    bc, sc_ = _f(sm_cell.get("tx_buy")), _f(sm_cell.get("tx_sell"))
    if bc is not None and sc_ is not None and (bc + sc_) > 0:
        flow.append((0.45, 100.0 * _clamp01(((bc / (bc + sc_)) - 0.40) / 0.35),
                     f"smart-money buys={bc:.0f} sells={sc_:.0f} ratio={bc/(bc+sc_):.2f}"))
    if flow:
        wsum = sum(w for w, _, _ in flow)
        put("sm_flow", sum(w * s for w, s, _ in flow) / wsum,
            " | ".join(d for _, _, d in flow))
    else:
        put("sm_flow", None, "smart-money money-flow absent")

    # --- holding quality -------------------------------------------------
    smart_buy = _f(smart_tag.get("buy_volume")) or _f(smart_tag.get("buy_volume_usd"))
    smart_sell = _f(smart_tag.get("sell_volume")) or _f(smart_tag.get("sell_volume_usd"))
    smart_traders = _f(sm_cell.get("traders"))
    if smart_buy is not None and smart_sell is not None and (smart_buy + smart_sell) > 0:
        hold_ratio = smart_buy / (smart_buy + smart_sell)
    q = []
    if sm_supply is not None:
        q.append((0.55, 100.0 * _ramp_s(sm_supply, 0.0, 10.0),
                  f"smart-trader supply share {_pct(sm_supply)}"))
    if hold_ratio is not None:
        q.append((0.45, 100.0 * _clamp01((hold_ratio - 0.45) / 0.30),
                  f"smart-trader buy share {hold_ratio*100:.0f}%"))
    if q:
        wsum = sum(w for w, _, _ in q)
        put("sm_quality", sum(w * s for w, s, _ in q) / wsum,
            " | ".join(d for _, _, d in q))
    else:
        put("sm_quality", None, "smart-trader supply / flow quality absent")

    # --- whale -----------------------------------------------------------
    whale_parts = []
    whale_count = _f(whale_tag.get("holder_count"))
    whale_pct = _f(whale_tag.get("percent_of_supply"))
    whale_buy = _f(whale_tag.get("buy_volume")) or _f(whale_tag.get("buy_volume_usd"))
    whale_sell = _f(whale_tag.get("sell_volume")) or _f(whale_tag.get("sell_volume_usd"))
    if whale_count is not None:
        whale_parts.append((0.35, 100.0 * _ramp_s(whale_count, 0.0, 20.0),
                            f"{whale_count:,.0f} whale wallets"))
    if whale_pct is not None:
        whale_parts.append((0.35, 100.0 * _ramp_s(whale_pct, 0.0, 12.0),
                            f"whales hold {_pct(whale_pct)}"))
    whale_net = _f(whale_cell.get("net_usd"))
    if whale_net is None:
        whale_net = _f((ovd.get("_mf_tag_net_24h") or {}).get("whales"))
    whale_multi, whale_agree, whale_per_frame = _cohort_flow_score(
        frames_grid, "whales", ovd, -0.08, 0.08)
    if whale_multi is not None:
        whale_parts.append((0.30, whale_multi,
                            "whales net flow " + ", ".join(
                                f"{p['frame']}={p['pct_of_vol'] * 100:+.1f}% of vol"
                                for p in whale_per_frame)
                            + f" (consistency {whale_agree:.0%})"))
    if whale_buy is not None and whale_sell is not None and (whale_buy + whale_sell) > 0:
        whale_sell_ratio = whale_sell / (whale_buy + whale_sell)
    if whale_parts:
        wsum = sum(w for w, _, _ in whale_parts)
        put("whale", sum(w * s for w, s, _ in whale_parts) / wsum,
            " | ".join(d for _, _, d in whale_parts))
    else:
        put("whale", None, "no whale signal measurable")

    # --- KOL -------------------------------------------------------------
    kol_count = _f(kol_tag.get("holder_count"))
    kol_pct = _f(kol_tag.get("percent_of_supply"))
    kol_net = _f(kol_cell.get("net_usd"))
    if kol_net is None:
        kol_net = _f((ovd.get("_mf_tag_net_24h") or {}).get("kol"))
    kol_parts = []
    if kol_count is not None:
        kol_parts.append((0.45, 100.0 * _ramp_s(kol_count, 0.0, 40.0),
                          f"{kol_count:,.0f} KOL wallets"))
    if kol_pct is not None:
        kol_parts.append((0.35, 100.0 * _ramp_s(kol_pct, 0.0, 8.0),
                          f"KOL holds {_pct(kol_pct)}"))
    kol_multi, kol_agree, kol_per_frame = _cohort_flow_score(
        frames_grid, "kol", ovd, -0.05, 0.06)
    if kol_multi is not None:
        kol_parts.append((0.20, kol_multi,
                          "KOL net flow " + ", ".join(
                              f"{p['frame']}={p['pct_of_vol'] * 100:+.1f}% of vol"
                              for p in kol_per_frame)
                          + f" (consistency {kol_agree:.0%})"))
    if kol_parts:
        wsum = sum(w for w, _, _ in kol_parts)
        put("kol", sum(w * s for w, s, _ in kol_parts) / wsum,
            " | ".join(d for _, _, d in kol_parts))
    else:
        put("kol", None, "KOL cohort absent")

    score, coverage = _wmean([(SUB_W["smart_money"][k], sub.get(k))
                              for k in SUB_W["smart_money"]])

    # --- action: what is the smart/whale cohort actually doing? -----------
    v_pct = (net / v24) if (net is not None and v24 > 0) else None
    tilt = 0.0
    if v_pct is not None:
        tilt += 1.0 if v_pct >= 0.02 else (-1.0 if v_pct <= -0.02 else 0.0)
    if hold_ratio is not None:
        tilt += 1.0 if hold_ratio >= 0.55 else (-1.0 if hold_ratio <= 0.40 else 0.0)
    if whale_sell_ratio is not None:
        tilt += -1.0 if whale_sell_ratio >= 0.50 else (1.0 if whale_sell_ratio <= 0.20 else 0.0)
    if v_pct is None and hold_ratio is None and whale_sell_ratio is None:
        sm_action, sm_action_detail = "Unknown", "no net-flow or holding data"
    else:
        sm_action = "Accumulating" if tilt >= 1.0 else ("Distributing" if tilt <= -1.0 else "Mixed")
        parts = []
        if v_pct is not None:
            parts.append(f"net flow {v_pct*100:+.1f}% of 24h volume")
        if hold_ratio is not None:
            parts.append(f"still holding {hold_ratio*100:.0f}% of SM PnL")
        if whale_sell_ratio is not None:
            parts.append(f"whale sell share {whale_sell_ratio*100:.0f}%")
        if bc is not None and sc_ is not None and (bc + sc_) > 0:
            parts.append(f"buys {bc:.0f} / sells {sc_:.0f}")
        sm_action_detail = " · ".join(parts)

    signals = {
        "smart_traders_no": n_sm,
        "smart_trader_pct_of_supply": sm_supply,
        "net_flow_24h_usd": net,
        "net_flow_source": net_src,
        "net_flow_pct_of_vol": round(net / v24, 4) if (net is not None and v24 > 0) else None,
        # Multi-interval view: net flow as % of each window's own volume, plus
        # how many of those windows agree with the blended direction.
        "net_flow_by_frame": ({p["frame"]: round(p["pct_of_vol"], 4)
                               for p in sm_per_frame} or None),
        "net_flow_consistency": (round(sm_agree, 3) if sm_agree is not None else None),
        "sm_buy_count_24h": bc, "sm_sell_count_24h": sc_,
        "sm_buy_ratio": round(bc / (bc + sc_), 3) if (bc is not None and sc_ is not None
                                                      and (bc + sc_) > 0) else None,
        "sm_trader_count_24h": smart_traders,
        "action": sm_action, "action_detail": sm_action_detail,
        "hold_ratio_pct": (round(hold_ratio * 100.0, 1) if hold_ratio is not None else None),
        "kol_count": kol_count,
        "kol_source": "holder_profile" if kol_count is not None else None,
        "kol_pct_of_supply": kol_pct,
        "kol_net_flow_24h_usd": kol_net,
        "whale_count": whale_count,
        "whale_pct_of_supply": whale_pct,
        "whale_net_flow_24h_usd": whale_net,
        "whale_net_flow_by_frame": ({p["frame"]: round(p["pct_of_vol"], 4)
                                     for p in whale_per_frame} or None),
        "kol_net_flow_by_frame": ({p["frame"]: round(p["pct_of_vol"], 4)
                                   for p in kol_per_frame} or None),
        "whale_sell_share_pct": (round(whale_sell_ratio * 100.0, 1)
                                 if whale_sell_ratio is not None else None),
    }
    return {"score": None if score is None else _r1(score), "coverage": round(coverage, 3),
            "breakdown": bd, "signals": signals, "hard_blocks": []}


# ===========================================================================
# Compose
# ===========================================================================

def compose(pillars, mode, preset="default", chain="sol"):
    weights = dict(WEIGHT_PRESETS.get(preset) or WEIGHT_PRESETS["default"])
    if mode == "standard":
        weights.pop("smart_money", None)
    weights, applied_shift = apply_chain_weight_shift(weights, chain)

    liq = pillars.get("liquidity") or {}
    gate, gate_detail = liquidity_gate(liq.get("stats"))
    health = liquidity_health(gate_detail, liq.get("liq_now"), liq.get("exit_now"))

    avail = {k: v for k, v in weights.items()
             if isinstance(pillars.get(k), dict) and pillars[k].get("score") is not None}
    wsum = sum(avail.values())
    if wsum <= 0:
        return {"final": 0.0, "rating": "F", "verdict": RATING_VERDICT["F"],
                "gate": 0.0, "gate_detail": {}, "liquidity_health": health,
                "weights_used": {}, "pillar_points": {},
                "weights_declared": weights, "applied_shift": applied_shift}

    norm = {k: v / wsum for k, v in avail.items()}
    base = sum(norm[k] * pillars[k]["score"] for k in norm)

    final = base * gate
    r = rating_of(final)
    return {
        "final": _r1(final),
        "base_before_gate": _r1(base),
        "rating": r,
        "verdict": RATING_VERDICT[r],
        "gate": round(gate, 3),
        "gate_detail": gate_detail,
        "liquidity_health": health,
        "weights_used": {k: round(v, 4) for k, v in norm.items()},
        "weights_declared": weights,
        "applied_shift": applied_shift,
        "pillar_points": {k: _r1(norm[k] * pillars[k]["score"]) for k in norm},
    }


# ===========================================================================
# Orchestration
# ===========================================================================

def _mode_plan(args, chain):
    """Return (steps, skips) describing which endpoints are called."""
    skip = {s.strip().lower() for s in (getattr(args, "skip", None) or "").split(",") if s.strip()}
    adv = args.mode == "advanced"
    sol = chain in SOL_ONLY
    plan = ["overview", "security"]
    skips = []

    if adv:
        for name in ("distribution", "holder_profile", "top_holders", "token_money_flow"):
            if name in skip:
                skips.append((name, "skipped by --skip"))
            elif name in ("distribution", "holder_profile") and not sol:
                skips.append((name, "Solana only — CU refunded"))
            else:
                plan.append(name)
        if "liq" in skip or "liquidity" in skip:
            skips.append(("liquidity_ohlc", "skipped by --skip"))
        elif not sol:
            skips.append(("liquidity_ohlc", "Solana only — CU refunded"))
        else:
            plan.append("liquidity_ohlc")
    else:
        skips.append(("distribution", "standard mode"))
        skips.append(("holder_profile", "standard mode"))
        skips.append(("top_holders", "standard mode"))
        skips.append(("token_money_flow", "standard mode"))
        skips.append(("liquidity_ohlc", "standard mode"))
    # Live liquidity snapshot (Solana only) — the cheap way to get *current* total
    # and exit liquidity for both modes instead of reading the last OHLC close.
    if "liq" in skip or "liquidity" in skip:
        skips.append(("liquidity_latest", "skipped by --skip"))
    elif not sol:
        skips.append(("liquidity_latest", "Solana only — CU refunded"))
    else:
        plan.append("liquidity_latest")
    return plan, skips


def analyze(args, emit=print):
    chain = getattr(args, "chain", "sol") or "sol"
    address = args.address.strip()
    mode = getattr(args, "mode", "standard")
    key = _load_key()
    if not key:
        emit("[E] No Birdeye API key. Set BIRDEYE_API_KEY or ~/.config/birdeye/.env")
        return 3

    api = Api(key, chain)
    warm = getattr(args, "_warm_errors", None) or []
    request_time = int(time.time())

    plan, skips = _mode_plan(args, chain)
    raw = {}
    errs = list(warm)

    def step(name, fn, required=False):
        if name not in plan:
            return None
        try:
            return fn()
        except RuntimeError as e:
            errs.append(f"{name}: {e}")
            if required:
                raise
            return None

    ovd = step("overview", lambda: fetch_overview(api, address), required=True)
    if ovd is None:
        emit("[E] token_overview failed — cannot score this token.")
        for e in errs:
            emit("    · " + e)
        return 4
    raw["overview"] = ovd
    secd = step("security", lambda: fetch_security(api, address)) or {}
    raw["security"] = secd
    dist = step("distribution",
                lambda: fetch_distribution(api, address,
                                           getattr(args, "top_n", 20) or 20)) or {}
    raw["distribution"] = dist
    profile = step("holder_profile", lambda: fetch_holder_profile(api, address)) or {}
    raw["holder_profile"] = profile
    top_holders = step("top_holders", lambda: fetch_top_holders(api, address, 100, 0, True)) or {}
    raw["top_holders"] = top_holders
    token_money_flow = step("token_money_flow",
                            lambda: fetch_token_money_flow(api, address, UI_KEY_FRAMES,
                                                           ["smart_money", "whales", "kol"])) or {}
    raw["token_money_flow"] = token_money_flow
    candles = step("liquidity_ohlc",
                   lambda: fetch_liquidity_ohlc(api, address,
                                                getattr(args, "liq_resolution", "15m") or "15m",
                                                getattr(args, "liq_candles", 96) or 96)) or []
    raw["liquidity_ohlc"] = candles
    liq_latest = step("liquidity_latest",
                      lambda: fetch_liquidity_latest(api, address)) or {}
    raw["liquidity_latest"] = liq_latest
    liq_resolution = getattr(args, "liq_resolution", "15m") or "15m"
    liq_snapshot = _liq_snapshot(ovd, liq_latest, candles, liq_resolution, request_time)
    # money flow: net + buy/sell volume per frame (same overview call)
    # plus volume/wallet/liquidity change summaries for the renderer/momentum.
    flow = _flow_block(ovd, candles, liq_resolution, liq_snapshot)
    flow["money_flow"] = _merge_money_flow_maps(flow.get("money_flow"), _money_flow_map(token_money_flow))

    # ---------------- score ----------------
    conc = _concentration(dist, secd, getattr(args, "top_n", 20) or 20)
    pillars = {
        "security": score_security(secd, ovd, address, chain),
        "holders": score_holders(conc, ovd, profile, top_holders),
        "activity": score_activity(ovd, pace_on=bool(getattr(args, "pace", False))),
        "liquidity": score_liquidity(ovd, candles, liq_resolution,
                                     liq_latest, request_time),
        "smart_money": score_smart_money(token_money_flow, top_holders, conc, ovd, profile),
    }
    if mode == "standard":
        pillars["smart_money"] = {"score": None, "coverage": 0.0,
                                  "breakdown": [], "signals": {}, "hard_blocks": []}

    comp = compose(pillars, mode, getattr(args, "weights_preset", "default") or "default", chain)
    hard = []
    for p in pillars.values():
        hard.extend(p.get("hard_blocks") or [])
    if hard:
        comp["final"] = 0.0
        comp["rating"] = "F"
        comp["verdict"] = RATING_VERDICT["F"]
        comp["hard_blocked"] = True

    # ---------------- CU bookkeeping ----------------
    cost = {"overview": 21, "security": 30, "distribution": 30, "holder_profile": 30,
            "top_holders": 30, "token_money_flow": 10, "liquidity_ohlc": 30,
            "liquidity_latest": 5}
    cu = {"base": 0, "list": 0, "advanced_security": 0, "risk_history": 0,
          "refunded_rollback": 0}
    cu["base"] = cost["overview"] + cost["security"]
    for name in plan:
        if name in ("distribution", "holder_profile", "top_holders"):
            cu["list"] += cost[name]
        elif name in ("token_money_flow", "liquidity_ohlc", "liquidity_latest"):
            cu["advanced_security"] += cost[name]
        elif name == "security":
            cu["base"] += cost["security"]
    for name, reason in skips:
        if "refund" in reason:
            cu["refunded_rollback"] += cost.get(name, 0)
    # security was added twice above when it is the first plan entry — normalise:
    cu["base"] = cost["overview"] + cost["security"]
    cu_total = sum(cu.values()) - cu["refunded_rollback"]

    # ---------------- coverage caveats ----------------
    caveats = []
    if mode == "standard":
        caveats.append("standard mode: cohorts/snipers, liquidity stability "
                       "and smart-money are NOT measured — score is not comparable to advanced")
    for name, reason in skips:
        if "refund" in reason or "skipped" in reason:
            caveats.append(f"{name}: {reason}")
    for e in errs:
        caveats.append("⚠ pipeline_gap — " + e)
    if modes_covered := frames_coverage(ovd):
        pass
    else:
        caveats.append("⚠ pipeline_gap — token_overview returned no usable frame data")

    api_call_details = [
        {"path": path, "cu": cu, "ok": ok, "note": note}
        for path, cu, ok, note in api.calls
    ]
    derived_data = {
        "market": {
            "price_usd": _f(ovd.get("price")),
            "market_cap_usd": _f(ovd.get("marketCap")),
            "fdv_usd": _f(ovd.get("fdv")),
            "liquidity_usd": _f(flow.get("liquidity_now")) or _f(ovd.get("liquidity")),
            "exit_liquidity_usd": (pillars["liquidity"] or {}).get("exit_now"),
            "holders": _f(ovd.get("holder")),
            "volume_24h_usd": _f(ovd.get("v24hUSD")),
            "trades_24h": _f(ovd.get("trade24h")),
            "unique_wallets_24h": _f(ovd.get("uniqueWallet24h")),
            "fees_paid_24h_usd": _f(ovd.get("global_fees_paid")),
        },
        "flow": flow,
        "holder_top": conc,
        "holder_cohorts": (pillars["holders"] or {}).get("cohorts", {}),
        "liquidity_stats": (pillars["liquidity"] or {}).get("stats"),
        "liquidity_snapshot": (pillars["liquidity"] or {}).get("snapshot"),
        "smart_money_signals": (pillars["smart_money"] or {}).get("signals", {}),
    }
    ext = (ovd.get("extensions") if isinstance(ovd, dict) else {}) or {}
    result = {
        "schemaVersion": 1,
        "kind": SKILL_KIND,
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "meta": {
            "chain": chain,
            "address": address,
            "symbol": ovd.get("symbol"),
            "name": ovd.get("name"),
            "logo": _clean_urlish(ovd.get("logoURI") or ovd.get("logo_uri")
                                  or ovd.get("logo") or ovd.get("image")
                                  or ext.get("logoURI") or ext.get("logo_uri")
                                  or ext.get("logo") or ext.get("image")),
            "mode": mode,
            "weights_preset": getattr(args, "weights_preset", "default"),
            "weights_declared": comp.get("weights_declared", {}),
            "weights_shift": comp.get("applied_shift"),
            "cu_breakdown": cu,
            "cu_billed_total": cu_total,
            "endpoint_calls": len(api.calls),
            "api_call_details": api_call_details,
            "frames_used": frames_coverage(ovd),
            "caveats": caveats,
        },
        "market": derived_data["market"],
        # Price change + money flow per frame from the same overview call.
        # `key_intervals` (5m/1h/4h/24h) is the short list the UI renders.
        "flow": derived_data["flow"],
        "score": {
            "final": comp["final"],
            "base_before_gate": comp.get("base_before_gate"),
            "rating": comp["rating"],
            "verdict": comp["verdict"],
            "gate": comp["gate"],
            "gate_detail": comp["gate_detail"],
            "liquidity_health": comp.get("liquidity_health"),
            "weights_used": comp["weights_used"],
            "pillar_points": comp.get("pillar_points", {}),
            "hard_blocked": comp.get("hard_blocked", False),
        },
        "pillars": {k: {"score": (pillars[k] or {}).get("score"),
                        "coverage": (pillars[k] or {}).get("coverage", 0.0),
                        "breakdown": (pillars[k] or {}).get("breakdown", [])}
                    for k in PILLAR_ORDER},
        "holder_top": derived_data["holder_top"],
        "holder_cohorts": derived_data["holder_cohorts"],
        "liquidity_stats": derived_data["liquidity_stats"],
        "smart_money_signals": derived_data["smart_money_signals"],
        "raw_data": raw,
        "derived_data": derived_data,
        "inputs": raw,
        "format_renderers": ["ui", "json", "plain", "telegram", "raw-json"],
    }
    return result


# ===========================================================================
# Renderers
# ===========================================================================

_SYMBOL_BARS = "_" * 70

_NON_UI_PRIVATE_KEYS = {
    "html",
    "rendered_ui",
    "rendered_plain",
    "rendered_telegram",
    "rendered_json",
    "rendered_raw-json",
    "rendered_rendered",
    "out",
}


def _strip_non_ui_recursive(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _NON_UI_PRIVATE_KEYS:
                continue
            out[k] = _strip_non_ui_recursive(v)
        return out
    if isinstance(value, list):
        return [_strip_non_ui_recursive(v) for v in value]
    return value


def _compact_dict(d):
    if not isinstance(d, dict):
        return d
    return {k: v for k, v in d.items() if v is not None}


def _public_json_contract(res):
    src = _strip_non_ui_recursive(res or {})
    m = src.get("meta") or {}
    raw_data = (src.get("inputs") or src.get("raw_data") or {})
    derived_data = src.get("derived_data") or {
        "market": src.get("market") or {},
        "flow": src.get("flow") or {},
        "holder_top": src.get("holder_top") or {},
        "holder_cohorts": src.get("holder_cohorts") or {},
        "liquidity_stats": src.get("liquidity_stats") or {},
        "smart_money_signals": src.get("smart_money_signals") or {},
    }
    return {
        "schemaVersion": src.get("schemaVersion", 1),
        "kind": src.get("kind"),
        "skill": src.get("skill"),
        "skill_version": src.get("skill_version"),
        "format_renderers": src.get("format_renderers") or ["ui", "json", "plain", "telegram", "raw-json"],
        "token": _compact_dict({
            "chain": m.get("chain"),
            "address": m.get("address"),
            "symbol": m.get("symbol"),
            "name": m.get("name"),
            "logo": m.get("logo"),
            "mode": m.get("mode"),
            "market": src.get("market") or {},
        }),
        "score": src.get("score") or {},
        "pillars": src.get("pillars") or {},
        "holders": {
            "concentration": src.get("holder_top") or {},
            "cohorts": src.get("holder_cohorts") or {},
        },
        "liquidity": src.get("liquidity_stats") or {},
        "smart_money": src.get("smart_money_signals") or {},
        "flow": src.get("flow") or {},
        "derived_data": derived_data,
        "raw_data": raw_data,
        "meta": _compact_dict({
            "weights_preset": m.get("weights_preset"),
            "weights_declared": m.get("weights_declared"),
            "weights_shift": m.get("weights_shift"),
            "run_id": m.get("run_id"),
            "cache_file": m.get("cache_file"),
            "latency_ms": m.get("latency_ms"),
            "frames_used": m.get("frames_used"),
            "cu_billed_total": m.get("cu_billed_total"),
            "cu_breakdown": m.get("cu_breakdown"),
            "endpoint_calls": m.get("endpoint_calls"),
            "api_call_details": m.get("api_call_details"),
            "caveats": m.get("caveats"),
        }),
    }


def _ui_envelope(res, explain=False):
    clean = _strip_non_ui_recursive(json.loads(json.dumps(res, ensure_ascii=False)))
    contract = _public_json_contract(clean)
    try:
        out_plain = render_plain(clean)
    except Exception:
        out_plain = json.dumps(contract, ensure_ascii=False, indent=2)
    try:
        out_telegram = render_telegram(clean)
    except Exception:
        out_telegram = json.dumps(contract, ensure_ascii=False, indent=2)
    out_json = json.dumps(contract, ensure_ascii=False, indent=2)
    out_raw_json = json.dumps(contract, ensure_ascii=False)
    payload = {
        "schemaVersion": contract.get("schemaVersion", 1),
        "kind": SKILL_KIND,
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "format_renderers": contract.get("format_renderers") or ["ui", "json", "plain", "telegram", "raw-json"],
        "payload": contract,
        "rendered_plain": out_plain,
        "rendered_telegram": out_telegram,
        "rendered_json": out_json,
        "rendered_raw-json": out_raw_json,
        "html": render_html(res),
        "final": res["score"]["final"],
        "rating": res["score"]["rating"],
        "verdict": res["score"]["verdict"],
        "pillars": {k: res["pillars"][k]["score"] for k in PILLAR_ORDER},
        "meta": res["meta"],
        "score": res["score"],
    }
    if explain:
        payload["breakdowns"] = {k: res["pillars"][k]["breakdown"] for k in PILLAR_ORDER}
    return payload


def render_plain(res):
    m = res["meta"]
    s = res["score"]
    mk = res["market"]
    L = [
        "skill: token-due-diligence-score",
        f"symbol: {m.get('symbol') or '?'}",
        f"chain: {m['chain']}",
        f"mode: {m['mode']}",
        f"address: {m['address']}",
        f"final_score: {s['final']:.1f}",
        f"rating: {s['rating']}",
        f"verdict: {s['verdict']}",
        f"base_before_gate: {s['base_before_gate']:.1f}",
        f"gate: {s['gate']:.3f}",
        f"binding_gate: {s['gate_detail'].get('binding')}",
    ]
    health = s.get("liquidity_health") or {}
    if health.get("label"):
        L.append(f"liquidity_health: {health['label']} ({health.get('reason')})")
    gd = s["gate_detail"]
    if gd.get("liquidity_drawdown_pct") is not None:
        L.append(f"liquidity_drawdown_pct: {gd.get('liquidity_drawdown_pct')}")
    if gd.get("exit_drawdown_pct") is not None:
        L.append(f"exit_drawdown_pct: {gd.get('exit_drawdown_pct')}")
    if gd.get("binding") != "none":
        L.append(f"gate_penalty: liquidity={gd.get('liquidity_penalty')} "
                 f"exit={gd.get('exit_penalty')}")
    L.extend([
        f"market.price_usd: {_fmt_usd(mk['price_usd'])}",
        f"market.market_cap_usd: {_fmt_usd(mk['market_cap_usd'])}",
        f"market.fdv_usd: {_fmt_usd(mk['fdv_usd'])}",
        f"market.liquidity_usd: {_fmt_usd(mk['liquidity_usd'])}",
        f"market.liquidity_source: {(res.get('flow') or {}).get('liquidity_now_source') or 'N/A'}",
        f"market.exit_liquidity_usd: {_fmt_usd(mk['exit_liquidity_usd'])}",
        f"market.exit_liquidity_source: {(res.get('flow') or {}).get('exit_liquidity_now_source') or 'N/A'}",
        f"market.volume_24h_usd: {_fmt_usd(mk['volume_24h_usd'])}",
        f"market.holders: {_num(mk['holders'],0)}",
        f"market.trades_24h: {_num(mk['trades_24h'],0)}",
        f"market.unique_wallets_24h: {_num(mk['unique_wallets_24h'],0)}",
    ])
    for k in PILLAR_ORDER:
        p = res["pillars"][k]
        if p["score"] is None:
            continue
        w = s["weights_used"].get(k, 0.0)
        key = k.replace("_", ".")
        L.append(f"pillar.{key}.score: {p['score']:.1f}")
        L.append(f"pillar.{key}.weight: {w:.3f}")
        L.append(f"pillar.{key}.points: {s['pillar_points'].get(k, 0.0):.1f}")
        L.append(f"pillar.{key}.coverage_pct: {p['coverage']*100:.0f}")
    if s.get("hard_blocked"):
        L.append("hard_blocked: true")
    top = res.get("holder_top") or {}
    if top.get("top1") is not None or top.get("top10") is not None:
        for name in ("top1", "top3", "top10", "top20"):
            if top.get(name) is not None:
                L.append(f"holder_concentration.{name}_pct: {_pct(top.get(name))}")
    coh = res.get("holder_cohorts") or {}
    if coh:
        for k, v in coh.items():
            base = f"holder_cohorts.{k}"
            L.append(f"{base}.pct_of_supply: {_pct(v.get('pct_of_supply'))}")
            L.append(f"{base}.holder_count: {_num(v.get('holder_count'),0)}")
    ls = res.get("liquidity_stats")
    if ls:
        win = ls.get("window") or {}
        lq = ls.get("liquidity") or {}
        ex = ls.get("exit_liquidity") or {}
        L.append(f"liquidity_window.span_hours: {win.get('span_hours')}")
        L.append(f"liquidity_window.candles: {win.get('candles')}")
        L.append(f"liquidity_window.resolution: {win.get('resolution')}")
        for key, value in lq.items():
            if key == "candles":
                continue
            L.append(f"liquidity_stats.liquidity.{key}: {_fmt_usd(value) if 'pct' not in key and key not in ('std',) else (_pct(value) if 'pct' in key else _num(value,2))}")
        if ex.get("current") is not None:
            for key, value in ex.items():
                if key == "candles":
                    continue
                L.append(f"liquidity_stats.exit_liquidity.{key}: {_fmt_usd(value) if 'pct' not in key and key not in ('std',) else (_pct(value) if 'pct' in key else _num(value,2))}")
    sm = res.get("smart_money_signals") or {}
    if sm:
        for key in ("action", "smart_traders_no", "smart_trader_pct_of_supply", "net_flow_24h_usd",
                    "net_flow_pct_of_vol", "sm_buy_count_24h", "sm_sell_count_24h",
                    "hold_ratio_pct", "kol_count", "kol_source", "whale_count",
                    "kol_net_flow_24h_usd", "whale_net_flow_24h_usd"):
            if sm.get(key) is not None:
                L.append(f"smart_money.{key}: {sm.get(key)}")
    for c in (res["meta"].get("caveats") or []):
        L.append(f"caveat: {c}")
    L.append(f"meta.cu_billed_total: {res['meta']['cu_billed_total']}")
    L.append(f"meta.endpoint_calls: {res['meta']['endpoint_calls']}")
    L.append(f"meta.cu_breakdown: {json.dumps(res['meta']['cu_breakdown'], separators=(',', ':'))}")
    return "\n".join(L)


def render_telegram(res):
    m, s, mk = res["meta"], res["score"], res["market"]
    health = s.get("liquidity_health") or {}
    L = [f"*TOKEN DUE-DILIGENCE SCORE* · `{m.get('symbol') or '?'}` · {m['chain']} · {m['mode']}",
         f"`{m['address']}`",
         f"*FINAL {s['final']:.1f}/100  →  {s['rating']}*  {s['verdict']}",
         f"base {s['base_before_gate']:.1f} × gate {s['gate']:.2f}", ""]
    if health.get("label"):
        mark = "🔴" if health["code"] == "LIQ_DEAD" else "🟠"
        L.insert(3, f"{mark} *LIQUIDITY {health['label']}* — {health.get('reason')}")
    L.append("```")
    L.append(f"{'PILLAR':<12}{'SCORE':>7}{'WT':>7}")
    for k in PILLAR_ORDER:
        p = res["pillars"][k]
        if p["score"] is None:
            continue
        L.append(f"{PILLAR_LABEL[k]:<12}{p['score']:>7.1f}{s['weights_used'].get(k,0):>7.2f}")
    L.append("```")
    L.append(f"MCap {_fmt_usd(mk['market_cap_usd'])} · Liquidity {_fmt_usd(mk['liquidity_usd'])}"
             f" · Exit Liquidity {_fmt_usd(mk['exit_liquidity_usd'])}")
    L.append(f"Vol24h {_fmt_usd(mk['volume_24h_usd'])} · Holders {_num(mk['holders'],0)}"
             f" · Tx24h {_num(mk['trades_24h'],0)}")
    top = res.get("holder_top") or {}
    if top.get("top1") is not None:
        L.append(f"top1 {_pct(top.get('top1'))} · top3 {_pct(top.get('top3'))}"
                 f" · top10 {_pct(top.get('top10'))} · top20 {_pct(top.get('top20'))}")
    ls = res.get("liquidity_stats")
    if ls:
        lq, ex = ls.get("liquidity") or {}, ls.get("exit_liquidity") or {}
        L.append(f"liquidity now {_fmt_usd(lq.get('current'))} · min {_fmt_usd(lq.get('min'))}"
                 f" · max {_fmt_usd(lq.get('max'))} · dd {_pct(lq.get('drawdown_pct'))}")
        if ex.get("current") is not None:
            L.append(f"exit liquidity now {_fmt_usd(ex.get('current'))} · min {_fmt_usd(ex.get('min'))}"
                     f" · max {_fmt_usd(ex.get('max'))} · dd {_pct(ex.get('drawdown_pct'))}")
    sm = res.get("smart_money_signals") or {}
    if sm and sm.get("action"):
        flow = (f" · netflow {_fmt_usd_short(sm.get('net_flow_24h_usd'))}"
                f" ({100.0 * sm['net_flow_pct_of_vol']:+.1f}% of vol)"
                if sm.get("net_flow_pct_of_vol") is not None else "")
        L.append(f"SM action {sm.get('action')}{flow} · KOL {sm.get('kol_count')}"
                 f" · whale {sm.get('whale_count')}")
    for c in (m.get("caveats") or []):
        L.append("⚠ " + c)
    L.append(f"⚡CU {m['cu_billed_total']} "
             f"(`{json.dumps(m['cu_breakdown'], separators=(',', ':'))}`)")
    return "\n".join(L)


_RATING_COLOR = {"A+": "#16a34a", "A": "#22c55e", "B+": "#65a30d", "B": "#84cc16",
                 "C+": "#eab308", "C": "#f59e0b", "D": "#f97316",
                 "E": "#ef4444", "F": "#b91c1c"}
_DD_TONE = {
    "good": ("rgba(34,197,94,.10)", "#86efac", "rgba(34,197,94,.22)", "#22c55e"),
    "warn": ("rgba(250,204,21,.10)", "#fde68a", "rgba(250,204,21,.22)", "#facc15"),
    "bad": ("rgba(239,68,68,.10)", "#fca5a5", "rgba(239,68,68,.22)", "#ef4444"),
    "neutral": ("#0f1115", "#cbd5e1", "#202530", "#e6e8ef"),
}


def _dd_tone(score):
    if not isinstance(score, (int, float)):
        return "neutral"
    if score >= 80:
        return "good"
    if score >= 55:
        return "warn"
    return "bad"


def _dd_chip(label, value, tone="neutral"):
    _bg, fg, bd, _c = _DD_TONE.get(tone, _DD_TONE["neutral"])
    return (f'<div style="background:{_bg};border:1px solid {bd};border-radius:999px;'
            f'padding:3px 9px;font-size:10.5px;color:{fg}">{_html.escape(str(label))}: '
            f'<span style="font-weight:700">{_html.escape(str(value))}</span></div>')


def _dd_tip(text):
    esc = _html.escape(str(text))
    return (
        f'<span style="position:relative;display:inline-flex;vertical-align:middle;margin-left:5px" '
        f'onmouseenter="var p=this.querySelector(\'span[data-tip-pop]\');if(p){{p.style.opacity=\'1\';p.style.visibility=\'visible\';}}" '
        f'onmouseleave="var p=this.querySelector(\'span[data-tip-pop]\');if(p){{p.style.opacity=\'0\';p.style.visibility=\'hidden\';}}">'
        f'<span style="display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:999px;'
        f'border:1px solid #2a3342;color:#8fb8ff;font-size:9px;cursor:help">?</span>'
        f'<span data-tip-pop="1" style="position:absolute;left:50%;bottom:calc(100% + 8px);transform:translateX(-50%);'
        f'min-width:180px;max-width:260px;padding:7px 9px;border-radius:8px;background:#0b1220;border:1px solid #24324a;'
        f'color:#dbe4f0;font-size:11px;line-height:1.45;box-shadow:0 10px 25px rgba(0,0,0,.28);'
        f'opacity:0;visibility:hidden;white-space:normal;z-index:30">{esc}</span></span>')


def _dd_label(text, tip=None):
    out = _html.escape(str(text))
    if tip:
        out += _dd_tip(tip)
    return out


def _dd_tile(label, value, sub=None, bg="#0f1115", tip=None):
    s = (f'<div style="font-size:10px;color:#64748b;margin-top:2px">{_html.escape(str(sub))}</div>'
         if sub else "")
    return (f'<div style="background:{bg};border-radius:9px;padding:8px 9px;text-align:center;border:1px solid #151b24">'
            f'<div style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.3px">'
            f'{_dd_label(label, tip)}</div>'
            f'<div style="font-size:15px;font-weight:800;color:#e6e8ef;margin-top:0">'
            f'{_html.escape(str(value))}</div>{s}</div>')


def _dd_tile_html_sub(label, value, sub_html="", bg="#0f1115", tip=None):
    s = f'<div style="font-size:10px;color:#64748b;margin-top:2px">{sub_html}</div>' if sub_html else ""
    return (f'<div style="background:{bg};border-radius:9px;padding:8px 9px;text-align:center;border:1px solid #151b24">'
            f'<div style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.3px">'
            f'{_dd_label(label, tip)}</div>'
            f'<div style="font-size:15px;font-weight:800;color:#e6e8ef;margin-top:0">'
            f'{_html.escape(str(value))}</div>{s}</div>')


def _dd_score_block(label, score, weight, coverage):
    tone = _dd_tone(score)
    color = _DD_TONE[tone][3]
    ok = isinstance(score, (int, float))
    val = f"{score:.1f}" if ok else "N/A"
    bar = ""
    if ok:
        bar = (f'<div style="height:4px;background:#1c2230;border-radius:2px;margin-top:6px;overflow:hidden">'
               f'<div style="width:{max(0.0, min(100.0, score)):.0f}%;height:100%;background:{color}"></div></div>')
    meta = (f'w {weight:.3f} · '
            f'{_dd_label(f"coverage {coverage*100:.0f}%", "Coverage = share of this pillar weight that had measurable inputs in the current mode/run. Missing sub-signals are dropped instead of scored as pass.")}'
            ) if ok else "not measured in this mode"
    return (f'<div style="background:#0f1115;border-radius:9px;padding:10px">'
            f'<div style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.3px">'
            f'{_dd_label(label, "Weighted pillar score. Coverage shows how much of the pillar had measurable inputs.")}</div>'
            f'<div style="font-size:20px;font-weight:800;color:{color};margin-top:2px">{val}'
            f'<span style="font-size:11px;color:#64748b;font-weight:600">/100</span></div>'
            f'{bar}<div style="font-size:10px;color:#64748b;margin-top:4px">{meta}</div></div>')


def _dd_liq_row(name, st):
    if not st:
        return ""
    tips = {
        "Current": "Current liquidity at the last candle in the window.",
        "Min": "Lowest observed liquidity in the window.",
        "Max": "Highest observed liquidity in the window.",
        "Median": "Middle liquidity level across all candles in the window.",
        "Mean": "Average liquidity across the window.",
        "Drawdown": "In-window swing: (max - min) / max.",
        "From peak": "Distance from the current value to the window peak: (max - current) / max.",
        "Trend": "Net change from the first candle to the current candle.",
        "σ/μ": "Coefficient of variation: standard deviation divided by mean. Higher means less stable liquidity.",
    }
    cells = [("Current", _fmt_usd(st.get("current"))), ("Min", _fmt_usd(st.get("min"))),
             ("Max", _fmt_usd(st.get("max"))), ("Median", _fmt_usd(st.get("median"))),
             ("Mean", _fmt_usd(st.get("mean"))), ("Drawdown", _pct(st.get("drawdown_pct"))),
             ("From peak", _pct(st.get("drawdown_from_peak_pct"))),
             ("Trend", _pct(st.get("trend_pct"))), ("σ/μ", _pct(st.get("std_pct_of_mean")))]
    tds = "".join(
        f'<td style="padding:6px 9px;white-space:nowrap">'
        f'<div style="font-size:10px;color:#94a3b8;text-transform:uppercase">{_dd_label(k, tips.get(k))}</div>'
        f'<div style="font-size:14px;font-weight:700;color:#e6e8ef;margin-top:1px">{v}</div></td>'
        for k, v in cells)
    return (f'<tr><td style="padding:6px 9px;font-size:13px;font-weight:700;color:#cbd5e1;'
            f'white-space:nowrap">{_dd_label(name, "Rolling liquidity statistics over the selected window.")}</td>{tds}</tr>')


def _dd_signed(v, nd=1, suffix="%"):
    """Green/red signed value, or a muted dash when absent."""
    if not isinstance(v, (int, float)):
        return '<span style="color:#475569">—</span>'
    c = "#22c55e" if v >= 0 else "#ef4444"
    return f'<span style="color:{c};font-weight:700">{v:+.{nd}f}{suffix}</span>'


def _dd_usd_signed(v):
    """Compact signed USD cell for net-flow columns."""
    if not isinstance(v, (int, float)):
        return '<span style="color:#475569">–</span>'
    c = "#22c55e" if v >= 0 else "#ef4444"
    return f'<span style="color:{c};font-weight:700">{"+" if v >= 0 else ""}{_fmt_usd_short(v)}</span>'


def _dd_frame_toggle_js(root_name):
    safe_root = _html.escape(str(root_name or ""), quote=True)
    return (
        "var root=this.closest('[data-dd-switch-root]');"
        "if(!root)return;"
        "var frame=this.getAttribute('data-frame');"
        f"root.querySelectorAll('[data-dd-frame-btn=\"{safe_root}\"]').forEach(function(b){{"
        "var on=b===this;"
        "b.dataset.active=on?'1':'0';"
        "b.style.background=on?'#1d4ed8':'#0f172a';"
        "b.style.borderColor=on?'#3b82f6':'#243041';"
        "b.style.color=on?'#eff6ff':'#94a3b8';"
        "}.bind(this));"
        f"root.querySelectorAll('[data-dd-frame-panel-root=\"{safe_root}\"]').forEach(function(p){{"
        "p.style.display=(p.getAttribute('data-dd-frame-value')===frame)?'block':'none';"
        "});"
    )


def _dd_frame_switcher(root_name, frames, default_frame):
    order = [f for f in ("24h", "4h", "1h", "15m") if f in set(frames or [])]
    if not order:
        return ""
    js = _html.escape(_dd_frame_toggle_js(root_name), quote=True)
    buttons = []
    for frame in order:
        active = frame == default_frame
        buttons.append(
            f'<button type="button" data-dd-frame-btn="{_html.escape(str(root_name), quote=True)}" data-active="{"1" if active else "0"}" '
            f'data-frame="{_html.escape(frame, quote=True)}" onclick="{js}" '
            f'style="padding:3px 8px;border-radius:999px;border:1px solid '
            f'{"#3b82f6" if active else "#243041"};'
            f'background:{"#1d4ed8" if active else "#0f172a"};'
            f'color:{"#eff6ff" if active else "#94a3b8"};font-size:10px;font-weight:700;cursor:pointer">'
            f'{_html.escape(frame)}</button>'
        )
    return f'<div style="display:flex;gap:6px;flex-wrap:wrap">{"".join(buttons)}</div>'


def _dd_flow_panel(res):
    """Selected-frame momentum/activity panel with clickable frame buttons."""
    flow = res.get("flow") or {}
    frames = flow.get("key_intervals") or KEY_FRAMES
    pc = flow.get("price_change_pct") or {}
    vc = flow.get("volume_change_pct") or {}
    wc = flow.get("wallet_change_pct") or {}
    tc = flow.get("trade_change_pct") or {}
    lc = flow.get("liquidity_change_pct") or {}
    vv = flow.get("volume_value") or {}
    wv = flow.get("wallet_value") or {}
    tv = flow.get("trade_value") or {}

    if not any(
        pc.get(f) is not None or vc.get(f) is not None or wc.get(f) is not None
        or tc.get(f) is not None or lc.get(f) is not None
        for f in frames
    ):
        return ""
    order = [f for f in ("24h", "4h", "1h", "15m") if f in set(frames or [])]
    default_frame = "24h" if "24h" in order else (order[0] if order else None)
    if not default_frame:
        return ""

    def _metric_tile(label, value, delta, tip):
        return (
            f'<div style="background:#0c1018;border:1px solid #1c2432;border-radius:9px;padding:8px 9px">'
            f'<div style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.3px">'
            f'{_dd_label(label, tip)}</div>'
            f'<div style="font-size:16px;font-weight:800;color:#e6e8ef;margin-top:2px">{value}</div>'
            f'<div style="font-size:11px;color:#64748b;margin-top:2px">vs same interval {_dd_signed(delta)}</div></div>'
        )

    panels = []
    for frame in order:
        panels.append(
            f'<div data-dd-frame-panel-root="flow" data-dd-frame-value="{_html.escape(frame, quote=True)}" '
            f'style="display:{"block" if frame == default_frame else "none"}">'
            f'<div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px">'
            f'{_metric_tile("Price", _fmt_usd(res["market"].get("price_usd")), pc.get(frame), "Current price with change vs the selected interval.")}'
            f'{_metric_tile(f"Volume {frame}", _fmt_usd(vv.get(frame)), vc.get(frame), "Volume value and change percent for the selected interval.")}'
            f'{_metric_tile(f"Wallets {frame}", _num(wv.get(frame), 0), wc.get(frame), "Unique wallets and change percent for the selected interval.")}'
            f'{_metric_tile(f"Trades {frame}", _num(tv.get(frame), 0), tc.get(frame), "Trade count and change percent for the selected interval.")}'
            f'{_metric_tile("Liquidity", _fmt_usd(res["market"].get("liquidity_usd")), lc.get(frame), "Current liquidity with inferred change percent vs the selected interval.")}'
            f'</div></div>'
        )
    return (
        f'<div data-dd-switch-root="flow" style="background:#0f1115;border-radius:10px;padding:12px;margin-bottom:12px">'
        f'<div style="display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px">'
        f'<div style="font-size:12px;font-weight:700;color:#e6e8ef">'
        f'{_dd_label("Activity Snapshot", "Selected-frame view of price, volume, wallet, trade, and liquidity changes.")}</div>'
        f'{_dd_frame_switcher("flow", order, default_frame)}</div>'
        f'{"".join(panels)}</div>'
    )


def _dd_smart_money_mini_flow(res, root_name="smart-mini", include_switcher=True):
    flow = res.get("flow") or {}
    mf = flow.get("money_flow") or {}
    label_map = {"smart_money": "Smart", "whales": "Whales", "kol": "KOL"}
    frames = [f for f in ("24h", "4h", "1h", "15m") if any(((mf.get(tag) or {}).get(f) or {}) for tag in label_map)]
    default_frame = "24h" if "24h" in frames else (frames[0] if frames else None)
    if not default_frame:
        return ""

    def _line(tag, frame):
        cell = ((mf.get(tag) or {}).get(frame) or {})
        buy = _f(cell.get("buy_usd"))
        sell = _f(cell.get("sell_usd"))
        net = _f(cell.get("net_usd"))
        txb = _f(cell.get("tx_buy"))
        txs = _f(cell.get("tx_sell"))
        denom = (buy or 0.0) + (sell or 0.0)
        buy_pct = (100.0 * (buy or 0.0) / denom) if denom > 0 else 50.0
        return (
            f'<div style="padding:7px 0;border-top:1px solid #1a2231">'
            f'<div style="display:flex;justify-content:space-between;gap:6px;align-items:center">'
            f'<span style="font-size:11px;color:#cbd5e1;font-weight:800">{label_map[tag]}</span>'
            f'{_dd_usd_signed(net)}</div>'
            f'<div style="margin-top:5px;height:7px;background:#1f2937;border-radius:999px;overflow:hidden">'
            f'<div style="height:100%;width:{buy_pct:.1f}%;background:#86efac;float:left"></div>'
            f'<div style="height:100%;width:{100.0-buy_pct:.1f}%;background:#fca5a5;float:left"></div></div>'
            f'<div style="display:flex;justify-content:space-between;gap:6px;margin-top:4px;font-size:10px;color:#94a3b8">'
            f'<span>{_num(txb,0)} / {_num(txs,0)}</span>'
            f'<span>{_fmt_usd_short(buy)} / {_fmt_usd_short(sell)}</span></div></div>'
        )

    panels = []
    for frame in frames:
        panels.append(
            f'<div data-dd-frame-panel-root="{_html.escape(str(root_name), quote=True)}" data-dd-frame-value="{_html.escape(frame, quote=True)}" '
            f'style="display:{"block" if frame == default_frame else "none"}">'
            f'<div style="background:#0c1018;border:1px solid #1c2432;border-radius:8px;padding:8px 9px">'
            f'{_line("smart_money", frame)}{_line("whales", frame)}{_line("kol", frame)}</div></div>'
        )
    if not include_switcher:
        return "".join(panels)
    return (
        f'<div data-dd-switch-root="{_html.escape(str(root_name), quote=True)}" style="min-width:340px;width:100%">'
        f'<div style="display:flex;justify-content:flex-end;margin-bottom:6px">{_dd_frame_switcher(root_name, frames, default_frame)}</div>'
        f'{"".join(panels)}</div>'
    )


def _dd_liquidity_now(res):
    flow = res.get("flow") or {}
    v = _f(flow.get("liquidity_now"))
    if v is not None:
        return v
    stats = res.get("liquidity_stats") or {}
    v = _f((stats.get("liquidity") or {}).get("current"))
    if v is not None:
        return v
    return _f((res.get("market") or {}).get("liquidity_usd"))


def _dd_holder_panel(res):
    """Compact holder strip — values only, no oversized tiles."""
    top = res.get("holder_top") or {}
    coh = res.get("holder_cohorts") or {}
    parts = []
    for n in ("1", "3", "10", "20"):
        v = top.get(f"top{n}")
        if v is None:
            continue
        heavy = n in ("1", "3") and v >= 50.0
        color = "#f87171" if heavy else "#e6e8ef"
        parts.append(f'<span style="color:#64748b">Top{n}</span> '
                     f'<span style="color:{color};font-weight:700">{_pct(v)}</span>')
    if not parts and not coh:
        return ""
    strip = (f'<div style="font-size:14px;line-height:1.6">{" · ".join(parts)}</div>'
             if parts else "")
    coh_html = ""
    if coh:
        items = []
        for k, v in coh.items():
            if v.get("pct_of_supply") is None:
                continue
            items.append(f'<span style="color:#94a3b8">{_html.escape(str(k).replace("_", " "))}'
                         f' <b style="color:#cbd5e1;font-size:12.5px">{_pct(v.get("pct_of_supply"))}</b>'
                         f'<span style="color:#475569">/{_num(v.get("holder_count"), 0)}</span></span>')
        if items:
            coh_html = (f'<div style="font-size:12px;margin-top:6px;line-height:1.7">'
                        f'<span style="color:#64748b">cohorts </span>'
                        f'{" · ".join(items)}</div>')
    return (
        f'<div style="background:linear-gradient(180deg,#151018 0%,#0f1115 100%);border:1px solid #2a1c25;'
        f'border-top:2px solid #7c3aed;border-radius:10px;padding:10px 12px">'
        f'<div style="font-size:12px;font-weight:700;color:#e6e8ef;margin-bottom:6px">'
        f'{_dd_label("Holder Concentration", "Top-holder concentration and cohort ownership. High concentration means a smaller float and a heavier exit overhang.")}</div>{strip}{coh_html}</div>')


def _dd_short_addr(addr):
    a = str(addr or "")
    return a if len(a) <= 14 else f"{a[:4]}...{a[-4:]}"


def _holder_funding_note(row):
    funding = row.get("funding") if isinstance(row, dict) else None
    if not isinstance(funding, dict):
        return "—"
    funder = str(funding.get("funder") or funding.get("wallet") or "")
    amt = _f(funding.get("amount"))
    bits = []
    if funder:
        bits.append(_dd_short_addr(funder))
    if amt is not None:
        bits.append(f"{amt:.2f} SOL")
    return " · ".join(bits) if bits else "—"


def _holder_pct_of_supply(row, supply=None):
    if not isinstance(row, dict):
        return None
    for key in (
        "percent_of_supply", "percentage", "pct_of_supply", "percent", "supply_percent",
        "supply_pct", "holding_percentage", "holdingPercent", "ownership_percentage",
        "ownershipPercent", "share_percentage", "sharePercent", "percentOfSupply",
        "percentageOfSupply",
    ):
        v = _f(row.get(key))
        if v is not None:
            return v * 100 if v <= 1.0 else v
    amt = _f(row.get("ui_amount") if row.get("ui_amount") is not None
             else row.get("holding") if row.get("holding") is not None
             else row.get("amount"))
    supply = _f(supply)
    if amt is not None and supply is not None and supply > 0:
        return 100.0 * amt / supply
    return None


def _dd_holder_detail_panel(res):
    chain = ((res.get("meta") or {}).get("chain") or "sol")
    top = ((res.get("inputs") or {}).get("top_holders")
           or (res.get("raw_data") or {}).get("top_holders")
           or {})
    overview = ((res.get("inputs") or {}).get("overview")
                or (res.get("raw_data") or {}).get("overview")
                or {})
    rows = (top.get("items") or top.get("rows") or top.get("holders") or [])
    if not rows:
        dist = ((res.get("inputs") or {}).get("distribution") or {})
        rows = (dist.get("holders") or dist.get("rows") or dist.get("items") or [])
    if not rows:
        return ""
    total_supply = (
        _f(top.get("total_supply")) or _f(top.get("totalSupply"))
        or _f(overview.get("supply")) or _f(overview.get("totalSupply"))
        or _f(overview.get("circulatingSupply")) or _f(overview.get("vSupply"))
    )
    body = []
    shown = rows[:24]
    for i, row in enumerate(shown, 1):
        if not isinstance(row, dict):
            continue
        wallet = str(row.get("wallet") or row.get("owner") or row.get("address") or "")
        wallet_url = _birdeye_wallet_url(chain, wallet) if wallet else ""
        copy_js = (f"navigator.clipboard.writeText({json.dumps(wallet)});"
                   f"this.textContent='Copied';setTimeout(()=>this.textContent='📋',1200);")
        pct = _holder_pct_of_supply(row, total_supply)
        amount = _f(row.get("ui_amount") if row.get("ui_amount") is not None
                    else row.get("holding") if row.get("holding") is not None
                    else row.get("amount"))
        amount_usd = _f(row.get("amount_usd") if row.get("amount_usd") is not None else row.get("amountUsd"))
        net_worth = _f(row.get("net_worth") if row.get("net_worth") is not None else row.get("netWorth"))
        sol_balance = _f(row.get("sol_balance") if row.get("sol_balance") is not None else row.get("solBalance"))
        hold_avg = _f(row.get("hold_avg_price") if row.get("hold_avg_price") is not None else row.get("holdAvgPrice"))
        avg_buy = _f(row.get("avg_buy_price") if row.get("avg_buy_price") is not None else row.get("avgBuyPrice"))
        avg_sell = _f(row.get("avg_sell_price") if row.get("avg_sell_price") is not None else row.get("avgSellPrice"))
        body.append(
            f'<tr style="border-top:1px solid #20283a">'
            f'<td style="padding:9px 8px;color:#cbd5e1;font-weight:700">{i}</td>'
            f'<td style="padding:9px 8px;color:#e6e8ef;font-family:ui-monospace,Menlo,monospace">'
            f'<div style="display:flex;align-items:center;gap:6px;white-space:nowrap">'
            f'<button type="button" onclick="{_html.escape(copy_js, quote=True)}" '
            f'style="padding:0;border:0;background:none;color:#dbe4f0;font:12px ui-monospace,Menlo,monospace;cursor:pointer">{_html.escape(_dd_short_addr(wallet))}</button>'
            f'<button type="button" onclick="{_html.escape(copy_js, quote=True)}" '
            f'style="display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:999px;border:1px solid #334155;background:#111827;color:#dbe4f0;cursor:pointer">📋</button>'
            f'{(f"<a href=\"{_html.escape(wallet_url, quote=True)}\" target=\"_blank\" rel=\"noopener noreferrer\" style=\"display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:999px;border:1px solid #334155;background:#111827;color:#8fb8ff;text-decoration:none\">↗</a>" if wallet_url else "")}'
            f'</div><div style="font-size:10px;color:#94a3b8;margin-top:3px">funding {_html.escape(_holder_funding_note(row))}</div></td>'
            f'<td style="padding:9px 8px;text-align:right;color:#ffffff;font-weight:800">{_pct(pct)}</td>'
            f'<td style="padding:9px 8px;text-align:right;color:#e6e8ef"><div style="font-weight:700">{_fmt_usd_short(amount_usd) if amount_usd is not None else _num(amount, 2)}</div>'
            f'<div style="font-size:10px;color:#94a3b8;margin-top:2px">{_num(amount,2)} units</div></td>'
            f'<td style="padding:9px 8px;text-align:right;color:#dbe4f0">{_fmt_usd_short(net_worth)}</td>'
            f'<td style="padding:9px 8px;text-align:right;color:#dbe4f0">{_fmt_usd(hold_avg) if hold_avg is not None else "—"}</td>'
            f'<td style="padding:9px 8px;text-align:right;color:#86efac">{_fmt_usd(avg_buy) if avg_buy is not None else "—"}</td>'
            f'<td style="padding:9px 8px;text-align:right;color:#fca5a5">{_fmt_usd(avg_sell) if avg_sell is not None else "—"}</td>'
            f'<td style="padding:9px 8px;text-align:right;color:#dbe4f0">{_num(sol_balance, 2)}</td>'
            f'</tr>'
        )
    return (
        f'<details style="background:#0f1115;border:1px solid #1e293b;border-top:2px solid #60a5fa;border-radius:10px;padding:0 12px 10px 12px;margin-top:10px">'
        f'<summary style="cursor:pointer;list-style:none;padding:11px 0;font-size:12px;font-weight:800;color:#f8fafc">'
        f'Holder Details <span style="color:#93c5fd;font-weight:600">mode wallet · holder infos on · top {len(shown)} of {len(rows)}</span></summary>'
        f'<div style="overflow:auto"><table style="border-collapse:collapse;font-size:12px;width:100%">'
        f'<thead><tr>'
        f'<th style="padding:5px 8px;text-align:left;color:#93c5fd;font-size:10px;text-transform:uppercase">#</th>'
        f'<th style="padding:5px 8px;text-align:left;color:#93c5fd;font-size:10px;text-transform:uppercase">Wallet</th>'
        f'<th style="padding:5px 8px;text-align:right;color:#93c5fd;font-size:10px;text-transform:uppercase">% Supply</th>'
        f'<th style="padding:5px 8px;text-align:right;color:#93c5fd;font-size:10px;text-transform:uppercase">Holding</th>'
        f'<th style="padding:5px 8px;text-align:right;color:#93c5fd;font-size:10px;text-transform:uppercase">Net worth</th>'
        f'<th style="padding:5px 8px;text-align:right;color:#93c5fd;font-size:10px;text-transform:uppercase">Hold avg</th>'
        f'<th style="padding:5px 8px;text-align:right;color:#93c5fd;font-size:10px;text-transform:uppercase">Avg buy</th>'
        f'<th style="padding:5px 8px;text-align:right;color:#93c5fd;font-size:10px;text-transform:uppercase">Avg sell</th>'
        f'<th style="padding:5px 8px;text-align:right;color:#93c5fd;font-size:10px;text-transform:uppercase">SOL</th>'
        f'</tr></thead><tbody>{"".join(body)}</tbody></table></div></details>')


def render_html(res):
    m, s, mk = res["meta"], res["score"], res["market"]
    rating = s.get("rating") or "?"
    health = s.get("liquidity_health") or {}
    final = s.get("final")
    fcolor = _RATING_COLOR.get(rating, "#64748b")
    ftone = _dd_tone(final)
    if health.get("label"):
        _hbg, _hfg, _hbd, _hc = _DD_TONE.get(health.get("tone") or "bad", _DD_TONE["bad"])
        health_chip = (
            f'<div title="{_html.escape(str(health.get("reason") or ""), quote=True)}" '
            f'style="background:{_hbg};border:1px solid {_hbd};border-radius:999px;padding:3px 9px;'
            f'font-size:10.5px;color:{_hfg}">Liquidity: '
            f'<span style="font-weight:700">{_html.escape(str(health["label"]))}</span></div>')
    else:
        health_chip = ""
    symbol = str(m.get("symbol") or "?")
    name = str(m.get("name") or "")
    overview = ((res.get("inputs") or {}).get("overview")
                or (res.get("raw_data") or {}).get("overview")
                or {})
    ext = (overview.get("extensions") if isinstance(overview, dict) else {}) or {}
    logo = _clean_urlish(
        m.get("logo")
        or overview.get("logoURI")
        or overview.get("logo_uri")
        or overview.get("logo")
        or overview.get("image")
        or ext.get("logoURI")
        or ext.get("logo_uri")
        or ext.get("logo")
        or ext.get("image")
        or ""
    )
    subtitle = f'{_html.escape(str(m.get("chain", "")).upper())} · {_html.escape(symbol)}'
    if name and name.lower() != symbol.lower():
        subtitle += f' · {_html.escape(name)}'
    subtitle += f' · mode {_html.escape(str(m.get("mode", "")))}'
    address = str(m.get("address") or "")
    birdeye_url = _birdeye_token_url(m.get("chain"), address) if address else ""
    copy_js = (f"navigator.clipboard.writeText({json.dumps(address)});"
               f"this.textContent='Copied';setTimeout(()=>this.textContent='📋',1200);")
    open_tip = "Open the Birdeye token page directly on the Holders tab."
    copy_tip = "Click to copy the token address."

    logo_fallback = (
        f'<div style="width:34px;height:34px;border-radius:999px;display:flex;align-items:center;justify-content:center;'
        f'background:linear-gradient(180deg,#132033 0%,#0f172a 100%);border:1px solid #1f2937;'
        f'color:#e6e8ef;font-size:13px;font-weight:800;flex:0 0 auto">{_html.escape(symbol[:1] or "?")}</div>'
    )
    logo_html = (
        f'<div style="position:relative;width:34px;height:34px;flex:0 0 auto">'
        f'{logo_fallback if not logo else ""}'
        f'{(f"<img src=\"{_html.escape(logo, quote=True)}\" alt=\"\" "
           f"style=\"position:absolute;inset:0;width:34px;height:34px;border-radius:999px;object-fit:cover;"
           f"border:1px solid #1f2937;background:#0f1115\" "
           f"onerror=\"this.style.display=\\'none\\';var p=this.parentNode;if(p&&p.firstElementChild)p.firstElementChild.style.display=\\'flex\\';\">"
           if logo else "")}'
        f'{(logo_fallback.replace("display:flex", "display:none") if logo else "")}'
        f'</div>'
    )

    header = (
        f'<div style="max-width:980px;margin-bottom:10px;'
        f'background:linear-gradient(180deg,#0d1322 0%,#0b1018 100%);'
        f'border:1px solid #182133;border-radius:12px;padding:12px 14px">'
        f'<div style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:start">'
        f'<div style="min-width:0">'
        f'<div style="display:flex;align-items:center;gap:10px;min-width:0">'
        f'{logo_html}'
        f'<div style="min-width:0">'
        f'<div style="font-size:20px;font-weight:800;color:#e6e8ef;line-height:1.1">🧠 Token Due-Diligence Score</div>'
        f'<div style="font-size:12px;color:#94a3b8;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
        f'{subtitle}</div></div></div>'
        f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:6px">'
        f'<button type="button" title="{_html.escape(copy_tip, quote=True)}" onclick="{_html.escape(copy_js, quote=True)}" '
        f'style="padding:0;border:0;background:none;color:#64748b;font:11px ui-monospace,Menlo,monospace;cursor:pointer">'
        f'{_html.escape(address)}</button>'
        f'<button type="button" title="{_html.escape(copy_tip, quote=True)}" onclick="{_html.escape(copy_js, quote=True)}" '
        f'style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;'
        f'border:1px solid #262b36;background:#0f1115;color:#cbd5e1;cursor:pointer">📋</button>'
        f'<a href="{_html.escape(birdeye_url, quote=True)}" target="_blank" rel="noopener noreferrer" '
        f'title="{_html.escape(open_tip, quote=True)}" '
        f'style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;'
        f'border:1px solid #262b36;background:#0f1115;color:#8fb8ff;text-decoration:none">↗</a></div></div>'
        f'<div style="text-align:right;flex-shrink:0;min-width:156px;align-self:center">'
        f'<div style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.34px">{_dd_label("Final Due-Diligence Score", "Final score after the weighted pillar mean is scaled by the liquidity-drawdown gate.")}</div>'
        f'<div style="font-size:30px;font-weight:900;color:{fcolor};line-height:1.1">'
        f'{f"{final:.1f}" if isinstance(final, (int, float)) else "N/A"}'
        f'<span style="font-size:14px;color:#64748b">/100</span></div>'
        f'<div style="margin-top:5px;display:flex;justify-content:flex-end;gap:6px;flex-wrap:wrap">{health_chip}{_dd_chip("Rating", rating, ftone)}</div>'
        f'</div></div></div>')

    flow = res.get("flow") or {}
    stats_frames = [f for f in ("24h", "4h", "1h", "15m") if f in set(flow.get("key_intervals") or [])]
    stats_default_frame = "24h" if "24h" in stats_frames else (stats_frames[0] if stats_frames else None)
    price_change = flow.get("price_change_pct") or {}
    volume_change = flow.get("volume_change_pct") or {}
    wallet_change = flow.get("wallet_change_pct") or {}
    trade_change = flow.get("trade_change_pct") or {}
    liquidity_change = flow.get("liquidity_change_pct") or {}
    volume_value = flow.get("volume_value") or {}
    wallet_value = flow.get("wallet_value") or {}
    trade_value = flow.get("trade_value") or {}

    def _frame_sub(frame, delta, prefix=None):
        if not frame:
            return ""
        return f'% change: {_dd_signed(delta)}'

    def _age_note(seconds):
        if seconds is None:
            return ""
        s = int(seconds)
        if s < 90:
            return f"{s}s ago"
        if s < 5400:
            return f"{int(round(s / 60))}m ago"
        return f"{s / 3600:.1f}h ago"

    # A live snapshot (overview / liquidity-latest) needs no caveat; when the
    # fallback OHLC bar close is used, label it with how stale it is.
    def _stale_note(source, age_seconds):
        return f"{_age_note(age_seconds)} (OHLC close)" if source == "ohlc_close" else ""

    liq_stale = _stale_note(flow.get("liquidity_now_source"),
                            flow.get("liquidity_now_age_seconds"))
    ex_stale = _stale_note(flow.get("exit_liquidity_now_source"),
                           flow.get("exit_liquidity_now_age_seconds"))

    def _liq_sub(frame, stale_note):
        bits = []
        if frame:
            bits.append(f"% change: {_dd_signed(liquidity_change.get(frame))}")
        if stale_note:
            bits.append(stale_note)
        return " · ".join(bits)

    def _stats_dynamic_tiles_for(frame):
        volume_label = "Volume"
        trades_label = "Trades"
        wallets_label = "Wallets"
        volume_val = volume_value.get(frame) if frame else mk.get("volume_24h_usd")
        trades_val = trade_value.get(frame) if frame else mk.get("trades_24h")
        wallets_val = wallet_value.get(frame) if frame else mk.get("unique_wallets_24h")
        liq_now = _dd_liquidity_now(res)
        return "".join([
            _dd_tile_html_sub("Price", _fmt_usd(mk.get("price_usd")),
                              _frame_sub(frame, price_change.get(frame), frame)),
            _dd_tile_html_sub("Liquidity", _fmt_usd(liq_now),
                              _liq_sub(frame, liq_stale)),
            _dd_tile_html_sub(volume_label, _fmt_usd(volume_val),
                              _frame_sub(frame, volume_change.get(frame), frame)),
            _dd_tile_html_sub(trades_label, _num(trades_val, 0),
                              _frame_sub(frame, trade_change.get(frame), frame)),
            _dd_tile_html_sub(wallets_label, _num(wallets_val, 0),
                              _frame_sub(frame, wallet_change.get(frame), frame)),
        ])

    static_tiles = "".join([
        _dd_tile("MCap", _fmt_usd(mk.get("market_cap_usd"))),
        _dd_tile("Exit Liquidity", _fmt_usd(mk.get("exit_liquidity_usd")), ex_stale or None),
        _dd_tile("Holders", _num(mk.get("holders"), 0)),
        _dd_tile("FDV", _fmt_usd(mk.get("fdv_usd"))),
    ])

    if stats_default_frame:
        stats_tiles = (
            f'<div data-dd-switch-root="top-stats" style="max-width:980px;margin-bottom:8px">'
            f'<div style="display:flex;justify-content:flex-end;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px">'
            f'{_dd_frame_switcher("top-stats", stats_frames, stats_default_frame)}</div>'
            + "".join(
                f'<div data-dd-frame-panel-root="top-stats" data-dd-frame-value="{_html.escape(frame, quote=True)}" '
                f'style="display:{"block" if frame == stats_default_frame else "none"}">'
                f'<div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin-bottom:6px">{_stats_dynamic_tiles_for(frame)}</div>'
                f'</div>'
                for frame in stats_frames
            )
            + f'<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px">{static_tiles}</div>'
            + f'</div>'
        )
    else:
        stats_tiles = (
            f'<div style="max-width:980px;margin-bottom:8px">'
            f'<div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin-bottom:6px">{_stats_dynamic_tiles_for(None)}</div>'
            f'<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px">{static_tiles}</div>'
            f'</div>'
        )

    gate = s.get("gate_detail") or {}
    gv = s.get("gate")
    chips = [
        _dd_chip("Verdict", s.get("verdict") or "N/A", ftone),
        _dd_chip("Gate", f"×{gv:.2f}" if isinstance(gv, (int, float)) else "N/A",
                 "good" if isinstance(gv, (int, float)) and gv >= 0.95 else "warn"),
        _dd_chip("Binding", str(gate.get("binding") or "—")),
        _dd_chip("Mode", str(m.get("mode") or "—")),
    ]
    if health.get("label"):
        # DEAD / DYING overrides the verdict visually — it is emitted even when the
        # score is still non-zero (e.g. ~30/100, band E).
        chips.insert(0, _dd_chip("Liquidity", health["label"], health.get("tone") or "bad"))
    if s.get("hard_blocked"):
        chips.append(_dd_chip("Hard block", "score forced to 0", "bad"))
    chips_html = "".join(chips)

    blocks = "".join(
        _dd_score_block(PILLAR_LABEL[k], res["pillars"][k]["score"],
                        s["weights_used"].get(k, 0.0), res["pillars"][k]["coverage"])
        for k in PILLAR_ORDER)

    ls = res.get("liquidity_stats") or {}
    liq_panel = ""
    if ls:
        win = ls.get("window") or {}
        head = (f'{_dd_label("Liquidity Window", "Rolling liquidity statistics from the liquidity OHLC endpoint.")} · {win.get("span_hours", "?")}h '
                f'({win.get("candles", "?")}×{_html.escape(str(win.get("resolution", "?")))}'
                f' · {_html.escape(str(win.get("source", "")))})')
        rows = _dd_liq_row("Total liquidity", ls.get("liquidity")) + _dd_liq_row("Exit liquidity", ls.get("exit_liquidity"))
        liq_panel = (
            f'<div style="background:linear-gradient(180deg,#0f1624 0%,#0f1115 100%);border:1px solid #1c2a42;'
            f'border-top:2px solid #3b82f6;border-radius:10px;padding:10px 12px">'
            f'<div style="font-size:12px;font-weight:700;color:#e6e8ef;margin-bottom:8px">{head}</div>'
            f'<div style="overflow:auto"><table style="border-collapse:collapse;font-size:12px">'
            f'<tbody>{rows}</tbody></table></div></div>')

    hold_panel = _dd_holder_panel(res)
    holder_detail_panel = _dd_holder_detail_panel(res)
    flow_panel = ""

    sm = res.get("smart_money_signals") or {}
    sm_summary_html = ""
    flow = res.get("flow") or {}
    flow_mf = flow.get("money_flow") or {}
    flow_vol = flow.get("volume_value") or {}
    sm_frames = [f for f in ("24h", "4h", "1h", "15m") if f in set(flow.get("key_intervals") or [])]
    sm_default_frame = "24h" if "24h" in sm_frames else (sm_frames[0] if sm_frames else None)
    sm_root_name = "smart-section"
    sm_switcher_html = _dd_frame_switcher(sm_root_name, sm_frames, sm_default_frame) if sm_default_frame else ""
    sm_mini_flow_html = _dd_smart_money_mini_flow(res, root_name=sm_root_name, include_switcher=False)
    if not sm:
        sm_rows = [("Status", "Not measured in this mode")]
    else:
        head_txt = f"{_num(sm.get('smart_traders_no'), 0)} smart-trader wallet(s)"
        if sm.get("smart_trader_pct_of_supply") is not None:
            head_txt += f" · holds {_pct(sm.get('smart_trader_pct_of_supply'))}"
        action = str(sm.get("action") or "Unknown")
        net = sm.get("net_flow_24h_usd")
        net_pct = sm.get("net_flow_pct_of_vol")
        ratio = sm.get("sm_buy_ratio")
        buys = _num(sm.get("sm_buy_count_24h"), 0)
        sells = _num(sm.get("sm_sell_count_24h"), 0)
        flow_tone = {"Accumulating": "good", "Distributing": "bad"}.get(action, "warn")
        sm_bits = []
        sm_summary_bits = []
        if isinstance(net_pct, (int, float)):
            chip = _dd_chip("Net", f"{net_pct*100:+.1f}% of vol", flow_tone)
            sm_bits.append(chip)
            sm_summary_bits.append(chip)
        if sm.get("whale_sell_share_pct") is not None:
            chip = _dd_chip("Whale sell", _pct(sm.get("whale_sell_share_pct")), "warn")
            sm_bits.append(chip)
            sm_summary_bits.append(chip)
        if sm.get("sm_buy_count_24h") is not None or sm.get("sm_sell_count_24h") is not None:
            sm_bits.append(_dd_chip("Buys / sells", f"{buys} / {sells}", "neutral"))
        net_color = "#22c55e" if isinstance(net, (int, float)) and net >= 0 else "#ef4444"
        summary_panels = []
        for frame in sm_frames or ["24h"]:
            all_cell = ((flow_mf.get("all") or {}).get(frame) or {})
            all_net = _f(all_cell.get("net_usd"))
            frame_vol = _f(flow_vol.get(frame))
            frame_net_pct = (all_net / frame_vol) if all_net is not None and frame_vol not in (None, 0) else None
            frame_net_color = "#22c55e" if isinstance(all_net, (int, float)) and all_net >= 0 else "#ef4444"
            summary_panels.append(
                f'<div data-dd-frame-panel-root="{_html.escape(sm_root_name, quote=True)}" '
                f'data-dd-frame-value="{_html.escape(frame, quote=True)}" '
                f'style="display:{"block" if frame == sm_default_frame else "none"}">'
                f'<div style="display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap">'
                f'<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
                f'{_dd_chip("Action", action, flow_tone)}'
                f'{"".join(sm_summary_bits)}'
                f'</div>'
                f'<div style="display:flex;align-items:baseline;gap:8px;white-space:nowrap">'
                f'<span style="font-size:10px;color:#94a3b8;text-transform:uppercase">{_html.escape(frame)} net flow</span>'
                f'<span style="font-size:18px;font-weight:900;color:{frame_net_color}">{_fmt_usd_short(all_net)}</span>'
                + (f'<span style="font-size:11px;color:#64748b">{frame_net_pct*100:+.1f}% of vol</span>'
                   if isinstance(frame_net_pct, (int, float)) else "")
                + f'</div></div></div>'
            )
        sm_summary_html = (
            f'<div style="background:#0c1018;border:1px solid #1c2432;border-radius:10px;padding:8px 10px;margin-bottom:8px">'
            f'{"".join(summary_panels)}</div>'
        )
        sm_rows = [
            ("Presence", _html.escape(head_txt)),
            ("Net flow 24h", f'{_fmt_usd_short(net)}'
                             + (f' <span style="color:#64748b">({net_pct*100:+.1f}% of vol)</span>'
                                if isinstance(net_pct, (int, float)) else "")),
            ("Buys / sells", f'{buys} / {sells}'
                             + (f' <span style="color:#64748b">(ratio '
                                f'{ratio})</span>'
                                if ratio is not None else "")),
            ("Smart buy share", f'{_pct(sm.get("hold_ratio_pct"))}'
                              if sm.get("hold_ratio_pct") is not None else "—"),
            ("Smart traders", f'{_num(sm.get("sm_trader_count_24h"), 0)} active traders / 24h'
                              if sm.get("sm_trader_count_24h") is not None else "—"),
            ("KOL", f'{_num(sm.get("kol_count"), 0)} · {_html.escape(str(sm.get("kol_source") or ""))}'
                    + (f' · holds {_pct(sm.get("kol_pct_of_supply"))}'
                       if sm.get("kol_pct_of_supply") is not None else "")),
            ("KOL flow", f'{_fmt_usd_short(sm.get("kol_net_flow_24h_usd"))}'
                         if sm.get("kol_net_flow_24h_usd") is not None else "—"),
            ("Whales", f'{_num(sm.get("whale_count"), 0)}'
                       + (f' · holds {_pct(sm.get("whale_pct_of_supply"))}'
                          if sm.get("whale_pct_of_supply") is not None else "")
                       + (f' · sell share {_pct(sm.get("whale_sell_share_pct"))}'
                          if sm.get("whale_sell_share_pct") is not None else "")),
            ("Whale flow", f'{_fmt_usd_short(sm.get("whale_net_flow_24h_usd"))}'
                           if sm.get("whale_net_flow_24h_usd") is not None else "—"),
        ]
    sm_rows_html = "".join(
        f'<div style="display:grid;grid-template-columns:96px minmax(0,1fr);gap:8px;align-items:start;'
        f'padding:5px 0;border-top:1px solid #161b26">'
        f'<span style="font-size:11px;color:#64748b;white-space:nowrap">{k}</span>'
        f'<span style="font-size:13px;color:#cbd5e1;line-height:1.35">{v}</span></div>'
        for k, v in sm_rows)
    side = (
        f'<div style="display:flex;flex-direction:column;gap:10px">'
        f'<div data-dd-switch-root="{_html.escape(sm_root_name, quote=True)}" style="background:#0f1115;border:1px solid #151b24;border-radius:10px;padding:10px 12px">'
        f'<div style="display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:6px">'
        f'<div style="font-size:12px;font-weight:700;color:#e6e8ef">{_dd_label("Smart Money", "Signals derived from token money-flow, holder profile cohorts, and top-holder wallet balances.")}</div>'
        f'{sm_switcher_html}</div>'
        f'{sm_summary_html}'
        f'<div style="display:grid;grid-template-columns:minmax(260px,.82fr) minmax(360px,1.02fr);gap:8px;align-items:start">'
        f'<div>{sm_rows_html}'
        + (f'<div style="font-size:10.5px;color:#64748b;margin-top:6px;line-height:1.5">'
           f'{_html.escape(str(sm.get("action_detail") or ""))}</div>'
           if sm.get("action_detail") and not sm_summary_html else "")
        + f'</div>{sm_mini_flow_html}</div></div>'
        f'<div style="background:#0f1115;border:1px solid #151b24;border-radius:10px;padding:10px 12px">'
        f'<div style="font-size:12px;font-weight:700;color:#e6e8ef;margin-bottom:6px">{_dd_label("Run Snapshot", "Execution metadata for this run, including billed CU and endpoint count.")}</div>'
        f'<div style="font-size:12px;color:#cbd5e1">⚡CU cost: {int(m.get("cu_billed_total") or 0)}</div>'
        f'<div style="font-size:12px;color:#cbd5e1;margin-top:4px">'
        f'🔌 {int(m.get("endpoint_calls") or 0)} endpoint calls</div></div></div>')

    cav_html = ""
    for c in (m.get("caveats") or []):
        c = str(c)
        if c.startswith("⚠"):
            c = c.lstrip("⚠ ").strip()
        cav_html += (f'<div style="font-size:11px;color:#fbbf24;margin-top:4px">'
                     f'⚠ {_html.escape(c)}</div>')

    ttip_css = '<style>details summary::-webkit-details-marker{display:none}</style>'
    return (
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        f'background:#0a0e1a;color:#e2e8f0;padding:14px;border-radius:12px">'
        f'{ttip_css}'
        f'{header}'
        f'{stats_tiles}'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">{chips_html}</div>'
        f'{flow_panel}'
        f'<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:10px">{blocks}</div>'
        f'<div style="display:grid;grid-template-columns:minmax(0,1.15fr) minmax(260px,.85fr);gap:12px;margin-bottom:10px">{liq_panel}{hold_panel}</div>'
        f'<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(290px,.62fr);gap:10px">{side}</div>'
        f'{holder_detail_panel}'
        f'{cav_html}</div>')


def render(res, fmt, explain=False):
    fmt = (fmt or "ui").lower()
    if isinstance(res, dict) and "result" in res and isinstance(res.get("result"), dict):
        res = res["result"]
    if fmt in ("json", "raw-json", "plain", "telegram"):
        res = _strip_non_ui_recursive(json.loads(json.dumps(res, ensure_ascii=False)))
    if fmt in ("json", "raw-json"):
        return json.dumps(_public_json_contract(res), ensure_ascii=False, indent=2 if fmt == "json" else None)
    if fmt == "plain":
        return render_plain(res)
    if fmt == "telegram":
        return render_telegram(res)
    return json.dumps(_ui_envelope(res, explain), ensure_ascii=False)


# ===========================================================================
# Cache (compatible with `birdeye_cli.py history-render`)
# ===========================================================================

def _cache_dir(custom=None):
    p = Path(custom) if custom else CACHE_DIR_DEFAULT
    p.mkdir(parents=True, exist_ok=True)
    return p


def _run_id(address, mode, ts=None):
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in f"{address}_{mode}")
    return f"{SKILL_NAME}_{safe}_{ts or int(time.time())}"


def _write_cache(cdir, run_id, res, store_inputs=True):
    cache_res = _strip_non_ui_recursive(json.loads(json.dumps(res, ensure_ascii=False)))
    payload = {
        "schemaVersion": 1, "kind": SKILL_KIND, "run_id": run_id,
        "params": {"chain": res["meta"]["chain"], "address": res["meta"]["address"],
                   "mode": res["meta"]["mode"]},
        "cu_used_total": res["meta"]["cu_billed_total"],
        "cu_breakdown": res["meta"]["cu_breakdown"],
        "snapshot_time": _dt.datetime.now().isoformat(timespec="seconds"),
        "rendered_plain": render(cache_res, "plain"),
        "rendered_telegram": render(cache_res, "telegram"),
        "rendered_json": render(cache_res, "raw-json"),
        "rendered_ui": render(res, "ui"),
        "result": cache_res,
    }
    if not store_inputs:
        payload["result"] = {k: v for k, v in cache_res.items() if k != "inputs"}
    fp = cdir / (run_id + ".json")
    fp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return fp, run_id


def _read_rescore(value):
    """Accept base64 JSON, a file path, or a run-id."""
    raw = value.strip()
    obj = None
    p = Path(raw)
    if p.is_file():
        obj = json.loads(p.read_text(encoding="utf-8"))
    if obj is None:
        cdir = _cache_dir()
        for cand in (cdir / (raw + ".json"), cdir / raw):
            if cand.is_file():
                obj = json.loads(cand.read_text(encoding="utf-8"))
                break
    if obj is None:
        pad = raw + "=" * (-len(raw) % 4)
        try:
            obj = json.loads(base64.b64decode(pad).decode("utf-8"))
        except Exception:
            return None
    if isinstance(obj, dict) and "result" in obj:
        return obj["result"]
    if isinstance(obj, dict) and obj.get("kind") == SKILL_KIND:
        return obj
    return None


def _safe_render_output(res, fmt, explain=False):
    fmt = str(fmt or "ui").lower()
    out = render(res, fmt, explain)
    if fmt in ("json", "raw-json"):
        try:
            parsed = json.loads(out)
        except Exception:
            parsed = None
        if (isinstance(parsed, dict) and "html" in parsed) or "\"html\"" in out:
            return json.dumps(
                _public_json_contract(_strip_non_ui_recursive(res)),
                ensure_ascii=False,
                indent=2 if fmt == "json" else None,
            )
        return out
    if fmt == "plain":
        if "<div" in out or "\"html\"" in out:
            return render_plain(_strip_non_ui_recursive(res))
        return out
    if fmt == "telegram":
        if "<div" in out or "\"html\"" in out:
            return render_telegram(_strip_non_ui_recursive(res))
        return out
    return out


# ===========================================================================
# CLI wiring
# ===========================================================================

def add_parser(sub, chains=None):
    chain_ids = list((chains or CHAINS).keys())
    p = sub.add_parser(
        "token-dd-score",
        help=f"Skill #24 — Token Due-Diligence Score 0-100 + rating A+..F. "
             f"standard = token_overview + token_security + live liquidity snapshot (56 CU); "
             f"advanced = + distribution/profile/top-holders/money-flow/liquidity-OHLC (~186 CU).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "5 weighted pillars (Security / Holders / Activity / Liquidity / Smart Money),\n"
            "each a weighted mean of ramped sub-scores, then a smooth liquidity-drawdown gate.\n"
            "Absent sub-signals are dropped AND their weight removed, so the pillar score\n"
            "reflects measured coverage only."
        ))
    p.add_argument("--chain", choices=chain_ids, default="sol")
    p.add_argument("--address", required=True, help="Token contract / mint address")
    p.add_argument("--mode", choices=["standard", "advanced"], default="standard",
                   help="standard = overview + security + live liquidity snapshot (56 CU). advanced = all pillars (~186 CU).")
    p.add_argument("--top-n", dest="top_n", type=int, default=20, choices=[10, 20, 50],
                   help="Holder rows requested from /holder/v1/distribution (advanced).")
    p.add_argument("--liq-resolution", dest="liq_resolution",
                   choices=["auto", "1m", "5m", "15m", "30m", "1h", "4h", "1D"],
                   default="15m", help="Liquidity OHLC resolution. auto = 15m for 24h window.")
    p.add_argument("--liq-candles", dest="liq_candles", type=int, default=96,
                   help="Liquidity OHLC candle count (max 100). 15m x 96 = 24h.")
    p.add_argument("--pace", action="store_true", default=False,
                   help="Enable the pace sub-signal in Activity (Phase 2, default OFF).")
    p.add_argument("--skip", default=None,
                   help="Comma list to skip (advanced): distribution,holder_profile,"
                        "top_holders,token_money_flow,liquidity (alias: liq)")
    p.add_argument("--weights-preset", dest="weights_preset",
                   choices=list(WEIGHT_PRESETS.keys()), default="default")
    p.add_argument("--rescore", default=None,
                   help="0-CU re-score: run-id, cache file path, or base64 of a previous "
                        "result. Re-uses cached inputs, calls no API.")
    p.add_argument("--no-store-inputs", dest="store_inputs", action="store_false", default=True,
                   help="Do not persist raw inputs in cache (disables --rescore replay).")
    p.add_argument("--explain", action="store_true", default=False,
                   help="Include per-sub-signal breakdown in the 'ui' payload.")
    p.add_argument("--format", choices=["ui", "json", "telegram", "plain", "raw-json",
                                       "render", "rendered"], default="ui")
    p.set_defaults(func=run)
    return p


def run(args):
    """Entry point used by the unified CLI: `birdeye_cli.py token-dd-score ...`."""
    return cmd_token_dd_score(args)


def cmd_token_dd_score(args):
    if getattr(args, "liq_resolution", "") == "auto":
        args.liq_resolution = "15m"

    if getattr(args, "rescore", None):
        prev = _read_rescore(args.rescore)
        if not prev:
            print(f"[E] --rescore could not decode '{args.rescore}'")
            return 3
        res = _rescore(prev, args)
        print(_safe_render_output(res, getattr(args, "format", "ui"), getattr(args, "explain", False)))
        return 0

    t0 = time.perf_counter()
    res = analyze(args)
    if isinstance(res, int):
        return res
    res["meta"]["latency_ms"] = int((time.perf_counter() - t0) * 1000)

    if getattr(args, "write_cache", True):
        try:
            fp, rid = _write_cache(_cache_dir(getattr(args, "cache_dir", None)),
                                   _run_id(res["meta"]["address"], res["meta"]["mode"]),
                                   res, getattr(args, "store_inputs", True))
            res["meta"]["run_id"] = rid
            res["meta"]["cache_file"] = str(fp)
            # First-line marker so the unified CLI / HUB UI can detect run_id + CU
            # and enable 0-CU format switching (same convention as other skills).
            sys.stdout.write(f"#RUN_ID {rid}\ttoken-dd-score\tcu={res['meta']['cu_billed_total']}\n")
        except OSError as e:
            res["meta"].setdefault("caveats", []).append(f"cache write failed: {e}")

    print(_safe_render_output(res, getattr(args, "format", "ui"), getattr(args, "explain", False)))
    return 0


def _rescore(prev, args):
    """Re-run scoring from a previous result's stored inputs (0 API calls)."""
    inputs = prev.get("inputs") or prev.get("raw_data") or {}
    ovd = dict(inputs.get("overview") or {})
    secd = inputs.get("security") or {}
    dist = inputs.get("distribution") or {}
    profile = inputs.get("holder_profile") or {}
    top_holders = inputs.get("top_holders") or {}
    token_money_flow = inputs.get("token_money_flow") or inputs.get("smart_money") or {}
    candles = inputs.get("liquidity_ohlc") or []
    liq_latest = inputs.get("liquidity_latest") or {}
    liq_resolution = getattr(args, "liq_resolution", "15m") or "15m"
    # Reuse the stored snapshot so a 0-CU re-score keeps the original "current"
    # value (and its OHLC staleness) instead of drifting with wall-clock time.
    liq_snapshot = ((prev.get("derived_data") or {}).get("liquidity_snapshot")
                    or _liq_snapshot(ovd, liq_latest, candles, liq_resolution))

    flow = _flow_block(ovd, candles, liq_resolution, liq_snapshot)
    flow["money_flow"] = _merge_money_flow_maps(flow.get("money_flow"), _money_flow_map(token_money_flow))

    mode = getattr(args, "mode", None) or prev["meta"]["mode"]
    conc = _concentration(dist, secd, getattr(args, "top_n", 20) or 20)
    pillars = {
        "security": score_security(secd, ovd, prev["meta"]["address"], prev["meta"]["chain"]),
        "holders": score_holders(conc, ovd, profile, top_holders),
        "activity": score_activity(ovd, pace_on=bool(getattr(args, "pace", False))),
        "liquidity": score_liquidity(ovd, candles, liq_resolution,
                                     liq_latest, liq_snapshot.get("request_time")),
        "smart_money": score_smart_money(token_money_flow, top_holders, conc, ovd, profile),
    }
    if mode == "standard":
        pillars["smart_money"] = {"score": None, "coverage": 0.0, "breakdown": [],
                                  "signals": {}, "hard_blocks": []}
    comp = compose(pillars, mode, getattr(args, "weights_preset", "default") or "default",
                   prev["meta"].get("chain", "sol"))
    out = json.loads(json.dumps(prev, ensure_ascii=False))
    out["meta"]["mode"] = mode
    out["meta"]["weights_preset"] = getattr(args, "weights_preset", "default")
    out["meta"]["weights_declared"] = comp.get("weights_declared", {})
    out["meta"]["weights_shift"] = comp.get("applied_shift")
    out["meta"]["cu_breakdown"] = {"base": 0, "list": 0, "advanced_security": 0,
                                   "risk_history": 0, "refunded_rollback": 0}
    out["meta"]["cu_billed_total"] = 0
    out["meta"].setdefault("caveats", []).insert(0, "0-CU re-score from cache")
    out["score"] = {
        "final": comp["final"], "base_before_gate": comp.get("base_before_gate"),
        "rating": comp["rating"], "verdict": comp["verdict"], "gate": comp["gate"],
        "gate_detail": comp["gate_detail"], "liquidity_health": comp.get("liquidity_health"),
        "weights_used": comp["weights_used"],
        "pillar_points": comp.get("pillar_points", {}), "hard_blocked": False,
    }
    out["pillars"] = {k: {"score": (pillars[k] or {}).get("score"),
                          "coverage": (pillars[k] or {}).get("coverage", 0.0),
                          "breakdown": (pillars[k] or {}).get("breakdown", [])}
                      for k in PILLAR_ORDER}
    out["holder_top"] = conc
    out["holder_cohorts"] = (pillars["holders"] or {}).get("cohorts", {})
    out["liquidity_stats"] = (pillars["liquidity"] or {}).get("stats")
    out["flow"] = flow
    out["smart_money_signals"] = (pillars["smart_money"] or {}).get("signals", {})
    out["market"]["liquidity_usd"] = _f(flow.get("liquidity_now")) or _f(out.get("market", {}).get("liquidity_usd"))
    out["market"]["exit_liquidity_usd"] = (pillars["liquidity"] or {}).get("exit_now")
    out["raw_data"] = inputs
    out["inputs"] = inputs
    out["derived_data"] = {
        "market": out.get("market") or {},
        "flow": out.get("flow"),
        "holder_top": out.get("holder_top"),
        "holder_cohorts": out.get("holder_cohorts"),
        "liquidity_stats": out.get("liquidity_stats"),
        "liquidity_snapshot": (pillars["liquidity"] or {}).get("snapshot"),
        "smart_money_signals": out.get("smart_money_signals"),
    }
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(
        prog="token-dd-score",
        description="Token Due-Diligence score (0-100) — standalone entry point.")
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--no-write-cache", dest="write_cache", action="store_false", default=True)
    sub = p.add_subparsers(dest="cmd")
    add_parser(sub)
    # Two invocation shapes are accepted:
    #   token-dd-score.py --chain sol --address X --mode advanced
    #   token-dd-score.py token-dd-score --chain sol --address X
    if "token-dd-score" not in argv:
        argv = ["token-dd-score"] + argv
    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
