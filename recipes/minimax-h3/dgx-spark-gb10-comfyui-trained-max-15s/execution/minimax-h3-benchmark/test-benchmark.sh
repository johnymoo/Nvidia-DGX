#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
python3 -m py_compile "$SCRIPT_DIR/benchmark.py"
jq -e '(.profiles | length) == 1 and .profiles[0].frames == 362 and (.cases | length) == 9' "$SCRIPT_DIR/cases.json" >/dev/null
mkdir -p "$tmp/source" "$tmp/site"
printf 'fake-video' > "$tmp/source/a.mp4"
printf 'fake-image' > "$tmp/source/a.png"
jq -n --arg video "$tmp/source/a.mp4" --arg image "$tmp/source/a.png" '{
 schema_version:1,run_id:"fixture",status:"passed",completed_at:"2026-08-13T00:00:00Z",
 selected_profile:{id:"minimum",width:320,height:192,frames:5,steps:1},
 deployment:{gitee_revision:"g",comfyui_revision:"c",subject_sha256:"s",runtime_before:{}},
 summary:{successful:1,total:1,sequential_success:false},
 reproducibility:{bitstream_equal:true,decoded_frames_equal:true},fatal_scans:{comfyui:{status:"passed"},kernel:{status:"passed"}},
 cases:[{id:"fixture",title:"Fixture",category:"Test",prompt:"A fixture",seed:1,status:"success",
 timing:{bounded_wall_seconds:1.2},profile:{id:"minimum"},
 video:{source_path:$video,bytes:10,sha256:"v",decoded_rgb_sequence_sha256:"p",ffprobe:{streams:[{codec_type:"video",width:320,height:192}],format:{duration:"1.0"}}},
 image:{source_path:$image,bytes:10,sha256:"i",decoded_rgb_sha256:"q"}}]
}' > "$tmp/report.json"
python3 "$SCRIPT_DIR/benchmark.py" render --input "$tmp/report.json" --site "$tmp/site" >/dev/null
test -s "$tmp/site/index.html"
test -s "$tmp/site/evidence.html"
test -s "$tmp/site/benchmark.json"
test ! -L "$tmp/site/assets/fixture.mp4"
grep -q 'MiniMax H3 on NVIDIA GB10' "$tmp/site/index.html"
grep -q 'Benchmark evidence' "$tmp/site/evidence.html"
echo passed
