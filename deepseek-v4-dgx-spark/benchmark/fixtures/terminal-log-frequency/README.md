# Log frequency

Implement `solve.sh`. Run `./solve.sh input` to read every regular `app.log*`
file below the supplied input directory and write `report.json` in the current
directory. Process only lines containing `ERROR `; the signature is the text
after that marker. Normalize `user_id=...`, `request_id=...`, `trace_id=...`,
and `latency_ms=<digits>` to `key=?`. Emit `{"errors":[{"signature":string,"count":integer}]}`,
ordered by descending count and then bytewise signature. Use shell and standard
Unix utilities only; do not use Python, Node, network access, or `eval`.
