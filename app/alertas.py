import smtplib
import os
import html
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from app.database import conectar

load_dotenv()


def enviar_email(destinatario, assunto, corpo):
    """
    Envia e-mail utilizando, na seguinte ordem de prioridade:
    1) SendGrid API (recomendado para produção / Railway)
       Variáveis: SENDGRID_API_KEY, SENDGRID_FROM_EMAIL
    2) SMTP padrão (Gmail), para uso local
       Variáveis: EMAIL_REMETENTE, EMAIL_SENHA
    """
    sendgrid_key = os.getenv("SENDGRID_API_KEY")
    sendgrid_from = os.getenv("SENDGRID_FROM_EMAIL")

    if sendgrid_key and sendgrid_from:
        headers = {
            "Authorization": f"Bearer {sendgrid_key}",
            "Content-Type": "application/json",
        }
        data = {
            "personalizations": [{"to": [{"email": destinatario}]}],
            "from": {"email": sendgrid_from},
            "subject": assunto,
            "content": [{"type": "text/html", "value": corpo}],
        }

        try:
            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers=headers,
                json=data,
                timeout=10,
            )
            if resp.status_code in (200, 202):
                print(f"E-mail enviado para {destinatario} via SendGrid")
                return True
            print(
                f"Falha ao enviar e-mail via SendGrid: "
                f"{resp.status_code} - {resp.text}"
            )
            return False
        except Exception as e:
            print(f"Erro ao enviar e-mail via SendGrid: {e}")
            return False

    remetente = os.getenv("EMAIL_REMETENTE")
    senha = os.getenv("EMAIL_SENHA")

    if not remetente or not senha:
        missing = []
        if not remetente:
            missing.append("EMAIL_REMETENTE")
        if not senha:
            missing.append("EMAIL_SENHA")
        raise RuntimeError(
            "Configuração de e-mail incompleta. "
            f"Defina as variáveis: {', '.join(missing)} "
            "no .env (ambiente local) ou na configuração da Railway. "
            "Para Gmail, prefira utilizar uma App Password."
        )

    msg = MIMEMultipart()
    msg["From"] = remetente
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.attach(MIMEText(corpo, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(remetente, senha)
            server.sendmail(remetente, destinatario, msg.as_string())
        print(f"E-mail enviado para {destinatario} via SMTP")
        return True
    except Exception as e:
        print(f"Erro ao enviar e-mail via SMTP: {e}")
        return False

def montar_corpo_email(licitacoes):
    if not licitacoes:
        return ""

    itens = ""
    for l in licitacoes:
        valor = f"R$ {l[3]:,.2f}" if l[3] else "Não informado"
        link = f'<a href="{l[5]}">Ver licitação</a>' if l[5] else "Link não disponível"
        
        # Trata o texto nulo e limita o tamanho a 250 caracteres para não quebrar o layout
        orgao_texto = str(l[1]) if l[1] else 'N/A'
        objeto_texto = str(l[2]) if l[2] else 'N/A'
        
        if len(objeto_texto) > 250:
            objeto_texto = objeto_texto[:247] + "..."

        # Transforma caracteres perigosos (<, >, &) em texto inofensivo para o HTML
        orgao_seguro = html.escape(orgao_texto)
        objeto_seguro = html.escape(objeto_texto)

        itens += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #eee">{orgao_seguro}</td>
            <td style="padding:8px;border-bottom:1px solid #eee">{objeto_seguro}</td>
            <td style="padding:8px;border-bottom:1px solid #eee">{valor}</td>
            <td style="padding:8px;border-bottom:1px solid #eee">{link}</td>
        </tr>
        """

    return f"""
    <html>
    <body style="font-family:Arial,sans-serif;color:#333">
        <div style="max-width:800px;margin:auto;padding:20px">
            <h2 style="color:#1B3A6B">🔔 LicitaBot — Novas Oportunidades</h2>
            <p>Encontramos <strong>{len(licitacoes)} licitação(ões)</strong> relevantes para você hoje.</p>
            <table style="width:100%;border-collapse:collapse">
                <thead>
                    <tr style="background:#1B3A6B;color:white">
                        <th style="padding:10px;text-align:left">Órgão</th>
                        <th style="padding:10px;text-align:left">Objeto</th>
                        <th style="padding:10px;text-align:left">Valor</th>
                        <th style="padding:10px;text-align:left">Link</th>
                    </tr>
                </thead>
                <tbody>{itens}</tbody>
            </table>
            <p style="color:#888;font-size:12px;margin-top:20px">
                LicitaBot — Monitor Inteligente de Licitações
            </p>
        </div>
    </body>
    </html>
    """

def disparar_alertas():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("SELECT id, nome, email, palavras_chave, plano FROM clientes WHERE ativo = TRUE")
    clientes = cur.fetchall()

    for cliente_row in clientes:
        cliente_id, nome, email, palavras_chave, plano = cliente_row
        palavras_chave = palavras_chave or []

        # Aplicar limite do plano (gratuito=2, basico=5, profissional=20, agencia=ilimitado)
        limites = {None: 2, "basico": 5, "profissional": 20, "agencia": None}
        limite = limites.get(plano, 2)
        if limite is not None and len(palavras_chave) > limite:
            palavras_chave = palavras_chave[:limite]

        from app.scraper import filtrar_por_palavra_chave
        licitacoes = filtrar_por_palavra_chave(palavras_chave)

        novas = []
        for l in licitacoes:
            cur.execute("""
                SELECT id FROM alertas_enviados
                WHERE cliente_id = %s AND licitacao_id = (
                    SELECT id FROM licitacoes WHERE pncp_id = %s
                )
            """, (cliente_id, l[0]))
            if not cur.fetchone():
                novas.append(l)

        if novas:
            corpo = montar_corpo_email(novas)
            assunto = f"LicitaBot — {len(novas)} nova(s) licitação(ões) para você"
            enviado = enviar_email(email, assunto, corpo)

            if enviado:
                for l in novas:
                    cur.execute("""
                        INSERT INTO alertas_enviados (cliente_id, licitacao_id)
                        VALUES (%s, (SELECT id FROM licitacoes WHERE pncp_id = %s))
                    """, (cliente_id, l[0]))

    conn.commit()
    cur.close()
    conn.close()