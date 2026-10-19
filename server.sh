#!/usr/bin/env bash
# Birdeye Data Skills — server control (2 servers)
#   hub    → birdeye_ui.py      @ 127.0.0.1:8765   (Hub Home + /test)
#   public → deploy/server.py   @ 127.0.0.1:8899   (deployable hub + /test)
#
# Usage:
#   ./server.sh start   [hub|public|all]    # background (default: all)
#   ./server.sh stop    [hub|public|all]
#   ./server.sh restart [hub|public|all]
#   ./server.sh fg      [hub|public]        # foreground (Ctrl+C to stop)
#   ./server.sh watch   [hub|public|all]    # auto-restart on file change
#   ./server.sh status
# Env overrides: HOST=0.0.0.0 HUB_PORT=8765 PUB_PORT=8899 WATCH_INTERVAL=2 ./server.sh watch
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

HOST="${HOST:-127.0.0.1}"
HUB_PORT="${HUB_PORT:-8765}"
PUB_PORT="${PUB_PORT:-8899}"
HUB_APP="birdeye_ui.py"
PUB_APP="deploy/server.py"
HUB_LOG="${HUB_LOG:-/tmp/birdeye-hub.log}";    HUB_PID="${HUB_PID:-/tmp/birdeye-hub.pid}"
PUB_LOG="${PUB_LOG:-/tmp/birdeye-public.log}"; PUB_PID="${PUB_PID:-/tmp/birdeye-public.pid}"
WATCH_INTERVAL="${WATCH_INTERVAL:-2}"

busy() { lsof -ti:"$1" >/dev/null 2>&1; }

# launch_bg <name> <port> <app> <extra-args> <log> <pid>
launch_bg() {
  local name="$1" port="$2" app="$3" extra="$4" log="$5" pid="$6"
  if busy "$port"; then echo "→ [$name] port $port busy, killing old"; lsof -ti:"$port" | xargs kill -9; sleep 1; fi
  nohup python3 "$ROOT/$app" --host "$HOST" --port "$port" $extra >"$log" 2>&1 &
  echo $! >"$pid"
  sleep 2
  if busy "$port"; then echo "✓ [$name] http://$HOST:$port  (PID $(cat "$pid"))  log: $log"
  else echo "✗ [$name] failed on :$port"; tail -n 15 "$log"; fi
}

launch_fg() {
  local name="$1" port="$2" app="$3" extra="$4"
  if busy "$port"; then echo "→ [$name] port $port busy, killing old"; lsof -ti:"$port" | xargs kill -9; sleep 1; fi
  echo "→ [$name] foreground http://$HOST:$port  · Ctrl+C to stop"
  exec python3 "$ROOT/$app" --host "$HOST" --port "$port" $extra
}

stop_one() {
  local name="$1" port="$2" pid="$3"
  if busy "$port"; then lsof -ti:"$port" | xargs kill -9; echo "✓ [$name] stopped :$port"
  else echo "• [$name] not running :$port"; fi
  rm -f "$pid"
}

start_hub()    { launch_bg hub    "$HUB_PORT" "$HUB_APP" "--reload" "$HUB_LOG" "$HUB_PID"; }
start_public() { launch_bg public "$PUB_PORT" "$PUB_APP" ""        "$PUB_LOG" "$PUB_PID"; }
stop_hub()     { stop_one hub    "$HUB_PORT" "$HUB_PID"; }
stop_public()  { stop_one public "$PUB_PORT" "$PUB_PID"; }
status() {
  busy "$HUB_PORT" && echo "hub    running → http://$HOST:$HUB_PORT" || echo "hub    stopped"
  busy "$PUB_PORT" && echo "public running → http://$HOST:$PUB_PORT" || echo "public stopped"
}

watch_paths_for() {
  local target="$1"
  case "$target" in
    hub)
      cat <<EOF
$ROOT/birdeye_ui.py
$ROOT/assets
$ROOT/birdeye-screener/scripts
$ROOT/docs
$ROOT/API
EOF
      ;;
    public)
      cat <<EOF
$ROOT/deploy
$ROOT/assets
$ROOT/birdeye-screener/scripts
$ROOT/docs
$ROOT/API
EOF
      ;;
    *)
      cat <<EOF
$ROOT/birdeye_ui.py
$ROOT/deploy
$ROOT/assets
$ROOT/birdeye-screener/scripts
$ROOT/docs
$ROOT/API
EOF
      ;;
  esac
}

snapshot_target() {
  local target="$1"
  local paths=()
  while IFS= read -r path; do
    [[ -n "$path" && -e "$path" ]] && paths+=("$path")
  done < <(watch_paths_for "$target")
  if [[ "${#paths[@]}" -eq 0 ]]; then
    echo "no-paths"
    return 0
  fi
  find "${paths[@]}" -type f \
    \( -name '*.py' -o -name '*.sh' -o -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.md' \) \
    -print0 2>/dev/null \
    | xargs -0 stat -f '%m %N' 2>/dev/null \
    | shasum -a 1 \
    | awk '{print $1}'
}

restart_target() {
  local target="$1"
  case "$target" in
    hub) stop_hub; start_hub ;;
    public) stop_public; start_public ;;
    *) stop_hub; stop_public; start_hub; start_public ;;
  esac
}

stop_target() {
  local target="$1"
  case "$target" in
    hub) stop_hub ;;
    public) stop_public ;;
    *) stop_hub; stop_public ;;
  esac
}

watch_target() {
  local target="$1"
  local last_hash current_hash
  restart_target "$target"
  last_hash="$(snapshot_target "$target")"
  echo "👀 watching [$target] every ${WATCH_INTERVAL}s for code changes"
  echo "   Ctrl+C to stop watcher and managed server(s)"
  trap 'echo; echo "→ stopping watch [$target]"; stop_target "$target"; exit 0' INT TERM
  while true; do
    sleep "$WATCH_INTERVAL"
    current_hash="$(snapshot_target "$target")"
    if [[ "$current_hash" != "$last_hash" ]]; then
      echo "↻ change detected for [$target] at $(date '+%H:%M:%S')"
      restart_target "$target"
      last_hash="$(snapshot_target "$target")"
    fi
  done
}

TARGET="${2:-all}"
case "${1:-start}" in
  start)   case "$TARGET" in hub) start_hub;; public) start_public;; *) start_hub; start_public;; esac ;;
  stop)    case "$TARGET" in hub) stop_hub;;  public) stop_public;;  *) stop_hub;  stop_public;;  esac ;;
  restart) case "$TARGET" in hub) stop_hub; start_hub;; public) stop_public; start_public;; *) stop_hub; stop_public; start_hub; start_public;; esac ;;
  fg)      case "$TARGET" in public) launch_fg public "$PUB_PORT" "$PUB_APP" "";; *) launch_fg hub "$HUB_PORT" "$HUB_APP" "--reload";; esac ;;
  watch)   watch_target "$TARGET" ;;
  status)  status ;;
  *) echo "usage: $0 {start|stop|restart|fg|watch|status} [hub|public|all]"; exit 2 ;;
esac
