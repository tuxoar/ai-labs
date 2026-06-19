# Monitoring the AI Server (`ai-server`)

How to expose **host** and **GPU** metrics from the `ai-server` inference box so
the platform's Prometheus (running in the Compose stack on the dev host) can
scrape them. This adds the missing half of "AI observability": the LiteLLM
gateway already gives you request/token/latency metrics, but it can't see the
GPU. After this you'll have **VRAM usage, GPU utilization, temperature, power,
and host CPU/RAM/disk** alongside the gateway metrics.

> Throughout, `<ai-server>` is the hostname or LAN IP of the inference box —
> substitute your own. Nothing here hard-codes an address.

## Target box

| Property | Value |
|---|---|
| Host | `ai-server` (reachable at `<ai-server>`) |
| OS | Ubuntu (systemd) |
| GPU | NVIDIA GeForce RTX 5080, 16 GB (Blackwell, `sm_120`) |
| Driver | 595.71.05 |
| Runs | Ollama (model server) |

## What gets installed

| Component | Port | Provides | Method |
|---|---|---|---|
| **node_exporter** | `9100` | CPU, RAM, disk, network, load | native binary + systemd |
| **Docker Engine** | — | container runtime (for dcgm-exporter) | apt (not yet installed) |
| **NVIDIA Container Toolkit** | — | GPU access for containers | apt |
| **dcgm-exporter** | `9400` | per-GPU util, VRAM, temp, power, clocks | Docker container |

```
Prometheus (Compose, dev host) ──scrape──▶ <ai-server>:9100  (node_exporter)
                               └──scrape──▶ <ai-server>:9400  (dcgm-exporter)
```

> Run every command below **on `ai-server`** (`ssh <you>@<ai-server>`) unless a
> section says "platform side."

---

## Part 1 — node_exporter (host metrics)

Install as a hardened systemd service (no Docker dependency).

```bash
# 1. dedicated unprivileged user
sudo useradd --system --no-create-home --shell /usr/sbin/nologin node_exporter

# 2. download the binary (check https://github.com/prometheus/node_exporter/releases
#    for the latest; set VER accordingly)
VER=1.8.2
cd /tmp
curl -fsSLO "https://github.com/prometheus/node_exporter/releases/download/v${VER}/node_exporter-${VER}.linux-amd64.tar.gz"
tar xzf "node_exporter-${VER}.linux-amd64.tar.gz"
sudo install -m 0755 "node_exporter-${VER}.linux-amd64/node_exporter" /usr/local/bin/node_exporter
node_exporter --version
```

Create the service:

```bash
sudo tee /etc/systemd/system/node_exporter.service >/dev/null <<'EOF'
[Unit]
Description=Prometheus Node Exporter
After=network-online.target
Wants=network-online.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
Restart=on-failure
RestartSec=5
# Listen on all interfaces; the firewall (Part 5) restricts who can reach it.
ExecStart=/usr/local/bin/node_exporter --web.listen-address=:9100

# hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
sudo systemctl status node_exporter --no-pager
```

Verify locally:

```bash
curl -s localhost:9100/metrics | grep -E '^node_(load1|memory_MemAvailable_bytes) ' | head
```

---

## Part 2 — Install Docker Engine

`dcgm-exporter` runs as a container, and Docker is **not yet installed** on
`ai-server`. Install Docker Engine from the official apt repo.

```bash
# prerequisites + Docker apt repo
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

# install engine + compose plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# enable + verify
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

(Optional, to run docker without sudo: `sudo usermod -aG docker "$USER"` then
log out/in. The commands below use `sudo docker` so this isn't required.)

---

## Part 3 — NVIDIA Container Toolkit

This wires the NVIDIA runtime into Docker so containers can see the GPU.

```bash
# add the toolkit repo
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# register the runtime with Docker and restart
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# smoke test — the toolkit bind-mounts nvidia-smi into the container
sudo docker run --rm --gpus all ubuntu nvidia-smi
```

You should see the RTX 5080 listed. If this fails, fix it before continuing —
dcgm-exporter cannot work without it.

---

## Part 4 — dcgm-exporter (GPU metrics)

```bash
# Distroless DCGM 4.x image — required for Blackwell (RTX 5080). Browse tags at:
#   https://catalog.ngc.nvidia.com/orgs/nvidia/containers/dcgm-exporter/tags
DCGM_TAG=4.5.2-4.8.1-distroless

sudo docker run -d --restart unless-stopped \
  --gpus all \
  --name dcgm-exporter \
  --cap-add SYS_ADMIN \
  -p 9400:9400 \
  "nvcr.io/nvidia/k8s/dcgm-exporter:${DCGM_TAG}"

