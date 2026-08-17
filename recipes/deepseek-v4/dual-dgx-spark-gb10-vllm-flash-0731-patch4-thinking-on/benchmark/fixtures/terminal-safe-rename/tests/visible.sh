#!/bin/sh
set -eu
./solve.sh input
grep -F 'summer-photo-2.jpg' rename-plan.json >/dev/null
./solve.sh input --apply
test -f input/media/summer-photo.jpg
test -f input/media/summer-photo-2.jpg
./solve.sh input
grep -F '"operations":[]' rename-plan.json >/dev/null
