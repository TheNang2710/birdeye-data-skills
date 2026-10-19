"""
Token Trending Score — momentum-based computation module.

Computes a 0..100 trending score for a token across intervals:
  5m, 15m, 30m, 1h, 4h, 6h, 12h, 24h

Six weighted components (tunable for later ML tuning):
  1. Volume Growth    (20%) — statistical momentum of per-candle volume series
  2. Swap Activity    (15%) — trade count growth (overview) or volume proxy
  3. Price Momentum   (20%) — linear regression slope of log(close) over window
  4. Liquidity Health (15%) — liquidity/mcap ratio + stability
  5. Holder Dynamics  (15%) — holder count momentum (chart) + health (profile)
  6. Security         (15%) — contract risk penalties (hard floor if honeypot)

Statistical Momentum Score (core formula for Volume, Price, Holders):
  Uses ALL data points in the window via linear regression of log(value) on time:
    slope  → trend direction & magnitude (log-return over the window)
    R²     → trend QUALITY (penalizes single-bar spikes / noise)
    combined = (0.7·trend_return + 0.3·actual_return) × (0.5 + 0.5·R²)
    score = 50 + 50·tanh(combined / scale)
  Sustained growth over time → high score; flat → ~50; decline → low.

For short intervals (5m, 15m, 30m): 1-second OHLCV candles.
For 1h+ intervals: 1m OHLCV candles (or overview fields as fallback).
Holder growth from /token/v1/holder/chart (1m resolution).
Holder health from /token/v1/holder-profile (cohort analysis).
"""
from __future__ import annotations

import math
from statistics import mean, median
from typing import Any

# Default component weights (tunable — for ML tuning later)
DEFAULT_WEIGHTS = {
    "volume": 0.20,
    "swaps": 0.15,
    "price": 0.20,
    "liquidity": 0.15,
    "holder": 0.15,
    "security": 0.15,
}

# Final interval set (GMGN-inspired, adjusted for data availability)
# 5m, 15m, 30m use 1s candles for price/volume; 1h+ use overview or 1m candles
INTERVALS = ["5m", "15m", "30m", "1h", "4h", "6h", "12h", "24h"]
INTERVAL_MINUTES = {
    "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "6h": 360, "12h": 720, "24h": 1440,
}

# Birdeye overview supports: 1m, 5m, 1h, 2h, 4h, 8h, 24h
# Intervals directly available in token_overview:
OVERVIEW_INTERVALS = {"5m", "1h", "4h", "24h"}
# Intervals that must be computed from candles:
CANDLE_INTERVALS = {"15m", "30m", "6h", "12h"}

# Short intervals using 1-second candles for price/volume:
SHORT_CANDLE_INTERVALS = {"5m", "15m", "30m"}

# Snapshot baseline windows per interval
BASELINE_WINDOW_SECONDS = {
    "5m": 4 * 3600,    # last 4h of snapshots
    "15m": 6 * 3600,     # last 6h
    "30m": 12 * 3600,     # last 12h
    "1h": 24 * 3600,      # last 24h
    "4h": 72 * 3600,       # last 72h
    "6h": 7 * 86400,     # last 7d
    "12h": 14 * 86400,     # last 14d
    "24h": 30 * 86400,    # last 30d
}
MIN_BASELINE_SAMPLES = 3  # need at least this many samples for median

EPS = 1e-8


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _to_float(v) -> float | None:
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _pct_change(cur: float, prev: float) -> float:
    if not prev:
        return 0.0 if not cur else (100.0 if cur > 0 else -100.0)
    return (cur - prev) / abs(prev) * 100.0


# ──────────────────────────────────────────────
# Growth Score (core formula)
# ──────────────────────────────────────────────
def growth_score(current: float, baseline: float, eps: float = EPS) -> float:
    """Growth Score: min(100, 100 * ln(1 + G) / ln(16))

    G = (current + eps) / (baseline + eps)
    Maps: G=1 (no change) → ~33.3, G=2 → ~50, G=4 → ~66.7, G=8 → ~83.3, G=15 → 100
    """
    if current is None or baseline is None:
        return 50.0
    g = (current + eps) / (baseline + eps)
    if g <= 0:
        return 0.0
    score = 100.0 * math.log(1.0 + g) / math.log(16.0)
    return _clamp(score)


def growth_score_from_pct(change_pct: float) -> float:
    """Convert a percent change to a growth-style score.

    Maps: +0% → 33, +100% → 50, +300% → 67, +700% → 83, +1500% → 100
           -50% → ~20, -100% → 0
    """
    if change_pct is None:
        return 50.0
    g = 1.0 + change_pct / 100.0
    if g <= 0:
        return 0.0
    score = 100.0 * math.log(1.0 + g) / math.log(16.0)
    return _clamp(score)


