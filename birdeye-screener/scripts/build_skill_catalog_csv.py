#!/usr/bin/env python3
"""Build revised skills catalog CSV matching the standard 10-column marketplace CSV format.

Output:
  /Users/nguyenthenang/nang/birdeye/app/skills/birdeye-screener/Birdeye Data Skills - skills-builtin-revised.csv

Columns (10 match marketplace 48 skills template header):
  skill name, display title, trader question, description, category, stage, difficulty, core_calls, core_capabilities, example_prompts

Rows:
  Rows 1-2   comment lines (#) summary stats
  Header     10 column names
  Rows 1-31  BUILTIN (from _30_SKILLS_CATALOG 8 groups, 31 skills)
  Rows 32-48 BACKLOG = marketplace 48 skills not matched to builtin (17 rows) stage=BACKLOG
"""

from __future__ import annotations
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)   # birdeye-screener/
SKILLS_ROOT = os.path.dirname(ROOT)  # /app/skills/

MARKETPLACE_CSV = os.path.join(ROOT, "Birdeye Data Skills - marketplace-catalog.csv")
OUT_CSV = os.path.join(ROOT, "Birdeye Data Skills - skills-builtin-revised.csv")

# Category map 8 local groups → 5 marketplace category values
CAT_MAP = {
    "🔥 Discovery (3)": "Discovery",
    "🛡 Token Due Diligence (5)": "Token Analysis",
    "🧠 Wallet & Smart Money (7)": "Wallet Intelligence",
    "🔐 Security & Risk (3)": "Token Analysis",
    "⛓ Chain & Platform (3)": "Data Analytics",
    "📈 History & Charts (5)": "Data Analytics",
    "🤖 Alerts & Bots (2)": "Monitor",
    "⚙ Utils & Settings (2)": "Utils",
    "⚙ Utils & Settings (3)": "Utils",
}

STAGE_MAP = {
    "🔥 Discovery (3)": "DISCOVER",
    "🛡 Token Due Diligence (5)": "DECIDE",
    "🧠 Wallet & Smart Money (7)": "RESEARCH",
    "🔐 Security & Risk (3)": "RESEARCH",
    "⛓ Chain & Platform (3)": "DISCOVER",
    "📈 History & Charts (5)": "RESEARCH",
    "🤖 Alerts & Bots (2)": "MONITOR",
    "⚙ Utils & Settings (2)": "UTILS",
    "⚙ Utils & Settings (3)": "UTILS",
}

DIFFICULTY_MAP = {
    "tl": "Basic", "tl_v3": "Intermediate", "new_pair": "Basic",
    "dd": "Advanced", "security": "Advanced", "contract_dd": "Advanced", "holders": "Advanced", "compare": "Advanced",
    "sm_tokens": "Intermediate", "sm_wallets": "Advanced", "wallet_portfolio": "Basic",
    "wallet_style": "Intermediate", "wallet_money_flow": "Intermediate", "copy_trade": "Advanced", "wallet_analysis": "Advanced",
    "rug_score": "Advanced", "lp_check": "Basic", "kols": "Basic",
    "chains": "Advanced", "pf_tokens": "Intermediate", "meme_index": "Intermediate",
    "kline_pattern": "Intermediate",
    "price_1y": "Intermediate", "vol_profile": "Advanced", "corr_map": "Advanced", "events": "Basic",
    "alert_surge": "Intermediate", "tg_signal": "Basic",
    "key": "Basic", "billing": "Intermediate", "about": "Basic",
}

