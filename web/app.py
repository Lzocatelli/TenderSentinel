import csv
import hmac
import html as html_lib
import io
import logging
import os
import re
import secrets
import time
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import frontmatter
import markdown as md_lib
import requests
import stripe
from dotenv import load_dotenv
from flask import (Flask, Response, abort, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

from app.alertas import send_email
from app.config import (BASE_URL, DASHBOARD_LIMIT, CSV_EXPORT_LIMIT,
                        COUNTER_CACHE_TTL_MINUTES, TRIAL_PERIOD_DAYS,
                        VALID_SET_ASIDES, PLAN_LIMITS, FREE_KEYWORD_LIMIT,
                        get_plan_features)
from app.database import get_connection, release_connection
from app.score import calcular_score
from app.utils import format_currency, keyword_limit

load_dotenv(override=False)

logger = logging.getLogger("tendersentinel.web")

# ── App Configuration ────────────────────────────────────────────────────────

secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    secret_key = secrets.token_urlsafe(32)
    if os.getenv("FLASK_ENV") != "production":
        logger.warning(
            "SECRET_KEY not set; using temporary key. "
            "Set SECRET_KEY in environment for production."
        )

app = Flask(__name__)
app.secret_key = secret_key
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",
    SESSION_COOKIE_SAMESITE="Strict",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

# Template globals
@app.context_processor
def inject_now():
    return {"now": datetime.now()}

# HTTPS redirect for production (Q10)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

if os.getenv("FLASK_ENV") == "production":
    @app.before_request
    def redirect_to_https():
        if request.scheme == "http":
            url = request.url.replace("http://", "https://", 1)
            return redirect(url, code=301)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# ── Startup env var validation (Q40) ─────────────────────────────────────────

if os.getenv("FLASK_ENV") == "production":
    _required_env = ["DATABASE_URL", "SECRET_KEY", "STRIPE_SECRET_KEY"]
    _missing_env = [v for v in _required_env if not os.getenv(v)]
    if _missing_env:
        logger.error(f"Missing required environment variables: {', '.join(_missing_env)}")

# ── Rate Limiter (Q6, Q42) ──────────────────────────────────────────────────

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# ── Login Manager ────────────────────────────────────────────────────────────

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class Client(UserMixin):
    def __init__(self, id, name, email, keywords, plan=None, naics_codes=None, set_asides=None):
        self.id = id
        self.name = name
        self.email = email
        self.keywords = keywords or []
        self.plan = plan
        self.naics_codes = naics_codes or []
        self.set_asides = set_asides or []

    @property
    def keyword_limit(self):
        return keyword_limit(self.plan)

    @property
    def has_paid_plan(self):
        return self.plan in ("basico", "profissional", "agencia")

    # Legacy aliases
    @property
    def nome(self):
        return self.name

    @property
    def palavras_chave(self):
        return self.keywords

    @property
    def plano(self):
        return self.plan

    @property
    def plano_pago(self):
        return self.has_paid_plan

    @property
    def limite_palavras(self):
        return self.keyword_limit


@login_manager.user_loader
def load_user(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, nome, email, palavras_chave, plano, naics_codes, set_asides FROM clientes WHERE id = %s",
        (user_id,),
    )
    row = cur.fetchone()
    cur.close()
    release_connection(conn)
    return Client(*row) if row else None


# ── CSRF ─────────────────────────────────────────────────────────────────────

def _get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(16)
        session["_csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = _get_csrf_token


@app.before_request
def verify_csrf():
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if (request.endpoint or "") in {"api_counter", "health", "webhook_stripe",
                                     "blog_preview_api", "api_contador"}:
        return
    token_form = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    token_session = session.get("_csrf_token")
    if not token_form or not token_session or not hmac.compare_digest(token_form, token_session):
        abort(400)


# ── Jinja Filters ────────────────────────────────────────────────────────────

@app.template_filter("currency")
def currency_filter(value):
    if not value:
        return "—"
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "—"

# Legacy filter name
app.jinja_env.filters["moeda"] = currency_filter


# ── Counter Cache ────────────────────────────────────────────────────────────

_counter_cache = {"total": 0, "updated_at": None}


def count_opportunities_today():
    now = datetime.utcnow()
    if (_counter_cache["updated_at"] and
            now - _counter_cache["updated_at"] < timedelta(minutes=COUNTER_CACHE_TTL_MINUTES)):
        return _counter_cache["total"]

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM licitacoes WHERE data_publicacao = CURRENT_DATE")
        total = cur.fetchone()[0] or 0
        cur.close()
        release_connection(conn)
    except Exception:
        total = 0

    _counter_cache["total"] = total
    _counter_cache["updated_at"] = now
    return total


# ── Email validation helper (Q5) ─────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _is_valid_email(email):
    return bool(_EMAIL_RE.match(email))


# ── Manual search lock (Q28) ─────────────────────────────────────────────────

_search_lock = threading.Lock()


# ── Public Routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", total_hoje=count_opportunities_today())


@app.route("/api/contador")
def api_contador():
    return jsonify({"total": count_opportunities_today()})


@app.route("/health")
def health():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        release_connection(conn)
        return jsonify({"status": "ok", "database": "ok"}), 200
    except Exception:
        return jsonify({"status": "error", "database": "unavailable"}), 503


# ── Auth ─────────────────────────────────────────────────────────────────────

@app.route("/signup", methods=["GET", "POST"])
@limiter.limit("10/minute")
def signup():
    if request.method == "POST":
        name = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("senha", "")
        keywords_raw = request.form.get("palavras_chave", "")
        keywords_list = [p.strip() for p in keywords_raw.split(",") if p.strip()]

        # Validation (Q4, Q5)
        if not name or not email or not password:
            flash("Please fill in all fields.", "erro")
            return render_template("cadastro.html")

        if not _is_valid_email(email):
            flash("Please enter a valid email address.", "erro")
            return render_template("cadastro.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "erro")
            return render_template("cadastro.html")

        limit = keyword_limit(None)
        if len(keywords_list) > limit:
            flash(f"The free plan allows up to {limit} keyword. The first one was saved.", "info")
            keywords_list = keywords_list[:limit]

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM clientes WHERE email = %s", (email,))
        if cur.fetchone():
            flash("Email already registered.", "erro")
            cur.close()
            release_connection(conn)
            return render_template("cadastro.html")

        cur.execute(
            "INSERT INTO clientes (nome, email, senha, palavras_chave, ativo) VALUES (%s, %s, %s, %s, TRUE)",
            (name, email, generate_password_hash(password), keywords_list),
        )
        conn.commit()
        cur.close()
        release_connection(conn)

        send_email(email, "Welcome to TenderSentinel!", f"""
        <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:2rem">
            <h1 style="color:#0f2444;font-family:Inter,sans-serif">TenderSentinel</h1>
            <h2>Welcome, {html_lib.escape(name)}!</h2>
            <p>Your account is ready. You'll receive alerts for:
               <strong>{html_lib.escape(', '.join(keywords_list))}</strong></p>
        </div>
        """)
        flash("Account created! Check your email.", "sucesso")
        return redirect(url_for("login"))

    return render_template("cadastro.html")

# Legacy route alias
app.add_url_rule("/cadastro", endpoint="cadastro", view_func=signup)


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute")
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("senha", "")

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, nome, email, palavras_chave, senha, plano FROM clientes WHERE email = %s",
            (email,),
        )
        row = cur.fetchone()
        cur.close()
        release_connection(conn)

        if row and check_password_hash(row[4], password):
            login_user(Client(row[0], row[1], row[2], row[3], row[5]), remember=True)
            return redirect(url_for("dashboard"))

        flash("Incorrect email or password.", "erro")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ── Dashboard ────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    paid = current_user.has_paid_plan
    valor_min = request.args.get("valor_min", type=float) if paid else None
    uf = request.args.get("uf", "").strip().upper() or None if paid else None

    keywords = current_user.keywords or []
    if not keywords:
        return render_template(
            "dashboard.html",
            licitacoes=[],
            cliente=current_user,
            show_score=paid,
            valor_min=valor_min or "",
            uf_selecionada=uf or "",
        )

    filters_sql = " OR ".join(["l.objeto ILIKE %s"] * len(keywords))
    params_kw = [f"%{kw}%" for kw in keywords]

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT l.orgao, l.objeto, l.valor, l.data_publicacao, l.link, l.naics_code, l.set_aside
        FROM licitacoes l
        WHERE ({filters_sql})
          AND (%s IS NULL OR l.valor >= %s)
          AND (%s IS NULL OR l.uf = %s)
        ORDER BY l.data_publicacao DESC
        LIMIT {DASHBOARD_LIMIT}
    """, params_kw + [valor_min, valor_min, uf, uf])

    rows = cur.fetchall()
    cur.close()
    release_connection(conn)

    if paid:
        licitacoes = []
        for row in rows:
            agency, title, value, posted, link, naics_code, set_aside = row
            score = calcular_score(
                title, keywords, value,
                naics_code=naics_code,
                user_naics=current_user.naics_codes,
                set_aside=set_aside,
                user_set_asides=current_user.set_asides,
            )
            licitacoes.append((agency, title, value, posted, link, score))
        licitacoes.sort(key=lambda x: x[5], reverse=True)
    else:
        licitacoes = [row[:5] for row in rows]

    return render_template(
        "dashboard.html",
        licitacoes=licitacoes,
        cliente=current_user,
        show_score=paid,
        valor_min=valor_min or "",
        uf_selecionada=uf or "",
    )


# ── Manual Search ────────────────────────────────────────────────────────────

@app.route("/search-now", methods=["POST"])
@login_required
def search_now():
    if not current_user.has_paid_plan:
        flash("Manual search is available on paid plans. You'll receive automatic alerts at 9am.", "info")
        return redirect(url_for("dashboard"))

    client_id = current_user.id
    client_email = current_user.email
    client_keywords = current_user.keywords

    def _run(cid, cemail, ckeywords):
        if not _search_lock.acquire(blocking=False):
            logger.info("Manual search already running, skipping")
            return

        try:
            from app.scraper import fetch_opportunities, save_opportunities
            opportunities = fetch_opportunities()
            save_opportunities(opportunities)

            conn = get_connection()
            cur = conn.cursor()
            try:
                filters = " OR ".join(["l.objeto ILIKE %s"] * len(ckeywords))
                params = [f"%{kw}%" for kw in ckeywords]
                cur.execute(f"""
                    SELECT l.id, l.sam_id, l.orgao, l.objeto, l.valor, l.link
                    FROM licitacoes l
                    WHERE {filters}
                """, params)
                candidates = cur.fetchall()

                ids = [c[0] for c in candidates]
                cur.execute(
                    "SELECT licitacao_id FROM alertas_enviados WHERE cliente_id = %s AND licitacao_id = ANY(%s)",
                    (cid, ids),
                )
                already_sent = {row[0] for row in cur.fetchall()}
                new_matches = [c for c in candidates if c[0] not in already_sent]

                if new_matches:
                    from app.alertas import _build_opportunity_card
                    cards = "".join(_build_opportunity_card(m[2], m[3], m[4], m[5]) for m in new_matches)
                    count = len(new_matches)
                    plural = "opportunity" if count == 1 else "opportunities"
                    body = f"""
                    <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:2rem">
                        <h1 style="color:#0f2444;font-family:Inter,sans-serif">TenderSentinel</h1>
                        <p style="color:#64748b;margin-bottom:1.5rem">{count} new {plural} found!</p>
                        {cards}
                    </div>
                    """
                    send_email(cemail, f"TenderSentinel — {count} new {plural} found!", body)
                    cur.executemany(
                        "INSERT INTO alertas_enviados (cliente_id, licitacao_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        [(cid, m[0]) for m in new_matches],
                    )

                conn.commit()
            except Exception as e:
                logger.error(f"Manual search error: {e}")
                conn.rollback()
            finally:
                cur.close()
                release_connection(conn)
        finally:
            _search_lock.release()

    threading.Thread(target=_run, args=(client_id, client_email, client_keywords), daemon=True).start()
    flash("Search started! If we find new matches, you'll receive an email shortly.", "info")
    return redirect(url_for("dashboard"))

# Legacy route alias
app.add_url_rule("/buscar-agora", endpoint="buscar_agora", view_func=search_now, methods=["POST"])


# ── My Account ───────────────────────────────────────────────────────────────

@app.route("/my-account", methods=["GET", "POST"])
@login_required
def my_account():
    renewal_date = None
    if current_user.has_paid_plan:
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT stripe_subscription_id FROM clientes WHERE id = %s", (current_user.id,))
            row = cur.fetchone()
            cur.close()
            release_connection(conn)
            if row and row[0]:
                sub = stripe.Subscription.retrieve(row[0])
                renewal_date = datetime.fromtimestamp(sub.current_period_end).strftime("%B %d, %Y")
        except Exception:
            pass

    if request.method == "POST":
        current_password = request.form.get("senha_atual", "")
        new_password = request.form.get("nova_senha", "")
        confirm_password = request.form.get("confirmar_senha", "")

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT senha FROM clientes WHERE id = %s", (current_user.id,))
        row = cur.fetchone()

        if not row or not check_password_hash(row[0], current_password):
            flash("Current password is incorrect.", "erro")
        elif len(new_password) < 8:
            flash("New password must be at least 8 characters.", "erro")
        elif new_password != confirm_password:
            flash("Passwords do not match.", "erro")
        else:
            cur.execute(
                "UPDATE clientes SET senha = %s WHERE id = %s",
                (generate_password_hash(new_password), current_user.id),
            )
            conn.commit()
            flash("Password updated successfully!", "sucesso")

        cur.close()
        release_connection(conn)

    return render_template("minha_conta.html", cliente=current_user, renovacao=renewal_date)

# Legacy route alias
app.add_url_rule("/minha-conta", endpoint="minha_conta", view_func=my_account, methods=["GET", "POST"])


# ── CSV Export ───────────────────────────────────────────────────────────────

@app.route("/export-csv")
@login_required
def export_csv():
    if current_user.plan not in ("profissional", "agencia"):
        flash("CSV export is available on Professional and Agency plans.", "info")
        return redirect(url_for("dashboard"))

    valor_min = request.args.get("valor_min", type=float)
    uf = request.args.get("uf", "").strip().upper() or None

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT l.orgao, l.objeto, l.valor, l.data_publicacao, l.link, l.uf
        FROM licitacoes l
        JOIN alertas_enviados ae ON ae.licitacao_id = l.id
        WHERE ae.cliente_id = %s
          AND (%s IS NULL OR l.valor >= %s)
          AND (%s IS NULL OR l.uf = %s)
        ORDER BY ae.enviado_em DESC
        LIMIT {CSV_EXPORT_LIMIT}
    """, [current_user.id, valor_min, valor_min, uf, uf])

    rows = cur.fetchall()
    cur.close()
    release_connection(conn)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Agency", "Title", "Value (USD)", "Posted Date", "Link", "State"])
    for row in rows:
        agency, title, value, posted, link, state = row
        writer.writerow([agency, title, format_currency(value), posted, link, state or ""])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=contracts.csv"},
    )


