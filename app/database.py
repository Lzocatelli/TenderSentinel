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

    # ── Feature 1: Company profiles & match scores ─────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS company_profiles (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            company_name VARCHAR(255),
            cage_code VARCHAR(10),
            uei VARCHAR(20),
            sam_registered BOOLEAN DEFAULT FALSE,
            employee_count_range VARCHAR(50),
            annual_revenue_range VARCHAR(50),
            years_in_business INTEGER,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS company_naics (
            id SERIAL PRIMARY KEY,
            company_profile_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            naics_code VARCHAR(10) NOT NULL,
            is_primary BOOLEAN DEFAULT FALSE,
            proficiency VARCHAR(20) DEFAULT 'experienced',
            UNIQUE(company_profile_id, naics_code)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS company_certifications (
            id SERIAL PRIMARY KEY,
            company_profile_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            certification_type VARCHAR(50) NOT NULL,
            certification_number VARCHAR(100),
            expiration_date DATE,
            verified BOOLEAN DEFAULT FALSE,
            UNIQUE(company_profile_id, certification_type)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS company_keywords (
            id SERIAL PRIMARY KEY,
            company_profile_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            keyword VARCHAR(100) NOT NULL,
            weight FLOAT DEFAULT 1.0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS company_past_performance (
            id SERIAL PRIMARY KEY,
            company_profile_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            contract_number VARCHAR(100),
            agency VARCHAR(255),
            naics_code VARCHAR(10),
            contract_value NUMERIC(15, 2),
            performance_period_start DATE,
            performance_period_end DATE,
            description TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS opportunity_match_scores (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            opportunity_id INTEGER NOT NULL REFERENCES licitacoes(id) ON DELETE CASCADE,
            overall_score FLOAT NOT NULL,
            naics_score FLOAT DEFAULT 0,
            setaside_score FLOAT DEFAULT 0,
            keyword_score FLOAT DEFAULT 0,
            size_fit_score FLOAT DEFAULT 0,
            past_perf_score FLOAT DEFAULT 0,
            scored_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, opportunity_id)
        );
    """)

    # ── Feature 2: Historical awards & value estimation ────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS historical_awards (
            id SERIAL PRIMARY KEY,
            contract_number VARCHAR(100),
            agency_code VARCHAR(20),
            agency_name VARCHAR(255),
            naics_code VARCHAR(10) NOT NULL,
            psc_code VARCHAR(10),
            set_aside_code VARCHAR(20),
            award_amount NUMERIC(15, 2) NOT NULL,
            base_and_options_value NUMERIC(15, 2),
            award_date DATE NOT NULL,
            period_of_performance_days INTEGER,
            place_of_performance_state VARCHAR(5),
            contractor_size VARCHAR(20),
            contract_type VARCHAR(50),
            competition_type VARCHAR(50),
            fetched_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS value_statistics (
            id SERIAL PRIMARY KEY,
            naics_code VARCHAR(10),
            agency_name VARCHAR(255),
            sample_size INTEGER NOT NULL,
            median_value NUMERIC(15, 2),
            mean_value NUMERIC(15, 2),
            p25_value NUMERIC(15, 2),
            p75_value NUMERIC(15, 2),
            p10_value NUMERIC(15, 2),
            p90_value NUMERIC(15, 2),
            min_value NUMERIC(15, 2),
            max_value NUMERIC(15, 2),
            last_computed TIMESTAMP DEFAULT NOW(),
            UNIQUE(naics_code, agency_name)
        );
    """)

    # Estimated value columns on licitacoes
    est_value_cols = [
        ("licitacoes", "estimated_value_low", "NUMERIC(15, 2)"),
        ("licitacoes", "estimated_value_mid", "NUMERIC(15, 2)"),
        ("licitacoes", "estimated_value_high", "NUMERIC(15, 2)"),
        ("licitacoes", "estimation_confidence", "VARCHAR(20)"),
        ("licitacoes", "estimation_sample_size", "INTEGER"),
    ]
    for table, col, col_type in est_value_cols:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type};")
        except Exception as e:
            logger.warning(f"Migration failed for {table}.{col}: {e}")
            conn.rollback()

    # ── Feature 3: Go/Consider/Skip decisions ──────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS opportunity_decisions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            opportunity_id INTEGER NOT NULL REFERENCES licitacoes(id) ON DELETE CASCADE,
            decision VARCHAR(20) NOT NULL CHECK (decision IN ('go', 'consider', 'skip')),
            auto_classified BOOLEAN DEFAULT FALSE,
            notes TEXT,
            decided_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, opportunity_id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS decision_history (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            opportunity_id INTEGER NOT NULL REFERENCES licitacoes(id) ON DELETE CASCADE,
            old_decision VARCHAR(20),
            new_decision VARCHAR(20) NOT NULL,
            changed_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # ── New indexes ────────────────────────────────────────────────────────
    new_indexes = [
        "CREATE INDEX IF NOT EXISTS idx_match_scores_user_score ON opportunity_match_scores(user_id, overall_score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_match_scores_opp ON opportunity_match_scores(opportunity_id)",
        "CREATE INDEX IF NOT EXISTS idx_decisions_user_dec ON opportunity_decisions(user_id, decision)",
        "CREATE INDEX IF NOT EXISTS idx_decisions_user_opp ON opportunity_decisions(user_id, opportunity_id)",
        "CREATE INDEX IF NOT EXISTS idx_historical_naics ON historical_awards(naics_code)",
        "CREATE INDEX IF NOT EXISTS idx_historical_agency ON historical_awards(agency_name)",
        "CREATE INDEX IF NOT EXISTS idx_historical_date ON historical_awards(award_date)",
    ]
    for idx_sql in new_indexes:
        try:
            cur.execute(idx_sql)
        except Exception as e:
            logger.warning(f"Index creation failed: {e}")
            conn.rollback()

    conn.commit()
    cur.close()
    release_connection(conn)
    logger.info("Database tables and indexes ready")


if __name__ == "__main__":
    create_tables()
