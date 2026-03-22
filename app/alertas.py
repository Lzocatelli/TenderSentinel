import smtplib
import os
import html
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from app.database import conectar
from app.utils import limite_palavras, formatar_moeda

BASE_URL = os.getenv("BASE_URL", "https://web-production-54881.up.railway.app")

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
    obj_raw = str(objeto or "N/A")
    objeto_s = html.escape(obj_raw[:280] + ("…" if len(obj_raw) > 280 else ""))
    valor_s = formatar_moeda(valor)
    link_s = html.escape(str(link or "#"))
    return f"""
    <div style="border:1px solid #e2e8f0;border-radius:10px;padding:16px 18px;margin-bottom:12px;background:#ffffff">
        <p style="font-size:14px;font-weight:600;color:#0f1f3d;margin:0 0 6px;line-height:1.45">{objeto_s}</p>
        <p style="font-size:12px;color:#64748b;margin:0 0 12px">
            {orgao_s} &nbsp;·&nbsp; <strong style="color:#0f1f3d">{valor_s}</strong>
        </p>
        <a href="{link_s}" style="display:inline-block;background:#0f1f3d;color:#ffffff;text-decoration:none;font-size:12px;font-weight:600;padding:7px 16px;border-radius:6px">Ver edital →</a>
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
        primeiro_nome = html.escape(nome.split()[0]) if nome else "você"
        cards = "".join(_montar_card_licitacao(l[2], l[3], l[4], l[5]) for l in novas)
        qtd = len(novas)
        plural = "licitação encontrada" if qtd == 1 else "licitações encontradas"
        corpo = f"""<!DOCTYPE html>
<html lang="pt-br">
<head><meta charset="UTF-8"><title>Novas licitações — LicitaBot</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Inter,system-ui,-apple-system,'Segoe UI',sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">

    {_EMAIL_BANNER}

    <div style="background:#ffffff;padding:28px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0">
        <p style="font-size:16px;font-weight:600;color:#0f1f3d;margin:0 0 4px">
            Olá, {primeiro_nome}!
        </p>
        <p style="font-size:13px;color:#64748b;margin:0 0 24px;line-height:1.6">
            Encontramos <strong style="color:#0f1f3d">{qtd} {plural}</strong> para as suas palavras-chave. Confira abaixo:
        </p>

        {cards}

        <div style="text-align:center;margin-top:24px">
            <a href="{BASE_URL}/dashboard"
               style="display:inline-block;background:#d4af37;color:#0f1f3d;text-decoration:none;
                      font-size:14px;font-weight:700;padding:12px 28px;border-radius:8px">
                Ver todas no dashboard
            </a>
        </div>
    </div>

    <div style="background:#0f1f3d;padding:18px 32px;text-align:center;border-radius:0 0 12px 12px">
        <p style="font-size:11px;color:rgba(255,255,255,0.4);margin:0;line-height:1.6">
            Você recebe estes alertas porque monitoramos licitações para o seu perfil.<br>
            <a href="{BASE_URL}/minha-conta" style="color:rgba(255,255,255,0.4)">Gerenciar conta</a>
        </p>
    </div>

</div>
</body>
</html>"""
        assunto = f"LicitaBot — {qtd} {plural} para você"
        enviado = enviar_email(email, assunto, corpo)

        if enviado:
            cur.executemany(
                "INSERT INTO alertas_enviados (cliente_id, licitacao_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                [(cliente_id, l[0]) for l in novas],
            )

    conn.commit()
    cur.close()
    conn.close()
