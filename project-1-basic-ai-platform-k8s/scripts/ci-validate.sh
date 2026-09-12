#!/usr/bin/env bash
#
# Chart validation shared by CI (.github/workflows/ci.yaml) and local pre-push.
# helm lint + helm template (both secret modes, all hardening features on) +
# kubeconform against upstream + CRD-catalog schemas, plus the guardrail that
# the two litellm configs (compose & k8s) stay byte-identical.
#
# Requires: helm, kubeconform (https://github.com/yannh/kubeconform)
#
set -euo pipefail
cd "$(dirname "$0")/.."

DUMMY_SECRETS=(
  --set secrets.values.postgresPassword=ci-dummy
  --set secrets.values.litellmMasterKey=sk-ci-dummy
  --set secrets.values.litellmSaltKey=ci-dummy
  --set secrets.values.webuiSecretKey=ci-dummy
  --set secrets.values.grafanaPassword=ci-dummy
)

KUBECONFORM_ARGS=(
  -strict -summary
  -schema-location default
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
)

echo "==> helm lint"
helm lint . "${DUMMY_SECRETS[@]}"

echo "==> helm template (defaults) | kubeconform"
helm template ci . "${DUMMY_SECRETS[@]}" \
  --set networkPolicy.enabled=true --set networkPolicy.defaultDeny=true \
  --set kyverno.enabled=true \
  | kubeconform "${KUBECONFORM_ARGS[@]}"

echo "==> helm template (values-talos) | kubeconform"
helm template ci . -f values-talos.yaml \
  --set networkPolicy.defaultDeny=true --set kyverno.enabled=true \
  | kubeconform "${KUBECONFORM_ARGS[@]}"

echo "==> compose/k8s litellm configs must stay byte-identical"
diff ../project-1-basic-ai-platform/litellm/config.yaml files/litellm/config.yaml
diff ../project-1-basic-ai-platform/litellm/hooks/prompt_guard.py files/litellm/prompt_guard.py

echo "OK: chart validation passed"
