from pathlib import Path
import json

assert isinstance(json.loads(Path("deployment.json").read_text(encoding="utf-8")), dict)
assert Path("rollback.md").is_file()
