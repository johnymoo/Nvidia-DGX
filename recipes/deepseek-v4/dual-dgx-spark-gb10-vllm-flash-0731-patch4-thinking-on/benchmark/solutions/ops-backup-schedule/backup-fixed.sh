set -eu

TZ=UTC
export TZ

if ! mkdir "./runtime/backup.lock"; then
    exit 75
fi
trap 'rmdir "./runtime/backup.lock"' EXIT

stamp="$(./bin/utc-stamp)"
./bin/snapshot --output "./backups/ledger-${stamp}.tar"
./bin/prune-backups --directory ./backups --keep 7
