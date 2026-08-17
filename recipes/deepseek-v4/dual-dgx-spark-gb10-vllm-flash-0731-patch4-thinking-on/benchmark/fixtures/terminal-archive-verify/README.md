# Archive verification

Implement `solve.sh`. Run `./solve.sh input` to verify `bundle.tar` against
`manifest.tsv` (`sha256<TAB>relative-path`), selectively extract verified
regular members to `extracted/`, and write `verification.json` with `verified`
and `rejected` arrays of `{path,reason}` objects. Paths must be relative,
nonempty, contain no `.`/`..` components, and contain no component starting
with `-`. Never use archive member names as output paths until they pass that
check. Reject malformed manifest rows, checksum mismatches, traversal members,
and unsupported members; do not use Python, Node, network access, or `eval`.
