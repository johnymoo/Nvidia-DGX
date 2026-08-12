#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR"}
for file in ps.tsv sockets.tsv services.tsv; do
  [[ -f $root/$file ]] || { printf '%s\n' "missing $file" >&2; exit 2; }
done
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-process.XXXXXX")
trap 'rm -f "$tmp" "$tmp.sockets"' EXIT
rm -f process-report.tsv
sed '1d' "$root/sockets.tsv" | LC_ALL=C sort -t $'\t' -k1,1n -k2,2 -k3,3 -k4,4 > "$tmp.sockets"

if ! awk -F '\t' '
function invalid(message) { print message > "/dev/stderr"; bad=1; exit 2 }
FILENAME == ARGV[1] {
  if (FNR == 1) { if ($1 != "service" || $2 != "pid" || $3 != "state") invalid("bad services header"); next }
  if (NF != 3 || $1 == "" || $2 !~ /^[1-9][0-9]*$/ || $3 !~ /^[A-Za-z0-9_-]+$/ || ($2 in service)) invalid("bad service row")
  service[$2]=$1; state[$2]=$3; next
}
FILENAME == ARGV[2] {
  if (NF != 4 || $1 !~ /^[1-9][0-9]*$/ || $2 !~ /^[A-Za-z0-9_-]+$/ || $3 == "" || $4 == "") invalid("bad socket row")
  socket[$1]=(socket[$1] == "" ? "" : socket[$1] ",") $2 " " $3 "->" $4; next
}
FILENAME == ARGV[3] {
  if (FNR == 1) { if ($1 != "pid" || $2 != "ppid" || $3 != "command") invalid("bad ps header"); next }
  if (NF != 3 || $1 !~ /^[1-9][0-9]*$/ || $2 !~ /^[0-9]+$/ || $3 == "" || ($1 in process)) invalid("bad process row")
  process[$1]=1; ppid[$1]=$2; command[$1]=$3; next
}
END {
  if (bad) exit 2
  for (pid in service) if (!(pid in process)) { print "orphan service" > "/dev/stderr"; exit 2 }
  for (pid in socket) if (!(pid in process)) { print "orphan socket" > "/dev/stderr"; exit 2 }
  for (pid in process) printf "%s\t%s\t%s\t%s\t%s\t%s\n", pid, (pid in service ? service[pid] : "-"), (pid in state ? state[pid] : "-"), ppid[pid], command[pid], (pid in socket ? socket[pid] : "-")
}
' "$root/services.tsv" "$tmp.sockets" "$root/ps.tsv" > "$tmp"; then
  exit 2
fi
{
  printf 'pid\tservice\tstate\tppid\tcommand\tsockets\n'
  LC_ALL=C sort -t $'\t' -k1,1n "$tmp"
} > process-report.tsv
