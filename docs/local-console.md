# Local Console UI

Run the Birdeye Skills **web console** on your own machine. It is the same console that
ships at the hosted URL — a web frontend plus a tiny local proxy that forwards each request
to the scoring engine. Clone the repo, start one process, open the browser.

The console is **zero-dependency**: it uses only Python's standard library. No `pip install`,
no Node, no build step.

## What you get

- Every skill in a point-and-click form — pick a skill, fill the inputs, run
- The same five output formats as the CLI (`ui` · `plain` · `json` · `telegram` · `raw-json`)
- A **Key bar** — paste your Birdeye API key once, stored in the browser only
- A collapsible **History** panel with **0-CU replay** of previous runs
- A ready-to-copy `cURL` for every run, so a UI run becomes a script
- The freezer v1 console is still served at `/v1`

| Layer | File | Role |
|---|---|---|
| Frontend | [`public/index.html`](../public/index.html) | the console (v2) · [`public/v1.html`](../public/v1.html) is the frozen v1 |
| Local proxy | [`server.py`](../server.py) | serves the frontend + forwards `/api/run` to the engine |
| Control script | [`server.sh`](../server.sh) | start / stop / restart / fg / watch / status (macOS + Linux) |
| Engine | private service | the closed scoring engine (formulas + API calls) |

## Requirements

- Python ≥ 3.8 (standard library only)
- A Birdeye API key
- Internet access (to reach the engine)

## 1. Clone

```bash
git clone https://github.com/TheNang2710/birdeye-data-skills.git
cd birdeye-data-skills
```

## 2. Start

### macOS / Linux

```bash
./server.sh start      # background  → http://127.0.0.1:8765/
./server.sh fg         # foreground  (Ctrl+C to stop)
./server.sh watch      # auto-restart when source files change
./server.sh status     # running / stopped
./server.sh stop       # stop
```

### Windows (cmd / PowerShell)

`server.sh` is a bash script, so on Windows run the server directly:

```bat
python server.py
```

Then open the URL it prints (`http://127.0.0.1:8765/`). To stop it, press `Ctrl+C` in that
window.

### Any OS — run the server directly

```bash
python3 server.py                      # http://127.0.0.1:8765/
python3 server.py --host 0.0.0.0 --port 8080
python3 server.py --engine https://your-engine.example.com
```

The startup log prints the URL, the engine it will use and whether a key is already set.

## 3. Open the console

Go to **<http://127.0.0.1:8765/>** in your browser.

| Route | Serves |
|---|---|
| `/` or `/v2` | the console (v2) |
| `/v1` | the frozen v1 console |
| `/health` | liveness probe (`{ok, root, engine}`) |
| `/api/meta` | runtime capabilities |
| `/api/key-info` | masked key state |
| `/assets/*` | static assets |

## 4. Add your API key

Three ways — pick one. They are checked in this order:

1. **Paste in the UI (browser only)** — paste into the Key bar. It stays in this browser and
   is sent only to the engine with each request. Nothing is written to disk.
2. **Save to this project's `.env`** — use the Key bar's save action; it writes
   `BIRDEYE_API_KEY=…` to `./.env` (git-ignored, chmod 600). The server picks it up on the
   next request.
3. **Environment variable** — export it before you start the server:

   ```bash
   # macOS / Linux
   export BIRDEYE_API_KEY=<KEY>
   ./server.sh start
   ```

   ```bat
   :: Windows cmd
   set BIRDEYE_API_KEY=<KEY>
   python server.py
   ```

The full key is never displayed — the UI shows a `head2****tail2` mask.

> Also set the key once for the CLI at the same time with `birdeye-cli config --apply <KEY>`,
> so terminal and console share one credential.

## 5. Use the console

1. **Pick a skill** — `token-dd-score`, `trending-list`, `price-surge`, `wallet-score`,
   `wallet-style`, `kline-pattern`, `token-trending-score`, `junk-predict`.
2. **Fill the inputs** — chain, subject (`address` / `wallet` / `tokens`) and any mode or
   threshold flags. Empty fields use the skill defaults.
3. **Run** — the result renders in the output area. Switch the output format without paying
   again.
4. **Copy the cURL** — turns the run into a reproducible command figure.
5. **History** — expand the panel to replay any previous run at **0 CU**.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `HOST` | `127.0.0.1` | bind address (use `0.0.0.0` to reach it from other devices) |
| `PORT` | `8765` | listen port |
| `LOG` | `/tmp/birdeye-skills.log` | background log file |
| `WATCH_INTERVAL` | `2` | seconds between change checks in `watch` mode |
| `ENGINE_URL` | hosted engine | engine base URL |
| `BIRDEYE_API_KEY` | — | pre-set key (see §4) |

CLI flags: `--host`, `--port`, `--engine`, `--reload`.

## Hosted build & self-hosting the engine

- Hosted console: <https://birdeye-data-skills.vercel.app> (frozen v1 at `/v1`).
- The console talks to the same engine as the CLI. To use your **own** engine, point it with
  `--engine <URL>` or `ENGINE_URL=<URL>`; the proxy only needs the engine's `/api/run`
  contract.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `port 8765 busy` | another process holds the port | `./server.sh stop`, or run with `PORT=8080` |
| `Address already in use` (Windows) | port taken | `python server.py --port 8080` |
| `⚠ Paste your Birdeye API key to run` | no key resolvable | paste in the Key bar (§4) |
| `engine_unreachable` | no network / engine down | retry, or point `--engine` at a reachable engine |
| Page does not load | server not running | check `./server.sh status` |
