"""Shared helpers for the Vercel test-console functions.

Design notes
------------
* The Birdeye CLI is bundled under ``api/_cli/`` (underscore prefix = not routed).
* Serverless filesystems are read-only except ``/tmp``. We therefore redirect
  ``HOME`` and the CLI cache dir into a scratch folder so every ``Path.home()``
  write inside the CLI lands somewhere writable.
* The API key is supplied by the caller. On a real serverless runtime the
  server env key is ignored unless ``BIRDEYE_ALLOW_ENV_KEY=1`` is set, so a
  public deployment always requires the visitor's own key.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent  # .../api

# ── Runtime detection ───────────────────────────────────────────────────────
# VERCEL_REGION / AWS_LAMBDA_FUNCTION_NAME only exist on a real deployment.
# `vercel dev` sets VERCEL=1 but runs on the developer machine, so it must
# still count as "local".
IS_SERVERLESS = bool(
    os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get("VERCEL_REGION")
)
ENV_KEY_ALLOWED = (not IS_SERVERLESS) or os.environ.get("BIRDEYE_ALLOW_ENV_KEY") == "1"

# ── Paths ───────────────────────────────────────────────────────────────────
SCRATCH = pathlib.Path(os.environ.get("BIRDEYE_SCRATCH_DIR") or "/tmp/birdeye")
CACHE_DIR = SCRATCH / "runs"
VENDOR_DIR = HERE / "_vendor"

_CLI_REL = ("_cli", "scripts", "birdeye_cli.py")
CLI_CANDIDATES = [
    HERE.joinpath(*_CLI_REL),  # api/_cli/scripts/birdeye_cli.py
    HERE.parent.joinpath("_cli", *_CLI_REL[1:]),
    pathlib.Path("/var/task/api").joinpath(*_CLI_REL),
    pathlib.Path.cwd() / "api" / pathlib.Path(*_CLI_REL),
]
CLI_PATH = next((p for p in CLI_CANDIDATES if p.exists()), CLI_CANDIDATES[0])

ALLOWED_SCRIPTS = {"birdeye_cli"}
PY = sys.executable
TIMEOUT_S = int(os.environ.get("BIRDEYE_TIMEOUT_S") or 55)
MAX_ARGV = 64
_BAD_CHARS = ";&|`$<>\\'\""


def find_env_key() -> str:
    """Return the Birdeye key available in the server environment, if any."""
    if k := os.environ.get("BIRDEYE_API_KEY"):
        return k.strip()
    for p in (pathlib.Path("/var/task/birdeye-screener/.env"), SCRATCH / ".birdeye.env"):
        try:
            if not p.exists():
                continue
            for ln in p.read_text(encoding="utf-8").splitlines():
                if ln.strip().startswith("BIRDEYE_API_KEY="):
                    return ln.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            continue
    return ""


def resolve_key(user_key: str = "") -> tuple[str, str]:
    """Resolve the key to use. Returns ``(key, source)``."""
    if user_key and user_key.strip():
        return user_key.strip(), "ui"
    if ENV_KEY_ALLOWED and (k := find_env_key()):
        return k, "env"
    return "", "none"


def mask(key: str) -> str:
    if not key:
        return ""
    return f"{key[:2]}****{key[-2:]}" if len(key) > 6 else "****"


def build_env(key: str) -> dict:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(SCRATCH)  # every Path.home() write now hits /tmp
    env["BIRDEYE_CACHE_DIR"] = str(CACHE_DIR)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if VENDOR_DIR.exists():
        existing = env.get("PYTHONPATH", "").strip()
        env["PYTHONPATH"] = f"{VENDOR_DIR}{os.pathsep}{existing}" if existing else str(VENDOR_DIR)
    env.pop("BIRDEYE_API_KEY", None)
    if key:
        env["BIRDEYE_API_KEY"] = key
    return env


def run_cli(argv: list, key: str = "") -> dict:
    """Execute the bundled CLI. Never raises — always returns a result dict."""
    if not isinstance(argv, list) or not argv:
        return {"exit": 2, "stdout": "", "stderr": "argv must be a non-empty list",
                "duration_ms": 0}
    if len(argv) > MAX_ARGV:
        return {"exit": 2, "stdout": "", "stderr": f"too many argv tokens (>{MAX_ARGV})",
                "duration_ms": 0}
    for tok in argv:
        if isinstance(tok, str) and any(c in tok for c in _BAD_CHARS):
            return {"exit": 2, "stdout": "", "stderr": f"invalid token: {tok!r}",
                    "duration_ms": 0}

    cmd = [PY, str(CLI_PATH), *[str(a) for a in argv]]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=str(SCRATCH), capture_output=True, text=True,
            timeout=TIMEOUT_S, env=build_env(key),
        )
        return {
            "exit": int(proc.returncode),
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"exit": 124, "stdout": "",
                "stderr": f"timeout after {TIMEOUT_S}s — this skill needs more than the function budget",
                "duration_ms": TIMEOUT_S * 1000}
    except Exception as exc:  # pragma: no cover - defensive
        return {"exit": 1, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}",
                "duration_ms": 0}


_RUN_ID_PREFIX = "#RUN_ID"


def split_run_id(stdout: str) -> tuple[str, str]:
    """Split the CLI output into ``(run_id, body)``."""
    text = stdout or ""
    if not text.startswith(_RUN_ID_PREFIX):
        return "", text
    head, _, body = text.partition("\n")
    parts = head.split()
    run_id = parts[1] if len(parts) > 1 else ""
    return run_id, body


def read_meta(stdout: str) -> dict:
    """Pull ``cu=`` out of the ``#RUN_ID`` header line."""
    meta = {"cu": None}
    if (stdout or "").startswith(_RUN_ID_PREFIX):
        head = stdout.split("\n", 1)[0]
        for tok in head.split():
            if tok.startswith("cu="):
                try:
                    meta["cu"] = int(tok[3:])
                except ValueError:
                    pass
    return meta


