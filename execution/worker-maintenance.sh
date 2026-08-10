#!/usr/bin/env bash
# Root-owned deployment target installed by install-worker-maintenance-sudoers.sh.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
LC_ALL=C
export LC_ALL

readonly EXPECTED_HOST="spark-3345"
readonly EXPECTED_USER="admin"
readonly DOCKER_CONFIG="/etc/docker/daemon.json"
readonly BACKUP_ROOT="/var/backups/gb10-ds4-worker-maintenance"
readonly FSTAB="/etc/fstab"
readonly SWAP_FILE="/swap.img"
readonly UBUNTU_SOURCES="/etc/apt/sources.list.d/ubuntu.sources"
readonly UBUNTU_PORTS="http://ports.ubuntu.com/ubuntu-ports/"
readonly TUNA_PORTS="https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/"
readonly FABRIC_IF="enp1s0f0np0"
readonly FABRIC_CIDR="192.168.192.198/24"
readonly FABRIC_PEER="192.168.192.181"
readonly FABRIC_CONNECTION="gb10-ds4-fabric-enp1s0f0np0"

usage() {
  echo "Usage: gb10-ds4-worker-maintenance {check|apply-basic|restart-docker|configure-fabric|remove-swap|apt-use-tuna}" >&2
}

[ "$#" -eq 1 ] || { usage; exit 64; }
case "$1" in
  check|apply-basic|restart-docker|configure-fabric|remove-swap|apt-use-tuna) action="$1" ;;
  *) usage; exit 64 ;;
esac
[ "$(/usr/bin/id -u)" -eq 0 ] || { echo "ERROR: root is required." >&2; exit 77; }
[ "$(/bin/hostname -s)" = "$EXPECTED_HOST" ] || { echo "ERROR: refusing host $(/bin/hostname -s)." >&2; exit 65; }
admin_uid="$(/usr/bin/id -u "$EXPECTED_USER" 2>/dev/null)" || { echo "ERROR: admin is absent." >&2; exit 65; }
[ "${SUDO_USER:-}" = "$EXPECTED_USER" ] && [ "${SUDO_UID:-}" = "$admin_uid" ] || {
  echo "ERROR: only an admin sudo invocation is allowed." >&2; exit 77;
}

require() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: missing $1" >&2; exit 69; }; }
for command in apt-cache apt-get awk cat chown chmod cmp cp date docker dockerd dpkg-query findmnt grep id ip jq mkdir mktemp mv nmcli ping rdma rm sed sleep stat swapoff swapon systemctl tee timeout; do require "$command"; done

stamp() { /bin/date -u +%Y%m%dT%H%M%SZ; }
backup_dir() { local dir="$BACKUP_ROOT/$(stamp)"; /bin/mkdir -p -m 0700 "$dir"; printf '%s\n' "$dir"; }
staged_tmp=""
cleanup_staged_tmp() {
  local status=$?
  if [ -n "${staged_tmp:-}" ]; then
    /bin/rm -f -- "$staged_tmp" || true
  fi
  return "$status"
}
pkg_version() { /usr/bin/dpkg-query -W -f='${Version}' "$1" 2>/dev/null || printf 'not-installed'; }
candidate_version() { /usr/bin/apt-cache policy "$1" 2>/dev/null | /usr/bin/awk '/Candidate:/ { print $2; exit }'; }
json_rotation_ok() {
  [ -f "$DOCKER_CONFIG" ] && /usr/bin/jq -e '."log-driver" == "json-file" and ."log-opts"."max-size" == "50m" and ."log-opts"."max-file" == "10"' "$DOCKER_CONFIG" >/dev/null
}
lexdata_health() {
  /usr/bin/docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' lexdata-ai 2>/dev/null || printf absent
}

