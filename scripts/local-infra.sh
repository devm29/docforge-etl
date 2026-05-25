#!/usr/bin/env bash
# Runs PostgreSQL (with pgvector) and Redis as local processes on the project's ports,
# keeping all state under .local/. Use this when Docker is not available.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$ROOT/.local"
PG_PORT="${PG_PORT:-5503}"
REDIS_PORT="${REDIS_PORT:-6403}"
# Must match the password in REDIS_URL. arq jobs are JSON, but Redis still should not be open.
REDIS_PASSWORD="${REDIS_PASSWORD:-docforge-dev}"

if [[ -z "${PG_BIN:-}" ]]; then
  bundled=$(find "$STATE/pg" -type d -name bin -path "*postgresql*" 2>/dev/null | head -n1 || true)
  PG_BIN="${bundled:-$(dirname "$(command -v pg_ctl)")}"
fi

start() {
  mkdir -p "$STATE/redis"
  if [[ ! -d "$STATE/pgdata" ]]; then
    "$PG_BIN/initdb" -D "$STATE/pgdata" -U docforge --auth=trust -E UTF8 >/dev/null
  fi
  if ! "$PG_BIN/pg_ctl" -D "$STATE/pgdata" status >/dev/null 2>&1; then
    "$PG_BIN/pg_ctl" -D "$STATE/pgdata" -l "$STATE/postgres.log" -w \
      -o "-p $PG_PORT -k $STATE -c listen_addresses=localhost" start >/dev/null
  fi
  "$PG_BIN/psql" -h localhost -p "$PG_PORT" -U docforge -d postgres -tAc \
    "select 1 from pg_database where datname = 'docforge'" | grep -q 1 \
    || "$PG_BIN/createdb" -h localhost -p "$PG_PORT" -U docforge docforge
  if ! "$PG_BIN/psql" -h localhost -p "$PG_PORT" -U docforge -d docforge -qc "create extension if not exists vector" 2>/dev/null; then
    echo "pgvector is not installed for $PG_BIN. Install it (https://github.com/pgvector/pgvector) or use docker compose." >&2
    exit 1
  fi
  if ! redis-cli -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning ping 2>/dev/null | grep -q PONG; then
    redis-server --port "$REDIS_PORT" --bind 127.0.0.1 ::1 --protected-mode yes \
      --requirepass "$REDIS_PASSWORD" --dir "$STATE/redis" --save "" --appendonly no \
      --daemonize yes --logfile "$STATE/redis/redis.log"
  fi
  echo "postgres on :$PG_PORT, redis on :$REDIS_PORT"
}

stop() {
  "$PG_BIN/pg_ctl" -D "$STATE/pgdata" stop -m fast >/dev/null 2>&1 || true
  redis-cli -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning shutdown nosave >/dev/null 2>&1 || true
  echo "stopped"
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  *) echo "usage: $0 [start|stop]" >&2; exit 2 ;;
esac
