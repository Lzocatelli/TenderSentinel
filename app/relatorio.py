import html
import os
from datetime import datetime, timedelta

from app.database import conectar
from app.alertas import enviar_email
from app.score import calcular_score
from app.utils import formatar_moeda


BASE_URL = os.getenv("BASE_URL", "https://web-production-54881.up.railway.app")

def _formatar_valor(valor):
    return formatar_moeda(valor)


_EMAIL_BANNER = """
<div style="background:linear-gradient(135deg,#0f1f3d 0%,#1a3a6b 100%);padding:28px 32px;text-align:center;border-radius:12px 12px 0 0">
    <div style="font-size:28px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;font-family:Georgia,serif">
        Licita<span style="color:#d4af37">Bot</span>
    </div>
    <div style="font-size:11px;letter-spacing:2.5px;text-transform:uppercase;color:rgba(255,255,255,0.45);margin-top:5px">
        Monitor Inteligente de Licitações
    </div>
</div>
"""


def _montar_email_relatorio(nome_cliente, licitacoes, top5, total_valor):
    """
    Monta o HTML do relatório semanal com banner e personalização.
    """
    total_geral = len(licitacoes)
    primeiro_nome = html.escape(nome_cliente.split()[0])

    def estrelas(s):
        filled = "★" * s
        empty = "☆" * (5 - s)
        return f'<span style="color:#d4af37">{filled}</span><span style="color:#4a5568">{empty}</span>'

    cards_html = ""
    for l in top5:
        orgao = html.escape(l["orgao"] or "N/A")
        obj_raw = l["objeto"] or "N/A"
        objeto = html.escape(obj_raw[:280] + ("…" if len(obj_raw) > 280 else ""))
        valor = _formatar_valor(l["valor"])
        data_pub = l["data_publicacao"].strftime("%d/%m/%Y") if l["data_publicacao"] else "-"
        link = html.escape(l["link"] or "#")
        score = l["score"]
        score_label = "Alta" if score >= 8 else ("Média" if score >= 5 else "Baixa")
        score_color = "#16a34a" if score >= 8 else ("#d97706" if score >= 5 else "#94a3b8")

        cards_html += f"""
        <div style="border:1px solid #e2e8f0;border-radius:10px;padding:16px 18px;margin-bottom:12px;background:#ffffff">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;gap:8px">
                <span style="font-size:12px;color:#64748b;font-weight:500">{orgao}</span>
                <span style="font-size:11px;font-weight:700;color:{score_color};white-space:nowrap;background:{score_color}1a;padding:2px 8px;border-radius:20px">
                    {score}/10 {score_label}
                </span>
            </div>
            <p style="font-size:14px;font-weight:600;color:#0f1f3d;margin:0 0 8px;line-height:1.45">{objeto}</p>
            <p style="font-size:12px;color:#64748b;margin:0 0 12px">
                Valor estimado: <strong style="color:#0f1f3d">{valor}</strong>
                &nbsp;·&nbsp; Publicado em: {data_pub}
            </p>
            <a href="{link}" target="_blank"
               style="display:inline-block;background:#0f1f3d;color:#ffffff;text-decoration:none;
                      font-size:12px;font-weight:600;padding:7px 16px;border-radius:6px">
                Ver edital →
            </a>
        </div>
        """

    resumo_stars = estrelas(min(5, round(total_geral / 2))) if total_geral > 0 else ""

    corpo = f"""<!DOCTYPE html>
<html lang="pt-br">
<head><meta charset="UTF-8"><title>Relatório semanal — LicitaBot</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Inter,system-ui,-apple-system,'Segoe UI',sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">

    {_EMAIL_BANNER}

    <div style="background:#ffffff;padding:28px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0">

        <p style="font-size:16px;font-weight:600;color:#0f1f3d;margin:0 0 4px">
            Olá, {primeiro_nome}!
        </p>
        <p style="font-size:13px;color:#64748b;margin:0 0 24px;line-height:1.6">
            Aqui está o resumo das oportunidades monitoradas para você nos últimos 7 dias.
        </p>

        <!-- Resumo numérico -->
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px 20px;margin-bottom:24px;display:flex;gap:32px">
            <div>
                <div style="font-size:28px;font-weight:800;color:#0f1f3d;line-height:1">{total_geral}</div>
                <div style="font-size:11px;color:#64748b;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px">licitações monitoradas</div>
            </div>
            <div style="border-left:1px solid #e2e8f0;padding-left:32px">
                <div style="font-size:16px;font-weight:700;color:#0f1f3d;line-height:1.3">{_formatar_valor(total_valor)}</div>
                <div style="font-size:11px;color:#64748b;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px">valor total estimado</div>
            </div>
        </div>

        <p style="font-size:13px;font-weight:600;color:#0f1f3d;margin:0 0 4px;text-transform:uppercase;letter-spacing:0.5px">
            Top oportunidades da semana
        </p>
        <p style="font-size:12px;color:#94a3b8;margin:0 0 16px">
            Selecionadas por relevância com base nas suas palavras-chave.
        </p>

        {cards_html or '<p style="font-size:13px;color:#94a3b8;text-align:center;padding:16px 0">Nenhuma licitação relevante encontrada nos últimos 7 dias.</p>'}

        <div style="text-align:center;margin-top:24px">
            <a href="{BASE_URL}/dashboard"
               style="display:inline-block;background:#d4af37;color:#0f1f3d;text-decoration:none;
                      font-size:14px;font-weight:700;padding:12px 28px;border-radius:8px">
                Acessar meu dashboard
            </a>
        </div>
    </div>

    <!-- Footer -->
    <div style="background:#0f1f3d;padding:18px 32px;text-align:center;border-radius:0 0 12px 12px">
        <p style="font-size:11px;color:rgba(255,255,255,0.4);margin:0;line-height:1.6">
            Você recebe este relatório por ter um plano Profissional ou Agência no LicitaBot.<br>
            <a href="{BASE_URL}/minha-conta" style="color:rgba(255,255,255,0.4)">Gerenciar conta</a>
        </p>
    </div>

</div>
</body>
</html>"""
    return corpo


