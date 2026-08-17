#!/bin/sh
set -eu
./solve.sh input
test -f extracted/docs/readme.txt
grep -F 'docs/readme.txt' verification.json >/dev/null
