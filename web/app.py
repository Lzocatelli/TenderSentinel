from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.database import conectar
from app.alertas import enviar_email
import requests
import stripe
import os
from datetime import date
from dotenv import load_dotenv

load_dotenv(override=False)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "licitabot2026")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

PLANO_LIMITES = {"basico": 5, "profissional": 20, "agencia": None}

def limite_palavras(plano):
    if not plano:
        return 2
    return PLANO_LIMITES.get(plano)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class Cliente(UserMixin):
    def __init__(self, id, nome, email, palavras_chave, plano=None):
        self.id = id
        self.nome = nome
        self.email = email
        self.palavras_chave = palavras_chave or []
        self.plano = plano

    @property
    def limite_palavras(self):
        return limite_palavras(self.plano)

@login_manager.user_loader
def load_user(user_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT id, nome, email, palavras_chave, plano FROM clientes WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return Cliente(row[0], row[1], row[2], row[3], row[4])
    return None

_cache_contador = {"total": 0, "atualizado_em": None}

def contar_licitacoes_hoje():
    from datetime import datetime, timedelta
    agora = datetime.utcnow()
    if _cache_contador["atualizado_em"] and agora - _cache_contador["atualizado_em"] < timedelta(minutes=5):
        return _cache_contador["total"]

    hoje = date.today().strftime("%Y%m%d")
    url = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
    total = 0
    for modalidade in [4, 5, 6, 7]:
        pagina = 1
        while True:
            try:
                r = requests.get(url, params={
                    "dataInicial": hoje,
                    "dataFinal": hoje,
                    "pagina": pagina,
                    "tamanhoPagina": 50,
                    "codigoModalidadeContratacao": modalidade
                }, timeout=5)
                if r.status_code == 200:
                    dados = r.json().get("data", [])
                    total += len(dados)
                    if len(dados) < 50:
                        break
                    pagina += 1
                else:
                    break
            except:
                break

    _cache_contador["total"] = total
    _cache_contador["atualizado_em"] = agora
    return total

@app.route("/")
def index():
    return render_template("index.html", total_hoje=0)

@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form.get("nome")
        email = request.form.get("email")
        senha = request.form.get("senha")
        palavras = request.form.get("palavras_chave", "")
        palavras_lista = [p.strip() for p in palavras.split(",") if p.strip()]

        limite_free = 2
        if len(palavras_lista) > limite_free:
            flash(f"No plano gratuito você pode cadastrar até {limite_free} palavras-chave. As primeiras foram salvas.", "info")
            palavras_lista = palavras_lista[:limite_free]

        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT id FROM clientes WHERE email = %s", (email,))
        if cur.fetchone():
            flash("E-mail já cadastrado.", "erro")
            return render_template("cadastro.html")

        senha_hash = generate_password_hash(senha)
        cur.execute("""
            INSERT INTO clientes (nome, email, senha, palavras_chave, ativo)
            VALUES (%s, %s, %s, %s, TRUE)
        """, (nome, email, senha_hash, palavras_lista))
        conn.commit()
        cur.close()
        conn.close()

        corpo = f"""
        <h2>Bem-vindo ao LicitaBot, {nome}!</h2>
        <p>Seu cadastro foi realizado com sucesso.</p>
        <p>Você receberá alertas de licitações relacionadas a: <strong>{', '.join(palavras_lista)}</strong></p>
        """
        enviar_email(email, "Bem-vindo ao LicitaBot!", corpo)
        flash("Cadastro realizado! Verifique seu e-mail.", "sucesso")
        return redirect(url_for("login"))

    return render_template("cadastro.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")

        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT id, nome, email, palavras_chave, senha, plano FROM clientes WHERE email = %s", (email,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row and check_password_hash(row[4], senha):
            cliente = Cliente(row[0], row[1], row[2], row[3], row[5])
            login_user(cliente)
            return redirect(url_for("dashboard"))

        flash("E-mail ou senha incorretos.", "erro")

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("""
        SELECT l.orgao, l.objeto, l.valor, l.data_publicacao, l.link
        FROM licitacoes l
        JOIN alertas_enviados ae ON ae.licitacao_id = l.id
        WHERE ae.cliente_id = %s
        ORDER BY ae.enviado_em DESC
        LIMIT 50
    """, (current_user.id,))
    licitacoes = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("dashboard.html", licitacoes=licitacoes, cliente=current_user)

@app.route("/api/contador")
def api_contador():
    total = contar_licitacoes_hoje()
    return jsonify({"total": total})

@app.route("/health")
def health():
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return jsonify({"status": "ok", "database": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "error", "database": str(e)}), 503

@app.route("/assinar/<plano>")
@login_required
def assinar(plano):
    # CORREÇÃO 2: bloqueia se já tem assinatura ativa
    if current_user.plano in ('basico', 'profissional', 'agencia'):
        flash("Você já possui uma assinatura ativa. Para trocar de plano, cancele o atual primeiro.", "info")
        return redirect(url_for("dashboard"))

    periodo = request.args.get("periodo", "mensal")

    precos = {
        "basico": os.getenv("STRIPE_PRICE_BASICO"),
        "profissional": os.getenv("STRIPE_PRICE_PROFISSIONAL"),
        "agencia": os.getenv("STRIPE_PRICE_AGENCIA"),
        "basico_anual": os.getenv("STRIPE_PRICE_BASICO_ANUAL"),
        "profissional_anual": os.getenv("STRIPE_PRICE_PROFISSIONAL_ANUAL"),
        "agencia_anual": os.getenv("STRIPE_PRICE_AGENCIA_ANUAL"),
    }

    chave = f"{plano}_anual" if periodo == "anual" else plano
    price_id = precos.get(chave)

    if not price_id:
        flash("Plano inválido.", "erro")
        return redirect(url_for("index"))

    # CORREÇÃO 1: reutiliza customer_id existente para evitar duplicatas
    customer_id = None
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT stripe_customer_id FROM clientes WHERE id = %s", (current_user.id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and row[0]:
        customer_id = row[0]

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        customer=customer_id if customer_id else None,
        customer_email=None if customer_id else current_user.email,
        metadata={"cliente_id": current_user.id},
        subscription_data={"trial_period_days": 7},
        success_url=request.host_url + "pagamento/sucesso",
        cancel_url=request.host_url + "pagamento/cancelado",
    )
    return redirect(session.url, code=303)

