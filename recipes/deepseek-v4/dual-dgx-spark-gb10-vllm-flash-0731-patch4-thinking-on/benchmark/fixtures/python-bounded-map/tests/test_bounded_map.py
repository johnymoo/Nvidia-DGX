import asyncio
import unittest

from bounded_map import bounded_map


class BoundedMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_results_in_input_order(self):
        async def square(value):
            await asyncio.sleep(0)
            return value * value

        self.assertEqual(await bounded_map(square, [3, 1, 2], limit=2), [9, 1, 4])


if __name__ == "__main__":
    unittest.main()
