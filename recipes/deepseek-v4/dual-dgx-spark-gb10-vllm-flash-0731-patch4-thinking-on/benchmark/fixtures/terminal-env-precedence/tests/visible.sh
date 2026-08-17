#!/bin/sh
set -eu
APP_PORT=9000 ./solve.sh input
grep -F '"APP_PORT":"9000"' effective-env.json >/dev/null
grep -F '"APP_LABEL":"flash service"' effective-env.json >/dev/null
