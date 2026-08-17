from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tools.lab import main


FIXTURE = Path(__file__).parent / "fixtures" / "catalog-repo"


class LabCliTests(unittest.TestCase):
    def test_list_and_best_are_hostless(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--root", str(FIXTURE), "list"]), 0)
            self.assertEqual(main(["--root", str(FIXTURE), "best"]), 0)
        self.assertIn("model.verified", output.getvalue())
        self.assertIn("run-b", output.getvalue())

    def test_dispatch_dry_run_does_not_execute_recipe(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["--root", str(FIXTURE), "run", "model.verified", "status", "--dry-run"])
        self.assertEqual(status, 0)
        self.assertIn("status.sh", output.getvalue())


if __name__ == "__main__":
    unittest.main()
