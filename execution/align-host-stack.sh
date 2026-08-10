#!/usr/bin/env bash
# Safely inspect, then stage only the non-disruptive portion of host alignment.
set -euo pipefail

readonly HEAD_HOSTNAME="fusionxparkgb10-3e23"
readonly WORKER_HOSTNAME="spark-3345"
readonly DOCKER_CONFIG="/etc/docker/daemon.json"
readonly BACKUP_DIR="/var/backups/gb10-ds4-host-alignment"
readonly EXPECTED_KERNEL="6.17.0-1014-nvidia"
readonly EXPECTED_DRIVER="580.142"
readonly EXPECTED_DOCKER="29.2.1"
readonly EXPECTED_COMPOSE="v5.0.2"
readonly EXPECTED_TOOLKIT="1.19.0"
readonly EXPECTED_RDMA="50.0-2ubuntu0.2"

usage() {
  cat >&2 <<'EOF'
Usage: align-host-stack.sh [--check|--apply]

Default and --check are read-only. --apply is restricted to the worker and
only merges Docker json-file log rotation (50m x 10) into daemon.json. It
never restarts Docker, changes packages, limits, swap, containers, or reboots.
EOF
}

mode="${1:---check}"
if [ "$#" -gt 1 ] || { [ "$mode" != "--check" ] && [ "$mode" != "--apply" ]; }; then
  usage
  exit 64
fi
for command in apt-cache docker dockerd dpkg-query hostname jq nvidia-ctk nvidia-smi swapon uname; do
  command -v "$command" >/dev/null 2>&1 || { echo "ERROR: missing $command" >&2; exit 69; }
done

host="$(hostname -s)"
case "$host" in
  "$HEAD_HOSTNAME") role="head" ;;
  "$WORKER_HOSTNAME") role="worker" ;;
  *) echo "ERROR: refusing unknown host '$host'" >&2; exit 65 ;;
esac

issues=0
issue() { echo "PENDING: $*" >&2; issues=$((issues + 1)); }
note() { echo "NOTE: $*" >&2; }
value() { printf '%s=%s\n' "$1" "$2"; }
installed() { dpkg-query -W -f='${Version}' "$1" 2>/dev/null || printf not-installed; }
candidate() { apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ { print $2; exit }'; }
rotation_ok() {
  [ -f "$DOCKER_CONFIG" ] && jq -e '."log-driver" == "json-file" and ."log-opts"."max-size" == "50m" and ."log-opts"."max-file" == "10"' "$DOCKER_CONFIG" >/dev/null
}

kernel="$(uname -r)"
driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
docker_version="$(docker version --format '{{.Server.Version}}' 2>/dev/null || printf unavailable)"
compose_version="$(docker compose version 2>/dev/null | sed 's/^Docker Compose version //')"
toolkit_version="$(nvidia-ctk --version 2>/dev/null | sed -n 's/^NVIDIA Container Toolkit CLI version //p' | head -1)"

value host "$host"
value role "$role"
value kernel "$kernel"
value driver "$driver"
value docker "$docker_version"
value compose "$compose_version"
value nvidia_container_toolkit "${toolkit_version:-unavailable}"
value rdma_core "$(installed rdma-core)"
value rdma_core_candidate "$(candidate rdma-core)"
value memlock_kib "$(ulimit -l)"
value active_swap "$(swapon --show --bytes --noheadings 2>/dev/null | awk '{print $1 ":size=" $3 ":used=" $4}' | paste -sd, - || true)"

rotation_ok || issue "Docker json-file rotation is not configured as 50m x 10"
[ "$docker_version" = "$EXPECTED_DOCKER" ] || issue "Docker server must be $EXPECTED_DOCKER"
[ "$compose_version" = "$EXPECTED_COMPOSE" ] || issue "Docker Compose must be $EXPECTED_COMPOSE"
[ "$toolkit_version" = "$EXPECTED_TOOLKIT" ] || issue "NVIDIA Container Toolkit must be $EXPECTED_TOOLKIT"
[ "$(installed rdma-core)" = "$EXPECTED_RDMA" ] || issue "rdma-core must be $EXPECTED_RDMA"
[ "$(installed libibverbs1)" = "$EXPECTED_RDMA" ] || issue "libibverbs1 must be $EXPECTED_RDMA"
[ "$(installed ibverbs-providers)" = "$EXPECTED_RDMA" ] || issue "ibverbs-providers must be $EXPECTED_RDMA"
case "$role" in
  head)
    [ "$kernel" = "$EXPECTED_KERNEL" ] || issue "head kernel requires Spark OTA maintenance update"
    [ "$driver" = "$EXPECTED_DRIVER" ] || issue "head driver requires Spark OTA maintenance update"
    [ "$(installed dgx-release)" = "7.5.0" ] || issue "head dgx-release must be 7.5.0"
    [ "$(installed dgx-spark-ota-update-meta)" = "26.04.1" ] || issue "head Spark OTA meta must be 26.04.1"
    [ "$(installed nvidia-spark-repo)" = "1.1-1" ] || issue "head NVIDIA Spark repository package must be 1.1-1"
    [ -f /etc/security/limits.d/99-nv-spark-limits.conf ] || issue "head unlimited memlock comes with Spark OTA"
    ;;
  worker)
    [ "$kernel" = "$EXPECTED_KERNEL" ] || issue "worker kernel is not the target Spark baseline"
    [ "$driver" = "$EXPECTED_DRIVER" ] || issue "worker driver is not the target Spark baseline"
    [ "$(installed dgx-release)" = "7.5.0" ] || issue "worker dgx-release must be 7.5.0"
    [ "$(installed dgx-spark-ota-update-meta)" = "26.04.1" ] || issue "worker Spark OTA meta must be 26.04.1"
    [ "$(installed nvidia-spark-repo)" = "1.1-1" ] || issue "worker NVIDIA Spark repository package must be 1.1-1"
    [ -f /etc/security/limits.d/99-nv-spark-limits.conf ] || issue "worker Spark memlock policy is missing"
    if swapon --show --noheadings 2>/dev/null | awk 'NF { found=1 } END { exit !found }'; then
      note "worker swap remains configured; benchmark gate must reject any increase in pswpin/pswpout"
    fi
    ;;
