import unittest
from decimal import Decimal

from streaming_csv import aggregate_csv


class StreamingCsvTests(unittest.TestCase):
    def test_groups_valid_amounts(self):
        result = aggregate_csv(["category,amount\n", "fruit,1.25\n", "fruit,2\n"])
        self.assertEqual(result.totals, (("fruit", Decimal("3.25")),))
        self.assertEqual(result.accepted_rows, 2)


if __name__ == "__main__":
    unittest.main()
