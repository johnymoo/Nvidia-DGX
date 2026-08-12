#!/usr/bin/env python3

import importlib
import sys
import unittest
from pathlib import Path

from graderlib import emit_setup_error, run_suite, suite_for


def main():
    try:
        workspace = Path(sys.argv[1]).resolve()
        sys.path.insert(0, str(workspace))
        module = importlib.import_module("miniconfig")
    except Exception as exc:
        return emit_setup_error(exc)

    class HiddenTests(unittest.TestCase):
        def test_escaped_dot_and_nested_value(self):
            data = {"api.v1": {"models": ["pro", "flash"]}}
            self.assertEqual(module.get_path(data, r"api\.v1.models.1"), "flash")

        def test_escaped_backslash(self):
            self.assertEqual(module.get_path({"a\\b": 7}, r"a\\b"), 7)

        def test_missing_key_default(self):
            self.assertIsNone(module.get_path({"a": {}}, "a.b", default=None))

        def test_list_range_default(self):
            self.assertEqual(module.get_path({"a": [1]}, "a.4", default=9), 9)

        def test_bad_list_index_is_type_error_even_with_default(self):
            with self.assertRaises(TypeError):
                module.get_path({"a": [1]}, "a.-1", default=9)
            with self.assertRaises(TypeError):
                module.get_path({"a": [1]}, "a.first", default=9)

        def test_scalar_traversal_is_type_error_even_with_default(self):
            with self.assertRaises(TypeError):
                module.get_path({"a": 1}, "a.b", default=9)

        def test_malformed_paths(self):
            for path in ("", ".a", "a.", "a..b", "a\\"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    module.get_path({}, path)

        def test_missing_without_default_keeps_native_errors(self):
            with self.assertRaises(KeyError):
                module.get_path({}, "missing")
            with self.assertRaises(IndexError):
                module.get_path({"a": []}, "a.0")

    return run_suite(suite_for(HiddenTests))


if __name__ == "__main__":
    raise SystemExit(main())
