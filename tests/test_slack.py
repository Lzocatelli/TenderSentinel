import hashlib
import hmac
import time
import unittest
from unittest.mock import patch

from app import slack


def _sign(secret, timestamp, body_text):
    base_string = f"v0:{timestamp}:{body_text}".encode("utf-8")
    return "v0=" + hmac.new(secret.encode("utf-8"), base_string, hashlib.sha256).hexdigest()


class TestVerifySlackSignature(unittest.TestCase):
    @patch.object(slack, "SLACK_SIGNING_SECRET", "test-secret")
    def test_valid_signature_accepted(self):
        timestamp = str(int(time.time()))
        body = b"command=/opps&text=541512"
        signature = _sign("test-secret", timestamp, body.decode())
        self.assertTrue(slack.verify_slack_signature(body, timestamp, signature))

    @patch.object(slack, "SLACK_SIGNING_SECRET", "test-secret")
    def test_wrong_signature_rejected(self):
        timestamp = str(int(time.time()))
        self.assertFalse(slack.verify_slack_signature(b"command=/opps", timestamp, "v0=deadbeef"))

    @patch.object(slack, "SLACK_SIGNING_SECRET", "test-secret")
    def test_stale_timestamp_rejected(self):
        old_timestamp = str(int(time.time()) - 3600)
        body = b"command=/opps"
        signature = _sign("test-secret", old_timestamp, body.decode())
        self.assertFalse(slack.verify_slack_signature(body, old_timestamp, signature))

    def test_no_signing_secret_configured_rejects(self):
        with patch.object(slack, "SLACK_SIGNING_SECRET", None):
            timestamp = str(int(time.time()))
            self.assertFalse(slack.verify_slack_signature(b"body", timestamp, "v0=whatever"))

    @patch.object(slack, "SLACK_SIGNING_SECRET", "test-secret")
    def test_non_numeric_timestamp_rejected(self):
        self.assertFalse(slack.verify_slack_signature(b"body", "not-a-number", "v0=whatever"))

    @patch.object(slack, "SLACK_SIGNING_SECRET", "test-secret")
    def test_missing_signature_rejected(self):
        timestamp = str(int(time.time()))
        self.assertFalse(slack.verify_slack_signature(b"body", timestamp, ""))


if __name__ == "__main__":
    unittest.main()
