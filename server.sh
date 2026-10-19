#!/usr/bin/env bash
# Birdeye Data Skills — local server control (single process)
#   birdeye_ui.py @ 127.0.0.1:8765   (Hub Home at / · shared test console at /test)
#
# Usage:
#   ./server.sh start        # background (default)
#   ./server.sh stop
#   ./server.sh restart
#   ./server.sh fg           # foreground (Ctrl+C to stop)
#   ./server.sh watch        # auto-restart on file change
#   ./server.sh status
# Env overrides: HOST=0.0.0.0 PORT=8765 WATCH_INTERVAL=2 ./server.sh watch
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"
APP="birdeye_ui.py"
LOG="${LOG:-/tmp/birdeye-hub.log}"; PID="${PID:-/tmp/birdeye-hub.pid}"
WATCH_INTERVAL="${WATCH_INTERVAL:-2}"

busy() { lsof -ti:"$1" >/dev/null 2>&1; }

launch_bg() {
  local port="$1" app="$2" extra="$3" log="$4" pid="$5"
  if busy "$port"; then echo "→ port $port busy, killing old"; lsof -ti:"$port" | xargs kill -9; sleep 1; fi
  nohup python3 "$ROOT/$app" --host "$HOST" --port "$port" $extra >"$log" 2>&1 &
  echo $! >"$pid"
  sleep 2
  if busy "$port"; then echo "✓ http://$HOST:$port/test  (PID $(cat "$pid"))  log: $log"
  else echo "✗ failed on :$port"; tail -n 15 "$log"; fi
}

launch_fg() {
  local port="$1" app="$2" extra="$3"
  if busy "$port"; then echo "→ port $port busy, killing old"; lsof -ti:"$port" | xargs kill -9; sleep 1; fi
  echo "→ foreground http://$HOST:$port/test  · Ctrl+C to stop"
  exec python3 "$ROOT/$app" --host "$HOST" --port "$port" $extra
}

stop_one() {
  if busy "$PORT"; then lsof -ti:"$PORT" | xargs kill -9; echo "✓ stopped :$PORT"
  else echo "• not running :$PORT"; fi
  rm -f "$PID"
}

status() {
  busy "$PORT" && echo "running → http://$HOST:$PORT/test" || echo "stopped"
}

watch_paths() {
  cat <<EOF
$ROOT/birdeye_ui.py
$ROOT/deploy-vercel/public
$ROOT/deploy-vercel/api
$ROOT/birdeye-screener/scripts
$ROOT/docs
$ROOT/API
EOF
}

snapshot() {
  local paths=()
  while IFS= read -r path; do
    [[ -n "$path" && -e "$path" ]] && paths+=("$path")
  done < <(watch_paths)
  if [[ "${#paths[@]}" -eq 0 ]]; then echo "no-paths"; return 0; fi
  find "${paths[@]}" -type f \
    \( -name '*.py' -o -name '*.sh' -o -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.md' \) \
    -print0 2>/dev/null \
    | xargs -0 stat -f '%m %N' 2>/dev/null \
    | shasum -a 1 \
    | awk '{print $1}'
}

restart() { stop_one; launch_bg "$PORT" "$APP" "--reload" "$LOG" "$PID"; }

watch_target() {
  local last_hash current_hash
  restart
  last_hash="$(snapshot)"
  echo "👀 watching every ${WATCH_INTERVAL}s for code changes"
  echo "   Ctrl+C to stop watcher and managed server"
  trap 'echo; echo "→ stopping watch"; stop_one; exit 0' INT TERM
  while true; do
    sleep "$WATCH_INTERVAL"
    current_hash="$(snapshot)"
    if [[ "$current_hash" != "$last_hash" ]]; then
      echo "↻ change detected at $(date '+%H:%M:%S')"
      restart
      last_hash="$(snapshot)"
    fi
  done
}

case "${1:-start}" in
  start)   launch_bg "$PORT" "$APP" "--reload" "$LOG" "$PID" ;;
  stop)    stop_one ;;
  restart) restart ;;
  fg)      launch_fg "$PORT" "$APP" "--reload" ;;
  watch)   watch_target ;;
  status)  status ;;
  *) echo "usage: $0 {start|stop|restart|fg|watch|status}"; exit 2 ;;
esac
