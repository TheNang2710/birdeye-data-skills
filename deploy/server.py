#!/usr/bin/env python3
"""Birdeye Skills — Deployable Test Console (minimal server).

Serves a self-contained test page that runs the Birdeye CLI as a subprocess.
No source code is exposed — only the test UI + JSON results.

Run:
    cd /path/to/deploy
    python3 server.py --port 8675

Deploy notes:
  * The server resolves `birdeye_cli.py` relative to this file's location
    (../birdeye-screener/scripts/birdeye_cli.py). Override with
    --cli-path if your layout differs.
  * API key priority: UI-set session key -> env BIRDEYE_API_KEY
    -> ~/.birdeye.env -> ../birdeye-screener/.env
  * --host 0.0.0.0 exposes to LAN; use behind a reverse proxy + auth for
    public deployment.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
ASSETS = REPO / "assets"
DEFAULT_CLI = REPO / "birdeye-screener" / "scripts" / "birdeye_cli.py"
PY = sys.executable

# Import the lean test console HTML (served at /test)
try:
    TEST_UI_HTML = (ASSETS / "test.html").read_text(encoding="utf-8")
except Exception as _e:
    TEST_UI_HTML = f"<html><body><pre>Test UI unavailable: {_e}</pre></body></html>"

# Import skill catalog for /api/catalog (hub home uses this to render cards)
sys.path.insert(0, str(REPO / "birdeye-screener" / "scripts"))
try:
    from build_skill_catalog_csv import BUILTIN_CATALOG  # noqa: E402
except Exception:
    BUILTIN_CATALOG = []

# Session-only key (set via UI -> /api/set-key; NOT persisted unless persist=true)
_SESSION_KEY: dict[str, str] = {"key": ""}

ALLOWED_SCRIPTS = {"birdeye_cli"}  # whitelist — no arbitrary script execution


def resolve_key() -> tuple[str, str]:
    """Return (key, source)."""
    if _SESSION_KEY["key"]:
        return _SESSION_KEY["key"], "UI session"
    if k := os.environ.get("BIRDEYE_API_KEY"):
        return k, "env BIRDEYE_API_KEY"
    for p in (pathlib.Path.home() / ".birdeye.env", REPO / "birdeye-screener" / ".env"):
        if p.exists():
            try:
                for ln in p.read_text(encoding="utf-8").splitlines():
                    ln = ln.strip()
                    if ln.startswith("BIRDEYE_API_KEY="):
                        v = ln.split("=", 1)[1].strip().strip('"').strip("'")
                        if v:
                            return v, str(p)
            except Exception:
                pass
    return "", "none"


def run_cli(argv: list[str], cli_path: pathlib.Path) -> dict:
    # basic argv safety: no shell metachars in any token (newlines allowed for multi-line inputs)
    for tok in argv:
        if isinstance(tok, str) and any(c in tok for c in ";&|`$<>\\'\""):
            return {"exit": 2, "stdout": "", "stderr": f"invalid token: {tok!r}", "duration_ms": 0}
    key, _src = resolve_key()
    env = {**os.environ}
    if key:
        env["BIRDEYE_API_KEY"] = key
    cmd = [PY, str(cli_path), *[str(a) for a in argv]]
    t0 = __import__("time").perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                              timeout=180, env=env)
        dur = int((__import__("time").perf_counter() - t0) * 1000)
        return {"exit": int(proc.returncode), "stdout": proc.stdout or "",
                "stderr": proc.stderr or "", "duration_ms": dur}
    except subprocess.TimeoutExpired:
        return {"exit": 124, "stdout": "", "stderr": "timeout 180s", "duration_ms": 180000}
    except Exception as e:
        return {"exit": 1, "stdout": "", "stderr": str(e), "duration_ms": 0}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "BirdeyeDeploy/1.0"
    cli_path: pathlib.Path = DEFAULT_CLI

    def log_message(self, fmt, *args):
        sys.stderr.write("[deploy] " + (fmt % args) + "\n")

    def _send_json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, code, html_bytes):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html_bytes)

    def _serve_asset(self, name, content_type=None):
        """Serve a static file from assets/."""
        path = ASSETS / name
        try:
            data = path.read_bytes()
        except Exception as e:
            self._send_html(404, f"<html><body><pre>asset not found: {name} ({e})</pre></body></html>".encode())
            return
        if content_type is None:
            ext = path.suffix.lower()
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
            }.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send_json(204, {})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path

        # ── Hub static assets (served from assets/) ──
        if p in ("/", "/home.html"):
            self._serve_asset("home.html")
            return
        if p == "/detail.html":
            self._serve_asset("detail.html")
            return
        if p == "/hub.js":
            self._serve_asset("hub.js", "application/javascript; charset=utf-8")
            return
        if p == "/hub.css":
            self._serve_asset("hub.css", "text/css; charset=utf-8")
            return
        if p in ("/test", "/test/"):
            try:
                self._send_html(200, (ASSETS / "test.html").read_bytes())
            except Exception:
                self._send_html(200, TEST_UI_HTML.encode("utf-8"))
            return
        if p.startswith("/docs/") or p.startswith("/API/"):
            safe = p.lstrip("/").replace("..", "_")
            fp = (REPO / safe).resolve()
            try:
                fp.relative_to(REPO)
            except Exception:
                self._send_html(403, b"<html><body><pre>forbidden</pre></body></html>")
                return
            if not fp.is_file():
                self._send_html(404, b"<html><body><pre>doc not found</pre></body></html>")
                return
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if p == "/health":
            self._send_json(200, {"ok": True, "cwd": str(REPO),
                                  "cli": str(Handler.cli_path),
                                  "cli_exists": Handler.cli_path.exists()})
            return
        if p == "/api/key-info":
            k, src = resolve_key()
            h2 = k[:2] if k else ""
            t2 = k[-2:] if k else ""
            self._send_json(200, {"key_set": bool(k), "source": src,
                                  "head": h2, "tail": t2,
                                  "mask": f"{h2}****{t2}" if k else ""})
            return
        if p == "/api/catalog":
            self._send_json(200, {"items": BUILTIN_CATALOG})
            return
        if p == "/api/ai-key-info":
            self._send_json(200, {"providers": {}})
            return
        if p == "/api/history/list":
            qs = urllib.parse.parse_qs(parsed.query)
            limit = int((qs.get("limit") or ["30"])[0])
            res = run_cli(["history-list", "--limit", str(limit), "--format", "raw-json"], Handler.cli_path)
            items = []
            if res.get("exit") == 0 and (res.get("stdout") or "").strip():
                try:
                    parsed_list = json.loads(res["stdout"].strip())
                    if isinstance(parsed_list, dict):
                        items = parsed_list.get("items") or parsed_list.get("results") or []
                    elif isinstance(parsed_list, list):
                        items = parsed_list
                except Exception:
                    items = []
            self._send_json(200, {"items": items if isinstance(items, list) else []})
            return
        if parsed.path == "/api/history/render":
            qs = urllib.parse.parse_qs(parsed.query)
            run_id = (qs.get("runId") or qs.get("run_id") or [""])[0]
            fmt = (qs.get("format") or ["render"])[0]
            if not run_id:
                self._send_json(400, {"error": "runId required"})
                return
            if fmt not in {"render", "plain", "telegram", "raw-json"}:
                fmt = "render"
            res = run_cli(["history-render", "--run-id", run_id, "--format", fmt], Handler.cli_path)
            if fmt == "render":
                out_obj = {"success": False, "cached": True, "cu_used_total": 0}
                if res.get("exit") == 0 and (res.get("stdout") or "").strip():
                    try:
                        out_obj = json.loads(res["stdout"].strip())
                    except Exception as e:
                        out_obj["error"] = f"parse fail: {e}"
                        out_obj["raw"] = res.get("stdout", "")[:1000]
                else:
                    out_obj["error"] = res
                self._send_json(200, out_obj)
                return
            self._send_json(200, {"runId": run_id, "format": fmt, "exit": res.get("exit"),
                                   "stdout": res.get("stdout", ""), "stderr": res.get("stderr", ""),
                                   "duration_ms": res.get("duration_ms", 0)})
            return
        if parsed.path == "/api/history/delete":
            qs = urllib.parse.parse_qs(parsed.query)
            run_id = (qs.get("runId") or qs.get("run_id") or [""])[0]
            if run_id:
                run_cli(["history-delete", "--run-id", run_id], Handler.cli_path)
            self._send_json(200, {"ok": True})
            return
        # No static file serving beyond hub assets — prevents code leakage
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"error": f"bad json: {e}"})
            return

        if parsed.path == "/api/run":
            script = body.get("script") or "birdeye_cli"
            argv = body.get("argv") or []
            if script not in ALLOWED_SCRIPTS:
                self._send_json(400, {"error": f"script not allowed: {script}"})
                return
            if not isinstance(argv, list):
                self._send_json(400, {"error": "argv must be list"})
                return
            res = run_cli(argv, Handler.cli_path)
            self._send_json(200, res)
            return

        if parsed.path == "/api/set-key":
            val = (body.get("key") or "").strip()
            persist = bool(body.get("persist"))
            if not val:
                self._send_json(400, {"error": "empty key"})
                return
            _SESSION_KEY["key"] = val
            if persist:
                env_path = pathlib.Path.home() / ".birdeye.env"
                existing = ""
                if env_path.exists():
                    try:
                        existing = env_path.read_text(encoding="utf-8")
                    except Exception:
                        existing = ""
                lines = [ln for ln in existing.splitlines()
                         if not ln.strip().startswith("BIRDEYE_API_KEY=")]
                lines.append(f"BIRDEYE_API_KEY={val}")
                try:
                    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    os.chmod(env_path, 0o600)
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
                    return
            self._send_json(200, {"ok": True, "persisted": persist})
            return

        if parsed.path == "/api/set-ai-key":
            self._send_json(200, {"ok": True, "note": "AI key not persisted in deploy mode"})
            return

        self._send_json(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8675)
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--cli-path", type=str, default=str(DEFAULT_CLI),
                    help="Path to birdeye_cli.py")
    args = ap.parse_args()
    Handler.cli_path = pathlib.Path(args.cli_path).resolve()
    if not Handler.cli_path.exists():
        sys.stderr.write(f"[deploy] WARNING: CLI not found at {Handler.cli_path}\n")
    srv = http.server.HTTPServer((args.host, args.port), Handler)
    sys.stderr.write(f"[deploy] Birdeye Test Console → http://{args.host}:{args.port}\n")
    sys.stderr.write(f"[deploy] CLI: {Handler.cli_path}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[deploy] stopped.\n")
        srv.server_close()


if __name__ == "__main__":
    main()
