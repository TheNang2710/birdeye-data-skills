# Birdeye Skills

Eight self-contained discovery & insight skills for [Birdeye](https://birdeye.so) data, plus a
zero-dependency local console. Everything lives in this folder — CLI, skill logic, ML model
assets, agent manifests, docs and UI.

```
new/
├── birdeye_cli.py               # single entrypoint for every skill
├── pyproject.toml               # installs the global `birdeye-cli` command
├── server.py                    # local console server (stdlib only, port 8765)
├── server.sh                    # start / stop / restart / watch helper
├── requirements.txt             # requests (only third-party dep)
├── .env.example                 # copy to .env and add your key
├── .claude-plugin/plugin.json   # AI-agent plugin manifest (skills → ./skills/)
├── modules/                     # skill logic + ML model assets
│   ├── kline_pattern.py         # candlestick pattern classification
│   ├── trending_score.py        # momentum scoring
│   ├── wallet_data.py           # wallet PnL / trade parsing
│   ├── junk_ml.py               # logistic-regression junk classifier
│   ├── junk_modes.py            # function (heuristic) + supervised (GBM) junk models
│   ├── lr_params.json           # trained LR weights
│   ├── junk_function_params.json # tuned heuristic parameters
│   └── junk_supervised_model.json
├── skills/                      # one SKILL.md per skill (agent-facing)
│   ├── token-duediligence/      # SKILL.md + token-dd-score.py (loaded by the CLI)
│   ├── wallet-score/            # SKILL.md
│   ├── wallet-style/            # SKILL.md
│   ├── kline-pattern/           # SKILL.md
│   ├── trending-list/           # SKILL.md
│   ├── price-surge/             # SKILL.md
│   ├── token-trending-score/    # SKILL.md
│   └── junk-predict/            # SKILL.md
├── public/index.html            # console UI (self-contained)
├── docs/                        # public per-skill workflow docs (one *-workflow.md per skill)
└── docs-local/                  # local-only full derivations (git-ignored)
```

## Quick Start (AI Agent)

Follow this exactly. Do **not** use web search / WebFetch / hand-rolled `curl` for Birdeye data —
the CLI already wraps every endpoint, the CU accounting and the output contract.

1. **Install the CLI** (from the `new/` folder):

   ```bash
   pipx install -e .
   ```

   Editable (`-e`) matters: it keeps `skills/` and `modules/` resolvable at runtime.
   If `pipx` is unavailable, use `python3 -m pip install -e .` or run the CLI directly with
   `python3 birdeye_cli.py <subcommand> …` from this folder (no install needed).

2. **Verify credentials** — always run this before any skill:

   ```bash
   birdeye-cli config --check
   ```

   - exit `0` → a Birdeye key is resolvable, continue.
   - exit `1` → no key. Ask the user for their **Birdeye API key**, then:

     ```bash
     birdeye-cli config --apply <BIRDEYE_API_KEY>
     ```

     This writes `~/.config/birdeye/.env` (chmod 600). Re-run `--check` to confirm.

3. **Discover skills**: `birdeye-cli --help`, then `birdeye-cli <skill> --help` for any skill.

4. **Run a skill** and read the requested format. Machines should use `--format json`
   (clean, HTML-free) or `--format raw-json`:

   ```bash
   birdeye-cli token-dd-score --chain sol --address <MINT> --mode advanced --format json
   ```

5. **Respect the CU budget**: every response ends with a `⚡CU` footer. Prefer cached replays
   (`history-list` → `history-render`) over re-running a skill for the same inputs.

### Intent → skill routing

| User intent | Skill (SKILL.md) |
|---|---|
| "Should I buy this token?", risk score, rug check, holder concentration, money flow | `token-dd-score` |
| "What is trending right now?", hot token list, Birdeye leaderboard | `trending-list` |
| Surging / pumping tokens right now, market-cap band screener, auto rug / wash / honeypot screen | `price-surge` |
| Score a wallet, copy-trade quality, wallet alpha | `wallet-score` |
| Scam / low-quality / filter dust tokens, junk score | `junk-predict` |
| Candlestick / chart pattern for a token | `kline-pattern` |
| How hot / trending / momentum is a token | `token-trending-score` |
| Wallet trading style (scalper vs swing, hold time) | `wallet-style` |

Each skill's `SKILL.md` in `skills/<name>/` carries its own credential guard, flags, CU cost
and error map.

## Quick Start (human)

```bash
cd new
python3 -m pip install -r requirements.txt
cp .env.example .env          # then paste your Birdeye API key into .env
python3 birdeye_cli.py config --check
```

## Credentials

Resolution order (first hit wins):

1. `$BIRDEYE_API_KEY` (env var)
2. `~/.config/birdeye/.env` (written by `config --apply`)
3. `~/.birdeye.env`
4. `./.env` (skill-local, git-ignored)

```bash
birdeye-cli config --check          # exit 0 = ready, exit 1 = missing
birdeye-cli config --status         # masked key (head2****tail2) + source + paths
birdeye-cli config --apply <KEY>    # write ~/.config/birdeye/.env (chmod 600)
```

The full key is **never** printed — only a `head2****tail2` mask.

## Skills

| Subcommand | What it does | CU |
|---|---|---|
| `token-dd-score` | Token Due-Diligence Score 0-100 + A+..F rating (standard / advanced) | 56 / 186 |
| `kline-pattern` | Candlestick pattern classifier + 0..100 score | 25-100 |
| `trending-list` | Birdeye hot-token list passthrough | 30 |
| `price-surge` | Price-surge screen in a market-cap band + auto rug / wash / honeypot filter (min / advanced) | 50 / 50-430 |
| `token-trending-score` | 0..100 momentum score per interval | ~176 |
| `junk-predict` | ML junk-token score (unsupervised LR16 / function heuristic / supervised GBM) | 51 / token |
| `wallet-score` | Wallet alpha score + copy-tradeability breakdown | 30-110 |
| `wallet-style` | Trading-style tagger (frequency × P&L grid) | 60-90 |

Additional subcommands: `config` (credential onboarding) and the helpers `history-list` /
`history-render` which replay any cached run at **0 CU**.

Every skill supports 4 output formats: `ui` (HTML payload for the console), `telegram`,
`plain`, `json` (plus `raw-json`). `json` / `plain` are free of HTML for bot integration.

## Run the console

```bash
./server.sh start             # background → http://127.0.0.1:8765/
./server.sh fg                # foreground
./server.sh watch             # auto-restart on file change
./server.sh stop
./server.sh status
```

The console runs each skill as a subprocess of `birdeye_cli.py` and renders the `ui` payload.
`GET /api/meta`, `/api/key-info`, `/health` and `POST /api/run`, `/api/set-key` back it.

## Run a skill from the shell

```bash
birdeye-cli token-dd-score --chain sol --address <MINT> --mode advanced --format plain
birdeye-cli kline-pattern  --chain sol --address <MINT> --resolution 15m --window 7d
birdeye-cli trending-list  --chain sol --interval 24h --limit 20 --format plain
birdeye-cli price-surge    --chain solana --interval 5m --mode min --min-market-cap 50000 --max-market-cap 5000000
birdeye-cli junk-predict   --chain sol --tokens <MINT1>,<MINT2> --model unsupervised
birdeye-cli wallet-score   --chain sol --wallet <ADDR> --duration 30d
birdeye-cli wallet-style   --chain sol --wallet <ADDR>
birdeye-cli token-trending-score --chain sol --address <MINT>
birdeye-cli history-list
```

(Without a global install, prefix each with `python3 birdeye_cli.py`.)

### Exit codes

| Exit | Meaning | CU spent? |
|---:|---|---|
| 0 | Success | Actual CU |
| 2 | Invalid args / address / key (argparse / preflight) | 0 CU |
| 3 | API key missing | 0 CU |
| 4 | Birdeye upstream HTTP error | Partial possible on 429 |
| 5 | Post-response invariant failed | CU (already called) — `pipeline_gap` badge |

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `BIRDEYE_API_KEY` | Birdeye API key | — |
| `BIRDEYE_CACHE_DIR` | Run cache for 0-CU replay | `~/.cache/birdeye-skills-runs` |
| `BIRDEYE_LR_PARAMS` | Override `modules/lr_params.json` | bundled |
| `BIRDEYE_FUNCTION_PARAMS` | Override `modules/junk_function_params.json` | bundled |
| `BIRDEYE_SUPERVISED_MODEL` | Override `modules/junk_supervised_model.json` | bundled |

## Docs

Public per-skill workflow docs live in [`docs/`](docs/) — one `*-workflow.md` per skill
(token-dd-score, token-trending-score, trending-list, price-surge, wallet-score, wallet-style,
wallet-analysis, kline-pattern, junk — spam-token-cleaner, rugcheck-audit, smart-money-profile).

The deeper local-only derivations (full formulas, scoring research, raw API walkthroughs) stay in
`docs-local/` (git-ignored, never published).

## Notes

- Standard `token-dd-score` mode pulls overview + security + a live liquidity snapshot (~56 CU);
  advanced adds holder distribution, holder profile, top holders, token money flow and 24h
  liquidity OHLC (~186 CU).
- The "current" liquidity / exit-liquidity figure is a **live snapshot** (`token_overview` +
  `POST /defi/v3/liquidity/latest/token`), never a stale OHLC bar close; the 96 × 15m window is
  used only for the time-series statistics (min / max / median / p05 / p95 / drawdown / floor-of-now /
  trend).
- `trending-list` is deliberately thin: one `/defi/token_trending` call, one list, no local scoring.
- `price-surge` starts from token list v3: `min` is a single 50 CU call with the market-cap band and
  surge / liquidity / volume floors applied server-side; `advanced` hydrates at most `--top` rows with
  security, smart-money, top-trader and (Solana) holder-health data. Excluded rows stay visible with
  their reason; `--no-auto-filter` keeps them all.
- Ratings are risk labels only — no buy/sell recommendations.
