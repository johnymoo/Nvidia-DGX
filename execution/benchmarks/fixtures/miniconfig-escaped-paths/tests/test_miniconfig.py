import unittest

from miniconfig import get_path


class GetPathTests(unittest.TestCase):
    def test_plain_dictionary_path(self):
        self.assertEqual(get_path({"service": {"port": 8890}}, "service.port"), 8890)

    def test_escaped_dot_in_key(self):
        self.assertEqual(get_path({"service.name": "flash"}, r"service\.name"), "flash")

    def test_list_index(self):
        self.assertEqual(get_path({"ranks": ["head", "worker"]}, "ranks.1"), "worker")

    def test_default_for_missing_key(self):
        self.assertEqual(get_path({}, "missing", default="fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
