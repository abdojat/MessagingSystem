#!/bin/sh
set -eu

case "${POSTGRES_APP_USER:-}" in
  ""|*[!A-Za-z0-9_]*)
    echo "POSTGRES_APP_USER must contain only letters, digits, and underscores" >&2
    exit 1
    ;;
esac

if [ "${#POSTGRES_APP_PASSWORD}" -lt 32 ]; then
  echo "POSTGRES_APP_PASSWORD must be at least 32 characters" >&2
  exit 1
fi

if [ "$POSTGRES_APP_USER" = "$POSTGRES_USER" ]; then
  echo "runtime and administrative PostgreSQL roles must be different" >&2
  exit 1
fi

psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_user="$POSTGRES_APP_USER" \
  --set=app_password="$POSTGRES_APP_PASSWORD" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'app_user',
  :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec
SQL
