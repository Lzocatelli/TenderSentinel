"""
Integration test for TenderSentinel pipeline.
Tests: SAM.gov fetch → save → alert dispatch.
"""
import os

from dotenv import load_dotenv

load_dotenv()

from app.scraper import fetch_opportunities, save_opportunities
from app.alertas import dispatch_alerts
from app.database import get_connection, release_connection

TEST_EMAIL = os.getenv("TEST_EMAIL", "test@example.com")


if __name__ == "__main__":
    print("=== TenderSentinel — Full Flow Test ===")

    print("\n1. Fetching opportunities from SAM.gov...")
    opportunities = fetch_opportunities()
    saved = save_opportunities(opportunities)
    print(f"{saved} new opportunities saved to database.")

    print("\n2. Setting up test client...")
    conn = get_connection()
    cur = conn.cursor()

    test_keywords = [
        "software",
        "IT services",
        "cybersecurity",
        "cloud computing",
        "data analytics",
    ]

    cur.execute(
        """
        INSERT INTO clientes (nome, email, palavras_chave, ativo)
        VALUES ('Test User', %s, %s, TRUE)
        ON CONFLICT (email) DO UPDATE
        SET palavras_chave = %s;
        """,
        (TEST_EMAIL, test_keywords, test_keywords),
    )

    # Only clear alerts for the test user, not all users (Q31)
    cur.execute(
        "DELETE FROM alertas_enviados WHERE cliente_id = (SELECT id FROM clientes WHERE email = %s)",
        (TEST_EMAIL,),
    )
    conn.commit()
    cur.close()
    release_connection(conn)

    print("\n3. Dispatching alerts for test client...")
    dispatch_alerts()

    print("\nFull flow test completed!")
