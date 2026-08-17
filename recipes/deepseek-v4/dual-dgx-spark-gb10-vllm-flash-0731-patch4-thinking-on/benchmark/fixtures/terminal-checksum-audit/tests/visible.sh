#!/bin/sh
set -eu
./solve.sh input
grep -F '"keep.txt"' audit.json >/dev/null
grep -F '"missing.txt"' audit.json >/dev/null
