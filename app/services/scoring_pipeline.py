"""
Scoring pipeline — orchestrates match scoring, value estimation, and auto-classification.
"""
import logging

from app.config import get_plan_features
from app.database import get_connection, release_connection
from app.services.match_scorer import MatchScorer
from app.services.value_estimator import ContractValueEstimator
from app.services.auto_classifier import AutoClassifier, upsert_decision

logger = logging.getLogger("tendersentinel.scoring_pipeline")

_scorer = MatchScorer()
_estimator = ContractValueEstimator()
_classifier = AutoClassifier()


def build_profile_dict(user_id: int) -> dict:
    """Build a profile dict from the database for scoring."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Company profile
        cur.execute("""
            SELECT company_name, employee_count_range, annual_revenue_range, years_in_business
            FROM company_profiles WHERE user_id = %s
        """, (user_id,))
        profile_row = cur.fetchone()
        if not profile_row:
            # Fall back to basic clientes data
            cur.execute(
                "SELECT palavras_chave, naics_codes, set_asides FROM clientes WHERE id = %s",
                (user_id,),
            )
            basic = cur.fetchone()
            if not basic:
                return {}
            keywords = basic[0] or []
            naics = basic[1] or []
            set_asides = basic[2] or []
            return {
                "naics_codes": [{"code": n, "is_primary": i == 0} for i, n in enumerate(naics)],
                "certifications": [{"type": s} for s in set_asides],
                "keywords": [{"keyword": k, "weight": 1.0} for k in keywords],
                "annual_revenue_range": None,
                "past_performance": [],
            }

        profile_id = None
        cur.execute("SELECT id FROM company_profiles WHERE user_id = %s", (user_id,))
        pid_row = cur.fetchone()
        if pid_row:
            profile_id = pid_row[0]

        # NAICS codes
        naics_codes = []
        if profile_id:
            cur.execute(
                "SELECT naics_code, is_primary FROM company_naics WHERE company_profile_id = %s",
                (profile_id,),
            )
            naics_codes = [{"code": r[0], "is_primary": r[1]} for r in cur.fetchall()]

        # Certifications
        certs = []
        if profile_id:
            cur.execute(
                "SELECT certification_type FROM company_certifications WHERE company_profile_id = %s",
                (profile_id,),
            )
            certs = [{"type": r[0]} for r in cur.fetchall()]

        # Keywords
        keywords = []
        if profile_id:
            cur.execute(
                "SELECT keyword, weight FROM company_keywords WHERE company_profile_id = %s",
                (profile_id,),
            )
            keywords = [{"keyword": r[0], "weight": float(r[1])} for r in cur.fetchall()]

        # Past performance
        past_perf = []
        if profile_id:
            cur.execute(
                "SELECT agency, naics_code FROM company_past_performance WHERE company_profile_id = %s",
                (profile_id,),
            )
            past_perf = [{"agency": r[0], "naics_code": r[1]} for r in cur.fetchall()]

        return {
            "naics_codes": naics_codes,
            "certifications": certs,
            "keywords": keywords,
            "annual_revenue_range": profile_row[2],
            "past_performance": past_perf,
        }
    finally:
        cur.close()
        release_connection(conn)


def _opp_row_to_dict(row) -> dict:
    """Convert a licitacoes row to dict for scoring."""
    return {
        "id": row[0],
        "sam_id": row[1],
        "orgao": row[2],
        "objeto": row[3],
        "valor": float(row[4]) if row[4] else None,
        "naics_code": row[5],
        "set_aside": row[6],
        "estimated_value_mid": float(row[7]) if row[7] else None,
    }


def upsert_match_score(user_id: int, opportunity_id: int, breakdown) -> None:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO opportunity_match_scores
                (user_id, opportunity_id, overall_score,
                 naics_score, setaside_score, keyword_score,
                 size_fit_score, past_perf_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, opportunity_id)
            DO UPDATE SET
                overall_score = EXCLUDED.overall_score,
                naics_score = EXCLUDED.naics_score,
                setaside_score = EXCLUDED.setaside_score,
                keyword_score = EXCLUDED.keyword_score,
                size_fit_score = EXCLUDED.size_fit_score,
                past_perf_score = EXCLUDED.past_perf_score,
                scored_at = NOW()
        """, (
            user_id, opportunity_id, breakdown.overall,
            breakdown.naics_score, breakdown.setaside_score,
            breakdown.keyword_score, breakdown.size_fit_score,
            breakdown.past_perf_score,
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to upsert match score: {e}")
        conn.rollback()
    finally:
        cur.close()
        release_connection(conn)


def score_opportunity_for_all_users(opportunity_id: int):
    """Score a single opportunity for all users with profiles."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, sam_id, orgao, objeto, valor, naics_code, set_aside, estimated_value_mid "
            "FROM licitacoes WHERE id = %s",
            (opportunity_id,),
        )
        row = cur.fetchone()
        if not row:
            return

        opp = _opp_row_to_dict(row)

        cur.execute("SELECT id, plano FROM clientes WHERE ativo = TRUE")
        users = cur.fetchall()
    finally:
        cur.close()
        release_connection(conn)

    for uid, plano in users:
        profile = build_profile_dict(uid)
        if not profile:
            continue
        breakdown = _scorer.score(opp, profile)
        upsert_match_score(uid, opportunity_id, breakdown)

        # Auto-classify only for plans that support it
        features = get_plan_features(plano)
        if features.get("auto_classify"):
            decision = _classifier.classify(breakdown.overall)
            upsert_decision(uid, opportunity_id, decision, auto_classified=True)


def rescore_user_opportunities(user_id: int):
    """Rescore all active opportunities for a user (after profile update)."""
    profile = build_profile_dict(user_id)
    if not profile:
        return

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, sam_id, orgao, objeto, valor, naics_code, set_aside, estimated_value_mid "
            "FROM licitacoes WHERE deadline >= CURRENT_DATE OR deadline IS NULL"
        )
        rows = cur.fetchall()

        # Get user plan for feature gating
        cur.execute("SELECT plano FROM clientes WHERE id = %s", (user_id,))
        plano_row = cur.fetchone()
        plano = plano_row[0] if plano_row else None
    finally:
        cur.close()
        release_connection(conn)

    features = get_plan_features(plano)

    for row in rows:
        opp = _opp_row_to_dict(row)
        breakdown = _scorer.score(opp, profile)
        upsert_match_score(user_id, opp["id"], breakdown)

        if features.get("auto_classify"):
            decision = _classifier.classify(breakdown.overall)
            upsert_decision(user_id, opp["id"], decision, auto_classified=True)

    logger.info(f"Rescored {len(rows)} opportunities for user {user_id}")


def estimate_opportunity_value(opportunity_id: int):
    """Estimate and store the value for a single opportunity."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, naics_code, orgao FROM licitacoes WHERE id = %s",
            (opportunity_id,),
        )
        row = cur.fetchone()
        if not row:
            return

        opp = {"naics_code": row[1], "orgao": row[2]}
        estimate = _estimator.estimate(opp)

        if estimate["estimated_value_mid"] is not None:
            cur.execute("""
                UPDATE licitacoes SET
                    estimated_value_low = %s,
                    estimated_value_mid = %s,
                    estimated_value_high = %s,
                    estimation_confidence = %s,
                    estimation_sample_size = %s
                WHERE id = %s
            """, (
                estimate["estimated_value_low"],
                estimate["estimated_value_mid"],
                estimate["estimated_value_high"],
                estimate["confidence"],
                estimate["sample_size"],
                opportunity_id,
            ))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to estimate value for opportunity {opportunity_id}: {e}")
        conn.rollback()
    finally:
        cur.close()
        release_connection(conn)
