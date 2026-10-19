"""POST /api/run — execute one Birdeye skill and return every output format.

Request  : {"argv": ["kline-pattern", "--chain", "sol", ...], "key": "<birdeye key>"}
Response : {"exit", "runId", "cu", "duration_ms", "html", "formats", "stderr"}

The CLI is invoked exactly once (real CU spend). Extra formats are replayed
from the run cache via `history-render`, which costs 0 CU.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib import (  # noqa: E402
    ALLOWED_SCRIPTS, CLI_PATH, ENV_KEY_ALLOWED, IS_SERVERLESS, TIMEOUT_S,
    collect_formats, read_meta, resolve_key, run_skill, split_run_id,
)

MAX_BODY = 256 * 1024


class handler(BaseHTTPRequestHandler):
    server_version = "BirdeyeVercel/1.0"

    # ── plumbing ────────────────────────────────────────────────────────────
    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Allow", "POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        self._json(405, {"error": "use POST"})

    # ── main ────────────────────────────────────────────────────────────────
    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._json(413, {"error": "payload too large"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception as exc:
            self._json(400, {"error": f"bad json: {exc}"})
            return

        script = body.get("script") or "birdeye_cli"
        if script not in ALLOWED_SCRIPTS:
            self._json(400, {"error": f"script not allowed: {script}"})
            return
        argv = body.get("argv")
        if not isinstance(argv, list):
            self._json(400, {"error": "argv must be a list"})
            return
        argv = [str(a) for a in argv]

        key, source = resolve_key(body.get("key") or "")
        if not key:
            self._json(400, {
                "error": "api_key_required",
                "message": "Paste your Birdeye API key to run skills on this deployment.",
            })
            return

        # Each skill accepts a different set of formats, so let the CLI pick
        # (`rendered` -> `render` -> `plain`). Probing costs 0 CU because an
        # unknown format is rejected by argparse before any API call.
        if not CLI_PATH.exists():
            self._json(500, {"error": "cli_missing", "path": str(CLI_PATH)})
            return

        res, fmt_used = run_skill(argv, key)
        run_id, rendered_body = split_run_id(res.get("stdout", ""))
        meta = read_meta(res.get("stdout", ""))

        if res.get("exit") == 0:
            formats = collect_formats(run_id, rendered_body)
        else:
            formats = {"ui": "", "json": "", "telegram": "", "plain": ""}
        html = formats["ui"]
        text = "" if html else rendered_body.strip()

        self._json(200, {
            "exit": res.get("exit"),
            "runId": run_id,
            "cu": meta.get("cu"),
            "duration_ms": res.get("duration_ms"),
            "format_used": fmt_used,
            "key_source": source,
            "serverless": IS_SERVERLESS,
            "env_key_allowed": ENV_KEY_ALLOWED,
            "timeout_s": TIMEOUT_S,
            "html": html,
            "text": text,
            "formats": formats,
            "stderr": res.get("stderr", ""),
            # raw stdout helps debugging when no run_id could be parsed
            "stdout": "" if run_id else (res.get("stdout") or "")[:8000],
        })

    def log_message(self, fmt, *args):  # keep Vercel logs readable
        sys.stderr.write("[run] " + (fmt % args) + "\n")
