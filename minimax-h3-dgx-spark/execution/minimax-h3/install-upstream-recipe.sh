#!/usr/bin/env bash

set -euo pipefail

root="${H3_ROOT:-$HOME/minimax-h3}"
revision="${H3_GITEE_REVISION:-9f9eca9589d4b4c0a01a8081c8c4add279e18868}"
repository="${H3_GITEE_REPOSITORY:-https://gitee.com/alexlu0912_admin/dgxspark_comfyui_minimax_h3.git}"

while (( $# )); do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    --revision) revision="$2"; shift 2 ;;
    --repository) repository="$2"; shift 2 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done

command -v git >/dev/null
mkdir -p "$root/sources"
source_dir="$root/sources/gitee-recipe"
if [[ ! -d "$source_dir/.git" ]]; then
  git clone "$repository" "$source_dir"
fi
git -C "$source_dir" fetch origin "$revision"
git -C "$source_dir" checkout --detach "$revision"
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$revision" ]]

installer="$source_dir/deploy_from_scratch.sh"
[[ -f "$installer" ]] || { printf 'pinned installer is missing\n' >&2; exit 1; }
expected_installer_sha="83405c98203d8f7d7f5e57be58a2810665b06d3f6e9ea9f174a058a6bedec37a"
[[ "$(sha256sum "$installer" | awk '{print $1}')" == "$expected_installer_sha" ]] || {
  printf 'pinned installer content hash mismatch\n' >&2
  exit 1
}

safe_tmp="$(mktemp -d -p /var/tmp minimax-h3-install.XXXXXXXX)"
chmod 700 "$safe_tmp"
safe_installer="$safe_tmp/deploy_from_scratch.safe.sh"
python3 - "$installer" "$safe_installer" "$safe_tmp/keys-heretic" <<'PY'
import sys
from pathlib import Path

source, target, private_tmp = map(Path, sys.argv[1:])
text = source.read_text()
old_tmp = '    TMP="/tmp/keys-heretic-tmp"\n'
old_kill = '    pkill -f "main.py.*${COMFY_PORT}" 2>/dev/null || true\n    sleep 1\n'
if text.count(old_tmp) != 1 or text.count(old_kill) != 1:
    raise SystemExit("upstream installer safety patch anchors changed")
text = text.replace(old_tmp, f'    TMP="{private_tmp}"\n')
text = text.replace(old_kill, '    # Existing listeners are preserved; startup fails if the port is occupied.\n')
if 'pkill -f' in text or '/tmp/keys-heretic-tmp' in text:
    raise SystemExit("unsafe upstream installer behavior remains")
target.write_text(text)
target.chmod(0o700)
PY

printf 'About to run safety-patched pinned installer: %s\n' "$safe_installer"
printf 'Target root: %s\n' "$root"
printf 'The upstream installer may install OS/Python packages and start ComfyUI.\n'
INSTALL_DIR="$root" VENV_DIR="$root/venv" COMFY_PORT="${H3_PORT:-8188}" \
  RESERVE_VRAM="${H3_RESERVE_VRAM:-8}" bash "$safe_installer"

# The upstream recipe starts ComfyUI with a PID file. Stop only that exact
# process after validating its root, interpreter and port; later starts use the
# receipt-bound controls in this repository.
python3 - "$root" "${H3_PORT:-8188}" <<'PY'
import os
import signal
import sys
import time
from pathlib import Path

root = Path(sys.argv[1]).resolve()
port = sys.argv[2]
pid_file = root / "logs/comfyui.pid"
if not pid_file.is_file():
    raise SystemExit("upstream installer did not record its launched PID")
pid = int(pid_file.read_text().strip())
cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0").split(b"\0")
argv = [item.decode(errors="replace") for item in cmdline]
expected_python = str(root / "venv/bin/python")
expected_main = str(root / "comfy/ComfyUI/main.py")
if not argv or Path(argv[0]).resolve() != Path(expected_python).resolve():
    raise SystemExit("refusing to stop unexpected upstream interpreter")
cwd = Path(f"/proc/{pid}/cwd").resolve()
main_arg = next((item for item in argv[1:] if item.endswith("main.py")), None)
resolved_main = (cwd / main_arg).resolve() if main_arg and not Path(main_arg).is_absolute() else Path(main_arg or "").resolve()
if str(resolved_main) != expected_main or "--port" not in argv or argv[argv.index("--port") + 1] != port:
    raise SystemExit("refusing to stop unexpected upstream ComfyUI process")
os.kill(pid, signal.SIGTERM)
for _ in range(120):
    if not Path(f"/proc/{pid}").exists():
        break
    time.sleep(0.25)
else:
    raise SystemExit("upstream ComfyUI process did not stop")
PY

pin_repo() {
  local path="$1" url="$2" commit="$3"
  [[ -d "$path/.git" ]] || { printf 'missing source tree: %s\n' "$path" >&2; exit 1; }
  git -C "$path" remote set-url origin "$url"
  git -C "$path" fetch origin "$commit"
  git -C "$path" checkout --detach "$commit"
  [[ "$(git -C "$path" rev-parse HEAD)" == "$commit" ]]
}

comfy="$root/comfy/ComfyUI"
custom="$comfy/custom_nodes"
pin_repo "$comfy" https://github.com/comfyanonymous/ComfyUI.git \
  0764232429b8cfb10b79b6f186c8cb23e0b22897
pin_repo "$custom/ComfyUI-SolAttn_triton" https://github.com/kijai/ComfyUI-SolAttn_triton.git \
  842c4eaa7d91dbaef3fee3ccdbf36a39521e82fc
pin_repo "$custom/ComfyUI-KJNodes" https://github.com/kijai/ComfyUI-KJNodes.git \
  6ab7e8130e449ed2c0037589bcf84146ceb7fc9c
pin_repo "$custom/ComfyUI-Spectrum-MiniMax-H3" https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3.git \
  1a8930d662f4f66694d06275bff40c002e0d451d
pin_repo "$custom/ComfyUI-H3-Multishot" https://github.com/jlucasmcrell/ComfyUI-H3-Multishot.git \
  1e1b8321f3031da0426537f637c6e1e38ccd8aeb
pin_repo "$custom/ComfyUI-VideoHelperSuite" https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
  4ee72c065db22c9d96c2427954dc69e7b908444b

keys="$root/sources/keys-heretic"
if [[ ! -d "$keys/.git" ]]; then
  git clone https://github.com/drowzeys/keys-heretic-MiniMax-H3-sol-engine-more-speed-upgrades-upscaler-finish-Single-DGX-Spark.git "$keys"
fi
pin_repo "$keys" https://github.com/drowzeys/keys-heretic-MiniMax-H3-sol-engine-more-speed-upgrades-upscaler-finish-Single-DGX-Spark.git \
  6f21656d9182c6a3fae0c671253f2523084b9204

[[ -e "$root/models" ]] || ln -s "$comfy/models" "$root/models"
mkdir -p "$root/workflows"
cp "$source_dir"/workflows/*.json "$root/workflows/"

"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/configure-runtime.sh" --root "$root"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
installed_scripts="$root/execution/minimax-h3"
if [[ "$script_dir" != "$installed_scripts" ]]; then
  mkdir -p "$installed_scripts"
  cp -a "$script_dir/." "$installed_scripts/"
fi
printf 'Pinned upstream recipe normalized at %s\n' "$root"