# ──────────────────────────────────────────────
# Statistical Momentum Score (full time-series)
# ──────────────────────────────────────────────
def momentum_score_from_series(
    values: list[float],
    timestamps: list[int] | None = None,
    scale: float = 50.0,
) -> tuple[float, dict]:
    """Compute a momentum score 0..100 from a FULL time series.

    Statistically sound approach using ALL data points:
      1. Linear regression of log(value) on time → slope (trend direction & magnitude)
      2. R² of the fit → trend QUALITY (penalizes spikes / noise / single-bar pumps)
      3. Actual total return over the window → magnitude confirmation

    Combined signal = (0.7·trend_return + 0.3·actual_return) × (0.5 + 0.5·R²)
    Score = 50 + 50·tanh(combined / scale)

    Properties:
      - Sustained growth over time (high slope, high R²) → score → 100
      - Sustained decline → score → 0
      - Flat / no trend → score ≈ 50
      - A single spike (low R²) is discounted → stays near 50
    """
    bd: dict[str, Any] = {}
    n = len(values)
    bd["n_points"] = n

    if n < 3:
        bd["score_reason"] = "insufficient_data"
        return 50.0, bd

    # Build (x, y) pairs with valid positive values
    if timestamps is None:
        xs_raw = list(range(n))
    else:
        xs_raw = timestamps
    pairs = [(x, v) for x, v in zip(xs_raw, values)
             if v is not None and v > 0 and not math.isinf(v)]
    if len(pairs) < 3:
        bd["score_reason"] = "insufficient_valid"
        return 50.0, bd

    xs = [p[0] for p in pairs]
    vs = [p[1] for p in pairs]
    ys = [math.log(v) for v in vs]
    m = len(xs)

    # Normalize x to [0, 1] so slope is comparable across windows
    x_min, x_max = min(xs), max(xs)
    x_span = x_max - x_min if x_max > x_min else 1.0
    xn = [(x - x_min) / x_span for x in xs]

    # Linear regression: y = a + b·xn
    sum_x = sum(xn)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xn, ys))
    sum_x2 = sum(x * x for x in xn)
    denom = m * sum_x2 - sum_x * sum_x
    if abs(denom) < 1e-15:
        bd["score_reason"] = "zero_variance"
        return 50.0, bd

    slope = (m * sum_xy - sum_x * sum_y) / denom       # log-return per normalized unit
    intercept = (sum_y - slope * sum_x) / m

    # R² — coefficient of determination (trend quality)
    y_mean = sum_y / m
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xn, ys))
    r2 = max(0.0, 1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Trend-line return over the full window (%, in log space converted)
    trend_log_return = slope  # since xn ∈ [0,1], slope = log(v_end/v_start) of trend
    trend_return_pct = (math.exp(trend_log_return) - 1.0) * 100.0

    # Actual total return (first → last)
    actual_return_pct = (vs[-1] - vs[0]) / vs[0] * 100.0

    # Combined: 70% trend (regression), 30% actual return, weighted by R² quality
    combined = (trend_return_pct * 0.7 + actual_return_pct * 0.3) * (0.5 + 0.5 * r2)

    score = 50.0 + 50.0 * math.tanh(combined / scale)
    score = _clamp(score)

    bd.update({
        "n_valid": m,
        "slope_log": round(slope, 6),
        "r2": round(r2, 4),
        "trend_return_pct": round(trend_return_pct, 2),
        "actual_return_pct": round(actual_return_pct, 2),
        "combined": round(combined, 2),
    })
    return round(score, 1), bd


# ──────────────────────────────────────────────
# Candle-based helpers (for non-overview intervals)
# ──────────────────────────────────────────────
def _candle_window(candles: list[dict], window_minutes: int,
                    now_ts: int) -> list[dict]:
    """Return candles within [now_ts - window_minutes*60, now_ts]."""
    if not candles:
        return []
    cutoff = now_ts - window_minutes * 60
    return [c for c in candles
            if cutoff <= int(c.get("t") or 0) <= now_ts + 60]


def price_change_from_candles(candles: list[dict], window_minutes: int,
                          now_ts: int) -> float | None:
    """Compute price change % over window from candles.

    Uses first close in window as start, last close as end.
    """
    series = _candle_window(candles, window_minutes, now_ts)
    if len(series) < 2:
        return None
    start_close = _to_float(series[0].get("c") or series[0].get("close"))
    end_close = _to_float(series[-1].get("c") or series[-1].get("close"))
    if start_close is None or end_close is None or start_close <= 0:
        return None
    return (end_close - start_close) / start_close * 100.0


def volume_from_candles(candles: list[dict], window_minutes: int,
                       now_ts: int) -> float | None:
    """Sum volume_usd over window from candles."""
    series = _candle_window(candles, window_minutes, now_ts)
    if not series:
        return None
    total = 0.0
    for c in series:
        v = _to_float(c.get("v_usd") or c.get("volumeUsd") or c.get("volume_usd"))
        if v is not None:
            total += v
    return total if total > 0 else None


# ──────────────────────────────────────────────
# Baseline extraction from snapshots
# ──────────────────────────────────────────────
def _field_for_interval(iv: str, prefix: str) -> str:
    """Build field name like v5mUSD, trade1h, uniqueWallet24h."""
    return f"{prefix}{iv}"


def extract_baseline(snapshots: list[dict], field: str, now_ts: int,
                     window_seconds: int) -> float | None:
    """Extract median value of `field` from snapshots within window_seconds.

    Returns None if fewer than MIN_BASELINE_SAMPLES valid samples.
    """
    if not snapshots:
        return None
    cutoff = now_ts - window_seconds
    values = []
    for snap in snapshots:
        ts_raw = snap.get("timestamp") or snap.get("t") or 0
        try:
            ts = int(ts_raw)
        except (TypeError, ValueError):
            continue
        if not ts or ts < cutoff or ts > now_ts + 60:
            continue
        val = _to_float(snap.get(field))
        if val is not None and val > 0:
            values.append(val)
    if len(values) < MIN_BASELINE_SAMPLES:
        return None
    return median(values)


def get_current_and_baseline(ovd: dict, snapshots: list[dict],
                             field: str, hist_field: str, now_ts: int,
                             window_seconds: int) -> tuple[float | None, float | None, str]:
    """Get current value and baseline for a field.

    Returns (current, baseline, source) where source is 'median' or 'history'.
    """
    current = _to_float(ovd.get(field))
    baseline = extract_baseline(snapshots, field, now_ts, window_seconds)
    if baseline is not None:
        return current, baseline, "median"
    hist = _to_float(ovd.get(hist_field))
    if hist is not None and hist > 0:
        return current, hist, "history"
    return current, None, "none"


# ──────────────────────────────────────────────
# Component 1: Volume Growth (20%)
# ──────────────────────────────────────────────
def volume_growth_score(ovd: dict, snapshots: list[dict], interval: str,
                        now_ts: int, candles: list[dict] | None = None) -> tuple[float, dict]:
    """Score volume growth 0..100 using statistical momentum on the full candle series.

    For intervals with candle data: run linear regression on per-candle volume
    over the window — sustained growth (high slope + high R²) scores high.
    For overview intervals (5m, 1h, 4h, 24h): prefer candle series if available,
    else fall back to v{iv}USD vs History field.
    """
    bd: dict[str, Any] = {}
    window = BASELINE_WINDOW_SECONDS[interval]
    iv_minutes = INTERVAL_MINUTES[interval]

    # Prefer full candle-series momentum when candles are available
    use_candles = bool(candles)
    if use_candles:
        series = _candle_window(candles or [], iv_minutes, now_ts)
        vols = [_to_float(c.get("v_usd") or c.get("volumeUsd") or c.get("volume_usd"))
                for c in series]
        ts = [int(c.get("t") or c.get("unix_time") or 0) for c in series]
        # Filter valid
        valid = [(t, v) for t, v in zip(ts, vols) if v is not None and v > 0]
        if len(valid) >= 3:
            vol_ts = [v[0] for v in valid]
            vol_vals = [v[1] for v in valid]
            score, mom_bd = momentum_score_from_series(vol_vals, vol_ts, scale=50.0)
            bd.update(mom_bd)
            bd["source"] = "candles_momentum"
            bd["volume_current"] = round(sum(vol_vals), 2)
            bd["volume_baseline"] = None
            return round(_clamp(score), 1), bd
        # Not enough valid candles — fall through to overview
        use_candles = False

    if interval in OVERVIEW_INTERVALS:
        field = _field_for_interval(interval, "v") + "USD"
        hist_field = "vHistory" + interval + "USD"
        cur, base, src = get_current_and_baseline(ovd, snapshots, field, hist_field,
                                                  now_ts, window)
        bd["source"] = "overview"
        bd["volume_current"] = round(cur, 2) if cur is not None else None
        bd["volume_baseline"] = round(base, 2) if base is not None else None
        bd["baseline_source"] = src
        if cur is None or base is None:
            bd["volume_g"] = None
            return 50.0, bd
        g = (cur + EPS) / (base + EPS)
        bd["volume_g"] = round(g, 4)
        score = growth_score(cur, base)
        return round(_clamp(score), 1), bd

    # Candle interval but no valid candles — use snapshot estimate as last resort
    bd["source"] = "no_data"
    bd["volume_current"] = None
    bd["volume_baseline"] = None
    bd["baseline_source"] = "none"
    return 50.0, bd


# ──────────────────────────────────────────────
# Component 2: Swap Activity (15%)
# ──────────────────────────────────────────────
def swaps_growth_score(ovd: dict, snapshots: list[dict], interval: str,
                       now_ts: int, vol_score: float = 50.0) -> tuple[float, dict]:
    """Score swap/trade count growth 0..100.

    For overview intervals: use trade{iv}.
    For candle intervals: fall back to volume score as proxy (candles lack trade count).
    """
    bd: dict[str, Any] = {}

    if interval in OVERVIEW_INTERVALS:
        field = _field_for_interval(interval, "trade")
        hist_field = "tradeHistory" + interval
        window = BASELINE_WINDOW_SECONDS[interval]
        cur, base, src = get_current_and_baseline(ovd, snapshots, field, hist_field,
                                                  now_ts, window)
        bd["swaps_current"] = int(cur) if cur is not None else None
        bd["swaps_baseline"] = int(base) if base is not None else None
        bd["baseline_source"] = src
        bd["source"] = "overview"

        if cur is None or base is None:
            bd["swaps_g"] = None
            return 50.0, bd

        g = (cur + EPS) / (base + EPS)
        bd["swaps_g"] = round(g, 4)
        score = growth_score(cur, base)
        return round(_clamp(score), 1), bd
    else:
        # Candles don't have trade count; use volume score as proxy
        bd["swaps_current"] = None
        bd["swaps_baseline"] = None
        bd["baseline_source"] = "volume_proxy"
        bd["source"] = "volume_proxy"
        bd["swaps_g"] = None
        return round(vol_score, 1), bd


# ──────────────────────────────────────────────
# Component 3: Price Momentum (20%)
# ──────────────────────────────────────────────
def price_momentum_score(ovd: dict, interval: str, now_ts: int,
                        candles_1s: list[dict] | None = None,
                        candles_1m: list[dict] | None = None) -> tuple[float, dict]:
    """Score price momentum 0..100 using full candle series regression.

    For intervals with candle data: linear regression of log(close) on time
    over the window. Sustained uptrend (high slope + high R²) → high score.
    Falls back to overview priceChange{iv}Percent when candles unavailable.
    """
    bd: dict[str, Any] = {}
    iv_minutes = INTERVAL_MINUTES[interval]

    # Choose candle source
    if interval in SHORT_CANDLE_INTERVALS:
        candles = candles_1s or []
        candle_src = "candles_1s"
    else:
        candles = candles_1m or []
        candle_src = "candles_1m"

    if candles:
        series = _candle_window(candles, iv_minutes, now_ts)
        closes = [_to_float(c.get("c") or c.get("close")) for c in series]
        ts = [int(c.get("t") or c.get("unix_time") or 0) for c in series]
        valid = [(t, v) for t, v in zip(ts, closes) if v is not None and v > 0]
        if len(valid) >= 3:
            p_ts = [v[0] for v in valid]
            p_vals = [v[1] for v in valid]
            score, mom_bd = momentum_score_from_series(p_vals, p_ts, scale=30.0)
            bd.update(mom_bd)
            bd["source"] = candle_src + "_momentum"
            return round(_clamp(score), 1), bd

    # Fallback: overview priceChange field (single-point, no R²)
    field = f"priceChange{interval}Percent"
    change = _to_float(ovd.get(field))
    bd["source"] = "overview"
    bd["price_change_pct"] = round(change, 2) if change is not None else None
    if change is None:
        # Last resort: 1m candles (may not cover the full window)
        change = price_change_from_candles(candles_1m or [], iv_minutes, now_ts)
        bd["source"] = "candles_1m"
        bd["price_change_pct"] = round(change, 2) if change is not None else None
    if change is None:
        return 50.0, bd
    score = growth_score_from_pct(change)
    return round(_clamp(score), 1), bd


# ──────────────────────────────────────────────
# Component 4: Liquidity Health (15%)
# ──────────────────────────────────────────────
def liquidity_health_score(liquidity: float | None, mcap: float | None,
                           liq_1m: list[dict] | None = None,
                           now_ts: int = 0) -> tuple[float, dict]:
    """Score liquidity health 0..100.

    Factors:
      - liq_mcap_ratio: liquidity / market_cap (higher = deeper)
      - liq_stability: inverse of recent drawdown (if liq history available)
    """
    bd: dict[str, Any] = {}

    # 1) Liquidity / Market Cap ratio — weight 70%
    if liquidity is not None and mcap and mcap > 0:
        ratio = liquidity / mcap
        bd["liq_mcap_ratio"] = round(ratio, 6)
        if ratio >= 0.10:
            ratio_score = 100.0
        elif ratio >= 0.05:
            ratio_score = 70.0 + (ratio - 0.05) / 0.05 * 30.0
        elif ratio >= 0.02:
            ratio_score = 40.0 + (ratio - 0.02) / 0.03 * 30.0
        else:
            ratio_score = ratio / 0.02 * 40.0
        ratio_score = _clamp(ratio_score)
    else:
        ratio_score = 50.0
        bd["liq_mcap_ratio"] = None

    # 2) Liquidity stability — weight 30%
    if liq_1m and len(liq_1m) >= 5 and now_ts:
        lookback = now_ts - 3600
        series = []
        for e in liq_1m:
            t = int(e.get("t") or 0)
            if lookback <= t <= now_ts:
                v = _to_float(e.get("liq"))
                if v is not None and v > 0:
                    series.append(v)
        if len(series) >= 3:
            peak = max(series)
            trough = min(series)
            dd = (peak - trough) / peak * 100.0 if peak > 0 else 0.0
            bd["liq_drawdown_1h_pct"] = round(dd, 2)
            stability_score = _clamp(100.0 - dd * 2.0)
        else:
            stability_score = 50.0
            bd["liq_drawdown_1h_pct"] = None
    else:
        stability_score = 50.0
        bd["liq_drawdown_1h_pct"] = None

    score = ratio_score * 0.70 + stability_score * 0.30
    bd["subscores"] = {"ratio": round(ratio_score, 1),
                       "stability": round(stability_score, 1)}
    return round(_clamp(score), 1), bd


# ──────────────────────────────────────────────
# Component 5: Holder Dynamics (15%)
# ──────────────────────────────────────────────
def holder_growth_from_chart(holder_chart: list[dict], window_minutes: int,
                            now_ts: int) -> tuple[float | None, dict]:
    """Compute holder growth score from the FULL holder chart series.

    Uses linear regression on holder count over the window — sustained growth
    (positive slope + high R²) scores high. A single spike is discounted.
    Returns (score, breakdown).
    """
    bd: dict[str, Any] = {}
    if not holder_chart:
        bd["source"] = "none"
        return None, bd
    cutoff = now_ts - window_minutes * 60
    pts = [p for p in holder_chart
           if cutoff <= int(p.get("timestamp") or 0) <= now_ts + 120]
    if len(pts) < 3:
        bd["source"] = "insufficient"
        bd["n_points"] = len(pts)
        return None, bd

    holders = [_to_float(p.get("holder")) for p in pts]
    ts = [int(p.get("timestamp") or 0) for p in pts]
    valid = [(t, v) for t, v in zip(ts, holders) if v is not None and v > 0]
    if len(valid) < 3:
        bd["source"] = "insufficient_valid"
        return None, bd

    h_ts = [v[0] for v in valid]
    h_vals = [v[1] for v in valid]
    score, mom_bd = momentum_score_from_series(h_vals, h_ts, scale=20.0)
    bd.update(mom_bd)
    bd["source"] = "holder_chart_momentum"
    return round(score, 1), bd


def holder_health_from_profile(holder_profile: dict | None) -> tuple[float, dict]:
    """Score holder health 0..100 from holder profile cohort analysis.

    Parses structured tags array: [{tag, holder_count, percent_of_supply, ...}].
    Penalizes risky cohorts (bundler, sniper, insider, dev) by their supply share.
    Rewards quality cohorts (smart_trader, kol).
    """
    bd: dict[str, Any] = {}
    if not holder_profile:
        return 50.0, {"source": "none"}

    hp = holder_profile
    score = 50.0
    penalties: list[dict] = []
    bonuses: list[dict] = []

    tags = hp.get("tags") or hp.get("holderTags") or []
    # Build tag lookup: tag_name → percent_of_supply
    tag_map: dict[str, float] = {}
    tag_details: list[dict] = []
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, dict):
                name = (t.get("tag") or "").lower()
                pct = _to_float(t.get("percent_of_supply")) or 0.0
                if name:
                    tag_map[name] = pct
                    tag_details.append({
                        "tag": name,
                        "holder_count": t.get("holder_count"),
                        "percent_of_supply": round(pct, 2),
                    })
            elif isinstance(t, str):
                tag_map[t.lower()] = 0.0
    bd["cohort_tags"] = tag_details

    # ── Risky cohort penalties (weighted by % of supply held) ──
    # NOTE: bundler penalty intentionally removed per user request.

    # sniper: MEV/sandwich traders — quick dump risk
    sniper_pct = tag_map.get("sniper", 0.0)
    if sniper_pct >= 20:
        score -= 20
        penalties.append({"name": "sniper_concentration", "delta": -20,
                          "detail": f"Snipers hold {sniper_pct:.1f}% of supply"})
    elif sniper_pct >= 10:
        score -= 10
        penalties.append({"name": "sniper_concentration", "delta": -10,
                          "detail": f"Snipers hold {sniper_pct:.1f}% of supply"})

    # insider: team/early backers — unlock risk
    insider_pct = tag_map.get("insider", 0.0)
    if insider_pct >= 20:
        score -= 25
        penalties.append({"name": "insider_concentration", "delta": -25,
                          "detail": f"Insiders hold {insider_pct:.1f}% of supply"})
    elif insider_pct >= 10:
        score -= 12
        penalties.append({"name": "insider_concentration", "delta": -12,
                          "detail": f"Insiders hold {insider_pct:.1f}% of supply"})

    # dev: developer wallet — dump risk
    dev_pct = tag_map.get("dev", 0.0)
    if dev_pct >= 30:
        score -= 30
        penalties.append({"name": "dev_concentration", "delta": -30,
                          "detail": f"Dev holds {dev_pct:.1f}% of supply"})
    elif dev_pct >= 15:
        score -= 15
        penalties.append({"name": "dev_concentration", "delta": -15,
                          "detail": f"Dev holds {dev_pct:.1f}% of supply"})

    # ── Quality cohort bonuses ──
    smart_pct = tag_map.get("smart_trader", 0.0)
    if smart_pct >= 5:
        bonus = min(15, smart_pct)
        score += bonus
        bonuses.append({"name": "smart_trader", "delta": round(bonus, 1),
                        "detail": f"Smart traders hold {smart_pct:.1f}% of supply"})

    kol_pct = tag_map.get("kol", 0.0)
    if kol_pct >= 2:
        bonus = min(10, kol_pct * 2)
        score += bonus
        bonuses.append({"name": "kol", "delta": round(bonus, 1),
                        "detail": f"KOLs hold {kol_pct:.1f}% of supply"})

    # ── Legacy fields (top1 holder, whale ratio) ──
    top1 = _to_float(hp.get("top1HolderPercent") or hp.get("top_holder_pct"))
    if top1 is not None:
        top1_pct = top1 * 100 if top1 <= 1.0 else top1
        bd["top1_holder_pct"] = round(top1_pct, 1)
        if top1_pct > 50:
            score -= 20
            penalties.append({"name": "top1_holder", "delta": -20,
                              "detail": f"Top holder {top1_pct:.1f}%"})
        elif top1_pct > 30:
            score -= 10
            penalties.append({"name": "top1_holder", "delta": -10,
                              "detail": f"Top holder {top1_pct:.1f}%"})

    whale_ratio = _to_float(hp.get("whaleRatio") or hp.get("whale_ratio"))
    if whale_ratio is not None:
        bd["whale_ratio"] = round(whale_ratio, 4)
        if whale_ratio > 0.5:
            score -= 15
            penalties.append({"name": "whale_ratio", "delta": -15,
                              "detail": f"Whale ratio {whale_ratio:.2f}"})

    score = _clamp(score)
    bd["penalties"] = penalties
    bd["bonuses"] = bonuses
    bd["final"] = round(score, 1)
    bd["source"] = "holder_profile"
    return round(score, 1), bd


