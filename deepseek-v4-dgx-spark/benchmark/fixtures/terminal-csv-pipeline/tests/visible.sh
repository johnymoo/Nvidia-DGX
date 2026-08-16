#!/bin/sh
set -eu
./solve.sh input
cmp summary.csv input/expected.csv
