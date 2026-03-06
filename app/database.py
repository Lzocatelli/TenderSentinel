import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()


def conectar():
    """
    Abre conexão com o Postgres.

    - Em produção (ex.: Railway), prioriza DATABASE_URL se disponível.
    - Caso contrário, usa as variáveis discretas DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD.
    Em ambos os casos, falha com mensagem clara se algo essencial estiver faltando.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        try:
            return psycopg2.connect(database_url)
        except Exception as e:
            raise RuntimeError(
                "Falha ao conectar ao banco usando DATABASE_URL. "
                "Verifique se a variável está correta na Railway."
            ) from e

    required_vars = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise RuntimeError(
            "Variáveis de ambiente de banco de dados ausentes ou vazias: "
            + ", ".join(missing)
            + ". Defina-as no .env (ambiente local) ou na configuração da Railway."
        )

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )

def criar_tabelas():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS licitacoes (
            id SERIAL PRIMARY KEY,
            pncp_id TEXT UNIQUE,
            orgao TEXT,
            objeto TEXT,
            valor NUMERIC,
            data_publicacao DATE,
            link TEXT,
            criado_em TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            nome TEXT,
            email TEXT UNIQUE,
            palavras_chave TEXT[],
            ativo BOOLEAN DEFAULT TRUE,
            criado_em TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS alertas_enviados (
            id SERIAL PRIMARY KEY,
            cliente_id INT REFERENCES clientes(id),
            licitacao_id INT REFERENCES licitacoes(id),
            enviado_em TIMESTAMP DEFAULT NOW()
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Tabelas criadas com sucesso!")

if __name__ == "__main__":
    criar_tabelas()