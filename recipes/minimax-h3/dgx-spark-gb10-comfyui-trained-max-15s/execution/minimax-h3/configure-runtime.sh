#!/usr/bin/env bash

set -euo pipefail

root=""

usage() {
  cat <<'EOF'
Usage: configure-runtime.sh --root PATH

Configures pinned MiniMax H3 custom nodes, model paths, and workflows inside
an existing deployment root. Source repositories and the Python environment
must already be present.
EOF
}

while (( $# )); do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done

[[ -n "$root" ]] || { printf '%s\n' '--root is required' >&2; exit 1; }

comfy="$root/comfy/ComfyUI"
keys="$root/sources/keys-heretic"
custom="$comfy/custom_nodes"
artifacts="$root/artifacts/deployment"
run_id="$(date -u +%Y%m%dT%H%M%SZ)"

[[ "$(git -C "$comfy" rev-parse HEAD)" == 0764232429b8cfb10b79b6f186c8cb23e0b22897 ]]
[[ "$(git -C "$keys" rev-parse HEAD)" == 6f21656d9182c6a3fae0c671253f2523084b9204 ]]
mkdir -p "$custom" "$artifacts" "$root/workflows"

install_tree() {
  local source="$1" destination="$2" name="$3" staged quarantine
  staged="${destination}.staged.$$"
  rm -rf "$staged"
  cp -a "$source" "$staged"
  if [[ -e "$destination" ]]; then
    quarantine="$root/artifacts/incomplete/$run_id/runtime/$name"
    mkdir -p "$(dirname "$quarantine")"
    mv "$destination" "$quarantine"
  fi
  mv "$staged" "$destination"
}

install_tree \
  "$keys/vendor/ComfyUI_sol-attn_Blackwell" \
  "$custom/ComfyUI_sol-attn_Blackwell" \
  ComfyUI_sol-attn_Blackwell

ports_staged="$custom/h3_sol_engine_ports.staged.$$"
rm -rf "$ports_staged"
mkdir -p "$ports_staged"
cp "$keys/nodes/h3_fbc_node.py" "$keys/nodes/h3_vae_batch.py" "$ports_staged/"
cat > "$ports_staged/__init__.py" <<'PYEOF'
from .h3_fbc_node import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

try:
    from .h3_vae_batch import install as _install_vae_batch
    _install_vae_batch()
except Exception as exc:
    import logging
    logging.getLogger(__name__).warning("H3 batched VAE not installed: %s", exc)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
PYEOF
if [[ -e "$custom/h3_sol_engine_ports" ]]; then
  quarantine="$root/artifacts/incomplete/$run_id/runtime/h3_sol_engine_ports"
  mkdir -p "$(dirname "$quarantine")"
  mv "$custom/h3_sol_engine_ports" "$quarantine"
fi
mv "$ports_staged" "$custom/h3_sol_engine_ports"

find "$keys/workflows" -maxdepth 1 -type f -name '*.json' -print0 |
  xargs -0 -r cp -t "$root/workflows"
[[ "$(find "$root/workflows" -maxdepth 1 -type f -name '*.json' | wc -l)" == 12 ]]

cat > "$root/extra_model_paths.yaml" <<EOF
minimax_h3:
  base_path: $root/models
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
  upscale_models: upscale_models
EOF

{
  printf 'configured_at=%s\n' "$(date -u +%FT%TZ)"
  printf 'comfyui_revision=%s\n' "$(git -C "$comfy" rev-parse HEAD)"
  printf 'keys_revision=%s\n' "$(git -C "$keys" rev-parse HEAD)"
  printf 'workflow_count=12\n'
  printf 'extra_model_paths_sha256=%s\n' "$(sha256sum "$root/extra_model_paths.yaml" | awk '{print $1}')"
  printf 'vendor_tree_sha256=%s\n' "$(find "$custom/ComfyUI_sol-attn_Blackwell" -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"
  printf 'ports_tree_sha256=%s\n' "$(find "$custom/h3_sol_engine_ports" -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"
} > "$artifacts/runtime-configuration.txt"

cat "$artifacts/runtime-configuration.txt"