check() {
  printf 'host=%s\n' "$(/bin/hostname -s)"
  printf 'docker_daemon=%s\n' "$(/bin/systemctl is-active docker 2>/dev/null || true)"
  if [ -f "$DOCKER_CONFIG" ]; then
    printf 'docker_daemon_json=present\n'
    /usr/bin/jq -c '{"log-driver": .["log-driver"], "log-opts": .["log-opts"], "registry-mirrors": .["registry-mirrors"], "insecure-registries": .["insecure-registries"], "runtimes": .runtimes}' "$DOCKER_CONFIG"
  else
    printf 'docker_daemon_json=absent\n'
  fi
  printf 'docker_log_rotation=%s\n' "$(json_rotation_ok && printf aligned || printf pending)"
  for package in rdma-core libibverbs1 ibverbs-providers; do
    printf '%s=%s candidate=%s\n' "$package" "$(pkg_version "$package")" "$(candidate_version "$package")"
  done
  printf 'fabric_interface=%s\n' "$FABRIC_IF"
  /usr/sbin/ip -br link show dev "$FABRIC_IF" || true
  /usr/sbin/ip -br address show dev "$FABRIC_IF" || true
  /usr/bin/rdma link show 2>/dev/null | /usr/bin/grep -F "$FABRIC_IF" || true
  printf 'lexdata_ai=%s\n' "$(lexdata_health)"
  printf 'swappiness=%s\n' "$(/bin/cat /proc/sys/vm/swappiness)"
  printf 'active_swap='
  /usr/sbin/swapon --show --bytes --noheadings 2>/dev/null \
    | /usr/bin/awk '{printf "%s:size=%s:used=%s ", $1, $3, $4}'
  printf '\n'
}

apply_basic() {
  local backup tmp simulation
  backup="$(backup_dir)"
  tmp="$(/usr/bin/mktemp "${DOCKER_CONFIG}.gb10-ds4.XXXXXX")"
  trap '/bin/rm -f "${tmp:-}"' EXIT
  if [ -e "$DOCKER_CONFIG" ]; then
    /usr/bin/jq -e . "$DOCKER_CONFIG" >/dev/null || { echo "ERROR: invalid Docker daemon JSON." >&2; exit 65; }
    /bin/cp --preserve=mode,ownership,timestamps "$DOCKER_CONFIG" "$backup/daemon.json"
    /usr/bin/jq --argjson log_opts '{"max-size":"50m","max-file":"10"}' \
      '. + {"log-driver":"json-file"} | .["log-opts"] = ((.["log-opts"] // {}) + $log_opts)' \
      "$DOCKER_CONFIG" >"$tmp"
  else
    : >"$backup/daemon.json.absent"
    /usr/bin/jq -n '{"log-driver":"json-file","log-opts":{"max-size":"50m","max-file":"10"}}' >"$tmp"
  fi
  /usr/bin/jq -e . "$tmp" >/dev/null
  /usr/bin/dockerd --validate --config-file "$tmp" >/dev/null
  if [ -e "$DOCKER_CONFIG" ] && /usr/bin/cmp -s "$tmp" "$DOCKER_CONFIG"; then
    echo "APPLY-BASIC: Docker log rotation already configured."
  else
    /usr/bin/chown root:root "$tmp"
    /usr/bin/chmod 0644 "$tmp"
    /bin/mv -f "$tmp" "$DOCKER_CONFIG"
    echo "APPLY-BASIC: Docker configuration staged; Docker was not restarted."
  fi
  simulation="$backup/rdma-apt-simulate.txt"
  /usr/bin/dpkg-query -W rdma-core libibverbs1 ibverbs-providers \
    >"$backup/rdma-packages-before.txt"
  /usr/bin/apt-get -s --no-install-recommends --only-upgrade install \
    rdma-core=50.0-2ubuntu0.2 \
    libibverbs1=50.0-2ubuntu0.2 \
    ibverbs-providers=50.0-2ubuntu0.2 >"$simulation"
  if /usr/bin/grep -q '^Remv ' "$simulation"; then
    echo "ERROR: RDMA simulation contains removals; evidence=$simulation" >&2
    exit 65
  fi
  DEBIAN_FRONTEND=noninteractive /usr/bin/apt-get install -y --no-install-recommends --only-upgrade \
    rdma-core=50.0-2ubuntu0.2 \
    libibverbs1=50.0-2ubuntu0.2 \
    ibverbs-providers=50.0-2ubuntu0.2
  /usr/bin/dpkg-query -W rdma-core libibverbs1 ibverbs-providers \
    >"$backup/rdma-packages-after.txt"
  printf 'backup=%s\n' "$backup"
  printf 'rdma_core=%s\n' "$(pkg_version rdma-core)"
}

