# Checksum audit

Implement `solve.sh`. Run `./solve.sh input` to compare `input/checksums.txt`
against regular files below `input/tree`. Each manifest line is
`sha256<two spaces>relative-path`. Write `audit.json` containing sorted
`matching`, `missing`, `changed`, and `unexpected` string arrays. Reject
malformed hashes, duplicates, or unsafe manifest paths (`/`, `.`, `..`, or a
component starting with `-`) without evaluating any input. Symlinks are not
followed. Use shell and standard Unix utilities only.
