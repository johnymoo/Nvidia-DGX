import unittest

from ndjson_stream import NDJSONDecoder, NDJSONError


class NDJSONDecoderTests(unittest.TestCase):
    def test_partial_record_is_retained(self):
        decoder = NDJSONDecoder()
        self.assertEqual(decoder.feed('{"rank":'), [])
        self.assertEqual(decoder.feed('2}\n'), [{"rank": 2}])

    def test_split_crlf(self):
        decoder = NDJSONDecoder()
        self.assertEqual(decoder.feed('{"ok":true}\r'), [])
        self.assertEqual(decoder.feed("\n"), [{"ok": True}])

    def test_finalize_once(self):
        decoder = NDJSONDecoder()
        decoder.feed('{"done":true}')
        self.assertEqual(decoder.finalize(), [{"done": True}])
        self.assertEqual(decoder.finalize(), [])

    def test_error_reports_physical_line(self):
        decoder = NDJSONDecoder()
        decoder.feed("\n")
        with self.assertRaises(NDJSONError) as captured:
            decoder.feed("not-json\n")
        self.assertEqual(captured.exception.line_number, 2)


if __name__ == "__main__":
    unittest.main()
