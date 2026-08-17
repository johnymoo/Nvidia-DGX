# NUL-safe inventory

Implement `solve.sh`. Run `./solve.sh input` to inventory regular files under
`input/tree` and write `inventory.json` in the current directory. Paths are
relative to `tree`, and the output is `{"files":[{"path":string,"bytes":integer}]}`
in bytewise path order. Inputs may contain spaces, tabs, and leading dashes;
do not split filenames on whitespace or use `eval`. Ignore directories and
symlinks. Use shell and standard Unix utilities only.
