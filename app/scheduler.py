import logging
import os
import traceback

from apscheduler.schedulers.blocking import BlockingScheduler
from pytz import timezone

from app.scraper import fetch_opportunities, save_opportunities
from app.alertas import dispatch_alerts, send_email
from app.relatorio import generate_weekly_report

logger = logging.getLogger("tendersentinel.scheduler")


def fetch_and_alert():
    """Daily job: fetch opportunities from SAM.gov and send alerts."""
    try:
        logger.info("Starting daily opportunity fetch...")
        opportunities = fetch_opportunities()
        saved = save_opportunities(opportunities)
        logger.info(f"{saved} new opportunities saved")

        logger.info("Dispatching alerts...")
        dispatch_alerts()
        logger.info("Daily cycle completed")
    except Exception as e:
        error_msg = f"Scheduler job failed:\n\n{traceback.format_exc()}"
        logger.error(error_msg)
        admin_email = os.getenv("ADMIN_EMAIL")
        if admin_email:
            try:
                send_email(admin_email, "TenderSentinel — Daily job failure", f"<pre>{error_msg}</pre>")
            except Exception:
                pass


def start_scheduler():
    """
    Schedule:
    - Daily at 9:00 AM ET: fetch_and_alert
    - Every Monday at 9:30 AM ET: generate_weekly_report
    """
    tz = timezone("America/New_York")
    scheduler = BlockingScheduler(timezone=tz)

    scheduler.add_job(
        fetch_and_alert,
        "cron",
        hour=9,
        minute=0,
        id="daily_fetch_and_alert",
        replace_existing=True,
    )

    scheduler.add_job(
        generate_weekly_report,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=30,
        id="weekly_report",
        replace_existing=True,
    )

    logger.info("Scheduler started. Waiting for jobs...")
    scheduler.start()


# Legacy aliases
buscar_e_alertar = fetch_and_alert
iniciar_scheduler = start_scheduler

if __name__ == "__main__":
    start_scheduler()
