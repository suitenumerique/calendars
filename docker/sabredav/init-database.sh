#!/bin/bash
###
# Initialize sabre/dav database schema in PostgreSQL
# This script creates all necessary tables for sabre/dav to work
###

set -e

if [ -z ${PGHOST+x} ]; then
  echo "PGHOST must be set"
  exit 1
fi
if [ -z ${PGDATABASE+x} ]; then
  echo "PGDATABASE must be set"
  exit 1
fi
if [ -z ${PGUSER+x} ]; then
  echo "PGUSER must be set"
  exit 1
fi
if [ -z ${PGPASSWORD+x} ]; then
  echo "PGPASSWORD must be set"
  exit 1
fi

export PGHOST
export PGPORT=${PGPORT:-5432}
export PGDATABASE
export PGUSER
export PGPASSWORD

# Wait for PostgreSQL to be ready
retries=30
until pg_isready -q -h "$PGHOST" -p "$PGPORT" -U "$PGUSER"; do
  [[ retries -eq 0 ]] && echo "Could not connect to Postgres" && exit 1
  echo "Waiting for Postgres to be available..."
  retries=$((retries-1))
  sleep 1
done

echo "PostgreSQL is ready. Initializing sabre/dav database schema..."

# SQL files directory (will be copied into container)
SQL_DIR="/var/www/sabredav/sql"

# Check if tables already exist
TABLES_EXIST=$(psql -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('users', 'principals', 'calendars')" 2>/dev/null || echo "0")

if [ "$TABLES_EXIST" -gt "0" ]; then
  echo "sabre/dav tables already exist, skipping initialization"
  exit 0
fi

# Create tables
echo "Creating sabre/dav tables..."

if [ -f "$SQL_DIR/pgsql.users.sql" ]; then
  psql -f "$SQL_DIR/pgsql.users.sql"
  echo "Created users table"
fi

if [ -f "$SQL_DIR/pgsql.principals.sql" ]; then
  psql -f "$SQL_DIR/pgsql.principals.sql"
  echo "Created principals table"
fi

if [ -f "$SQL_DIR/pgsql.calendars.sql" ]; then
  psql -f "$SQL_DIR/pgsql.calendars.sql"
  echo "Created calendars table"
fi

if [ -f "$SQL_DIR/pgsql.addressbooks.sql" ]; then
  psql -f "$SQL_DIR/pgsql.addressbooks.sql"
  echo "Created addressbooks table"
fi

if [ -f "$SQL_DIR/pgsql.locks.sql" ]; then
  psql -f "$SQL_DIR/pgsql.locks.sql"
  echo "Created locks table"
fi

if [ -f "$SQL_DIR/pgsql.propertystorage.sql" ]; then
  psql -f "$SQL_DIR/pgsql.propertystorage.sql"
  echo "Created propertystorage table"
fi

echo "sabre/dav database schema initialized successfully!"
