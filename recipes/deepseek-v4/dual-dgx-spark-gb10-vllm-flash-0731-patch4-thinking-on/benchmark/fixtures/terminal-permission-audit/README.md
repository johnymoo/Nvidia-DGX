# Permission audit

Implement `solve.sh`. Run `./solve.sh input` to audit and remediate
`input/tree`: directories and `*.sh` regular files must be mode `0750`; other
regular files must be `0640`. Do not follow or change symlinks. Write
`permission-report.tsv` with header `path,kind,before,after,action` as
tab-separated columns, sorted by path; paths are relative to `tree`, whose root
is `.`. `action` is `fixed` or `ok`. A second run should show only `ok`.
Use shell and standard Unix utilities only.