# ── Edit Keywords ────────────────────────────────────────────────────────────

@app.route("/edit-keywords", methods=["GET", "POST"])
@login_required
def edit_keywords():
    if request.method == "POST":
        keywords_list = [p.strip() for p in request.form.get("palavras_chave", "").split(",") if p.strip()]

        limit = current_user.keyword_limit
        if limit is not None and len(keywords_list) > limit:
            flash(f"Your plan allows up to {limit} keywords. The first {limit} were saved.", "info")
            keywords_list = keywords_list[:limit]

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE clientes SET palavras_chave = %s WHERE id = %s", (keywords_list, current_user.id))
        conn.commit()
        cur.close()
        release_connection(conn)
        flash("Keywords updated successfully!", "sucesso")
        return redirect(url_for("dashboard"))

    return render_template("editar_palavras.html", cliente=current_user)

# Legacy route alias
app.add_url_rule("/editar-palavras", endpoint="editar_palavras", view_func=edit_keywords, methods=["GET", "POST"])


# ── Edit Profile (NAICS / Set-Asides) ────────────────────────────────────────

@app.route("/edit-profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        naics_raw = request.form.get("naics_codes", "")
        naics_list = [c.strip() for c in naics_raw.replace(",", " ").split() if c.strip().isdigit()]

        set_asides_list = [
            s for s in request.form.getlist("set_asides")
            if s.upper() in VALID_SET_ASIDES
        ]

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE clientes SET naics_codes = %s, set_asides = %s WHERE id = %s",
            (naics_list or None, set_asides_list or None, current_user.id),
        )
        conn.commit()
        cur.close()
        release_connection(conn)
        flash("Profile updated successfully!", "sucesso")
        return redirect(url_for("dashboard"))

    return render_template("editar_perfil.html", cliente=current_user, valid_set_asides=sorted(VALID_SET_ASIDES))

