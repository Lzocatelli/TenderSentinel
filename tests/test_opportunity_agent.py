import unittest

from app.services.opportunity_agent import format_opportunities_slack


class TestFormatOpportunitiesSlack(unittest.TestCase):
    def test_empty_list(self):
        text = format_opportunities_slack([])
        self.assertIn("None found", text)

    def test_includes_title_agency_value_and_link(self):
        opps = [{
            "title": "IT Support Services",
            "agency": "Dept. of Defense",
            "value": 250000,
            "naics_code": "541512",
            "link": "https://sam.gov/opp/1",
            "created_at": None,
        }]
        text = format_opportunities_slack(opps)
        self.assertIn("IT Support Services", text)
        self.assertIn("Dept. of Defense", text)
        self.assertIn("$250,000.00", text)
        self.assertIn("https://sam.gov/opp/1", text)

    def test_naics_header_included_when_filtered(self):
        text = format_opportunities_slack([], naics_code="541512")
        self.assertIn("NAICS 541512", text)

    def test_no_naics_header_when_unfiltered(self):
        text = format_opportunities_slack([])
        self.assertNotIn("NAICS", text)

    def test_handles_missing_link(self):
        opps = [{"title": "T", "agency": "A", "value": None, "naics_code": None, "link": None, "created_at": None}]
        text = format_opportunities_slack(opps)
        self.assertNotIn("View on SAM.gov", text)

    def test_handles_missing_title(self):
        opps = [{"title": None, "agency": "A", "value": None, "naics_code": None, "link": None, "created_at": None}]
        text = format_opportunities_slack(opps)
        self.assertIn("Untitled", text)


if __name__ == "__main__":
    unittest.main()
