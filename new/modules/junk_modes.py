"""Additional junk-token scoring modes backed by JSON model assets.

Modes
-----
* `unsupervised`: delegates to the existing Logistic Regression 16-feature model.
* `function`: uses the tuned heuristic scorer from `function_params.json`.
* `supervised`: uses the exported GradientBoosting JSON model.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from . import junk_ml as _lr

_HERE = Path(__file__).resolve().parent

def _uniq_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


# Model assets ship inside this folder so the project stays self-contained.
# $BIRDEYE_SUPERVISED_MODEL / $BIRDEYE_FUNCTION_PARAMS can override the path.
_SUPERVISED_CANDIDATES = _uniq_paths([p for p in [
    Path(os.environ["BIRDEYE_SUPERVISED_MODEL"]) if os.environ.get("BIRDEYE_SUPERVISED_MODEL") else None,
    _HERE / "junk_supervised_model.json",
    _HERE / "supervised_model.json",
] if p is not None])

_FUNCTION_CANDIDATES = _uniq_paths([p for p in [
    Path(os.environ["BIRDEYE_FUNCTION_PARAMS"]) if os.environ.get("BIRDEYE_FUNCTION_PARAMS") else None,
    _HERE / "junk_function_params.json",
    _HERE / "function_params.json",
] if p is not None])

# Fallback parameters used when the asset is missing; the shipped JSON is the
# source of truth and simply overrides these keys.
_FUNCTION_DEFAULTS = {
    "band_liq_hi": 100000.0,
    "band_liq_lo": 10000.0,
    "band_ramp_holder_hi": 5000.0,
    "band_ramp_vol_hi": 100000.0,
    "function_threshold": 0.9,
    "guard_holder": 20000.0,
    "guard_liq": 1000000.0,
    "guard_vol": 100000.0,
    "hard_holder_max": 3.0,
    "hard_liq_max": 10.0,
    "hard_ratio_max": 45433.7186430309,
    "inactive_alive_holder_min": 20.0,
    "inactive_alive_liq_min": 1000.0,
    "inactive_alive_ratio_max": 10.0,
    "price_drop_hi": 99.9,
    "price_drop_knee": 98.0,
    "price_drop_lo": 90.0,
    "price_light": 0.38939921497524266,
    "ramp_holder_hi": 1000.0,
    "ramp_holder_lo": 10.0,
    "ramp_liq_hi": 100000.0,
    "ramp_liq_lo": 10.0,
    "ramp_vol_hi": 10000.0,
    "ramp_vol_lo": 1.0,
    "ratio_ref": 100.0,
    "ratio_slope": 1.2,
    "ratio_span": 100.0,
    "relief_holder_hi": 10000.0,
    "relief_max": 0.17883852679399187,
    "relief_vol_hi": 100000.0,
    "risk_floor": 0.7,
    "risk_liq_max": 100000.0,
    "risk_price_drop": -95.0,
    "soft_ratio_holder_min": 61.16466271588971,
    "soft_ratio_vol_min": 4920.725626563919,
    "susp_top1": 99.0,
    "susp_top10": 95.0,
    "susp_top10_full": 99.0,
    "tiny_base_floor": 0.8,
    "tiny_holder_max": 4.0,
    "tiny_vol_max": 1.0,
    "top10_hi": 100.0,
    "top10_lo": 95.0,
    "top1_hi": 99.0,
    "top1_lo": 90.0,
    "top3_hi": 100.0,
    "top3_lo": 90.0,
    "w_holder": 0.08960903264310115,
    "w_liq": 0.6519359206073068,
    "w_price": 0.14130242600634127,
    "w_ratio": 0.12181536350880473,
    "w_top1": 0.05,
    "w_top10": 0.01,
    "w_top3": 0.017012809395993506,
    "w_vol": 0.13663968324078737,
}

_CAL_KNEE_X = 0.45
_CAL_KNEE_Y = 0.7
_CAL_CAP = 0.92
_LR_LABEL = "Logistic Regression (16 features)"

_SUPERVISED_CACHE: dict[str, Any] | None = None
_FUNCTION_CACHE: dict[str, Any] | None = None


def _load_json(candidates: list[Path]) -> dict[str, Any]:
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"JSON asset not found. Searched: {[str(p) for p in candidates]}")


def _get_supervised_model() -> dict[str, Any]:
    global _SUPERVISED_CACHE
    if _SUPERVISED_CACHE is None:
        _SUPERVISED_CACHE = _load_json(_SUPERVISED_CANDIDATES)
    return json.loads(json.dumps(_SUPERVISED_CACHE))


def _get_function_params() -> dict[str, Any]:
    global _FUNCTION_CACHE
    if _FUNCTION_CACHE is None:
        payload = dict(_FUNCTION_DEFAULTS)
        for path in _FUNCTION_CANDIDATES:
            if path.exists():
                payload.update(json.loads(path.read_text(encoding="utf-8")))
                break
        _FUNCTION_CACHE = payload
    return dict(_FUNCTION_CACHE)


def normalize_mode(mode: str | None) -> str:
    m = str(mode or "unsupervised").strip().lower()
    if m in {"unsup", "ml", "ml_unsup"}:
        return "unsupervised"
    if m in {"fn", "heuristic"}:
        return "function"
    if m in {"sup", "gbm", "tree"}:
        return "supervised"
    return m if m in {"unsupervised", "function", "supervised"} else "unsupervised"


def merge_mode_payload(mode: str, override: dict[str, Any] | None = None) -> dict[str, Any]:
    override = override or {}
    if mode == "function":
        base = _get_function_params()
        base.update(override)
        return base
    if mode == "supervised":
        base = _get_supervised_model()
        base.update(override)
        return base
    return _lr._get_model()


def model_label(mode: str, payload: dict[str, Any] | None = None) -> str:
    mode = normalize_mode(mode)
    payload = payload or {}
    if mode == "function":
        return "Function"
    if mode == "supervised":
        return str(payload.get("model_name") or "Supervised")
    return _LR_LABEL


def threshold_points(mode: str, payload: dict[str, Any] | None = None) -> float:
    payload = payload or {}
    if normalize_mode(mode) == "unsupervised":
        return float(payload.get("threshold", 95.0))
    if normalize_mode(mode) == "function":
        return float(payload.get("function_threshold", 0.9)) * 100.0
    return float(payload.get("threshold", 0.9)) * 100.0


def _num(value: Any, default: float | None = None) -> float | None:
    f = _lr._to_float(value)
    return default if f is None else f


def _safe_log10(value: float) -> float:
    return math.log10(value) if value > 0 else 0.0


def build_supervised_features(token: dict[str, Any]) -> dict[str, float]:
    liquidity = _num(token.get("liquidity_usd"))
    liq_missing = 1 if liquidity is None else 0
    liq = 0.0 if liquidity is None else liquidity

    holder_count = _num(token.get("holder_count"))
    holder_missing = 1 if holder_count is None else 0
    holder = 0.0 if holder_count is None else holder_count

    mcap = _num(token.get("mcap_usd"), 0.0) or 0.0
    fdv = _num(token.get("fdv_usd"), 0.0) or 0.0
    valuation = _num(token.get("mcap_usd"))
    if valuation is None:
        valuation = _num(token.get("fdv_usd"))
    valuation = valuation or 0.0

    vol = _num(token.get("vol_24h_usd"))
    vol4 = _num(token.get("volume_4h_usd"))
    if (vol is None or vol == 0) and vol4 is not None and vol4 > 0:
        vol = vol4
    vol = vol or 0.0

    tx = _num(token.get("tx_24h"), 0.0) or 0.0
    trader = _num(token.get("trader_24h"), 0.0) or 0.0
    price_change = _num(token.get("price_change_24h"), 0.0) or 0.0

    v1h = _num(token.get("volume_1h_usd"), 0.0) or 0.0
    v8h = _num(token.get("volume_8h_usd"), 0.0) or 0.0
    v7d = _num(token.get("vol_7d_usd"), 0.0) or 0.0
    v30d = _num(token.get("vol_30d_usd"), 0.0) or 0.0
    t1h = _num(token.get("trade_1h_count"), 0.0) or 0.0
    t4h = _num(token.get("trade_4h_count"), 0.0) or 0.0
    t8h = _num(token.get("trade_8h_count"), 0.0) or 0.0
    t7d = _num(token.get("tx_7d"), 0.0) or 0.0
    t30d = _num(token.get("tx_30d"), 0.0) or 0.0
    fees = _num(token.get("global_fees_paid"), 0.0) or 0.0

    now = _num(token.get("now_unix"), 0.0) or 0.0
    if not now:
        now = float(__import__("time").time())
    chain = str(token.get("chain") or "solana").lower()
    is_sol = chain == "solana"
    creation = _num(token.get("creation_time"), 0.0) or 0.0
    last_trade = _num(token.get("last_trade_unix_time"), 0.0) or 0.0
    token_age_days = ((now - creation) / 86400.0) if (is_sol and creation > 0) else 0.0
    days_since_last_trade = ((now - last_trade) / 86400.0) if (is_sol and last_trade > 0) else 0.0

    top1 = _num(token.get("top1_pct"))
    top3 = _num(token.get("top3_pct"))
    top10 = _num(token.get("top10_pct"))
    top_missing = 1 if top1 is None else 0

    def ratio(a: float, b: float) -> float:
        return a / b if b > 0 else 0.0

    return {
        "log_val": _safe_log10(valuation),
        "log_fdv": _safe_log10(fdv),
        "log_mcap": _safe_log10(mcap),
        "log_liq": 2.0 if liq_missing else math.log10(liq + 1.0),
        "log_vol": math.log10(vol + 1.0),
        "log_tx": math.log10(tx + 1.0),
        "log_trader": math.log10(trader + 1.0),
        "log_holder": 1.0 if holder_missing else math.log10(holder + 1.0),
        "val_liq_gap": _safe_log10(valuation) - (2.0 if liq_missing else math.log10(liq + 1.0)),
        "val_vol_gap": _safe_log10(valuation) - math.log10(vol + 1.0),
        "liq_vol_gap": (2.0 if liq_missing else math.log10(liq + 1.0)) - math.log10(vol + 1.0),
        "val_holder_gap": _safe_log10(valuation) - (1.0 if holder_missing else math.log10(holder + 1.0)),
        "liq_holder_gap": (2.0 if liq_missing else math.log10(liq + 1.0)) - (1.0 if holder_missing else math.log10(holder + 1.0)),
        "liq_to_val": ratio(liq, valuation) if not liq_missing else 0.0,
        "vol_to_val": ratio(vol, valuation),
        "vol_to_liq": ratio(vol, liq) if not liq_missing else 0.0,
        "vol_per_tx": ratio(vol, tx),
        "fdv_to_mcap": ratio(fdv, mcap),
        "holder_per_mcap": ratio(holder, mcap),
        "holder_per_liq": ratio(holder, liq) if not liq_missing else 0.0,
        "price_change_24h": price_change,
        "abs_price_change": abs(price_change),
        "has_val": 1.0 if valuation > 0 else 0.0,
        "has_liq": 1.0 if (not liq_missing and liq > 0) else 0.0,
        "has_vol": 1.0 if vol > 0 else 0.0,
        "has_holder": 1.0 if holder > 0 else 0.0,
        "is_dead": 1.0 if (vol == 0 and tx == 0 and trader == 0) else 0.0,
        "holder_missing": float(holder_missing),
        "liq_missing": float(liq_missing),
        "token_age_days": token_age_days,
        "is_new_token": 1.0 if (is_sol and creation > 0 and token_age_days < 1.0) else 0.0,
        "log_global_fees": math.log10(fees + 1.0),
        "low_global_fees": 1.0 if fees < 100 else 0.0,
        "days_since_last_trade": days_since_last_trade,
        "is_inactive": 1.0 if (is_sol and last_trade > 0 and days_since_last_trade > 30) else 0.0,
        "log_vol_1h": math.log10(v1h + 1.0),
        "log_vol_4h": math.log10((vol4 or 0.0) + 1.0),
        "log_vol_8h": math.log10(v8h + 1.0),
        "log_trade_1h": math.log10(t1h + 1.0),
        "log_trade_4h": math.log10(t4h + 1.0),
        "log_trade_8h": math.log10(t8h + 1.0),
        "vol_1h_to_4h": (v1h / 1.0) / ((vol4 or 0.0) / 4.0) if (vol4 or 0.0) > 0 else 0.0,
        "vol_4h_to_8h": ((vol4 or 0.0) / 4.0) / (v8h / 8.0) if v8h > 0 else 0.0,
        "vol_8h_to_24h": (v8h / 8.0) / (vol / 24.0) if vol > 0 else 0.0,
        "trade_1h_to_4h": (t1h / 1.0) / (t4h / 4.0) if t4h > 0 else 0.0,
        "trade_4h_to_8h": (t4h / 4.0) / (t8h / 8.0) if t8h > 0 else 0.0,
        "trade_8h_to_24h": (t8h / 8.0) / (tx / 24.0) if tx > 0 else 0.0,
        "vol_per_tx_1h": ratio(v1h, t1h),
        "vol_per_tx_4h": ratio((vol4 or 0.0), t4h),
        "vol_per_tx_8h": ratio(v8h, t8h),
        "log_vol_7d": math.log10(v7d + 1.0),
        "log_vol_30d": math.log10(v30d + 1.0),
        "log_trade_7d": math.log10(t7d + 1.0),
        "log_trade_30d": math.log10(t30d + 1.0),
        "vol_24h_to_7d": (vol / 24.0) / (v7d / (7.0 * 24.0)) if v7d > 0 else 0.0,
        "vol_7d_to_30d": (v7d / (7.0 * 24.0)) / (v30d / (30.0 * 24.0)) if v30d > 0 else 0.0,
        "trade_24h_to_7d": (tx / 24.0) / (t7d / (7.0 * 24.0)) if t7d > 0 else 0.0,
        "trade_7d_to_30d": (t7d / (7.0 * 24.0)) / (t30d / (30.0 * 24.0)) if t30d > 0 else 0.0,
        "top1_conc": 0.0 if top1 is None else top1,
        "top3_conc": 0.0 if top3 is None else top3,
        "top10_conc": 0.0 if top10 is None else top10,
        "top_missing": float(top_missing),
    }


def score_supervised(token: dict[str, Any], model_override: dict[str, Any] | None = None) -> dict[str, Any]:
    model = merge_mode_payload("supervised", model_override)
    features = build_supervised_features(token)
    feature_names = model.get("features") or []
    trees = model.get("trees") or []
    learning_rate = float(model.get("learning_rate", 0.1))
    init_raw = float(model.get("init_raw", 0.0))
    threshold = float(model.get("threshold", 0.9))

    raw_score = init_raw
    for tree in trees:
        node = 0
        left = tree["left"]
        while left[node] != -1:
            feat_name = feature_names[tree["feature"][node]]
            thresh = tree["threshold"][node]
            node = tree["left"][node] if features.get(feat_name, 0.0) <= thresh else tree["right"][node]
        raw_score += learning_rate * float(tree["value"][node])
    proba = 1.0 / (1.0 + math.exp(-raw_score))
    return {
        "mode": "supervised",
        "score": round(proba * 100.0, 1),
        "proba": round(proba, 6),
        "is_junk": proba >= threshold,
        "threshold": threshold * 100.0,
        "features": features,
    }


def build_shared_metrics(token: dict[str, Any]) -> dict[str, float | None]:
    valuation = _num(token.get("mcap_usd"))
    if valuation is None or valuation <= 0:
        valuation = _num(token.get("fdv_usd"))
    liq = _num(token.get("liquidity_usd"))
    vol = _num(token.get("vol_24h_usd"))
    holder = _num(token.get("holder_count"))
    top3 = _num(token.get("top3_pct"))

    log_liq = math.log10((liq or 0.0) + 1.0)
    log_vol = math.log10((vol or 0.0) + 1.0)
    val_liq_gap = None
    if valuation is not None and valuation > 0:
        val_liq_gap = math.log10(valuation) - log_liq
    liq_vol_gap = log_liq - log_vol
    vol_per_holder = None
    if holder is not None and holder > 0 and vol is not None:
        vol_per_holder = vol / holder
    return {
        "liquidity_usd": liq,
        "liquid_depth_log10": log_liq if liq is not None and liq > 0 else None,
        "val_liq_gap": val_liq_gap,
        "liq_vol_gap": liq_vol_gap,
        "vol_per_holder_usd": vol_per_holder,
        "top3_pct": top3,
    }


# ──────────────────────────────────────────────
# Supply-concentration pressure (internal)
#
# A continuous ramp over the top-holder supply share. Anchors are calibrated
# from the ALIVE cohort of new_solana.csv (tier: liq >= $1k, mcap/liq <= 10,
# volume_30d > 0): each ramp runs from the cohort median (p50) to p95, so a
# median-concentrated token contributes ~0 and a top-5%-concentrated token
# contributes ~1. Weights favour the single largest holder (rug authority),
# then the top-3 block, then the top-10 block.
#
# The breakdown is returned for internal tracing only — the skill surfaces the
# resulting junk score, never the formula behind it.
# ──────────────────────────────────────────────
_CONC_RAMPS: tuple[tuple[str, float, float, float], ...] = (
    ("top1_pct", 30.0, 97.0, 0.50),
    ("top3_pct", 45.0, 99.3, 0.30),
    ("top10_pct", 60.0, 99.9, 0.20),
)
# Maximum share of the remaining headroom (100 - score) the pressure can add.
_CONC_MAX_LIFT = 0.5


def _ramp(value: float | None, lo: float, hi: float) -> float:
    if value is None or hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


# ──────────────────────────────────────────────
# Function mode — tuned heuristic scorer
#
# A transparent, parameter-driven alternative to the ML models: additive
# weighted parts (ratio / liquidity / holders / volume / price / top-holder
# concentration) are summed, then mapped through a two-segment calibration
# (knee -> cap) so the display score stays on a 0..100 scale.
# ──────────────────────────────────────────────
def _calibrate_fn(raw_score: float) -> float:
    x = max(0.0, min(1.0, float(raw_score)))
    if x <= _CAL_KNEE_X:
        y = _CAL_KNEE_Y / _CAL_KNEE_X * x
    else:
        y = _CAL_KNEE_Y + (_CAL_CAP - _CAL_KNEE_Y) / (1.0 - _CAL_KNEE_X) * (x - _CAL_KNEE_X)
    return min(_CAL_CAP, max(0.0, y))


def score_function(token: dict[str, Any], params_override: dict[str, Any] | None = None) -> dict[str, Any]:
    p = merge_mode_payload("function", params_override)
    liquidity_usd = _num(token.get("liquidity_usd"))
    holder_count = _num(token.get("holder_count"))
    valuation = _num(token.get("mcap_usd"))
    if valuation is None or valuation <= 0:
        valuation = _num(token.get("fdv_usd"))
    if valuation is None or valuation <= 0:
        valuation = _num(token.get("valuation"), 0.0) or 0.0
    vol_24h_usd = _num(token.get("vol_24h_usd"), 0.0) or 0.0
    vol_30d_usd = _num(token.get("vol_30d_usd"))
    price_change_24h = _num(token.get("price_change_24h"))
    top1_pct = _num(token.get("top1_pct"))
    top3_pct = _num(token.get("top3_pct"))
    top10_pct = _num(token.get("top10_pct"))

    is_dead = vol_30d_usd is not None and vol_30d_usd == 0 and vol_24h_usd <= 0
    if is_dead:
        extreme = (
            liquidity_usd is not None and liquidity_usd > 0 and valuation > 0
            and (valuation / liquidity_usd) > p["hard_ratio_max"]
        )
        if extreme:
            is_dead = False

    alive_guard = (
        liquidity_usd is not None and liquidity_usd >= p["inactive_alive_liq_min"]
        and valuation is not None and valuation > 0
        and (valuation / liquidity_usd) <= p["inactive_alive_ratio_max"]
    )

    parts: dict[str, Any] = {}
    score = 0.0
    band_strict = False
    if is_dead:
        raw_score = 0.0
        parts = {"dead": "no_30d_volume"}
    elif liquidity_usd is not None and liquidity_usd < p["hard_liq_max"]:
        raw_score = 1.0
        parts = {"hard": f"liq<{p['hard_liq_max']}"}
    elif holder_count is not None and holder_count <= p["hard_holder_max"]:
        raw_score = 1.0
        parts = {"hard": f"holder<={p['hard_holder_max']}"}
    else:
        if liquidity_usd is not None and liquidity_usd > 0 and valuation > 0:
            ratio = valuation / liquidity_usd
            if ratio > p["hard_ratio_max"]:
                if vol_24h_usd >= p["soft_ratio_vol_min"] and holder_count is not None and holder_count >= p["soft_ratio_holder_min"]:
                    band_strict = p["band_liq_lo"] <= liquidity_usd < p["band_liq_hi"]
                else:
                    raw_score = 1.0
                    function_score = _calibrate_fn(raw_score)
                    return {
                        "mode": "function",
                        "score": round(function_score * 100.0, 1),
                        "raw_score": round(raw_score * 100.0, 1),
                        "is_junk": function_score >= p["function_threshold"],
                        "threshold": p["function_threshold"] * 100.0,
                        "parts": {"hard": "extreme_ratio"},
                        "healthy_guard": False,
                        "alive_guard": alive_guard,
                        "is_dead": False,
                        "suspicious": False,
                    }
            limit = min(p["hard_ratio_max"], max(1.0, liquidity_usd / p["ratio_ref"]) ** p["ratio_slope"])
            relief = 0.5 * _ramp(math.log10(max(vol_24h_usd, 0.0) + 1.0),
                                 math.log10(p["soft_ratio_vol_min"] + 1.0),
                                 math.log10(p["relief_vol_hi"] + 1.0))
            if holder_count is not None:
                relief += 0.5 * _ramp(math.log10(max(holder_count, 0.0) + 1.0),
                                      math.log10(p["soft_ratio_holder_min"] + 1.0),
                                      math.log10(p["relief_holder_hi"] + 1.0))
            sev = _ramp(math.log10(ratio), math.log10(limit), math.log10(limit * p["ratio_span"]))
            parts["ratio"] = p["w_ratio"] * sev * (1.0 - p["relief_max"] * relief)
            score += parts["ratio"]
        if liquidity_usd is not None:
            parts["liq"] = p["w_liq"] * (1.0 - _ramp(math.log10(max(liquidity_usd, 0.0) + 1.0),
                                                    math.log10(p["ramp_liq_lo"] + 1.0),
                                                    math.log10(p["ramp_liq_hi"] + 1.0)))
            score += parts["liq"]
        if holder_count is not None:
            holder_hi = p["band_ramp_holder_hi"] if band_strict else p["ramp_holder_hi"]
            parts["holder"] = p["w_holder"] * (1.0 - _ramp(math.log10(max(holder_count, 0.0) + 1.0),
                                                          math.log10(p["ramp_holder_lo"] + 1.0),
                                                          math.log10(holder_hi + 1.0)))
            score += parts["holder"]
        vol_hi = p["band_ramp_vol_hi"] if band_strict else p["ramp_vol_hi"]
        parts["vol"] = p["w_vol"] * (1.0 - _ramp(math.log10(max(vol_24h_usd, 0.0) + 1.0),
                                                 math.log10(p["ramp_vol_lo"] + 1.0),
                                                 math.log10(vol_hi + 1.0)))
        score += parts["vol"]

        if price_change_24h is not None:
            drop = -price_change_24h
            if drop <= p["price_drop_lo"]:
                price_sev = 0.0
            elif drop <= p["price_drop_knee"]:
                price_sev = p["price_light"] * _ramp(drop, p["price_drop_lo"], p["price_drop_knee"])
            elif drop >= p["price_drop_hi"]:
                price_sev = 1.0
            else:
                price_sev = p["price_light"] + (1.0 - p["price_light"]) * _ramp(drop, p["price_drop_knee"], p["price_drop_hi"])
        else:
            price_sev = 0.0
        parts["price"] = p["w_price"] * price_sev
        score += parts["price"]

        if top1_pct is not None:
            parts["top1"] = p["w_top1"] * _ramp(top1_pct, p["top1_lo"], p["top1_hi"])
            score += parts["top1"]
        if top3_pct is not None:
            parts["top3"] = p["w_top3"] * _ramp(top3_pct, p["top3_lo"], p["top3_hi"])
            score += parts["top3"]
        if top10_pct is not None:
            parts["top10"] = p["w_top10"] * _ramp(top10_pct, p["top10_lo"], p["top10_hi"])
            score += parts["top10"]
        raw_score = min(score, 1.0)

    function_score = _calibrate_fn(raw_score)
    healthy_guard = (
        liquidity_usd is not None and liquidity_usd >= p["guard_liq"]
        and vol_24h_usd is not None and vol_24h_usd >= p["guard_vol"]
        and holder_count is not None and holder_count >= p["guard_holder"]
    )
    price_suspicious = (
        liquidity_usd is not None and liquidity_usd < p["risk_liq_max"]
        and price_change_24h is not None and price_change_24h <= p["risk_price_drop"]
    )
    holding_suspicious = (
        (top1_pct is not None and top1_pct >= p["susp_top1"])
        or (top10_pct is not None and top10_pct > p["susp_top10"])
    )
    is_junk = False if healthy_guard else (function_score >= p["function_threshold"])
    suspicious = (price_suspicious or holding_suspicious) and (not is_junk)
    display_score = max(function_score, p["risk_floor"]) if suspicious else function_score
    if vol_24h_usd < p["tiny_vol_max"] and holder_count is not None and holder_count < p["tiny_holder_max"]:
        display_score = max(display_score, p["tiny_base_floor"])
    return {
        "mode": "function",
        "score": round(display_score * 100.0, 1),
        "raw_score": round(raw_score * 100.0, 1),
        "is_junk": is_junk,
        "threshold": p["function_threshold"] * 100.0,
        "parts": {k: round(v, 6) if isinstance(v, (int, float)) else v for k, v in parts.items()},
        "healthy_guard": healthy_guard,
        "alive_guard": alive_guard,
        "is_dead": is_dead,
        "suspicious": suspicious,
        "price_suspicious": price_suspicious,
        "holding_suspicious": holding_suspicious,
    }


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def concentration_pressure(token: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Continuous 0..1 supply-concentration pressure + internal breakdown."""
    num = 0.0
    den = 0.0
    detail: dict[str, Any] = {}
    for key, lo, hi, weight in _CONC_RAMPS:
        value = _num(token.get(key))
        if value is None:
            continue
        r = _smoothstep(_ramp(value, lo, hi))
        num += weight * r
        den += weight
        detail[key] = {"value": round(value, 4), "ramp": round(r, 4)}
    if den <= 0:
        return 0.0, {"index": None, "detail": {}}
    return num / den, {"index": round(num / den, 4), "detail": detail}


