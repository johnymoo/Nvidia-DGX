set -eu

target="${1:?release name required}"
case "$target" in
    ./releases/*) ;;
    *) exit 64 ;;
esac
case "$target" in
    *".."*) exit 64 ;;
esac

test -d "$target"
test -f "$target/.release-ok"
previous="$(readlink "./runtime/current")"
case "$previous" in
    ./releases/*) ;;
    *) exit 65 ;;
esac

test ! -e "./runtime/current.next"
ln -s "$target" "./runtime/current.next"
mv -f "./runtime/current.next" "./runtime/current"

if ! ./bin/verify-release --release "$target"; then
    ln -s "$previous" "./runtime/current.restore"
    mv -f "./runtime/current.restore" "./runtime/current"
    printf '{"status":"verification_failed"}\n' > "./runtime/rollback-audit.json.tmp"
    mv -f "./runtime/rollback-audit.json.tmp" "./runtime/rollback-audit.json"
    exit 1
fi

printf '{"status":"rolled_back"}\n' > "./runtime/rollback-audit.json.tmp"
mv -f "./runtime/rollback-audit.json.tmp" "./runtime/rollback-audit.json"
