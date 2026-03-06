import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def conectar():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
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