# Legacy route alias
app.add_url_rule("/editar-perfil", endpoint="editar_perfil", view_func=edit_profile, methods=["GET", "POST"])


# ── Stripe Subscription ─────────────────────────────────────────────────────

@app.route("/subscribe/<plan>")
@login_required
def subscribe(plan):
    if current_user.has_paid_plan:
        flash("You already have an active subscription. To change plans, cancel the current one first.", "info")
        return redirect(url_for("dashboard"))

    period = request.args.get("periodo", "mensal")
    prices = {
        "basico":               os.getenv("STRIPE_PRICE_BASICO"),
        "profissional":         os.getenv("STRIPE_PRICE_PROFISSIONAL"),
        "agencia":              os.getenv("STRIPE_PRICE_AGENCIA"),
        "basico_anual":         os.getenv("STRIPE_PRICE_BASICO_ANUAL"),
        "profissional_anual":   os.getenv("STRIPE_PRICE_PROFISSIONAL_ANUAL"),
        "agencia_anual":        os.getenv("STRIPE_PRICE_AGENCIA_ANUAL"),
    }
    price_id = prices.get(f"{plan}_anual" if period == "anual" else plan)

    if not price_id:
        flash("Invalid plan.", "erro")
        return redirect(url_for("index"))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT stripe_customer_id FROM clientes WHERE id = %s", (current_user.id,))
    row = cur.fetchone()
    cur.close()
    release_connection(conn)
    customer_id = row[0] if row and row[0] else None

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        customer=customer_id,
        customer_email=None if customer_id else current_user.email,
        metadata={"cliente_id": current_user.id},
        subscription_data={"trial_period_days": TRIAL_PERIOD_DAYS},
        success_url=request.host_url + "payment/success",
        cancel_url=request.host_url + "payment/cancelled",
    )
    return redirect(checkout_session.url, code=303)

