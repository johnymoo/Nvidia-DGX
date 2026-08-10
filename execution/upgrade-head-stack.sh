#!/usr/bin/env bash
set -euo pipefail

PATH=/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL

readonly EXPECTED_HOST="fusionxparkgb10-3e23"
readonly DEPLOY_USER="chriswang"
readonly BACKUP_ROOT="/var/backups/gb10-ds4-head-maintenance"
readonly ALLOWED_REMOVAL="linux-modules-nvidia-580-open-6.14.0-1015-nvidia"

packages=(
  dgx-spark-ota-update-meta=26.04.1
  linux-nvidia-hwe-24.04=6.17.0-1014.14
  linux-image-nvidia-hwe-24.04=6.17.0-1014.14
  linux-headers-nvidia-hwe-24.04=6.17.0-1014.14
  linux-tools-nvidia-hwe-24.04=6.17.0-1014.14
  linux-modules-nvidia-580-open-nvidia-hwe-24.04=6.17.0-1014.14+1000
  nvidia-driver-580-open=580.142-0ubuntu0.24.04.1
  nvidia-kernel-common-580=580.142-0ubuntu0.24.04.1
  nvidia-kernel-source-580-open=580.142-0ubuntu0.24.04.1
  nvidia-firmware-580-580.142=580.142-0ubuntu0.24.04.1
  libnvidia-gl-580=580.142-0ubuntu0.24.04.1
  libnvidia-common-580=580.142-0ubuntu0.24.04.1
  libnvidia-compute-580=580.142-0ubuntu0.24.04.1
  libnvidia-extra-580=580.142-0ubuntu0.24.04.1
  nvidia-compute-utils-580=580.142-0ubuntu0.24.04.1
  libnvidia-decode-580=580.142-0ubuntu0.24.04.1
  libnvidia-encode-580=580.142-0ubuntu0.24.04.1
  nvidia-utils-580=580.142-0ubuntu0.24.04.1
  xserver-xorg-video-nvidia-580=580.142-0ubuntu0.24.04.1
  libnvidia-cfg1-580=580.142-0ubuntu0.24.04.1
  libnvidia-fbc1-580=580.142-0ubuntu0.24.04.1
  docker-ce=5:29.2.1-1~ubuntu.24.04~noble
  docker-ce-cli=5:29.2.1-1~ubuntu.24.04~noble
  docker-compose-plugin=5.0.2-1~ubuntu.24.04~noble
  nvidia-container-toolkit=1.19.0-1
  nvidia-container-toolkit-base=1.19.0-1
  libnvidia-container-tools=1.19.0-1
  libnvidia-container1=1.19.0-1
)

usage() {
  echo "Usage: $0 [--check|--apply]" >&2
}

mode="${1:---check}"
[ "$#" -le 1 ] && { [ "$mode" = --check ] || [ "$mode" = --apply ]; } || {
  usage
  exit 64
}
[ "$(hostname -s)" = "$EXPECTED_HOST" ] || {
  echo "ERROR: refusing host $(hostname -s)" >&2
  exit 65
}

run_simulation() {
  apt-get -s --no-install-recommends install "${packages[@]}"
}

validate_simulation() {
  local simulation="$1" removal unexpected=0
  grep -Eq '^[0-9]+ upgraded, [0-9]+ newly installed, [0-9]+ to remove' "$simulation" || {
    echo "ERROR: APT simulation has no parseable summary" >&2
    return 1
  }
  while IFS= read -r removal; do
    removal="${removal#Remv }"
    removal="${removal%% *}"
    if [ "$removal" != "$ALLOWED_REMOVAL" ]; then
      echo "ERROR: unexpected package removal: $removal" >&2
      unexpected=1
    fi
  done < <(grep '^Remv ' "$simulation" || true)
  [ "$unexpected" -eq 0 ]
  grep -E '^(The following packages will be (REMOVED|upgraded)|[0-9]+ upgraded|Remv )' "$simulation" || true
}

if [ "$mode" = --check ]; then
  simulation="$(mktemp)"
  trap 'rm -f "$simulation"' EXIT
  run_simulation >"$simulation"
  validate_simulation "$simulation"
  echo "CHECK: exact head package closure is resolvable."
  exit 0
fi

[ "$(id -u)" -eq 0 ] || {
  echo "ERROR: --apply requires root" >&2
  exit 77
}

deploy_uid="$(id -u "$DEPLOY_USER")"
tmux_socket="/tmp/tmux-$deploy_uid/default"
for session in gb10-vllm-model-sync gb10-unsloth-download gb10-prelink-finalizer; do
  if [ -S "$tmux_socket" ] && tmux -S "$tmux_socket" has-session -t "$session" 2>/dev/null; then
    echo "ERROR: tmux session $session is still active" >&2
    exit 75
  fi
done
if pgrep -u "$deploy_uid" -f '(hf download|rsync .*DeepSeek-V4-Flash-0731|finalize-prelink-assets)' >/dev/null; then
  echo "ERROR: a model transfer or finalizer process is still active" >&2
  exit 75
fi

running_known="$({ docker ps --format '{{.Names}}' || true; } | grep -E '^(vllm-qwen36-nvfp4-nightly-aarch64|pdf2md-api|tradingagents-ashare)$' || true)"
if [ -n "$running_known" ]; then
  echo "ERROR: stop known head workloads before --apply:" >&2
  printf '%s\n' "$running_known" >&2
  exit 75
fi

root_free_kib="$(df -Pk / | awk 'NR == 2 { print $4 }')"
[ "$root_free_kib" -ge 20971520 ] || {
  echo "ERROR: less than 20 GiB free on root filesystem" >&2
  exit 75
}

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$BACKUP_ROOT/$stamp"
install -d -m 0700 "$backup"
docker ps -a --no-trunc >"$backup/docker-ps-a.txt"
docker inspect $(docker ps -aq) >"$backup/docker-inspect.json" 2>/dev/null || true
dpkg-query -W >"$backup/dpkg-before.txt"
apt-cache policy "${packages[@]%%=*}" >"$backup/apt-policy-before.txt"
cp -a /etc/docker/daemon.json "$backup/daemon.json" 2>/dev/null || : >"$backup/daemon.json.absent"
journalctl -k --since '2026-08-10 21:40:00' --until '2026-08-10 21:50:00' --no-pager \
  >"$backup/cx7-gpu-incident-kernel.log"

simulation="$backup/apt-simulate.txt"
run_simulation >"$simulation"
validate_simulation "$simulation"

DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}" \
  2>&1 | tee "$backup/apt-install.log"

dpkg-query -W >"$backup/dpkg-after.txt"
test -e /boot/vmlinuz-6.17.0-1014-nvidia
test -d /lib/modules/6.17.0-1014-nvidia
[ "$(dpkg-query -W -f='${Version}' nvidia-driver-580-open)" = 580.142-0ubuntu0.24.04.1 ]
[ "$(dpkg-query -W -f='${Version}' docker-ce)" = '5:29.2.1-1~ubuntu.24.04~noble' ]
[ "$(dpkg-query -W -f='${Version}' nvidia-container-toolkit)" = 1.19.0-1 ]

echo "APPLY: exact head stack installed; backup=$backup"
echo "APPLY: reboot is required and was NOT performed."
