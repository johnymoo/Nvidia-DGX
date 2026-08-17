# CSV pipeline

Implement `solve.sh`. Run `./solve.sh input` to parse `input/records.csv` and
write `summary.csv`. The header is exactly `account,team,amount_cents,status`.
CSV fields may be quoted and quoted quotes are doubled. Select rows whose
status is `approved`, sum their non-negative integer `amount_cents` values by
team, and emit `team,total_cents,rows` in bytewise team order using valid CSV
encoding. Reject malformed CSV, wrong headers, or invalid row values without
leaving a stale summary. Use shell and standard Unix utilities only.
