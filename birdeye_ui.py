#!/usr/bin/env python3
"""Birdeye Skills HUB — unified HTTP UI for up to 30 Birdeye discovery & insight skills.

## =========================================================================
## QUICK START · SERVER OPS COMMANDS
## cd to the root skills folder containing birdeye_ui.py FIRST:
##   $ cd /Users/nguyenthenang/nang/birdeye/app/skills
##
## [A] START FOREGROUND (press Ctrl+C to STOP — easiest)
##   $ python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload
##      --host  127.0.0.1 = localhost only      [def] | 0.0.0.0 = expose LAN
##      --port  8765      = default port        [def]
##      --reload          = hot-reload inline HTML/CSS/JS (no process restart
##                          needed when editing _build_ui_html strings)
##      After boot → open http://127.0.0.1:8765/
##   Short defaults:
##      $ python3 birdeye_ui.py                            # port 8765
##      $ python3 birdeye_ui.py --port 8888 --host 0.0.0.0
##
## [B] STOP (when server runs in background / another terminal)
##   $ lsof -i :8765          # Find PID listening on port (column 2)
##   $ lsof -ti:8765 | xargs kill -9     # One-liner force-kill port owner
##   $ pkill -9 -f "birdeye_ui"          # Kill ALL birdeye_ui processes
##   $ lsof -i :8765          # No output = port released (SUCCESS)
##
## [C] BACKGROUND RUN (nohup, log file, PID file — survives terminal close)
##   $ nohup python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload \
##         > /tmp/birdeye-hub.log 2>&1 &
##   $ echo $! > /tmp/birdeye-hub.pid     # Persist PID
##   $ tail -f /tmp/birdeye-hub.log       # Stream logs realtime
##   $ kill $(cat /tmp/birdeye-hub.pid)   # Stop background process
##
## IMPORTANT HOT-RELOAD CAVEAT: --reload ONLY refreshes CSS/JS literals
## inside _build_ui_html().  If you touch Handler.do_GET / do_POST / main /
## argparse / top-level dicts, you MUST perform a FULL server restart
## (kill the old PID, then re-run [A] or [C]).
## =========================================================================

Design goals:
  * Zero npm / pip install (stdlib http.server only). HTML+JS inline 1 file.
  * 30-skill scaffold (sidebar registry). Implemented today:
      Skill #1  Trending List  (birdeye_cli trending-list)
      Skill #3  Token DD      (birdeye_cli token-dd — netflow via overview money_flow include)
      Skill #20 API Key mgmt  (paste + session-only/persist)
    Other 27 skills = WIP cards.
  * Click token row from any discovery → SUGGESTED NEXT-ACTIONS panel (8 cards).
  * Key resolution priority:
      explicit from UI paste (session / localStorage for browser)
      → env BIRDEYE_API_KEY
      → ~/.birdeye.env
      → ~/.config/birdeye/.env
      → birdeye-screener/.env
  * /api/set-key = temporary session key kept in-process; also can save to ~/.birdeye.env.
  * Live-reload on code edit: --reload flag reads UI_HTML source per request from disk.
"""
from __future__ import annotations

import argparse
import html as _html
import http.server
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
# Shared web app: same folder serves the local hub (8765) and the Vercel deploy.
PUBLIC = HERE / "deploy-vercel" / "public"
SKILL_SCREENER = HERE / "birdeye-screener"
# Local UI must use the same bundled CLI as deploy-vercel so format support and
# skill behavior stay in sync between localhost and Vercel.
CLI_PATH = HERE / "deploy-vercel" / "api" / "_cli" / "scripts" / "birdeye_cli.py"
SCREENER_PATH = SKILL_SCREENER / "scripts" / "birdeye_screener.py"
SIMPLE_PATH = SKILL_SCREENER / "scripts" / "birdeye_trending_simple.py"

# Session-only key storage (applied via UI paste → /api/set-key; NOT persisted unless user clicks Save)
_SESSION_KEY: dict[str, str] = {"key": ""}
_SESSION_AI_KEYS: dict[str, str] = {
    "openai": "",
    "anthropic": "",
    "openrouter": "",
    "gemini": "",
}
_AI_PROVIDER_ENV_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}
_AI_PROVIDER_BASE = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}
_AI_PROVIDER_MODEL = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest-20250514",
    "openrouter": "openai/gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
}

ALLOWED_SCRIPTS = {
    "birdeye_cli": str(CLI_PATH),
    "birdeye_screener": str(SCREENER_PATH),
    "birdeye_trending_simple": str(SIMPLE_PATH),
    "stc": str(SKILL_SCREENER / "scripts" / "stc.py"),
}
PY = sys.executable

CLI_CACHE_DIR = pathlib.Path(os.environ.get("BIRDEYE_CACHE_DIR") or
                             (pathlib.Path.home() / ".cache" / "birdeye-skills-runs"))


