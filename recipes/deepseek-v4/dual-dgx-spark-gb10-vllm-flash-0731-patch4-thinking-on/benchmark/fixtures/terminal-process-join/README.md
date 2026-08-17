# Process join

Implement `solve.sh`. Run `./solve.sh input` to join `ps.tsv`, `sockets.tsv`,
and `services.tsv` into `process-report.tsv`. Each input has the supplied
header; reject malformed rows, duplicate PIDs, and service/socket rows with no
matching process. Emit `pid,service,state,ppid,command,sockets` as tab-separated
columns, sorted numerically by PID. Missing service metadata or sockets are
`-`; sockets are `proto local->remote` strings sorted and joined with commas.
Use shell and standard Unix utilities only.
