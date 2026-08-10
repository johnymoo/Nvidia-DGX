#!/usr/bin/env bash
# Interactive bootstrap: deploy a root-owned wrapper and its narrowly scoped sudoers rule.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

readonly EXPECTED_HOST="spark-3345"
readonly EXPECTED_USER="admin"
readonly TARGET="/usr/local/sbin/gb10-ds4-worker-maintenance"
readonly SUDOERS="/etc/sudoers.d/gb10-ds4-worker-maintenance"

[ "$(/usr/bin/id -u)" -eq 0 ] || { echo "ERROR: run interactively as: sudo $0" >&2; exit 77; }
[ "$(/bin/hostname -s)" = "$EXPECTED_HOST" ] || { echo "ERROR: refusing host $(/bin/hostname -s)." >&2; exit 65; }
[ "${SUDO_USER:-}" = "$EXPECTED_USER" ] || { echo "ERROR: installer must be invoked by admin through sudo." >&2; exit 77; }
[ -t 0 ] && [ -w /dev/tty ] || { echo "ERROR: installer requires an interactive terminal." >&2; exit 77; }
admin_uid="$(/usr/bin/id -u "$EXPECTED_USER" 2>/dev/null)" || { echo "ERROR: admin is absent." >&2; exit 65; }
[ "${SUDO_UID:-}" = "$admin_uid" ] || { echo "ERROR: sudo identity does not match admin." >&2; exit 77; }

source_dir="$(cd "$(/usr/bin/dirname "$0")" && /bin/pwd -P)"
source="$source_dir/worker-maintenance.sh"
[ -f "$source" ] && [ ! -L "$source" ] || { echo "ERROR: missing regular wrapper source: $source" >&2; exit 66; }
for command in install mktemp mv visudo; do command -v "$command" >/dev/null || { echo "ERROR: missing $command" >&2; exit 69; }; done
/bin/bash -n "$source"

tmp_wrapper="$(/usr/bin/mktemp "${TARGET}.XXXXXX")"
tmp_sudoers="$(/usr/bin/mktemp "${SUDOERS}.XXXXXX")"
trap 'rm -f "$tmp_wrapper" "$tmp_sudoers"' EXIT
/usr/bin/install -o root -g root -m 0755 "$source" "$tmp_wrapper"

cat >"$tmp_sudoers" <<'EOF'
# Managed by install-worker-maintenance-sudoers.sh. Do not edit by hand.
Cmnd_Alias GB10_DS4_WORKER_MAINTENANCE = \
    /usr/local/sbin/gb10-ds4-worker-maintenance check, \
    /usr/local/sbin/gb10-ds4-worker-maintenance apply-basic, \
    /usr/local/sbin/gb10-ds4-worker-maintenance restart-docker, \
    /usr/local/sbin/gb10-ds4-worker-maintenance configure-fabric, \
    /usr/local/sbin/gb10-ds4-worker-maintenance remove-swap, \
    /usr/local/sbin/gb10-ds4-worker-maintenance apt-use-tuna
admin ALL=(root) NOSETENV: NOPASSWD: GB10_DS4_WORKER_MAINTENANCE
EOF
/usr/bin/chown root:root "$tmp_sudoers"
/usr/bin/chmod 0440 "$tmp_sudoers"
/usr/sbin/visudo -cf "$tmp_sudoers" >/dev/null

/usr/bin/install -d -o root -g root -m 0755 /usr/local/sbin /etc/sudoers.d
/usr/bin/mv -f "$tmp_wrapper" "$TARGET"
/usr/bin/chown root:root "$TARGET"
/usr/bin/chmod 0755 "$TARGET"
/usr/bin/mv -f "$tmp_sudoers" "$SUDOERS"
/usr/bin/chown root:root "$SUDOERS"
/usr/bin/chmod 0440 "$SUDOERS"
/usr/sbin/visudo -cf "$SUDOERS" >/dev/null
printf 'Installed %s and %s for %s (uid %s).\n' "$TARGET" "$SUDOERS" "$EXPECTED_USER" "$admin_uid"
