#!/usr/bin/env python3
"""Explore `new/data/wallet.csv` — the candidate universe behind the Smart Money leaderboard.

Re-runnable reference implementation for every number quoted in
`API/API-smart-money-csv-exploration.md`. Edit `--window` / `--top` (or the
`STABLE_MINTS` set) to re-cut the numbers.

Usage:
    python3 new/data/explore_wallet_csv.py
    python3 new/data/explore_wallet_csv.py --window all --top 25
    python3 new/data/explore_wallet_csv.py --section axes       # the four axes + screen
    python3 new/data/explore_wallet_csv.py --section pnl        # realized/total split + ROI
    python3 new/data/explore_wallet_csv.py --json /tmp/wallet_csv_agg.json

Sections: structure | stability | wealth | wallets | exit | funnel | axes | pnl | anomalies |
coverage | all
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics as st
from collections import Counter
from pathlib import Path

WINDOWS = ("7d", "30d", "90d", "all")

# Base currencies / pegged assets. Excluded from every "skill" metric because a
# swap into SOL or USDC is a routing leg, not a speculative position.
STABLE = frozenset({"usdc", "usdt", "usds", "dai", "sol", "wsol", "usdg", "fdusd",
                    "pyusd", "weth", "eth", "msol", "jitosol"})
STABLE_MINTS = frozenset({
    "So11111111111111111111111111111111111111112",    # WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",   # USDT
})

# Tuple layout inside every `top_tokens_*` cell (verified against 101,071 tuples).
IDX = {"rank": 0, "mint": 1, "window_ts": 2, "trade_count": 3, "volume_usd": 4,
       "pnl_total": 5, "pnl_realized": 6, "pnl_unrealized": 7,
       "buy_count": 8, "sell_count": 9}

SAFE_LITERAL = re.compile(r"^[\d\.,\-eE\(\)\[\]'\"\w\s]+$")
TOL = 1e-3  # relative tolerance for the total == realized + unrealized invariant

# One glitching tuple upstream reports a ±10^11 PnL. Winsorise before any SUM(),
# otherwise a single wallet owns an entire band's total.
WINSOR_ABS_USD = 1e9


def parse_cell(raw: str | None) -> list[tuple]:
    """Parse a list-of-tuples literal. The file uses SQL-style NULL, not None."""
    if not raw or not raw.strip():
        return []
    if not SAFE_LITERAL.match(raw):
        raise ValueError(f"unsafe literal: {raw[:80]}")
    return eval(  # noqa: S307 — sandboxed: no builtins, NULL/None/inf mapped
        raw,
        {"__builtins__": {}},
        {"nan": float("nan"), "inf": float("inf"), "None": None, "NULL": None},
    )


def f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def winsor(x: float, cap: float = WINSOR_ABS_USD) -> float:
    return max(-cap, min(cap, x))


def q(vals: list[float], p: float) -> float:
    """Cheap percentile — no numpy dependency."""
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))]


def spec_tokens(tokens: list[tuple]) -> list[tuple]:
    return [t for t in tokens if t[IDX["mint"]] not in STABLE_MINTS]


def aggregate(rows: list[dict], window: str) -> list[dict]:
    """Wallet-level PnL / exit metrics for one window, stablecoins excluded."""
    out = []
    for r in rows:
        toks = parse_cell(r["top_tokens_" + window])
        spec = spec_tokens(toks)
        real = sum(f(t[IDX["pnl_realized"]]) for t in spec)
        unreal = sum(f(t[IDX["pnl_unrealized"]]) for t in spec)
        # A NULL pnl_total must never be read as 0 — rebuild it from realized + unrealized.
        total = sum((f(t[IDX["pnl_realized"]]) + f(t[IDX["pnl_unrealized"]]))
                    if t[IDX["pnl_total"]] is None else f(t[IDX["pnl_total"]]) for t in spec)
        buys = sum(int(f(t[IDX["buy_count"]])) for t in spec)
        sells = sum(int(f(t[IDX["sell_count"]])) for t in spec)
        # Realised split in two by outcome — the profit booked on positions that
        # finished green vs the loss booked on positions that finished red. This
        # is a PnL decomposition, not a token-selection criterion.
        real_win = sum(f(t[IDX["pnl_realized"]]) for t in spec
                       if f(t[IDX["pnl_realized"]]) > 0)
        real_loss = sum(f(t[IDX["pnl_realized"]]) for t in spec
                        if f(t[IDX["pnl_realized"]]) < 0)
        # Realised split in two by exit state — booked on positions that actually
        # round-tripped (buy AND sell) vs booked on positions never sold.
        cycled = [t for t in spec
                  if f(t[IDX["sell_count"]]) > 0 and f(t[IDX["buy_count"]]) > 0]
        real_closed = sum(f(t[IDX["pnl_realized"]]) for t in cycled)
        out.append({
            "wallet": r["wallet"],
            "candidate_value_usd": f(r["candidate_value_usd"]),
            "n_tokens": len(toks),
            "n_spec": len(spec),
            "n_null": sum(1 for t in toks if t[IDX["pnl_unrealized"]] is None),
            "realized_usd": real,
            "unrealized_usd": unreal,
            "total_usd": total if total else real + unreal,
            "realized_win_usd": real_win,
            "realized_loss_usd": real_loss,
            "realized_closed_usd": real_closed,
            "realized_open_usd": real - real_closed,
            "spec_volume_usd": sum(f(t[IDX["volume_usd"]]) for t in spec),
            "buy_count": buys,
            "sell_count": sells,
            "n_cycled": len(cycled),
            "n_win_tokens": len(wins),
            "exit_ratio": (sells / (buys + sells)) if (buys + sells) else 0.0,
            "realization_ratio": (real / (real + unreal)) if (real + unreal) else None,
        })
    return out


# ── sections ──────────────────────────────────────────────────────────────

def sec_structure(rows, args, acc):
    print("## A. structure")
    print(f"rows                 : {len(rows):,}")
    print(f"columns              : {list(rows[0].keys())}")
    lens, fails, nulls = Counter(), 0, Counter()
    per_window = {w: [] for w in WINDOWS}
    ok = bad = null_pairs = 0
    for r in rows:
        for w in WINDOWS:
            try:
                toks = parse_cell(r["top_tokens_" + w])
            except Exception:
                fails += 1
                continue
            per_window[w].append(len(toks))
            for t in toks:
                lens[len(t)] += 1
                tot, rz, uz = t[IDX["pnl_total"]], t[IDX["pnl_realized"]], t[IDX["pnl_unrealized"]]
                if tot is None or uz is None:
                    null_pairs += 1
                    nulls[(w, IDX["pnl_total"])] += 1
                    nulls[(w, IDX["pnl_unrealized"])] += 1
                    continue
                if abs(f(tot) - (f(rz) + f(uz))) <= TOL * max(1.0, abs(f(tot))):
                    ok += 1
                else:
                    bad += 1
    print(f"tuple length         : {dict(lens)}")
    print(f"parse failures       : {fails}")
    print(f"INVARIANT pnl_total == pnl_realized + pnl_unrealized : "
          f"ok={ok:,} bad={bad:,} NULL-pairs={null_pairs:,}")
    print(f"NULL cells (window, idx) : {dict(sorted(nulls.items()))}"
          "   idx 5=pnl_total, 7=pnl_unrealized")
    print("tokens per wallet row:")
    for w in WINDOWS:
        v = per_window[w]
        print(f"  {w:4} lo={min(v)} hi={max(v)} mean={st.mean(v):.2f}")
    acc["structure"] = {"rows": len(rows), "invariant_ok": ok, "invariant_bad": bad,
                        "null_pairs": null_pairs, "tuple_len": dict(lens)}


def sec_stability(rows, args, acc):
    print("\n## B. stablecoin dilution (share of traded volume, lo/hi only)")
    out = {}
    for w in WINDOWS:
        sv = tv = 0.0
        for r in rows:
            for t in parse_cell(r["top_tokens_" + w]):
                tv += f(t[IDX["volume_usd"]])
                if t[IDX["mint"]] in STABLE_MINTS:
                    sv += f(t[IDX["volume_usd"]])
        share = 100 * sv / tv if tv else 0.0
        print(f"  {w:4} stable_share={share:5.1f}%")
        out[w] = round(share, 2)
    acc["stable_share_pct"] = out


def sec_wealth(rows, args, acc):
    cv = [f(r["candidate_value_usd"]) for r in rows]
    print("\n## C. candidate_value_usd (lo/hi only)")
    print(f"  lo(min)={min(cv):,.2f}  p25={q(cv,.25):,.2f}  p50={q(cv,.50):,.2f}  "
          f"p75={q(cv,.75):,.2f}  p90={q(cv,.90):,.2f}  hi(max)={max(cv):,.2f}")
    print(f"  NOTE: min = {min(cv):,.2f} USD -> the file already carries a 100k wealth floor")

    bands = [(100_000, 250_000), (250_000, 500_000), (500_000, 1_000_000),
             (1_000_000, 5_000_000), (5_000_000, float("inf"))]
    print("\n## C2. wealth band vs edge (window=%s, stablecoins excluded)" % args.window)
    print("  band                wallets  with-spec-tokens  positive-edge-share  sum_realized(winsorised)")
    agg = {a["wallet"]: a for a in aggregate(rows, args.window)}
    for lo, hi in bands:
        sel = [a for a in agg.values() if lo <= a["candidate_value_usd"] < hi]
        withspec = [a for a in sel if a["n_spec"] > 0]
        pos = [a for a in withspec if a["realized_usd"] > 0]
        ssum = sum(winsor(a["realized_usd"]) for a in withspec)
        lbl = f"{lo/1e3:,.0f}k-{hi/1e3:,.0f}k" if hi != float("inf") else f">={lo/1e3:,.0f}k"
        print(f"  {lbl:18} {len(sel):>7,} {len(withspec):>17,} "
              f"{100*len(pos)/max(len(withspec),1):>18.1f}% {ssum:>22,.0f}")
    pairs = [(a["candidate_value_usd"], a["realized_usd"]) for a in agg.values()
             if a["candidate_value_usd"] > 0 and a["realized_usd"] != 0]
    if len(pairs) > 2:
        try:
            print(f"\n  Pearson r(candidate_value_usd, realized_usd) = "
                  f"{st.correlation([p[0] for p in pairs], [p[1] for p in pairs]):+.4f}")
        except Exception as exc:  # degenerate input
            print(f"  correlation unavailable: {exc}")


def sec_wallets(rows, args, acc):
    agg = aggregate(rows, args.window)
    real = [a["realized_usd"] for a in agg]
    print(f"\n## D. wallet aggregates — window={args.window} (stablecoins excluded)")
    print(f"  realized_usd  p10={q(real,.10):,.0f}  p50={q(real,.50):,.0f}  "
          f"p90={q(real,.90):,.0f}  hi(max)={max(real):,.0f}")
    print(f"  positive_edge={sum(1 for v in real if v > 0):,}  "
          f"negative={sum(1 for v in real if v < 0):,}  "
          f"zero_or_no_data={sum(1 for v in real if v == 0):,}")
    print(f"  (zero bucket = wallet has no speculative top-token in this window)")
    top = sorted(agg, key=lambda a: -a["realized_usd"])[:args.top]
    print(f"  top {args.top} by realized PnL:")
    print("    #   wallet                                        realized   unrealized       total   "
          "vol_spec  cycled  exit_ratio")
    for i, a in enumerate(top, 1):
        print(f"    {i:>3}  {a['wallet']:<44} {a['realized_usd']:>11,.0f} {a['unrealized_usd']:>12,.0f} "
              f"{a['total_usd']:>11,.0f} {a['spec_volume_usd']/1e6:>9,.1f}M "
              f"{a['n_cycled']:>3}/{a['n_spec']:<2} {100*a['exit_ratio']:>8.1f}%")


def sec_exit(rows, args, acc):
    agg = aggregate(rows, args.window)
    print(f"\n## E. exit capability — window={args.window}, stablecoins excluded")
    b = Counter()
    for a in agg:
        if a["n_spec"] == 0:
            b["E0_NO_SPEC_TOKEN"] += 1
        elif a["n_cycled"] == 0:
            b["E1_BAGHOLDER"] += 1
        elif a["n_cycled"] == a["n_spec"]:
            b["E3_FULL_CYCLER"] += 1
        else:
            b["E2_PARTIAL_CYCLER"] += 1
    for k in sorted(b):
        print(f"  {k:20} {b[k]:>7,} ({100*b[k]/len(agg):5.1f}%)")
    er = [a["exit_ratio"] for a in agg if a["n_spec"] > 0]
    wr = [(a["n_win_tokens"]/a["n_cycled"]) for a in agg if a["n_cycled"] > 0]
    print(f"  exit_ratio (sells/(buys+sells)) p10={q(er,.10):.3f} p50={q(er,.50):.3f} p90={q(er,.90):.3f}")
    print(f"  token win-rate per wallet       p10={q(wr,.10):.3f} p50={q(wr,.50):.3f} p90={q(wr,.90):.3f}")

    # token-level population, pooled
    tot = spec_n = cycled = win = loss = bag = 0
    for r in rows:
        for w in WINDOWS:
            for t in parse_cell(r["top_tokens_" + w]):
                tot += 1
                if t[IDX["mint"]] in STABLE_MINTS:
                    continue
                spec_n += 1
                rz, uz = f(t[IDX["pnl_realized"]]), f(t[IDX["pnl_unrealized"]])
                if f(t[IDX["sell_count"]]) > 0 and f(t[IDX["buy_count"]]) > 0:
                    cycled += 1
                    win += rz > 0
                    loss += rz < 0
                elif rz <= 0 and uz < 0:
                    bag += 1
    print(f"\n  token population pooled over {len(WINDOWS)} windows: "
          f"tuples={tot:,} stable={tot-spec_n:,} speculative={spec_n:,}")
    print(f"  cycled={cycled:,}  closed_win={win:,}  closed_loss={loss:,}  baghold={bag:,}  "
          f"token_win_rate={100*win/max(cycled,1):.1f}%")
    acc["exit"] = {"token_win_rate_pct": round(100*win/max(cycled, 1), 2), "cycled": cycled,
                   "tuples": tot, "stable": tot-spec_n, "speculative": spec_n}


def sec_funnel(rows, args, acc):
    """Filter-first: the performance-only free screen, priced in CU.

    Same ladder as `--section axes` (I5) — PnL, exit, ROI, activity. Which tokens
    a wallet picked is not a gate. Only the survivors get paid calls.
    """
    print(f"\n## F. filter-first funnel — window={args.window}, stablecoins excluded")
    agg = aggregate(rows, args.window)

    def _roi(a):
        return (a["realized_usd"] / a["spec_volume_usd"]) if a["spec_volume_usd"] > 0 else None

    def _trades(a):
        return a["buy_count"] + a["sell_count"]

    def _share(a):
        d = a["realized_usd"] + a["unrealized_usd"]
        return (a["realized_usd"] / d) if d > 0 else None

    p = [a for a in agg if a["n_spec"] > 0]
    stages = [("P0_UNIVERSE", agg), ("P1_HAS_SPEC_TOKEN", p)]
    p = [a for a in p if a["realized_usd"] > 0]
    stages.append(("P2_REALIZED_GT_0", p))
    p = [a for a in p if a["total_usd"] > 0]
    stages.append(("P3_TOTAL_GT_0", p))
    p = [a for a in p if (_roi(a) or 0) >= 0.01]
    stages.append(("P4_ROI_GE_1PCT", p))
    p = [a for a in p if _trades(a) >= 50]
    stages.append(("P5_TRADES_GE_50", p))
    p = [a for a in p if a["n_cycled"] >= 1]
    stages.append(("P6_HAS_ROUNDTRIP", p))
    p = [a for a in p if (_share(a) or 0) >= 0.5]
    stages.append(("P7_REALIZED_SHARE_GE_50", p))

    base = len(agg)
    for label, sel in stages:
        print(f"  {label:26} {len(sel):>7,}  ({100*len(sel)/base:6.2f}% of universe)")
    print(f"  -> paid enrichment on P7 survivors: {len(p):,} wallets")
    for unit, name in ((30, "pnl/summary"), (60, "summary+details")):
        print(f"     {len(p)*unit:>10,} CU @ {unit} CU/wallet ({name})")
    print(f"     vs enriching the whole universe: {base*60:,} CU @ 60 CU/wallet")
    acc["funnel"] = {label: len(sel) for label, sel in stages}


def sec_anomalies(rows, args, acc):
    agg = aggregate(rows, args.window)
    print(f"\n## G. anomalies — window={args.window}")
    srt = sorted(agg, key=lambda a: a["realized_usd"])
    print("  worst 5 realized:", [f"{a['wallet'][:8]}…={a['realized_usd']:,.0f}" for a in srt[:5]])
    print("  best  5 realized:", [f"{a['wallet'][:8]}…={a['realized_usd']:,.0f}" for a in srt[-5:]])
    glitch = [a for a in agg if abs(a["realized_usd"]) > WINSOR_ABS_USD]
    print(f"  tuples beyond ±{WINSOR_ABS_USD:,.0f} USD after wallet SUM: {len(glitch)} "
          f"-> {[a['wallet'][:8] + '…' for a in glitch]}")
    zeros_tot = [a for a in agg if a["n_spec"] > 0 and a["total_usd"] == 0 and a["realized_usd"] != 0]
    print(f"  wallets whose cell pnl_total was NULL (total recomputed): "
          f"{sum(1 for a in agg if a['n_null'])}")


def sec_coverage(rows, args, acc):
    c, full = Counter(), 0
    for r in rows:
        toks = parse_cell(r["top_tokens_" + args.window])
        c[len(spec_tokens(toks))] += 1
        full += len(toks) == 10
    print(f"\n## H. coverage — speculative tokens visible per wallet, window={args.window}")
    print(f"  top-N cell cap = 10 -> wallets with a full cell: {full:,} "
          f"({100*full/len(rows):.1f}%) — their tail is truncated")
    print(f"  wallets with zero speculative token: {c.get(0, 0):,} "
          f"({100*c.get(0, 0)/len(rows):.1f}%)")
    print("  -> any per-wallet SUM from this file is a FLOOR, never a true total;")
    print("     true totals require /wallet/v2/pnl/summary during enrichment.")
    ts = [int(float(r["last_trade_unix_time"] or 0)) for r in rows]
    now = max(ts)
    print(f"  last_trade_unix_time span: file covers "
          f"{(now - min(ts))/86400:.1f} days (a 30d activity filter is already applied)")
    for label, secs in (("<=24h", 86400), ("<=7d", 7*86400), ("<=30d", 30*86400)):
        n = sum(1 for t in ts if now - t <= secs)
        print(f"  active {label:5}: {100*n/len(ts):5.1f}%")


def sec_axes(rows, args, acc):
    """The four questions a human asks first, in order:

        1. how many wallets are profitable?
        2. how much profit per dollar traded (ROI)?
        3. how many trades?
        4. how much capital (assets)?

    Then folds them into a screen that produces a rankable list. The screen is
    performance-only — PnL, exit, ROI, activity. Which tokens a wallet picked is
    not a criterion.
    """
    agg = aggregate(rows, args.window)
    n = len(agg)
    with_spec = [a for a in agg if a["n_spec"] > 0]
    win = [a for a in with_spec if a["realized_usd"] > 0]
    loss = [a for a in with_spec if a["realized_usd"] < 0]
    flat = [a for a in with_spec if a["realized_usd"] == 0]

    def roi(a):
        """Realised PnL per dollar of speculative volume. None when nothing traded."""
        return (a["realized_usd"] / a["spec_volume_usd"]) if a["spec_volume_usd"] > 0 else None

    def trades(a):
        return a["buy_count"] + a["sell_count"]

    def realized_share(a):
        """Share of the wallet's total PnL that is booked rather than still paper."""
        d = a["realized_usd"] + a["unrealized_usd"]
        return (a["realized_usd"] / d) if d > 0 else None

    print(f"\n## I. the four axes — window={args.window}, stablecoins excluded")

    # ── I1 ────────────────────────────────────────────────────────────────
    ws = max(len(with_spec), 1)
    print("\n### I1. how many wallets are profitable")
    print(f"  universe (all rows)              {n:>8,}")
    print(f"  .. with >=1 speculative token    {len(with_spec):>8,}  ({100*len(with_spec)/n:5.1f}% of universe)")
    print(f"     realised  > 0  (winners)      {len(win):>8,}  ({100*len(win)/ws:5.1f}% of with-spec)")
    print(f"     realised  < 0  (losers)       {len(loss):>8,}  ({100*len(loss)/ws:5.1f}%)")
    print(f"     realised == 0  (flat)         {len(flat):>8,}  ({100*len(flat)/ws:5.1f}%)")
    print(f"  .. no speculative token          {n-len(with_spec):>8,}  ({100*(n-len(with_spec))/n:5.1f}%)")

    # ── I2 ────────────────────────────────────────────────────────────────
    es = [100 * roi(a) for a in with_spec if roi(a) is not None]
    print("\n### I2. profit per traded volume  (ROI = realised / speculative volume)")
    if es:
        print(f"  lo={min(es):.2f}%  p25={q(es,.25):.2f}%  p50={q(es,.50):.2f}%  "
              f"p75={q(es,.75):.2f}%  p90={q(es,.90):.2f}%  hi={max(es):.2f}%")
    for t in (0.5, 1.0, 2.0, 5.0):
        k = sum(1 for e in es if e >= t)
        print(f"  ROI >= {t:>4.1f}% : {k:>8,}  ({100*k/max(len(es),1):5.1f}%)")
    ew = [100 * roi(a) for a in win if roi(a) is not None]
    el = [100 * roi(a) for a in loss if roi(a) is not None]
    print(f"  median ROI — winners p50={q(ew,.50):.2f}%   losers p50={q(el,.50):.2f}%")

    # ── I3 ────────────────────────────────────────────────────────────────
    tr = [trades(a) for a in with_spec]
    print("\n### I3. number of trades  (buys + sells on speculative tokens)")
    print(f"  lo={min(tr)}  p25={q(tr,.25):,.0f}  p50={q(tr,.50):,.0f}  "
          f"p75={q(tr,.75):,.0f}  p90={q(tr,.90):,.0f}  hi={max(tr):,}")
    for t in (3, 10, 50, 200):
        k = sum(1 for v in tr if v >= t)
        print(f"  trades >= {t:>4} : {k:>8,}  ({100*k/max(len(tr),1):5.1f}%)")

    # ── I4 ────────────────────────────────────────────────────────────────
    bands = [(100_000, 250_000), (250_000, 500_000), (500_000, 1_000_000),
             (1_000_000, 5_000_000), (5_000_000, float("inf"))]
    print("\n### I4. assets (candidate_value_usd) cross-cut with the other three axes")
    print("  band          w/spec  %profitable  med_ROI%  med_trades  med_volume")
    for lo, hi in bands:
        sel = [a for a in with_spec if lo <= a["candidate_value_usd"] < hi]
        if not sel:
            continue
        p = sum(1 for a in sel if a["realized_usd"] > 0)
        me = q([100 * roi(a) for a in sel if roi(a) is not None], .50)
        mt = q([trades(a) for a in sel], .50)
        mv = q([a["spec_volume_usd"] for a in sel], .50)
        lbl = f"{lo/1e3:,.0f}k-{hi/1e3:,.0f}k" if hi != float("inf") else f">={lo/1e3:,.0f}k"
        print(f"  {lbl:12} {len(sel):>7,} {100*p/len(sel):>11.1f}% {me:>9.2f} {mt:>11,.0f} {mv:>12,.0f}")

    # ── I5 ────────────────────────────────────────────────────────────────
    print("\n### I5. screen -> the list  (performance only: PnL, exit, ROI, activity)")
    s = [("P0_UNIVERSE", agg), ("P1_HAS_SPEC_TOKEN", with_spec)]
    cur = [a for a in with_spec if a["realized_usd"] > 0]
    s.append(("P2_REALIZED_GT_0", cur))
    cur = [a for a in cur if a["total_usd"] > 0]
    s.append(("P3_TOTAL_GT_0", cur))
    cur = [a for a in cur if (roi(a) or 0) >= 0.01]
    s.append(("P4_ROI_GE_1PCT", cur))
    cur = [a for a in cur if trades(a) >= 50]
    s.append(("P5_TRADES_GE_50", cur))
    cur = [a for a in cur if a["n_cycled"] >= 1]
    s.append(("P6_HAS_ROUNDTRIP", cur))
    cur = [a for a in cur if (realized_share(a) or 0) >= 0.5]
    s.append(("P7_REALIZED_SHARE_GE_50", cur))

    for label, sel in s:
        print(f"  {label:26} {len(sel):>7,}  ({100*len(sel)/n:6.2f}% of universe)")
    surv = cur
    if surv:
        print("\n  survivors profile (the smart-money cut):")
        print(f"    median realised  : {q([a['realized_usd'] for a in surv],.50):>12,.0f} USD")
        print(f"    median ROI       : {q([100*roi(a) for a in surv if roi(a) is not None],.50):>12.2f}%")
        print(f"    median trades    : {q([trades(a) for a in surv],.50):>12,.0f}")
        print(f"    median booked    : {q([a['realized_closed_usd'] for a in surv],.50):>12,.0f} USD")
        print(f"    median volume    : {q([a['spec_volume_usd'] for a in surv],.50):>12,.0f} USD")
        print(f"    median assets    : {q([a['candidate_value_usd'] for a in surv],.50):>12,.0f} USD")
    print(f"\n  -> paid enrichment on survivors: {len(surv):,} wallets "
          f"= {len(surv)*60:,} CU @ 60 CU (summary+details)")
    acc["axes"] = {"universe": n, "with_spec": len(with_spec), "winners": len(win),
                   "losers": len(loss), "flat": len(flat),
                   "screen": {label: len(sel) for label, sel in s}}


