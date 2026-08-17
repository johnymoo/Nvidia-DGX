from pathlib import Path
import json

assert Path("fix.conf").is_file()
assert isinstance(json.loads(Path("diagnosis.json").read_text(encoding="utf-8")), dict)
