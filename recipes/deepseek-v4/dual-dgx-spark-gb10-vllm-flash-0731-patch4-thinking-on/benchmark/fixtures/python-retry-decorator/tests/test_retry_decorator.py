import unittest

from retry_decorator import retry


class RetryDecoratorTests(unittest.TestCase):
    def test_retries_a_sync_function(self):
        calls = 0

        @retry(attempts=3)
        def operation():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ValueError("not yet")
            return "ok"

        self.assertEqual(operation(), "ok")
        self.assertEqual(calls, 3)


if __name__ == "__main__":
    unittest.main()
