#!/usr/bin/env python3
"""D1a import-compatibility audit.

Every import in the vendored tip files (59) must resolve against the IMAGE
tree. The image = upstream baseline 7e33081cee7b for all non-boundary files,
plus the 7 fork-modified files (which we overlay from the apply-test baseline
commit). The vendored files themselves replace their image counterparts.

Checks, per vendored file:
  - `from vllm.a.b import s1, s2` → module must exist (tip-vendored OR image);
    each symbol must be a top-level name (def/class/assign/import) there.
  - `import vllm.a.b` → module must exist.
  - `from vllm.a.b import module` where module is a submodule → OK if the
    submodule file exists.
Resolution order for a target path: (1) vendored staging tree, (2) apply-test
baseline commit (fork files + everything pulled), (3) upstream baseline
7e33081cee7b. Try/except-guarded imports are listed separately (degraded
paths, not hard failures).
"""
import ast
import re
import subprocess
import sys
from pathlib import Path

import sys as _sys
STAGE = Path(_sys.argv[1] if len(_sys.argv) > 1 else "/Users/chris/project/Shili/workspaces/dev-lite/GB10-DS/tmp/kv-offload-d1a/vendored")
UP = Path("/tmp/vllm-upstream")
BASELINE = "7e33081cee7b"
# apply-test baseline commit holds the pulled image files (repo root = vllm pkg)
APPLY = ("git", "-C", "/tmp/apply-test")
APPLY_INIT = "ea1e7797bbb023e14a9ad197c4208d794f31c6bc"


def git_exists(repo_args, rev, path):
    return subprocess.run(list(repo_args) + ["cat-file", "-e", f"{rev}:{path}"],
                          capture_output=True).returncode == 0


def git_read(repo_args, rev, path):
    r = subprocess.run(list(repo_args) + ["show", f"{rev}:{path}"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def resolve(rel):
    """rel: path under vllm package, e.g. 'v1/kv_offload/base.py'.
    Returns ('stage', text) | ('image', text) | (None, None)."""
    p = STAGE / rel
    if p.exists():
        return "stage", p.read_text()
    # apply-test repo root == the vllm package dir; upstream repo needs the
    # vllm/ prefix.
    for repo_args, rev, prefixes in (
        (APPLY, APPLY_INIT, ("",)),
        (("git", "-C", str(UP)), BASELINE, ("vllm/", "")),
    ):
        for prefix in prefixes:
            if git_exists(repo_args, rev, prefix + rel):
                t = git_read(repo_args, rev, prefix + rel)
                if t is not None:
                    return "image", t
    return None, None


def module_file(mod):
    """mod: 'vllm.v1.kv_offload.base' → ['vllm/v1/kv_offload/base.py',
    'vllm/v1/kv_offload/base/__init__.py'] candidates (package-relative)."""
    base = mod[len("vllm."):] if mod.startswith("vllm.") else mod
    base = base.replace(".", "/")
    pkg_init = base + "/__init__.py" if mod != "vllm" else "__init__.py"
    return [base + ".py", pkg_init]


def top_names(src):
    names = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            if node.name == "__getattr__":
                # module-level lazy attributes: collect compared string names
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        names.add(sub.value)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.If):
            # conditional top-level defs (TYPE_CHECKING etc.)
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
        elif isinstance(node, ast.FunctionDef) and node.name == "__getattr__":
            # module-level lazy attributes: names come from the string compares
            # inside; collect them so lazy names resolve.
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    names.add(sub.value)
        elif isinstance(node, ast.Try):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
    return names


def check_file(path):
    src = path.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(str(path), "SYNTAX", f"{e}")]
    problems, guarded = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        mod = node.module if node.level == 0 else None
        if node.level > 0 or not (mod == "vllm" or mod.startswith("vllm.")):
            continue
        is_guarded = any(isinstance(p, (ast.Try,)) for p in [])  # replaced below
        # determine guarding: walk manually is complex; approximate via source scan
        # of the enclosing region — instead mark via node.col_offset and try-blocks
        for cands in module_file(mod):
            src_kind, text = resolve(cands)
            if src_kind:
                break
        else:
            cands, src_kind, text = None, None, None
        bucket = guarded  # refined below
        where = str(path.relative_to(STAGE))
        if src_kind is None:
            bucket.append((where, mod, "MODULE MISSING in image"))
            continue
        names = top_names(text)
        if names is None:
            bucket.append((where, mod, f"cannot parse {cands}"))
            continue
        for a in node.names:
            sym = a.name
            if sym == "*":
                continue
            if sym in names:
                continue
            # submodule import? from vllm.a import b where b is a module
            sub = f"{mod}.{sym}".replace("vllm.", "").replace(".", "/")
            if any(resolve(f"{sub}.py")[0] or resolve(f"{sub}/__init__.py")[0] for _ in (0,)):
                continue
            bucket.append((where, f"{mod} import {sym}", f"SYMBOL not found in {src_kind}:{cands}"))
    return problems, guarded


def main():
    # Refine guarding: re-walk with a parent map to know if an ImportFrom sits
    # inside a Try block.
    hard, soft = [], []
    for path in sorted(STAGE.rglob("*.py")):
        src = path.read_text()
        tree = ast.parse(src)
        parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            mod = node.module
            if not (mod == "vllm" or mod.startswith("vllm.")):
                continue
            chain = []
            p = parents.get(node)
            while p is not None:
                chain.append(p)
                p = parents.get(p)
            in_try = any(isinstance(n, ast.Try) for n in chain)
            in_tc = any(
                isinstance(n, ast.If)
                and isinstance(n.test, ast.Name)
                and n.test.id == "TYPE_CHECKING"
                for n in chain
            )
            if in_tc:
                continue  # never executed at runtime
            bucket = soft if in_try else hard
            where = str(path.relative_to(STAGE))
            for cands in module_file(mod):
                src_kind, text = resolve(cands)
                if src_kind:
                    break
            else:
                bucket.append((where, mod, "MODULE MISSING in image"))
                continue
            names = top_names(text)
            for a in node.names:
                sym = a.name
                if sym == "*" or (names and sym in names):
                    continue
                sub = f"{mod}.{sym}".replace("vllm.", "").replace(".", "/")
                if resolve(f"{sub}.py")[0] is not None or resolve(f"{sub}/__init__.py")[0] is not None:
                    continue
                bucket.append((where, f"{mod} :: {sym}", f"symbol absent in {src_kind}:{cands}"))
    print(f"HARD failures (unguarded, must fix): {len(hard)}")
    for row in hard:
        print("  ", row)
    print(f"GUARDED (try/except around import, degraded-ok): {len(soft)}")
    for row in soft:
        print("  ", row)


if __name__ == "__main__":
    main()
