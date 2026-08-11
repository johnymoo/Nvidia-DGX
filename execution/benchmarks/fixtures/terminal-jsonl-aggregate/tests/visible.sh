#!/bin/sh
set -eu
./solve.sh input
cmp aggregate.json input/expected.json
