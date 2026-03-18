import html
import os
from datetime import datetime, timedelta

from app.database import conectar
from app.alertas import enviar_email
from app.score import calcular_score


BASE_URL = os.getenv("BASE_URL", "https://web-production-54881.up.railway.app")

def _formatar_valor(valor):
    if valor is None:
        return "Não informado"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "Não informado"


def _montar_email_relatorio(nome_cliente, licitacoes, top5, total_valor):
    """
    Monta o HTML do relatório semanal, seguindo as cores/fontes solicitadas.
    """
    total_geral = len(licitacoes)
    estrelas = lambda s: "★" * s + "☆" * (5 - s)

    cards_html = ""
    for l in top5:
        orgao = html.escape(l["orgao"] or "N/A")
        objeto = html.escape((l["objeto"] or "N/A")[:300] + ("..." if l["objeto"] and len(l["objeto"]) > 300 else ""))
        valor = _formatar_valor(l["valor"])
        data_pub = l["data_publicacao"].strftime("%d/%m/%Y") if l["data_publicacao"] else "-"
        link = l["link"] or "#"
        score = l["score"]

        cards_html += f"""
        <div style="background:#1e3a5f;border-radius:12px;padding:16px 18px;margin-bottom:12px;color:#f7f9fc">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                <span style="font-size:13px;color:#d4af37">{orgao}</span>
                <span style="font-size:12px;color:#ffd700">{estrelas(score)}</span>
            </div>
            <div style="font-size:14px;font-weight:500;margin-bottom:6px;line-height:1.4">
                {objeto}
            </div>
            <div style="font-size:12px;color:#cbd5f5;margin-bottom:6px">
                Valor estimado: <strong>{valor}</strong> · Publicação: {data_pub}
            </div>
            <a href="{html.escape(link)}" target="_blank" style="display:inline-block;margin-top:4px;font-size:12px;color:#d4af37;text-decoration:none">
                Ver detalhes da licitação →
            </a>
        </div>
        """

    corpo = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Relatório semanal — LicitaBot</title>
    </head>
    <body style="margin:0;padding:0;background:#0f1f3d;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
        <div style="max-width:600px;margin:0 auto;padding:24px 16px;">
            <div style="background:#0f1f3d;border-radius:16px;padding:20px 20px 18px;border:1px solid rgba(255,255,255,0.05);box-shadow:0 10px 30px rgba(0,0,0,0.45);">
                <div style="text-align:center;margin-bottom:18px">
                    <div style="font-size:11px;letter-spacing:0.15em;text-transform:uppercase;color:#9ca8d8;margin-bottom:6px">
                        Relatório semanal de oportunidades
                    </div>
                    <h1 style="margin:0;font-size:20px;color:#ffffff;font-weight:600;">
                        Olá, {html.escape(nome_cliente.split()[0])} 👋
                    </h1>
                </div>

                <div style="background:rgba(15,31,61,0.85);border-radius:12px;padding:12px 14px;margin-bottom:16px;border:1px solid rgba(212,175,55,0.25);">
                    <div style="display:flex;justify-content:space-between;align-items:center;font-size:13px;color:#e5e7f5;">
                        <div>
                            <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:#9ca8d8;margin-bottom:2px">
                                Resumo da semana
                            </div>
                            <div>
                                <strong>{total_geral}</strong> licitação(ões) monitoradas ·
                                Valor estimado total de <strong>{_formatar_valor(total_valor)}</strong>
                            </div>
                        </div>
                    </div>
                </div>

                <div style="margin-bottom:14px">
                    <h2 style="margin:0 0 4px 0;font-size:15px;color:#ffffff;font-weight:500;">
                        Top oportunidades para você
                    </h2>
                    <p style="margin:0;font-size:12px;color:#9ca8d8;">
                        Selecionamos até 5 licitações mais promissoras com base nas suas palavras‑chave.
                    </p>
                </div>

                {cards_html or '<p style="font-size:13px;color:#cbd5f5;">Nenhuma licitação relevante encontrada nos últimos 7 dias.</p>'}

                <div style="text-align:center;margin-top:18px;">
                    <a href="{BASE_URL}/dashboard" style="display:inline-block;background:#d4af37;color:#0f1f3d;text-decoration:none;font-size:13px;font-weight:600;padding:10px 22px;border-radius:999px;">
                        Acessar meu dashboard
                    </a>
                </div>

                <p style="margin-top:18px;font-size:11px;color:#6b7280;text-align:center;line-height:1.5;">
                    Você está recebendo este relatório porque possui um plano Profissional ou Agência no LicitaBot.
                </p>
            </div>
        </div>
    </body>
    </html>
    """
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
            score = calcular_score(objeto or "", palavras_chave or [])

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


