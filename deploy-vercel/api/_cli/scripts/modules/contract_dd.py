"""
Contract DD skill module (GMGN gmgn-contract-dd port).

Composite 0-100 score from three pillars:
  1. Contract safety (mint/freeze/lp authority, taxes, honeypot)
  2. Holder structure (concentration, top-10, LP locked)
  3. Price action (drawdown, volatility, trend from kline)

Inputs are raw Birdeye API dicts:
  - ovd: token_overview data
  - secd: token_security data
  - holder_data: holder/v1/distribution data
  - kline_result: kline_pattern.analyze_kline result (optional)
"""
from __future__ import annotations

import math
from typing import Any


def _f(v, default=None):
    try:
        if v is None or v == "":
            return default
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return default
        return fv
    except (TypeError, ValueError):
        return default


def _is_populated(v) -> bool:
    """GMGN rule: EVM security fields populated if not null/absent/empty/'0'."""
    if v is None:
        return False
    if isinstance(v, str):
        s = v.strip().lower()
        return s not in ("", "0", "null", "none", "false", "0x0")
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, bool):
        return v
    return bool(v)


def contract_safety_score(ovd: dict, secd: dict) -> tuple[float, list[dict]]:
    """Pillar 1: contract safety 0..100. Returns (score, breakdown)."""
    score = 100.0
    breakdown: list[dict] = []

    # Mint authority
    mint_auth = secd.get("mintAuthority") or secd.get("mint_authority") or secd.get("mintAuthorityAddress")
    mint_disabled = secd.get("freezeAuthority") is not None  # placeholder
    # GMGN: renounced mint is real on Solana, struct default on EVM
    mint_renounced = (
        secd.get("mintAuthority") in (None, "", "0x000000000000000000000000000000000000000000000")
        or secd.get("isMintAuthorityDisabled") is True
        or secd.get("mintDisabled") is True
    )
    if mint_renounced:
        breakdown.append({"name": "mint_renounced", "delta": 0, "detail": "Mint authority disabled/renounced"})
    else:
        score -= 25
        breakdown.append({"name": "mint_active", "delta": -25, "detail": f"Mint authority still active: {str(mint_auth)[:20]}"})

    # Freeze authority
    freeze_auth = secd.get("freezeAuthority") or secd.get("freeze_authority")
    freeze_disabled = (
        freeze_auth in (None, "", "0x000000000000000000000000000000000000000000000")
        or secd.get("isFreezeAuthorityDisabled") is True
        or secd.get("freezeDisabled") is True
    )
    if freeze_disabled:
        breakdown.append({"name": "freeze_renounced", "delta": 0, "detail": "Freeze authority disabled"})
    else:
        score -= 20
        breakdown.append({"name": "freeze_active", "delta": -20, "detail": f"Freeze authority active: {str(freeze_auth)[:20]}"})

    # LP locked
    lp_locked_pct = _f(secd.get("lpLocked") or secd.get("lp_locked") or secd.get("lpLockedPercentage"))
    lp_total = _f(secd.get("lpTotalSupply") or secd.get("lp_total_supply"))
    if lp_locked_pct is not None:
        if lp_locked_pct >= 80:
            breakdown.append({"name": "lp_locked", "delta": 0, "detail": f"LP locked {lp_locked_pct:.0f}%"})
        elif lp_locked_pct >= 50:
            score -= 10
            breakdown.append({"name": "lp_partial", "delta": -10, "detail": f"LP only {lp_locked_pct:.0f}% locked"})
        else:
            score -= 25
            breakdown.append({"name": "lp_unlocked", "delta": -25, "detail": f"LP only {lp_locked_pct:.0f}% locked"})
    else:
        # Try from overview
        lp = ovd.get("liquidity") if isinstance(ovd, dict) else None
        breakdown.append({"name": "lp_unknown", "delta": -5, "detail": "LP lock status unknown"})

    # Buy/sell tax (GMGN: all rate fields are decimal fractions, ×100 for %)
    buy_tax = _f(secd.get("buyTax") or secd.get("buy_tax") or secd.get("buyFee") or secd.get("buy_fee"))
    sell_tax = _f(secd.get("sellTax") or secd.get("sell_tax") or secd.get("sellFee") or secd.get("sell_fee"))
    # Normalize: if > 1, assume already percentage; else assume fraction
    if buy_tax is not None:
        bt = buy_tax * 100 if buy_tax <= 1 else buy_tax
        if bt > 10:
            score -= 15
            breakdown.append({"name": "high_buy_tax", "delta": -15, "detail": f"Buy tax {bt:.1f}%"})
        elif bt > 5:
            score -= 5
            breakdown.append({"name": "buy_tax", "delta": -5, "detail": f"Buy tax {bt:.1f}%"})
        else:
            breakdown.append({"name": "buy_tax", "delta": 0, "detail": f"Buy tax {bt:.1f}%"})
    if sell_tax is not None:
        st = sell_tax * 100 if sell_tax <= 1 else sell_tax
        if st > 10:
            score -= 15
            breakdown.append({"name": "high_sell_tax", "delta": -15, "detail": f"Sell tax {st:.1f}%"})
        elif st > 5:
            score -= 5
            breakdown.append({"name": "sell_tax", "delta": -5, "detail": f"Sell tax {st:.1f}%"})
        else:
            breakdown.append({"name": "sell_tax", "delta": 0, "detail": f"Sell tax {st:.1f}%"})

    # Honeypot
    honeypot = secd.get("isHoneypot") or secd.get("honeypot") or secd.get("is_honeypot")
    if honeypot is True:
        score -= 50
        breakdown.append({"name": "honeypot", "delta": -50, "detail": "Token is a honeypot"})

    score = max(0.0, min(100.0, score))
    return round(score, 1), breakdown


