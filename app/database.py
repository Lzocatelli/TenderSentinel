import os
import logging

import psycopg2
import psycopg2.pool
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("tendersentinel.database")

# ── Connection Pool ──────────────────────────────────────────────────────────

_pool = None


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        _pool = psycopg2.pool.SimpleConnectionPool(1, 10, database_url)
    else:
        required_vars = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            raise RuntimeError(
                f"Missing database environment variables: {', '.join(missing)}. "
                "Set them in .env (local) or Railway (production)."
            )
        _pool = psycopg2.pool.SimpleConnectionPool(
            1, 10,
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
        )

    logger.info("Database connection pool initialized")
    return _pool


def get_connection():
    """Get a connection from the pool."""
    return _get_pool().getconn()


def release_connection(conn):
    """Return a connection to the pool."""
    try:
        _get_pool().putconn(conn)
    except Exception:
        pass


# Legacy alias
conectar = get_connection


# ── Schema ───────────────────────────────────────────────────────────────────

def create_tables():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS licitacoes (
            id SERIAL PRIMARY KEY,
            sam_id TEXT UNIQUE,
            orgao TEXT,
            objeto TEXT,
            valor NUMERIC,
            data_publicacao DATE,
            deadline DATE,
            link TEXT,
            uf TEXT,
            naics_code TEXT,
            set_aside TEXT,
            criado_em TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            nome TEXT,
            email TEXT UNIQUE,
            senha TEXT,
            palavras_chave TEXT[],
            ativo BOOLEAN DEFAULT TRUE,
            plano TEXT,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            stripe_last_session_id TEXT,
            naics_codes TEXT[],
            set_asides TEXT[],
            criado_em TIMESTAMP DEFAULT NOW()
        );
    """)

    # Incremental migrations
    migrations = [
        ("licitacoes", "uf", "TEXT"),
        ("licitacoes", "sam_id", "TEXT"),
        ("licitacoes", "deadline", "DATE"),
        ("licitacoes", "naics_code", "TEXT"),
        ("licitacoes", "set_aside", "TEXT"),
        ("clientes", "plano", "TEXT"),
        ("clientes", "stripe_customer_id", "TEXT"),
        ("clientes", "stripe_subscription_id", "TEXT"),
        ("clientes", "stripe_last_session_id", "TEXT"),
        ("clientes", "naics_codes", "TEXT[]"),
        ("clientes", "set_asides", "TEXT[]"),
    ]
    for table, col, col_type in migrations:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type};")
        except Exception as e:
            logger.warning(f"Migration failed for {table}.{col}: {e}")
            conn.rollback()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS alertas_enviados (
            id SERIAL PRIMARY KEY,
            cliente_id INT REFERENCES clientes(id),
            licitacao_id INT REFERENCES licitacoes(id),
            enviado_em TIMESTAMP DEFAULT NOW(),
            UNIQUE (cliente_id, licitacao_id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS newsletter (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE,
            nome TEXT,
            token_descadastro TEXT,
            ativo BOOLEAN DEFAULT TRUE,
            confirmed BOOLEAN DEFAULT FALSE,
            criado_em TIMESTAMP DEFAULT NOW()
        );
    """)

    # ── Indexes (Q20) ────────────────────────────────────────────────────────
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_licitacoes_data_pub ON licitacoes(data_publicacao)",
        "CREATE INDEX IF NOT EXISTS idx_licitacoes_sam_id ON licitacoes(sam_id)",
        "CREATE INDEX IF NOT EXISTS idx_alertas_cliente ON alertas_enviados(cliente_id)",
        "CREATE INDEX IF NOT EXISTS idx_alertas_licitacao ON alertas_enviados(licitacao_id)",
        "CREATE INDEX IF NOT EXISTS idx_newsletter_email ON newsletter(email)",
    ]
    for idx_sql in indexes:
        try:
            cur.execute(idx_sql)
        except Exception as e:
            logger.warning(f"Index creation failed: {e}")
            conn.rollback()

    # ── pg_trgm for ILIKE performance (Q21) ──────────────────────────────────
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_licitacoes_objeto_trgm "
            "ON licitacoes USING gin (objeto gin_trgm_ops);"
        )
        logger.info("pg_trgm extension and GIN index created")
    except Exception as e:
        logger.warning(f"pg_trgm setup failed (may need superuser): {e}")
        conn.rollback()

    # ── Newsletter confirmed column migration ────────────────────────────────
    try:
        cur.execute("ALTER TABLE newsletter ADD COLUMN IF NOT EXISTS confirmed BOOLEAN DEFAULT FALSE;")
    except Exception as e:
        logger.warning(f"Newsletter confirmed column migration failed: {e}")
        conn.rollback()

    conn.commit()
    cur.close()
    release_connection(conn)
    logger.info("Database tables and indexes ready")


if __name__ == "__main__":
    create_tables()
