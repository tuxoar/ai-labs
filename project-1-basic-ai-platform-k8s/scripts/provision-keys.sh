#!/usr/bin/env bash
#
# Provision scoped LiteLLM virtual keys for the Kubernetes Basic AI Platform.
#
# Creates two keys via the LiteLLM management API (idempotent — safe to re-run):
#   openwebui   — what Open WebUI uses instead of the master key: model
#                 allow-list, monthly budget, TPM/RPM rate limits.
#   smoke-test  — all models, small weekly budget, for scripts/smoke-test.sh.
#
# The generated keys are runtime state in LiteLLM's Postgres; their durable home
# is Vault (kv-v2 secret/basic-ai-platform, keys openwebuiApiKey /
# smokeTestApiKey), from which VSO syncs them into the cluster Secret within
# refreshAfter (60s). This script:
#   1. reads existing keys from the cluster Secret and validates them (skip if OK)
#   2. otherwise deletes any stale alias and generates a fresh key
#   3. writes to Vault directly when the vault CLI + VAULT_ADDR/VAULT_TOKEN are
#      available; otherwise saves keys to a chmod-600 local file and prints the
#      exact `vault kv patch` command to run
#
# Usage:
#   ./scripts/provision-keys.sh            # namespace basic-ai-platform
#   ./scripts/provision-keys.sh -n my-ns
#   FORCE=1 ./scripts/provision-keys.sh    # rotate: regenerate even if valid
#
set -uo pipefail

NS="${NS:-basic-ai-platform}"
SECRET="${SECRET:-basic-ai-platform-secrets}"
LPORT="${LPORT:-14100}"
VAULT_KV_MOUNT="${VAULT_KV_MOUNT:-secret}"
VAULT_KV_PATH="${VAULT_KV_PATH:-basic-ai-platform}"
FORCE="${FORCE:-0}"

while getopts "n:" opt; do case "$opt" in n) NS="$OPTARG" ;; *) ;; esac; done

command -v kubectl >/dev/null 2>&1 || { echo "FAIL: kubectl not found"; exit 1; }
command -v jq      >/dev/null 2>&1 || { echo "FAIL: jq not found"; exit 1; }

# --- master key from the cluster Secret (management routes require it) ---
MASTER_KEY=$(kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.litellmMasterKey}' 2>/dev/null | base64 -d 2>/dev/null)
[ -n "$MASTER_KEY" ] || { echo "FAIL: could not read litellmMasterKey from secret/$SECRET in ns/$NS"; exit 1; }

secret_key() { # <camelCase key> -> value or empty
  kubectl -n "$NS" get secret "$SECRET" -o jsonpath="{.data.$1}" 2>/dev/null | base64 -d 2>/dev/null
}

# --- port-forward the gateway, clean up on exit ---
kubectl -n "$NS" port-forward svc/litellm "$LPORT:4000" >/dev/null 2>&1 &
PF_PID=$!
trap 'kill "$PF_PID" 2>/dev/null' EXIT INT TERM

LITELLM="http://localhost:${LPORT}"
for _ in $(seq 1 30); do
  curl -s --max-time 3 "$LITELLM/health/readiness" >/dev/null 2>&1 && break
  sleep 1
done

mask() { printf '%s…%s' "$(echo "$1" | cut -c1-7)" "$(echo "$1" | rev | cut -c1-4 | rev)"; }

key_valid() { # <key> -> 0 if the gateway accepts it
  local code
  code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $1" "$LITELLM/v1/models")
  [ "$code" = "200" ]
}

generate_key() { # <alias> <json-body> -> prints new key
  # A stale alias blocks regeneration (key_alias is unique) — delete it first.
  curl -s --max-time 15 -X POST "$LITELLM/key/delete" \
    -H "Authorization: Bearer $MASTER_KEY" -H "Content-Type: application/json" \
    -d "{\"key_aliases\":[\"$1\"]}" >/dev/null 2>&1
  curl -s --max-time 15 -X POST "$LITELLM/key/generate" \
    -H "Authorization: Bearer $MASTER_KEY" -H "Content-Type: application/json" \
    -d "$2" | jq -r '.key // empty'
}

