"""Unit tests for app/score.py"""
import unittest
from app.score import calcular_score, _keyword_score, _naics_score, _set_aside_score, _value_bonus


class TestKeywordScore(unittest.TestCase):
    def test_no_keywords(self):
        self.assertEqual(_keyword_score("some title", []), 0.0)

    def test_no_title(self):
        self.assertEqual(_keyword_score("", ["software"]), 0.0)

    def test_single_match(self):
        score = _keyword_score("IT software development contract", ["software"])
        self.assertGreater(score, 0)

    def test_phrase_match(self):
        score_phrase = _keyword_score("cloud computing services for DoD", ["cloud computing"])
        score_single = _keyword_score("cloud computing services for DoD", ["cloud"])
        self.assertGreaterEqual(score_phrase, score_single)

    def test_no_match(self):
        self.assertEqual(_keyword_score("Navy ship maintenance", ["software"]), 0.0)

    def test_max_capped_at_6(self):
        title = "software software software software software software"
        score = _keyword_score(title, ["software"])
        self.assertLessEqual(score, 6.0)


class TestNaicsScore(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(_naics_score("541512", ["541512"]), 3.0)

    def test_4digit_match(self):
        self.assertEqual(_naics_score("541512", ["541511"]), 1.5)

    def test_2digit_match(self):
        self.assertEqual(_naics_score("541512", ["540000"]), 0.5)

    def test_no_match(self):
        self.assertEqual(_naics_score("541512", ["236220"]), 0.0)

    def test_empty_inputs(self):
        self.assertEqual(_naics_score(None, ["541512"]), 0.0)
        self.assertEqual(_naics_score("541512", []), 0.0)


class TestSetAsideScore(unittest.TestCase):
    def test_match(self):
        self.assertEqual(_set_aside_score("SDVOSB", ["SDVOSB", "WOSB"]), 1.0)

    def test_no_match(self):
        self.assertEqual(_set_aside_score("8A", ["SDVOSB", "WOSB"]), 0.0)

    def test_empty(self):
        self.assertEqual(_set_aside_score(None, ["SDVOSB"]), 0.0)
        self.assertEqual(_set_aside_score("SDVOSB", []), 0.0)


class TestValueBonus(unittest.TestCase):
    def test_no_value(self):
        self.assertEqual(_value_bonus(None), 0.0)

    def test_zero(self):
        self.assertEqual(_value_bonus(0), 0.0)

    def test_positive_value(self):
        score = _value_bonus(100_000)
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 1.0)

    def test_large_value_capped(self):
        self.assertLessEqual(_value_bonus(100_000_000), 1.0)


class TestCalcularScore(unittest.TestCase):
    def test_full_score_components(self):
        score = calcular_score(
            "cloud computing services",
            ["cloud computing"],
            valor=500_000,
            naics_code="541512",
            user_naics=["541512"],
            set_aside="SDVOSB",
            user_set_asides=["SDVOSB"],
        )
        self.assertGreater(score, 5)
        self.assertLessEqual(score, 10)

    def test_no_match_returns_zero(self):
        score = calcular_score("Navy ship maintenance", ["software"], None)
        self.assertEqual(score, 0)

    def test_score_never_exceeds_10(self):
        score = calcular_score(
            "software development IT cloud",
            ["software", "development", "IT", "cloud"],
            valor=10_000_000,
            naics_code="541512",
            user_naics=["541512"],
            set_aside="SBA",
            user_set_asides=["SBA"],
        )
        self.assertLessEqual(score, 10)

    def test_score_never_negative(self):
        score = calcular_score("", [], None)
        self.assertGreaterEqual(score, 0)


class TestUtils(unittest.TestCase):
    def test_format_currency(self):
        from app.utils import format_currency
        self.assertEqual(format_currency(1234.56), "$1,234.56")
        self.assertEqual(format_currency(0), "$0.00")
        self.assertEqual(format_currency(None), "N/A")

    def test_keyword_limit(self):
        from app.utils import keyword_limit
        self.assertEqual(keyword_limit(None), 1)
        self.assertEqual(keyword_limit("basico"), 5)
        self.assertEqual(keyword_limit("profissional"), 20)
        self.assertIsNone(keyword_limit("agencia"))


if __name__ == "__main__":
    unittest.main()
