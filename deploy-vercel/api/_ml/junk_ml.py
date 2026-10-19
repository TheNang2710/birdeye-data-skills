"""Junk Token ML Classifier — trained model from junk_token_ML.ipynb.

Model: Logistic Regression (16 features, standardized).
Trained on confirmed-junk samples vs healthy/borderline tokens.
Learned: MCAP cao + liquidity thấp → high junk probability.

Usage:
    from modules import junk_ml
    pred = junk_ml.predict(mcap=..., fdv=..., liquidity=...,
                           vol_24h=..., tx_24h=..., trader_24h=...)
    # pred = {"score": 0-100, "is_junk": bool, "features": {...}}
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

# Path to the trained model params.
# The secure runtime lives in api/_ml/, so the model usually sits right next
# to this module; the remaining candidates cover the bundled CLI (api/_cli/)
# and the birdeye-screener workspace layout.
_MODULE_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _MODULE_DIR.parent.parent  # birdeye-screener/
_MODEL_CANDIDATES = [
    _MODULE_DIR / "lr_params.json",
    _SKILL_ROOT / "lr_params.json",
    _SKILL_ROOT / "test" / "valuation" / "lr_params.json",
    # Original training notebook location
    Path(__file__).resolve().parents[5] / "test" / "valuation" / "lr_params.json",
    Path.cwd() / "lr_params.json",
]


def _load_model() -> dict[str, Any]:
    """Load the trained Logistic Regression parameters (mean, std, coef, intercept)."""
    for p in _MODEL_CANDIDATES:
        if p.exists():
            return json.loads(p.read_text())
    raise FileNotFoundError(
        f"lr_params.json not found. Searched: {[str(p) for p in _MODEL_CANDIDATES]}"
    )


_MODEL: dict[str, Any] | None = None


def _get_model() -> dict[str, Any]:
    global _MODEL
    if _MODEL is None:
        _MODEL = _load_model()
    return _MODEL


def _to_float(v: Any) -> float | None:
    if v is None or v == "" or v == "\\N":
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def engineer_features(mcap: float | None, fdv: float | None,
                      liquidity: float | None, vol_24h: float | None,
                      tx_24h: float | None, trader_24h: float | None) -> dict[str, float]:
    """Build the 16 features used by the LR model (same as notebook)."""
    val = _to_float(mcap)
    if val is None or val <= 0:
        val = _to_float(fdv) or 0.0
    liq = _to_float(liquidity) or 0.0
    vol = _to_float(vol_24h) or 0.0
    tx = _to_float(tx_24h) or 0.0
    tr = _to_float(trader_24h) or 0.0

    # log transforms (safe, never -inf)
    log_val = math.log10(val) if val > 0 else 0.0
    log_liq = math.log10(liq + 1)
    log_vol = math.log10(vol + 1)
    log_tx = math.log10(tx + 1)
    log_trader = math.log10(tr + 1)

    # KEY gaps
    val_liq_gap = log_val - log_liq
    val_vol_gap = log_val - log_vol
    liq_vol_gap = log_liq - log_vol

    # ratios
    liq_to_val = liq / val if val > 0 else 0.0
    vol_to_val = vol / val if val > 0 else 0.0
    vol_to_liq = vol / liq if liq > 0 else 0.0
    vol_per_tx = vol / tx if tx > 0 else 0.0

    return {
        "log_val": log_val,
        "log_liq": log_liq,
        "log_vol": log_vol,
        "log_tx": log_tx,
        "log_trader": log_trader,
        "val_liq_gap": val_liq_gap,
        "val_vol_gap": val_vol_gap,
        "liq_vol_gap": liq_vol_gap,
        "liq_to_val": liq_to_val,
        "vol_to_val": vol_to_val,
        "vol_to_liq": vol_to_liq,
        "vol_per_tx": vol_per_tx,
        "has_val": 1.0 if val > 0 else 0.0,
        "has_liq": 1.0 if liq > 0 else 0.0,
        "has_vol": 1.0 if vol > 0 else 0.0,
        "is_dead": 1.0 if (vol == 0 and tx == 0 and tr == 0) else 0.0,
    }


def predict(mcap: float | None = None, fdv: float | None = None,
            liquidity: float | None = None, vol_24h: float | None = None,
            tx_24h: float | None = None, trader_24h: float | None = None,
            threshold: float | None = None) -> dict[str, Any]:
    """Predict junk probability score (0-100) and junk verdict.

    Args:
        mcap: market cap USD (preferred valuation)
        fdv: fully diluted valuation USD (fallback if mcap missing)
        liquidity: liquidity USD
        vol_24h: 24h volume USD
        tx_24h: 24h transaction count (buy + sell)
        trader_24h: 24h unique wallet count
        threshold: score >= threshold → is_junk=True. If None, uses the
            threshold baked into the model params file (lr_params.json),
            which is learned during training.

    Returns:
        {"score": float 0-100, "is_junk": bool, "features": dict, "threshold": float}
    """
    model = _get_model()
    features_list = model["features"]
    mean = model["mean"]
    std = model["std"]
    coef = model["coef"]
    intercept = model["intercept"]
    # Threshold is decided by the model (learned in training), not by the caller.
    if threshold is None:
        threshold = float(model.get("threshold", 95.0))

    feats = engineer_features(mcap, fdv, liquidity, vol_24h, tx_24h, trader_24h)

    # Standardize and compute logit
    z = intercept
    for i, fname in enumerate(features_list):
        raw = feats.get(fname, 0.0)
        s = std[i] if std[i] != 0 else 1.0
        x_std = (raw - mean[i]) / s
        z += coef[i] * x_std

    # Sigmoid → probability
    proba = 1.0 / (1.0 + math.exp(-z))
    score = round(proba * 100.0, 1)
    is_junk = score >= threshold

    return {
        "score": score,
        "is_junk": is_junk,
        "proba": round(proba, 6),
        "features": {k: round(v, 4) for k, v in feats.items()},
        "threshold": threshold,
    }


def predict_from_overview(ovd: dict, threshold: float | None = None) -> dict[str, Any]:
    """Predict directly from a Birdeye token_overview data dict.

    Extracts: marketCap, fdv, liquidity, v24hUSD, buy24h+sell24h, uniqueWallet24h.
    """
    mcap = _to_float(ovd.get("marketCap"))
    fdv = _to_float(ovd.get("fdv"))
    liquidity = _to_float(ovd.get("liquidity"))
    vol_24h = _to_float(ovd.get("v24hUSD"))
    buy24 = _to_float(ovd.get("buy24h")) or 0.0
    sell24 = _to_float(ovd.get("sell24h")) or 0.0
    tx_24h = buy24 + sell24 if (buy24 or sell24) else None
    trader_24h = _to_float(ovd.get("uniqueWallet24h"))

    return predict(mcap=mcap, fdv=fdv, liquidity=liquidity,
                   vol_24h=vol_24h, tx_24h=tx_24h, trader_24h=trader_24h,
                   threshold=threshold)
