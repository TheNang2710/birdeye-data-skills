#!/usr/bin/env python3
"""Birdeye Skills — local console (public shell).

Zero dependencies (stdlib only). Serves the console UI from ./public and
proxies every skill request to the private scoring engine; the scoring
formulas and model assets deliberately do not live in this repository.

    python3 server.py                      # http://127.0.0.1:8765
    python3 server.py --port 8765 --host 0.0.0.0
    python3 server.py --engine https://... # override the engine endpoint

API surface
    GET  /                 public/index.html (console v2)
    GET  /v1               frozen v1 console (public/v1.html)
    GET  /v2               alias of /
    GET  /assets/*         static assets
    GET  /health           liveness probe
    GET  /api/meta         runtime capabilities
    GET  /api/key-info     masked key state
    POST /api/run          {script, argv, key} -> engine response
    POST /api/set-key      {key, action=apply|clear|save}
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
PUBLIC = HERE / "public"
DOCS = HERE / "docs"
ENV_FILE = HERE / ".env"
TIMEOUT_S = 180

# The scoring engine owns every formula and model asset. This shell only
# forwards requests; point ENGINE_URL elsewhere to use a self-hosted engine.
ENGINE_URL = (os.environ.get("ENGINE_URL") or "https://birdeye-score-engine.vercel.app").rstrip("/")
UPSTREAM_RUN = ENGINE_URL + "/api/run"

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


# ── engine proxy ─────────────────────────────────────────────────────────────
def proxy_run(raw: bytes) -> tuple[int, bytes]:
    """Forward a /api/run request to the engine and return its raw response."""
    req = urllib.request.Request(
        UPSTREAM_RUN,
        data=raw,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), (exc.read() or b"")
    except Exception as exc:  # pragma: no cover - defensive
        payload = json.dumps({"error": "engine_unreachable", "message": str(exc),
                              "engine": ENGINE_URL}).encode("utf-8")
        return 502, payload


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

        if path in ("/", "/index.html", "/v2"):
            data = self._read_bytes(PUBLIC / "index.html")
            if data is None:
                self._json(500, {"error": "public/index.html missing"})
                return
            self._send(200, data, MIME[".html"])
            return

        if path in ("/v1", "/v1.html"):
            data = self._read_bytes(PUBLIC / "v1.html")
            if data is None:
                self._json(500, {"error": "public/v1.html missing"})
                return
            self._send(200, data, MIME[".html"])
            return

        if path == "/health":
            self._json(200, {"ok": True, "root": str(HERE), "engine": ENGINE_URL})
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
                "engine": ENGINE_URL,
                "engine_remote": True,
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
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception as e:
                self._json(400, {"error": f"bad json: {e}"})
                return
            # Local convenience: fall back to a key from .env / the session
            # when the request does not carry one (the engine requires a key).
            if not payload.get("key"):
                key, _ = resolve_key()
                if key:
                    payload["key"] = key
                    raw = json.dumps(payload).encode("utf-8")
            code, body = proxy_run(raw)
            self._send(code, body, "application/json; charset=utf-8")
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
    sys.stderr.write(f"[srv] engine: {ENGINE_URL}\n")
    sys.stderr.write(f"[srv] key: {'set via ' + src if key else 'not set (paste it in the UI)'}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[srv] stopped\n")
        srv.server_close()


def main():
    global ENGINE_URL, UPSTREAM_RUN
    ap = argparse.ArgumentParser(description="Birdeye Skills local console")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--engine", default=None, help="override the scoring engine URL")
    ap.add_argument("--reload", action="store_true", help="kept for parity; static files are always re-read")
    args = ap.parse_args()
    if args.engine:
        ENGINE_URL = args.engine.rstrip("/")
        UPSTREAM_RUN = ENGINE_URL + "/api/run"
    serve(args.host, args.port, hot=args.reload)


if __name__ == "__main__":
    main()
