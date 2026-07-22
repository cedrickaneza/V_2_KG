import unittest

from forexbot.execution.alpaca_broker import format_qty


class TestFormatQty(unittest.TestCase):
    def test_whole_number_has_no_decimal(self):
        self.assertEqual(format_qty(1.0), "1")
        self.assertEqual(format_qty(12.0), "12")

    def test_fractional_crypto_size(self):
        self.assertEqual(format_qty(0.01), "0.01")
        self.assertEqual(format_qty(0.1), "0.1")

    def test_no_scientific_notation_for_small_values(self):
        result = format_qty(0.000001)
        self.assertNotIn("e", result.lower())
        self.assertEqual(result, "0.000001")

    def test_zero_formats_as_zero(self):
        self.assertEqual(format_qty(0), "0")

    def test_tiny_value_below_precision_floors_to_zero(self):
        # below 1e-8 precision, must format cleanly to "0" rather than
        # producing an empty string or malformed order payload
        self.assertEqual(format_qty(0.000000001), "0")


if __name__ == "__main__":
    unittest.main()