def _list_cache_items(limit: int = 50) -> list[dict]:
    CLI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    try:
        now = time.time()
        for fp in CLI_CACHE_DIR.glob("*.json"):
            try:
                if not fp.is_file():
                    continue
                m = fp.stat()
                age_h = (now - m.st_mtime) / 3600.0
                if age_h > 48:
                    try:
                        fp.unlink(missing_ok=True)
                    except Exception:
                        pass
                    continue
                raw = json.loads(fp.read_text(encoding="utf-8"))
                kind = raw.get("kind") or "unknown"
                # Backward-compat: old wallet-score cache files had no top-level kind.
                if kind == "unknown" and (raw.get("rendered_rendered") or raw.get("alpha_score") is not None):
                    kind = "wallet-alpha-score-v1"
                params = raw.get("params") or {}
                summary = ""
                score = None
                if kind == "trending-list":
                    summary = f"{params.get('source','?')}·{params.get('interval','?')}·{params.get('sort_by','?')}·{params.get('chain','?')}"
                    n = len(raw.get("rows") or [])
                    detail = f"{n} rows · {params.get('platform') or ''}"
                elif kind == "token-dd":
                    sym = raw.get("symbol") or (params.get("address") or "")
                    chain = params.get("chain", "sol")
                    addrs = params.get("address") or ""
                    summary = f"{chain.upper()} {sym[:16] if sym else ''} {addrs[:8]}…{addrs[-4:]}"
                    sc = raw.get("scores") or {}
                    if "final" in sc:
                        score = float(sc["final"])
                        verdict = sc.get("verdict") or ""
                        detail = f"⭐{score:.1f}/10 {verdict}"
                    else:
                        detail = ""
                elif kind == "smart-wallets":
                    p = params
                    depth = p.get("depth_label") or p.get("depth") or "?"
                    pass_n = raw.get("total_pass") or len(raw.get("results_pass") or [])
                    scan_n = raw.get("total_wallets_scanned") or "?"
                    summary = f"SM · {depth} · {p.get('chain','sol')} · pass≥{p.get('pass_min','?')}"
                    detail = f"✅PASS {pass_n}/{scan_n}"
                elif kind in ("wallet-alpha-score-v1", "wallet-style-v1"):
                    w = params.get("wallet") or ""
                    chain = params.get("chain", "sol")
                    dur = params.get("duration", "?")
                    if kind == "wallet-style-v1":
                        mt = raw.get("main_title") or {}
                        style_label = f"{mt.get('freq','?')}×{mt.get('pnl','?')}"
                        summary = f"🎭 WalletStyle · {chain.upper()} · {dur} · {w[:6]}…{w[-4:] if len(w)>10 else ''}"
                        detail = f"{mt.get('emoji','')} {style_label} {mt.get('zh','')}"
                    else:
                        alpha = raw.get("alpha_score")
                        summary = f"📊 wallet-score · {chain.upper()} · {dur} · {w[:6]}…{w[-4:] if len(w)>10 else ''}"
                        if alpha is not None:
                            try:
                                score = float(alpha)
                                detail = f"⭐alpha {score:.1f}"
                            except Exception:
                                detail = ""
                        else:
                            detail = ""
                elif kind == "kline-pattern-v1":
                    addr = params.get("address") or ""
                    chain = params.get("chain", "sol")
                    res = params.get("resolution", "?")
                    win = params.get("window", "?")
                    pat = raw.get("pattern") or ""
                    label = raw.get("label") or pat
                    sc = raw.get("score")
                    summary = f"🕯️ Kline · {chain.upper()} · {res} {win} · {addr[:6]}…{addr[-4:] if len(addr)>10 else ''}"
                    detail = f"{label}"
                    if sc is not None:
                        try:
                            score = float(sc)
                            detail += f" · {score:.0f}/100"
                        except Exception:
                            pass
                elif kind == "token-trending-score-v1":
                    addr = params.get("address") or ""
                    chain = params.get("chain", "sol")
                    sym = raw.get("symbol") or ""
                    ov = raw.get("overall_trending_score")
                    summary = f"📈 TrendScore · {chain.upper()} · {sym or addr[:8]} · {addr[:6]}…{addr[-4:] if len(addr)>10 else ''}"
                    if ov is not None:
                        try:
                            score = float(ov)
                            detail = f"overall {score:.1f}/100"
                        except Exception:
                            detail = ""
                    else:
                        detail = ""
                elif kind == "contract-dd-v1":
                    addr = params.get("address") or ""
                    chain = params.get("chain", "sol")
                    sym = raw.get("symbol") or ""
                    comp = raw.get("composite")
                    tier = raw.get("tier") or {}
                    summary = f"🛡️ ContractDD · {chain.upper()} · {sym or addr[:6]+'…'+addr[-4:]} · {addr[:6]}…{addr[-4:] if len(addr)>10 else ''}"
                    detail = f"{tier.get('emoji','')} {tier.get('name','')}"
                    if comp is not None:
                        try:
                            score = float(comp)
                            detail += f" · {score:.0f}/100"
                        except Exception:
                            pass
                else:
                    summary = str(fp.stem[:40])
                    detail = ""
                cu = int(raw.get("cu_used_total") or
                         raw.get("payload", {}).get("cu_used_total") or 0)
                items.append({
                    "runId": fp.stem,
                    "kind": kind,
                    "summary": summary,
                    "detail": detail,
                    "score": score,
                    "cu_used_total": cu,
                    "saved_at_unix": int(m.st_mtime),
                    "saved_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(m.st_mtime)),
                    "path": str(fp),
                })
            except Exception:
                continue
    except Exception:
        return items
    items.sort(key=lambda x: x["saved_at_unix"], reverse=True)
    return items[:max(1, int(limit or 50))]


