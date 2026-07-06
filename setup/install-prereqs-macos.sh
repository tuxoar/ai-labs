#!/usr/bin/env bash
#
# Prereqs for ai-labs Project 1 (Compose-first) on macOS (Apple Silicon or Intel).
# Installs Homebrew (if missing), jq, and Docker Desktop (Engine + Compose plugin),
# then starts Docker and waits for the daemon to come up.
#
# macOS has no apt/systemd and no docker group — Docker Desktop runs the engine in
# a lightweight VM and the invoking user already has access to the socket.
#
# Run with:  bash setup/install-prereqs.sh
# (Do NOT run with sudo — Homebrew refuses to run as root.)
#
set -euo pipefail

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
  echo "ERROR: run this WITHOUT sudo — Homebrew and Docker Desktop install per-user." >&2
  exit 1
fi

if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: this script targets macOS. For Ubuntu/WSL2 use the Linux prereqs steps." >&2
  exit 1
fi

echo "==> Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  echo "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
# Make brew available on this shell (Apple Silicon: /opt/homebrew, Intel: /usr/local).
if [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

echo "==> jq"
if ! command -v jq >/dev/null 2>&1; then
  brew install jq
fi

echo "==> Docker Desktop (Engine + Compose plugin)"
if ! command -v docker >/dev/null 2>&1 && [ ! -d /Applications/Docker.app ]; then
  brew install --cask docker
fi

echo "==> start Docker and wait for the daemon"
if ! docker info >/dev/null 2>&1; then
  open -a Docker
  printf "waiting for Docker daemon"
  for _ in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
      break
    fi
    printf "."
    sleep 2
  done
  echo
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon did not come up. Open Docker Desktop manually and re-run." >&2
  exit 1
fi

echo
echo "DONE. $(docker --version)."
echo "Compose plugin: $(docker compose version 2>/dev/null || echo 'not found')."
echo "jq: $(jq --version)."
echo
echo "Next:  cd project-1-basic-ai-platform && docker compose up -d"
