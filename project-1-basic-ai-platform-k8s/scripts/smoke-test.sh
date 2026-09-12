#!/usr/bin/env bash
#
# Smoke-test the Kubernetes Basic AI Platform through the LiteLLM gateway.
# Verifies the full path: client -> LiteLLM -> model server, plus the UI and the
# metrics endpoint. Mirrors the Compose smoke-test, but reads the gateway key
# from the cluster Secret and port-forwards the in-cluster Services (so it works
# against a remote cluster with no NodePort/ingress).
#
# Usage:
#   ./scripts/smoke-test.sh                 # namespace basic-ai-platform
#   ./scripts/smoke-test.sh -n my-namespace
#
set -uo pipefail

NS="${NS:-basic-ai-platform}"
SECRET="${SECRET:-basic-ai-platform-secrets}"
LITELLM_LPORT="${LITELLM_LPORT:-14000}"   # local ports for the forwards
WEBUI_LPORT="${WEBUI_LPORT:-13000}"

while getopts "n:" opt; do case "$opt" in n) NS="$OPTARG" ;; *) ;; esac; done

command -v kubectl >/dev/null 2>&1 || { echo "FAIL: kubectl not found"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 not found"; exit 1; }

# --- gateway keys from the cluster Secret ---
MASTER_KEY=$(kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.litellmMasterKey}' 2>/dev/null | base64 -d 2>/dev/null)
[ -n "$MASTER_KEY" ] || { echo "FAIL: could not read litellmMasterKey from secret/$SECRET in ns/$NS"; exit 1; }

# Prefer the scoped smoke-test virtual key (least privilege); fall back to the
# master key only on a fresh install where provision-keys.sh hasn't run yet.
SMOKE_KEY=$(kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.smokeTestApiKey}' 2>/dev/null | base64 -d 2>/dev/null)
OPENWEBUI_KEY=$(kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.openwebuiApiKey}' 2>/dev/null | base64 -d 2>/dev/null)
if [ -n "$SMOKE_KEY" ]; then
  GATEWAY_KEY="$SMOKE_KEY"
else
  GATEWAY_KEY="$MASTER_KEY"
  echo "WARN: no smokeTestApiKey in secret/$SECRET — using the master key." \
       "Run scripts/provision-keys.sh to mint scoped keys."
fi

# --- port-forward the Services, clean up on exit ---
pids=()
cleanup() { for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null; done; }
trap cleanup EXIT INT TERM

pf() { # svc localport remoteport
  kubectl -n "$NS" port-forward "svc/$1" "$2:$3" >/dev/null 2>&1 &
  pids+=("$!")
}
pf litellm    "$LITELLM_LPORT" 4000
pf open-webui "$WEBUI_LPORT"   3000

LITELLM="http://localhost:${LITELLM_LPORT}"
WEBUI="http://localhost:${WEBUI_LPORT}"
AUTH="Authorization: Bearer ${GATEWAY_KEY}"

pass=0; fail=0
ok()  { echo "  PASS: $1"; pass=$((pass+1)); }
bad() { echo "  FAIL: $1"; fail=$((fail+1)); }
hr()  { printf '\n=== %s ===\n' "$1"; }

# Wait for the LiteLLM forward to be ready (readiness endpoint needs no auth).
echo "waiting for port-forwards (ns=$NS)..."
for _ in $(seq 1 30); do
  curl -s --max-time 3 "$LITELLM/health/readiness" >/dev/null 2>&1 && break
  sleep 1
done

# 1. LiteLLM reachable + lists models
hr "LiteLLM /v1/models"
models=$(curl -s --max-time 10 -H "$AUTH" "$LITELLM/v1/models")
if echo "$models" | grep -q '"llama3"'; then
  count=$(echo "$models" | python3 -c "import sys,json;print(len(json.load(sys.stdin)['data']))" 2>/dev/null)
  ok "gateway up, ${count} models registered"
else
  bad "gateway did not list models -> ${models:0:200}"
fi

# Split registered models into chat vs embedding (embedding names start "embed").
chat_models=$(echo "$models" | python3 -c "import sys,json;print(' '.join(m['id'] for m in json.load(sys.stdin).get('data',[]) if not m['id'].startswith('embed')))" 2>/dev/null)
embed_models=$(echo "$models" | python3 -c "import sys,json;print(' '.join(m['id'] for m in json.load(sys.stdin).get('data',[]) if m['id'].startswith('embed')))" 2>/dev/null)

# 2. Chat completion against EVERY chat model (proves LiteLLM -> model server per model).
hr "chat completion — all chat models"
for m in $chat_models; do
  chat=$(curl -s --max-time 180 -H "$AUTH" -H "Content-Type: application/json" \
    "$LITELLM/v1/chat/completions" \
    -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: pong\"}],\"max_tokens\":64,\"temperature\":0}")
  reply=$(echo "$chat" | python3 -c "import sys,json;m=json.load(sys.stdin)['choices'][0]['message'];print((m.get('content') or m.get('reasoning_content') or '').strip())" 2>/dev/null)
  if [ -n "$reply" ]; then ok "$(printf '%-16s' "$m") -> $(echo "$reply" | tr -d '\n' | head -c 40)"
  else bad "$(printf '%-16s' "$m") -> no completion: $(echo "$chat" | tr -d '\n' | head -c 140)"; fi
done

# 3. Embedding against EVERY embedding model (proves RAG path + reports dims).
hr "embedding — all embedding models"
for m in $embed_models; do
  emb=$(curl -s --max-time 60 -H "$AUTH" -H "Content-Type: application/json" \
    "$LITELLM/v1/embeddings" \
    -d "{\"model\":\"$m\",\"input\":\"kubernetes admission control\"}")
  dim=$(echo "$emb" | python3 -c "import sys,json;print(len(json.load(sys.stdin)['data'][0]['embedding']))" 2>/dev/null)
  if [ -n "$dim" ]; then ok "$(printf '%-16s' "$m") -> ${dim} dims"
  else bad "$(printf '%-16s' "$m") -> no embedding: $(echo "$emb" | tr -d '\n' | head -c 140)"; fi
done

# 4. Caching: second identical chat should carry a Redis cache header.
hr "redis cache"
hit=$(curl -s --max-time 30 -D - -o /dev/null -H "$AUTH" -H "Content-Type: application/json" \
  "$LITELLM/v1/chat/completions" \
  -d '{"model":"llama3","messages":[{"role":"user","content":"Reply with exactly: pong"}],"max_tokens":10,"temperature":0}' \
  | grep -i "x-litellm-cache" | tr -d '\r')
if [ -n "$hit" ]; then ok "cache header present: $hit"; else echo "  INFO: no cache header (may need a warm entry / OK to ignore)"; fi

# 5. Open WebUI up
hr "Open WebUI"
code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "$WEBUI/health" || echo 000)
[ "$code" = "200" ] && ok "Open WebUI healthy ($WEBUI)" || bad "Open WebUI /health returned $code"

