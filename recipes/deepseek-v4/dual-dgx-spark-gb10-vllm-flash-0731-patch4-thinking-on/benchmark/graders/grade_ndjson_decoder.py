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
        module = importlib.import_module("ndjson_stream")
    except Exception as exc:
        return emit_setup_error(exc)

    class HiddenTests(unittest.TestCase):
        def test_partial_and_multiple_records(self):
            decoder = module.NDJSONDecoder()
            self.assertEqual(decoder.feed('{"a":'), [])
            self.assertEqual(decoder.feed('1}\n{"b":2}\n'), [{"a": 1}, {"b": 2}])

        def test_split_crlf_and_following_record(self):
            decoder = module.NDJSONDecoder()
            self.assertEqual(decoder.feed('{"a":1}\r'), [])
            self.assertEqual(decoder.feed('\n{"b":2}\r\n'), [{"a": 1}, {"b": 2}])

        def test_blank_lines_advance_physical_line(self):
            decoder = module.NDJSONDecoder()
            decoder.feed("\n  \r\n")
            with self.assertRaises(module.NDJSONError) as captured:
                decoder.feed("broken\n")
            self.assertEqual(captured.exception.line_number, 3)

        def test_error_preserves_decoder_message(self):
            decoder = module.NDJSONDecoder()
            with self.assertRaises(module.NDJSONError) as captured:
                decoder.feed("nope\n")
            self.assertEqual(captured.exception.message, "Expecting value")
            self.assertIn("line 1", str(captured.exception))

        def test_finalize_unterminated_record_once(self):
            decoder = module.NDJSONDecoder()
            decoder.feed('{"tail":true}')
            self.assertEqual(decoder.finalize(), [{"tail": True}])
            self.assertEqual(decoder.finalize(), [])

        def test_finalize_whitespace_once(self):
            decoder = module.NDJSONDecoder()
            decoder.feed("   ")
            self.assertEqual(decoder.finalize(), [])
            self.assertEqual(decoder.finalize(), [])

        def test_feed_after_finalize_is_rejected(self):
            decoder = module.NDJSONDecoder()
            decoder.finalize()
            with self.assertRaises(RuntimeError):
                decoder.feed("{}\n")

        def test_non_string_chunk_is_rejected(self):
            decoder = module.NDJSONDecoder()
            with self.assertRaises(TypeError):
                decoder.feed(b"{}\n")

    return run_suite(suite_for(HiddenTests))


if __name__ == "__main__":
    raise SystemExit(main())