def holder_structure_score(holder_data: dict | None, ovd: dict) -> tuple[float, list[dict]]:
    """Pillar 2: holder structure 0..100. Returns (score, breakdown)."""
    score = 100.0
    breakdown: list[dict] = []

    if not holder_data:
        score -= 10
        breakdown.append({"name": "no_holder_data", "delta": -10, "detail": "No holder distribution data"})
        return max(0.0, min(100.0, score)), breakdown

    # Top 10 holder concentration
    holders = (
        holder_data.get("holders")
        or holder_data.get("data", {}).get("holders")
        or holder_data.get("items")
        or []
    )
    top10_pct = _f(holder_data.get("top10") or holder_data.get("top10Percentage") or holder_data.get("top_10_pct"))
    if top10_pct is None and isinstance(holders, list) and len(holders) >= 10:
        # Estimate from holder list
        total = sum(_f(h.get("amount") or h.get("balance") or h.get("percentage"), 0) for h in holders[:10])
        # If percentages, sum; if amounts, need supply
        first_pct = _f(holders[0].get("percentage") if isinstance(holders[0], dict) else None)
        if first_pct is not None:
            top10_pct = sum(_f(h.get("percentage"), 0) for h in holders[:10])
    if top10_pct is not None:
        if top10_pct > 70:
            score -= 30
            breakdown.append({"name": "top10_high", "delta": -30, "detail": f"Top 10 hold {top10_pct:.0f}%"})
        elif top10_pct > 50:
            score -= 15
            breakdown.append({"name": "top10_med", "delta": -15, "detail": f"Top 10 hold {top10_pct:.0f}%"})
        elif top10_pct > 30:
            score -= 5
            breakdown.append({"name": "top10_low", "delta": -5, "detail": f"Top 10 hold {top10_pct:.0f}%"})
        else:
            breakdown.append({"name": "top10_ok", "delta": 0, "detail": f"Top 10 hold {top10_pct:.0f}%"})

    # #1 holder
    top1_pct = _f(holder_data.get("top1") or holder_data.get("top1Percentage") or holder_data.get("top_1_pct"))
    if top1_pct is None and isinstance(holders, list) and holders:
        top1_pct = _f(holders[0].get("percentage") if isinstance(holders[0], dict) else None)
    if top1_pct is not None:
        if top1_pct > 30:
            score -= 25
            breakdown.append({"name": "top1_whale", "delta": -25, "detail": f"#1 holder {top1_pct:.0f}%"})
        elif top1_pct > 15:
            score -= 10
            breakdown.append({"name": "top1_high", "delta": -10, "detail": f"#1 holder {top1_pct:.0f}%"})
        else:
            breakdown.append({"name": "top1_ok", "delta": 0, "detail": f"#1 holder {top1_pct:.0f}%"})

    # Holder count
    holder_count = _f(ovd.get("holder") if isinstance(ovd, dict) else None)
    if holder_count is not None:
        if holder_count < 100:
            score -= 20
            breakdown.append({"name": "few_holders", "delta": -20, "detail": f"Only {holder_count:.0f} holders"})
        elif holder_count < 500:
            score -= 5
            breakdown.append({"name": "low_holders", "delta": -5, "detail": f"{holder_count:.0f} holders"})
        else:
            breakdown.append({"name": "holders_ok", "delta": 0, "detail": f"{holder_count:.0f} holders"})

    score = max(0.0, min(100.0, score))
    return round(score, 1), breakdown


def price_action_score(kline_result: dict | None) -> tuple[float, list[dict]]:
    """Pillar 3: price action 0..100 from kline pattern result. Returns (score, breakdown)."""
    breakdown: list[dict] = []
    if not kline_result or not kline_result.get("ok"):
        breakdown.append({"name": "no_kline", "delta": -5, "detail": "No kline data"})
        return 50.0, breakdown

    score = float(kline_result.get("score", 50))
    pattern = kline_result.get("pattern", "unknown")
    breakdown.append({"name": "kline_pattern", "delta": score - 50, "detail": f"Kline pattern: {pattern} → {score:.0f}/100"})
    return round(score, 1), breakdown


def composite_score(safety: float, holders: float, price: float,
                    w_safety=0.45, w_holders=0.30, w_price=0.25) -> float:
    """Weighted composite 0..100."""
    return round(safety * w_safety + holders * w_holders + price * w_price, 1)


def dd_tier(score: float) -> tuple[str, str, str]:
    """(name, emoji, color) for composite score."""
    if score >= 75:
        return ("Safe", "🟢", "#22c55e")
    if score >= 55:
        return ("Caution", "🟡", "#f59e0b")
    if score >= 35:
        return ("Risky", "🟠", "#f97316")
    return ("Danger", "🔴", "#ef4444")


def analyze_contract(ovd: dict, secd: dict, holder_data: dict | None,
                     kline_result: dict | None = None) -> dict:
    """Main entry: raw Birdeye dicts → {safety, holders, price, composite, tier, breakdowns}."""
    safety, safety_bd = contract_safety_score(ovd or {}, secd or {})
    holders, holders_bd = holder_structure_score(holder_data, ovd or {})
    price, price_bd = price_action_score(kline_result)
    composite = composite_score(safety, holders, price)
    tier_name, tier_emoji, tier_color = dd_tier(composite)
    return {
        "safety_score": safety,
        "holders_score": holders,
        "price_score": price,
        "composite": composite,
        "tier": {"name": tier_name, "emoji": tier_emoji, "color_hex": tier_color},
        "safety_breakdown": safety_bd,
        "holders_breakdown": holders_bd,
        "price_breakdown": price_bd,
        "weights": {"safety": 0.45, "holders": 0.30, "price": 0.25},
    }