restart_docker() {
  local backup health deadline
  backup="$(backup_dir)"
  if [ -e "$DOCKER_CONFIG" ]; then
    /usr/bin/jq -e . "$DOCKER_CONFIG" >/dev/null
    /usr/bin/dockerd --validate --config-file "$DOCKER_CONFIG" >/dev/null
  fi
  /usr/bin/docker ps --no-trunc >"$backup/docker-ps-before.txt"
  /usr/bin/docker inspect lexdata-ai >"$backup/lexdata-ai-inspect-before.json" 2>&1 || true
  /usr/bin/docker logs --tail 500 lexdata-ai >"$backup/lexdata-ai-before.log" 2>&1 || true
  /bin/systemctl restart docker
  deadline=$(( $(/bin/date +%s) + 120 ))
  while [ "$(/bin/date +%s)" -lt "$deadline" ]; do
    health="$(lexdata_health)"
    [ "$health" = "healthy" ] && { echo "RESTART-DOCKER: lexdata-ai healthy."; return 0; }
    /bin/sleep 2
  done
  /usr/bin/docker ps --no-trunc >"$backup/docker-ps-after-timeout.txt" 2>&1 || true
  /usr/bin/docker inspect lexdata-ai >"$backup/lexdata-ai-inspect-after-timeout.json" 2>&1 || true
  /usr/bin/docker logs --tail 500 lexdata-ai >"$backup/lexdata-ai-after-timeout.log" 2>&1 || true
  echo "ERROR: lexdata-ai did not become healthy; evidence=$backup" >&2
  return 1
}