CORE_CALLS_MAP = {
    "tl": "defi/token_trending",
    "tl_v3": "defi/v3/token/list",
    "new_pair": "market/new-listings, market launchpad-new",
    "dd": "token_overview?includes=money_flow, token_security, smart-money/v1/token/list",
    "security": "token_security, holder/v1/distribution, defi/v2/markets",
    "contract_dd": "token_overview, token_security, holder/v1/distribution, defi/v3/ohlcv (GMGN contract-dd port)",
    "holders": "holder/v1/distribution, token/v1/holder-profile, defi/v2/tokens/top_traders",
    "compare": "N × token-dd",
    "sm_tokens": "smart-money/v1/token/list",
    "sm_wallets": "wallet/v2/pnl/summary (7d+30d), wallet/v2/pnl/details, wallet/v1/tx_list, optional wallet/v2/tx/first-funded",
    "wallet_portfolio": "wallet/v1/holdings",
    "wallet_style": "wallet/v2/pnl/summary, wallet/v2/pnl/details, optional wallet/v1/tx_list (GMGN wallet-style port)",
    "wallet_money_flow": "wallet/v1/net-flow",
    "copy_trade": "wallet-score run (plan)",
    "wallet_analysis": "wallet/v2/pnl/summary × intervals, wallet/v2/pnl/details, wallet/v2/current-net-worth, wallet/v1/tx_list, wallet/v2/tx/first-funded",
    "rug_score": "token_security, holder/v1/distribution, heuristic aggregate",
    "lp_check": "token_security (lpLocked)",
    "kols": "token_overview (creator address + social)",
    "chains": "multi-chain defi/token_trending × chains",
    "pf_tokens": "market launchpad-trending (pump.fun, moonshot…)",
    "meme_index": "market trending + token basket aggregate",
    "kline_pattern": "defi/v3/ohlcv → 6 numbers → 11 patterns → 0..100 score (GMGN gmgn-kline-pattern port)",
    "price_1y": "market kline (1y, 1d-resolution)",
    "vol_profile": "market kline + trades aggregate",
    "corr_map": "multi-token market kline cross-correlation (N × 15 CU)",
    "events": "unlock/vesting off-chain (reference)",
    "alert_surge": "volume-5m poller + webhook",
    "tg_signal": "client-side render only",
    "key": "client-side session + ~/.birdeye.env persist",
    "billing": "client-side history /api/key-info",
    "about": "client-side docs links",
}

PROMPTS_MAP = {
    "tl": "Show me the hottest Solana tokens by 5-minute volume today.; Find trending tokens with ≥$25K liquidity and ≥$10K 5m volume.",
    "tl_v3": "Rank the latest V3 token list filtering min_volume ≥1000 and holders ≥200.",
    "new_pair": "What new pairs launched on Solana in the last 6 hours across all launchpads?",
    "dd": "Run full Birdeye due-diligence for <TOKEN_ADDRESS> and give me A/F research priority.; Should I buy this token? Run DD first: <ADDR>.",
    "security": "What are the observable security and holder concentration risks for <TOKEN_ADDRESS>?",
    "contract_dd": "Run Contract DD for <TOKEN_ADDRESS> — composite safety/holders/price score.",
    "holders": "Who are the top 20 holders for <TOKEN_ADDRESS>? Show tag% and BotProxy.",
    "compare": "Side-by-side DD rating of 3 tokens: <A>, <B>, <C>.",
    "sm_tokens": "What tokens are most Smart Money buying today on Birdeye SM list?",
    "sm_wallets": "Analyze this wallet's trading behavior: style, take-profit/stop-loss, copy-trade ROI, and copy/avoid verdict: <WALLET_ADDRESS>.",
    "wallet_portfolio": "Show current holdings + unrealized PnL for wallet <WALLET_ADDRESS>.",
    "wallet_style": "Classify this wallet's trading style (frequency × P&L grid): <WALLET_ADDRESS>.",
    "wallet_money_flow": "Aggregate 24h net inflow/outflow USD for 5 wallets I care about.",
    "copy_trade": "Can I realistically copy-trade wallet <ADDRESS> with $500 position + 30s delay?",
    "wallet_analysis": "Deep-dive wallet analysis: net worth, P&L by interval, trading activity, risk metrics for <WALLET_ADDRESS>.",
    "rug_score": "Heuristic 0-100 rugpull risk score for <TOKEN_ADDRESS> and red flag list.",
    "lp_check": "Is liquidity locked? For <TOKEN_ADDRESS>, show locked percent + unlock date if known.",
    "kols": "Show website/TG/X links + creator launch history for <TOKEN_ADDRESS>.",
    "chains": "Compare trending tokens on Solana vs Base vs BSC right now.",
    "pf_tokens": "Show all trending launchpad tokens filtered to Pump.fun only, newest first.",
    "meme_index": "Health of meme basket today and which memes are rotating top performers.",
    "kline_pattern": "What is the current candlestick pattern + score for <TOKEN_ADDRESS> (15m 7d)?",
    "price_1y": "1Y price history for <TOKEN> with ATH/ATL and drawdown vs SOL/BTC/ETH.",
    "vol_profile": "Historical buy/sell volume distribution profile for <TOKEN_ADDRESS>.",
    "corr_map": "Which tokens move most correlated with <TOKEN_ADDRESS> last 30 days?",
    "events": "What unlock/listing/vesting catalyst events are coming for <TOKEN> next 30 days?",
    "alert_surge": "Create a Telegram webhook alert rule for token <T>: fire when 5m volume > 200% avg.",
    "tg_signal": "Format the last DD result for <TOKEN> as Telegram ```copy-paste``` signal pack.",
    "key": "Paste my Birdeye API key here → save session-only or persist to ~/.birdeye.env.",
    "billing": "Show CU usage per skill last 7 days and set daily $ budget alerts.",
    "about": "Open docs and all skill source code paths for reference.",
}

