#!/bin/bash
# Parse DATABASE_URL into individual PG* environment variables.
# Usage: source bin/export_pg_vars.sh
#
# Needed because PHP (server.php) and psql (init-database.sh) expect
# PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD — but Scalingo only
# provides DATABASE_URL.

if [ -n "$DATABASE_URL" ] && [ -z "$PGHOST" ]; then
  eval "$(python3 -c "
import os, urllib.parse
u = urllib.parse.urlparse(os.environ['DATABASE_URL'])
print(f'export PGHOST=\"{u.hostname}\"')
print(f'export PGPORT=\"{u.port or 5432}\"')
print(f'export PGDATABASE=\"{u.path.lstrip(\"/\")}\"')
print(f'export PGUSER=\"{u.username}\"')
print(f'export PGPASSWORD=\"{urllib.parse.unquote(u.password)}\"')
")"
  echo "-----> Parsed DATABASE_URL into PG* vars (host=$PGHOST port=$PGPORT db=$PGDATABASE)"
fi