configure_fabric() {
  local backup rollback_connection rdma_state existed active=0
  [ -d "/sys/class/net/$FABRIC_IF" ] || { echo "ERROR: missing $FABRIC_IF." >&2; return 65; }
  [ "$(/bin/cat "/sys/class/net/$FABRIC_IF/carrier" 2>/dev/null || printf 0)" = 1 ] || {
    echo "ERROR: $FABRIC_IF has no carrier; configuration was not changed." >&2; return 2;
  }
  /bin/systemctl is-active --quiet NetworkManager || { echo "ERROR: NetworkManager is inactive." >&2; return 69; }
  backup="$(backup_dir)"
  rollback_connection="${FABRIC_CONNECTION}-rollback-$(stamp)"
  if /usr/bin/nmcli -g NAME connection show | /usr/bin/grep -Fxq "$FABRIC_CONNECTION"; then
    existed=1
    /usr/bin/nmcli -t -f NAME,DEVICE connection show --active | /usr/bin/grep -Fqx "${FABRIC_CONNECTION}:${FABRIC_IF}" && active=1 || true
    /usr/bin/nmcli connection clone "$FABRIC_CONNECTION" "$rollback_connection"
    /usr/bin/nmcli connection show "$rollback_connection" >"$backup/networkmanager-rollback.txt"
  else
    existed=0
  fi
  rollback_fabric() {
    if [ "$existed" -eq 1 ]; then
      /usr/bin/nmcli connection down "$FABRIC_CONNECTION" >/dev/null 2>&1 || true
      /usr/bin/nmcli connection delete "$FABRIC_CONNECTION" >/dev/null 2>&1 || true
      /usr/bin/nmcli connection modify "$rollback_connection" connection.id "$FABRIC_CONNECTION" >/dev/null 2>&1 || true
      [ "$active" -eq 1 ] && /usr/bin/nmcli connection up "$FABRIC_CONNECTION" >/dev/null 2>&1 || true
    else
      /usr/bin/nmcli connection down "$FABRIC_CONNECTION" >/dev/null 2>&1 || true
      /usr/bin/nmcli connection delete "$FABRIC_CONNECTION" >/dev/null 2>&1 || true
    fi
  }
  if [ "$existed" -eq 1 ]; then
    /usr/bin/nmcli connection modify "$FABRIC_CONNECTION" connection.interface-name "$FABRIC_IF" \
      ipv4.method manual ipv4.addresses "$FABRIC_CIDR" ipv4.never-default yes ipv6.method disabled ethernet.mtu 9000 || {
        rollback_fabric; return 1;
      }
  else
    /usr/bin/nmcli connection add type ethernet ifname "$FABRIC_IF" con-name "$FABRIC_CONNECTION" \
      ipv4.method manual ipv4.addresses "$FABRIC_CIDR" ipv4.never-default yes ipv6.method disabled ethernet.mtu 9000 || {
        rollback_fabric; return 1;
      }
  fi
  /usr/bin/nmcli connection up "$FABRIC_CONNECTION" || { rollback_fabric; return 1; }
  /usr/sbin/ip -4 -o address show dev "$FABRIC_IF" | /usr/bin/grep -Fq " $FABRIC_CIDR " || {
    rollback_fabric; return 1;
  }
  [ "$(/bin/cat "/sys/class/net/$FABRIC_IF/mtu")" = 9000 ] || { rollback_fabric; return 1; }
  if /usr/sbin/ip -4 route show default dev "$FABRIC_IF" | /usr/bin/grep -q .; then
    rollback_fabric; return 1
  fi
  rdma_state="$(/usr/bin/rdma link show | /usr/bin/grep -F "netdev $FABRIC_IF " || true)"
  printf '%s\n' "$rdma_state" | /usr/bin/grep -Fq 'state ACTIVE' || { rollback_fabric; return 1; }
  printf '%s\n' "$rdma_state" | /usr/bin/grep -Fq 'physical_state LINK_UP' || { rollback_fabric; return 1; }
  /usr/bin/ping -c 3 -W 2 "$FABRIC_PEER" >/dev/null || { rollback_fabric; return 1; }
  if [ "$existed" -eq 1 ] && ! /usr/bin/nmcli connection delete "$rollback_connection"; then
    echo "WARNING: configured fabric but retained rollback connection $rollback_connection" >&2
  fi
  printf 'CONFIGURE-FABRIC: %s %s peer=%s configured; rollback=%s\n' "$FABRIC_IF" "$FABRIC_CIDR" "$FABRIC_PEER" "$backup"
}

capture_swap_evidence() {
  local backup="$1"
  /bin/cp --preserve=mode,ownership,timestamps "$FSTAB" "$backup/fstab-before"
  /usr/sbin/swapon --show --bytes >"$backup/swapon-before.txt"
  /usr/bin/grep -E '^(pswpin|pswpout) ' /proc/vmstat >"$backup/vmstat-before.txt" || true
  if [ -e "$SWAP_FILE" ] || [ -L "$SWAP_FILE" ]; then
    /usr/bin/stat --printf='%n\nmode=%a\nuid=%u\ngid=%g\nsize=%s\nmtime=%y\n' "$SWAP_FILE" >"$backup/swap.img-before.txt"
  else
    printf '%s absent\n' "$SWAP_FILE" >"$backup/swap.img-before.txt"
  fi
}

active_swap_names() {
  /usr/sbin/swapon --show=NAME --noheadings --raw
}

only_swap_img_is_active() {
  local active name
  active="$(active_swap_names)" || return 1
  while IFS= read -r name; do
    [ -z "$name" ] && continue
    [ "$name" = "$SWAP_FILE" ] || return 1
  done <<<"$active"
}

