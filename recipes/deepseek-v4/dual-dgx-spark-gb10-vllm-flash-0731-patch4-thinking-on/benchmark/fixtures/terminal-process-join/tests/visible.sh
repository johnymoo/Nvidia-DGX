#!/bin/sh
set -eu
./solve.sh input
cmp process-report.tsv input/expected.tsv