@app.route("/buscar-agora")
@login_required
def buscar_agora():
    from app.scraper import buscar_licitacoes, salvar_licitacoes, filtrar_por_palavra_chave
    from app.alertas import montar_corpo_email
    from app.database import conectar

    try:
        licitacoes = buscar_licitacoes()
        salvar_licitacoes(licitacoes)

        novas = filtrar_por_palavra_chave(current_user.palavras_chave)

        conn = conectar()
        cur = conn.cursor()
        novas_para_cliente = []
        for l in novas:
            cur.execute("""
                SELECT id FROM alertas_enviados
                WHERE cliente_id = %s AND licitacao_id = (
                    SELECT id FROM licitacoes WHERE pncp_id = %s
                )
            """, (current_user.id, l[0]))
            if not cur.fetchone():
                novas_para_cliente.append(l)

        if novas_para_cliente:
            corpo = montar_corpo_email(novas_para_cliente)
            assunto = f"LicitaBot — {len(novas_para_cliente)} nova(s) licitação(ões) encontradas agora"
            enviado = enviar_email(current_user.email, assunto, corpo)
            if enviado:
                for l in novas_para_cliente:
                    cur.execute("""
                        INSERT INTO alertas_enviados (cliente_id, licitacao_id)
                        VALUES (%s, (SELECT id FROM licitacoes WHERE pncp_id = %s))
                    """, (current_user.id, l[0]))

        conn.commit()
        cur.close()
        conn.close()

        if novas_para_cliente:
            flash(f"{len(novas_para_cliente)} nova(s) licitação(ões) encontradas! Verifique seu e-mail.", "sucesso")
        else:
            flash("Nenhuma licitação nova encontrada no momento.", "info")

    except Exception as e:
        flash(f"Erro ao buscar licitações: {str(e)}", "erro")

    return redirect(url_for("dashboard"))

