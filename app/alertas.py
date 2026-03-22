import smtplib
import os
import html
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from app.database import conectar
from app.utils import limite_palavras, formatar_moeda

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
        try:
            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {sendgrid_key}", "Content-Type": "application/json"},
                json={
                    "personalizations": [{"to": [{"email": destinatario}]}],
                    "from": {"email": sendgrid_from},
                    "subject": assunto,
                    "content": [{"type": "text/html", "value": corpo}],
                },
                timeout=10,
            )
            if resp.status_code in (200, 202):
                print(f"E-mail enviado para {destinatario} via SendGrid")
                return True
            print(f"Falha SendGrid: {resp.status_code} — {resp.text}")
            return False
        except Exception as e:
            print(f"Erro SendGrid: {e}")
            return False

    remetente = os.getenv("EMAIL_REMETENTE")
    senha = os.getenv("EMAIL_SENHA")

    if not remetente or not senha:
        missing = [v for v in ("EMAIL_REMETENTE", "EMAIL_SENHA") if not os.getenv(v)]
        raise RuntimeError(
            f"Configuração de e-mail incompleta. Defina: {', '.join(missing)}"
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
        print(f"Erro SMTP: {e}")
        return False


def _montar_card_licitacao(orgao, objeto, valor, link):
    orgao_s = html.escape(str(orgao or "N/A"))
    objeto_s = html.escape(str(objeto or "N/A")[:280])
    valor_s = formatar_moeda(valor)
    link_s = html.escape(str(link or "#"))
    return f"""
    <div style="border:1px solid #e5e7eb;border-radius:8px;padding:1rem;margin-bottom:1rem">
        <p style="font-weight:600;color:#0f2444;margin:0 0 0.35rem">{objeto_s}</p>
        <p style="color:#64748b;font-size:0.85rem;margin:0 0 0.75rem">{orgao_s} — {valor_s}</p>
        <a href="{link_s}" style="background:#0f2444;color:white;padding:0.35rem 0.85rem;border-radius:6px;text-decoration:none;font-size:0.8rem">Ver edital</a>
    </div>
    """


def disparar_alertas():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("SELECT id, nome, email, palavras_chave, plano FROM clientes WHERE ativo = TRUE")
    clientes = cur.fetchall()

    for cliente_id, nome, email, palavras_chave, plano in clientes:
        palavras_chave = palavras_chave or []

        # Aplica limite do plano via utils (fonte única)
        limite = limite_palavras(plano)
        if limite is not None and len(palavras_chave) > limite:
            palavras_chave = palavras_chave[:limite]

        if not palavras_chave:
            continue

        # Busca todas as licitações que batem com qualquer palavra-chave
        filtros = " OR ".join(["l.objeto ILIKE %s"] * len(palavras_chave))
        params = [f"%{p}%" for p in palavras_chave]
        cur.execute(f"""
            SELECT l.id, l.pncp_id, l.orgao, l.objeto, l.valor, l.link
            FROM licitacoes l
            WHERE {filtros}
        """, params)
        candidatas = cur.fetchall()

        if not candidatas:
            continue

        # FIX N+1: busca todos os alertas já enviados para este cliente de uma só vez
        ids_candidatas = [l[0] for l in candidatas]
        cur.execute("""
            SELECT licitacao_id FROM alertas_enviados
            WHERE cliente_id = %s AND licitacao_id = ANY(%s)
        """, (cliente_id, ids_candidatas))
        ja_enviados = {row[0] for row in cur.fetchall()}

        novas = [l for l in candidatas if l[0] not in ja_enviados]

        if not novas:
            continue

        # Monta e-mail
        cards = "".join(_montar_card_licitacao(l[2], l[3], l[4], l[5]) for l in novas)
        corpo = f"""
        <div style="font-family:Inter,system-ui,sans-serif;max-width:600px;margin:0 auto;padding:2rem">
            <h1 style="color:#0f2444;margin-bottom:0.25rem">Licita<span style="color:#c9a84c">Bot</span></h1>
            <p style="color:#64748b;font-size:0.9rem;margin-bottom:1.5rem">
                {len(novas)} nova(s) licitação(ões) encontradas para você
            </p>
            {cards}
        </div>
        """
        assunto = f"LicitaBot — {len(novas)} nova(s) licitação(ões) para você"
        enviado = enviar_email(email, assunto, corpo)

        if enviado:
            cur.executemany(
                "INSERT INTO alertas_enviados (cliente_id, licitacao_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                [(cliente_id, l[0]) for l in novas],
            )

    conn.commit()
    cur.close()
    conn.close()
