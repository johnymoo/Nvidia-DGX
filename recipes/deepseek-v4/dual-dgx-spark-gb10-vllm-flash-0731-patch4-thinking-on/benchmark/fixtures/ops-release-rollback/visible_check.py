from pathlib import Path
import json

assert Path("rollback.sh").is_file()
assert isinstance(json.loads(Path("rollback-plan.json").read_text(encoding="utf-8")), dict)