def holder_dynamics_score(ovd: dict, snapshots: list[dict], interval: str,
                          now_ts: int, holder_count: float | None,
                          holder_chart: list[dict] | None = None,
                          holder_profile: dict | None = None) -> tuple[float, dict]:
    """Score holder dynamics 0..100.

    Factors:
      - holder_growth: statistical momentum of holder count over window (holder chart) — 40%
      - holder_health: holder profile cohort quality — 30%
      - holder_sufficiency: absolute holder count (log scale) — 30%
    """
    bd: dict[str, Any] = {}
    iv_minutes = INTERVAL_MINUTES[interval]

    # 1) Holder growth from chart (full series regression) — weight 40%
    growth_score_val, growth_bd = holder_growth_from_chart(holder_chart or [], iv_minutes, now_ts)
    bd["holder_growth"] = growth_bd
    if growth_score_val is not None:
        bd["growth_source"] = growth_bd.get("source")
    else:
        # Fallback: unique wallet change from overview (single-point)
        chg_field = f"uniqueWallet{interval}ChangePercent"
        change = _to_float(ovd.get(chg_field))
        if change is not None:
            growth_score_val = growth_score_from_pct(change)
            bd["growth_source"] = "unique_wallet"
            bd["holder_growth_pct"] = round(change, 2)
        else:
            growth_score_val = 50.0
            bd["growth_source"] = "none"

    # 2) Holder health from profile — weight 30%
    health_score, health_bd = holder_health_from_profile(holder_profile)
    bd["holder_health"] = health_bd

    # 3) Holder count sufficiency — weight 30%
    if holder_count is not None and holder_count > 0:
        bd["holder_count"] = int(holder_count)
        suff_score = _clamp(math.log10(holder_count + 1) / math.log10(1_000_001) * 100.0)
    else:
        suff_score = 0.0
        bd["holder_count"] = None

    score = (growth_score_val * 0.40 + health_score * 0.30 + suff_score * 0.30)
    bd["subscores"] = {
        "growth": round(growth_score_val, 1),
        "health": round(health_score, 1),
        "sufficiency": round(suff_score, 1),
    }
    return round(_clamp(score), 1), bd


