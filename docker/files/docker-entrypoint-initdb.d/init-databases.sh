#!/bin/bash
# Initialize multiple databases on the same PostgreSQL server
# This script runs automatically when the PostgreSQL container starts for the first time

set -e
set -u

# Function to create a database and user if they don't exist
create_database() {
    local database=$1
    local user=$2
    local password=$3
    
    echo "Creating database '$database' with user '$user'..."
    
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        -- Create user if not exists
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$user') THEN
                CREATE USER $user WITH PASSWORD '$password';
            END IF;
        END
        \$\$;
        
        -- Create database if not exists
        SELECT 'CREATE DATABASE $database OWNER $user'
        WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$database')\gexec
        
        -- Grant privileges
        GRANT ALL PRIVILEGES ON DATABASE $database TO $user;
EOSQL

    echo "Database '$database' created successfully."
}

# Create databases for all services
# The main 'calendar' database is created by default via POSTGRES_DB

echo "All databases initialized successfully!"
