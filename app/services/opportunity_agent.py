"""
Slack /opps command: lists recently ingested federal contract opportunities.

Read-only and not tied to any client account — there's no mapping from a
Slack user to a TenderSentinel login, so this shows the same public
ingestion data to anyone who can run the command in the workspace,
optionally narrowed by NAICS code.
"""

import logging

from app.database import get_connection, release_connection
from app.utils import format_currency

logger = logging.getLogger("tendersentinel.opportunity_agent")

DEFAULT_LIMIT = 5


def get_recent_opportunities(naics_code: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Most recently ingested opportunities, optionally filtered by NAICS code."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        if naics_code:
            cur.execute(
                """SELECT orgao, objeto, valor, naics_code, link, criado_em
                   FROM licitacoes
                   WHERE naics_code = %s
                   ORDER BY criado_em DESC
                   LIMIT %s""",
                (naics_code, limit),
            )
        else:
            cur.execute(
                """SELECT orgao, objeto, valor, naics_code, link, criado_em
                   FROM licitacoes
                   ORDER BY criado_em DESC
                   LIMIT %s""",
                (limit,),
            )
        rows = cur.fetchall()
        return [
            {
                "agency": row[0],
                "title": row[1],
                "value": row[2],
                "naics_code": row[3],
                "link": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]
    finally:
        cur.close()
        release_connection(conn)


def format_opportunities_slack(opportunities: list[dict], naics_code: str | None = None) -> str:
    """Formats a list of opportunities as a Slack mrkdwn message."""
    header = f"*Latest opportunities — NAICS {naics_code}*" if naics_code else "*Latest opportunities*"

    if not opportunities:
        return f"{header}\nNone found."

    lines = [header]
    for opp in opportunities:
        title = (opp["title"] or "Untitled")[:120]
        agency = opp["agency"] or "N/A"
        value = format_currency(opp["value"])
        link = opp["link"]
        line = f"• *{title}* — {agency} · {value}"
        if link:
            line += f"\n  <{link}|View on SAM.gov>"
        lines.append(line)

    return "\n".join(lines)