# Build BUILTIN rows = exact copy of _30_SKILLS_CATALOG literal copy (keep synchronized)
BUILTIN_CATALOG = [
    {"cat": "🔥 Discovery (3)", "items": [
        {"id": "tl", "title": "Trending List", "cu": "30 CU", "status": "live",
         "desc": "/defi/token_trending — hot tokens by volume/rank/liquidity"},
        {"id": "tl_v3", "title": "V3 Token List", "cu": "50 CU", "status": "live",
         "desc": "/defi/v3/token/list — min_volume filter, trade_count/holders enriched"},
        {"id": "new_pair", "title": "New Pairs / New Listings", "cu": "TBD CU", "status": "wip",
         "desc": "Recently launched tokens sorted by age across all launchpads"},
    ]},
    {"cat": "🛡 Token Due Diligence (5)", "items": [
        {"id": "dd", "title": "Token DD (Should I Buy?)", "cu": "71 CU", "status": "live",
         "desc": "overview+money_flow+security+SM join → A/B/C/D/F/NG research rating (birdeye-dd-workflow step 10)"},
        {"id": "security", "title": "Security + LP Concentration", "cu": "75 CU", "status": "wip",
         "desc": "token_security + /holder/v1/distribution + /defi/v2/markets join = LP holder% + top50 (DD steps 3/4/9)"},
        {"id": "contract_dd", "title": "Contract DD", "cu": "65 CU", "status": "live",
         "desc": "Composite 0-100: safety 45% + holders 30% + price 25% (GMGN gmgn-contract-dd port)"},
        {"id": "holders", "title": "Top 20 Holders + 5 Tags% + BotProxy", "cu": "60 CU", "status": "wip",
         "desc": "holder-profile + holder-distribution + top-traders tags = tag% + holding$ nội suy + BotProxy% (DD steps 4/5/6b)"},
        {"id": "compare", "title": "Multi-Token Compare Rating", "cu": "N × DD CU", "status": "wip",
         "desc": "Side-by-side DD A-F rating of 3-5 tokens same scale"},
    ]},
    {"cat": "🧠 Wallet & Smart Money (7)", "items": [
        {"id": "sm_tokens", "title": "Smart Money Hot Tokens", "cu": "20 CU", "status": "wip",
         "desc": "/smart-money/v1/token/list — tokens with most SM buying today"},
        {"id": "sm_wallets", "title": "Smart Money Profile", "cu": "~90 CU", "status": "live",
         "desc": "Single-wallet behavior analysis: 7d/30d performance trend, trading style, TP/SL patterns, copy-trade ROI estimate, 🟢/🟡/🔴 verdict"},
        {"id": "wallet_portfolio", "title": "Wallet Portfolio + Unreal PnL", "cu": "10 CU", "status": "wip",
         "desc": "Any address → token holdings USD + unrealized P&L vs avg buy"},
        {"id": "wallet_style", "title": "Wallet Style", "cu": "60..90 CU", "status": "live",
         "desc": "Freq × P&L grid + speed subtitle + badges — classify a wallet's trading style (GMGN wallet-style port)"},
        {"id": "wallet_money_flow", "title": "Wallet Net Flow (aggregated)", "cu": "5 CU", "status": "wip",
         "desc": "24h Inflow/outflow USD totals for a custom list of wallets"},
        {"id": "copy_trade", "title": "Copy-Trade Setup Config", "cu": "0 CU", "status": "wip",
         "desc": "Generate Telegram bot / webhook copy-trade signal config for 1 SM wallet"},
        {"id": "wallet_analysis", "title": "Wallet Analysis", "cu": "90..180 CU", "status": "live",
         "desc": "Single-wallet deep-dive: profile, assets (current + intervals), trading & PnL performance by interval, risk metrics (concentration, activeness, open positions)"},
    ]},
    {"cat": "🔐 Security & Risk (4)", "items": [
        {"id": "rug_score", "title": "Rugpull Risk Score (0-100)", "cu": "35 CU", "status": "wip",
         "desc": "Security + contract authority + holder concentration heuristics aggregate"},
        {"id": "lp_check", "title": "LP Lock Checker", "cu": "5 CU", "status": "wip",
         "desc": "Verify % liquidity locked + locker name + unlock date if available"},
        {"id": "kols", "title": "KOL / Dev Links + Creator History", "cu": "0 CU", "status": "wip",
         "desc": "Website/Telegram/X social links + CA creator address prior launches track record"},
        {"id": "junk_predict", "title": "Junk Token Prediction (ML)", "cu": "300 CU", "status": "live",
         "desc": "Logistic-regression junk score (0-100) on 16 features. Score ≥ threshold → JUNK. Paste one/many addresses, or Quick Test random 30 from v3 list."},
    ]},
    {"cat": "⛓ Chain & Platform (3)", "items": [
        {"id": "chains", "title": "Cross-Chain Compare", "cu": "multi-CU", "status": "wip",
         "desc": "Same trending discovery list shown side-by-side across sol/bsc/base/eth"},
        {"id": "pf_tokens", "title": "Platform: Pump.fun / Moonshot / …", "cu": "50 CU", "status": "wip",
         "desc": "Filter all discovery skills to one launch platform only"},
        {"id": "meme_index", "title": "Meme Basket Health Index", "cu": "30 CU", "status": "wip",
         "desc": "Track top 25 meme basket aggregate health + rotation heat leaders"},
    ]},
    {"cat": "📈 History & Charts (5)", "items": [
        {"id": "kline_pattern", "title": "Kline Pattern", "cu": "5 CU", "status": "live",
         "desc": "Classify candlestick pattern + 0..100 score (GMGN gmgn-kline-pattern port). 6 numbers → 11 patterns."},
        {"id": "price_1y", "title": "1Y Price + Benchmarks (SOL/BTC/ETH)", "cu": "15 CU", "status": "wip",
         "desc": "ATH/ATL + drawdown percentages vs 3 big-cap benchmarks"},
        {"id": "vol_profile", "title": "Volume Profile (historic distribution)", "cu": "10 CU", "status": "wip",
         "desc": "Buy/sell volume distribution by price bucket POC/VA/VAH"},
        {"id": "corr_map", "title": "Token Correlation Map (N)", "cu": "N × 15 CU", "status": "wip",
         "desc": "Pearson 30d/7d correlations: which tokens move together most with my watchlist?"},
        {"id": "events", "title": "Catalyst Events Timeline (unlock/listing)", "cu": "0 CU", "status": "wip",
         "desc": "Upcoming unlock / CEX listing / vesting cliff timeline for a token"},
    ]},
    {"cat": "🤖 Alerts & Bots (2)", "items": [
        {"id": "alert_surge", "title": "Volume Surge Alert Rule + Webhook", "cu": "30 CU/hr poll", "status": "wip",
         "desc": "Generate Telegram/Discord webhook payload configuration for volume/price poller"},
        {"id": "tg_signal", "title": "Telegram Copy-Paste Signal Pack", "cu": "0 CU", "status": "wip",
         "desc": "Render any DD/trending result into Telegram-ready markdown signal ```pack```"},
    ]},
    {"cat": "⚙ Utils & Settings (3)", "items": [
        {"id": "key", "title": "API Key Manager", "cu": "0 CU", "status": "live",
         "desc": "Paste Birdeye API key → temp session OR persist to ~/.birdeye.env"},
        {"id": "billing", "title": "CU Usage Monitor + Budget Alerts", "cu": "0 CU", "status": "wip",
         "desc": "Track CU/day per skill + set daily / weekly spend budget webhook alerts"},
        {"id": "about", "title": "About · Docs · Source Links", "cu": "0 CU", "status": "live",
         "desc": "Links to Birdeye llms.txt OpenAPI docs + all source code paths"},
    ]},
]