_30_SKILLS_CATALOG = [
    {"cat": "🔥 Discovery (3)", "items": [
        {"id": "tl", "title": "Skill #1 · Trending List", "cu": "30 CU", "status": "live",
         "desc": "/defi/token_trending — hot tokens by volume/rank/liquidity"},
        {"id": "tl_v3", "title": "Skill #1b · V3 Token List", "cu": "50 CU", "status": "live",
         "desc": "/defi/v3/token/list — min_volume filter, trade_count/holders enriched"},
        {"id": "new_pair", "title": "Skill #2 · New Pairs", "cu": "TBD", "status": "wip",
         "desc": "Recently launched tokens sorted by age"},
    ]},
    {"cat": "🛡 Token Due Diligence (5)", "items": [
        {"id": "dd", "title": "Skill #3 · Token DD (Should I Buy?)", "cu": "71 CU", "status": "live",
         "desc": "overview+money_flow+security+SM join → A/B/C/D/F/NG rating (birdeye-dd-workflow step 10)"},
        {"id": "security", "title": "Skill #4 · Security + LP Concentration", "cu": "75 CU", "status": "wip",
         "desc": "token_security + /holder/v1/distribution + /defi/v2/markets join = LP holder% + top50 (step 3/4/9)"},
        {"id": "contract_dd", "title": "Skill #5 · Contract DD", "cu": "86 CU", "status": "live",
         "desc": "Composite 0-100 score: contract safety 45% + holder structure 30% + price action 25%. mint/freeze/LP/taxes + top10 + kline pattern."},
        {"id": "stc", "title": "Skill #6 · Spam Token Cleaner (stc)", "cu": "~70 CU min · 0 holder CU (Web scrape)", "status": "live", "source": "birdeye",
         "desc": "V3 token/list sweep (MC ≥ $1B AND V24h ≤ $50) × solana→robinhood→base→bsc→eth · Web scrape holder top1/top10% (0 Birdeye CU holder cost) + identity batch labels. Final sort: MC desc → Top Wallet Value desc → Liq desc → V24h asc. Export plain / telegram / rendered UI / raw-json."},
        {"id": "compare", "title": "Skill #7 · Multi-Token Compare Rating", "cu": "× N CU", "status": "wip",
         "desc": "side-by-side DD A-F rating of 3-5 tokens"},
    ]},
    {"cat": "🧠 Wallet & Smart Money (7)", "items": [
        {"id": "sm_tokens", "title": "Skill #8 · Smart Money Hot Tokens", "cu": "20 CU", "status": "wip",
         "desc": "/smart-money/v1/token/list — tokens with most SM buying today"},
        {"id": "sm_wallets", "title": "Skill #9 · Smart Money Profile", "cu": "~90 CU", "status": "live",
         "desc": "Single-wallet behavior analysis: 7d/30d performance trend, trading style, TP/SL patterns, copy-trade ROI estimate, 🟢/🟡/🔴 verdict"},
        {"id": "wallet_portfolio", "title": "Skill #10 · Wallet Portfolio", "cu": "10 CU", "status": "wip",
         "desc": "Any address → token holdings + unrealized PnL"},
        {"id": "wallet_style", "title": "Skill #11 · Wallet Style", "cu": "60..90 CU", "status": "live",
         "desc": "Freq × P&L grid + speed subtitle + badges — classify a wallet's trading style."},
        {"id": "wallet_money_flow", "title": "Skill #12 · Wallet Net Flow", "cu": "5 CU", "status": "wip",
         "desc": "Inflow/outflow USD aggregates for a wallet list"},
        {"id": "wallet_score", "title": "Skill #13 · Wallet Score", "cu": "30..110 CU", "status": "live",
         "desc": "4-factor wallet scoring with alpha tier, formula breakdown, and dedicated UI"},
        {"id": "sm_flow_token", "title": "Skill #14 · Wallet Analysis", "cu": "90..180 CU", "status": "live",
         "desc": "Single-wallet deep-dive: profile, assets (current + intervals), trading & PnL by interval, risk metrics (concentration, activeness, open positions)"},
    ]},
    {"cat": "🔐 Security & Risk (5)", "items": [
        {"id": "rug_score", "title": "Skill #15 · Rugpull Risk Score", "cu": "35 CU", "status": "wip",
         "desc": "Security + contract + holder heuristic aggregate"},
        {"id": "lp_check", "title": "Skill #16 · LP Lock Checker", "cu": "5 CU", "status": "wip",
         "desc": "Confirm locked liquidity + unlock date"},
        {"id": "kols", "title": "Skill #17 · KOL / Dev Links", "cu": "0 CU", "status": "wip",
         "desc": "Social/website + CA creator address history"},
        {"id": "rugcheck_risk_audit", "title": "Skill #17b · RugCheck Audit (Live)", "cu": "142 CU", "status": "live", "source":"birdeye",
         "desc": "Same UI format as rugcheck.xyz · 7 risk cards + Liq Min/Max/DD 24h (×1 call 20CU) + Holder list top20 (×1 call 30CU) + insider/dev/sniper/bundle cohorts (×1 call 21CU) — max 3×1-call, total ~142 CU. YES holders default."},
        {"id": "junk_predict", "title": "Skill #23 · Junk Token Prediction (ML)", "cu": "300 CU", "status": "live", "source":"birdeye",
         "desc": "Logistic-regression junk score (0-100) on 16 features. Score ≥ threshold → JUNK. Paste one/many addresses, or Quick Test random 30 from v3 list."},
    ]},
    {"cat": "⛓ Chain & Platform (3)", "items": [
        {"id": "chains", "title": "Skill #18 · Cross-Chain Compare", "cu": "× CU", "status": "wip",
         "desc": "Same trending list across sol/bsc/base/eth side-by-side"},
        {"id": "pf_tokens", "title": "Skill #19 · Platform (pump.fun, moonshot…)", "cu": "50 CU", "status": "wip",
         "desc": "Filter discovery to a launch platform"},
        {"id": "meme_index", "title": "Skill #20 · Meme Index", "cu": "30 CU", "status": "wip",
         "desc": "Track meme basket health + rotation heat"},
    ]},
    {"cat": "📈 History & Charts (5)", "items": [
        {"id": "kline_pattern", "title": "Skill #21 · Kline Pattern", "cu": "25..100 CU", "status": "live",
         "desc": "Classify candlestick pattern + 0..100 score. trend/slope/volatility/drawdown/vol_ratio/up_from_low → 11 patterns."},
        {"id": "trending_score", "title": "Skill #22 · Token Trending Score", "cu": "~171 CU", "status": "live", "source": "birdeye",
         "desc": "0..100 momentum score per interval (5m/15m/30m/1h/4h) from Volume 25% + Price 25% + Liquidity 15% + Holder 20% + Security 15%. Security <40 → hard cap 0.1× (scam-proof). All raw data cached to CSV for backtest/ML tuning."},
        {"id": "price_1y", "title": "Skill #23 · 1Y Price + Benchmarks", "cu": "15 CU", "status": "wip",
         "desc": "ATH/ATL + drawdowns vs SOL/ETH/BTC"},
        {"id": "vol_profile", "title": "Skill #23 · Volume Profile", "cu": "10 CU", "status": "wip",
         "desc": "Historic buy/sell volume distribution"},
        {"id": "corr_map", "title": "Skill #24 · Token Correlation Map", "cu": "N×15", "status": "wip",
         "desc": "Which tokens move together?"},
        {"id": "events", "title": "Skill #25 · Catalyst Events", "cu": "0 CU", "status": "wip",
         "desc": "Upcoming unlock / listing / vesti timeline"},
    ]},
    {"cat": "🤖 Alerts & Bots (2)", "items": [
        {"id": "alert_surge", "title": "Skill #26 · Volume Surge Alert Rule", "cu": "30 CU/hr", "status": "wip",
         "desc": "Generate Telegram webhook payload for poller"},
        {"id": "tg_signal", "title": "Skill #27 · Telegram Signal Pack", "cu": "0 CU", "status": "wip",
         "desc": "Render outputs ready to ```paste``` into Telegram bot"},
    ]},
    {"cat": "⚙ Utils & Settings (2)", "items": [
        {"id": "key", "title": "Skill #28 · API Key", "cu": "0 CU", "status": "live",
         "desc": "Paste key → session / persist to ~/.birdeye.env"},
        {"id": "billing", "title": "Skill #29 · CU Usage Monitor", "cu": "0 CU", "status": "wip",
         "desc": "Track CU/day per skill + budget alerts"},
        {"id": "about", "title": "Skill #30 · About / Docs Links", "cu": "0 CU", "status": "live",
         "desc": "OpenAPI llms.txt + skill source paths"},
    ]},
]


def _load_key_fs() -> str | None:
    if k := os.environ.get("BIRDEYE_API_KEY"):
        return k.strip() or None
    home_alt = pathlib.Path.home() / ".birdeye.env"
    candidates = [
        pathlib.Path.home() / ".config" / "birdeye" / ".env",
        home_alt,
        SKILL_SCREENER / ".env",
    ]
    for cand in candidates:
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


