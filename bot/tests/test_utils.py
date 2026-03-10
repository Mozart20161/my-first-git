import unittest

from football_bot.utils import (
    balance_two_teams,
    format_lineups,
    get_three_team_rating_deltas,
    get_two_team_rating_delta,
    parse_float_arg,
    parse_int_arg,
    validate_date,
    validate_time,
)


class UtilsTests(unittest.TestCase):
    def test_parse_int_arg(self):
        self.assertEqual(parse_int_arg('/setlimit 12'), 12)
        self.assertIsNone(parse_int_arg('/setlimit -1'))
        self.assertEqual(parse_int_arg('/bank -10', allow_negative=True), -10)

    def test_parse_float_arg(self):
        self.assertEqual(parse_float_arg('/setrating Ivan 7.3'), ('Ivan', 7.3))
        self.assertEqual(parse_float_arg('/setrating Ivan 7,3'), ('Ivan', 7.3))
        self.assertIsNone(parse_float_arg('/setrating Ivan abc'))
        self.assertEqual(parse_float_arg('/setrating Andrew Shumilov 6.1'), ('Andrew Shumilov', 6.1))

    def test_balance_two_teams_respects_core(self):
        names = ["A", "B", "C", "D", "E", "F", "G", "H"]
        ratings = {"A": 9, "B": 8, "C": 7, "D": 6, "E": 5, "F": 4, "G": 3, "H": 2}
        teams = balance_two_teams(names, ratings, {"красные": ["A"], "белые": ["B"]})
        self.assertIn("A", teams["красные"])
        self.assertIn("B", teams["белые"])
        self.assertEqual(len(teams["красные"]), 4)
        self.assertEqual(len(teams["белые"]), 4)


    def test_two_team_delta(self):
        self.assertEqual(get_two_team_rating_delta(0), 0.0)
        self.assertEqual(get_two_team_rating_delta(1), 0.035)
        self.assertEqual(get_two_team_rating_delta(2), 0.07)
        self.assertEqual(get_two_team_rating_delta(5), 0.1)

    def test_three_team_deltas(self):
        deltas = get_three_team_rating_deltas({"красные": 6, "белые": 3, "зеленые": 0})
        self.assertGreater(deltas["красные"], 0)
        self.assertLess(deltas["зеленые"], 0)
        self.assertAlmostEqual(sum(deltas.values()), 0.0, places=2)

    def test_format_lineups(self):
        text = format_lineups(
            {"красные": ["Ivan", "Petr"], "белые": ["Oleg"]},
            {"Ivan": 7.0, "Petr": 6.5, "Oleg": 8.0},
        )
        self.assertIn("Красные (рейтинг: 13.5):", text)
        self.assertIn("- Ivan", text)
        self.assertIn("Белые (рейтинг: 8.0):", text)
        self.assertIn("Разница рейтингов: 5.5", text)

    def test_balance_two_teams_respects_core(self):
        names = ["A", "B", "C", "D", "E", "F", "G", "H"]
        ratings = {"A": 9, "B": 8, "C": 7, "D": 6, "E": 5, "F": 4, "G": 3, "H": 2}
        teams = balance_two_teams(names, ratings, {"красные": ["A"], "белые": ["B"]})
        self.assertIn("A", teams["красные"])
        self.assertIn("B", teams["белые"])
        self.assertEqual(len(teams["красные"]), 4)
        self.assertEqual(len(teams["белые"]), 4)


    def test_two_team_delta(self):
        self.assertEqual(get_two_team_rating_delta(0), 0.0)
        self.assertEqual(get_two_team_rating_delta(1), 0.035)
        self.assertEqual(get_two_team_rating_delta(2), 0.07)
        self.assertEqual(get_two_team_rating_delta(5), 0.1)

    def test_three_team_deltas(self):
        deltas = get_three_team_rating_deltas({"красные": 6, "белые": 3, "зеленые": 0})
        self.assertGreater(deltas["красные"], 0)
        self.assertLess(deltas["зеленые"], 0)
        self.assertAlmostEqual(sum(deltas.values()), 0.0, places=2)

    def test_format_lineups(self):
        text = format_lineups(
            {"красные": ["Ivan", "Petr"], "белые": ["Oleg"]},
            {"Ivan": 7.0, "Petr": 6.5, "Oleg": 8.0},
        )
        self.assertIn("Красные (рейтинг: 13.5):", text)
        self.assertIn("- Ivan", text)
        self.assertIn("Белые (рейтинг: 8.0):", text)
        self.assertIn("Разница рейтингов: 5.5", text)

    def test_date_time_validation(self):
        self.assertTrue(validate_date('10.02'))
        self.assertFalse(validate_date('2024-02-10'))
        self.assertTrue(validate_time('22:00'))
        self.assertFalse(validate_time('25:10'))


if __name__ == '__main__':
    unittest.main()
