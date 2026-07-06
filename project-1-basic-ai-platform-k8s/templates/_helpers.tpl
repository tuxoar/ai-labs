{{/*
Chart name / fullname. Component Services are given FIXED, unprefixed names
(postgres, redis, litellm, open-webui, prometheus, grafana, ai-server) so the
verbatim config files copied from the Compose stack resolve them by DNS without
edits. One release per namespace, so there is no collision risk.
*/}}
{{- define "bap.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Common labels applied to every object. */}}
{{- define "bap.labels" -}}
app.kubernetes.io/part-of: basic-ai-platform
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end -}}

{{/* Per-component selector labels. Call with (dict "ctx" . "component" "postgres"). */}}
{{- define "bap.selectorLabels" -}}
app.kubernetes.io/name: {{ .component }}
app.kubernetes.io/part-of: basic-ai-platform
{{- end -}}

{{/* Name of the Secret holding all credentials. */}}
{{- define "bap.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- .Values.secrets.secretName -}}
{{- end -}}
{{- end -}}

{{/*
Shared Postgres credential env for LiteLLM / Open WebUI.
Password comes from the Secret; DATABASE_URL is composed via Kubernetes'
$(VAR) interpolation so the plaintext URL never lives in the Secret or in git.
Call with (dict "ctx" . "database" "litellm").
*/}}
{{- define "bap.postgresEnv" -}}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "bap.secretName" .ctx }}
      key: postgresPassword
- name: DATABASE_URL
  value: "postgresql://{{ .ctx.Values.postgres.user }}:$(POSTGRES_PASSWORD)@postgres:5432/{{ .database }}"
{{- end -}}
