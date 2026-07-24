"""
Internal daily business snapshot (signups, alerts, decisions), posted to
Slack by the scheduler. Read-only aggregate queries over existing tables —
no new schema.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.database import get_connection, release_connection

logger = logging.getLogger("tendersentinel.analytics")

PAID_PLANS = ("basico", "profissional", "agencia")


def get_daily_snapshot(since: datetime | None = None) -> dict:
    """Aggregate counts for the last 24h (or since `since` if given)."""
    since = since or (datetime.now(timezone.utc) - timedelta(days=1))

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM clientes WHERE criado_em >= %s", (since,))
        new_signups = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM licitacoes WHERE criado_em >= %s", (since,))
        new_opportunities = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM alertas_enviados WHERE enviado_em >= %s", (since,))
        alerts_sent = cur.fetchone()[0]

        cur.execute(
            """SELECT decision, COUNT(*) FROM opportunity_decisions
               WHERE decided_at >= %s GROUP BY decision""",
            (since,),
        )
        decisions = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute(
            "SELECT COUNT(*) FROM clientes WHERE ativo = TRUE AND plano IN %s",
            (PAID_PLANS,),
        )
        active_paid_clients = cur.fetchone()[0]

        return {
            "since": since,
            "new_signups": new_signups,
            "new_opportunities": new_opportunities,
            "alerts_sent": alerts_sent,
            "decisions": decisions,
            "active_paid_clients": active_paid_clients,
        }
    finally:
        cur.close()
        release_connection(conn)


def format_snapshot_text(snapshot: dict) -> str:
    """Formats a snapshot dict as a Slack mrkdwn message."""
    decisions = snapshot["decisions"]
    decisions_line = ", ".join(
        f"{decisions.get(d, 0)} {d}" for d in ("go", "consider", "skip")
    )

    return (
        "*TenderSentinel — Daily Snapshot*\n"
        f"• New signups: *{snapshot['new_signups']}*\n"
        f"• New opportunities ingested: *{snapshot['new_opportunities']}*\n"
        f"• Alerts sent: *{snapshot['alerts_sent']}*\n"
        f"• Decisions logged: {decisions_line}\n"
        f"• Active paid clients: *{snapshot['active_paid_clients']}*"
    )
