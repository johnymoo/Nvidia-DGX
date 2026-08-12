import unittest

from toposort import stable_toposort


class ToposortTests(unittest.TestCase):
    def test_dependencies_precede_dependents(self):
        graph = {"build": ("compile",), "compile": ("lint",), "lint": ()}
        self.assertEqual(stable_toposort(graph), ["lint", "compile", "build"])


if __name__ == "__main__":
    unittest.main()