def sec_pnl(rows, args, acc):
    """PnL decomposition — the numbers behind "how much did this wallet actually make".

        1. realized / unrealized / total, per wallet
        2. realized split in two by outcome    (winning tokens vs losing tokens)
        3. realized split in two by exit state (round-tripped vs still held)
        4. ROI = realized / speculative volume
    """
    agg = aggregate(rows, args.window)
    with_spec = [a for a in agg if a["n_spec"] > 0]
    n = len(agg)
    ws = max(len(with_spec), 1)
    print(f"\n## J. PnL decomposition — window={args.window}, stablecoins excluded")

    # ── J1 ────────────────────────────────────────────────────────────────
    print("\n### J1. realized / unrealized / total  (per wallet)")
    for name, key in (("realized", "realized_usd"), ("unrealized", "unrealized_usd"),
                      ("total", "total_usd")):
        v = [a[key] for a in with_spec]
        print(f"  {name:11} lo={min(v):>16,.0f}  p10={q(v,.10):>14,.0f}  p50={q(v,.50):>12,.0f}  "
              f"p90={q(v,.90):>14,.0f}  hi={max(v):>16,.0f}")
    for name, key in (("realized > 0", "realized_usd"), ("unrealized > 0", "unrealized_usd"),
                      ("total > 0", "total_usd")):
        k = sum(1 for a in with_spec if a[key] > 0)
        print(f"  wallets with {name:16} {k:>7,}  ({100*k/ws:5.1f}% of with-spec, "
              f"{100*k/n:5.2f}% of universe)")
    bad = sum(1 for a in with_spec
              if abs(a["total_usd"] - (a["realized_usd"] + a["unrealized_usd"])) > 1.0)
    print(f"  identity total == realized + unrealized : mismatches={bad}")

    # ── J2 ────────────────────────────────────────────────────────────────
    print("\n### J2. realized split in two — winning tokens vs losing tokens (per token sign)")
    gw = sum(a["realized_win_usd"] for a in with_spec)
    gl = sum(a["realized_loss_usd"] for a in with_spec)
    print(f"  half A — realized from winning tokens : {gw:>20,.0f} USD")
    print(f"  half B — realized from losing  tokens : {gl:>20,.0f} USD")
    print(f"  sum    — net realized                 : {gw + gl:>20,.0f} USD")
    if gl:
        print(f"  profit factor (A / |B|)               : {gw/abs(gl):>20.2f}")
    share = [a["realized_win_usd"]/abs(a["realized_usd"]) for a in with_spec
             if a["realized_usd"] != 0]
    print(f"  per-wallet share of |realized| coming from winners: "
          f"p50={q(share,.50):.3f}  p90={q(share,.90):.3f}")
    both = sum(1 for a in with_spec if a["realized_win_usd"] > 0 and a["realized_loss_usd"] < 0)
    print(f"  wallets carrying BOTH a winning and a losing token: {both:,}")

    # ── J3 ────────────────────────────────────────────────────────────────
    print("\n### J3. realized split in two — round-tripped tokens vs still-held tokens")
    closed = sum(a["realized_closed_usd"] for a in with_spec)
    opened = sum(a["realized_open_usd"] for a in with_spec)
    print(f"  half A — realized on round-tripped tokens (buy AND sell) : {closed:>16,.0f} USD")
    print(f"  half B — realized on non-cycled tokens    (no sell)      : {opened:>16,.0f} USD")
    ghost = [a for a in with_spec if a["realized_usd"] > 0 and a["realized_closed_usd"] <= 0]
    print(f"  wallets profitable with ZERO realized from a closed token: {len(ghost):,}")
    print("    -> the 'realized but never exited' rows that P6_HAS_ROUNDTRIP removes")

    # ── J4 ────────────────────────────────────────────────────────────────
    print("\n### J4. ROI = realized / speculative volume   (= `edge` in the doc)")
    roi = [100 * a["realized_usd"]/a["spec_volume_usd"] for a in with_spec
           if a["spec_volume_usd"] > 0]
    print(f"  lo={min(roi):.2f}%  p25={q(roi,.25):.2f}%  p50={q(roi,.50):.2f}%  "
          f"p75={q(roi,.75):.2f}%  p90={q(roi,.90):.2f}%  hi={max(roi):.2f}%")
    for t in (0.5, 1.0, 2.0, 5.0):
        k = sum(1 for v in roi if v >= t)
        print(f"  ROI >= {t:>4.1f}% : {k:>8,}  ({100*k/max(len(roi),1):5.1f}%)")
    rw = [100*a["realized_usd"]/a["spec_volume_usd"] for a in with_spec
          if a["spec_volume_usd"] > 0 and a["realized_usd"] > 0]
    rl = [100*a["realized_usd"]/a["spec_volume_usd"] for a in with_spec
          if a["spec_volume_usd"] > 0 and a["realized_usd"] < 0]
    print(f"  median ROI — winners p50={q(rw,.50):.2f}%   losers p50={q(rl,.50):.2f}%")
    acc["pnl"] = {"gross_win_usd": gw, "gross_loss_usd": gl, "net_realized_usd": gw + gl,
                  "realized_closed_usd": closed, "realized_open_usd": opened,
                  "roi_p50_pct": round(q(roi, .50), 3),
                  "wallets_total_gt_0": sum(1 for a in with_spec if a["total_usd"] > 0)}


SECTIONS = {
    "structure": sec_structure,
    "stability": sec_stability,
    "wealth": sec_wealth,
    "wallets": sec_wallets,
    "exit": sec_exit,
    "funnel": sec_funnel,
    "axes": sec_axes,
    "pnl": sec_pnl,
    "anomalies": sec_anomalies,
    "coverage": sec_coverage,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?",
                    default=str(Path(__file__).resolve().parent / "wallet.csv"))
    ap.add_argument("--window", choices=WINDOWS, default="30d")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--section", default="all", choices=["all", *SECTIONS])
    ap.add_argument("--json", metavar="PATH", help="dump aggregate summary as JSON")
    args = ap.parse_args()

    with open(args.csv, newline="") as fh:
        rows = list(csv.DictReader(fh))
    print(f"# source : {args.csv}\n# rows   : {len(rows):,}\n# window : {args.window}\n")
    acc: dict = {}
    todo = SECTIONS.values() if args.section == "all" else [SECTIONS[args.section]]
    for fn in todo:
        fn(rows, args, acc)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(acc, fh, indent=2, sort_keys=True)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