assert sum(len(g["items"]) for g in BUILTIN_CATALOG) == 32, f"Expected 32 builtin, got {sum(len(g['items']) for g in BUILTIN_CATALOG)}"

def slugify_id(skill_id: str, cat: str, title: str) -> str:
    """Map local skill id → birdeye-<slug> (marketplace slug style)"""
    known = {
        "tl": "birdeye-5-minute-most-traded-tokens",   # close to marketplace
        "tl_v3": "birdeye-v3-token-trending-list",
        "new_pair": "birdeye-newly-listed-tokens",
        "dd": "birdeye-token-due-diligence",
        "security": "birdeye-token-security-check",
        "contract_dd": "birdeye-contract-dd",
        "holders": "birdeye-top-holders",
        "compare": "birdeye-multi-token-due-diligence-compare",
        "sm_tokens": "birdeye-smart-money-token-radar",
        "sm_wallets": "birdeye-smart-money-profile",
        "wallet_portfolio": "birdeye-wallet-holdings-portfolio",
        "wallet_style": "birdeye-wallet-style-grid",
        "wallet_money_flow": "birdeye-wallet-net-buying",
        "copy_trade": "birdeye-wallet-copy-trade-assessment",
        "wallet_analysis": "birdeye-wallet-analysis",
        "rug_score": "birdeye-token-due-diligence",  # alias; marketplace has separate rugcheck later
        "lp_check": "birdeye-liquidity-pool-analysis",
        "kols": "birdeye-dev-launch-track-record",
        "chains": "birdeye-cross-chain-trending-compare",
        "pf_tokens": "birdeye-launchpad-trending-tokens",
        "meme_index": "birdeye-curated-hot-token-radar",
        "kline_pattern": "birdeye-kline-pattern",
        "price_1y": "birdeye-token-price-benchmarks-1y",
        "vol_profile": "birdeye-token-volume-profile-distribution",
        "corr_map": "birdeye-token-correlation-map",
        "events": "birdeye-token-catalyst-events-timeline",
        "alert_surge": "birdeye-5-minute-volume-surge",
        "tg_signal": "birdeye-telegram-signal-pack-renderer",
        "key": "birdeye-api-key-manager",
        "billing": "birdeye-cu-usage-budget-monitor",
        "about": "birdeye-about-docs-source-links",
        "junk_predict": "birdeye-junk-token-prediction-ml",
    }
    if skill_id in known:
        return known[skill_id]
    # fallback
    clean = title.lower().replace(" ", "-").replace("/", "-").replace("(", "").replace(")", "")
    import re
    clean = re.sub(r"[^a-z0-9\-]+", "", clean)
    clean = re.sub(r"\-+", "-", clean).strip("-")
    return f"birdeye-{clean}"