def gerar_relatorio_semanal():
    """
    Gera e envia o relatório semanal para clientes dos planos Profissional e Agência.
    """
    conn = conectar()
    cur = conn.cursor()

    sete_dias_atras = datetime.utcnow() - timedelta(days=7)

    cur.execute(
        """
        SELECT id, nome, email, palavras_chave
        FROM clientes
        WHERE ativo = TRUE
          AND plano IN ('profissional', 'agencia')
        """
    )
    clientes = cur.fetchall()

    for cliente_id, nome, email, palavras_chave in clientes:
        cur.execute(
            """
            SELECT
                l.pncp_id,
                l.orgao,
                l.objeto,
                l.valor,
                l.data_publicacao,
                l.link,
                ae.enviado_em
            FROM alertas_enviados ae
            JOIN licitacoes l ON l.id = ae.licitacao_id
            WHERE ae.cliente_id = %s
              AND ae.enviado_em >= %s
            ORDER BY ae.enviado_em DESC
            """,
            (cliente_id, sete_dias_atras),
        )
        rows = cur.fetchall()

        if not rows:
            continue

        licitacoes = []
        total_valor = 0.0

        for row in rows:
            pncp_id, orgao, objeto, valor, data_publicacao, link, _enviado_em = row
            score = calcular_score(objeto or "", palavras_chave or [], valor)

            licitacoes.append(
                {
                    "pncp_id": pncp_id,
                    "orgao": orgao,
                    "objeto": objeto,
                    "valor": valor,
                    "data_publicacao": data_publicacao,
                    "link": link,
                    "score": score,
                }
            )
            if valor:
                try:
                    total_valor += float(valor)
                except Exception:
                    pass

        # Ordena por score decrescente e, em seguida, por valor (quando houver)
        licitacoes.sort(key=lambda x: (x["score"], x["valor"] or 0), reverse=True)
        top5 = licitacoes[:5]

        corpo = _montar_email_relatorio(nome, licitacoes, top5, total_valor)
        assunto = "LicitaBot — Relatório semanal de oportunidades"
        enviar_email(email, assunto, corpo)

    cur.close()
    conn.close()


if __name__ == "__main__":
    gerar_relatorio_semanal()


