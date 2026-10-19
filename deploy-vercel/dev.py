#!/usr/bin/env python3
"""Local dev server for the Vercel test console (stdlib only).

Mirrors the Vercel routing so you can develop without the `vercel` CLI:

    python3 dev.py --port 8787        # -> http://127.0.0.1:8787

Locally the server env key is allowed, so you can run skills without
pasting a key. Key lookup order: process env -> ./.env -> ../birdeye-screener/.env
"""
from __future__ import annotations

import argparse
import http.server
import importlib.util
import json
import os
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
API = HERE / "api"
PUBLIC = HERE / "public"


def load_dotenv() -> None:
    """Populate os.environ from .env files (existing vars always win)."""
    for path in (HERE / ".env", HERE.parent / "birdeye-screener" / ".env"):
        try:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
        except Exception as exc:  # pragma: no cover - best effort
            sys.stderr.write(f"[dev] dotenv {path}: {exc}\n")


load_dotenv()
sys.path.insert(0, str(API))


def load_function(name: str):
    spec = importlib.util.spec_from_file_location(name, API / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


RUN = load_function("run")
META = load_function("meta")


class Router(http.server.BaseHTTPRequestHandler):
    """Dispatches to the same handler classes Vercel uses."""

    server_version = "BirdeyeDev/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[dev] " + (fmt % args) + "\n")

    def _json(self, code, obj):
        """Required by the delegated api/*.py handlers."""
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path: pathlib.Path, ctype: str):
        try:
            data = path.read_bytes()
        except Exception as exc:
            self.send_error(404, f"{path.name}: {exc}")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):  # noqa: N802
        RUN.handler.do_OPTIONS(self)

    def do_GET(self):  # noqa: N802
        p = urllib.parse.urlparse(self.path).path
        if p.startswith("/api/meta"):
            return META.handler.do_GET(self)
        if p.startswith("/api/run"):
            return RUN.handler.do_GET(self)
        if p in ("/", "/index.html"):
            return self._static(PUBLIC / "index.html", "text/html; charset=utf-8")
        self.send_error(404, "not found")

    def do_POST(self):  # noqa: N802
        p = urllib.parse.urlparse(self.path).path
        if p.startswith("/api/run"):
            return RUN.handler.do_POST(self)
        self.send_error(404, "not found")


def main() -> None:
    ap = argparse.ArgumentParser(description="Local dev server for the Vercel test console")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    srv = http.server.ThreadingHTTPServer((args.host, args.port), Router)
    sys.stderr.write(f"[dev] test console -> http://{args.host}:{args.port}/  (Ctrl+C to stop)\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[dev] stopped.\n")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