# ──────────────────────────────────────────────
# Security Score (0..100) — contract risk only
# ──────────────────────────────────────────────
def security_score(secd: dict | None) -> tuple[float, dict]:
    """Security score 0..100 from token contract risk flags.

    Checks: honeypot, mint/freeze authority, LP lock, top10 concentration, taxes.
    Does NOT penalize holder cohorts (bundler/sniper etc.) — those are handled
    in holder health, or ignored per user request.
    """
    bd: dict[str, Any] = {"penalties": []}
    secd = secd or {}
    score = 100.0

    # Honeypot → hard 0
    honeypot = secd.get("isHoneypot") or secd.get("honeypot") or secd.get("is_honeypot")
    if isinstance(honeypot, str):
        honeypot = honeypot.lower() in ("1", "true", "yes", "high")
    elif isinstance(honeypot, (int, float)):
        honeypot = bool(honeypot)
    bd["honeypot"] = bool(honeypot) if honeypot is not None else None
    if honeypot:
        bd["penalties"].append({"name": "honeypot", "delta": -100,
                                "detail": "Token is a honeypot"})
        return 0.0, bd

    # Mint authority
    mint_auth = secd.get("ownerAddress") or secd.get("mintAuthority") or secd.get("mint_authority")
    mint_renounced = mint_auth in (None, "", "0x000000000000000000000000000000000000000000000")
    bd["mint_renounced"] = mint_renounced
    if not mint_renounced:
        score -= 25
        bd["penalties"].append({"name": "mint_active", "delta": -25,
                                "detail": "Mint authority still active"})

    # Freeze authority
    freeze_auth = secd.get("freezeAuthority") or secd.get("freeze_authority")
    freeze_renounced = freeze_auth in (None, "", "0x000000000000000000000000000000000000000000000")
    bd["freeze_renounced"] = freeze_renounced
    if not freeze_renounced:
        score -= 25
        bd["penalties"].append({"name": "freeze_active", "delta": -25,
                                "detail": "Freeze authority still active"})

    # LP lock
    lp_locked = secd.get("lpLocked") or secd.get("lp_locked")
    if isinstance(lp_locked, str):
        lp_locked = lp_locked.lower() in ("1", "true", "yes")
    bd["lp_locked"] = bool(lp_locked) if lp_locked is not None else None
    if lp_locked is False:
        score -= 30
        bd["penalties"].append({"name": "lp_unlocked", "delta": -30,
                                "detail": "Liquidity pool not locked"})

    # Top 10 holder concentration
    top10 = _to_float(secd.get("top10HolderPercent") or secd.get("top10_holder_percent")
                      or secd.get("top10UserPercent") or secd.get("top_10_pct"))
    if top10 is not None:
        top10_pct = top10 * 100 if top10 <= 1.0 else top10
        bd["top10_holder_pct"] = round(top10_pct, 1)
        if top10_pct > 60:
            score -= 20
            bd["penalties"].append({"name": "top10_high", "delta": -20,
                                    "detail": f"Top 10 holders {top10_pct:.0f}%"})
        elif top10_pct > 40:
            score -= 10
            bd["penalties"].append({"name": "top10_med", "delta": -10,
                                    "detail": f"Top 10 holders {top10_pct:.0f}%"})

    # Sell tax
    sell_tax = _to_float(secd.get("sellTax") or secd.get("sell_tax") or secd.get("sellFee"))
    if sell_tax is not None:
        st = sell_tax * 100 if sell_tax <= 1.0 else sell_tax
        bd["sell_tax_pct"] = round(st, 1)
        if st > 10:
            score -= 25
            bd["penalties"].append({"name": "high_sell_tax", "delta": -25,
                                    "detail": f"Sell tax {st:.1f}%"})
        elif st > 5:
            score -= 12
            bd["penalties"].append({"name": "sell_tax", "delta": -12,
                                    "detail": f"Sell tax {st:.1f}%"})

    # Buy tax
    buy_tax = _to_float(secd.get("buyTax") or secd.get("buy_tax") or secd.get("buyFee"))
    if buy_tax is not None:
        bt = buy_tax * 100 if buy_tax <= 1.0 else buy_tax
        bd["buy_tax_pct"] = round(bt, 1)
        if bt > 10:
            score -= 15
            bd["penalties"].append({"name": "high_buy_tax", "delta": -15,
                                    "detail": f"Buy tax {bt:.1f}%"})

    score = _clamp(score)
    bd["final"] = round(score, 1)
    return round(score, 1), bd


