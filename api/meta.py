"""GET /api/meta — runtime capabilities for the console UI.

The public shell has no server-side key and no local CLI: every request is
proxied to the engine service, which requires the visitor's own key. The
payload therefore stays static (no engine round-trip on page load).
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

ENGINE_URL = (os.environ.get("ENGINE_URL") or "https://birdeye-score-engine.vercel.app").rstrip("/")


class handler(BaseHTTPRequestHandler):
    server_version = "BirdeyeShell/2.0"

    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._json(200, {
            "serverless": True,
            "env_key_allowed": False,
            "env_key_present": False,
            "env_key_mask": "",
            # The UI blocks Run until a key exists when this is true.
            "key_required": True,
            "timeout_s": 55,
            "engine": ENGINE_URL,
            "engine_remote": True,
        })

    def log_message(self, fmt, *args):
        sys.stderr.write("[meta] " + (fmt % args) + "\n")
