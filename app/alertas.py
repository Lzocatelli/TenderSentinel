import html
import logging
import os
import smtplib

import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

from app.config import BASE_URL, EMAIL_BANNER
from app.database import get_connection, release_connection
from app.utils import keyword_limit, format_currency

load_dotenv()

logger = logging.getLogger("tendersentinel.alertas")


def send_email(recipient, subject, body):
    """
    Sends email using, in order of priority:
    1) SendGrid API (recommended for production)
    2) Gmail SMTP fallback (local use)
    """
    sendgrid_key = os.getenv("SENDGRID_API_KEY")
    sendgrid_from = os.getenv("SENDGRID_FROM_EMAIL")

    if sendgrid_key and sendgrid_from:
        try:
            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {sendgrid_key}", "Content-Type": "application/json"},
                json={
                    "personalizations": [{"to": [{"email": recipient}]}],
                    "from": {"email": sendgrid_from},
                    "subject": subject,
                    "content": [{"type": "text/html", "value": body}],
                },
                timeout=10,
            )
            if resp.status_code in (200, 202):
                logger.info(f"Email sent to {recipient} via SendGrid")
                return True
            logger.error(f"SendGrid error: {resp.status_code} — {resp.text}")
            return False
        except Exception as e:
            logger.error(f"SendGrid exception: {e}")
            return False

    sender = os.getenv("EMAIL_REMETENTE")
    password = os.getenv("EMAIL_SENHA")

    if not sender or not password:
        missing = [v for v in ("EMAIL_REMETENTE", "EMAIL_SENHA") if not os.getenv(v)]
        raise RuntimeError(
            f"Email configuration incomplete. Set: {', '.join(missing)}"
        )

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        logger.info(f"Email sent to {recipient} via SMTP")
        return True
    except Exception as e:
        logger.error(f"SMTP error: {e}")
        return False


def _score_badge_html(score):
    """Generate a color-coded match score badge for emails."""
    if score is None:
        return ""
    if score >= 8:
        bg, color = "#dcfce7", "#166534"
    elif score >= 5:
        bg, color = "#fef9c3", "#854d0e"
    else:
        bg, color = "#f1f5f9", "#64748b"
    return (
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'font-size:11px;font-weight:700;padding:3px 8px;border-radius:4px;'
        f'margin-left:8px">{score:.1f}/10</span>'
    )


def _build_opportunity_card(agency, title, value, link, score=None):
    agency_s = html.escape(str(agency or "N/A"))
    title_raw = str(title or "N/A")
    title_s = html.escape(title_raw[:280] + ("…" if len(title_raw) > 280 else ""))
    value_s = format_currency(value)
    link_s = html.escape(str(link or "#"))
    badge = _score_badge_html(score)
    return f"""
    <div style="border:1px solid #e2e8f0;border-radius:10px;padding:16px 18px;margin-bottom:12px;background:#ffffff">
        <p style="font-size:14px;font-weight:600;color:#0f1f3d;margin:0 0 6px;line-height:1.45">{title_s}{badge}</p>
        <p style="font-size:12px;color:#64748b;margin:0 0 12px">
            {agency_s} &nbsp;·&nbsp; <strong style="color:#0f1f3d">{value_s}</strong>
        </p>
        <a href="{link_s}" style="display:inline-block;background:#0f1f3d;color:#ffffff;text-decoration:none;font-size:12px;font-weight:600;padding:7px 16px;border-radius:6px">View opportunity →</a>
    </div>
    """


def dispatch_alerts():
    """Send email alerts for new matching opportunities."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, nome, email, palavras_chave, plano FROM clientes WHERE ativo = TRUE")
    clients = cur.fetchall()

    for client_id, name, email, keywords, plan in clients:
        keywords = keywords or []

        limit = keyword_limit(plan)
        if limit is not None and len(keywords) > limit:
            keywords = keywords[:limit]

        if not keywords:
            continue

        filters = " OR ".join(["l.objeto ILIKE %s"] * len(keywords))
        params = [f"%{kw}%" for kw in keywords]
        cur.execute(f"""
            SELECT l.id, l.sam_id, l.orgao, l.objeto, l.valor, l.link
            FROM licitacoes l
            WHERE {filters}
        """, params)
        candidates = cur.fetchall()

        if not candidates:
            continue

        candidate_ids = [c[0] for c in candidates]
        cur.execute("""
            SELECT licitacao_id FROM alertas_enviados
            WHERE cliente_id = %s AND licitacao_id = ANY(%s)
        """, (client_id, candidate_ids))
        already_sent = {row[0] for row in cur.fetchall()}

        new_matches = [c for c in candidates if c[0] not in already_sent]

        if not new_matches:
            continue

        # Fetch match scores for this user's new matches
        match_ids = [m[0] for m in new_matches]
        scores_map = {}
        try:
            cur.execute("""
                SELECT opportunity_id, overall_score
                FROM opportunity_match_scores
                WHERE user_id = %s AND opportunity_id = ANY(%s)
            """, (client_id, match_ids))
            scores_map = {row[0]: float(row[1]) for row in cur.fetchall()}
        except Exception:
            pass  # Scores are optional; proceed without them

        first_name = html.escape(name.split()[0]) if name else "there"
        cards = "".join(
            _build_opportunity_card(m[2], m[3], m[4], m[5], score=scores_map.get(m[0]))
            for m in new_matches
        )
        count = len(new_matches)
        plural = "opportunity" if count == 1 else "opportunities"
        body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>New contracts — TenderSentinel</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Inter,system-ui,-apple-system,'Segoe UI',sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">

    {EMAIL_BANNER}

    <div style="background:#ffffff;padding:28px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0">
        <p style="font-size:16px;font-weight:600;color:#0f1f3d;margin:0 0 4px">
            Hi, {first_name}!
        </p>
        <p style="font-size:13px;color:#64748b;margin:0 0 24px;line-height:1.6">
            We found <strong style="color:#0f1f3d">{count} new {plural}</strong> matching your profile. Check them out below:
        </p>

        {cards}

        <div style="text-align:center;margin-top:24px">
            <a href="{BASE_URL}/dashboard"
               style="display:inline-block;background:#d4af37;color:#0f1f3d;text-decoration:none;
                      font-size:14px;font-weight:700;padding:12px 28px;border-radius:8px">
                View all in dashboard
            </a>
        </div>
    </div>

    <div style="background:#0f1f3d;padding:18px 32px;text-align:center;border-radius:0 0 12px 12px">
        <p style="font-size:11px;color:rgba(255,255,255,0.4);margin:0;line-height:1.6">
            You receive these alerts because we monitor federal contracts for your profile.<br>
            <a href="{BASE_URL}/my-account" style="color:rgba(255,255,255,0.4)">Manage account</a>
        </p>
    </div>

</div>
</body>
</html>"""
        top_score = max(scores_map.values()) if scores_map else None
        if top_score and top_score >= 7:
            subject = f"TenderSentinel — {top_score:.1f}/10 Match: {count} new contract {plural}"
        else:
            subject = f"TenderSentinel — {count} new contract {plural} for you"
        sent = send_email(email, subject, body)

        if sent:
            cur.executemany(
                "INSERT INTO alertas_enviados (cliente_id, licitacao_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                [(client_id, m[0]) for m in new_matches],
            )

    conn.commit()
    cur.close()
    release_connection(conn)
    logger.info("Alert dispatch completed")


# Legacy aliases
enviar_email = send_email
disparar_alertas = dispatch_alerts
_montar_card_licitacao = _build_opportunity_card