# ──────────────────────────────────────────────
# Main: compute trending score for all intervals
# ──────────────────────────────────────────────
def compute_trending_score(
    ovd: dict | None,
    secd: dict | None,
    snapshots: list[dict] | None = None,
    candles_1m: list[dict] | None = None,
    liq_1m: list[dict] | None = None,
    weights: dict | None = None,
    now_ts: int | None = None,
    candles_1s: list[dict] | None = None,
    holder_chart: list[dict] | None = None,
    holder_profile: dict | None = None,
) -> dict:
    """Compute trending scores for all intervals.

    Returns dict with per-interval scores + overall + components.
    """
    ovd = ovd or {}
    secd = secd or {}
    snapshots = snapshots or []
    candles_1m = candles_1m or []
    candles_1s = candles_1s or []
    liq_1m = liq_1m or []
    holder_chart = holder_chart or []
    holder_profile = holder_profile or {}
    w = weights or DEFAULT_WEIGHTS
    if now_ts is None:
        import time
        now_ts = int(time.time())

    mcap = _to_float(ovd.get("marketCap") or ovd.get("market_cap"))
    holder_count = _to_float(ovd.get("holder"))
    liquidity = _to_float(ovd.get("liquidity"))

    # Security is interval-agnostic (call once, cached)
    sec_score, sec_bd = security_score(secd)
    is_risky = sec_score < 40

    intervals_result: dict[str, dict] = {}
    for interval in INTERVALS:
        # Volume growth (candles for non-overview intervals)
        vol_candles = candles_1s if interval in SHORT_CANDLE_INTERVALS else candles_1m
        vol_s, vol_bd = volume_growth_score(ovd, snapshots, interval, now_ts, vol_candles)

        # Swaps growth (proxy from volume for candle intervals)
        swp_s, swp_bd = swaps_growth_score(ovd, snapshots, interval, now_ts, vol_s)

        # Price momentum (1s candles for short intervals)
        pr_s, pr_bd = price_momentum_score(ovd, interval, now_ts, candles_1s, candles_1m)

        # Liquidity health (interval-agnostic)
        liq_s, liq_bd = liquidity_health_score(liquidity, mcap, liq_1m, now_ts)

        # Holder dynamics (holder chart + profile)
        hol_s, hol_bd = holder_dynamics_score(
            ovd, snapshots, interval, now_ts, holder_count,
            holder_chart, holder_profile)

        # Composite
        raw = (vol_s * w["volume"] + swp_s * w["swaps"] + pr_s * w["price"] +
               liq_s * w["liquidity"] + hol_s * w["holder"] +
               sec_score * w["security"])

        final = raw * 0.1 if is_risky else raw
        final = round(_clamp(final), 1)

        intervals_result[interval] = {
            "trending_score": final,
            "components": {
                "volume": {"score": vol_s, **vol_bd},
                "swaps": {"score": swp_s, **swp_bd},
                "price": {"score": pr_s, **pr_bd},
                "liquidity": {"score": liq_s, **liq_bd},
                "holder": {"score": hol_s, **hol_bd},
                "security": {"score": sec_score, **sec_bd},
            },
            "raw_score": round(raw, 1),
            "security_multiplier": 0.1 if is_risky else 1.0,
        }

    scores = [v["trending_score"] for v in intervals_result.values()
              if v.get("trending_score") is not None]
    overall = round(mean(scores), 1) if scores else None

    return {
        "overall_trending_score": overall,
        "intervals": intervals_result,
        "security": sec_bd,
        "is_risky": is_risky,
        "weights": w,
        "meta": {
            "market_cap": mcap,
            "holder_count": holder_count,
            "liquidity": liquidity,
            "n_snapshots": len(snapshots),
            "n_1m_candles": len(candles_1m),
            "n_1s_candles": len(candles_1s),
            "n_liq_points": len(liq_1m),
            "n_holder_chart": len(holder_chart),
            "holder_profile": bool(holder_profile),
        },
    }
