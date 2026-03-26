"""
Contract value estimation for TenderSentinel.
Predicts likely dollar value range using historical data from USASpending.gov.
"""
import logging
import time
from typing import Optional

import requests

from app.database import get_connection, release_connection

logger = logging.getLogger("tendersentinel.value_estimator")


class USASpendingFetcher:
    """Fetches historical award data from USASpending.gov API (free, no auth)."""

    BASE_URL = "https://api.usaspending.gov/api/v2"

    def fetch_awards_by_naics(self, naics_code: str, fiscal_years: list[int]) -> list[dict]:
        payload = {
            "filters": {
                "naics_codes": [naics_code],
                "time_period": [
                    {"start_date": f"{fy - 1}-10-01", "end_date": f"{fy}-09-30"}
                    for fy in fiscal_years
                ],
                "award_type_codes": ["A", "B", "C", "D"],
            },
            "fields": [
                "Award ID", "Awarding Agency", "Award Amount",
                "NAICS Code", "Product or Service Code",
                "Start Date", "End Date", "Award Type",
                "Recipient Name", "Awarding Sub Agency",
            ],
            "limit": 100,
            "page": 1,
            "sort": "Award Amount",
            "order": "desc",
        }

        all_results = []
        max_pages = 50  # Safety limit

        while payload["page"] <= max_pages:
            try:
                resp = requests.post(
                    f"{self.BASE_URL}/search/spending_by_award/",
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                logger.warning(f"USASpending API error (page {payload['page']}): {e}")
                break

            results = data.get("results", [])
            all_results.extend(results)

            if len(results) < payload["limit"]:
                break

            payload["page"] += 1
            time.sleep(0.5)

        logger.info(f"Fetched {len(all_results)} awards for NAICS {naics_code}")
        return all_results

    def save_awards(self, awards: list[dict], naics_code: str) -> int:
        """Save fetched awards to historical_awards table."""
        conn = get_connection()
        cur = conn.cursor()
        saved = 0

        for award in awards:
            try:
                amount = award.get("Award Amount")
                if not amount or float(amount) <= 0:
                    continue

                cur.execute("""
                    INSERT INTO historical_awards
                        (contract_number, agency_name, naics_code, psc_code,
                         award_amount, award_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (
                    award.get("Award ID", ""),
                    award.get("Awarding Agency", ""),
                    naics_code,
                    award.get("Product or Service Code", ""),
                    float(amount),
                    award.get("Start Date") or "2020-01-01",
                ))
                saved += 1
            except Exception as e:
                logger.debug(f"Skipping award: {e}")
                conn.rollback()
                continue

        conn.commit()
        cur.close()
        release_connection(conn)
        logger.info(f"Saved {saved} historical awards for NAICS {naics_code}")
        return saved


class ContractValueEstimator:
    """
    Estimates the likely dollar value range of an opportunity
    using pre-computed statistics from historical awards.
    """

    HIGH_CONFIDENCE_MIN = 50
    MEDIUM_CONFIDENCE_MIN = 15
    LOW_CONFIDENCE_MIN = 5

    def estimate(self, opportunity: dict) -> dict:
        naics = opportunity.get("naics_code")
        agency = opportunity.get("orgao")

        queries = [
            {"naics_code": naics, "agency_name": agency},
            {"naics_code": naics},
            {"agency_name": agency},
        ]

        for query_params in queries:
            params = {k: v for k, v in query_params.items() if v}
            if not params:
                continue

            stats = self._get_statistics(params)
            if stats and stats["sample_size"] >= self.LOW_CONFIDENCE_MIN:
                confidence = self._determine_confidence(stats["sample_size"])
                return {
                    "estimated_value_low": stats["p25_value"],
                    "estimated_value_mid": stats["median_value"],
                    "estimated_value_high": stats["p75_value"],
                    "confidence": confidence,
                    "sample_size": stats["sample_size"],
                }

        return {
            "estimated_value_low": None,
            "estimated_value_mid": None,
            "estimated_value_high": None,
            "confidence": "none",
            "sample_size": 0,
        }

    def _get_statistics(self, params: dict) -> Optional[dict]:
        conn = get_connection()
        cur = conn.cursor()
        try:
            where_parts = []
            values = []
            for key, val in params.items():
                where_parts.append(f"{key} = %s")
                values.append(val)

            sql = f"""
                SELECT sample_size, median_value, p25_value, p75_value
                FROM value_statistics
                WHERE {' AND '.join(where_parts)}
                ORDER BY sample_size DESC
                LIMIT 1
            """
            cur.execute(sql, values)
            row = cur.fetchone()
            if row:
                return {
                    "sample_size": row[0],
                    "median_value": float(row[1]) if row[1] else None,
                    "p25_value": float(row[2]) if row[2] else None,
                    "p75_value": float(row[3]) if row[3] else None,
                }
            return None
        finally:
            cur.close()
            release_connection(conn)

    def _determine_confidence(self, sample_size: int) -> str:
        if sample_size >= self.HIGH_CONFIDENCE_MIN:
            return "high"
        elif sample_size >= self.MEDIUM_CONFIDENCE_MIN:
            return "medium"
        return "low"


def compute_statistics_batch():
    """
    Recompute value_statistics from historical_awards.
    Run as a scheduled task.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO value_statistics
                (naics_code, agency_name,
                 sample_size, median_value, mean_value,
                 p25_value, p75_value, p10_value, p90_value,
                 min_value, max_value, last_computed)
            SELECT
                naics_code,
                agency_name,
                COUNT(*) as sample_size,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY award_amount) as median_value,
                AVG(award_amount) as mean_value,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY award_amount) as p25_value,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY award_amount) as p75_value,
                PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY award_amount) as p10_value,
                PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY award_amount) as p90_value,
                MIN(award_amount) as min_value,
                MAX(award_amount) as max_value,
                NOW() as last_computed
            FROM historical_awards
            WHERE award_date >= NOW() - INTERVAL '5 years'
            GROUP BY naics_code, agency_name
            HAVING COUNT(*) >= 5
            ON CONFLICT (naics_code, agency_name)
            DO UPDATE SET
                sample_size = EXCLUDED.sample_size,
                median_value = EXCLUDED.median_value,
                mean_value = EXCLUDED.mean_value,
                p25_value = EXCLUDED.p25_value,
                p75_value = EXCLUDED.p75_value,
                p10_value = EXCLUDED.p10_value,
                p90_value = EXCLUDED.p90_value,
                min_value = EXCLUDED.min_value,
                max_value = EXCLUDED.max_value,
                last_computed = EXCLUDED.last_computed;
        """)
        conn.commit()
        logger.info("Value statistics recomputed successfully")
    except Exception as e:
        logger.error(f"Failed to compute statistics: {e}")
        conn.rollback()
    finally:
        cur.close()
        release_connection(conn)