# Legacy route alias
app.add_url_rule("/assinar/<plano>", endpoint="assinar", view_func=subscribe)


@app.route("/manage-subscription")
@login_required
def manage_subscription():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT stripe_customer_id FROM clientes WHERE id = %s", (current_user.id,))
    row = cur.fetchone()
    cur.close()
    release_connection(conn)

    if not row or not row[0]:
        flash("No subscription found.", "info")
        return redirect(url_for("dashboard"))

    try:
        portal = stripe.billing_portal.Session.create(
            customer=row[0],
            return_url=request.host_url + "dashboard",
        )
        return redirect(portal.url, code=303)
    except (stripe.InvalidRequestError, stripe.error.InvalidRequestError):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE clientes SET stripe_customer_id = NULL, stripe_subscription_id = NULL, plano = NULL WHERE id = %s",
            (current_user.id,),
        )
        conn.commit()
        cur.close()
        release_connection(conn)
        flash("Subscription not found. Your plan was reset — please subscribe again.", "info")
        return redirect(url_for("index"))

# Legacy route alias
app.add_url_rule("/gerenciar-assinatura", endpoint="gerenciar_assinatura", view_func=manage_subscription)


@app.route("/payment/success")
@login_required
def payment_success():
    return render_template("pagamento_sucesso.html")

# Legacy alias
app.add_url_rule("/pagamento/sucesso", endpoint="pagamento_sucesso", view_func=payment_success)


@app.route("/payment/cancelled")
@login_required
def payment_cancelled():
    flash("Payment cancelled. No charges were made.", "info")
    return redirect(url_for("index"))

# Legacy alias
app.add_url_rule("/pagamento/cancelado", endpoint="pagamento_cancelado", view_func=payment_cancelled)


