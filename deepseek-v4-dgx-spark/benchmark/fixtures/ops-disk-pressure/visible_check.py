from pathlib import Path
import json

assert isinstance(json.loads(Path("triage.json").read_text(encoding="utf-8")), dict)
assert Path("remediation.md").is_file()
