# Birdeye Skills — Vercel App & Shared Console

A single deployment that ships the **shared web app**: the landing page
(`/`), the test console (`/test`) and the per-skill drill view
(`/detail`). The exact same `public/` folder is also served locally by
`../birdeye_ui.py` (port `8765`) — one UI, one source of truth.

```
deploy-vercel/
├── api/
│   ├── run.py            POST /api/run   — run one skill, return every format
│   ├── meta.py           GET  /api/meta  — runtime + key capabilities
│   ├── _lib.py           shared helpers (not routed)
│   ├── _cli/             bundled Birdeye CLI (not routed)
│   │   └── scripts/{birdeye_cli.py, modules/*}
│   └── _ml/              secure ML runtime (not routed)
│       ├── junk_ml.py
│       ├── trending_score.py
│       └── lr_params.json
├── public/               the shared web app (served by Vercel & local 8765)
│   ├── index.html        landing page — skill cards + setup guide  (/)
│   ├── test.html         test console — run skills                 (/test)
│   ├── detail.html       per-skill drill view                      (/detail)
│   ├── hub.js / hub.css  shared front-end bundle
│   ├── catalog.json      static skill catalog (Vercel fallback for /api/catalog)
│   └── assets/           logos (favicon, dark/light wordmark, svg)
├── dev.py                local dev server, mirrors the Vercel routing
├── sync-cli.sh           re-copy the shared CLI bundle from the workspace
├── vercel.json           function config (maxDuration, includeFiles, cleanUrls)
└── requirements.txt
```

> `cleanUrls: true` in `vercel.json` makes `/test` serve `test.html` on Vercel.

## Secure ML runtime (`api/_ml/`)

The proprietary model (`lr_params.json`) and its scoring code (`junk_ml.py`,
`trending_score.py`) live in `api/_ml/`, **outside** the bundled CLI. They are
loaded at runtime through the `modules` package shim
([`api/_cli/scripts/modules/__init__.py`](api/_cli/scripts/modules/__init__.py)),
so the CLI's `from modules import junk_ml` imports keep working unchanged.

`vercel.json` ships the folder with `includeFiles: "api/**"`, and `/api/meta`
reports `ml_ready` so a deploy that dropped it is obvious. Keeping the model
files in one folder (rather than inside the bundled CLI) makes them easy to
audit and swap.

## API key behaviour

| Where | Who provides the key | UI |
|---|---|---|
| Local (`dev.py`, `vercel dev`) | server env → `.env` → `../birdeye-screener/.env` | shows `✓ server env key`, collapsible |
| Deployed on Vercel | the visitor, pasted into the UI | `⚠ API key required`, Run stays disabled until a key is pasted |

The key input is masked (`type=password`) with a 👁 button to reveal/hide it,
and the value is kept in `localStorage` on the visitor's browser only — it is
never written to the server and never logged.

Detection: the env key is only honoured when the process is **not** a real
serverless invocation. `AWS_LAMBDA_FUNCTION_NAME` / `VERCEL_REGION` mark a real
deployment (`vercel dev` sets neither). To deliberately allow the env key on a
private deployment, set `BIRDEYE_ALLOW_ENV_KEY=1`.

## Local development

The shared web app is normally previewed through the root hub server (which
serves this same `public/` folder):

```bash
cd ..
./server.sh watch            # -> http://127.0.0.1:8765/  (landing)  &  /test
```

To test this folder in isolation (mirrors the Vercel routing + `cleanUrls`):

```bash
cd deploy-vercel
python3 dev.py --port 8787        # -> http://127.0.0.1:8787/test
```

No dependencies beyond the stdlib plus `requests` (already needed by the CLI).

## Deploy to Vercel

`deploy-vercel/` is a self-contained sub-project that lives inside the workspace
repo (`birdeye-data-skills`). Pick one of the two ways below.

### Option A — Vercel CLI (fastest)

> The `birdeye-data-skills` project has **Root Directory = `deploy-vercel`**, so
> the CLI must run from the **repo root** (running inside `deploy-vercel/` makes
> Vercel look for `deploy-vercel/deploy-vercel` and fail with
> *"The specified Root Directory does not exist"*).

```bash
cd ..                 # repo root (birdeye-data-skills)
npx vercel login      # first run only
npx vercel --prod --project birdeye-data-skills --yes   # production
```

The CLI uploads the repo and Vercel builds only `deploy-vercel/`, so `api/_ml/`
goes up too (the ML skills need it).

