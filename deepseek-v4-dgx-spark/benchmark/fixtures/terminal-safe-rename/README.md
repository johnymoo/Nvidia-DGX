# Safe rename

Implement `solve.sh`. Run `./solve.sh input` to produce `rename-plan.json`
and `rollback.tsv` for regular files below `input/media`; run
`./solve.sh input --apply` to apply it. Normalize each ASCII basename to
lowercase hyphen-separated words, preserve a lowercased final extension, and
resolve collisions with `-2`, `-3`, and so on. Plans contain only changes as
`{"operations":[{"from":string,"to":string}]}`. `rollback.tsv` is
destination then original path, tab-separated. Applying must never overwrite a
file, must remain within `media`, and a second run after applying must have an
empty plan. Use shell and standard Unix utilities only.
