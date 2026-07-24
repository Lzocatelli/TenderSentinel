"""
Standalone entrypoint for the daily Slack analytics snapshot.

Mirrors main.py's shape (single execution, then exit) because production
runs jobs as Railway Cron Job services — an ephemeral container that
starts, runs the start command to completion, and shuts down on its own
schedule. app/scheduler.py's BlockingScheduler is built for an always-on
worker process, which isn't what's deployed here, so this job can't live
there; it needs its own Cron Job service with its own schedule, same as
main.py's.
"""

import logging

from dotenv import load_dotenv

import app.config  # noqa: F401 — configures root logging (basicConfig) as a side effect
from app.services.analytics import get_daily_snapshot, format_snapshot_text
from app.slack import post_to_slack

load_dotenv(override=False)

logger = logging.getLogger("tendersentinel.slack_analytics_job")

if __name__ == "__main__":
    logger.info("=== TenderSentinel — Slack analytics snapshot ===")
    snapshot = get_daily_snapshot()
    post_to_slack(format_snapshot_text(snapshot))
    logger.info("Slack analytics snapshot posted")
