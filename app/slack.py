"""
Thin Slack notifier for internal/business messages (analytics snapshots,
job failures, etc.), parallel to app/alertas.py's send_email.

Uses an Incoming Webhook URL rather than a bot token: this module only
posts messages, it never receives anything from Slack, so there is no
request to authenticate or sign.
"""

import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv(override=False)

logger = logging.getLogger("tendersentinel.slack")

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")


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
