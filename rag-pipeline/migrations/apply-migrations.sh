#!/usr/bin/env bash
#
# Apply rag schema migrations to the `knowledge` DB and manage the two
# pipeline roles. Idempotent: applied files are tracked in
# rag.schema_migrations; role creation upserts (CREATE or ALTER).
#
# Runs from the workstation via port-forward using the platform's aiplat
# superuser (from the cluster Secret). Role passwords: taken from
# RAG_INGEST_PASSWORD / RAG_READ_PASSWORD env if set, else generated and
# printed as a `vault kv patch` command (same pattern as provision-keys.sh).
#
# Usage:  ./migrations/apply-migrations.sh   [-n namespace]
#
set -euo pipefail
cd "$(dirname "$0")"

NS="${NS:-basic-ai-platform}"
SECRET="${SECRET:-basic-ai-platform-secrets}"
LPORT="${LPORT:-15432}"
DB="${DB:-knowledge}"

while getopts "n:" opt; do case "$opt" in n) NS="$OPTARG" ;; *) ;; esac; done
command -v kubectl >/dev/null || { echo "FAIL: kubectl not found"; exit 1; }
command -v psql    >/dev/null || { echo "FAIL: psql not found (install postgresql-client)"; exit 1; }

PGUSER=aiplat
PGPASSWORD=$(kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.postgresPassword}' | base64 -d)
[ -n "$PGPASSWORD" ] || { echo "FAIL: could not read postgresPassword"; exit 1; }
export PGPASSWORD

kubectl -n "$NS" port-forward svc/postgres "$LPORT:5432" >/dev/null 2>&1 &
PF=$!; trap 'kill "$PF" 2>/dev/null' EXIT INT TERM
for _ in $(seq 1 30); do pg_isready -h localhost -p "$LPORT" -U "$PGUSER" >/dev/null 2>&1 && break; sleep 1; done

PSQL=(psql -v ON_ERROR_STOP=1 -h localhost -p "$LPORT" -U "$PGUSER" -d "$DB" -q)

# --- roles first (003_grants.sql needs them to exist) ---
gen() { openssl rand -base64 32 | tr -d '/+=\n' | cut -c1-40; }
NEW_PW=()
role_upsert() { # <role> <pw-env-name>
  local role="$1" env_name="$2" pw
  pw="${!env_name:-}"
  if [ -z "$pw" ]; then
    # keep the existing password if the role already exists and no env given
    if "${PSQL[@]}" -tAc "SELECT 1 FROM pg_roles WHERE rolname='$role'" | grep -q 1; then
      echo "  OK:   role $role exists (password unchanged)"; return 0
    fi
    pw=$(gen); NEW_PW+=("$env_name=$pw")
  fi
  if "${PSQL[@]}" -tAc "SELECT 1 FROM pg_roles WHERE rolname='$role'" | grep -q 1; then
    "${PSQL[@]}" -c "ALTER ROLE $role LOGIN PASSWORD '$pw'"
    echo "  OK:   role $role password updated"
  else
    "${PSQL[@]}" -c "CREATE ROLE $role LOGIN PASSWORD '$pw'"
    echo "  OK:   role $role created"
  fi
}
echo "roles:"
role_upsert rag_ingest RAG_INGEST_PASSWORD
role_upsert rag_read   RAG_READ_PASSWORD

# --- migrations, ordered, tracked ---
# 001 creates the tracking table itself, so bootstrap it if missing.
"${PSQL[@]}" -c "CREATE SCHEMA IF NOT EXISTS rag;
                 CREATE TABLE IF NOT EXISTS rag.schema_migrations (
                   filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());"
echo "migrations:"
for f in $(ls -1 [0-9]*_*.sql | sort); do
  if "${PSQL[@]}" -tAc "SELECT 1 FROM rag.schema_migrations WHERE filename='$f'" | grep -q 1; then
    echo "  SKIP: $f (applied)"
    continue
  fi
  "${PSQL[@]}" -f "$f"
  "${PSQL[@]}" -c "INSERT INTO rag.schema_migrations (filename) VALUES ('$f')"
  echo "  OK:   $f"
done

if [ "${#NEW_PW[@]}" -gt 0 ]; then
  umask 077
  printf '%s\n' "${NEW_PW[@]}" > rag-roles.out.env
  echo "  WARN: new role passwords written to migrations/rag-roles.out.env (chmod 600)."
  echo "        Persist to Vault (used by rag-api in Phase 3; Open WebUI's external"
  echo "        connection stores its own copy at setup):"
  echo "          vault kv patch secret/basic-ai-platform ragIngestPassword=\$RAG_INGEST_PASSWORD ragReadPassword=\$RAG_READ_PASSWORD"
  echo "        then delete the file."
fi
echo "done."
