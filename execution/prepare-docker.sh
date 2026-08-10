#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [--check] | --apply USER" >&2
}

mode="${1:---check}"
target_user="${2:-${SUDO_USER:-${USER:-}}}"

for command in docker nvidia-ctk systemctl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    exit 1
  fi
done

echo "docker=$(docker --version)"
echo "compose=$(docker compose version 2>/dev/null || true)"
echo "nvidia_ctk=$(nvidia-ctk --version | head -1)"
echo "daemon=$(systemctl is-active docker || true)"
echo "user=$(id)"
echo "docker_group=$(getent group docker || true)"

if [ "$mode" = "--check" ]; then
  if docker info >/dev/null 2>&1; then
    echo "docker_access=ok"
  else
    echo "docker_access=missing"
    exit 2
  fi
  exit 0
fi

if [ "$mode" != "--apply" ] || [ -z "$target_user" ]; then
  usage
  exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "Apply mode requires root: sudo $0 --apply $target_user" >&2
  exit 1
fi

if ! id "$target_user" >/dev/null 2>&1; then
  echo "Unknown user: $target_user" >&2
  exit 1
fi

systemctl enable --now docker
getent group docker >/dev/null 2>&1 || groupadd --system docker
usermod -aG docker "$target_user"

if ! docker info --format '{{json .Runtimes}}' | grep -q 'nvidia'; then
  nvidia-ctk runtime configure --runtime=docker
  systemctl restart docker
fi

echo "Docker preparation complete for $target_user. Log out and back in before testing."
