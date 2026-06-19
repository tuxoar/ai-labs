#!/usr/bin/env bash
#
# Smoke-test the Basic AI Platform through the LiteLLM gateway.
# Verifies the full path: client -> LiteLLM -> Ollama, plus the UI/observability.
#
# Usage:  ./scripts/smoke-test.sh        (run from the project dir, after `docker compose up -d`)
#
set -uo pipefail

cd "$(dirname "$0")/.."

# --- load .env ---
if [ ! -f .env ]; then echo "FAIL: .env not found (cp .env.example .env)"; exit 1; fi
set -a; . ./.env; set +a

LITELLM=http://localhost:4000
WEBUI=http://localhost:3000
PROM=http://localhost:9090
AUTH="Authorization: Bearer ${LITELLM_MASTER_KEY}"

pass=0; fail=0
ok()   { echo "  PASS: $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL: $1"; fail=$((fail+1)); }
hr()   { printf '\n=== %s ===\n' "$1"; }

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

# 2. Chat completion against EVERY chat model (proves LiteLLM -> Ollama per model).
# First call to a model is a cold load into VRAM, so the timeout is generous;
# big/offloaded models (qwen3, anything Tier-3) are legitimately slow.
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

# 4. Caching: second identical chat should be served from Redis (x-litellm-cache-key/hit)
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

# 6. Prometheus scraping LiteLLM
hr "Prometheus target"
up=$(curl -s --max-time 10 "$PROM/api/v1/targets" \
  | python3 -c "import sys,json
try:
  t=[x for x in json.load(sys.stdin)['data']['activeTargets'] if x['labels'].get('job')=='litellm']
  print(t[0]['health'] if t else 'missing')
except Exception: print('error')" 2>/dev/null)
[ "$up" = "up" ] && ok "litellm target is UP in Prometheus" || echo "  INFO: litellm target state='${up}' (metrics may take a scrape interval; premium-gated on some LiteLLM builds)"

# --- summary ---
hr "summary"
echo "  passed: $pass   failed: $fail"
[ "$fail" -eq 0 ] && { echo "  ALL CORE CHECKS PASSED"; exit 0; } || { echo "  SOME CHECKS FAILED"; exit 1; }
