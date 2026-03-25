import logging
import os
import time
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

from app.database import get_connection, release_connection

load_dotenv()

logger = logging.getLogger("tendersentinel.scraper")

SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"


def fetch_opportunities(date_from=None, date_to=None):
    """Fetch opportunities from SAM.gov public API."""
    if not date_from:
        date_from = (date.today() - timedelta(days=1)).strftime("%m/%d/%Y")
    if not date_to:
        date_to = date.today().strftime("%m/%d/%Y")

    api_key = os.getenv("SAM_API_KEY")
    if not api_key:
        logger.error("SAM_API_KEY not set")
        return []

    params = {
        "api_key": api_key,
        "postedFrom": date_from,
        "postedTo": date_to,
        "limit": 1000,
        "offset": 0,
    }

    for attempt in range(3):
        try:
            response = requests.get(SAM_API_URL, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                results = data.get("opportunitiesData", [])
                logger.info(f"Fetched {len(results)} opportunities from SAM.gov")
                return results
            else:
                logger.error(f"SAM.gov returned status {response.status_code}")
                return []

        except requests.exceptions.Timeout:
            logger.warning(f"SAM.gov timeout (attempt {attempt + 1}/3)")
            if attempt < 2:
                time.sleep(3)
            else:
                logger.error("SAM.gov did not respond after 3 attempts")

    return []


def save_opportunities(opportunities):
    """Save opportunities to the database. Returns count of new records."""
    if not opportunities:
        logger.info("No opportunities to save")
        return 0

    conn = get_connection()
    cur = conn.cursor()
    saved = 0

    for item in opportunities:
        try:
            pop = item.get("placeOfPerformance") or {}
            state = (pop.get("state") or {}).get("code")

            deadline_raw = item.get("responseDeadLine")
            deadline = deadline_raw[:10] if deadline_raw else None

            posted_raw = item.get("postedDate")
            posted = posted_raw[:10] if posted_raw else None

            cur.execute("""
                INSERT INTO licitacoes
                    (sam_id, orgao, objeto, data_publicacao, link, uf, naics_code, set_aside, deadline)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sam_id) DO NOTHING
            """, (
                item.get("noticeId"),
                item.get("fullParentPathName"),
                item.get("title"),
                posted,
                item.get("uiLink"),
                state,
                item.get("naicsCode"),
                item.get("typeOfSetAside") or None,
                deadline,
            ))
            if cur.rowcount > 0:
                saved += 1
        except Exception as e:
            logger.error(f"Error saving opportunity: {e}")
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    release_connection(conn)
    logger.info(f"{saved} new opportunities saved")
    return saved


def filter_by_keywords(keywords):
    """Filter opportunities by keyword match."""
    conn = get_connection()
    cur = conn.cursor()
    results = []

    for keyword in keywords:
        cur.execute("""
            SELECT sam_id, orgao, objeto, deadline, data_publicacao, link, naics_code, set_aside
            FROM licitacoes
            WHERE LOWER(objeto) LIKE %s
        """, (f"%{keyword.lower()}%",))
        results.extend(cur.fetchall())

    cur.close()
    release_connection(conn)
    return results


# Legacy aliases for backwards compat
buscar_licitacoes = fetch_opportunities
salvar_licitacoes = save_opportunities
filtrar_por_palavra_chave = filter_by_keywords