# 6. Prometheus metrics exposed by LiteLLM (the scrape source). Whoever scrapes
#    it — the bundled Prometheus or an existing kube-prometheus-stack — reads this
#    same endpoint, so a healthy /metrics is the portable check.
hr "LiteLLM /metrics"
# LiteLLM serves metrics at /metrics/ and 307-redirects /metrics, so follow (-L).
# Use grep -c (reads the whole stream) rather than grep -q, which closes the pipe
# early and — under `set -o pipefail` — reports the curl as failed via SIGPIPE.
metrics=$(curl -sL --max-time 10 "$LITELLM/metrics")
series=$(printf '%s\n' "$metrics" | grep -c '^litellm_')
if [ "${series:-0}" -gt 0 ]; then
  ok "LiteLLM exposes Prometheus metrics (${series} series)"
else
  bad "no litellm_* metrics on /metrics -> ${metrics:0:140}"
fi

# 6b. Optional: if a Prometheus Service is reachable, confirm it scraped litellm.
hr "Prometheus target (optional)"
PROM_NS="${PROM_NS:-$NS}"
PROM_SVC="${PROM_SVC:-prometheus}"
if kubectl -n "$PROM_NS" get svc "$PROM_SVC" >/dev/null 2>&1; then
  PROM_LPORT="${PROM_LPORT:-19090}"
  kubectl -n "$PROM_NS" port-forward "svc/$PROM_SVC" "$PROM_LPORT:9090" >/dev/null 2>&1 &
  pids+=("$!")
  for _ in $(seq 1 15); do curl -s --max-time 2 "http://localhost:$PROM_LPORT/-/ready" >/dev/null 2>&1 && break; sleep 1; done
  up=$(curl -s --max-time 10 "http://localhost:$PROM_LPORT/api/v1/targets" \
    | python3 -c "import sys,json
try:
  t=[x for x in json.load(sys.stdin)['data']['activeTargets'] if x['labels'].get('job')=='litellm' or 'litellm' in x.get('scrapePool','')]
  print(t[0]['health'] if t else 'missing')
except Exception: print('error')" 2>/dev/null)
  [ "$up" = "up" ] && ok "litellm target is UP in Prometheus ($PROM_NS/$PROM_SVC)" \
    || echo "  INFO: litellm target state='${up}' (metrics may take a scrape interval)"
else
  echo "  INFO: no svc/$PROM_SVC in ns/$PROM_NS — skipping (set PROM_NS/PROM_SVC for an external kube-prometheus-stack, e.g. PROM_NS=monitoring PROM_SVC=kube-prom-stack-prometheus)"
fi

# 7. Governance: virtual-key scoping (negative tests — a denial is a PASS).
hr "virtual-key scoping"
if [ -n "$SMOKE_KEY" ]; then
  # 7a. A scoped key must NOT reach key-management routes.
  code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' -X POST \
    -H "Authorization: Bearer $SMOKE_KEY" -H "Content-Type: application/json" \
    "$LITELLM/key/generate" -d '{}')
  case "$code" in 4*) ok "scoped key denied /key/generate ($code)" ;;
                  *)  bad "scoped key reached /key/generate ($code) — privilege escalation" ;; esac
