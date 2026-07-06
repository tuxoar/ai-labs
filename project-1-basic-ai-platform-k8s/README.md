# Project 1 — Basic AI Platform (Kubernetes)

The **Kubernetes twin** of [`../project-1-basic-ai-platform`](../project-1-basic-ai-platform)
(the Docker Compose stack). Same six containers, same request flow:

```
User → Open WebUI → LiteLLM gateway → external model server (ai-server)
                        ├→ Postgres (pgvector)   keys / logs / embeddings
                        └→ Redis                 response cache
        Prometheus scrapes LiteLLM + ai-server; Grafana visualizes.
```

Packaged as **one umbrella Helm chart**. The chart lives here in the ai-labs repo;
the Talos cluster deploys it through ArgoCD, which references this path from
`k8s-gitops` (see [Wiring into GitOps](#wiring-into-gitops)).

## Why this mirrors Compose so closely

Every config file (`litellm/config.yaml`, `prometheus.yml`, the Postgres init SQL,
the Grafana provisioning + dashboard) is **copied verbatim** into `files/` and
mounted via ConfigMaps. That works because the Kubernetes Services are given the
same DNS names the Compose services had — `postgres`, `redis`, `litellm`,
`prometheus`, `grafana`, and `ai-server`. So `redis`, `litellm:4000`,
`http://prometheus:9090`, `ai-server:9100`, etc. all resolve without editing the
configs. Keep the two stacks in lockstep by editing the source configs and
re-copying (see the `cp` block below).

## Layout

```
Chart.yaml
values.yaml            # defaults + every toggle, documented inline
values-local.yaml      # laptop cluster: default SC, NodePort, generated Secret
values-talos.yaml      # GitOps: openebs-replicated, Cilium gateway, Vault secrets
files/                 # verbatim configs from the Compose stack (ConfigMap sources)
templates/             # one file per component + secrets, ai-server, gateway
scripts/gen-secret-values.sh   # random secrets for local installs (gitignored output)
```

## Observability: bundled vs. existing kube-prometheus-stack

The chart ships its own Prometheus + Grafana by default (handy on a bare laptop
cluster). If your cluster already runs **kube-prometheus-stack**, turn the bundled
pair off and integrate instead:

```yaml
prometheus:
  enabled: false
grafana:
  enabled: false
monitoring:
  serviceMonitors:
    enabled: true          # kube-prom scrapes litellm + ai-server
  dashboards:
    enabled: true
    namespace: monitoring  # where the kube-prom Grafana sidecar looks
```

This is exactly what `values-talos.yaml` does. It emits:
- a **ServiceMonitor** for LiteLLM (`:4000/metrics`) and one for the external
  **ai-server** (node_exporter `:9100`, dcgm `:9400`) — picked up automatically
  because your stack sets `serviceMonitorSelectorNilUsesHelmValues: false`;
- the LiteLLM dashboard as a **ConfigMap labeled `grafana_dashboard: "1"`** in the
  `monitoring` namespace, which the kube-prom Grafana sidecar auto-imports.

The dashboard's panels use datasource uid `prometheus` — the default uid
kube-prometheus-stack gives its Prometheus datasource — so it resolves as-is. On
Talos, Grafana is therefore the existing instance (its own ingress); the chart
only exposes Open WebUI via the gateway.

## How Compose concepts map

| Compose | Kubernetes |
|---|---|
| `depends_on` + healthchecks | init-container TCP waits + readiness/liveness probes |
| named volumes | PVCs (StatefulSet volumeClaimTemplates / Deployment PVC) |
| `.env` | `values.yaml` + a Secret (generated locally, or Vault-synced on Talos) |
| `extra_hosts: ai-server:<ip>` | selector-less **Service + EndpointSlice** named `ai-server` |
| `DATABASE_URL` with inline password | password from Secret; URL composed via k8s `$(VAR)` env interpolation (plaintext URL never stored) |
| published ports | ClusterIP everywhere; UIs exposed via NodePort (local) or Gateway API (Talos) |

## Run it locally (Docker Desktop k8s / kind / minikube)

```bash
# 1. random secrets -> values-secret.local.yaml (gitignored)
./scripts/gen-secret-values.sh

# 2. install
helm install bap . \
  -f values-local.yaml -f values-secret.local.yaml \
  -n basic-ai-platform --create-namespace

# 3. reach the UIs
kubectl -n basic-ai-platform get pods
kubectl -n basic-ai-platform port-forward svc/open-webui 3000:3000   # http://localhost:3000
kubectl -n basic-ai-platform port-forward svc/grafana    3001:3001   # http://localhost:3001
```

> The external model server must be reachable from cluster pods at
> `aiServer.ip` (default `10.6.6.13`). Override with
> `--set aiServer.ip=<ip> --set localAi.baseUrl=http://ai-server:11434/v1`.

Render without installing: `helm template bap . -f values-local.yaml -f values-secret.local.yaml`.

## Wiring into GitOps

`k8s-gitops/applications/92-basic-ai-platform.yaml` is an ArgoCD `Application`
whose source is **this repo/path**, with `valueFiles: [values-talos.yaml]`. The
existing app-of-apps auto-discovers it.

**One-time prerequisite:** ArgoCD only has a deploy key for `k8s-gitops`. Give it
read access to `tuxoar/ai-labs` too (a second deploy key + repo-credential Secret
in the `argocd` namespace) — same steps as `k8s-gitops/docs/argocd-github-ssh.md`.

The Talos overlay expects the secret keys to exist in Vault at
`secret/basic-ai-platform` (KV-v2): `postgresPassword`, `litellmMasterKey`,
`litellmSaltKey`, `webuiSecretKey`, `grafanaPassword`. VSO syncs them into the
`basic-ai-platform-secrets` Secret. External access is via the Cilium Gateway at
`ai.nuahs.net` (Open WebUI) and `grafana-ai.nuahs.net` (Grafana).

## Keeping configs in sync with the Compose stack

```bash
SRC=../project-1-basic-ai-platform
cp $SRC/litellm/config.yaml                              files/litellm/config.yaml
cp $SRC/prometheus/prometheus.yml                        files/prometheus/prometheus.yml
cp $SRC/postgres/init/01-init.sql                        files/postgres/01-init.sql
cp $SRC/grafana/provisioning/datasources/prometheus.yml files/grafana/datasources/prometheus.yml
cp $SRC/grafana/provisioning/dashboards/dashboards.yaml files/grafana/dashboards/dashboards.yaml
cp $SRC/grafana/provisioning/dashboards/*.json          files/grafana/dashboards/
```

A ConfigMap checksum annotation on each Deployment rolls the pod automatically
when its config changes.
