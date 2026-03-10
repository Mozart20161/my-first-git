import unittest

from football_bot.utils import format_lineups, parse_int_arg, parse_float_arg, validate_date, validate_time


class UtilsTests(unittest.TestCase):
    def test_parse_int_arg(self):
        self.assertEqual(parse_int_arg('/setlimit 12'), 12)
        self.assertIsNone(parse_int_arg('/setlimit -1'))
        self.assertEqual(parse_int_arg('/bank -10', allow_negative=True), -10)

    def test_parse_float_arg(self):
        self.assertEqual(parse_float_arg('/setrating Ivan 7.3'), ('Ivan', 7.3))
        self.assertEqual(parse_float_arg('/setrating Ivan 7,3'), ('Ivan', 7.3))
        self.assertIsNone(parse_float_arg('/setrating Ivan abc'))


    def test_format_lineups(self):
        text = format_lineups(
            {"красные": ["Ivan", "Petr"], "белые": ["Oleg"]},
            {"Ivan": 7.0, "Petr": 6.5, "Oleg": 8.0},
        )
        self.assertIn("Красные (рейтинг: 13.5):", text)
        self.assertIn("- Ivan", text)
        self.assertIn("Белые (рейтинг: 8.0):", text)

    def test_date_time_validation(self):
        self.assertTrue(validate_date('10.02'))
        self.assertFalse(validate_date('2024-02-10'))
        self.assertTrue(validate_time('22:00'))
        self.assertFalse(validate_time('25:10'))


if __name__ == '__main__':
    unittest.main()
