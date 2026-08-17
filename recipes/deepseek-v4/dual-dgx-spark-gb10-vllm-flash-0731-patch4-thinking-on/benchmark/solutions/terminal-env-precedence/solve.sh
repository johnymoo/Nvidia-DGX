#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR"}
[[ -f $root/defaults.env && -f $root/.env ]] || { printf '%s\n' "environment files are missing" >&2; exit 2; }
host= port= debug= label=
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-env.XXXXXX")
trap 'rm -f "$tmp" "$tmp.seen"' EXIT

trim() { sed 's/^[[:space:]]*//; s/[[:space:]]*$//' <<< "$1"; }
set_value() {
  case $1 in
    APP_HOST) host=$2 ;;
    APP_PORT) port=$2 ;;
    APP_DEBUG) debug=$2 ;;
    APP_LABEL) label=$2 ;;
    *) return 2 ;;
  esac
}
load_file() {
  local file=$1 line key value seen=$tmp.seen
  : > "$seen"
  while IFS= read -r line || [[ -n $line ]]; do
    line=$(trim "$line")
    [[ -z $line || $line == \#* ]] && continue
    [[ $line == *=* ]] || { printf '%s\n' "malformed environment line" >&2; return 2; }
    key=$(trim "${line%%=*}")
    value=$(trim "${line#*=}")
    case $key in APP_HOST|APP_PORT|APP_DEBUG|APP_LABEL) ;; *) printf '%s\n' "invalid environment key" >&2; return 2 ;; esac
    grep -Fqx -- "$key" "$seen" && { printf '%s\n' "duplicate environment key" >&2; return 2; }
    printf '%s\n' "$key" >> "$seen"
    set_value "$key" "$value"
  done < "$file"
}
load_file "$root/defaults.env"
load_file "$root/.env"
[[ ${APP_HOST+x} ]] && host=$APP_HOST
[[ ${APP_PORT+x} ]] && port=$APP_PORT
[[ ${APP_DEBUG+x} ]] && debug=$APP_DEBUG
[[ ${APP_LABEL+x} ]] && label=$APP_LABEL
json_escape() { awk -v value="$1" 'BEGIN { gsub(/\\/, "\\\\", value); gsub(/"/, "\\\"", value); gsub(/\t/, "\\t", value); gsub(/\r/, "\\r", value); printf "%s", value }'; }
printf '{"APP_HOST":"%s","APP_PORT":"%s","APP_DEBUG":"%s","APP_LABEL":"%s"}\n' \
  "$(json_escape "$host")" "$(json_escape "$port")" "$(json_escape "$debug")" "$(json_escape "$label")" > effective-env.json