esac

if [ "$mode" = "--check" ]; then
  if [ "$issues" -ne 0 ]; then
    echo "CHECK: $issues alignment item(s) pending; no changes made." >&2
    exit 2
  fi
  echo "CHECK: host alignment state is current."
  exit 0
fi

# Package changes and daemon restarts can interrupt user workloads; keep them out of apply.
if [ "$role" != "worker" ]; then
  echo "REFUSED: --apply is never permitted on head; use the maintenance plan." >&2
  exit 77
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: --apply requires root: sudo $0 --apply" >&2
  exit 77
fi
install -d -m 0700 "$BACKUP_DIR"
tmp="$(mktemp "${DOCKER_CONFIG}.gb10-ds4.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
if [ -e "$DOCKER_CONFIG" ]; then
  jq -e . "$DOCKER_CONFIG" >/dev/null || { echo "ERROR: invalid Docker JSON" >&2; exit 65; }
  jq --argjson log_opts '{"max-size":"50m","max-file":"10"}' \
    '. + {"log-driver":"json-file"} | .["log-opts"] = ((.["log-opts"] // {}) + $log_opts)' \
    "$DOCKER_CONFIG" >"$tmp"
else
  jq -n '{"log-driver":"json-file","log-opts":{"max-size":"50m","max-file":"10"}}' >"$tmp"
fi
jq -e . "$tmp" >/dev/null
dockerd --validate --config-file "$tmp" >/dev/null
if [ -e "$DOCKER_CONFIG" ] && cmp -s "$tmp" "$DOCKER_CONFIG"; then
  echo "APPLY: Docker log rotation already configured; no file changed."
else
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  if [ -e "$DOCKER_CONFIG" ]; then
    backup="$BACKUP_DIR/daemon.json.$stamp"
    cp --preserve=mode,ownership,timestamps "$DOCKER_CONFIG" "$backup"
  else
    backup="$BACKUP_DIR/daemon.json.absent.$stamp"
    : >"$backup"
  fi
  install -m 0644 "$tmp" "$DOCKER_CONFIG"
  echo "APPLY: wrote $DOCKER_CONFIG; backup=$backup"
fi
echo "APPLY: Docker was NOT restarted; policy activates in an approved maintenance window."
echo "REFUSED: package, RDMA, memlock, swap, container, daemon restart, and reboot changes need the plan."