> **Why `"framework": null` in `vercel.json`** — Vercel auto-detects a Python
> framework preset here and then demands a *single* entrypoint, failing with
> `PYTHON_ENTRYPOINT_NOT_FOUND` (it sees both `api/run.py` and `api/meta.py`).
> A framework preset takes precedence over file-based functions, so pinning
> `framework` to `null` (= preset **Other**) is what makes each `api/*.py`
> deploy as its own function and `public/` serve as the static output dir.

### Option B — Git + dashboard (manual)

Prerequisite: the workspace is pushed to `TheNang2710/birdeye-data-skills`
(branch `main`).

1. Open <https://vercel.com/new> and sign in **with GitHub** (account
   `TheNang2710`).
2. **Import Git Repository** → pick `birdeye-data-skills`. If it is not listed,
   click *Adjust GitHub App Permissions* and grant access to the repo.
3. In **Configure Project** set:
   - **Project Name**: `birdeye-data-skills` (or any name)
   - **Framework Preset**: **Other**
   - **Root Directory**: click **Edit** → choose **`deploy-vercel`**
     ← *required*: the repo is a monorepo, so `deploy-vercel/` is where
     `api/`, `public/` and `vercel.json` actually live
   - **Build Command** / **Output Directory** / **Install Command**: leave empty
     (Vercel installs `requirements.txt` and serves `public/` automatically)
4. **Environment Variables**: leave empty for a BYO-key public console.
   Set `BIRDEYE_ALLOW_ENV_KEY=1` **and** `BIRDEYE_API_KEY=<key>` only if you want
   the server's own key used on a private deployment.
5. Click **Deploy**. Every later push to `main` auto-deploys.

> Skipping step 3's Root Directory makes Vercel build from the repo root, where
> there is no `api/` — the deploy then produces no functions and `/api/*` 404s.

### Verify after deploy

```bash
curl https://<your-app>.vercel.app/api/meta
```

If the project still has **Deployment Protection** on (Vercel Authentication),
plain `curl` returns the login page. Bypass it with the CLI instead:

```bash
npx vercel curl /api/meta --deployment https://<your-app>.vercel.app
```

To let outside visitors use the console (BYO-key), turn Deployment Protection
off in **Project Settings → Deployment Protection**.

Expect JSON with `"serverless": true`, `"key_required": true`, `"cli_ready": true`,
`"ml_ready": true`. Then open `/`, paste a Birdeye key and run a light skill
(e.g. `trending-list`).

If `ml_ready` is `false`, the ML skills (`junk-predict`, `token-trending-score`)
will fail — make sure `api/_ml/` was uploaded (see `vercel.json` → `includeFiles`
and the “Secure ML runtime” section above).

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `BIRDEYE_ALLOW_ENV_KEY` | *(unset)* | `1` lets the server env key be used on a deployment |
| `BIRDEYE_API_KEY` | *(unset)* | only read when `BIRDEYE_ALLOW_ENV_KEY=1` |
| `BIRDEYE_TIMEOUT_S` | `55` | per-run subprocess budget (keep below `maxDuration`) |
| `BIRDEYE_SCRATCH_DIR` | `/tmp/birdeye` | writable scratch (serverless filesystems are read-only outside `/tmp`) |

## Runtime limits (Vercel serverless)

* **Function budget** — `api/run.py` is configured for `maxDuration: 60`.
  Anything above that needs a paid plan (Pro: up to 300s) — edit `vercel.json`
  *and* `BIRDEYE_TIMEOUT_S` together.
* **Heavy skills** may exceed 60s (`wallet-analysis` ≈240 CU, `rugcheck-audit`
  ≈142 CU). The console reports `timeout — try a lighter skill` in that case.
  This is a platform limit, not a bug.
* **`/tmp` is ephemeral and per-instance.** The CLI writes its run cache there
  so all four formats can be produced inside a single request, but there is no
  persistent history across requests.
* **CU is spent on the caller's key.** Each Run makes one real API call set;
  the JSON / Telegram tabs are replayed from the run cache and cost 0 CU.

## Format handling

Skills disagree on which `--format` values they accept (`rendered`, `render`,
`plain`). The server probes `rendered → render → plain` and stops at the first
one the CLI accepts. An unknown format is rejected by `argparse` **before** any
API call, so probing never costs CU. `format_used` is returned in the response.

## Updating the bundled CLI

`api/_cli/` bundles the **shared** CLI from `../birdeye-screener/`
(`birdeye_cli.py` + the generic modules). Re-sync it after changing those:

```bash
./sync-cli.sh           # copy
./sync-cli.sh --check   # CI-style drift check (also verifies api/_ml/ is present)
```

The ML runtime in `api/_ml/` is deliberately **not** synced from the workspace —
it is the independent, secure master copy.
