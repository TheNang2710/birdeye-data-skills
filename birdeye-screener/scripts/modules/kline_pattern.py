"""
Kline Pattern skill module.

Pure-python: takes a list of candle dicts and returns pattern + score + 6 measurements + evidence.

Candle dict format (normalized):
    {"t": int(seconds), "o": float, "h": float, "l": float, "c": float, "v": float}
"""
from __future__ import annotations

import math
from statistics import mean


def _to_float(v) -> float | None:
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def normalize_candles(raw: list[dict]) -> list[dict]:
    """Sort by time ascending, drop candles with close/high/low <= 0 or non-numeric."""
    out: list[dict] = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        t = _to_float(e.get("t") or e.get("time") or e.get("timestamp") or 0)
        o = _to_float(e.get("o") or e.get("open") or 0)
        h = _to_float(e.get("h") or e.get("high") or 0)
        l = _to_float(e.get("l") or e.get("low") or 0)
        c = _to_float(e.get("c") or e.get("close") or 0)
        v = _to_float(e.get("v") or e.get("volume") or 0) or 0.0
        if c is None or h is None or l is None:
            continue
        if c <= 0 or h <= 0 or l <= 0:
            continue
        if o is None or o <= 0:
            o = c
        out.append({"t": int(t) if t else 0, "o": o, "h": h, "l": l, "c": c, "v": v})
    out.sort(key=lambda x: x["t"])
    return out


def compute_measurements(candles: list[dict]) -> dict:
    """Compute the 6 core numbers from normalized candles."""
    n = len(candles)
    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    vols = [c["v"] for c in candles]

    # 1. trend_up (3-valued): mean(last 9 closes) vs mean(last 21 closes)
    if n >= 21:
        m9 = mean(closes[-9:])
        m21 = mean(closes[-21:])
    elif n >= 9:
        m9 = mean(closes[-9:])
        m21 = mean(closes)
    else:
        m9 = mean(closes)
        m21 = mean(closes)
    if m21 == 0:
        trend_up = "flat"
    else:
        ratio = m9 / m21
        if ratio > 1.003:
            trend_up = "up"
        elif ratio < 0.997:
            trend_up = "down"
        else:
            trend_up = "flat"

    # 2. slope
    if n >= 24:
        recent = mean(closes[-5:])
        older = mean(closes[-24:-19])
        slope = (recent - older) / older if older else 0.0
    else:
        slope = (closes[-1] - closes[0]) / closes[0] if closes[0] else 0.0

    # 3. volatility: mean(last 14 of (high-low)/close)
    body = candles[-14:] if n >= 14 else candles
    vol_pcts = [(c["h"] - c["l"]) / c["c"] if c["c"] else 0.0 for c in body]
    volatility = mean(vol_pcts) if vol_pcts else 0.0

    # 4. drawdown: (max(all highs) - close[-1]) / max(all highs)
    max_h = max(highs) if highs else 0.0
    drawdown = (max_h - closes[-1]) / max_h if max_h else 0.0

    # 5. vol_ratio: V[-1] / mean(V[-21:-1])
    if n >= 22:
        vol_prev = vols[-21:-1]
        mean_prev = mean(vol_prev) if vol_prev else 0.0
        vol_ratio = vols[-1] / mean_prev if mean_prev else 1.0
    else:
        vol_ratio = 1.0

    # 6. up_from_low: (close[-1] - min(all lows)) / min(all lows)
    min_l = min(lows) if lows else 0.0
    up_from_low = (closes[-1] - min_l) / min_l if min_l else 0.0

    return {
        "trend_up": trend_up,
        "slope": round(slope, 6),
        "volatility": round(volatility, 6),
        "drawdown": round(drawdown, 6),
        "vol_ratio": round(vol_ratio, 3),
        "up_from_low": round(up_from_low, 6),
        "n_candles": n,
    }


