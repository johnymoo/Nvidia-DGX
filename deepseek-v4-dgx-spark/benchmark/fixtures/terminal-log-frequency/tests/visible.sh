#!/bin/sh
set -eu
./solve.sh input
grep -F 'payment failed user_id=? request_id=? latency_ms=?' report.json >/dev/null
grep -F '"count":2' report.json >/dev/null
