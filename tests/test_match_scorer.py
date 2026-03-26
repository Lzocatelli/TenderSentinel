"""Unit tests for app/services/match_scorer.py"""
import unittest
from app.services.match_scorer import MatchScorer, MatchBreakdown


class TestMatchBreakdown(unittest.TestCase):
    def test_overall_sum(self):
        b = MatchBreakdown(naics_score=3.0, setaside_score=2.5, keyword_score=2.0,
                           size_fit_score=1.5, past_perf_score=1.0)
        self.assertEqual(b.overall, 10.0)

    def test_to_dict(self):
        b = MatchBreakdown(naics_score=1.5)
        d = b.to_dict()
        self.assertIn("overall_score", d)
        self.assertEqual(d["naics_score"], 1.5)


class TestNaicsScoring(unittest.TestCase):
    def setUp(self):
        self.scorer = MatchScorer()
        self.profile = {
            "naics_codes": [
                {"code": "541512", "is_primary": True},
                {"code": "541519", "is_primary": False},
            ],
            "certifications": [], "keywords": [], "past_performance": [],
        }

    def test_exact_primary_match(self):
        opp = {"naics_code": "541512", "objeto": "test"}
        b = self.scorer.score(opp, self.profile)
        self.assertEqual(b.naics_score, 3.0)

    def test_exact_secondary_match(self):
        opp = {"naics_code": "541519", "objeto": "test"}
        b = self.scorer.score(opp, self.profile)
        self.assertEqual(b.naics_score, 2.5)

    def test_4digit_match(self):
        opp = {"naics_code": "541511", "objeto": "test"}
        b = self.scorer.score(opp, self.profile)
        self.assertEqual(b.naics_score, 1.5)

    def test_2digit_match(self):
        opp = {"naics_code": "540000", "objeto": "test"}
        b = self.scorer.score(opp, self.profile)
        self.assertEqual(b.naics_score, 0.5)

    def test_no_match(self):
        opp = {"naics_code": "236220", "objeto": "test"}
        b = self.scorer.score(opp, self.profile)
        self.assertEqual(b.naics_score, 0.0)

    def test_no_opp_naics_neutral(self):
        opp = {"naics_code": "", "objeto": "test"}
        b = self.scorer.score(opp, self.profile)
        self.assertEqual(b.naics_score, 1.5)


class TestSetAsideScoring(unittest.TestCase):
    def setUp(self):
        self.scorer = MatchScorer()

    def test_matching_cert(self):
        profile = {"naics_codes": [], "certifications": [{"type": "SDVOSB"}],
                    "keywords": [], "past_performance": []}
        opp = {"set_aside": "SDVOSBC", "objeto": "test"}
        b = self.scorer.score(opp, profile)
        self.assertEqual(b.setaside_score, 2.5)

    def test_no_matching_cert(self):
        profile = {"naics_codes": [], "certifications": [{"type": "WOSB"}],
                    "keywords": [], "past_performance": []}
        opp = {"set_aside": "SDVOSBC", "objeto": "test"}
        b = self.scorer.score(opp, profile)
        self.assertEqual(b.setaside_score, 0.5)

    def test_full_and_open(self):
        profile = {"naics_codes": [], "certifications": [],
                    "keywords": [], "past_performance": []}
        opp = {"set_aside": "", "objeto": "test"}
        b = self.scorer.score(opp, profile)
        self.assertEqual(b.setaside_score, 1.5)


class TestKeywordScoring(unittest.TestCase):
    def setUp(self):
        self.scorer = MatchScorer()

    def test_all_match(self):
        profile = {"naics_codes": [], "certifications": [],
                    "keywords": [{"keyword": "cloud", "weight": 1.0}, {"keyword": "computing", "weight": 1.0}],
                    "past_performance": []}
        opp = {"objeto": "Cloud Computing Services"}
        b = self.scorer.score(opp, profile)
        self.assertEqual(b.keyword_score, 2.0)

    def test_partial_match(self):
        profile = {"naics_codes": [], "certifications": [],
                    "keywords": [{"keyword": "cloud", "weight": 1.0}, {"keyword": "blockchain", "weight": 1.0}],
                    "past_performance": []}
        opp = {"objeto": "Cloud Computing Services"}
        b = self.scorer.score(opp, profile)
        self.assertEqual(b.keyword_score, 1.0)

    def test_no_keywords(self):
        profile = {"naics_codes": [], "certifications": [],
                    "keywords": [], "past_performance": []}
        opp = {"objeto": "Cloud Computing Services"}
        b = self.scorer.score(opp, profile)
        self.assertEqual(b.keyword_score, 1.0)


class TestOverallScore(unittest.TestCase):
    def test_never_exceeds_10(self):
        scorer = MatchScorer()
        profile = {
            "naics_codes": [{"code": "541512", "is_primary": True}],
            "certifications": [{"type": "SDVOSB"}],
            "keywords": [{"keyword": "software", "weight": 2.0}],
            "past_performance": [{"agency": "DoD", "naics_code": "541512"}],
        }
        opp = {"naics_code": "541512", "set_aside": "SDVOSBC",
               "objeto": "software development", "orgao": "DoD"}
        b = scorer.score(opp, profile)
        self.assertLessEqual(b.overall, 10.0)

    def test_empty_profile_not_negative(self):
        scorer = MatchScorer()
        profile = {"naics_codes": [], "certifications": [],
                    "keywords": [], "past_performance": []}
        opp = {"objeto": "test"}
        b = scorer.score(opp, profile)
        self.assertGreaterEqual(b.overall, 0.0)


class TestAutoClassifier(unittest.TestCase):
    def test_classify(self):
        from app.services.auto_classifier import AutoClassifier
        c = AutoClassifier()
        self.assertEqual(c.classify(9.0), "go")
        self.assertEqual(c.classify(8.0), "go")
        self.assertEqual(c.classify(6.0), "consider")
        self.assertEqual(c.classify(5.0), "consider")
        self.assertEqual(c.classify(4.0), "skip")
        self.assertEqual(c.classify(0.0), "skip")


if __name__ == "__main__":
    unittest.main()
