#!/usr/bin/env bash
# Run the firm-radar demo on the home server (Termux, aarch64).
#
#   ./run-demo.sh setup    create the virtualenv, install dependencies, migrate, seed
#   ./run-demo.sh start    start in the background (pid file and log in ./run)
#   ./run-demo.sh stop     stop it
#   ./run-demo.sh status   print the pid and the resident memory of the process
#   ./run-demo.sh run      run in the foreground (what a service supervisor should call)
#
# PostgreSQL must already be running and the role and database must exist (see README.md).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
state="$here/run"
venv="${FIRM_RADAR_VENV:-$repo/.venv-demo}"
env_file="${FIRM_RADAR_ENV_FILE:-$here/firm-radar.env}"

load_env() {
  [ -f "$env_file" ] || { echo "missing $env_file (copy firm-radar.env.example)" >&2; exit 1; }
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
  export PYTHONPATH="$repo/src"
  export PYTHONDONTWRITEBYTECODE=1
  : "${HOST:=127.0.0.1}" "${PORT:=8093}"
}

pid_alive() { [ -f "$state/pid" ] && kill -0 "$(cat "$state/pid")" 2>/dev/null; }

case "${1:-}" in
  setup)
    load_env
    python3 -m venv "$venv"
    "$venv/bin/pip" install --upgrade pip
    "$venv/bin/pip" install --prefer-binary -r "$here/requirements.txt"
    cd "$repo"
    "$venv/bin/python" -m alembic upgrade head
    "$venv/bin/python" -m firm_radar.cli seed-demo
    ;;
  run)
    load_env
    cd "$repo"
    # One worker, plain asyncio and h11: no optional native extensions to build.
    exec "$venv/bin/python" -m uvicorn firm_radar.main:create_app --factory \
      --host "$HOST" --port "$PORT" --workers 1 --loop asyncio --http h11 \
      --limit-concurrency 32 --proxy-headers --forwarded-allow-ips 127.0.0.1
    ;;
  start)
    mkdir -p "$state"
    if pid_alive; then echo "already running (pid $(cat "$state/pid"))"; exit 0; fi
    nohup "$0" run >>"$state/firm-radar.log" 2>&1 &
    echo $! >"$state/pid"
    echo "started, pid $(cat "$state/pid"), log $state/firm-radar.log"
    ;;
  stop)
    if pid_alive; then
      kill "$(cat "$state/pid")"
      rm -f "$state/pid"
      echo stopped
    else
      rm -f "$state/pid"
      echo "not running"
    fi
    ;;
  status)
    if pid_alive; then
      pid="$(cat "$state/pid")"
      echo "running, pid $pid"
      grep -E 'VmRSS|VmHWM' "/proc/$pid/status" || true
    else
      echo "not running"
      exit 1
    fi
    ;;
  *)
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
