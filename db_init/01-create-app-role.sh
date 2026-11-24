#!/usr/bin/env bash
# Runs once, when the postgres container initializes an empty data volume
# (files in /docker-entrypoint-initdb.d are ignored on later starts).
#
# POSTGRES_USER is the administrative superuser. The application connects as
# a separate login role that owns only the application database, so
# migrations and the scraper never run with superuser rights.
set -euo pipefail

APP_DB_USER="${APP_DB_USER:-pymarket_scrapper}"
: "${APP_DB_PASS:?APP_DB_PASS must be set for the application role}"

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    -v app_user="$APP_DB_USER" \
    -v app_pass="$APP_DB_PASS" \
    -v app_db="$POSTGRES_DB" <<'SQL'
SELECT format(
    'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L',
    :'app_user', :'app_pass'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

-- The application role owns its database and the public schema, which is
-- what Alembic needs to create and alter tables.
ALTER DATABASE :"app_db" OWNER TO :"app_user";
ALTER SCHEMA public OWNER TO :"app_user";
REVOKE ALL ON DATABASE :"app_db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"app_db" TO :"app_user";
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