fstab_has_only_swap_img_entries() {
  /usr/bin/awk '
    /^[[:space:]]*($|#)/ { next }
    $3 == "swap" && $1 != "/swap.img" { bad = 1 }
    END { exit bad }
  ' "$1"
}

fstab_has_swap_img_entry() {
  /usr/bin/awk '
    /^[[:space:]]*($|#)/ { next }
    $1 == "/swap.img" && $3 == "swap" { found = 1 }
    END { exit !found }
  ' "$1"
}

remove_swap_img_entries() {
  /usr/bin/awk '
    /^[[:space:]]*($|#)/ { print; next }
    $1 == "/swap.img" && $3 == "swap" { next }
    { print }
  ' "$1"
}

remove_swap() {
  local backup tmp
  trap cleanup_staged_tmp EXIT
  [ -f "$FSTAB" ] && [ ! -L "$FSTAB" ] || { echo "ERROR: refusing non-regular $FSTAB." >&2; return 65; }
  backup="$(backup_dir)"
  capture_swap_evidence "$backup"
  fstab_has_only_swap_img_entries "$FSTAB" || {
    echo "ERROR: refusing non-$SWAP_FILE swap entry in $FSTAB; backup=$backup" >&2
    return 65
  }
  only_swap_img_is_active || {
    echo "ERROR: refusing active swap other than $SWAP_FILE; backup=$backup" >&2
    return 65
  }
  if [ -L "$SWAP_FILE" ] || { [ -e "$SWAP_FILE" ] && [ ! -f "$SWAP_FILE" ]; }; then
    echo "ERROR: refusing non-regular $SWAP_FILE; backup=$backup" >&2
    return 65
  fi
  active_swap_names >"$backup/active-swap-before.txt"
  if /usr/bin/grep -Fxq "$SWAP_FILE" "$backup/active-swap-before.txt"; then
    /usr/sbin/swapoff "$SWAP_FILE"
  fi
  only_swap_img_is_active || {
    echo "ERROR: swap other than $SWAP_FILE appeared during removal; backup=$backup" >&2
    return 65
  }
  if fstab_has_swap_img_entry "$FSTAB"; then
    tmp="$(/usr/bin/mktemp "${FSTAB}.gb10-ds4.XXXXXX")"
    staged_tmp="$tmp"
    remove_swap_img_entries "$FSTAB" >"$tmp"
    /usr/bin/findmnt --verify --tab-file "$tmp" >/dev/null
    fstab_has_only_swap_img_entries "$tmp" || { echo "ERROR: staged fstab has an unexpected swap entry." >&2; return 65; }
    ! fstab_has_swap_img_entry "$tmp" || { echo "ERROR: staged fstab still contains $SWAP_FILE." >&2; return 65; }
    /bin/chown --reference="$FSTAB" "$tmp"
    /bin/chmod --reference="$FSTAB" "$tmp"
    /bin/mv -f "$tmp" "$FSTAB"
    staged_tmp=""
  fi
  /usr/bin/findmnt --verify --tab-file "$FSTAB" >/dev/null
  ! fstab_has_swap_img_entry "$FSTAB" || { echo "ERROR: persistent $SWAP_FILE entry remains; backup=$backup" >&2; return 65; }
  active_swap_names >"$backup/active-swap-after.txt"
  if /usr/bin/grep -q . "$backup/active-swap-after.txt"; then
    echo "ERROR: active swap remains; refusing to delete $SWAP_FILE; backup=$backup" >&2
    return 65
  fi
  if [ -e "$SWAP_FILE" ] || [ -L "$SWAP_FILE" ]; then
    /bin/rm -f -- "$SWAP_FILE"
  fi
  printf 'REMOVE-SWAP: no active or persistent swap remains; backup=%s\n' "$backup"
  trap - EXIT
}

validate_ubuntu_deb822() {
  /usr/bin/awk '
    function finish() {
      if (!in_stanza) return
      if (!("Types" in field) || !("URIs" in field) || !("Suites" in field)) bad = 1
      delete field
      in_stanza = 0
    }
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { finish(); next }
    /^[A-Za-z0-9][A-Za-z0-9-]*:[[:space:]]*/ {
      split($0, parts, ":")
      field[parts[1]] = 1
      in_stanza = 1
      next
    }
    /^[[:space:]]+/ { if (!in_stanza) bad = 1; next }
    { bad = 1 }
    END { finish(); exit bad }
  ' "$1"
}

apt_update_once() {
  local log="$1"
  /usr/bin/timeout --foreground 180 /usr/bin/apt-get update \
    -o Acquire::Retries=1 \
    -o Acquire::http::Timeout=20 \
    -o Acquire::https::Timeout=20 >"$log" 2>&1
}

apt_update_with_retry() {
  local backup="$1" attempt log
  for attempt in 1 2 3; do
    log="$backup/apt-update-attempt-${attempt}.log"
    if apt_update_once "$log"; then
      return 0
    fi
    [ "$attempt" -eq 3 ] || /bin/sleep 5
  done
  echo "ERROR: apt-get update failed after 3 bounded attempts; evidence=$backup" >&2
  return 1
}

apt_use_tuna() {
  local backup tmp old_count tuna_count
  trap cleanup_staged_tmp EXIT
  [ -f "$UBUNTU_SOURCES" ] && [ ! -L "$UBUNTU_SOURCES" ] || {
    echo "ERROR: refusing non-regular $UBUNTU_SOURCES." >&2
    return 65
  }
  backup="$(backup_dir)"
  /bin/cp --preserve=mode,ownership,timestamps "$UBUNTU_SOURCES" "$backup/ubuntu.sources-before"
  old_count="$(/usr/bin/grep -Foc "$UBUNTU_PORTS" "$UBUNTU_SOURCES" || true)"
  tuna_count="$(/usr/bin/grep -Foc "$TUNA_PORTS" "$UBUNTU_SOURCES" || true)"
  if [ "$old_count" -eq 0 ] && [ "$tuna_count" -eq 0 ]; then
    echo "ERROR: neither expected Ubuntu Ports URI is present; backup=$backup" >&2
    return 65
  fi
  tmp="$(/usr/bin/mktemp "${UBUNTU_SOURCES}.gb10-ds4.XXXXXX")"
  staged_tmp="$tmp"
  /usr/bin/sed "s|$UBUNTU_PORTS|$TUNA_PORTS|g" "$UBUNTU_SOURCES" >"$tmp"
  validate_ubuntu_deb822 "$tmp" || { echo "ERROR: staged Ubuntu source is not valid deb822." >&2; return 65; }
  if ! /usr/bin/cmp -s "$tmp" "$UBUNTU_SOURCES"; then
    /bin/chown --reference="$UBUNTU_SOURCES" "$tmp"
    /bin/chmod --reference="$UBUNTU_SOURCES" "$tmp"
    /bin/mv -f "$tmp" "$UBUNTU_SOURCES"
    staged_tmp=""
  else
    /bin/rm -f -- "$tmp"
    staged_tmp=""
  fi
  /usr/bin/grep -Fq "$TUNA_PORTS" "$UBUNTU_SOURCES" || {
    echo "ERROR: TUNA URI is absent after staging; backup=$backup" >&2
    return 65
  }
  if /usr/bin/grep -Fq "$UBUNTU_PORTS" "$UBUNTU_SOURCES"; then
    echo "ERROR: Ubuntu Ports URI remains after staging; backup=$backup" >&2
    return 65
  fi
  validate_ubuntu_deb822 "$UBUNTU_SOURCES" || {
    echo "ERROR: installed Ubuntu source is not valid deb822." >&2
    return 65
  }
  apt_update_with_retry "$backup"
  printf 'APT-USE-TUNA: Ubuntu base source is TUNA; indexes refreshed only; backup=%s\n' "$backup"
  trap - EXIT
}

case "$action" in
  check) check ;;
  apply-basic) apply_basic ;;
  restart-docker) restart_docker ;;
  configure-fabric) configure_fabric ;;
  remove-swap) remove_swap ;;
  apt-use-tuna) apt_use_tuna ;;
esac
