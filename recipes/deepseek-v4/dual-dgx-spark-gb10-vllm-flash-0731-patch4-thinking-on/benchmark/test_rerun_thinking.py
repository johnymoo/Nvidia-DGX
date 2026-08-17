#!/usr/bin/env python3

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("rerun_thinking.py")
spec = importlib.util.spec_from_file_location("private_ds_thinking_rerun", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

pilot = module.load_pilot()
manifest = pilot.load_manifest()
assert [task["task_id"] for task in module.selected_tasks(manifest)] == [task_id for task_id, _ in module.SELECTED]

with tempfile.TemporaryDirectory() as directory:
    stream = Path(directory) / "stream.jsonl"
    stream.write_text("\n".join((
        json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "x"}]}}),
        json.dumps({"type": "system", "subtype": "thinking_tokens"}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}),
    )), encoding="utf-8")
    assert module.count_thinking(stream) == {"blocks": 1, "token_events": 1}

    output = Path(directory) / "index.html"
    payload = {
        "aggregates": {treatment: 2.0 for treatment in module.TREATMENTS},
        "tasks": [{
            "task_id": "t",
            "title": "Task",
            "selection_category": "SWE",
            "judge_preference": "offline_ds_thinking",
            "judge_rationale": "Thinking answer is more complete.",
            "scores": {treatment: {"quality": 2.0, "deterministic_tier": 2.0, "judge_layer": 2.0} for treatment in module.TREATMENTS},
            "answers": {treatment: "answer" for treatment in module.TREATMENTS},
            "hidden": {treatment: {"passed": 1, "total": 1} for treatment in module.TREATMENTS},
            "thinking": {"blocks": 1, "token_events": 1},
        }],
    }
    module.render_html(payload, output)
    rendered = output.read_text(encoding="utf-8")
    assert "Private DS Thinking" in rendered and "Thinking blocks: 1" in rendered

print("private_ds_thinking_rerun_tests=passed")