def trader_question_for(skill_id: str, title: str) -> str:
    map_q = {
        "tl": "What are the most traded Solana tokens right now by 5-minute volume?",
        "tl_v3": "Which tokens pass my V3 filters (volume, holders, trade count) for today?",
        "new_pair": "What new token pairs / listings launched on Solana in the last 6 hours?",
        "dd": "Does this token deserve deeper investigation — give me a Birdeye DD rating A-F.",
        "security": "What contract authority and holder concentration risks exist for <TOKEN_ADDRESS>?",
        "contract_dd": "Composite contract risk score for this token — safety, holder concentration, and price action.",
        "holders": "Who holds this token — top 20 holders + tag concentration% + BotProxy estimate?",
        "compare": "Compare the Birdeye DD ratings of 3-5 tokens side-by-side.",
        "sm_tokens": "Which tokens are most actively bought by Birdeye Smart Money wallets today?",
        "sm_wallets": "Analyze this wallet: trading style, take-profit/stop-loss behavior, copy-trade ROI estimate, and a copy/avoid verdict.",
        "wallet_portfolio": "What tokens does wallet <WALLET> hold now, and unrealized P&L vs avg buy?",
        "wallet_style": "What's this wallet's trading style — sniper, swing, or holder? Use the frequency × P&L grid.",
        "wallet_money_flow": "Aggregate USD net flow for my custom list of smart wallets last 24h.",
        "copy_trade": "Can I realistically copy-trade wallet <WALLET> with $500 size + 30s execution delay?",
        "wallet_analysis": "Deep-dive single-wallet analysis: net worth & change by interval, trading activity, P&L performance, and risk metrics.",
        "rug_score": "Heuristic rugpull risk 0-100 for this token — show me the red flag checklist.",
        "lp_check": "Is liquidity locked for this token? Percent locked + unlock date if observed.",
        "kols": "Show website/Telegram/X socials plus prior creator-launch track record for this token.",
        "chains": "Compare trending tokens of Solana / BSC / Base / Ethereum on the same scale.",
        "pf_tokens": "Which launchpad tokens are trending right now, filtered to Pump.fun or Moonshot?",
        "meme_index": "How healthy is the meme coin basket today — which memes are rotating top performance?",
        "kline_pattern": "What candlestick pattern is <TOKEN> forming right now? Give me the pattern name + 0-100 score.",
        "price_1y": "1-year price history for this token vs SOL / BTC / ETH benchmarks, show ATH/ATL/drawdown.",
        "vol_profile": "Historical buy/sell volume profile distribution by price bucket for this token.",
        "corr_map": "Which tokens correlate highest with my watchlist token over 7d/30d windows?",
        "events": "What upcoming unlock / CEX listing / vesting catalyst events exist for this token?",
        "alert_surge": "Build me a Telegram/Discord webhook rule: alert when 5m volume > 200% of average.",
        "tg_signal": "Render the last result into a copy-paste-ready Telegram markdown signal pack.",
        "key": "Paste my Birdeye API key here — session-only, or save to ~/.birdeye.env.",
        "billing": "Show CU spend per skill last 7 days and set daily/weekly budget alerts.",
        "about": "Open documentation links and all source-code paths for this Hub.",
    }
    return map_q.get(skill_id, f"How do I use the skill: {title}?")


