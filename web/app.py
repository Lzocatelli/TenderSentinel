from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.database import conectar
from app.alertas import enviar_email
import requests
import os
from datetime import date
from dotenv import load_dotenv

load_dotenv(override=False)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "licitabot2026")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class Cliente(UserMixin):
    def __init__(self, id, nome, email, palavras_chave):
        self.id = id
        self.nome = nome
        self.email = email
        self.palavras_chave = palavras_chave

@login_manager.user_loader
def load_user(user_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT id, nome, email, palavras_chave FROM clientes WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return Cliente(*row)
    return None

def contar_licitacoes_hoje():
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
    return total

@app.route("/")
def index():
    total_hoje = contar_licitacoes_hoje()
    return render_template("index.html", total_hoje=total_hoje)

@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form.get("nome")
        email = request.form.get("email")
        senha = request.form.get("senha")
        palavras = request.form.get("palavras_chave", "")
        palavras_lista = [p.strip() for p in palavras.split(",") if p.strip()]

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
        cur.execute("SELECT id, nome, email, palavras_chave, senha FROM clientes WHERE email = %s", (email,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row and check_password_hash(row[4], senha):
            cliente = Cliente(row[0], row[1], row[2], row[3])
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
    from flask import jsonify
    total = contar_licitacoes_hoje()
    return jsonify({"total": total})

if __name__ == "__main__":
    app.run(debug=True, port=5000)