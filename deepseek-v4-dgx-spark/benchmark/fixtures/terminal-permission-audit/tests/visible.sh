#!/bin/sh
set -eu
./solve.sh input
grep -F 'run.sh' permission-report.tsv >/dev/null
grep -F 'fixed' permission-report.tsv >/dev/null
./solve.sh input
! grep -F 'fixed' permission-report.tsv >/dev/null
