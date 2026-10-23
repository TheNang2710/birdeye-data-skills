#!/usr/bin/env bash
# Birdeye Skills — local console control (single process, port 8765)
#
#   ./server.sh start      # background (default)
#   ./server.sh stop
#   ./server.sh restart
#   ./server.sh fg         # foreground · Ctrl+C to stop
#   ./server.sh watch      # auto-restart when source files change
#   ./server.sh status
# Env overrides: HOST=0.0.0.0 PORT=8765 WATCH_INTERVAL=2 ./server.sh watch
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"
APP="server.py"
LOG="${LOG:-/tmp/birdeye-skills.log}"
PID="${PID:-/tmp/birdeye-skills.pid}"
WATCH_INTERVAL="${WATCH_INTERVAL:-2}"

busy() { lsof -ti:"$1" >/dev/null 2>&1; }

launch_bg() {
  if busy "$PORT"; then echo "→ port $PORT busy, killing old"; lsof -ti:"$PORT" | xargs kill -9; sleep 1; fi
  nohup python3 "$ROOT/$APP" --host "$HOST" --port "$PORT" --reload >"$LOG" 2>&1 &
  echo $! >"$PID"
  sleep 2
  if busy "$PORT"; then echo "✓ http://$HOST:$PORT/  (PID $(cat "$PID"))  log: $LOG"
  else echo "✗ failed on :$PORT"; tail -n 15 "$LOG"; fi
}

launch_fg() {
  if busy "$PORT"; then echo "→ port $PORT busy, killing old"; lsof -ti:"$PORT" | xargs kill -9; sleep 1; fi
  echo "→ foreground http://$HOST:$PORT/  · Ctrl+C to stop"
  exec python3 "$ROOT/$APP" --host "$HOST" --port "$PORT" --reload
}

stop_one() {
  if busy "$PORT"; then lsof -ti:"$PORT" | xargs kill -9; echo "✓ stopped :$PORT"
  else echo "• not running :$PORT"; fi
  rm -f "$PID"
}

snapshot() {
  find "$ROOT/server.py" "$ROOT/birdeye_cli.py" "$ROOT/public" "$ROOT/modules" "$ROOT/skills" "$ROOT/docs" \
    -type f \( -name '*.py' -o -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.md' \) \
    -print0 2>/dev/null | xargs -0 stat -f '%m %N' 2>/dev/null | shasum -a 1 | awk '{print $1}'
}

watch_target() {
  launch_bg
  last_hash="$(snapshot)"
  echo "👀 watching every ${WATCH_INTERVAL}s for code changes (Ctrl+C to stop)"
  trap 'echo; echo "→ stopping watch"; stop_one; exit 0' INT TERM
  while true; do
    sleep "$WATCH_INTERVAL"
    current_hash="$(snapshot)"
    if [[ "$current_hash" != "$last_hash" ]]; then
      echo "↻ change detected at $(date '+%H:%M:%S')"
      stop_one; launch_bg
      last_hash="$current_hash"
    fi
  done
}

case "${1:-start}" in
  start)   launch_bg ;;
  stop)    stop_one ;;
  restart) stop_one; launch_bg ;;
  fg)      launch_fg ;;
  watch)   watch_target ;;
  status)  busy "$PORT" && echo "running → http://$HOST:$PORT/" || echo "stopped" ;;
  *) echo "usage: $0 {start|stop|restart|fg|watch|status}"; exit 2 ;;
esac
