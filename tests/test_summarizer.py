import unittest
from unittest.mock import patch

from app.services import summarizer


class TestBuildSourceText(unittest.TestCase):
    def test_includes_all_fields(self):
        opp = {
            "title": "IT Support Services",
            "agency": "Dept. of Defense",
            "value": 250_000,
            "naics_code": "541512",
            "set_aside": "SDVOSB",
            "deadline": "2026-08-01",
        }
        text = summarizer._build_source_text(opp)
        self.assertIn("IT Support Services", text)
        self.assertIn("Dept. of Defense", text)
        self.assertIn("541512", text)
        self.assertIn("SDVOSB", text)
        self.assertIn("2026-08-01", text)

    def test_handles_missing_fields_gracefully(self):
        opp = {"title": None, "agency": None, "value": None,
               "naics_code": None, "set_aside": None, "deadline": None}
        text = summarizer._build_source_text(opp)
        self.assertIn("N/A", text)
        self.assertIn("None", text)  # set-aside falls back to the word "None"


class TestSourceHash(unittest.TestCase):
    def test_deterministic(self):
        h1 = summarizer._source_hash("some opportunity text")
        h2 = summarizer._source_hash("some opportunity text")
        self.assertEqual(h1, h2)

    def test_changes_when_input_changes(self):
        h1 = summarizer._source_hash("original text")
        h2 = summarizer._source_hash("amended text")
        self.assertNotEqual(h1, h2)

    def test_is_a_sha256_hex_digest(self):
        h = summarizer._source_hash("anything")
        self.assertEqual(len(h), 64)
        int(h, 16)  # raises ValueError if not valid hex


class TestSummarizerDisabledGuard(unittest.TestCase):
    @patch.object(summarizer, "ai_summary_enabled", False)
    def test_raises_when_no_api_key_configured(self):
        with self.assertRaises(summarizer.SummarizerDisabled):
            summarizer.get_or_generate_summary(1)


if __name__ == "__main__":
    unittest.main()
