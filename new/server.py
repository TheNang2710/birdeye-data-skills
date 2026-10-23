#!/usr/bin/env python3
"""Birdeye Skills — standalone local console.

Zero dependencies (stdlib only). Serves the console UI from ./public and runs
./birdeye_cli.py for every skill so the browser never talks to Birdeye directly.

    python3 server.py                      # http://127.0.0.1:8765
    python3 server.py --port 8765 --host 0.0.0.0
    python3 server.py --reload             # re-read public/ from disk per request

API surface
    GET  /                 public/index.html (console)
    GET  /assets/*         static assets
    GET  /docs/*           workflow markdown
    GET  /health           liveness probe
    GET  /api/meta         runtime capabilities
    GET  /api/key-info     masked key state
    POST /api/run          {script, argv, key} -> {exit, stdout, stderr, ...}
    POST /api/set-key      {key, action=apply|clear|save}
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
PUBLIC = HERE / "public"
DOCS = HERE / "docs"
CLI_PATH = HERE / "birdeye_cli.py"
ENV_FILE = HERE / ".env"
PY = sys.executable
TIMEOUT_S = 180

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}

_SESSION_KEY: dict[str, str] = {"key": ""}


# ── key resolution ───────────────────────────────────────────────────────────
def _read_env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_FILE.exists():
        return out
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def _load_env() -> None:
    """Export .env values into the process env without clobbering real env vars."""
    for k, v in _read_env_file().items():
        os.environ.setdefault(k, v)
    os.environ.setdefault("BIRDEYE_CACHE_DIR", str(HERE / ".cache" / "runs"))


def resolve_key(explicit: str | None = None) -> tuple[str, str]:
    if explicit:
        k = explicit.strip().strip('"').strip("'")
        if k:
            return k, "UI paste (session)"
    if _SESSION_KEY["key"]:
        return _SESSION_KEY["key"], "UI session key"
    if env := os.environ.get("BIRDEYE_API_KEY", "").strip():
        return env, ".env / environment"
    return "", "MISSING"


# ── CLI runner ───────────────────────────────────────────────────────────────
def run_cli(argv: list[str], ui_key: str | None = None) -> dict:
    for tok in argv:
        if isinstance(tok, str) and "\x00" in tok:
            return {"exit": 2, "stdout": "", "stderr": f"invalid token: {tok!r}", "duration_ms": 0}

    sub_env = dict(os.environ)
    key, _ = resolve_key(ui_key)
    if key:
        sub_env["BIRDEYE_API_KEY"] = key

    cmd = [PY, str(CLI_PATH), *argv]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=str(HERE), capture_output=True, text=True,
            timeout=TIMEOUT_S, env=sub_env,
        )
        return {
            "exit": int(proc.returncode),
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"exit": 124, "stdout": "", "stderr": f"timeout {TIMEOUT_S}s",
                "duration_ms": TIMEOUT_S * 1000}
    except Exception as e:  # pragma: no cover - defensive
        return {"exit": 1, "stdout": "", "stderr": str(e), "duration_ms": 0}


# ── HTTP handler ─────────────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "BirdeyeSkillsLocal/1.0"
    hot_reload = False

    def log_message(self, fmt, *args):
        sys.stderr.write("[srv] " + (fmt % args) + "\n")

    # -- helpers ------------------------------------------------------------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

    def _send(self, code: int, body: bytes, mime: str, cache: str = "no-store"):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def _read_bytes(self, fp: pathlib.Path) -> bytes | None:
        try:
            resolved = fp.resolve(strict=True)
            if not resolved.is_file():
                return None
            return resolved.read_bytes()
        except Exception:
            return None

    # -- routes -------------------------------------------------------------
    def do_OPTIONS(self):
        self._json(204, {})

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path in ("/", "/index.html"):
            data = self._read_bytes(PUBLIC / "index.html")
            if data is None:
                self._json(500, {"error": "public/index.html missing"})
                return
            self._send(200, data, MIME[".html"])
            return

        if path == "/health":
            self._json(200, {"ok": True, "root": str(HERE), "cli": CLI_PATH.exists()})
            return

        if path == "/api/meta":
            key, _ = resolve_key()
            self._json(200, {
                "serverless": False,
                "env_key_allowed": True,
                "env_key_present": bool(key),
                "env_key_mask": f"{key[:2]}****{key[-2:]}" if key else "",
                "key_required": not bool(key),
                "timeout_s": TIMEOUT_S,
                "cli_ready": CLI_PATH.exists(),
            })
            return

        if path == "/api/key-info":
            key, src = resolve_key()
            self._json(200, {
                "key_set": bool(key), "source": src,
                "mask": f"{key[:2]}****{key[-2:]}" if key else "",
            })
            return

        if path.startswith("/assets/"):
            self._serve_static(PUBLIC / path.lstrip("/"), PUBLIC)
            return
        if path.startswith("/docs/"):
            self._serve_static(DOCS / path[len("/docs/"):], DOCS)
            return

        self._json(404, {"error": "not found"})

    def _serve_static(self, fp: pathlib.Path, root: pathlib.Path):
        data = self._read_bytes(fp)
        if data is None:
            self._json(404, {"error": "static not found"})
            return
        try:
            fp.resolve().relative_to(root.resolve())
        except Exception:
            self._json(403, {"error": "forbidden"})
            return
        mime = MIME.get(fp.suffix.lower(), "application/octet-stream")
        cache = "no-store" if fp.suffix.lower() in (".md", ".html") else "public, max-age=3600"
        self._send(200, data, mime, cache)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._json(400, {"error": f"bad json: {e}"})
            return

        if path == "/api/run":
            argv = body.get("argv") or []
            if not isinstance(argv, list):
                self._json(400, {"error": "argv must be a list"})
                return
            key = body.get("key") or body.get("uiKey") or None
            self._json(200, run_cli([str(a) for a in argv], key))
            return

        if path == "/api/set-key":
            action = body.get("action") or "apply"
            val = (body.get("key") or "").strip().strip('"').strip("'")
            if action == "clear":
                _SESSION_KEY["key"] = ""
                self._json(200, {"ok": True, "message": "session key cleared"})
                return
            if action == "save":
                if not val:
                    self._json(400, {"error": "empty key"})
                    return
                _write_env_key(val)
                _SESSION_KEY["key"] = val
                self._json(200, {"ok": True, "message": f"saved to {ENV_FILE.name}"})
                return
            _SESSION_KEY["key"] = val
            self._json(200, {"ok": True, "message": "session key set" if val else "session key cleared"})
            return

        self._json(404, {"error": "not found"})


def _write_env_key(val: str) -> None:
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = [ln for ln in ENV_FILE.read_text(encoding="utf-8").splitlines()
                 if not ln.strip().startswith("BIRDEYE_API_KEY=")]
    lines.append(f"BIRDEYE_API_KEY={val}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except Exception:
        pass


def serve(host: str, port: int, hot: bool):
    Handler.hot_reload = hot
    _load_env()
    key, src = resolve_key()
    srv = http.server.ThreadingHTTPServer((host, port), Handler)
    sys.stderr.write(f"[srv] Birdeye Skills → http://{host}:{port}\n")
    sys.stderr.write(f"[srv] cli: {CLI_PATH} ({'ok' if CLI_PATH.exists() else 'MISSING'})\n")
    sys.stderr.write(f"[srv] key: {'set via ' + src if key else 'not set (paste it in the UI)'}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[srv] stopped\n")
        srv.server_close()


def main():
    ap = argparse.ArgumentParser(description="Birdeye Skills local console")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--reload", action="store_true", help="kept for parity; static files are always re-read")
    args = ap.parse_args()
    serve(args.host, args.port, hot=args.reload)


if __name__ == "__main__":
    main()
