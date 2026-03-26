"""
Auto-classification for the Go/Consider/Skip decision workflow.
Pre-classifies opportunities based on match score thresholds.
"""
import logging

from app.database import get_connection, release_connection

logger = logging.getLogger("tendersentinel.auto_classifier")


class AutoClassifier:
    """Pre-classifies opportunities based on match score."""

    GO_THRESHOLD = 8.0
    CONSIDER_THRESHOLD = 5.0

    def classify(self, match_score: float) -> str:
        if match_score >= self.GO_THRESHOLD:
            return "go"
        elif match_score >= self.CONSIDER_THRESHOLD:
            return "consider"
        return "skip"

    def classify_batch(self, scored_opportunities: list[dict]) -> list[dict]:
        results = []
        for opp in scored_opportunities:
            decision = self.classify(opp.get("match_score", 0))
            results.append({
                **opp,
                "auto_decision": decision,
                "auto_classified": True,
            })
        return results


def upsert_decision(user_id: int, opportunity_id: int, decision: str,
                    auto_classified: bool = False, notes: str = None):
    """Insert or update a user decision on an opportunity."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Check for existing decision to log history
        cur.execute(
            "SELECT decision FROM opportunity_decisions WHERE user_id = %s AND opportunity_id = %s",
            (user_id, opportunity_id),
        )
        old = cur.fetchone()

        cur.execute("""
            INSERT INTO opportunity_decisions
                (user_id, opportunity_id, decision, auto_classified, notes)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, opportunity_id)
            DO UPDATE SET
                decision = EXCLUDED.decision,
                auto_classified = EXCLUDED.auto_classified,
                notes = COALESCE(EXCLUDED.notes, opportunity_decisions.notes),
                updated_at = NOW()
        """, (user_id, opportunity_id, decision, auto_classified, notes))

        # Log decision change
        if old and old[0] != decision:
            cur.execute("""
                INSERT INTO decision_history
                    (user_id, opportunity_id, old_decision, new_decision)
                VALUES (%s, %s, %s, %s)
            """, (user_id, opportunity_id, old[0], decision))

        conn.commit()
    except Exception as e:
        logger.error(f"Failed to upsert decision: {e}")
        conn.rollback()
    finally:
        cur.close()
        release_connection(conn)


def get_pipeline(user_id: int) -> dict:
    """Get opportunities grouped by decision for a user."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                l.id, l.sam_id, l.orgao, l.objeto, l.valor, l.deadline,
                l.naics_code, l.set_aside, l.link,
                d.decision, d.notes, d.auto_classified,
                m.overall_score, m.naics_score, m.setaside_score,
                m.keyword_score, m.size_fit_score, m.past_perf_score,
                l.estimated_value_low, l.estimated_value_mid, l.estimated_value_high,
                l.estimation_confidence
            FROM licitacoes l
            LEFT JOIN opportunity_decisions d
                ON d.opportunity_id = l.id AND d.user_id = %s
            LEFT JOIN opportunity_match_scores m
                ON m.opportunity_id = l.id AND m.user_id = %s
            WHERE l.deadline >= CURRENT_DATE OR l.deadline IS NULL
            ORDER BY COALESCE(m.overall_score, 0) DESC
        """, (user_id, user_id))

        pipeline = {"go": [], "consider": [], "skip": [], "unclassified": []}
        for row in cur.fetchall():
            opp = {
                "id": row[0], "sam_id": row[1], "agency": row[2],
                "title": row[3], "value": float(row[4]) if row[4] else None,
                "deadline": str(row[5]) if row[5] else None,
                "naics_code": row[6], "set_aside": row[7], "link": row[8],
                "decision": row[9], "notes": row[10],
                "auto_classified": row[11],
                "overall_score": float(row[12]) if row[12] else None,
                "naics_score": float(row[13]) if row[13] else None,
                "setaside_score": float(row[14]) if row[14] else None,
                "keyword_score": float(row[15]) if row[15] else None,
                "size_fit_score": float(row[16]) if row[16] else None,
                "past_perf_score": float(row[17]) if row[17] else None,
                "estimated_value_low": float(row[18]) if row[18] else None,
                "estimated_value_mid": float(row[19]) if row[19] else None,
                "estimated_value_high": float(row[20]) if row[20] else None,
                "estimation_confidence": row[21],
            }
            bucket = opp["decision"] or "unclassified"
            pipeline.setdefault(bucket, []).append(opp)

        return pipeline
    finally:
        cur.close()
        release_connection(conn)


def get_pipeline_stats(user_id: int) -> dict:
    """Get pipeline analytics for a user."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                d.decision,
                COUNT(*),
                COALESCE(SUM(l.estimated_value_mid), 0)
            FROM opportunity_decisions d
            JOIN licitacoes l ON l.id = d.opportunity_id
            WHERE d.user_id = %s
            GROUP BY d.decision
        """, (user_id,))

        decisions = {}
        total_value = {"go": 0, "consider": 0}
        for row in cur.fetchall():
            decisions[row[0]] = row[1]
            if row[0] in total_value:
                total_value[row[0]] = float(row[2])

        # Count unclassified
        cur.execute("""
            SELECT COUNT(*)
            FROM licitacoes l
            LEFT JOIN opportunity_decisions d
                ON d.opportunity_id = l.id AND d.user_id = %s
            WHERE d.id IS NULL
            AND (l.deadline >= CURRENT_DATE OR l.deadline IS NULL)
        """, (user_id,))
        unclassified = cur.fetchone()[0]

        # Upcoming deadlines
        cur.execute("""
            SELECT d.decision, COUNT(*)
            FROM opportunity_decisions d
            JOIN licitacoes l ON l.id = d.opportunity_id
            WHERE d.user_id = %s
            AND d.decision IN ('go', 'consider')
            AND l.deadline BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
            GROUP BY d.decision
        """, (user_id,))
        deadlines = {row[0]: row[1] for row in cur.fetchall()}

        return {
            "decisions": {
                "go": decisions.get("go", 0),
                "consider": decisions.get("consider", 0),
                "skip": decisions.get("skip", 0),
                "unclassified": unclassified,
            },
            "estimated_pipeline_value": total_value,
            "deadlines_this_week": deadlines,
        }
    finally:
        cur.close()
        release_connection(conn)
