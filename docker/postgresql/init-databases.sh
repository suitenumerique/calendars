#!/bin/sh
# Initialize shared calendars database for local development
# All services (Django, Caldav, Keycloak) use the same database in public schema
# This script runs as POSTGRES_USER on first database initialization

set -e

echo "Initializing calendars database..."

# Ensure pgroot user exists with correct password and permissions
# This runs as POSTGRES_USER (which may be different from pgroot on existing databases)
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Ensure pgroot user exists with correct password
    -- POSTGRES_USER has superuser privileges, so it can create users
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'pgroot') THEN
            CREATE USER pgroot WITH PASSWORD 'pass' SUPERUSER CREATEDB CREATEROLE;
        ELSE
            ALTER USER pgroot WITH PASSWORD 'pass';
            -- Ensure superuser privileges
            ALTER USER pgroot WITH SUPERUSER CREATEDB CREATEROLE;
        END IF;
    END
    \$\$;
    
    -- Grant all privileges on calendars database
    GRANT ALL PRIVILEGES ON DATABASE "$POSTGRES_DB" TO pgroot;
    
    -- Grant all on public schema
    GRANT ALL ON SCHEMA public TO pgroot;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO pgroot;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO pgroot;
EOSQL

echo "Calendars database ready!"