def _apply_shared_adjustments(result: dict[str, Any], token: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    shared_metrics = build_shared_metrics(token)
    score = float(out.get("score", 0.0) or 0.0)
    floor_reason = None
    liq_vol_gap = shared_metrics.get("liq_vol_gap")
    if liq_vol_gap is not None and liq_vol_gap > 4.0 and score < 30.0:
        score = 30.0
        floor_reason = "liq_vol_gap>4 => min risk 30/100"
    pressure, conc_detail = concentration_pressure(token)
    if pressure > 0.0:
        score += (100.0 - score) * _CONC_MAX_LIFT * pressure
    threshold = float(out.get("threshold", 0.0) or 0.0)
    out["score"] = round(max(0.0, min(100.0, score)), 1)
    if threshold > 0.0:
        out["is_junk"] = out["score"] >= threshold
    out["shared_metrics"] = shared_metrics
    out["min_risk_floor_reason"] = floor_reason
    out["min_risk_floor_applied"] = floor_reason is not None
    out["concentration_pressure"] = conc_detail
    return out


def score_token(token: dict[str, Any], mode: str = "unsupervised",
                params_override: dict[str, Any] | None = None) -> dict[str, Any]:
    mode = normalize_mode(mode)
    if mode == "function":
        return _apply_shared_adjustments(score_function(token, params_override), token)
    if mode == "supervised":
        return _apply_shared_adjustments(score_supervised(token, params_override), token)
    pred = _lr.predict(
        mcap=token.get("mcap_usd"),
        fdv=token.get("fdv_usd"),
        liquidity=token.get("liquidity_usd"),
        vol_24h=token.get("vol_24h_usd"),
        tx_24h=token.get("tx_24h"),
        trader_24h=token.get("trader_24h"),
        threshold=float((params_override or {}).get("threshold", _lr._get_model().get("threshold", 95.0))),
    )
    return _apply_shared_adjustments({
        "mode": "unsupervised",
        "score": pred["score"],
        "proba": pred["proba"],
        "is_junk": pred["is_junk"],
        "threshold": float(pred["threshold"]),
        "features": pred["features"],
    }, token)
