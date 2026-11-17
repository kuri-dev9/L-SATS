#!/usr/bin/env bash
# Slab Thickness Analyzer - macOS/Linux launcher
#
#   ./run.sh                 run in this terminal (stop: Ctrl+C)
#   ./run.sh start           run in the background and open the browser
#   ./run.sh stop            stop the server on the port
#   ./run.sh restart         stop, then start
#   ./run.sh status          show whether it is running
#   ./run.sh log             follow the server log (Ctrl+C to quit watching)
#
# Port: LSATS_PORT (default 8501). Extra arguments go to streamlit, e.g. ./run.sh start --server.address 0.0.0.0
set -e
cd "$(dirname "$0")"
PORT="${LSATS_PORT:-8501}"
RUN_DIR=.run
PID_FILE="$RUN_DIR/server.pid"
LOG_FILE="$RUN_DIR/server.log"
URL="http://localhost:$PORT"

prepare() {
  # Install packages on first run, and again whenever requirements.txt changes (e.g. after git pull)
  if [ ! -f .venv/installed.ok ] || ! cmp -s requirements.txt .venv/requirements.txt; then
    echo "Installing packages - first run or new packages, 1-3 minutes..."
    [ -x .venv/bin/python ] || python3 -m venv .venv
    .venv/bin/python -m pip install -q --upgrade pip
    .venv/bin/python -m pip install -q -r requirements.txt
    cp requirements.txt .venv/requirements.txt
    touch .venv/installed.ok
  fi
  # Skip Streamlit's first-run email prompt
  if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
    mkdir -p "$HOME/.streamlit"
    printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
  fi
}

# PIDs listening on the port (lsof), else the PID we saved at start
server_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true
  elif [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    cat "$PID_FILE"
  fi
}

healthy() {
  [ "$(curl -s -m 2 "$URL/_stcore/health" 2>/dev/null)" = "ok" ]
}

open_browser() {
  [ -n "$LSATS_NO_BROWSER" ] && return 0
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 &
  fi
}

cmd_start() {
  local pids
  pids=$(server_pids)
  if [ -n "$pids" ]; then
    echo "Already running: $URL (PID $(echo $pids))"
    return 0
  fi
  prepare
  mkdir -p "$RUN_DIR"
  echo "Starting Slab Thickness Analyzer in the background..."
  nohup .venv/bin/python -m streamlit run app.py --server.headless true --server.port "$PORT" "$@" \
    > "$LOG_FILE" 2>&1 < /dev/null &
  echo $! > "$PID_FILE"
  for _ in $(seq 60); do
    if healthy; then
      echo "Running: $URL (PID $(cat "$PID_FILE"))  log: $LOG_FILE"
      open_browser
      return 0
    fi
    if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then break; fi
    sleep 1
  done
  echo "Failed to start. Last lines of $LOG_FILE:"
  tail -n 20 "$LOG_FILE"
  return 1
}

cmd_stop() {
  local pids
  pids=$(server_pids)
  if [ -z "$pids" ]; then
    echo "Not running (port $PORT)."
    rm -f "$PID_FILE"
    return 0
  fi
  kill $pids 2>/dev/null || true
  for _ in $(seq 10); do
    [ -z "$(server_pids)" ] && break
    sleep 1
  done
  pids=$(server_pids)
  [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "Stopped (port $PORT)."
}

cmd_status() {
  local pids
  pids=$(server_pids)
  if [ -z "$pids" ]; then
    echo "Stopped (port $PORT)."
    return 1
  fi
  if healthy; then
    echo "Running: $URL (PID $(echo $pids))"
  else
    echo "Port $PORT is in use (PID $(echo $pids)) but the app is not answering yet."
  fi
}

case "${1:-}" in
  start)   shift; cmd_start "$@" ;;
  stop)    cmd_stop ;;
  restart) shift; cmd_stop; cmd_start "$@" ;;
  status)  cmd_status ;;
  log|logs)
    [ -f "$LOG_FILE" ] || { echo "No log yet ($LOG_FILE)."; exit 1; }
    tail -n 50 -f "$LOG_FILE" ;;
  -h|--help|help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)
    prepare
    echo "Starting Slab Thickness Analyzer: $URL (stop: Ctrl+C)"
    exec .venv/bin/python -m streamlit run app.py --server.port "$PORT" "$@" ;;
esac
