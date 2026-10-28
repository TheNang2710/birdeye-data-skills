#!/usr/bin/env python3
"""Birdeye Skills CLI — a thin client for the hosted Birdeye scoring engine.

You only need a **Birdeye API key**: this command resolves the key, forwards the
skill request to the scoring engine and prints the result. The scoring formulas,
weights and model assets are not part of this repository — they run inside the
engine service.

    birdeye-cli config --apply <KEY>                             # store the key once
    birdeye-cli token-dd-score --chain sol --address <MINT>      # run a skill
    birdeye-cli trending-list --chain solana --interval 24h --format plain

Every skill command supports `--format` (default `plain` on the terminal):
`plain` · `json` · `telegram` · `raw-json` · `ui`.

Exit codes
    0  success
    1  no Birdeye API key configured (run `config --apply <KEY>`)
    2  bad usage (unknown command / missing flag value)
    4  engine unreachable or engine-side error
    other  exit code returned by the scoring engine for the skill

Environment
    BIRDEYE_API_KEY   Birdeye API key (highest priority)
    BIRDEYE_ENGINE    override the engine base URL
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import sys
import urllib.error
import urllib.request

try:  # restore default SIGPIPE so `| head` exits quietly (no-op on Windows)
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass

__version__ = "1.0.0"

DEFAULT_ENGINE = "https://birdeye-score-engine.vercel.app"
DEFAULT_TIMEOUT = 180

CONFIG_DIR = pathlib.Path.home() / ".config" / "birdeye"
CONFIG_FILE = CONFIG_DIR / ".env"
LEGACY_FILE = pathlib.Path.home() / ".birdeye.env"

# Formats the hosted engine can return; `ui` is the HTML console payload.
FORMATS = ("plain", "json", "telegram", "raw-json", "ui", "rendered", "render", "compact")

SKILLS = (
    "token-dd-score",
    "trending-list",
    "price-surge",
    "wallet-score",
    "wallet-style",
    "kline-pattern",
    "token-trending-score",
    "junk-predict",
    "junk-quick-test",
)

USAGE = """\
Birdeye Skills CLI {ver} — on-chain discovery & insight from your terminal

Usage
  birdeye-cli <skill> [flags] [--format <fmt>]
  birdeye-cli config --check | --status | --apply <KEY>
  birdeye-cli <skill> --help            # full flag list for one skill

Skills
  token-dd-score          token due-diligence score 0-100 + A+..F risk rating
  trending-list           Birdeye hot-token leaderboard (no local scoring)
  price-surge             market-cap-banded surge screen with auto rug/wash/honeypot filter
  wallet-score            wallet alpha + copy-tradeability score
  wallet-style            trading-style tagger (scalper vs swing)
  kline-pattern           candlestick pattern classifier + 0..100 score
  token-trending-score    0..100 momentum score per interval
  junk-predict            ML junk-token score (batch)
  junk-quick-test         junk-score N random tokens (model spot-check)

Formats
  plain (default) · json · telegram · raw-json · ui

Global flags (this client)
  --key <KEY>        use this Birdeye key for the run (overrides config)
  --engine <URL>     point at a different scoring engine
  --timeout <sec>    request timeout (default {timeout})
  -h, --help         show this help
  -V, --version      show the version

