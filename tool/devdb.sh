#!/usr/bin/env bash
# Local dev/test PostgreSQL for machines without Docker: a self-contained
# cluster in .devdb/ using Homebrew postgresql@16, TCP-only on 127.0.0.1.
# Trust auth — local development only, never expose this beyond localhost.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGDATA="$ROOT/.devdb/pgdata"
PGLOG="$ROOT/.devdb/postgres.log"
PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@16/bin}"
PORT="${DB_PORT:-5432}"

if [ ! -x "$PGBIN/pg_ctl" ]; then
  echo "postgresql@16 not found at $PGBIN — brew install postgresql@16 (or set PGBIN)" >&2
  exit 1
fi

# TCP-only: unix sockets are disabled so deep repo paths can't exceed the
# kernel's 103-byte socket-path limit.
START_OPTS="-p $PORT -c unix_socket_directories=''"

case "${1:-}" in
  init)
    if [ -d "$PGDATA" ]; then
      echo "already initialized: $PGDATA (use '$0 start')"
      exit 0
    fi
    mkdir -p "$ROOT/.devdb"
    "$PGBIN/initdb" -D "$PGDATA" -U quantai --auth=trust >/dev/null
    "$PGBIN/pg_ctl" -D "$PGDATA" -l "$PGLOG" -o "$START_OPTS" start >/dev/null
    "$PGBIN/createdb" -h 127.0.0.1 -p "$PORT" -U quantai quantai
    echo "initialized and started (db=quantai user=quantai port=$PORT, data in .devdb/)"
    ;;
  start)
    "$PGBIN/pg_ctl" -D "$PGDATA" -l "$PGLOG" -o "$START_OPTS" start
    ;;
  stop)
    "$PGBIN/pg_ctl" -D "$PGDATA" stop
    ;;
  status)
    "$PGBIN/pg_ctl" -D "$PGDATA" status || true
    ;;
  *)
    echo "usage: $0 {init|start|stop|status}" >&2
    exit 1
    ;;
esac
