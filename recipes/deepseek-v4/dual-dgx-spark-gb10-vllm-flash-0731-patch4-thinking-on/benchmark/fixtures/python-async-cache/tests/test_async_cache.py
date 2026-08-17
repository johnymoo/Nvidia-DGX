import unittest

from async_cache import AsyncTTLCache


class AsyncTTLCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_a_loaded_value(self):
        cache = AsyncTTLCache(5)
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            return "value"

        self.assertEqual(await cache.get_or_load("key", load), "value")
        self.assertEqual(await cache.get_or_load("key", load), "value")
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