def extract_html(body: str) -> str:
    """Rendered format emits a JSON envelope carrying an ``html`` field.

    Returns ``""`` when the payload carries no HTML, so the caller can fall
    back to a plain-text rendering.
    """
    text = (body or "").strip()
    if not text:
        return ""
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except Exception:
            return ""
        if isinstance(obj, dict):
            for field in ("html", "rendered_html"):
                val = obj.get(field)
                if isinstance(val, str) and val.strip():
                    return val
        return ""
    return text if text.startswith("<") else ""


# Not every skill accepts `--format rendered`; token-dd/rugcheck/smart-wallets
# use `render`, trending-list falls back to `plain`. argparse rejects an
# unknown choice before any API call, so probing costs 0 CU.
FORMAT_CHAIN = ("rendered", "render", "plain")


def strip_format(argv: list) -> list:
    out = [str(a) for a in argv]
    while "--format" in out:
        i = out.index("--format")
        del out[i:i + 2]
    return out


def run_skill(argv: list, key: str) -> tuple[dict, str]:
    """Run the CLI, probing the format chain until one is accepted."""
    base = strip_format(argv)
    res: dict = {"exit": 2, "stdout": "", "stderr": "no format candidate", "duration_ms": 0}
    used = FORMAT_CHAIN[0]
    for fmt in FORMAT_CHAIN:
        used = fmt
        res = run_cli(base + ["--format", fmt], key)
        if res.get("exit") == 0:
            return res, used
        # Only an unmapped format is worth retrying; anything else is a real error.
        if "invalid choice" not in (res.get("stderr") or ""):
            return res, used
    return res, used


def collect_formats(run_id: str, rendered_body: str) -> dict:
    """Render every other format from cache — always 0 CU.

    ``history-render`` reads the run the CLI just wrote, so no extra API
    calls are made. It can fail when the cache file is missing (e.g. a
    different warm instance); the caller degrades gracefully.
    """
    out = {
        "ui": extract_html(rendered_body),
        "json": "",
        "telegram": "",
        "plain": "",
    }
    if not run_id:
        return out
    for fmt, field in (("raw-json", "json"), ("telegram", "telegram"), ("plain", "plain")):
        res = run_cli(["history-render", "--run-id", run_id, "--format", fmt])
        if res.get("exit") == 0:
            out[field] = (res.get("stdout") or "").strip()
    return out
