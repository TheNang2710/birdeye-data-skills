"""POST /api/run — thin proxy to the private scoring engine.

The public deployment ships **no scoring code**: the formulas, weights and
model assets live in a separate (private) engine service. This handler
forwards the request body unchanged and returns the engine's JSON verbatim,
so the console is unaware of where the work actually happens.

The engine URL is configurable via the ``ENGINE_URL`` env var; the default
points at the hosted engine.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

ENGINE_URL = (os.environ.get("ENGINE_URL") or "https://birdeye-score-engine.vercel.app").rstrip("/")
UPSTREAM = ENGINE_URL + "/api/run"
TIMEOUT_S = int(os.environ.get("ENGINE_TIMEOUT_S") or 58)
MAX_BODY = 256 * 1024


class handler(BaseHTTPRequestHandler):
    server_version = "BirdeyeShell/2.0"

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
        raw = self.rfile.read(length) if length else b"{}"
        try:
            json.loads(raw.decode("utf-8") or "{}")
        except Exception as exc:
            self._json(400, {"error": f"bad json: {exc}"})
            return

        req = urllib.request.Request(
            UPSTREAM,
            data=raw,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                body, code = resp.read(), resp.status
        except urllib.error.HTTPError as exc:
            body, code = (exc.read() or b""), exc.code
        except Exception as exc:
            self._json(502, {
                "error": "engine_unreachable",
                "message": str(exc),
                "engine": ENGINE_URL,
            })
            return

        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep Vercel logs readable
        sys.stderr.write("[proxy] " + (fmt % args) + "\n")