def classify_pattern(m: dict) -> tuple[str, list[str]]:
    """First-match-wins pattern classification. Returns (pattern_name, evidence)."""
    ev: list[str] = []
    tu = m["trend_up"]
    slope = m["slope"]
    vol = m["volatility"]
    dd = m["drawdown"]
    vr = m["vol_ratio"]
    ufl = m["up_from_low"]

    # 1. vertical run-up
    if slope > 0.30 and tu == "up":
        ev.append(f"slope={slope:.3f} > 0.30 (vertical)")
        ev.append(f"trend_up={tu}")
        return "vertical_run_up", ev

    # 2. uptrend channel
    if tu == "up" and 0.005 <= slope <= 0.30 and dd < 0.25:
        ev.append(f"trend_up={tu}")
        ev.append(f"slope={slope:.4f} in [0.005, 0.30]")
        ev.append(f"drawdown={dd:.3f} < 0.25")
        return "uptrend_channel", ev

    # 3. breakdown
    if tu == "down" and slope < -0.10 and dd > 0.20:
        ev.append(f"trend_up={tu}")
        ev.append(f"slope={slope:.4f} < -0.10")
        ev.append(f"drawdown={dd:.3f} > 0.20")
        return "breakdown", ev

    # 4. bounce off lows
    if dd > 0.25 and ufl > 0.15 and tu in ("up", "flat"):
        ev.append(f"drawdown={dd:.3f} > 0.25 (off highs)")
        ev.append(f"up_from_low={ufl:.3f} > 0.15 (bouncing)")
        ev.append(f"trend_up={tu}")
        return "bounce_off_lows", ev

    # 5. distribution at highs
    if ufl > 0.50 and dd < 0.15 and tu in ("flat", "down") and vr > 1.5:
        ev.append(f"up_from_low={ufl:.3f} > 0.50 (near highs)")
        ev.append(f"drawdown={dd:.3f} < 0.15 (no big pullback)")
        ev.append(f"vol_ratio={vr:.2f} > 1.5 (high volume)")
        return "distribution_at_highs", ev

    # 6. slow bleed
    if tu == "down" and -0.30 <= slope < -0.005:
        ev.append(f"trend_up={tu}")
        ev.append(f"slope={slope:.4f} in [-0.30, -0.005) (slow)")
        return "slow_bleed", ev

    # 7. basing at lows
    if dd > 0.40 and ufl < 0.10 and tu == "flat":
        ev.append(f"drawdown={dd:.3f} > 0.40 (deep)")
        ev.append(f"up_from_low={ufl:.3f} < 0.10 (flat at bottom)")
        ev.append(f"trend_up={tu}")
        return "basing_at_lows", ev

    # 8. wide chop
    if vol > 0.12 and tu == "flat":
        ev.append(f"volatility={vol:.3f} > 0.12 (wide)")
        ev.append(f"trend_up={tu}")
        return "wide_chop", ev

    # 9. bullish consolidation
    if tu == "up" and 0.0 <= slope <= 0.01 and vol < 0.05:
        ev.append(f"trend_up={tu}")
        ev.append(f"slope={slope:.5f} in [0, 0.01]")
        ev.append(f"volatility={vol:.4f} < 0.05 (tight)")
        return "bullish_consolidation", ev

    # 10. bearish consolidation
    if tu == "down" and -0.01 <= slope <= 0.0 and vol < 0.05:
        ev.append(f"trend_up={tu}")
        ev.append(f"slope={slope:.5f} in [-0.01, 0]")
        ev.append(f"volatility={vol:.4f} < 0.05 (tight)")
        return "bearish_consolidation", ev

    # 11. sideways consolidation (default)
    ev.append("no strong directional signal")
    ev.append(f"trend_up={tu}, slope={slope:.5f}, vol={vol:.4f}")
    return "sideways_consolidation", ev


def compute_score(pattern: str, m: dict) -> tuple[float, list[str]]:
    """Score 0..100 starting at 50 with +/− rules. Returns (score, deltas)."""
    score = 50.0
    deltas: list[str] = []
    tu = m["trend_up"]
    slope = m["slope"]
    vol = m["volatility"]
    dd = m["drawdown"]
    vr = m["vol_ratio"]
    ufl = m["up_from_low"]

    if pattern == "vertical_run_up":
        score += 25
        deltas.append("+25 vertical_run_up")
        if dd > 0.20:
            score -= 10
            deltas.append("-10 drawdown > 0.20 (overextended)")
    elif pattern == "uptrend_channel":
        score += 20
        deltas.append("+20 uptrend_channel")
        if vr > 1.2:
            score += 5
            deltas.append("+5 vol_ratio > 1.2 (volume confirms)")
    elif pattern == "breakdown":
        score -= 25
        deltas.append("-25 breakdown")
    elif pattern == "bounce_off_lows":
        score += 15
        deltas.append("+15 bounce_off_lows")
        if vr > 1.3:
            score += 5
            deltas.append("+5 vol_ratio > 1.3 (volume confirms bounce)")
    elif pattern == "distribution_at_highs":
        score -= 20
        deltas.append("-20 distribution_at_highs")
    elif pattern == "slow_bleed":
        score -= 15
        deltas.append("-15 slow_bleed")
    elif pattern == "basing_at_lows":
        score += 10
        deltas.append("+10 basing_at_lows")
    elif pattern == "wide_chop":
        score -= 5
        deltas.append("-5 wide_chop")
    elif pattern == "bullish_consolidation":
        score += 12
        deltas.append("+12 bullish_consolidation")
    elif pattern == "bearish_consolidation":
        score -= 12
        deltas.append("-12 bearish_consolidation")
    else:
        deltas.append("±0 sideways_consolidation")

    # Universal adjustments
    if dd > 0.50:
        score -= 10
        deltas.append("-10 drawdown > 0.50 (deep)")
    if ufl > 1.0:
        score -= 5
        deltas.append("-5 up_from_low > 1.0 (far from lows)")
    if vol > 0.20:
        score -= 5
        deltas.append("-5 volatility > 0.20 (too volatile)")
    if vr < 0.5:
        score -= 5
        deltas.append("-5 vol_ratio < 0.5 (drying up)")

    score = max(0.0, min(100.0, score))
    return round(score, 1), deltas


def analyze_kline(raw_candles: list[dict]) -> dict:
    """Main entry: raw candles → {pattern, score, measurements, evidence, deltas}."""
    candles = normalize_candles(raw_candles)
    if len(candles) < 8:
        return {
            "ok": False,
            "error": f"need >= 8 valid candles, got {len(candles)}",
            "n_candles": len(candles),
        }
    m = compute_measurements(candles)
    pattern, evidence = classify_pattern(m)
    score, deltas = compute_score(pattern, m)
    return {
        "ok": True,
        "pattern": pattern,
        "score": score,
        "measurements": m,
        "evidence": evidence,
        "deltas": deltas,
        "n_candles": len(candles),
    }