@app.route("/pagamento/sucesso")
@login_required
def pagamento_sucesso():
    return render_template("pagamento_sucesso.html")

@app.route("/pagamento/cancelado")
@login_required
def pagamento_cancelado():
    flash("Pagamento cancelado. Nenhuma cobrança foi feita.", "info")
    return redirect(url_for("index"))

@app.route("/webhook/stripe", methods=["POST"])
def webhook_stripe():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception:
        return "", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        session_id = session["id"]

        # CORREÇÃO 4: valida cliente_id do metadata
        cliente_id = session["metadata"].get("cliente_id")
        if not cliente_id:
            return "", 200

        subscription_id = session.get("subscription")
        customer_id = session.get("customer")

        # CORREÇÃO 3: idempotência — ignora se já processou este session_id
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT stripe_last_session_id FROM clientes WHERE id = %s", (cliente_id,))
        row = cur.fetchone()
        if row and row[0] == session_id:
            cur.close()
            conn.close()
            return "", 200

        # CORREÇÃO 4: valida que customer_id bate com o cliente
        cur.execute("""
            SELECT id FROM clientes
            WHERE id = %s AND (stripe_customer_id = %s OR stripe_customer_id IS NULL)
        """, (cliente_id, customer_id))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return "", 200

        plano = "basico"
        for item in stripe.checkout.Session.list_line_items(session_id).data:
            price_id = item.price.id
            if price_id in (os.getenv("STRIPE_PRICE_PROFISSIONAL"), os.getenv("STRIPE_PRICE_PROFISSIONAL_ANUAL")):
                plano = "profissional"
            elif price_id in (os.getenv("STRIPE_PRICE_AGENCIA"), os.getenv("STRIPE_PRICE_AGENCIA_ANUAL")):
                plano = "agencia"

        cur.execute("""
            UPDATE clientes
            SET plano = %s, stripe_customer_id = %s, stripe_subscription_id = %s, stripe_last_session_id = %s
            WHERE id = %s
        """, (plano, customer_id, subscription_id, session_id, cliente_id))
        conn.commit()
        cur.close()
        conn.close()

    elif event["type"] == "customer.subscription.deleted":
        subscription_id = event["data"]["object"]["id"]
        conn = conectar()
        cur = conn.cursor()
        cur.execute("UPDATE clientes SET plano = NULL WHERE stripe_subscription_id = %s", (subscription_id,))
        conn.commit()
        cur.close()
        conn.close()

    return "", 200

@app.route("/editar-palavras", methods=["GET", "POST"])
@login_required
def editar_palavras():
    if request.method == "POST":
        palavras = request.form.get("palavras_chave", "")
        palavras_lista = [p.strip() for p in palavras.split(",") if p.strip()]

        limite = current_user.limite_palavras
        if limite is not None and len(palavras_lista) > limite:
            flash(f"Seu plano permite até {limite} palavras-chave. As primeiras {limite} foram salvas.", "info")
            palavras_lista = palavras_lista[:limite]

        conn = conectar()
        cur = conn.cursor()
        cur.execute("UPDATE clientes SET palavras_chave = %s WHERE id = %s", (palavras_lista, current_user.id))
        conn.commit()
        cur.close()
        conn.close()

        flash("Palavras-chave atualizadas com sucesso!", "sucesso")
        return redirect(url_for("dashboard"))

    return render_template("editar_palavras.html", cliente=current_user)

if __name__ == "__main__":
    app.run(debug=True, port=5000)