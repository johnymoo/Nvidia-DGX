# Environment precedence

Implement `solve.sh`. Run `./solve.sh input` to read `defaults.env` then
`.env`, then process overrides for `APP_HOST`, `APP_PORT`, `APP_DEBUG`, and
`APP_LABEL`; write those four string values to `effective-env.json` in that
key order. Later sources win, including an explicitly empty process value.
Each file permits blank lines, comments, and one `KEY=VALUE` per line, with
surrounding whitespace trimmed. Only the four allowed keys are valid; reject
duplicates in one file and malformed lines. Never source or evaluate input.
Use shell and standard Unix utilities only.
