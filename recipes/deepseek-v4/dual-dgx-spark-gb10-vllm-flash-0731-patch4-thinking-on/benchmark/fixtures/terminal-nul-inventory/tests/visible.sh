#!/bin/sh
set -eu
./solve.sh input
grep -F '"-leading.txt"' inventory.json >/dev/null
grep -F '"nested/item.txt"' inventory.json >/dev/null