# Allow-list for the openwebui key: chat models + the default embedder only.
# embed-bge-m3 / embed-arctic2 are deliberately excluded (Project 2 benchmark
# models) so least-privilege is demonstrably non-trivial.
OPENWEBUI_BODY='{
  "key_alias": "openwebui",
  "models": ["llama3","llama3.1","gemma2","phi4","qwen2.5","coder","deepseek-coder","qwen3","qwen3-8b","qwen3-next","qwen3.5","embed-nomic"],
  "max_budget": 50.0,
  "budget_duration": "30d",
  "tpm_limit": 100000,
  "rpm_limit": 60,
  "metadata": {"service": "open-webui", "provisioned_by": "provision-keys.sh"}
}'
SMOKETEST_BODY='{
  "key_alias": "smoke-test",
  "max_budget": 5.0,
  "budget_duration": "7d",
  "rpm_limit": 30,
  "metadata": {"service": "smoke-test", "provisioned_by": "provision-keys.sh"}
}'
# Embed-ONLY key for the rag-pipeline (bulk ingestion) and Open WebUI's RAG
# query embedding. Deliberately cannot chat; the chat key deliberately cannot
# reach the benchmark embedders — least privilege in both directions.
# TPM sized for bulk ingestion of a large ebook library.
OPENWEBUI_RAG_BODY='{
  "key_alias": "openwebui-rag",
  "models": ["embed-nomic","embed-bge-m3"],
  "max_budget": 10.0,
  "budget_duration": "30d",
  "tpm_limit": 2000000,
  "rpm_limit": 600,
  "metadata": {"service": "rag-pipeline", "provisioned_by": "provision-keys.sh"}
}'

declare -A NEW_KEYS=()

provision() { # <alias> <secretKeyName> <body>
  local alias="$1" skey="$2" body="$3" existing new
  existing=$(secret_key "$skey")
  if [ "$FORCE" != "1" ] && [ -n "$existing" ] && key_valid "$existing"; then
    echo "  SKIP: $alias — existing key in secret/$SECRET is valid ($(mask "$existing"))"
    return 0
  fi
  new=$(generate_key "$alias" "$body")
  if [ -z "$new" ]; then
    echo "  FAIL: $alias — /key/generate returned no key"
    return 1
  fi
  echo "  OK:   $alias — generated $(mask "$new")"
  NEW_KEYS["$skey"]="$new"
}

echo "provisioning virtual keys (ns=$NS, gateway=$LITELLM)..."
rc=0
provision openwebui  openwebuiApiKey "$OPENWEBUI_BODY"  || rc=1
provision smoke-test smokeTestApiKey "$SMOKETEST_BODY" || rc=1
provision openwebui-rag openwebuiRagApiKey "$OPENWEBUI_RAG_BODY" || rc=1

# --- persist new keys to Vault (durable home; VSO syncs the Secret) ---
if [ "${#NEW_KEYS[@]}" -gt 0 ]; then
  args=()
  for k in "${!NEW_KEYS[@]}"; do args+=("$k=${NEW_KEYS[$k]}"); done
  if command -v vault >/dev/null 2>&1 && [ -n "${VAULT_ADDR:-}" ]; then
    if vault kv patch "$VAULT_KV_MOUNT/$VAULT_KV_PATH" "${args[@]}" >/dev/null; then
      echo "  OK:   wrote ${!NEW_KEYS[*]} to Vault $VAULT_KV_MOUNT/$VAULT_KV_PATH (VSO syncs within ~60s)"
    else
      echo "  FAIL: vault kv patch failed — keys NOT persisted"; rc=1
    fi
  else
    out="$(cd "$(dirname "$0")/.." && pwd)/provision-keys.out.env"
    umask 077
    for k in "${!NEW_KEYS[@]}"; do echo "$k=${NEW_KEYS[$k]}"; done > "$out"
    echo "  WARN: vault CLI/VAULT_ADDR not available. Keys saved to $out (chmod 600)."
    echo "        Persist them with:"
    echo "          vault kv patch $VAULT_KV_MOUNT/$VAULT_KV_PATH \\"
    for k in "${!NEW_KEYS[@]}"; do echo "            $k=\$${k} \\"; done
    echo "        then delete $out. Until Vault has them, re-runs will regenerate."
  fi
fi

exit "$rc"
