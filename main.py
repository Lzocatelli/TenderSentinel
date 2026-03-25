import logging
import os
import traceback

from dotenv import load_dotenv

from app.scraper import fetch_opportunities, save_opportunities
from app.alertas import dispatch_alerts, send_email

load_dotenv(override=False)

logger = logging.getLogger("tendersentinel.main")

if __name__ == "__main__":
    logger.info("=== TenderSentinel — single execution (production) ===")

    try:
        logger.info("1. Fetching opportunities from SAM.gov...")
        opportunities = fetch_opportunities()
        saved = save_opportunities(opportunities)
        logger.info(f"{saved} new opportunities saved to database")

        logger.info("2. Dispatching alerts to active clients...")
        dispatch_alerts()

        logger.info("Execution completed successfully")

    except Exception as e:
        msg = f"TenderSentinel job error:\n\n{traceback.format_exc()}"
        logger.error(msg)

        admin_email = os.getenv("ADMIN_EMAIL")
        if admin_email:
            try:
                send_email(
                    admin_email,
                    "TenderSentinel — Daily job failure",
                    f"<pre>{msg}</pre>",
                )
            except Exception:
                pass

        raise
