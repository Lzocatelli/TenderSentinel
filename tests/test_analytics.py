import unittest
from datetime import datetime, timezone

from app.services.analytics import format_snapshot_text


class TestFormatSnapshotText(unittest.TestCase):
    def _snapshot(self, **overrides):
        base = {
            "since": datetime(2026, 7, 23, tzinfo=timezone.utc),
            "new_signups": 3,
            "new_opportunities": 42,
            "alerts_sent": 17,
            "decisions": {"go": 2, "skip": 5},
            "active_paid_clients": 10,
        }
        base.update(overrides)
        return base

    def test_includes_all_counts(self):
        text = format_snapshot_text(self._snapshot())
        self.assertIn("New signups: *3*", text)
        self.assertIn("New opportunities ingested: *42*", text)
        self.assertIn("Alerts sent: *17*", text)
        self.assertIn("Active paid clients: *10*", text)

    def test_decisions_line_includes_all_three_kinds(self):
        text = format_snapshot_text(self._snapshot())
        self.assertIn("2 go", text)
        self.assertIn("0 consider", text)
        self.assertIn("5 skip", text)

    def test_handles_no_decisions(self):
        text = format_snapshot_text(self._snapshot(decisions={}))
        self.assertIn("0 go, 0 consider, 0 skip", text)


if __name__ == "__main__":
    unittest.main()
