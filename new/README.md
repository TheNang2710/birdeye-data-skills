# Birdeye Skills

Six self-contained discovery & insight skills for [Birdeye](https://birdeye.so) data, plus a
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
│   ├── token-trending-score/    # SKILL.md
│   └── junk-predict/            # SKILL.md
├── public/index.html            # console UI (self-contained)
└── docs/                        # per-skill workflow documentation
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
| `token-dd-score` | Token Due-Diligence Score 0-100 + A+..F rating (standard / advanced) | 51 / 181 |
| `kline-pattern` | Candlestick pattern classifier + 0..100 score | 25-100 |
| `token-trending-score` | 0..100 momentum score per interval | ~171 |
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
birdeye-cli junk-predict   --chain sol --tokens <MINT1>,<MINT2> --model unsupervised
birdeye-cli wallet-score   --chain sol --wallet <ADDR> --duration 30d
birdeye-cli wallet-style   --chain sol --wallet <ADDR>
birdeye-cli token-trending-score --chain sol --address <MINT>
birdeye-cli history-list
```

(Without a global install, prefix each with `python3 birdeye_cli.py`.)

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `BIRDEYE_API_KEY` | Birdeye API key | — |
| `BIRDEYE_CACHE_DIR` | Run cache for 0-CU replay | `~/.cache/birdeye-skills-runs` |
| `BIRDEYE_LR_PARAMS` | Override `modules/lr_params.json` | bundled |
| `BIRDEYE_FUNCTION_PARAMS` | Override `modules/junk_function_params.json` | bundled |
| `BIRDEYE_SUPERVISED_MODEL` | Override `modules/junk_supervised_model.json` | bundled |

## Docs

Per-skill workflows live in [`docs/`](docs/): token-dd-score, kline-pattern,
token-trending-score, wallet-score, wallet-style.

## Notes

- Standard `token-dd-score` mode pulls overview + security (~51 CU); advanced adds holder
  distribution, holder profile, top holders, token money flow and 24h liquidity OHLC (~181 CU).
- Liquidity statistics are computed from 96 × 15m candles = 24 h (min / max / current /
  median / p05 / p95 / drawdown / floor-of-now / trend).
- Ratings are risk labels only — no buy/sell recommendations.
