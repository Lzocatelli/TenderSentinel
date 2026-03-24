import csv
import hmac
import html as html_lib
import io
import os
import secrets
import time
from datetime import date, datetime, timedelta
from threading import Thread

import requests
import stripe
from dotenv import load_dotenv
from flask import (Flask, Response, abort, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from werkzeug.security import check_password_hash, generate_password_hash

from app.alertas import enviar_email
from app.database import conectar
from app.utils import formatar_moeda, limite_palavras

load_dotenv(override=False)

# ── Configuração da aplicação ─────────────────────────────────────────────────

secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    secret_key = secrets.token_urlsafe(32)
    if os.getenv("FLASK_ENV") != "production":
        print(
            "WARNING: SECRET_KEY não definido; usando chave temporária. "
            "Defina SECRET_KEY no ambiente em produção."
        )

app = Flask(__name__)
app.secret_key = secret_key
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",
    REMEMBER_COOKIE_DURATION=timedelta(days=30),
)
app.permanent_session_lifetime = timedelta(days=30)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# ── Login ─────────────────────────────────────────────────────────────────────

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class Cliente(UserMixin):
    def __init__(self, id, nome, email, palavras_chave, plano=None, naics_codes=None, set_asides=None):
        self.id = id
        self.nome = nome
        self.email = email
        self.palavras_chave = palavras_chave or []
        self.plano = plano
        self.naics_codes = naics_codes or []
        self.set_asides = set_asides or []

    @property
    def limite_palavras(self):
        return limite_palavras(self.plano)

    @property
    def plano_pago(self):
        return self.plano in ("basico", "profissional", "agencia")