Setup
  1. Get a Birdeye API key (an account on https://birdeye.so).
  2. birdeye-cli config --apply <KEY>
  3. birdeye-cli config --check     # exit 0 = ready

Examples
  birdeye-cli trending-list --chain solana --interval 24h --limit 20 --format plain
  birdeye-cli token-dd-score --chain sol --address <MINT> --mode advanced --format json
  birdeye-cli wallet-score --chain sol --wallet <ADDR> --duration 30d --format plain
"""


# ── key handling ────────────────────────────────────────────────────────────
def _read_key_from(path: pathlib.Path) -> str:
    try:
        if not path.exists():
            return ""
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("BIRDEYE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return ""
    return ""


def resolve_key() -> tuple[str, str, str]:
    """Return ``(key, source, path)`` using the documented resolution order."""
    if k := (os.environ.get("BIRDEYE_API_KEY") or "").strip():
        return k, "$BIRDEYE_API_KEY", ""
    for source, path in (
        (str(CONFIG_FILE), CONFIG_FILE),
        (str(LEGACY_FILE), LEGACY_FILE),
        ("./.env", pathlib.Path(".env")),
    ):
        if k := _read_key_from(path):
            return k, source, str(path)
    return "", "", ""


def mask(key: str) -> str:
    if not key:
        return ""
    return f"{key[:2]}****{key[-2:]}" if len(key) > 6 else "****"


def cmd_config(args: list) -> int:
    action = "check"
    value = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--check":
            action = "check"
        elif a == "--status":
            action = "status"
        elif a == "--apply":
            action = "apply"
            value = args[i + 1] if i + 1 < len(args) else None
            i += 1
        elif a.startswith("--apply="):
            action = "apply"
            value = a.split("=", 1)[1]
        else:
            print(f"unknown config flag: {a}", file=sys.stderr)
            return 2
        i += 1

    key, source, path = resolve_key()

    if action == "apply":
        if not value or not value.strip():
            print("usage: birdeye-cli config --apply <KEY>", file=sys.stderr)
            return 2
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(f"BIRDEYE_API_KEY={value.strip()}\n", encoding="utf-8")
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            pass
        print(f"saved Birdeye API key ({mask(value.strip())}) -> {CONFIG_FILE}")
        return 0

    if action == "status":
        if key:
            print(f"key      : {mask(key)}")
            print(f"source   : {source}")
            if path:
                print(f"path     : {path}")
        else:
            print("key      : (none)")
        print("resolve  : $BIRDEYE_API_KEY -> ~/.config/birdeye/.env -> ~/.birdeye.env -> ./.env")
        print(f"engine   : {os.environ.get('BIRDEYE_ENGINE') or DEFAULT_ENGINE}")
        return 0 if key else 1

    # --check
    if key:
        print(f"ok: Birdeye API key resolvable ({mask(key)}) from {source}")
        return 0
    print("no Birdeye API key found — run: birdeye-cli config --apply <KEY>", file=sys.stderr)
    return 1


# ── engine call ─────────────────────────────────────────────────────────────
def requested_format(argv: list) -> str:
    fmt = "plain"
    for i, tok in enumerate(argv):
        if tok == "--format" and i + 1 < len(argv):
            fmt = argv[i + 1]
        elif tok.startswith("--format="):
            fmt = tok.split("=", 1)[1]
    return fmt


def pick_output(payload: dict, fmt: str) -> str:
    """Map the requested format onto the engine response."""
    formats = payload.get("formats") or {}
    if fmt in ("ui", "rendered", "render"):
        return payload.get("html") or formats.get("ui") or payload.get("text") or ""
    if fmt in ("json", "raw-json"):
        return formats.get("json") or payload.get("text") or ""
    if fmt == "telegram":
        return formats.get("telegram") or payload.get("text") or ""
    # plain / compact
    return formats.get("plain") or payload.get("text") or ""


def call_engine(engine: str, key: str, argv: list, timeout: int) -> tuple[int, str]:
    url = engine.rstrip("/") + "/api/run"
    body = json.dumps({"script": "birdeye_cli", "argv": argv, "key": key}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.read() or b"").decode("utf-8", "replace")
    except Exception as exc:
        return 0, json.dumps({"error": "engine_unreachable", "message": str(exc)})


# ── argument handling ───────────────────────────────────────────────────────
def split_globals(argv: list) -> tuple[dict, list]:
    """Pull client-only flags out of argv; everything else is forwarded."""
    opts = {"key": "", "engine": "", "timeout": DEFAULT_TIMEOUT}
    rest: list = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--key" and i + 1 < len(argv):
            opts["key"] = argv[i + 1]; i += 2; continue
        if a.startswith("--key="):
            opts["key"] = a.split("=", 1)[1]; i += 1; continue
        if a == "--engine" and i + 1 < len(argv):
            opts["engine"] = argv[i + 1]; i += 2; continue
        if a.startswith("--engine="):
            opts["engine"] = a.split("=", 1)[1]; i += 1; continue
        if a == "--timeout" and i + 1 < len(argv):
            try:
                opts["timeout"] = int(argv[i + 1])
            except ValueError:
                pass
            i += 2; continue
        if a.startswith("--timeout="):
            try:
                opts["timeout"] = int(a.split("=", 1)[1])
            except ValueError:
                pass
            i += 1; continue
        rest.append(a)
        i += 1
    return opts, rest


def main(argv: list) -> int:
    if not argv:
        print(USAGE.format(ver=__version__, timeout=DEFAULT_TIMEOUT))
        return 0
    if argv[0] in ("-h", "--help", "help"):
        print(USAGE.format(ver=__version__, timeout=DEFAULT_TIMEOUT))
        return 0
    if argv[0] in ("-V", "--version", "version"):
        print(f"birdeye-cli {__version__}")
        return 0

    opts, rest = split_globals(argv)
    if not rest:
        print(USAGE.format(ver=__version__, timeout=DEFAULT_TIMEOUT))
        return 0

    if rest[0] == "config":
        return cmd_config(rest[1:])

    # Engine URL: --engine > $BIRDEYE_ENGINE > default
    engine = opts["engine"] or os.environ.get("BIRDEYE_ENGINE") or DEFAULT_ENGINE

    key = opts["key"].strip()
    if not key:
        key, _source, _path = resolve_key()
    if not key:
        print("no Birdeye API key found — run: birdeye-cli config --apply <KEY>", file=sys.stderr)
        return 1

    fmt = requested_format(rest)
    status, raw = call_engine(engine, key, rest, opts["timeout"])

    if status == 0:
        try:
            err = json.loads(raw).get("message") or raw
        except Exception:
            err = raw
        print(f"engine error: {err}", file=sys.stderr)
        return 4

    try:
        payload = json.loads(raw)
    except Exception:
        # Not JSON (e.g. a proxy 5xx HTML page) — surface it verbatim.
        sys.stdout.write(raw)
        if raw and not raw.endswith("\n"):
            sys.stdout.write("\n")
        return 4 if status >= 400 else 0

    if payload.get("error"):
        msg = payload.get("message") or payload.get("error")
        print(f"engine error ({status}): {msg}", file=sys.stderr)
        return 4

    out = pick_output(payload, fmt)
    if out:
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
    if payload.get("stderr"):
        sys.stderr.write(payload["stderr"] if payload["stderr"].endswith("\n") else payload["stderr"] + "\n")

    exit_code = payload.get("exit")
    return int(exit_code) if isinstance(exit_code, int) else 0


def cli() -> None:
    """Console-script entry point (`birdeye-cli`)."""
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    cli()