# ── Stripe Webhook ───────────────────────────────────────────────────────────

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
        client_id = sess["metadata"].get("cliente_id")
        if not client_id:
            return "", 200

        subscription_id = sess.get("subscription")
        customer_id = sess.get("customer")

        conn = get_connection()
        cur = conn.cursor()

        # Idempotency check
        cur.execute("SELECT stripe_last_session_id FROM clientes WHERE id = %s", (client_id,))
        row = cur.fetchone()
        if row and row[0] == session_id:
            cur.close()
            release_connection(conn)
            return "", 200

        cur.execute(
            "SELECT id FROM clientes WHERE id = %s AND (stripe_customer_id = %s OR stripe_customer_id IS NULL)",
            (client_id, customer_id),
        )
        if not cur.fetchone():
            cur.close()
            release_connection(conn)
            return "", 200

        plan = "basico"
        try:
            for item in stripe.checkout.Session.list_line_items(session_id).data:
                pid = item.price.id
                if pid in (os.getenv("STRIPE_PRICE_PROFISSIONAL"), os.getenv("STRIPE_PRICE_PROFISSIONAL_ANUAL")):
                    plan = "profissional"
                elif pid in (os.getenv("STRIPE_PRICE_AGENCIA"), os.getenv("STRIPE_PRICE_AGENCIA_ANUAL")):
                    plan = "agencia"
        except Exception:
            pass

        cur.execute(
            "UPDATE clientes SET plano=%s, stripe_customer_id=%s, stripe_subscription_id=%s, stripe_last_session_id=%s WHERE id=%s",
            (plan, customer_id, subscription_id, session_id, client_id),
        )

        # Add to newsletter if not already
        cur.execute("SELECT id FROM newsletter WHERE email = (SELECT email FROM clientes WHERE id = %s)", (client_id,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO newsletter (email, nome, token_descadastro, confirmed)
                SELECT email, nome, %s, TRUE FROM clientes WHERE id = %s
                ON CONFLICT (email) DO NOTHING
            """, (secrets.token_urlsafe(32), client_id))

        conn.commit()
        cur.close()
        release_connection(conn)

    elif event["type"] == "customer.subscription.deleted":
        subscription_id = event["data"]["object"]["id"]
        conn = get_connection()
        cur = conn.cursor()

        # Idempotency check (Q9)
        cur.execute("SELECT id FROM clientes WHERE stripe_subscription_id = %s AND plano IS NOT NULL", (subscription_id,))
        if not cur.fetchone():
            cur.close()
            release_connection(conn)
            return "", 200

        cur.execute(
            "UPDATE clientes SET plano=NULL, stripe_customer_id=NULL, stripe_subscription_id=NULL WHERE stripe_subscription_id=%s",
            (subscription_id,),
        )
        conn.commit()
        cur.close()
        release_connection(conn)

    return "", 200


# ── Newsletter ───────────────────────────────────────────────────────────────

@app.route("/newsletter/signup", methods=["POST"])
@limiter.limit("5/minute")
def newsletter_signup():
    name = request.form.get("nome", "").strip()
    email = request.form.get("email", "").strip().lower()

    if not email or not _is_valid_email(email):
        flash("Please enter a valid email address.", "erro")
        return redirect(url_for("index") + "#newsletter")

    token = secrets.token_urlsafe(32)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, ativo, confirmed FROM newsletter WHERE email = %s", (email,))
    existing = cur.fetchone()

    if existing:
        if existing[1] and existing[2]:
            flash("This email is already subscribed to the newsletter.", "info")
        elif existing[1] and not existing[2]:
            flash("Check your email to confirm your subscription.", "info")
        else:
            cur.execute("UPDATE newsletter SET ativo = TRUE, confirmed = FALSE, token_descadastro = %s WHERE email = %s", (token, email))
            conn.commit()
            # Send confirmation email
            send_email(email, "Confirm your TenderSentinel newsletter subscription", f"""
            <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:2rem">
                <h1 style="color:#0f2444;font-family:Inter,sans-serif">TenderSentinel</h1>
                <p>Hi, <strong>{html_lib.escape(name)}</strong>!</p>
                <p>Click below to confirm your newsletter subscription:</p>
                <p><a href="{BASE_URL}/newsletter/confirm/{token}"
                   style="display:inline-block;background:#0f1f3d;color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;padding:12px 28px;border-radius:8px">
                   Confirm subscription
                </a></p>
            </div>
            """)
            flash("Welcome back! Check your email to confirm.", "sucesso")
        cur.close()
        release_connection(conn)
        return redirect(url_for("index") + "#newsletter")

    cur.execute(
        "INSERT INTO newsletter (email, nome, token_descadastro, confirmed) VALUES (%s, %s, %s, FALSE)",
        (email, name, token),
    )
    conn.commit()
    cur.close()
    release_connection(conn)

    # Double opt-in confirmation email (Q7)
    send_email(email, "Confirm your TenderSentinel newsletter subscription", f"""
    <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:2rem">
        <h1 style="color:#0f2444;font-family:Inter,sans-serif">TenderSentinel</h1>
        <p>Hi, <strong>{html_lib.escape(name)}</strong>!</p>
        <p>Click below to confirm your newsletter subscription:</p>
        <p><a href="{BASE_URL}/newsletter/confirm/{token}"
           style="display:inline-block;background:#0f1f3d;color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;padding:12px 28px;border-radius:8px">
           Confirm subscription
        </a></p>
        <p style="color:#64748b;font-size:0.85rem;margin-top:1.5rem">
            If you didn't request this, just ignore this email.
        </p>
    </div>
    """)
    flash("Check your email to confirm your subscription!", "sucesso")
    return redirect(url_for("index") + "#newsletter")

# Legacy route alias
app.add_url_rule("/newsletter/cadastro", endpoint="newsletter_cadastro", view_func=newsletter_signup, methods=["POST"])


@app.route("/newsletter/confirm/<token>")
def newsletter_confirm(token):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE newsletter SET confirmed = TRUE WHERE token_descadastro = %s AND ativo = TRUE", (token,))
    updated = cur.rowcount
    conn.commit()
    cur.close()
    release_connection(conn)

    if updated:
        flash("Subscription confirmed! You'll receive our weekly digest every Monday.", "sucesso")
    else:
        flash("Invalid or expired confirmation link.", "erro")
    return redirect(url_for("index"))


@app.route("/newsletter/unsubscribe/<token>")
def newsletter_unsubscribe(token):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE newsletter SET ativo = FALSE WHERE token_descadastro = %s", (token,))
    conn.commit()
    cur.close()
    release_connection(conn)
    flash("You've been unsubscribed from the newsletter.", "info")
    return redirect(url_for("index"))

# Legacy route alias
app.add_url_rule("/newsletter/descadastro/<token>", endpoint="newsletter_descadastro", view_func=newsletter_unsubscribe)


# ── Planos page ──────────────────────────────────────────────────────────────

@app.route("/planos")
def planos():
    return render_template("planos.html")


# ── Blog ─────────────────────────────────────────────────────────────────────

BLOG_DIR = Path(__file__).parent.parent / "content" / "blog"

_blog_cache = {"posts": None, "loaded_at": 0}
_BLOG_CACHE_TTL = 300  # 5 minutes


def _load_posts(limit=None):
    """Load and sort all blog posts from content/blog/*.md with caching."""
    now = time.time()
    if _blog_cache["posts"] is not None and (now - _blog_cache["loaded_at"]) < _BLOG_CACHE_TTL:
        posts = _blog_cache["posts"]
        return posts[:limit] if limit else posts

    posts = []
    if not BLOG_DIR.exists():
        return posts
    for path in BLOG_DIR.glob("*.md"):
        try:
            post = frontmatter.load(str(path))
            slug = path.stem
            posts.append({
                "slug": slug,
                "title": post.get("title", slug),
                "description": post.get("description", ""),
                "date": post.get("date"),
                "tags": post.get("tags", []),
                "thumbnail": post.get("thumbnail", ""),
                "author": post.get("author", "TenderSentinel"),
            })
        except Exception:
            continue
    posts.sort(key=lambda p: p["date"] or date.min, reverse=True)
    _blog_cache["posts"] = posts
    _blog_cache["loaded_at"] = now
    return posts[:limit] if limit else posts


@app.route("/api/blog/preview")
def blog_preview_api():
    posts = _load_posts(limit=3)
    return jsonify([{
        "slug": p["slug"],
        "title": p["title"],
        "description": p["description"],
        "date": str(p["date"]) if p["date"] else "",
        "tags": p["tags"],
        "thumbnail": p["thumbnail"],
    } for p in posts])


@app.route("/blog")
def blog_index():
    posts = _load_posts()
    return render_template("blog/index.html", posts=posts)


@app.route("/blog/<slug>")
def blog_post(slug):
    path = BLOG_DIR / f"{slug}.md"
    if not path.exists():
        abort(404)
    post = frontmatter.load(str(path))
    content_html = md_lib.markdown(
        post.content,
        extensions=["extra", "toc", "nl2br"],
    )
    all_posts = _load_posts()

    # Related articles by tag match (Q47)
    current_tags = set(post.get("tags", []))
    other_posts = [p for p in all_posts if p["slug"] != slug]
    if current_tags:
        other_posts.sort(
            key=lambda p: len(current_tags & set(p.get("tags", []))),
            reverse=True,
        )
    related = other_posts[:3]

    base_url = BASE_URL
    return render_template(
        "blog/post.html",
        post=post,
        slug=slug,
        content_html=content_html,
        related=related,
        base_url=base_url,
    )


# ── SEO ──────────────────────────────────────────────────────────────────────

@app.route("/sitemap.xml")
def sitemap():
    base_url = BASE_URL
    today = date.today().isoformat()
    posts = _load_posts()
    urls = [
        {"loc": base_url + "/", "lastmod": today, "priority": "1.0"},
        {"loc": base_url + "/blog", "lastmod": today, "priority": "0.8"},
        {"loc": base_url + "/planos", "lastmod": today, "priority": "0.7"},
        {"loc": base_url + "/signup", "lastmod": today, "priority": "0.6"},
    ]
    for p in posts:
        urls.append({
            "loc": f"{base_url}/blog/{p['slug']}",
            "lastmod": str(p["date"]) if p["date"] else today,
            "priority": "0.9",
        })
    xml = render_template("sitemap.xml", urls=urls)
    return Response(xml, mimetype="application/xml")


@app.route("/robots.txt")
def robots_txt():
    base_url = BASE_URL
    content = f"""User-agent: *
Allow: /

Sitemap: {base_url}/sitemap.xml
"""
    return Response(content, mimetype="text/plain")


# ── Company Profile API ──────────────────────────────────────────────────────

@app.route("/api/v1/profile", methods=["GET", "POST"])
@login_required
def api_profile():
    conn = get_connection()
    cur = conn.cursor()
    try:
        if request.method == "GET":
            cur.execute("""
                SELECT id, company_name, cage_code, uei, sam_registered,
                       employee_count_range, annual_revenue_range, years_in_business
                FROM company_profiles WHERE user_id = %s
            """, (current_user.id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"profile": None})

            profile_id = row[0]

            cur.execute("SELECT naics_code, is_primary, proficiency FROM company_naics WHERE company_profile_id = %s", (profile_id,))
            naics = [{"code": r[0], "is_primary": r[1], "proficiency": r[2]} for r in cur.fetchall()]

            cur.execute("SELECT certification_type, certification_number, expiration_date FROM company_certifications WHERE company_profile_id = %s", (profile_id,))
            certs = [{"type": r[0], "number": r[1], "expiration": str(r[2]) if r[2] else None} for r in cur.fetchall()]

            cur.execute("SELECT keyword, weight FROM company_keywords WHERE company_profile_id = %s", (profile_id,))
            keywords = [{"keyword": r[0], "weight": float(r[1])} for r in cur.fetchall()]

            cur.execute("SELECT contract_number, agency, naics_code, contract_value, description FROM company_past_performance WHERE company_profile_id = %s", (profile_id,))
            past_perf = [{"contract_number": r[0], "agency": r[1], "naics_code": r[2], "value": float(r[3]) if r[3] else None, "description": r[4]} for r in cur.fetchall()]

            return jsonify({
                "profile": {
                    "company_name": row[1], "cage_code": row[2], "uei": row[3],
                    "sam_registered": row[4], "employee_count_range": row[5],
                    "annual_revenue_range": row[6], "years_in_business": row[7],
                    "naics_codes": naics, "certifications": certs,
                    "keywords": keywords, "past_performance": past_perf,
                },
            })

        # POST: create or update profile
        data = request.get_json(silent=True) or {}
        cur.execute("""
            INSERT INTO company_profiles
                (user_id, company_name, cage_code, uei, sam_registered,
                 employee_count_range, annual_revenue_range, years_in_business)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                cage_code = EXCLUDED.cage_code,
                uei = EXCLUDED.uei,
                sam_registered = EXCLUDED.sam_registered,
                employee_count_range = EXCLUDED.employee_count_range,
                annual_revenue_range = EXCLUDED.annual_revenue_range,
                years_in_business = EXCLUDED.years_in_business,
                updated_at = NOW()
            RETURNING id
        """, (
            current_user.id,
            data.get("company_name"),
            data.get("cage_code"),
            data.get("uei"),
            data.get("sam_registered", False),
            data.get("employee_count_range"),
            data.get("annual_revenue_range"),
            data.get("years_in_business"),
        ))
        profile_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({"ok": True, "profile_id": profile_id})
    finally:
        cur.close()
        release_connection(conn)


@app.route("/api/v1/profile/naics", methods=["PUT"])
@login_required
def api_profile_naics():
    data = request.get_json(silent=True) or {}
    naics_list = data.get("naics_codes", [])

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM company_profiles WHERE user_id = %s", (current_user.id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Create a company profile first"}), 400
        profile_id = row[0]

        cur.execute("DELETE FROM company_naics WHERE company_profile_id = %s", (profile_id,))
        for n in naics_list:
            cur.execute("""
                INSERT INTO company_naics (company_profile_id, naics_code, is_primary, proficiency)
                VALUES (%s, %s, %s, %s)
            """, (profile_id, n["code"], n.get("is_primary", False), n.get("proficiency", "experienced")))

        conn.commit()

        # Trigger rescore in background
        from app.services.scoring_pipeline import rescore_user_opportunities
        t = threading.Thread(target=rescore_user_opportunities, args=(current_user.id,), daemon=True)
        t.start()

        return jsonify({"ok": True})
    finally:
        cur.close()
        release_connection(conn)


@app.route("/api/v1/profile/certifications", methods=["PUT"])
@login_required
def api_profile_certs():
    data = request.get_json(silent=True) or {}
    certs = data.get("certifications", [])

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM company_profiles WHERE user_id = %s", (current_user.id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Create a company profile first"}), 400
        profile_id = row[0]

        cur.execute("DELETE FROM company_certifications WHERE company_profile_id = %s", (profile_id,))
        for c in certs:
            cur.execute("""
                INSERT INTO company_certifications (company_profile_id, certification_type, certification_number, expiration_date)
                VALUES (%s, %s, %s, %s)
            """, (profile_id, c["type"], c.get("number"), c.get("expiration_date")))

        conn.commit()

        from app.services.scoring_pipeline import rescore_user_opportunities
        t = threading.Thread(target=rescore_user_opportunities, args=(current_user.id,), daemon=True)
        t.start()

        return jsonify({"ok": True})
    finally:
        cur.close()
        release_connection(conn)


@app.route("/api/v1/profile/keywords", methods=["PUT"])
@login_required
def api_profile_keywords():
    data = request.get_json(silent=True) or {}
    keywords = data.get("keywords", [])

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM company_profiles WHERE user_id = %s", (current_user.id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Create a company profile first"}), 400
        profile_id = row[0]

        cur.execute("DELETE FROM company_keywords WHERE company_profile_id = %s", (profile_id,))
        for kw in keywords:
            weight = max(0.1, min(2.0, float(kw.get("weight", 1.0))))
            cur.execute("""
                INSERT INTO company_keywords (company_profile_id, keyword, weight)
                VALUES (%s, %s, %s)
            """, (profile_id, kw["keyword"], weight))

        conn.commit()

        from app.services.scoring_pipeline import rescore_user_opportunities
        t = threading.Thread(target=rescore_user_opportunities, args=(current_user.id,), daemon=True)
        t.start()

        return jsonify({"ok": True})
    finally:
        cur.close()
        release_connection(conn)


@app.route("/api/v1/profile/past-performance", methods=["POST"])
@login_required
def api_profile_past_perf():
    features = get_plan_features(current_user.plano)
    pp_limit = features.get("past_performance_limit", 0)
    if pp_limit == 0:
        return jsonify({"error": "Past performance tracking requires Professional plan", "upgrade": True}), 403

    data = request.get_json(silent=True) or {}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM company_profiles WHERE user_id = %s", (current_user.id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Create a company profile first"}), 400
        profile_id = row[0]

        cur.execute("""
            INSERT INTO company_past_performance
                (company_profile_id, contract_number, agency, naics_code, contract_value, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            profile_id,
            data.get("contract_number"),
            data.get("agency"),
            data.get("naics_code"),
            data.get("contract_value"),
            data.get("description"),
        ))
        pp_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({"ok": True, "id": pp_id})
    finally:
        cur.close()
        release_connection(conn)


# ── Match Score & Opportunity API ────────────────────────────────────────────

@app.route("/api/v1/opportunities")
@login_required
def api_opportunities():
    scored = request.args.get("scored") == "true"

    conn = get_connection()
    cur = conn.cursor()
    try:
        if scored:
            cur.execute("""
                SELECT l.id, l.sam_id, l.orgao, l.objeto, l.valor, l.deadline,
                       l.naics_code, l.set_aside, l.link,
                       m.overall_score, m.naics_score, m.setaside_score,
                       m.keyword_score, m.size_fit_score, m.past_perf_score,
                       l.estimated_value_low, l.estimated_value_mid, l.estimated_value_high,
                       l.estimation_confidence
                FROM licitacoes l
                LEFT JOIN opportunity_match_scores m
                    ON m.opportunity_id = l.id AND m.user_id = %s
                WHERE l.deadline >= CURRENT_DATE OR l.deadline IS NULL
                ORDER BY COALESCE(m.overall_score, 0) DESC
                LIMIT 100
            """, (current_user.id,))
        else:
            cur.execute("""
                SELECT id, sam_id, orgao, objeto, valor, deadline,
                       naics_code, set_aside, link,
                       NULL, NULL, NULL, NULL, NULL, NULL,
                       estimated_value_low, estimated_value_mid, estimated_value_high,
                       estimation_confidence
                FROM licitacoes
                WHERE deadline >= CURRENT_DATE OR deadline IS NULL
                ORDER BY data_publicacao DESC
                LIMIT 100
            """)

        opps = []
        for row in cur.fetchall():
            opp = {
                "id": row[0], "sam_id": row[1], "agency": row[2],
                "title": row[3],
                "value": float(row[4]) if row[4] else None,
                "deadline": str(row[5]) if row[5] else None,
                "naics_code": row[6], "set_aside": row[7], "link": row[8],
            }
            if scored:
                opp["match_score"] = {
                    "overall": float(row[9]) if row[9] else None,
                    "naics": float(row[10]) if row[10] else None,
                    "setaside": float(row[11]) if row[11] else None,
                    "keyword": float(row[12]) if row[12] else None,
                    "size_fit": float(row[13]) if row[13] else None,
                    "past_perf": float(row[14]) if row[14] else None,
                }
            opp["estimated_value"] = {
                "low": float(row[15]) if row[15] else None,
                "mid": float(row[16]) if row[16] else None,
                "high": float(row[17]) if row[17] else None,
                "confidence": row[18],
            }
            opps.append(opp)

        return jsonify({"opportunities": opps})
    finally:
        cur.close()
        release_connection(conn)


@app.route("/api/v1/opportunities/<int:opp_id>/score")
@login_required
def api_opportunity_score(opp_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT overall_score, naics_score, setaside_score,
                   keyword_score, size_fit_score, past_perf_score, scored_at
            FROM opportunity_match_scores
            WHERE user_id = %s AND opportunity_id = %s
        """, (current_user.id, opp_id))
        row = cur.fetchone()
        if not row:
            return jsonify({"score": None})

        features = get_plan_features(current_user.plano)
        score_data = {
            "overall": float(row[0]),
            "naics": float(row[1]),
            "setaside": float(row[2]),
            "scored_at": str(row[6]),
        }
        # Full breakdown only for Professional+
        if features["score_factors"] >= 5:
            score_data["keyword"] = float(row[3])
            score_data["size_fit"] = float(row[4])
            score_data["past_perf"] = float(row[5])
        else:
            score_data["upgrade_hint"] = "Upgrade to Professional for full 5-factor scoring"

        return jsonify({
            "score": score_data
        })
    finally:
        cur.close()
        release_connection(conn)


@app.route("/api/v1/opportunities/rescore", methods=["POST"])
@login_required
def api_rescore():
    from app.services.scoring_pipeline import rescore_user_opportunities
    t = threading.Thread(target=rescore_user_opportunities, args=(current_user.id,), daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Rescoring started"})


# ── Decision / Pipeline API ──────────────────────────────────────────────────

@app.route("/api/v1/opportunities/<int:opp_id>/decision", methods=["PUT"])
@login_required
def api_decision(opp_id):
    data = request.get_json(silent=True) or {}
    decision = data.get("decision")
    if decision not in ("go", "consider", "skip"):
        return jsonify({"error": "Invalid decision. Must be go, consider, or skip."}), 400

    from app.services.auto_classifier import upsert_decision
    upsert_decision(
        user_id=current_user.id,
        opportunity_id=opp_id,
        decision=decision,
        auto_classified=False,
        notes=data.get("notes"),
    )
    return jsonify({"ok": True})


@app.route("/api/v1/pipeline")
@login_required
def api_pipeline():
    features = get_plan_features(current_user.plano)
    if not features.get("pipeline_dashboard"):
        return jsonify({"error": "Pipeline dashboard requires Basic plan or higher", "upgrade": True}), 403
    from app.services.auto_classifier import get_pipeline
    pipeline = get_pipeline(current_user.id)
    return jsonify(pipeline)


@app.route("/api/v1/pipeline/stats")
@login_required
def api_pipeline_stats():
    features = get_plan_features(current_user.plano)
    if not features.get("pipeline_dashboard"):
        return jsonify({"error": "Pipeline stats require Basic plan or higher", "upgrade": True}), 403
    from app.services.auto_classifier import get_pipeline_stats
    stats = get_pipeline_stats(current_user.id)
    return jsonify(stats)


# ── Profile Setup Page ───────────────────────────────────────────────────────

@app.route("/dashboard/profile")
@login_required
def dashboard_profile():
    return render_template("dashboard_profile.html")


# ── Pipeline Dashboard Page ──────────────────────────────────────────────────

@app.route("/dashboard/pipeline")
@login_required
def dashboard_pipeline():
    return render_template("dashboard_pipeline.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
