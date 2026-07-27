"""
Slack integration: posting internal/business messages (analytics snapshots,
job failures) via an Incoming Webhook, and verifying inbound Slash Command
requests signed with the app's signing secret.
"""

import hashlib
import hmac
import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv(override=False)

logger = logging.getLogger("tendersentinel.slack")

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")

# Slack recommends rejecting requests older than this to prevent replay
# attacks with a captured request body + signature.
_MAX_REQUEST_AGE_SECONDS = 60 * 5


def post_to_slack(text: str) -> bool:
    """Posts a plain-text (mrkdwn) message to the configured Slack channel.

    No-op with a logged warning if SLACK_WEBHOOK_URL isn't set, matching how
    other optional integrations (Google OAuth, AI summaries) degrade
    elsewhere in this app.
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not set; skipping Slack post")
        return False

    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error(f"Slack post failed: {e}")
        return False


def verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verifies a Slack request's X-Slack-Signature (v0 scheme).

    See https://api.slack.com/authentication/verifying-requests-from-slack.
    Returns False (never raises) on missing config, a stale timestamp, or a
    mismatched signature — callers should treat any False as "reject".
    """
    if not SLACK_SIGNING_SECRET or not timestamp or not signature:
        return False

    try:
        if abs(time.time() - float(timestamp)) > _MAX_REQUEST_AGE_SECONDS:
            return False
    except ValueError:
        return False

    base_string = b"v0:" + timestamp.encode("utf-8") + b":" + body
    computed = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode("utf-8"), base_string, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)
