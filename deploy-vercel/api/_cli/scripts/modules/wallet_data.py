"""Wallet-related data constants for Wallet Score (#13) and Wallet Style (#11).

Extracted from birdeye_cli.py to keep the CLI module lean.
All constants are plain Python literals (no imports needed).
"""

# ============================================================
# Skill #13 — Wallet Score constants
# ============================================================

_WS_HARD = {
    "MIN_TX_COUNT": 20,
    "MIN_VOLUME_USD": 5_000.0,
    "MAX_DEEP_LOSS_FRACTION": 0.50,   # max fraction of bag-hold deep-loss tokens
}

# v3 weights (profitability percentile benchmarked by daily leaderboard)
_WS_WEIGHTS = {
    "profitability": 0.35,
    "consistency": 0.35,
    "quality": 0.20,
    "activity": 0.10,
}

_WS_CONSISTENCY_WEIGHTS = {
    "win_rate": 0.20,
    "trend": 0.40,
    "trade_distribution": 0.25,
    "sample_confidence": 0.15,
}

_WS_QUALITY_WEIGHTS = {
    "realization": 0.35,
    "profit_distribution": 0.35,
    "loss_discipline": 0.30,
}

# v3.1 scoring thresholds
_WS_V3 = {
    "PROFIT_TARGET_USD": 1_000_000.0,       # fallback absolute target if leaderboard unavailable
    "OPTIMAL_TX_COUNT": 300,                 # sample confidence cap
    "MAX_BOT_PENALTY": 0.30,                 # activity bot penalty floor
    "WIN_RATE_TARGET": 0.60,                 # win rate that saturates win_rate subscore
    "SEVERE_LOSS_THRESHOLD": -0.50,          # positions losing >50% counted as severe
    "MAX_SEVERE_LOSS_FRACTION": 0.30,        # 30% severe-loss positions → loss_discipline = 0
    "MIN_MEANINGFUL_PROFIT_USD": 100.0,      # below this, trend stability is not meaningful
    # --- Deep-loss token tiers (by total_percent) ---
    "LOSS_TIER_CRITICAL": -0.90,             # ≥90% loss — catastrophic
    "LOSS_TIER_SEVERE":   -0.75,             # ≥75% loss — heavy
    "LOSS_TIER_MODERATE": -0.50,             # ≥50% loss — notable
    # --- Cash-out classification for loss tokens ---
    # A loss token is "bag_hold" (bad) if realized_profit_usd <= 0 (never booked profit).
    # A loss token is "smart_exit" (good) if realized_profit_usd > 0 (already took profit).
    "CASH_OUT_SMART_EXIT_MIN_USD": 0.0,      # realized > 0 → smart exit
}

_WS_CACHE_TTL_HOURS = 24

_WS_CSV_HEADER = [
    "ts_utc", "chain", "wallet", "duration", "pnl_method",
    "alpha_score", "copy_score", "profitability_score", "consistency_score", "quality_score", "activity_score",
    "realized_pnl_usd", "unrealized_pnl_usd", "total_pnl_usd", "volume_usd",
    "win_rate_percent", "total_trade", "unique_tokens",
    "deep_loss_token_count", "deep_loss_token_scanned", "deep_loss_penalty_pts",
    "loss_critical_count", "loss_severe_count", "loss_moderate_count",
    "bag_hold_loss_count", "smart_exit_loss_count", "concentration",
    "realized_pnl_90d_usd", "previous_60d_pnl_usd", "trend_score",
    "data_confidence", "benchmark_realized_pnl_usd", "leaderboard_rank", "leaderboard_size",
    "cu_used_total", "run_id",
]

_WS_BASELINES = {
    "profitability": {"low_usd": 1_000.0, "high_usd": 50_000.0},
    "consistency":   {"low_raw": 0.0,     "high_raw": 1.0},
    "quality":       {"low_raw": 0.0,     "high_raw": 1.0},
    # activity_raw = log1p(vol_usd) * log1p(unique_tokens). Baseline HIGH ~ log1p(5000)*log1p(500) ~= 8.52 * 6.22 ~= 53.
    "activity":      {"low_raw": 0.0,     "high_raw": 53.0},
}

# --- First-funded (wallet provenance) permanent cache ---
# wallet_created_ts_unix, block, tx_hash NEVER change for a wallet.
# Stored in a separate CSV so we never re-pay the 40 CU first-funded API call.
_WS_FF_CSV_HEADER = ["wallet", "chain", "ts_utc", "raw_json"]


# ============================================================
# Skill #11 — Wallet Style constants (GMGN-style trading-style tagger)
# 4×5 freq×PnL grid → 20 main titles + speed subtitle + badges.
# ============================================================

# --- 4×5 style grid (L = frequency, P = P&L) ---
_WSF_GRID = {
    # (L, P) -> (emoji, title_en, meaning)
    ("L4", "P5"): ("🖨️", "Money Printer", "Machine-speed and still strongly profitable"),
    ("L4", "P4"): ("⚙️", "Full-Auto Grinder", "Thin margins, huge volume"),
    ("L4", "P3"): ("🪫", "Worn Down", "Whatever the trades earn, fees and slippage take back"),
    ("L4", "P2"): ("🔥", "Gas Burner", "High frequency, high friction — loss is mostly cost"),
    ("L4", "P1"): ("💥", "Self-Destruct", "Machine-speed frequency plus broad heavy losses"),
    ("L3", "P5"): ("🌾", "Harvester", "High frequency, high win-rate, shallow drawdowns"),
    ("L3", "P4"): ("⚔️", "Active Winner", "Busy hands that actually keep the money"),
    ("L3", "P3"): ("🌀", "Spinning Top", "Spinning fast, going nowhere"),
    ("L3", "P2"): ("💸", "Fee Donor", "Real volume, and the money went on-chain"),
    ("L3", "P1"): ("🩸", "Bleeding Out", "Charging in at high frequency with a heavy tail of big losses"),
    ("L2", "P5"): ("🦅", "Old Hunter", "Rarely swings, mostly connects"),
    ("L2", "P4"): ("📈", "Steady Hand", "Normal cadence, positive return, no glaring weakness"),
    ("L2", "P3"): ("☕", "Lukewarm", "Active, but it has not turned into anything"),
    ("L2", "P2"): ("🐑", "Retail Loser", "The most common cell on the board"),
    ("L2", "P1"): ("🕳️", "Deep Underwater", "Most coins are down more than 50%"),
    ("L1", "P5"): ("🗡️", "One-Shot", "Almost never trades, and lands it when it does"),
    ("L1", "P4"): ("🧘", "Zen Winner", "The gain came from picks, not from working the trades"),
    ("L1", "P3"): ("👀", "Bystander", "Too small a sample to mean much"),
    ("L1", "P2"): ("💧", "Toe In The Water", "Tried a few times, none worked"),
    ("L1", "P1"): ("⚰️", "Wiped Out", "One or two swings, wiped out"),
}

_WSF_FREQ_LEVELS = [
    # (min_perDay, max_perDay_exclusive, key, name)
    (None, 1.0, "L1", "Rare"),
    (1.0, 10.0, "L2", "Regular"),
    (10.0, 50.0001, "L3", "Frequent"),  # 10 <= perDay <= 50
    (50.0, None, "L4", "Machine"),
]

_WSF_DAY_SECONDS = {"7d": 7, "30d": 30}