sudo docker logs -f dcgm-exporter   # watch for "Starting webserver" / no init errors
```

Verify locally:

```bash
curl -s localhost:9400/metrics | grep -E 'DCGM_FI_DEV_(GPU_UTIL|FB_USED|GPU_TEMP|POWER_USAGE)'
```
---

## Part 5 — Open the firewall (if `ufw` is active)

Restrict the exporters to the monitoring host only. Find the source IP first —
because Prometheus runs in WSL2, `ai-server` sees traffic from the **Windows
host's LAN IP** (WSL NAT), not the container or WSL interface.

```bash
sudo ufw status                      # is ufw active?
# allow only your LAN subnet (simplest) ...
sudo ufw allow from <LAN_SUBNET> to any port 9100 proto tcp
sudo ufw allow from <LAN_SUBNET> to any port 9400 proto tcp
# ... or lock to a single host: replace <LAN_SUBNET> with <MONITORING_HOST_IP>/32
```

If `ufw` is inactive and the box is on a trusted LAN, you can skip this — but see
Security notes below.

---

## Part 6 — Wire into Prometheus (platform side)

Back on the **dev host**, add two scrape jobs to
`project-1-basic-ai-platform/prometheus/prometheus.yml`:

```yaml
  - job_name: node-ai-server
    static_configs:
      - targets: ["<ai-server>:9100"]
        labels:
          host: ai-server

  - job_name: dcgm-ai-server
    static_configs:
      - targets: ["<ai-server>:9400"]
        labels:
          host: ai-server
```

Reload Prometheus to pick them up:

```bash
cd project-1-basic-ai-platform
docker compose restart prometheus
# or hot-reload without restart (Prometheus must be started with --web.enable-lifecycle):
# curl -X POST http://localhost:9090/-/reload
```

---

## Part 7 — Verify end to end

```bash
# from the dev host, confirm the exporters are reachable across the network:
curl -s http://<ai-server>:9100/metrics | head -1
curl -s http://<ai-server>:9400/metrics | grep -m1 DCGM_FI_DEV_GPU_UTIL

# then check both targets are UP in Prometheus:
#   http://localhost:9090/targets   -> node-ai-server and dcgm-ai-server should be "up"
```

If a target is **down** with a connection error, it's almost always the firewall
(Part 5) or the exporter not running (`systemctl status` / `sudo docker ps` on
the ai-server).

---

## Key metrics you now have

**GPU (DCGM)** — the ones that matter for serving:

| Metric | Meaning |
|---|---|
| `DCGM_FI_DEV_GPU_UTIL` | GPU utilization % |
| `DCGM_FI_DEV_FB_USED` / `DCGM_FI_DEV_FB_FREE` | VRAM used / free (MiB) — watch this against the 16 GB ceiling |
| `DCGM_FI_DEV_GPU_TEMP` | GPU temperature °C |
| `DCGM_FI_DEV_POWER_USAGE` | power draw (W) |
| `DCGM_FI_DEV_SM_CLOCK` / `DCGM_FI_DEV_MEM_CLOCK` | clocks (MHz) |
| `DCGM_FI_DEV_MEM_COPY_UTIL` | memory-controller utilization % |

**Host (node_exporter):** `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes`,
`node_filesystem_avail_bytes`, `node_load1`, `node_network_*`.

Useful pairing: when a model loads, `DCGM_FI_DEV_FB_USED` jumps — that's how you
confirm Ollama is actually on the GPU and see how much VRAM each model eats.

## Grafana dashboards

Import community dashboards by ID (Grafana → Dashboards → New → Import):

- **1860** — Node Exporter Full (host)
- **12239** — NVIDIA DCGM Exporter (GPU)

Both use the provisioned `Prometheus` datasource. These complement the
hand-built **LiteLLM — AI Gateway Overview** dashboard in this repo.

## Security notes

- Prometheus exporters serve **unauthenticated** metrics over plain HTTP. Anyone
  who can reach `:9100`/`:9400` can read host/GPU telemetry. Keep them firewalled
  to the monitoring host/subnet (Part 5).
- `dcgm-exporter` needs `--cap-add SYS_ADMIN` for GPU profiling counters — normal
  for this exporter, but it's a privileged container, so don't expose `:9400`
  publicly.
- For a production/Talos deployment you'd front these with TLS + auth (or scrape
  over a private network / mesh) rather than open ports on the LAN.

## Uninstall / rollback

```bash
# node_exporter
sudo systemctl disable --now node_exporter
sudo rm /etc/systemd/system/node_exporter.service /usr/local/bin/node_exporter
sudo userdel node_exporter
sudo systemctl daemon-reload

# dcgm-exporter
sudo docker rm -f dcgm-exporter
```