@login_manager.user_loader
def load_user(user_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, nome, email, palavras_chave, plano, naics_codes, set_asides FROM clientes WHERE id = %s",
        (user_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return Cliente(*row) if row else None


# ── CSRF ──────────────────────────────────────────────────────────────────────

def _get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(16)
        session["_csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = _get_csrf_token


@app.before_request
def verificar_csrf():
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if (request.endpoint or "") in {"api_contador", "health", "webhook_stripe"}:
        return
    token_form = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    token_session = session.get("_csrf_token")
    if not token_form or not token_session or not hmac.compare_digest(token_form, token_session):
        abort(400)


# ── Filtro Jinja ──────────────────────────────────────────────────────────────

@app.template_filter("moeda")
def moeda_filter(valor):
    if not valor:
        return "—"
    try:
        return f"${float(valor):,.2f}"
    except Exception:
        return "—"


# ── Contador com cache ────────────────────────────────────────────────────────

_cache_contador = {"total": 0, "atualizado_em": None}


def contar_licitacoes_hoje():
    agora = datetime.utcnow()
    if _cache_contador["atualizado_em"] and agora - _cache_contador["atualizado_em"] < timedelta(minutes=5):
        return _cache_contador["total"]

    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM licitacoes WHERE data_publicacao = CURRENT_DATE")
        total = cur.fetchone()[0] or 0
        cur.close()
        conn.close()
    except Exception:
        total = 0

    _cache_contador["total"] = total
    _cache_contador["atualizado_em"] = agora
    return total


# ── Rotas públicas ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", total_hoje=0)


@app.route("/api/contador")
def api_contador():
    return jsonify({"total": contar_licitacoes_hoje()})


@app.route("/health")
def health():
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return jsonify({"status": "ok", "database": "ok"}), 200
    except Exception:
        return jsonify({"status": "error", "database": "unavailable"}), 503


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        palavras = request.form.get("palavras_chave", "")
        palavras_lista = [p.strip() for p in palavras.split(",") if p.strip()]

        limite_free = limite_palavras(None)
        if len(palavras_lista) > limite_free:
            flash(f"The free plan allows up to {limite_free} keyword. The first one was saved.", "info")
            palavras_lista = palavras_lista[:limite_free]

        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT id FROM clientes WHERE email = %s", (email,))
        if cur.fetchone():
            flash("Email already registered.", "erro")
            cur.close()
            conn.close()
            return render_template("cadastro.html")

        cur.execute(
            "INSERT INTO clientes (nome, email, senha, palavras_chave, ativo) VALUES (%s, %s, %s, %s, TRUE)",
            (nome, email, generate_password_hash(senha), palavras_lista),
        )
        conn.commit()
        cur.close()
        conn.close()

        enviar_email(email, "Welcome to TenderSentinel!", f"""
        <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:2rem">
            <h1 style="color:#0f2444;font-family:Inter,sans-serif">TenderSentinel</h1>
            <h2>Welcome, {html_lib.escape(nome)}!</h2>
            <p>Your account is ready. You'll receive alerts for:
               <strong>{html_lib.escape(', '.join(palavras_lista))}</strong></p>
        </div>
        """)
        flash("Account created! Check your email.", "sucesso")
        return redirect(url_for("login"))

    return render_template("cadastro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")

        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, nome, email, palavras_chave, senha, plano FROM clientes WHERE email = %s",
            (email,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row and check_password_hash(row[4], senha):
            login_user(Cliente(row[0], row[1], row[2], row[3], row[5]), remember=True)
            return redirect(url_for("dashboard"))

        flash("Incorrect email or password.", "erro")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    plano_pago = current_user.plano_pago
    valor_min = request.args.get("valor_min", type=float) if plano_pago else None
    uf = request.args.get("uf", "").strip().upper() or None if plano_pago else None

    palavras = current_user.palavras_chave or []
    if not palavras:
        return render_template(
            "dashboard.html",
            licitacoes=[],
            cliente=current_user,
            show_score=plano_pago,
            valor_min=valor_min or "",
            uf_selecionada=uf or "",
        )

    filtros_kw = " OR ".join(["l.objeto ILIKE %s"] * len(palavras))
    params_kw = [f"%{p}%" for p in palavras]

    conn = conectar()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT l.orgao, l.objeto, l.valor, l.data_publicacao, l.link, l.naics_code, l.set_aside
        FROM licitacoes l
        WHERE ({filtros_kw})
          AND (%s IS NULL OR l.valor >= %s)
          AND (%s IS NULL OR l.uf = %s)
        ORDER BY l.data_publicacao DESC
        LIMIT 50
    """, params_kw + [valor_min, valor_min, uf, uf])

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if plano_pago:
        from app.score import calcular_score
        licitacoes = []
        for row in rows:
            orgao, objeto, valor, data, link, naics_code, set_aside = row
            score = calcular_score(
                objeto, palavras, valor,
                naics_code=naics_code,
                user_naics=current_user.naics_codes,
                set_aside=set_aside,
                user_set_asides=current_user.set_asides,
            )
            licitacoes.append((orgao, objeto, valor, data, link, score))
        licitacoes.sort(key=lambda x: x[5], reverse=True)
    else:
        licitacoes = [row[:5] for row in rows]

    return render_template(
        "dashboard.html",
        licitacoes=licitacoes,
        cliente=current_user,
        show_score=plano_pago,
        valor_min=valor_min or "",
        uf_selecionada=uf or "",
    )


# ── Busca manual ──────────────────────────────────────────────────────────────

@app.route("/buscar-agora", methods=["POST"])
@login_required
def buscar_agora():
    if not current_user.plano_pago:
        flash("Manual search is available on paid plans. You'll receive automatic alerts at 9am.", "info")
        return redirect(url_for("dashboard"))

    cliente_id = current_user.id
    cliente_email = current_user.email
    cliente_palavras = current_user.palavras_chave

    def _rodar(cliente_id, cliente_email, cliente_palavras):
        from app.scraper import buscar_licitacoes, salvar_licitacoes

        licitacoes = buscar_licitacoes()
        salvar_licitacoes(licitacoes)

        conn = conectar()
        cur = conn.cursor()
        try:
            # Busca novas licitações para as palavras do cliente
            filtros = " OR ".join(["l.objeto ILIKE %s"] * len(cliente_palavras))
            params = [f"%{p}%" for p in cliente_palavras]
            cur.execute(f"""
                SELECT l.id, l.sam_id, l.orgao, l.objeto, l.valor, l.link
                FROM licitacoes l
                WHERE {filtros}
            """, params)
            candidatas = cur.fetchall()

            ids = [l[0] for l in candidatas]
            cur.execute(
                "SELECT licitacao_id FROM alertas_enviados WHERE cliente_id = %s AND licitacao_id = ANY(%s)",
                (cliente_id, ids),
            )
            ja_enviados = {row[0] for row in cur.fetchall()}
            novas = [l for l in candidatas if l[0] not in ja_enviados]

            if novas:
                from app.alertas import _montar_card_licitacao
                cards = "".join(_montar_card_licitacao(l[2], l[3], l[4], l[5]) for l in novas)
                corpo = f"""
                <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:2rem">
                    <h1 style="color:#0f2444;font-family:Inter,sans-serif">TenderSentinel</h1>
                    <p style="color:#64748b;margin-bottom:1.5rem">{len(novas)} nova(s) licitação(ões) encontradas!</p>
                    {cards}
                </div>
                """
                enviar_email(
                    cliente_email,
                    f"TenderSentinel — {len(novas)} nova(s) licitação(ões) encontradas!",
                    corpo,
                )
                cur.executemany(
                    "INSERT INTO alertas_enviados (cliente_id, licitacao_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    [(cliente_id, l[0]) for l in novas],
                )

            conn.commit()
        except Exception as e:
            print(f"Erro buscar_agora: {e}")
            conn.rollback()
        finally:
            cur.close()
            conn.close()

    Thread(target=_rodar, args=(cliente_id, cliente_email, cliente_palavras), daemon=True).start()
    flash("Search started! If we find new matches, you'll receive an email shortly.", "info")
    return redirect(url_for("dashboard"))


# ── Minha Conta ───────────────────────────────────────────────────────────────

@app.route("/minha-conta", methods=["GET", "POST"])
@login_required
def minha_conta():
    renovacao = None
    if current_user.plano_pago:
        try:
            conn = conectar()
            cur = conn.cursor()
            cur.execute("SELECT stripe_subscription_id FROM clientes WHERE id = %s", (current_user.id,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row and row[0]:
                sub = stripe.Subscription.retrieve(row[0])
                renovacao = datetime.fromtimestamp(sub.current_period_end).strftime("%d/%m/%Y")
        except Exception:
            pass

    if request.method == "POST":
        senha_atual = request.form.get("senha_atual", "")
        nova_senha = request.form.get("nova_senha", "")
        confirmar = request.form.get("confirmar_senha", "")

        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT senha FROM clientes WHERE id = %s", (current_user.id,))
        row = cur.fetchone()

        if not row or not check_password_hash(row[0], senha_atual):
            flash("Current password is incorrect.", "erro")
        elif len(nova_senha) < 8:
            flash("New password must be at least 8 characters.", "erro")
        elif nova_senha != confirmar:
            flash("Passwords do not match.", "erro")
        else:
            cur.execute(
                "UPDATE clientes SET senha = %s WHERE id = %s",
                (generate_password_hash(nova_senha), current_user.id),
            )
            conn.commit()
            flash("Password updated successfully!", "sucesso")

        cur.close()
        conn.close()

    return render_template("minha_conta.html", cliente=current_user, renovacao=renovacao)


# ── Export CSV ────────────────────────────────────────────────────────────────

@app.route("/export-csv")
@login_required
def export_csv():
    if current_user.plano not in ("profissional", "agencia"):
        flash("O download de CSV está disponível a partir do plano Profissional.", "info")
        return redirect(url_for("dashboard"))

    valor_min = request.args.get("valor_min", type=float)
    uf = request.args.get("uf", "").strip().upper() or None

    conn = conectar()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT l.orgao, l.objeto, l.valor, l.data_publicacao, l.link, l.uf
            FROM licitacoes l
            JOIN alertas_enviados ae ON ae.licitacao_id = l.id
            WHERE ae.cliente_id = %s
              AND (%s IS NULL OR l.valor >= %s)
              AND (%s IS NULL OR l.uf = %s)
            ORDER BY ae.enviado_em DESC
            LIMIT 500
        """, [current_user.id, valor_min, valor_min, uf, uf])
    except Exception:
        cur.execute("""
            SELECT l.orgao, l.objeto, l.valor, l.data_publicacao, l.link
            FROM licitacoes l
            JOIN alertas_enviados ae ON ae.licitacao_id = l.id
            WHERE ae.cliente_id = %s
              AND (%s IS NULL OR l.valor >= %s)
            ORDER BY ae.enviado_em DESC
            LIMIT 500
        """, [current_user.id, valor_min, valor_min])

    rows = cur.fetchall()
    cur.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Órgão", "Objeto", "Valor (R$)", "Data publicação", "Link", "UF"])
    for row in rows:
        orgao, objeto, valor, data, link = row[:5]
        uf_val = row[5] if len(row) > 5 else ""
        writer.writerow([orgao, objeto, formatar_moeda(valor), data, link, uf_val])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=licitacoes.csv"},
    )


# ── Editar palavras-chave ─────────────────────────────────────────────────────

@app.route("/editar-palavras", methods=["GET", "POST"])
@login_required
def editar_palavras():
    if request.method == "POST":
        palavras_lista = [p.strip() for p in request.form.get("palavras_chave", "").split(",") if p.strip()]

        limite = current_user.limite_palavras
        if limite is not None and len(palavras_lista) > limite:
            flash(f"Your plan allows up to {limite} keywords. The first {limite} were saved.", "info")
            palavras_lista = palavras_lista[:limite]

        conn = conectar()
        cur = conn.cursor()
        cur.execute("UPDATE clientes SET palavras_chave = %s WHERE id = %s", (palavras_lista, current_user.id))
        conn.commit()
        cur.close()
        conn.close()
        flash("Keywords updated successfully!", "sucesso")
        return redirect(url_for("dashboard"))

    return render_template("editar_palavras.html", cliente=current_user)


# ── Editar perfil NAICS / set-asides ─────────────────────────────────────────

VALID_SET_ASIDES = {"SBA", "8A", "HZC", "WOSB", "EDWOSB", "SDVOSB", "VSB"}


@app.route("/editar-perfil", methods=["GET", "POST"])
@login_required
def editar_perfil():
    if request.method == "POST":
        naics_raw = request.form.get("naics_codes", "")
        naics_lista = [c.strip() for c in naics_raw.replace(",", " ").split() if c.strip().isdigit()]

        set_asides_lista = [
            s for s in request.form.getlist("set_asides")
            if s.upper() in VALID_SET_ASIDES
        ]

        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            "UPDATE clientes SET naics_codes = %s, set_asides = %s WHERE id = %s",
            (naics_lista or None, set_asides_lista or None, current_user.id),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("Profile updated successfully!", "sucesso")
        return redirect(url_for("dashboard"))

    return render_template("editar_perfil.html", cliente=current_user, valid_set_asides=sorted(VALID_SET_ASIDES))


# ── Assinatura / Stripe ───────────────────────────────────────────────────────

@app.route("/assinar/<plano>")
@login_required
def assinar(plano):
    if current_user.plano_pago:
        flash("You already have an active subscription. To change plans, cancel the current one first.", "info")
        return redirect(url_for("dashboard"))

    periodo = request.args.get("periodo", "mensal")
    precos = {
        "basico":               os.getenv("STRIPE_PRICE_BASICO"),
        "profissional":         os.getenv("STRIPE_PRICE_PROFISSIONAL"),
        "agencia":              os.getenv("STRIPE_PRICE_AGENCIA"),
        "basico_anual":         os.getenv("STRIPE_PRICE_BASICO_ANUAL"),
        "profissional_anual":   os.getenv("STRIPE_PRICE_PROFISSIONAL_ANUAL"),
        "agencia_anual":        os.getenv("STRIPE_PRICE_AGENCIA_ANUAL"),
    }
    price_id = precos.get(f"{plano}_anual" if periodo == "anual" else plano)

    if not price_id:
        flash("Invalid plan.", "erro")
        return redirect(url_for("index"))

    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT stripe_customer_id FROM clientes WHERE id = %s", (current_user.id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    customer_id = row[0] if row and row[0] else None

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        customer=customer_id,
        customer_email=None if customer_id else current_user.email,
        metadata={"cliente_id": current_user.id},
        subscription_data={"trial_period_days": 7},
        success_url=request.host_url + "pagamento/sucesso",
        cancel_url=request.host_url + "pagamento/cancelado",
    )
    return redirect(checkout_session.url, code=303)


@app.route("/gerenciar-assinatura")
@login_required
def gerenciar_assinatura():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT stripe_customer_id FROM clientes WHERE id = %s", (current_user.id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row or not row[0]:
        flash("No subscription found.", "info")
        return redirect(url_for("dashboard"))

    try:
        portal = stripe.billing_portal.Session.create(
            customer=row[0],
            return_url=request.host_url + "dashboard",
        )
        return redirect(portal.url, code=303)
    except stripe.error.InvalidRequestError:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            "UPDATE clientes SET stripe_customer_id = NULL, stripe_subscription_id = NULL, plano = NULL WHERE id = %s",
            (current_user.id,),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("Subscription not found. Your plan was reset — please subscribe again.", "info")
        return redirect(url_for("index"))


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
        sess = event["data"]["object"]
        session_id = sess["id"]
        cliente_id = sess["metadata"].get("cliente_id")
        if not cliente_id:
            return "", 200

        subscription_id = sess.get("subscription")
        customer_id = sess.get("customer")

        conn = conectar()
        cur = conn.cursor()

        # Idempotência: ignora se já processou esta sessão
        cur.execute("SELECT stripe_last_session_id FROM clientes WHERE id = %s", (cliente_id,))
        row = cur.fetchone()
        if row and row[0] == session_id:
            cur.close()
            conn.close()
            return "", 200

        # Valida que o customer bate com o registro
        cur.execute(
            "SELECT id FROM clientes WHERE id = %s AND (stripe_customer_id = %s OR stripe_customer_id IS NULL)",
            (cliente_id, customer_id),
        )
        if not cur.fetchone():
            cur.close()
            conn.close()
            return "", 200

        plano = "basico"
        try:
            for item in stripe.checkout.Session.list_line_items(session_id).data:
                pid = item.price.id
                if pid in (os.getenv("STRIPE_PRICE_PROFISSIONAL"), os.getenv("STRIPE_PRICE_PROFISSIONAL_ANUAL")):
                    plano = "profissional"
                elif pid in (os.getenv("STRIPE_PRICE_AGENCIA"), os.getenv("STRIPE_PRICE_AGENCIA_ANUAL")):
                    plano = "agencia"
        except Exception:
            pass

        cur.execute(
            "UPDATE clientes SET plano=%s, stripe_customer_id=%s, stripe_subscription_id=%s, stripe_last_session_id=%s WHERE id=%s",
            (plano, customer_id, subscription_id, session_id, cliente_id),
        )

        # Adiciona à newsletter se ainda não estiver
        cur.execute("SELECT id FROM newsletter WHERE email = (SELECT email FROM clientes WHERE id = %s)", (cliente_id,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO newsletter (email, nome, token_descadastro)
                SELECT email, nome, %s FROM clientes WHERE id = %s
                ON CONFLICT (email) DO NOTHING
            """, (secrets.token_urlsafe(32), cliente_id))

        conn.commit()
        cur.close()
        conn.close()

    elif event["type"] == "customer.subscription.deleted":
        subscription_id = event["data"]["object"]["id"]
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            "UPDATE clientes SET plano=NULL, stripe_customer_id=NULL, stripe_subscription_id=NULL WHERE stripe_subscription_id=%s",
            (subscription_id,),
        )
        conn.commit()
        cur.close()
        conn.close()

    return "", 200


# ── Newsletter ────────────────────────────────────────────────────────────────

@app.route("/newsletter/cadastro", methods=["POST"])
def newsletter_cadastro():
    nome = request.form.get("nome", "").strip()
    email = request.form.get("email", "").strip().lower()

    if not email:
        flash("E-mail inválido.", "erro")
        return redirect(url_for("index") + "#newsletter")

    token = secrets.token_urlsafe(32)
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT id, ativo FROM newsletter WHERE email = %s", (email,))
    existente = cur.fetchone()

    if existente:
        if existente[1]:
            flash("Este e-mail já está cadastrado na newsletter.", "info")
        else:
            cur.execute("UPDATE newsletter SET ativo = TRUE WHERE email = %s", (email,))
            conn.commit()
            flash("Bem-vindo de volta! Você voltou a receber a newsletter.", "sucesso")
        cur.close()
        conn.close()
        return redirect(url_for("index") + "#newsletter")

    cur.execute(
        "INSERT INTO newsletter (email, nome, token_descadastro) VALUES (%s, %s, %s)",
        (email, nome, token),
    )
    conn.commit()
    cur.close()
    conn.close()

    enviar_email(email, "Você está no Radar Semanal do TenderSentinel!", f"""
    <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:2rem">
        <h1 style="color:#0f2444;font-family:Inter,sans-serif">TenderSentinel</h1>
        <p>Olá, <strong>{html_lib.escape(nome)}</strong>!</p>
        <p>Você está no <strong>Radar Semanal</strong>. Toda segunda às 9h você recebe as melhores oportunidades da semana.</p>
        <p style="color:#64748b;font-size:0.85rem;margin-top:1.5rem">
            Não quer mais receber?
            <a href="{request.host_url}newsletter/descadastro/{token}" style="color:#c9a84c">Clique aqui para se descadastrar.</a>
        </p>
    </div>
    """)
    flash("Cadastrado! Você receberá a newsletter toda segunda.", "sucesso")
    return redirect(url_for("index") + "#newsletter")


@app.route("/newsletter/descadastro/<token>")
def newsletter_descadastro(token):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("UPDATE newsletter SET ativo = FALSE WHERE token_descadastro = %s", (token,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Você foi removido da newsletter.", "info")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
