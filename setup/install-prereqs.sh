#!/usr/bin/env bash
#
# Prereqs for ai-labs Project 1 (Compose-first) on Ubuntu 24.04 WSL2.
# Installs Docker Engine + Compose plugin + jq. systemd is already enabled here,
# so dockerd runs as a normal service.
#
# Run with:  sudo bash setup/install-prereqs.sh
#
set -euo pipefail

TARGET_USER="${SUDO_USER:-$USER}"

echo "==> apt prerequisites"
apt-get update
apt-get install -y ca-certificates curl gnupg jq

echo "==> Docker apt repo"
install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
fi
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list

echo "==> install Docker Engine + Compose plugin"
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "==> enable + start docker (systemd)"
systemctl enable --now docker

echo "==> add ${TARGET_USER} to docker group"
usermod -aG docker "${TARGET_USER}"

echo
echo "DONE. Docker $(docker --version 2>/dev/null || echo installed)."
echo "The docker group change needs a new shell. Either:"
echo "  - close and reopen this WSL terminal, or"
echo "  - run:  newgrp docker"