else
  echo "  INFO: no smokeTestApiKey — skipping scoping tests (run provision-keys.sh)"
fi
if [ -n "$OPENWEBUI_KEY" ]; then
  # 7b. The openwebui key's model allow-list must exclude the benchmark embedders.
  code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $OPENWEBUI_KEY" -H "Content-Type: application/json" \
    "$LITELLM/v1/embeddings" -d '{"model":"embed-bge-m3","input":"x"}')
  case "$code" in 401|403) ok "openwebui key denied disallowed model embed-bge-m3 ($code)" ;;
                  *)       bad "openwebui key was NOT denied on embed-bge-m3 ($code)" ;; esac
  # 7c. Budget + rate limits are attached (read via master key on /key/info).
  info=$(curl -s --max-time 10 -H "Authorization: Bearer $MASTER_KEY" \
    "$LITELLM/key/info?key=$OPENWEBUI_KEY")
  limits=$(echo "$info" | python3 -c "import sys,json;i=json.load(sys.stdin)['info'];print(f\"budget={i.get('max_budget')} tpm={i.get('tpm_limit')} rpm={i.get('rpm_limit')} models={len(i.get('models') or [])}\")" 2>/dev/null)
  if echo "$limits" | grep -qv 'budget=None'; then ok "openwebui key limits: $limits"
  else bad "openwebui key has no budget/limits -> ${info:0:140}"; fi
fi

# 8. Network policy: the egress pinhole (needs exec; skipped when CNPs absent).
hr "network policy (egress pinhole)"
if kubectl -n "$NS" get ciliumnetworkpolicy litellm >/dev/null 2>&1; then
  AI_HOST=$(kubectl -n "$NS" get deploy litellm \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LOCAL_AI_BASE_URL")].value}' \
    | sed -E 's|https?://||; s|:.*||')
  probe() { # deploy host port -> 0 if TCP connect succeeds within 3s
    kubectl -n "$NS" exec "deploy/$1" -- python3 -c \
      "import socket;socket.create_connection(('$2',$3),3)" >/dev/null 2>&1
  }
  if probe litellm "$AI_HOST" 11434; then ok "litellm CAN reach the model server ($AI_HOST:11434)"
  else bad "litellm cannot reach the model server — pinhole broken"; fi
  if probe litellm 1.1.1.1 80; then bad "litellm reached 1.1.1.1:80 — egress NOT locked down"
  else ok "litellm denied general egress (1.1.1.1:80)"; fi
  if probe open-webui redis 6379; then bad "open-webui reached redis — lateral movement possible"
  else ok "open-webui denied redis:6379"; fi
  if probe open-webui "$AI_HOST" 11434; then bad "open-webui reached the model server DIRECTLY — gateway bypass"
  else ok "open-webui denied the model server (must go through litellm)"; fi
else
  echo "  INFO: no CiliumNetworkPolicy 'litellm' in ns/$NS — skipping egress probes"
fi

# --- summary ---
hr "summary"
echo "  passed: $pass   failed: $fail"
[ "$fail" -eq 0 ] && { echo "  ALL CORE CHECKS PASSED"; exit 0; } || { echo "  SOME CHECKS FAILED"; exit 1; }