def build_builtin_rows():
    rows = []
    for g in BUILTIN_CATALOG:
        cat = g["cat"]
        csv_cat = CAT_MAP[cat]
        stage = STAGE_MAP[cat]
        for it in g["items"]:
            sid = it["id"]
            skill_name = slugify_id(sid, cat, it["title"])
            live_wip_tag = "" if it["status"]!="live" else " · LIVE"
            display_title = f"[{it['status'].upper()}] {it['title']} ({it['cu']}){live_wip_tag}"
            trader_q = trader_question_for(sid, it["title"])
            desc_full = f"{it['desc']}  ·  Status: {it['status'].upper()}, Cu: {it['cu']}, Cat: {cat}"
            difficulty = DIFFICULTY_MAP.get(sid, "Intermediate")
            core_calls = CORE_CALLS_MAP.get(sid, "(unspecified)")
            core_caps = it["desc"]
            prompts = PROMPTS_MAP.get(sid, f"Run skill {it['title']}.")
            rows.append([
                skill_name, display_title, trader_q, desc_full, csv_cat, stage, difficulty, core_calls, core_caps, prompts
            ])
    return rows


def read_marketplace_rows():
    import io
    rows = []
    with open(MARKETPLACE_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def main():
    builtin = build_builtin_rows()
    marketplace = read_marketplace_rows()
    builtin_names = {r[0] for r in builtin}

    builtin_count = len([r for r in builtin if r[5] != "BACKLOG"])
    # status LIVE count
    live_count = sum(1 for g in BUILTIN_CATALOG for it in g["items"] if it["status"]=="live")

    backlog_rows = []
    for mp in marketplace:
        sn = (mp.get("skill name") or "").strip()
        if sn and sn not in builtin_names:
            # stage = BACKLOG prefix
            backlog_rows.append([
                sn,
                mp.get("display title", ""),
                mp.get("trader question", ""),
                "[BACKLOG reference · marketplace source — NOT YET IMPLEMENTED as Birdeye native skill] " + (mp.get("description","")),
                mp.get("category", ""),
                "BACKLOG",
                mp.get("difficulty", ""),
                mp.get("core_calls", ""),
                mp.get("core_capabilities", ""),
                mp.get("example_prompts", ""),
            ])

    headers = ["skill name","display title","trader question","description","category","stage","difficulty","core_calls","core_capabilities","example_prompts"]

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        # 2 comment lines header
        f.write(f"# Total skills: {len(builtin)} BUILTIN ({live_count} LIVE + {len(builtin)-live_count} WIP) + {len(backlog_rows)} BACKLOG (from marketplace {len(marketplace)} marketplace source) = {len(builtin)+len(backlog_rows)} rows\n")
        f.write(f"# Coverage LIVE = {live_count} / {len(builtin)+len(backlog_rows)} = {100.0*live_count/(len(builtin)+len(backlog_rows) or 1):.1f}%  ·  Source builtin: birdeye_ui.py _30_SKILLS_CATALOG JSON  ·  Source ref: Birdeye Data Skills - marketplace-catalog.csv\n")
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writerow(headers)
        for r in builtin:
            w.writerow(r)
        for r in backlog_rows:
            w.writerow(r)

    print(f"[OK] Wrote: {OUT_CSV}")
    print(f"      - builtin rows: {len(builtin)} (LIVE {live_count})")
    print(f"      - backlog rows: {len(backlog_rows)}")
    print(f"      - total rows data: {len(builtin)+len(backlog_rows)}")
    print(f"      - headers match marketplace: {headers == list(csv.DictReader(open(MARKETPLACE_CSV, encoding='utf-8-sig')).fieldnames)}")


if __name__ == "__main__":
    main()
