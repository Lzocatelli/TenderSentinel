import html
import logging
from datetime import datetime, timedelta, timezone

from app.config import BASE_URL, EMAIL_BANNER
from app.database import get_connection, release_connection
from app.alertas import send_email
from app.score import calculate_score
from app.utils import format_currency

logger = logging.getLogger("tendersentinel.relatorio")


def _build_report_email(client_name, opportunities, top5, total_value):
    """Builds the weekly report HTML."""
    total_count = len(opportunities)
    first_name = html.escape(client_name.split()[0])

    def stars(s):
        filled = "★" * s
        empty = "☆" * (5 - s)
        return f'<span style="color:#fc7218">{filled}</span><span style="color:#4a5568">{empty}</span>'

    cards_html = ""
    for opp in top5:
        agency = html.escape(opp["agency"] or "N/A")
        title_raw = opp["title"] or "N/A"
        title = html.escape(title_raw[:280] + ("…" if len(title_raw) > 280 else ""))
        value = format_currency(opp["value"])
        posted = opp["posted_date"].strftime("%m/%d/%Y") if opp["posted_date"] else "-"
        link = html.escape(opp["link"] or "#")
        score = opp["score"]
        score_label = "High" if score >= 8 else ("Medium" if score >= 5 else "Low")
        score_color = "#16a34a" if score >= 8 else ("#d97706" if score >= 5 else "#94a3b8")

        cards_html += f"""
        <div style="border:1px solid #e2e8f0;border-radius:10px;padding:16px 18px;margin-bottom:12px;background:#ffffff">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;gap:8px">
                <span style="font-size:12px;color:#64748b;font-weight:500">{agency}</span>
                <span style="font-size:11px;font-weight:700;color:{score_color};white-space:nowrap;background:{score_color}1a;padding:2px 8px;border-radius:20px">
                    {score}/10 {score_label}
                </span>
            </div>
            <p style="font-size:14px;font-weight:600;color:#131b2e;margin:0 0 8px;line-height:1.45">{title}</p>
            <p style="font-size:12px;color:#64748b;margin:0 0 12px">
                Estimated value: <strong style="color:#131b2e">{value}</strong>
                &nbsp;·&nbsp; Posted: {posted}
            </p>
            <a href="{link}" target="_blank"
               style="display:inline-block;background:#131b2e;color:#ffffff;text-decoration:none;
                      font-size:12px;font-weight:600;padding:7px 16px;border-radius:6px">
                View on SAM.gov →
            </a>
        </div>
        """

    body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Weekly Report — TenderSentinel</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Inter,system-ui,-apple-system,'Segoe UI',sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">

    {EMAIL_BANNER}

    <div style="background:#ffffff;padding:28px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0">

        <p style="font-size:16px;font-weight:600;color:#131b2e;margin:0 0 4px">
            Hi, {first_name}!
        </p>
        <p style="font-size:13px;color:#64748b;margin:0 0 24px;line-height:1.6">
            Here's your weekly summary of monitored federal contract opportunities.
        </p>

        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px 20px;margin-bottom:24px;display:flex;gap:32px">
            <div>
                <div style="font-size:28px;font-weight:800;color:#131b2e;line-height:1">{total_count}</div>
                <div style="font-size:11px;color:#64748b;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px">opportunities monitored</div>
            </div>
            <div style="border-left:1px solid #e2e8f0;padding-left:32px">
                <div style="font-size:16px;font-weight:700;color:#131b2e;line-height:1.3">{format_currency(total_value)}</div>
                <div style="font-size:11px;color:#64748b;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px">total estimated value</div>
            </div>
        </div>

        <p style="font-size:13px;font-weight:600;color:#131b2e;margin:0 0 4px;text-transform:uppercase;letter-spacing:0.5px">
            Top opportunities this week
        </p>
        <p style="font-size:12px;color:#94a3b8;margin:0 0 16px">
            Ranked by relevance based on your keywords and NAICS codes.
        </p>

        {cards_html or '<p style="font-size:13px;color:#94a3b8;text-align:center;padding:16px 0">No relevant opportunities found in the last 7 days.</p>'}

        <div style="text-align:center;margin-top:24px">
            <a href="{BASE_URL}/dashboard"
               style="display:inline-block;background:#fc7218;color:#ffffff;text-decoration:none;
                      font-size:14px;font-weight:700;padding:12px 28px;border-radius:8px">
                Open my dashboard
            </a>
        </div>
    </div>

    <div style="background:#131b2e;padding:18px 32px;text-align:center;border-radius:0 0 12px 12px">
        <p style="font-size:11px;color:rgba(255,255,255,0.4);margin:0;line-height:1.6">
            You receive this report as part of your Professional or Agency plan on TenderSentinel.<br>
            <a href="{BASE_URL}/my-account" style="color:rgba(255,255,255,0.4)">Manage account</a>
        </p>
    </div>

</div>
</body>
</html>"""
    return body


def generate_weekly_report():
    """Generates and sends the weekly report to Professional and Agency plan clients."""
    conn = get_connection()
    cur = conn.cursor()

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    cur.execute("""
        SELECT id, nome, email, palavras_chave
        FROM clientes
        WHERE ativo = TRUE
          AND plano IN ('profissional', 'agencia')
    """)
    clients = cur.fetchall()

    for client_id, name, email, keywords in clients:
        cur.execute("""
            SELECT l.sam_id, l.orgao, l.objeto, l.valor, l.data_publicacao, l.link, ae.enviado_em
            FROM alertas_enviados ae
            JOIN licitacoes l ON l.id = ae.licitacao_id
            WHERE ae.cliente_id = %s AND ae.enviado_em >= %s
            ORDER BY ae.enviado_em DESC
        """, (client_id, seven_days_ago))
        rows = cur.fetchall()

        if not rows:
            continue

        opportunities = []
        total_value = 0.0

        for row in rows:
            sam_id, agency, title, value, posted_date, link, _sent_at = row
            score = calculate_score(title or "", keywords or [], value)
            opportunities.append({
                "sam_id": sam_id,
                "agency": agency,
                "title": title,
                "value": value,
                "posted_date": posted_date,
                "link": link,
                "score": score,
            })
            if value:
                try:
                    total_value += float(value)
                except Exception:
                    pass

        opportunities.sort(key=lambda x: (x["score"], x["value"] or 0), reverse=True)
        top5 = opportunities[:5]

        body = _build_report_email(name, opportunities, top5, total_value)
        send_email(email, "TenderSentinel — Weekly Opportunities Report", body)

    cur.close()
    release_connection(conn)
    logger.info("Weekly report generation completed")


# Legacy alias
gerar_relatorio_semanal = generate_weekly_report