def resolve_key(explicit_from_ui: str | None = None) -> tuple[str, str]:
    """Return (key, source_label)."""
    if explicit_from_ui:
        k = explicit_from_ui.strip().strip('"').strip("'")
        if k:
            return k, "UI paste (session)"
    if _SESSION_KEY["key"]:
        return _SESSION_KEY["key"], "UI session key"
    fs = _load_key_fs()
    if fs:
        return fs, "env / ~/.birdeye.env"
    return "", "MISSING"


def _js_str_escape(s: str) -> str:
    out: list[str] = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "'":
            out.append("\\'")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


# ============================================================
# Inline HTML/JS — multi-skill hub
# ============================================================
def _build_ui_html(skills_catalog) -> str:
    # serialize skill catalog into JSON for frontend sidebar; escape for single-quoted JS string.
    cat_json = _js_str_escape(json.dumps(skills_catalog, ensure_ascii=False))
    return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>🛰 Birdeye Data Skills Hub</title>
<script>
(function(){
  try {
    var t = localStorage.getItem('be.theme') || 'dark';
    document.documentElement.setAttribute('data-theme', t);
  } catch(e) {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
})();
</script>
<link rel="stylesheet" href="/hub.css">
<style>
/* Inline CSS removed for modularity. Edit assets/hub.css instead (hot-reload friendly). */
</style>
</head>
<body>
<header>
  <h1>🛰 Birdeye Data Skills Hub</h1>
  <span class="pill" id="cred">loading…</span>
  <span class="pill" id="ver" title="click to reload UI code from disk (hot reload)" style="cursor:pointer">⏳</span>
  <span id="breadcrumb" class="breadcrumb" style="display:none"></span>
  <span style="flex:1"></span>
  <button class="btn ghost" id="themeToggleBtn" title="Toggle theme (dark default)">☀️</button>
  <button class="btn hubBtn" id="goHubBtn" title="Back to category cards" style="display:none">🏠 Hub</button>
  <button class="btn ghost" id="hotReloadBtn" title="Reload inline HTML from server source">🔁 Hot Reload</button>
  <button class="btn ghost" id="docsBtn" title="Open llms.txt docs">📘 Docs</button>
</header>
<!-- Home view: hidden by default, shown when STATE.mode='home' -->
<div id="homeView" style="display:none"></div>
<main id="drillView">
  <!-- Catalog sidebar (260px) -->
  <aside class="catalog" id="catalog"></aside>

  <!-- Control panel (380px) -->
  <nav class="ctrl" id="ctrl">
    <div class="group" id="g_key">
      <details style="border:1px solid var(--line);border-radius:10px;background:var(--panel)" id="g_key_collapse">
        <summary style="list-style:none;cursor:pointer;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;gap:10px">
          <span style="font-weight:700">🔑 API Key</span>
          <span id="keyInfo" class="subtle" style="font-size:11px;text-align:right"><span class="subtle">Loading key…</span></span>
        </summary>
        <div style="padding:0 12px 12px">
          <div id="keyActions" style="display:none" class="keybox">
            <div class="subtle" style="font-size:12px;margin-bottom:4px">Paste key (32 chars typically):</div>
            <div style="display:flex;gap:6px;align-items:stretch">
              <input id="pasteKey" type="password" placeholder="dc9909a243924571b64f7c65fa2c032f…" style="flex:1;font-family:monospace;font-size:12px;padding:8px 10px;border-radius:8px;background:var(--input-bg);border:1px solid var(--line);color:var(--text);outline:none" />
              <button type="button" class="btn ghost keyEyeBtn" id="pasteKey_eye" title="Show/hide key">👁</button>
            </div>
            <div class="copyrow" style="margin-top:6px">
              <button class="btn primary" id="applySession">Apply · Session only (RAM)</button>
              <button class="btn" id="savePersist">💾 Save to ~/.birdeye.env</button>
              <button class="btn ghost" id="clearKey">Clear session</button>
            </div>
          </div>
        </div>
      </details>
    </div>

    <!-- Dynamic control panel per skill -->
    <div class="group" id="skillCtrl"></div>

    <div class="group">
      <div class="section-title">Quick tests</div>
      <div class="copyrow">
        <button class="btn" data-quick="hot">Trending SOL 1h</button>
        <button class="btn" data-quick="pump">Pump.fun hot</button>
        <button class="btn" data-quick="hee">DD · HeeHaw</button>
        <button class="btn" data-quick="spcx">DD · SPCX (SM #1)</button>
      </div>
    </div>

    <div class="group" id="nextActionsWrap" style="display:none">
      <div class="section-title">⚡ Next Actions for selected token</div>
      <div id="selToken" class="subtle"></div>
      <div class="nextactions" id="nextActions"></div>
    </div>
  </nav>

  <!-- Output (column 3 = col 3 from left: Installation pinned top full-height + out scroll independently) -->
  <section class="outWrap">
    <div id="installColTop" class="installColTop"></div>
    <section class="out"><div id="out"></div></section>
    <aside class="histCol" id="histCol">
      <div class="group" style="padding:10px 12px">
        <details open style="border:1px solid var(--line);border-radius:10px;background:var(--panel)">
          <summary style="list-style:none;cursor:pointer;padding:10px 12px;display:flex;align-items:center;gap:10px">
            <label style="margin:0;cursor:pointer">📜 Recent runs</label>
            <span style="margin-left:auto" class="subtle" id="histCount">0</span>
          </summary>
          <div style="padding:0 12px 12px">
            <div class="copyrow" style="margin-bottom:10px">
              <button class="btn ghost" onclick="refreshHistory()">⟳ Refresh</button>
              <button class="btn ghost" id="histClearOld" title="Clear runs older than 24h from disk">🗑 Clear old</button>
            </div>
            <div id="historyList" class="historyList"></div>
          </div>
        </details>
      </div>
    </aside>
  </section>
<!-- AI chat widget (feature flag off — lean UI by default)
<div id="chatFloatingRoot" style="position:fixed;right:20px;bottom:20px;z-index:99999">
  <div id="chatBox" style="display:none;width:360px;height:540px;position:absolute;right:0;bottom:72px;background:var(--bg);border:1px solid var(--line);border-radius:16px;box-shadow:0 14px 48px rgba(0,0,0,.4);flex-direction:column;overflow:hidden">
    <div style="padding:12px 14px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px;background:var(--grad-a)">
      <span style="font-size:18px">🤖</span>
      <div style="flex:1"><b style="font-size:13px;color:#fff">Birdeye AI Copilot</b>
      <div style="font-size:10px;color:rgba(255,255,255,.72)">BYO Key · Ask to run skills</div></div>
      <button id="chatCloseBtn" style="background:transparent;border:none;color:rgba(255,255,255,.85);cursor:pointer;font-size:15px;padding:4px 8px;border-radius:6px">✕</button>
    </div>
    <div id="chatMsgs" style="flex:1;overflow-y:auto;padding:12px;font-size:12.5px;display:flex;flex-direction:column;gap:10px">
      <div style="background:var(--card);border:1px solid var(--line);border-radius:12px 12px 12px 3px;padding:10px 12px;align-self:flex-start;max-width:92%;line-height:1.5">
        <b style="color:var(--accent)">🤖 Ready.</b> Ask to run any skill. Examples:<br>
        <i style="color:var(--mute)">• "Run trending list on Solana 1h"</i><br>
        <i style="color:var(--mute)">• "Token DD for ADDRESS"</i><br>
        <i style="color:var(--mute)">• "Show smart traders (skill #9)"</i>
      </div>
    </div>
    <div id="chatPrefillBanner" style="display:none;margin:0 10px;padding:8px 10px;background:rgba(124,58,237,.1);border:1px solid rgba(124,58,237,.35);border-radius:10px;font-size:11.5px;color:var(--accent)"></div>
    <div style="padding:10px 12px;border-top:1px solid var(--line);display:flex;gap:6px">
      <input id="chatInput" type="text" placeholder="Chat with your LLM..." style="flex:1;font-size:12.5px;padding:9px 12px;border-radius:10px;background:var(--input-bg);border:1px solid var(--line);color:var(--text);outline:none" />
      <button id="chatSendBtn" class="btn primary" style="padding:0 14px">⮕</button>
    </div>
  </div>
  <button id="chatToggleBtn" style="width:58px;height:58px;border-radius:50%;background:var(--grad-a);border:none;color:#fff;font-size:24px;cursor:pointer;box-shadow:0 8px 24px rgba(79,70,229,.45);display:flex;align-items:center;justify-content:center">💬</button>
</div>
-->
</main>
<script>
// Dynamic skill catalog (injected at render time; hot-reload via python).
window.CATALOG_JSON_RAW = '""" + cat_json + r"""';
</script>
<script defer src="/hub.js?v=4"></script>
</body>
</html>
"""

UI_HTML = _build_ui_html(_30_SKILLS_CATALOG)


def run_script_argv(script_alias: str, argv: list[str], ui_key: str | None = None):
    if script_alias not in ALLOWED_SCRIPTS:
        return {"exit": 2, "stdout": "", "stderr": f"script not allowed: {script_alias}", "duration_ms": 0}
    script_path = ALLOWED_SCRIPTS[script_alias]
    for tok in argv:
        if isinstance(tok, str) and any(c in tok for c in ";&|`$<>\\\n'\""):
            return {"exit": 2, "stdout": "", "stderr": f"invalid token: {tok!r}", "duration_ms": 0}

    resolved_key, _src = resolve_key(ui_key)
    sub_env = dict(os.environ)
    if resolved_key:
        sub_env["BIRDEYE_API_KEY"] = resolved_key

    cmd = [PY, script_path, *argv]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=str(HERE), capture_output=True, text=True, timeout=180,
            env=sub_env,
        )
        dur = int((time.perf_counter() - t0) * 1000)
        return {
            "exit": int(proc.returncode),
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "duration_ms": dur,
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired:
        return {"exit": 124, "stdout": "", "stderr": "timeout 180s", "duration_ms": 180000, "cmd": cmd}
    except Exception as e:
        return {"exit": 1, "stdout": "", "stderr": str(e), "duration_ms": 0, "cmd": cmd}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "BirdeyeSkillsHub/1.0"
    hot_reload: bool = False

    def log_message(self, fmt, *args):
        sys.stderr.write("[UI] " + (fmt % args) + "\n")

    def _html_current(self) -> bytes:
        if Handler.hot_reload:
            try:
                src = pathlib.Path(__file__).read_text(encoding="utf-8")
                # Re-evaluate _build_ui_html by re-exec-ing constant is too heavy; cheap way: use
                # module globals already populated. For truly live, re-read is just for sanity;
                # we re-import function via a trick: exec inline builder each request? No, simpler:
                # re-build from scratch using catalog literal. That refreshes JS string too.
                return _build_ui_html(_30_SKILLS_CATALOG).encode("utf-8")
            except Exception as e:
                sys.stderr.write(f"[UI] hot-reload read fail: {e}\n")
                return UI_HTML.encode("utf-8")
        return UI_HTML.encode("utf-8")

    def _send_json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, code, html_bytes):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html_bytes)

    def do_OPTIONS(self): self._send_json(204, {})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path in ("/", "/index.html", "/home.html", "/test", "/test.html"):
            html_p = PUBLIC / "test.html"
            try:
                data = html_p.read_bytes()
            except Exception as e:
                data = f"<html><body><pre>read test.html fail: {e}</pre></body></html>".encode("utf-8")
            self._send_html(200, data)
            return
        if parsed.path in ("/detail", "/detail.html"):
            html_p = PUBLIC / "detail.html"
            try:
                data = html_p.read_bytes()
            except Exception as e:
                data = f"<html><body><pre>read detail.html fail: {e}</pre></body></html>".encode("utf-8")
            self._send_html(200, data)
            return
        if parsed.path == "/health":
            self._send_json(200, {"ok": True, "cwd": str(HERE), "hot_reload": Handler.hot_reload,
                                   "cacheDir": str(CLI_CACHE_DIR)})
            return
        if parsed.path == "/api/catalog":
            self._send_json(200, {"items": _30_SKILLS_CATALOG, "total": sum(len(g.get("items") or []) for g in _30_SKILLS_CATALOG)})
            return
        # R9: Serve modular static assets (CSS/JS extracted to separate files for easy edit)
        if parsed.path in ("/hub.css", "/assets/hub.css"):
            css_p = PUBLIC / "hub.css"
            try:
                data = css_p.read_bytes() if css_p.exists() else b"/* hub.css missing, run extract step */"
            except Exception as e:
                data = f"/* read hub.css fail: {e} */".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path in ("/hub.js", "/assets/hub.js"):
            js_p = PUBLIC / "hub.js"
            try:
                data = js_p.read_bytes() if js_p.exists() else b"/* hub.js missing, run extract step */"
            except Exception as e:
                data = f"/* read hub.js fail: {e} */".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/api/key-info":
            k, src = resolve_key()
            h2 = k[:2] if k else ""
            t2 = k[-2:] if k else ""
            mask = f"{h2}****{t2}" if k else ""
            self._send_json(200, {"key_set": bool(k), "source": src, "head": h2, "tail": t2, "mask": mask, "hot": Handler.hot_reload})
            return
        if parsed.path == "/api/ai-key-info":
            results: dict = {}
            env_path = pathlib.Path.home() / ".birdeye.env"
            env_lines: list[str] = []
            if env_path.exists():
                try:
                    env_lines = env_path.read_text(encoding="utf-8").splitlines()
                except Exception:
                    env_lines = []
            env_file_map: dict[str, str] = {}
            for ln in env_lines:
                s = ln.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, _, v = s.partition("=")
                env_file_map[k.strip()] = v.strip().strip('"').strip("'")
            for p, env_name in _AI_PROVIDER_ENV_MAP.items():
                sess_k = _SESSION_AI_KEYS.get(p, "") or ""
                env_k = os.environ.get(env_name, "") or ""
                file_k = env_file_map.get(env_name, "") or ""
                k_val = sess_k or env_k or file_k
                src = "session" if sess_k else ("env" if env_k else ("birdeye.env" if file_k else ""))
                if len(k_val) >= 4:
                    h2, t2 = k_val[:2], k_val[-2:]
                elif k_val:
                    h2, t2 = k_val[:2], k_val[:2] if len(k_val) >= 2 else (k_val, k_val)
                else:
                    h2, t2 = "", ""
                results[p] = {
                    "key_set": bool(k_val),
                    "source": src,
                    "head": h2,
                    "tail": t2,
                    "mask": f"{h2}****{t2}" if k_val else "",
                }
            self._send_json(200, {"providers": results})
            return
        if parsed.path == "/api/history/list":
            limit = int(qs.get("limit", ["50"])[0])
            items = _list_cache_items(limit=limit)
            self._send_json(200, {"items": items, "cacheDir": str(CLI_CACHE_DIR)})
            return
        if parsed.path == "/api/history/render":
            run_id = (qs.get("runId") or qs.get("run_id") or [""])[0]
            fmt = (qs.get("format") or ["ui"])[0].lower()
            if not run_id:
                self._send_json(400, {"error": "runId required"})
                return
            fmt_map = {
                "ui": "render",
                "plain": "plain",
                "telegram": "telegram",
                "json": "raw-json",
                # backward-compatible aliases
                "render": "render",
                "raw-json": "raw-json",
                "rendered": "render",
                "scorecard": "render",
            }
            cli_fmt = fmt_map.get(fmt, "render")
            argv = ["history-render", "--run-id", run_id, "--format", cli_fmt]
            res = run_script_argv("birdeye_cli", argv, None)
            # if UI requested renderer payload: return JSON directly (stdout)
            if cli_fmt == "render":
                out_obj = {"success": False, "cached": True, "cu_used_total": 0}
                if res.get("exit") == 0 and (res.get("stdout") or "").strip():
                    try:
                        out_obj = json.loads(res["stdout"].strip())
                    except Exception as e:
                        out_obj["error"] = f"parse render JSON fail: {e}"
                        out_obj["raw"] = res.get("stdout", "")[:1000]
                else:
                    out_obj["error"] = res
                self._send_json(200 if out_obj.get("payload") else 500, out_obj)
                return
            # Plain / Telegram / JSON => return text envelope
            self._send_json(200, {"runId": run_id, "format": fmt, "exit": res.get("exit"),
                                   "stdout": res.get("stdout", ""), "stderr": res.get("stderr", ""),
                                   "duration_ms": res.get("duration_ms", 0)})
            return
        if parsed.path == "/api/history/delete":
            run_id = (qs.get("runId") or qs.get("run_id") or [""])[0]
            if not run_id:
                self._send_json(400, {"error": "runId required"})
                return
            CLI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in run_id)
            fp = CLI_CACHE_DIR / f"{safe}.json"
            deleted = False
            if fp.exists():
                try:
                    fp.unlink()
                    deleted = True
                except Exception:
                    pass
            self._send_json(200, {"ok": True, "deleted": deleted, "runId": run_id, "path": str(fp)})
            return
        # ---------- Aggregate composite endpoints (/api/v1/*) ----------
        # Design doc: /API/14-aggregate-endpoints.md (CU tables / invariants / curl examples)
        # STUB PHASE: returns skeleton JSON shape with correct meta.cu_breakdown labels
        #            + meta.include_flags + meta.include_flags_skipped rollback semantics.
        #            Real Birdeye micro-API fan-out is TBD. Routing / cache-key tuple
        #            invariant checks are testable today.
        if parsed.path.startswith("/api/v1/"):
            import time as _t
            now = int(_t.time())
            chain = (qs.get("chain") or ["sol"])[0].lower()
            def _split_csv(name):
                raw = (qs.get(name) or qs.get(name + "[]") or [""])[0]
                return [tok.strip() for tok in raw.split(",") if tok.strip()]
            # 1. /trending/simple  (flat 30 CU)
            if parsed.path.endswith("/trending/simple"):
                interval = (qs.get("interval") or ["24h"])[0].lower()
                try: limit = int((qs.get("limit") or ["40"])[0])
                except Exception: limit = 40
                self._send_json(200, {
                    "api_version": "v1",
                    "kind": "trending-simple",
                    "fetched_at_unix": now,
                    "meta": {
                        "chain": chain, "interval": interval,
                        "limit_requested": limit, "rows_returned": 0,
                        "cu_billed_total": 30,
                        "cu_breakdown": {
                            "trending_v1_fetch": 30,
                            "include_extra_fields": 0,
                            "fanout_parallel_price_batch": 0,
                            "client_filter_cull_count": 0,
                            "refunded_rollback": 0,
                        },
                        "include_flags": [],
                        "include_flags_skipped": [],
                        "pipeline_gap_rows": 0,
                        "upstream_birdeye_trace_ids": [],
                        "note_stub_phase": True,
                    },
                    "rows": [],
                })
                return
            # 2. /trending/v3  (base 50, +extra_fields=12, +security_shallow=18)
            if parsed.path.endswith("/trending/v3"):
                includes = _split_csv("include")
                cu_base = 50
                cu_extra = 12 if "extra_fields" in includes else 0
                cu_sec = 18 if "security_shallow" in includes else 0
                valid = {"extra_fields", "security_shallow"}
                try: limit = int((qs.get("limit") or ["40"])[0])
                except Exception: limit = 40
                self._send_json(200, {
                    "api_version": "v1",
                    "kind": "trending-v3",
                    "fetched_at_unix": now,
                    "meta": {
                        "chain": chain,
                        "limit_requested": limit,
                        "rows_returned": 0,
                        "cu_billed_total": cu_base + cu_extra + cu_sec,
                        "cu_breakdown": {
                            "v3_list_fetch": cu_base,
                            "extra_fields_enrich": cu_extra,
                            "security_shallow": cu_sec,
                            "filter_cull": 0,
                            "refunded_rollback": 0,
                        },
                        "include_flags": [i for i in includes if i in valid],
                        "include_flags_skipped": [i for i in includes if i not in valid],
                        "pipeline_gap_rows": 0,
                        "upstream_birdeye_trace_ids": [],
                        "note_stub_phase": True,
                    },
                    "rows": [],
                })
                return
            # 3. /token/dd   +   4. /token/rugcheck
            # Identical call graph + identical CU (BASE 71 + list 30 / advsec 21 / risk_hist 30)
            if parsed.path.endswith("/token/dd") or parsed.path.endswith("/token/rugcheck"):
                is_rug = parsed.path.endswith("/token/rugcheck")
                addr = (qs.get("address") or [""])[0].strip()
                includes = _split_csv("include")
                _VALID = {"list", "advanced_security", "risk_history"}
                _ADDER = {"list": 30, "advanced_security": 21, "risk_history": 30}
                flags_ok = [i for i in includes if i in _VALID]
                flags_skip = [i for i in includes if i not in _VALID]
                cu_base = 71
                cu_list = _ADDER["list"] if "list" in flags_ok else 0
                cu_adv  = _ADDER["advanced_security"] if "advanced_security" in flags_ok else 0
                cu_hist = _ADDER["risk_history"] if "risk_history" in flags_ok else 0
                cu_total = cu_base + cu_list + cu_adv + cu_hist
                kind = "rugcheck-risk-audit" if is_rug else "token-dd"
                try: list_top_n = int((qs.get("list_top_n") or ["20"])[0])
                except Exception: list_top_n = 20
                try: hist_pts = int((qs.get("history_points") or ["30"])[0])
                except Exception: hist_pts = 30
                meta = {
                    "chain": chain, "address": addr, "symbol": "", "name": "", "logo": "", "decimals": 0,
                    "cu_billed_total": cu_total,
                    "cu_breakdown": {
                        "base": cu_base, "list": cu_list, "advanced_security": cu_adv,
                        "risk_history": cu_hist, "refunded_rollback": 0,
                    },
                    "include_flags": flags_ok,
                    "include_flags_skipped": flags_skip,
                    "flags_skipped_reasons": {i: "unknown include token" for i in flags_skip},
                    "risk_history_points_requested": hist_pts if "risk_history" in flags_ok else 0,
                    "list_top_n_requested": list_top_n if "list" in flags_ok else 0,
                    "tag_cohort_interpolate": True,
                    "upstream_birdeye_trace_ids": [],
                    "note_stub_phase": True,
                }
                out = {"api_version": "v1", "kind": kind, "fetched_at_unix": now, "meta": meta}
                out["price_mc_liq"] = {
                    "price_usd": 0, "mc": 0, "fdv_mc_ratio": 0, "liquidity_usd_current": 0,
                    "holders_total": 0, "traders_unique_24h": 0,
                    "pct_change_1m":0,"pct_change_5m":0,"pct_change_15m":0,"pct_change_30m":0,
                    "pct_change_1h":0,"pct_change_2h":0,"pct_change_4h":0,"pct_change_8h":0,"pct_change_24h":0,
                }
                out["volume_24h"] = {
                    "v24h_usd":0,"buys_count_24h":0,"sells_count_24h":0,
                    "buy_usd_24h":0,"sell_usd_24h":0,"net_flow_usd_24h":0,
                    "buy_ratio_24h":0.5,"wallet_ratio_24h":0.5,
                }
                out["money_flow_32"] = []
                out["security"] = {
                    "creator_pct":0,"top10_holder_pct":0,"top10_user_pct":0,
                    "lp_locked":False,"mutable_metadata":False,"freeze_authority":False,
                    "owner_address":"","mint_authority_renounced_sol":True,"is_honeypot_evm_only":None,
                }
                out["smart_market"] = {"in_sm_top20":False,"rank_in_sm_top100":None,"smart_traders_no":0}
                out["score_pillars_0_10"] = {"sec":0,"smkt":0,"act":0,"vol":0}
                out["score_final_0_10"] = 0
                out["rating"] = "NG"
                out["verdict"] = "STUB PHASE — run CLI for real data"
                if "list" in flags_ok:
                    out["holder_list_meta"] = {"requested_top_n": meta["list_top_n_requested"], "returned_rows": 0, "sum_pct_checked_vs_security_top10": 0}
                    out["lp_concentration_pct"] = {"top_2_holders_pct_sum":0,"top_10_holders_pct_sum":0,"top_20_holders_pct_sum":0,"known_cex_or_burn_pct":0}
                    out["holder_list"] = []
                if "advanced_security" in flags_ok:
                    out["liq_stats"] = {"current":0,"min_24h":0,"max_24h":0,"drawdown_pct_24h":0,"lp_holder_concentration_pct":None}
                    out["holder_24h_delta"] = {"delta_abs":0,"delta_pct":0}
                    out["trader_24h_delta"] = {"delta_abs":0,"delta_pct":0}
                    out["tag_cohorts"] = []
                    out["bot_proxy"] = {"bot_trade_pct_24h":0,"bot_volume_pct_24h":0}
                    out["fee_mint_burn_events_24h"] = []
                if "risk_history" in flags_ok:
                    out["risk_score_daily"] = []
                if is_rug:
                    out["rug_summary_13_fields"] = {"tier_0_10_label": "LOW", "rug_score_0_10": 0}
                    out["risk_cards"] = [
                        {"id":"Mint","label":"Mint authority","level":"ok","detail":"Renounced"},
                        {"id":"Liq","label":"Liquidity 24h drawdown","level":"ok","detail":"Stub — no fan-out yet"},
                        {"id":"Honeypot","label":"Honeypot check","level":"ok","detail":"Stub — no fan-out yet"},
                        {"id":"DevHold","label":"Dev / creator hold%","level":"ok","detail":"Stub — no fan-out yet"},
                        {"id":"Top10Conc","label":"Top-10 holder concentration","level":"ok","detail":"Stub — no fan-out yet"},
                        {"id":"TagCohort","label":"Tag cohort% (Sniper/Smart/KOL/Bundler/Dev)","level":"ok","detail":"Stub — no fan-out yet"},
                        {"id":"BotWash","label":"Bot wash proxy (trades% vs volume%)","level":"ok","detail":"Stub — no fan-out yet"},
                    ]
                self._send_json(200, out)
                return
            # Unknown /api/v1/* route
            self._send_json(404, {
                "error": "unknown aggregate endpoint. See /API/14-aggregate-endpoints.md",
                "available": [
                    "/api/v1/trending/simple",
                    "/api/v1/trending/v3",
                    "/api/v1/token/dd",
                    "/api/v1/token/rugcheck",
                ],
            })
            return
        # Static file: shared web app (/assets/*) + design docs (/API/*, /docs/*)
        _p = parsed.path
        _MIME_MAP = {
            ".md": "text/markdown; charset=utf-8",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }
        if _p == "/catalog.json":
            _fp = PUBLIC / "catalog.json"
        elif _p.startswith("/assets/"):
            _fp = PUBLIC / _p.lstrip("/").replace("..", "_")
        elif _p.startswith("/API/") or _p.startswith("/docs/") or _p.startswith("/birdeye-screener/assets/"):
            _fp = HERE / _p.lstrip("/").replace("..", "_")
        else:
            _fp = None
        if _fp is not None:
            try:
                _fp_resolved = _fp.resolve(strict=True)
            except Exception:
                self._send_json(404, {"error": "static not found"})
                return
            # Security: must stay inside the served roots
            try:
                _fp_resolved.relative_to(PUBLIC if _p.startswith("/assets/") or _p == "/catalog.json" else HERE)
            except Exception:
                self._send_json(403, {"error": "forbidden"})
                return
            if not _fp_resolved.is_file():
                self._send_json(404, {"error": "static not a file"})
                return
            _ext = _fp_resolved.suffix.lower()
            _mime = _MIME_MAP.get(_ext, "application/octet-stream")
            try:
                _data = _fp_resolved.read_bytes()
            except Exception:
                self._send_json(500, {"error": "read fail"})
                return
            self.send_response(200)
            self.send_header("Content-Type", _mime)
            self.send_header("Content-Length", str(len(_data)))
            # No cache for markdown docs (frequently edited); short cache for images
            if _ext == ".md" or _p == "/catalog.json":
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            else:
                self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(_data)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._send_json(400, {"error": f"bad json: {e}"})
            return
        if parsed.path == "/api/run":
            script = body.get("script") or "birdeye_cli"
            argv = body.get("argv") or []
            if not isinstance(argv, list):
                self._send_json(400, {"error": "argv must be list"})
                return
            ui_key = body.get("uiKey") or None
            res = run_script_argv(script, [str(a) for a in argv], ui_key)
            self._send_json(200, res)
            return
        if parsed.path == "/api/set-key":
            action = body.get("action") or "apply"
            val = (body.get("key") or "").strip().strip('"').strip("'")
            if action == "apply":
                _SESSION_KEY["key"] = val
                if val:
                    _h2, _t2 = val[:2], val[-2:]
                    self._send_json(200, {"ok": True, "message": f"session key set: {_h2}****{_t2}"})
                else:
                    self._send_json(200, {"ok": True, "message": "session key cleared"})
                return
            if action == "clear":
                _SESSION_KEY["key"] = ""
                self._send_json(200, {"ok": True, "message": "session key cleared"})
                return
            if action == "save":
                if not val:
                    self._send_json(400, {"error": "empty key"})
                    return
                target = pathlib.Path.home() / ".birdeye.env"
                existing = target.read_text(encoding="utf-8") if target.exists() else ""
                # strip old entries with same key
                lines = [ln for ln in existing.splitlines() if not ln.strip().startswith("BIRDEYE_API_KEY=")]
                lines.append(f"BIRDEYE_API_KEY={val}")
                target.write_text("\n".join(lines) + "\n", encoding="utf-8")
                target.chmod(0o600)
                _SESSION_KEY["key"] = val
                self._send_json(200, {"ok": True, "message": f"saved to {target} (chmod 600). Head={val[:2]}****{val[-2:]}"})
                return
            self._send_json(400, {"error": f"unknown action: {action}"})
            return
        if parsed.path == "/api/set-ai-key":
            provider = (body.get("provider") or "").lower().strip()
            action = body.get("action") or "apply"
            val = (body.get("key") or "").strip().strip('"').strip("'")
            if provider not in _AI_PROVIDER_ENV_MAP:
                self._send_json(400, {"error": f"unknown provider. Valid: {list(_AI_PROVIDER_ENV_MAP.keys())}"})
                return
            env_name = _AI_PROVIDER_ENV_MAP[provider]
            def _ht(v):
                if len(v) >= 4:
                    return v[:2], v[-2:]
                if v:
                    return (v[:2], v[:2]) if len(v) >= 2 else (v, v)
                return "", ""
            if action == "apply":
                _SESSION_AI_KEYS[provider] = val
                if val:
                    _h2, _t2 = _ht(val)
                    self._send_json(200, {"ok": True, "message": f"[{provider}] session: {_h2}****{_t2}"})
                else:
                    self._send_json(200, {"ok": True, "message": f"[{provider}] session cleared"})
                return
            if action == "clear":
                _SESSION_AI_KEYS[provider] = ""
                self._send_json(200, {"ok": True, "message": f"[{provider}] session cleared"})
                return
            if action == "save":
                if not val:
                    self._send_json(400, {"error": "empty key"})
                    return
                target = pathlib.Path.home() / ".birdeye.env"
                existing = target.read_text(encoding="utf-8") if target.exists() else ""
                lines = [ln for ln in existing.splitlines() if not ln.strip().startswith(f"{env_name}=")]
                lines.append(f"{env_name}={val}")
                target.write_text("\n".join(lines) + "\n", encoding="utf-8")
                target.chmod(0o600)
                _SESSION_AI_KEYS[provider] = val
                _h2, _t2 = _ht(val)
                self._send_json(200, {"ok": True, "message": f"[{provider}] saved to {target} (chmod 600). {_h2}****{_t2}"})
                return
            self._send_json(400, {"error": f"unknown action: {action}"})
            return
        self._send_json(404, {"error": "not found"})


def serve(port: int, host: str, hot: bool):
    Handler.hot_reload = hot
    srv = http.server.HTTPServer((host, port), Handler)
    sys.stderr.write(f"[UI] 🛰 Birdeye Data Skills Hub (32 skills) → http://{host}:{port}\n")
    sys.stderr.write(f"[UI] hot reload: {'ON (read UI_HTML per request)' if hot else 'OFF'}\n")
    sys.stderr.write(f"[UI] cwd scripts root: {HERE}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[UI] stopped.\n")
        srv.server_close()


def headTail(s, h=6, t=4):
    if not s: return ""
    if len(s) <= h+t+3: return s
    return s[:h] + "…" + s[-t:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--reload", action="store_true", help="Re-render inline HTML every request (hot code edit).")
    args = ap.parse_args()
    serve(args.port, args.host, hot=args.reload)


if __name__ == "__main__":
    main()
