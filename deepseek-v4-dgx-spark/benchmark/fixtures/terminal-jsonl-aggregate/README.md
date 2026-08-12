# JSONL aggregate

Implement `solve.sh`. Run `./solve.sh input` to validate `requests.jsonl` and
write `aggregate.json`. Every input line is one JSON object with exactly the
non-negative integer fields `status` (100 through 599) and `latency_ms`, in
either key order; reject malformed rows, duplicate/extra keys, and invalid
numbers without leaving a stale result. Emit total rows, `1xx` through `5xx`
status buckets, `lt_100`, `100_499`, and `500_plus` latency buckets, and the
latency sum. Use shell and standard Unix utilities only.
