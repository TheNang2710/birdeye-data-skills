"""GET /api/meta — runtime capabilities for the console UI.

Tells the UI whether it may rely on a server-side env key (local dev) or
whether the visitor must paste their own key (public deployment).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib import (  # noqa: E402
    CLI_PATH, ENV_KEY_ALLOWED, IS_SERVERLESS, ROOT, TIMEOUT_S, find_env_key, mask,
)

# The ML assets live beside the CLI in modules/ and are shipped via
# vercel.json includeFiles — flag them so a bad deploy is visible immediately.
ML_READY = (ROOT / "modules" / "lr_params.json").exists()
FUNCTION_READY = (ROOT / "modules" / "junk_function_params.json").exists()


class handler(BaseHTTPRequestHandler):
    server_version = "BirdeyeVercel/1.0"

    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        env_key = find_env_key() if ENV_KEY_ALLOWED else ""
        self._json(200, {
            "serverless": IS_SERVERLESS,
            "env_key_allowed": ENV_KEY_ALLOWED,
            "env_key_present": bool(env_key),
            "env_key_mask": mask(env_key),
            # The UI blocks Run until a key exists when this is true.
            "key_required": not bool(env_key),
            "timeout_s": TIMEOUT_S,
            "cli_ready": CLI_PATH.exists(),
            "ml_ready": ML_READY,
            "function_ready": FUNCTION_READY,
        })

    def log_message(self, fmt, *args):
        sys.stderr.write("[meta] " + (fmt % args) + "\n")
