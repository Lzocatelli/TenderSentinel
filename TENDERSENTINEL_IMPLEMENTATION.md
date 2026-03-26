# TenderSentinel — Implementation Plan: Intelligent Procurement Features

## Overview

This document outlines the implementation of three interconnected features for TenderSentinel, a Flask/PostgreSQL SaaS that monitors US federal procurement opportunities from SAM.gov. These features elevate the product from an alert tool to a procurement intelligence platform.

**Current Stack:** Flask, PostgreSQL, Stripe, SendGrid, deployed on Railway  
**Current Features:** NAICS code matching, set-aside intelligence, opportunity scoring, email alerts  
**Pricing Tiers:** Basic $79/mo, Professional $179/mo, Agency $349/mo (coming soon)

---

## Feature 1: Company-Contract Match Score

### Purpose

Score every SAM.gov opportunity against the user's company profile on a 0–10 scale so users instantly know which contracts are worth pursuing.

### Database Schema Changes

```sql
-- Extended company profile
CREATE TABLE company_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_name VARCHAR(255),
    cage_code VARCHAR(10),
    uei VARCHAR(20),
    sam_registered BOOLEAN DEFAULT FALSE,
    employee_count_range VARCHAR(50), -- e.g., '1-50', '51-250', '251-500', '500+'
    annual_revenue_range VARCHAR(50), -- e.g., '<1M', '1M-5M', '5M-25M', '25M+'
    years_in_business INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id)
);

-- User's NAICS codes with proficiency/preference weight
CREATE TABLE company_naics (
    id SERIAL PRIMARY KEY,
    company_profile_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    naics_code VARCHAR(10) NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,
    proficiency VARCHAR(20) DEFAULT 'experienced', -- 'expert', 'experienced', 'capable', 'learning'
    UNIQUE(company_profile_id, naics_code)
);

-- User's set-aside certifications
CREATE TABLE company_certifications (
    id SERIAL PRIMARY KEY,
    company_profile_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    certification_type VARCHAR(50) NOT NULL, -- 'SBA', '8a', 'SDVOSB', 'WOSB', 'HUBZone', 'EDWOSB'
    certification_number VARCHAR(100),
    expiration_date DATE,
    verified BOOLEAN DEFAULT FALSE,
    UNIQUE(company_profile_id, certification_type)
);

-- User's keywords and capability areas
CREATE TABLE company_keywords (
    id SERIAL PRIMARY KEY,
    company_profile_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    keyword VARCHAR(100) NOT NULL,
    weight FLOAT DEFAULT 1.0 -- 0.1 to 2.0, user can boost/reduce
);

-- Past performance references (optional, for future scoring)
CREATE TABLE company_past_performance (
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

-- Match scores stored per opportunity per user
CREATE TABLE opportunity_match_scores (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    overall_score FLOAT NOT NULL, -- 0.0 to 10.0
    naics_score FLOAT DEFAULT 0,
    setaside_score FLOAT DEFAULT 0,
    keyword_score FLOAT DEFAULT 0,
    size_fit_score FLOAT DEFAULT 0,
    past_performance_score FLOAT DEFAULT 0,
    scored_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, opportunity_id)
);

CREATE INDEX idx_match_scores_user_score ON opportunity_match_scores(user_id, overall_score DESC);
CREATE INDEX idx_match_scores_opportunity ON opportunity_match_scores(opportunity_id);
```

### Match Scoring Algorithm

```python
# app/services/match_scorer.py

from dataclasses import dataclass
from typing import Optional


@dataclass
class MatchBreakdown:
    naics_score: float = 0.0       # max 3.0
    setaside_score: float = 0.0    # max 2.5
    keyword_score: float = 0.0     # max 2.0
    size_fit_score: float = 0.0    # max 1.5
    past_perf_score: float = 0.0   # max 1.0
    # total max = 10.0

    @property
    def overall(self) -> float:
        return round(
            self.naics_score +
            self.setaside_score +
            self.keyword_score +
            self.size_fit_score +
            self.past_perf_score,
            1
        )


class MatchScorer:
    """
    Scores an opportunity against a company profile.
    Each component has a defined max weight that sums to 10.0.
    """

    # Weight distribution (must sum to 10.0)
    NAICS_MAX = 3.0
    SETASIDE_MAX = 2.5
    KEYWORD_MAX = 2.0
    SIZE_FIT_MAX = 1.5
    PAST_PERF_MAX = 1.0

    def score(self, opportunity: dict, profile: dict) -> MatchBreakdown:
        breakdown = MatchBreakdown()
        breakdown.naics_score = self._score_naics(opportunity, profile)
        breakdown.setaside_score = self._score_setaside(opportunity, profile)
        breakdown.keyword_score = self._score_keywords(opportunity, profile)
        breakdown.size_fit_score = self._score_size_fit(opportunity, profile)
        breakdown.past_perf_score = self._score_past_performance(opportunity, profile)
        return breakdown

    def _score_naics(self, opp: dict, profile: dict) -> float:
        """
        NAICS matching logic:
        - Exact 6-digit match on primary NAICS   → 3.0
        - Exact 6-digit match on secondary NAICS  → 2.5
        - Industry group match (first 4 digits)    → 1.5
        - Sector match (first 2 digits)            → 0.5
        - No match                                 → 0.0
        """
        opp_naics = opp.get("naics_code", "")
        if not opp_naics:
            return self.NAICS_MAX * 0.5  # No NAICS specified = neutral

        user_naics = profile.get("naics_codes", [])
        primary_codes = [n["code"] for n in user_naics if n.get("is_primary")]
        secondary_codes = [n["code"] for n in user_naics if not n.get("is_primary")]

        # Exact match on primary
        if opp_naics in primary_codes:
            return self.NAICS_MAX

        # Exact match on secondary
        if opp_naics in secondary_codes:
            return self.NAICS_MAX * 0.83  # 2.5

        # Industry group match (4-digit prefix)
        all_codes = primary_codes + secondary_codes
        opp_prefix_4 = opp_naics[:4]
        if any(code[:4] == opp_prefix_4 for code in all_codes):
            return self.NAICS_MAX * 0.5  # 1.5

        # Sector match (2-digit prefix)
        opp_prefix_2 = opp_naics[:2]
        if any(code[:2] == opp_prefix_2 for code in all_codes):
            return self.NAICS_MAX * 0.17  # 0.5

        return 0.0

    def _score_setaside(self, opp: dict, profile: dict) -> float:
        """
        Set-aside matching:
        - Opportunity has set-aside AND user has matching cert → 2.5
        - Opportunity has set-aside, user has NO matching cert → 0.5
          (still eligible as unrestricted, but lower priority)
        - Opportunity has NO set-aside (full & open)           → 1.5
          (everyone eligible, moderate score)
        """
        opp_setaside = opp.get("set_aside_code", "")
        user_certs = [c["type"] for c in profile.get("certifications", [])]

        if not opp_setaside or opp_setaside.upper() in ("NONE", ""):
            return self.SETASIDE_MAX * 0.6  # Full & open

        # Map SAM.gov set-aside codes to certification types
        setaside_to_cert = {
            "SBA": "SBA",
            "8A": "8a",
            "8AN": "8a",
            "SDVOSBC": "SDVOSB",
            "SDVOSBS": "SDVOSB",
            "WOSB": "WOSB",
            "EDWOSB": "EDWOSB",
            "HZC": "HUBZone",
            "HZS": "HUBZone",
        }

        required_cert = setaside_to_cert.get(opp_setaside.upper())
        if required_cert and required_cert in user_certs:
            return self.SETASIDE_MAX  # Perfect match
        elif required_cert and required_cert not in user_certs:
            return self.SETASIDE_MAX * 0.2  # Set-aside they don't qualify for

        return self.SETASIDE_MAX * 0.4  # Unknown set-aside type

    def _score_keywords(self, opp: dict, profile: dict) -> float:
        """
        Keyword matching against opportunity title + description.
        Uses weighted keywords from user profile.
        Score = (matched_weight / total_possible_weight) * KEYWORD_MAX
        """
        opp_text = (
            opp.get("title", "") + " " + opp.get("description", "")
        ).lower()

        if not opp_text.strip():
            return 0.0

        user_keywords = profile.get("keywords", [])
        if not user_keywords:
            return self.KEYWORD_MAX * 0.5  # No keywords set = neutral

        total_weight = sum(kw.get("weight", 1.0) for kw in user_keywords)
        matched_weight = sum(
            kw.get("weight", 1.0)
            for kw in user_keywords
            if kw["keyword"].lower() in opp_text
        )

        ratio = matched_weight / total_weight if total_weight > 0 else 0
        return round(ratio * self.KEYWORD_MAX, 2)

    def _score_size_fit(self, opp: dict, profile: dict) -> float:
        """
        Estimates whether the contract size fits the company.
        Uses estimated_value (from Feature 2) or NAICS size standards.
        If no value data available, return neutral score.
        """
        estimated_value = opp.get("estimated_value")
        annual_revenue = profile.get("annual_revenue_midpoint")

        if not estimated_value or not annual_revenue:
            return self.SIZE_FIT_MAX * 0.5  # Neutral when unknown

        # Rule of thumb: contract should be 5%-50% of annual revenue
        ratio = estimated_value / annual_revenue if annual_revenue > 0 else 0

        if 0.05 <= ratio <= 0.50:
            return self.SIZE_FIT_MAX  # Sweet spot
        elif 0.01 <= ratio < 0.05 or 0.50 < ratio <= 1.0:
            return self.SIZE_FIT_MAX * 0.6  # Doable but stretch
        elif ratio > 1.0:
            return self.SIZE_FIT_MAX * 0.2  # Likely too large
        else:
            return self.SIZE_FIT_MAX * 0.3  # Very small, may not be worth it

    def _score_past_performance(self, opp: dict, profile: dict) -> float:
        """
        Checks if user has past performance in the same NAICS or agency.
        """
        past_perf = profile.get("past_performance", [])
        if not past_perf:
            return self.PAST_PERF_MAX * 0.3  # No data = low but not zero

        opp_naics = opp.get("naics_code", "")
        opp_agency = opp.get("agency", "").lower()

        naics_match = any(pp.get("naics_code") == opp_naics for pp in past_perf)
        agency_match = any(opp_agency in pp.get("agency", "").lower() for pp in past_perf)

        if naics_match and agency_match:
            return self.PAST_PERF_MAX
        elif naics_match or agency_match:
            return self.PAST_PERF_MAX * 0.6
        else:
            return self.PAST_PERF_MAX * 0.2
```

### API Endpoints

```python
# Company Profile CRUD
POST   /api/v1/profile                    # Create/update company profile
GET    /api/v1/profile                    # Get current profile
PUT    /api/v1/profile/naics              # Update NAICS codes
PUT    /api/v1/profile/certifications     # Update certifications
PUT    /api/v1/profile/keywords           # Update keywords
POST   /api/v1/profile/past-performance   # Add past performance

# Match Scores
GET    /api/v1/opportunities?scored=true  # List opportunities with match scores
GET    /api/v1/opportunities/:id/score    # Get detailed score breakdown
POST   /api/v1/opportunities/rescore      # Force rescore all (after profile update)
```

### Frontend: Profile Setup Flow

Build a multi-step onboarding wizard at `/dashboard/profile`:

1. **Company Basics** — Name, CAGE code, UEI, SAM registration status, employee count, revenue range
2. **NAICS Codes** — Search and select NAICS codes, mark one as primary, set proficiency
3. **Certifications** — Toggle applicable certs: SBA, 8(a), SDVOSB, WOSB, HUBZone, EDWOSB
4. **Keywords** — Add keywords/capabilities with weight sliders (0.1–2.0)
5. **Past Performance** (optional) — Add past contract references

### Scoring Pipeline

```python
# When to trigger scoring:
# 1. New opportunity ingested from SAM.gov → score for all users
# 2. User updates profile → rescore all active opportunities for that user
# 3. Nightly batch job → rescore expiring/updated opportunities

# app/services/scoring_pipeline.py

def score_opportunity_for_all_users(opportunity_id: int):
    """Called when a new opportunity is ingested."""
    opportunity = get_opportunity(opportunity_id)
    users = get_users_with_profiles()

    for user in users:
        profile = build_profile_dict(user.id)
        scorer = MatchScorer()
        breakdown = scorer.score(opportunity, profile)

        upsert_match_score(
            user_id=user.id,
            opportunity_id=opportunity_id,
            breakdown=breakdown
        )


def rescore_user_opportunities(user_id: int):
    """Called when user updates their profile."""
    profile = build_profile_dict(user_id)
    active_opportunities = get_active_opportunities()
    scorer = MatchScorer()

    for opp in active_opportunities:
        breakdown = scorer.score(opp, profile)
        upsert_match_score(
            user_id=user_id,
            opportunity_id=opp["id"],
            breakdown=breakdown
        )
```

### Email Alert Integration

Update SendGrid email templates to include the match score:

```
Subject: "🎯 9.2/10 Match: DoD Infrastructure Modernization Phase IV"

Body should show:
- Overall score badge (color-coded: green 8+, yellow 5-7, gray <5)
- Score breakdown chips: NAICS ✓ | SDVOSB ✓ | Keywords 3/5
- Quick action buttons: View Details | Mark as Go | Skip
```

---

## Feature 2: Estimated Contract Value

### Purpose

Predict the likely dollar value range of an opportunity before award, using historical data from FPDS and USASpending, since SAM.gov does not publish estimated values for most pre-award opportunities.

### Data Sources

1. **FPDS.gov (Federal Procurement Data System)** — Historical contract awards with values, NAICS codes, PSC codes, agencies
2. **USASpending.gov API** — Award data with amounts, NAICS, agency breakdowns
3. **SAM.gov Awards** — Post-award data for completed contracts

### Database Schema

```sql
-- Historical award data for value estimation
CREATE TABLE historical_awards (
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
    contractor_size VARCHAR(20), -- 'S' for small, 'O' for other
    contract_type VARCHAR(50), -- 'FFP', 'T&M', 'CPFF', etc.
    competition_type VARCHAR(50),
    fetched_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_historical_naics ON historical_awards(naics_code);
CREATE INDEX idx_historical_agency ON historical_awards(agency_code);
CREATE INDEX idx_historical_psc ON historical_awards(psc_code);
CREATE INDEX idx_historical_date ON historical_awards(award_date);
CREATE INDEX idx_historical_naics_agency ON historical_awards(naics_code, agency_code);

-- Pre-computed statistics per NAICS + agency combination
CREATE TABLE value_statistics (
    id SERIAL PRIMARY KEY,
    naics_code VARCHAR(10) NOT NULL,
    agency_code VARCHAR(20), -- NULL = all agencies
    psc_code VARCHAR(10),    -- NULL = all PSCs
    set_aside_code VARCHAR(20), -- NULL = all types
    sample_size INTEGER NOT NULL,
    median_value NUMERIC(15, 2),
    mean_value NUMERIC(15, 2),
    p25_value NUMERIC(15, 2),   -- 25th percentile
    p75_value NUMERIC(15, 2),   -- 75th percentile
    p10_value NUMERIC(15, 2),   -- 10th percentile
    p90_value NUMERIC(15, 2),   -- 90th percentile
    min_value NUMERIC(15, 2),
    max_value NUMERIC(15, 2),
    last_computed TIMESTAMP DEFAULT NOW(),
    UNIQUE(naics_code, agency_code, psc_code, set_aside_code)
);

-- Estimated values linked to opportunities
ALTER TABLE opportunities ADD COLUMN estimated_value_low NUMERIC(15, 2);
ALTER TABLE opportunities ADD COLUMN estimated_value_mid NUMERIC(15, 2);
ALTER TABLE opportunities ADD COLUMN estimated_value_high NUMERIC(15, 2);
ALTER TABLE opportunities ADD COLUMN estimation_confidence VARCHAR(20); -- 'high', 'medium', 'low'
ALTER TABLE opportunities ADD COLUMN estimation_sample_size INTEGER;
```

### Data Ingestion Pipeline

```python
# app/services/historical_data_fetcher.py

import requests
from datetime import datetime, timedelta


class USASpendingFetcher:
    """
    Fetches historical award data from USASpending.gov API.
    API docs: https://api.usaspending.gov/
    Free, no authentication required, rate-limited.
    """
    BASE_URL = "https://api.usaspending.gov/api/v2"

    def fetch_awards_by_naics(self, naics_code: str, fiscal_years: list[int]) -> list[dict]:
        """
        Fetch award records for a NAICS code across specified fiscal years.
        Use /search/spending_by_award/ endpoint.
        """
        payload = {
            "filters": {
                "naics_codes": [naics_code],
                "time_period": [
                    {
                        "start_date": f"{fy - 1}-10-01",
                        "end_date": f"{fy}-09-30"
                    }
                    for fy in fiscal_years
                ],
                "award_type_codes": ["A", "B", "C", "D"]  # Contracts only
            },
            "fields": [
                "Award ID",
                "Awarding Agency",
                "Award Amount",
                "NAICS Code",
                "Product or Service Code",
                "Start Date",
                "End Date",
                "Award Type",
                "Recipient Name",
                "Awarding Sub Agency"
            ],
            "limit": 100,
            "page": 1,
            "sort": "Award Amount",
            "order": "desc"
        }

        all_results = []
        while True:
            resp = requests.post(f"{self.BASE_URL}/search/spending_by_award/", json=payload)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            all_results.extend(results)

            if len(results) < payload["limit"]:
                break  # Last page

            payload["page"] += 1
            # Be respectful: rate limit
            import time
            time.sleep(0.5)

        return all_results

    def fetch_aggregate_by_naics_agency(self, naics_code: str, agency_code: str) -> dict:
        """
        Get aggregate spending stats for a NAICS + agency combo.
        Useful for quick estimates without fetching all records.
        """
        payload = {
            "group": "naics_code",
            "filters": {
                "naics_codes": [naics_code],
                "agencies": [
                    {"type": "awarding", "tier": "toptier", "toptier_name": agency_code}
                ],
                "time_period": [
                    {"start_date": "2020-10-01", "end_date": "2025-09-30"}
                ]
            }
        }
        resp = requests.post(f"{self.BASE_URL}/search/spending_by_category/naics/", json=payload)
        resp.raise_for_status()
        return resp.json()
```

### Value Estimation Engine

```python
# app/services/value_estimator.py

import numpy as np
from typing import Optional


class ContractValueEstimator:
    """
    Estimates the likely dollar value range of an opportunity
    based on historical awards with similar characteristics.
    """

    # Minimum sample size thresholds
    HIGH_CONFIDENCE_MIN = 50
    MEDIUM_CONFIDENCE_MIN = 15
    LOW_CONFIDENCE_MIN = 5

    def estimate(self, opportunity: dict) -> dict:
        """
        Returns estimated value range and confidence level.

        Strategy (cascading specificity):
        1. Try: NAICS + Agency + PSC + Set-aside
        2. Fall back: NAICS + Agency + Set-aside
        3. Fall back: NAICS + Agency
        4. Fall back: NAICS only
        5. Fall back: Agency + PSC
        6. Final fallback: return None (insufficient data)
        """
        naics = opportunity.get("naics_code")
        agency = opportunity.get("agency_code")
        psc = opportunity.get("psc_code")
        setaside = opportunity.get("set_aside_code")

        # Try from most specific to least specific
        queries = [
            {"naics_code": naics, "agency_code": agency, "psc_code": psc, "set_aside_code": setaside},
            {"naics_code": naics, "agency_code": agency, "set_aside_code": setaside},
            {"naics_code": naics, "agency_code": agency},
            {"naics_code": naics},
            {"agency_code": agency, "psc_code": psc},
        ]

        for query_params in queries:
            # Remove None values
            params = {k: v for k, v in query_params.items() if v}
            if not params:
                continue

            stats = self._get_cached_statistics(params)
            if stats and stats["sample_size"] >= self.LOW_CONFIDENCE_MIN:
                confidence = self._determine_confidence(stats["sample_size"])
                return {
                    "estimated_value_low": stats["p25_value"],
                    "estimated_value_mid": stats["median_value"],
                    "estimated_value_high": stats["p75_value"],
                    "confidence": confidence,
                    "sample_size": stats["sample_size"],
                    "range_p10_p90": (stats["p10_value"], stats["p90_value"]),
                    "query_used": params,
                }

        return {
            "estimated_value_low": None,
            "estimated_value_mid": None,
            "estimated_value_high": None,
            "confidence": "none",
            "sample_size": 0,
            "query_used": None,
        }

    def _get_cached_statistics(self, params: dict) -> Optional[dict]:
        """
        Look up pre-computed stats from value_statistics table.
        Returns None if no matching row exists.
        """
        # Query value_statistics table with exact match on provided params
        # NULL columns in DB match "not specified" in query
        # Implementation: build SQL WHERE clause from params
        pass  # Implement with SQLAlchemy or raw SQL

    def _determine_confidence(self, sample_size: int) -> str:
        if sample_size >= self.HIGH_CONFIDENCE_MIN:
            return "high"
        elif sample_size >= self.MEDIUM_CONFIDENCE_MIN:
            return "medium"
        else:
            return "low"


def compute_statistics_batch():
    """
    Nightly job: recompute value_statistics from historical_awards.
    Run this as a scheduled task (e.g., APScheduler or cron).
    """
    # Group by: naics_code, agency_code, psc_code, set_aside_code
    # For each combination with >= 5 records:
    #   Compute median, mean, p10, p25, p75, p90, min, max
    #   Upsert into value_statistics

    sql = """
    INSERT INTO value_statistics
        (naics_code, agency_code, psc_code, set_aside_code,
         sample_size, median_value, mean_value,
         p25_value, p75_value, p10_value, p90_value,
         min_value, max_value, last_computed)
    SELECT
        naics_code,
        agency_code,
        psc_code,
        set_aside_code,
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
    GROUP BY naics_code, agency_code, psc_code, set_aside_code
    HAVING COUNT(*) >= 5
    ON CONFLICT (naics_code, agency_code, psc_code, set_aside_code)
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
    """
    # Execute sql
    pass
```

### Display Format

On the opportunity card/detail page, show estimated value as:

```
Estimated Value: $250K – $1.2M (median $580K)
Confidence: ● High (based on 127 similar awards)
```

Color-code confidence: green = high, yellow = medium, red = low, gray = insufficient data.

---

## Feature 3: Go / Consider / Skip Decision Workflow

### Purpose

Let users triage opportunities with a simple 3-state workflow, turning the opportunity list from a passive feed into an active decision pipeline.

### Database Schema

```sql
-- User decisions on opportunities
CREATE TABLE opportunity_decisions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    decision VARCHAR(20) NOT NULL CHECK (decision IN ('go', 'consider', 'skip')),
    auto_classified BOOLEAN DEFAULT FALSE, -- TRUE if system pre-classified
    notes TEXT, -- Optional user notes on why
    decided_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, opportunity_id)
);

CREATE INDEX idx_decisions_user_decision ON opportunity_decisions(user_id, decision);
CREATE INDEX idx_decisions_user_opp ON opportunity_decisions(user_id, opportunity_id);

-- Track decision changes for analytics
CREATE TABLE decision_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    old_decision VARCHAR(20),
    new_decision VARCHAR(20) NOT NULL,
    changed_at TIMESTAMP DEFAULT NOW()
);
```

### Auto-Classification Logic

```python
# app/services/auto_classifier.py

class AutoClassifier:
    """
    Pre-classifies opportunities based on match score.
    Users can override at any time.
    """

    # Thresholds (configurable per user in the future)
    GO_THRESHOLD = 8.0
    CONSIDER_THRESHOLD = 5.0
    # Below CONSIDER_THRESHOLD = skip

    def classify(self, match_score: float) -> str:
        if match_score >= self.GO_THRESHOLD:
            return "go"
        elif match_score >= self.CONSIDER_THRESHOLD:
            return "consider"
        else:
            return "skip"

    def classify_batch(self, scored_opportunities: list[dict]) -> list[dict]:
        """
        Classify a batch of scored opportunities.
        Returns list with decision field added.
        """
        results = []
        for opp in scored_opportunities:
            decision = self.classify(opp["match_score"])
            results.append({
                **opp,
                "auto_decision": decision,
                "auto_classified": True,
            })
        return results
```

### API Endpoints

```python
# Decision CRUD
PUT    /api/v1/opportunities/:id/decision    # Set or update decision
GET    /api/v1/pipeline                       # Get opportunities grouped by decision
GET    /api/v1/pipeline/stats                 # Pipeline analytics

# Request body for PUT /decision:
# { "decision": "go", "notes": "Good fit for our SDVOSB cert" }

# Response for GET /pipeline:
# {
#   "go": [{ opportunity + score + estimated_value }, ...],
#   "consider": [...],
#   "skip": [...],
#   "unclassified": [...]  # New opportunities not yet triaged
# }
```

### Frontend: Pipeline Dashboard

The dashboard at `/dashboard/pipeline` should display:

```
┌─────────────────────────────────────────────────────────┐
│  PIPELINE OVERVIEW                              Filter ▾ │
│                                                          │
│  🟢 GO (12)      🟡 CONSIDER (34)     ⚫ SKIP (89)     │
│  $4.2M pipeline   $8.7M potential      Hidden by default │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  [Unclassified — 7 new opportunities]                    │
│  ┌──────────────────────────────────────────────────┐    │
│  │ DoD IT Modernization          Score: 9.2/10  🟢  │    │
│  │ Est. Value: $500K-$2M   NAICS ✓  SDVOSB ✓       │    │
│  │ Deadline: Apr 15, 2026                           │    │
│  │ [GO]  [CONSIDER]  [SKIP]                         │    │
│  └──────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────┐    │
│  │ VA Healthcare Support         Score: 6.1/10  🟡  │    │
│  │ Est. Value: $100K-$350K  NAICS ✓  Keywords 2/5   │    │
│  │ Deadline: Apr 22, 2026                           │    │
│  │ [GO]  [CONSIDER]  [SKIP]                         │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  ── GO (12 opportunities) ──────────────────────────     │
│  ... sorted by deadline, then score ...                  │
│                                                          │
│  ── CONSIDER (34 opportunities) ────────────────────     │
│  ... sorted by score desc ...                            │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Pipeline Analytics Endpoint

```python
# GET /api/v1/pipeline/stats

def get_pipeline_stats(user_id: int) -> dict:
    """
    Returns analytics about the user's decision patterns.
    Useful for profile optimization suggestions.
    """
    return {
        "total_opportunities": 142,
        "decisions": {
            "go": 12,
            "consider": 34,
            "skip": 89,
            "unclassified": 7
        },
        "estimated_pipeline_value": {
            "go_total_mid": 4200000,
            "consider_total_mid": 8700000
        },
        "skip_insights": {
            # Patterns in skipped opportunities for profile suggestions
            "top_skip_reasons": [
                {"reason": "NAICS mismatch", "count": 45, "pct": 50.5},
                {"reason": "Too large (size fit)", "count": 22, "pct": 24.7},
                {"reason": "No matching set-aside", "count": 12, "pct": 13.5}
            ],
            "suggestion": "You're skipping 50% of IT contracts outside your primary NAICS. Consider adding NAICS 541519 to your profile."
        },
        "deadlines_this_week": {
            "go": 3,
            "consider": 5
        }
    }
```

---

## Integration: How the Three Features Work Together

```
New SAM.gov Opportunity Ingested
            │
            ▼
    ┌───────────────────┐
    │  Value Estimator   │──→ estimated_value_low/mid/high
    │  (Feature 2)       │    confidence, sample_size
    └───────────────────┘
            │
            ▼
    ┌───────────────────┐
    │  Match Scorer      │──→ overall_score (0-10)
    │  (Feature 1)       │    naics/setaside/keyword/size/perf breakdown
    │  uses est. value   │
    └───────────────────┘
            │
            ▼
    ┌───────────────────┐
    │  Auto Classifier   │──→ go / consider / skip (pre-classification)
    │  (Feature 3)       │    auto_classified = true
    └───────────────────┘
            │
            ▼
    ┌───────────────────┐
    │  SendGrid Alert    │──→ Email with score + est. value + quick action buttons
    │  (existing)        │
    └───────────────────┘
            │
            ▼
    ┌───────────────────┐
    │  Dashboard         │──→ Pipeline view: GO | CONSIDER | SKIP
    │  (frontend)        │    User overrides auto-classification
    └───────────────────┘
            │
            ▼ (over time, user decisions feed back)
    ┌───────────────────┐
    │  Analytics Engine  │──→ Skip pattern insights
    │  (pipeline/stats)  │    Profile optimization suggestions
    └───────────────────┘
```

---

## Implementation Order

### Phase 1: Company Profile & Match Score (Week 1-2)
1. Create DB migrations for `company_profiles`, `company_naics`, `company_certifications`, `company_keywords`, `opportunity_match_scores`
2. Build profile API endpoints (CRUD)
3. Implement `MatchScorer` (start without past_performance and size_fit — hardcode neutral scores)
4. Build profile setup UI (multi-step wizard)
5. Integrate scoring into opportunity ingestion pipeline
6. Display scores on opportunity list and detail pages
7. Update email templates with match score

### Phase 2: Estimated Contract Value (Week 3-4)
1. Create DB migrations for `historical_awards`, `value_statistics`, opportunity columns
2. Build `USASpendingFetcher` — fetch last 5 years of awards for your most common NAICS codes
3. Run `compute_statistics_batch()` to populate `value_statistics`
4. Implement `ContractValueEstimator`
5. Integrate estimation into opportunity ingestion pipeline
6. Display estimated values on cards and detail pages
7. Wire up size_fit_score in MatchScorer (now has estimated_value data)
8. Set up nightly cron for statistics recomputation

### Phase 3: Go / Consider / Skip Workflow (Week 5-6)
1. Create DB migrations for `opportunity_decisions`, `decision_history`
2. Implement `AutoClassifier`
3. Build decision API endpoints
4. Build pipeline dashboard UI
5. Integrate auto-classification into scoring pipeline
6. Add quick-action buttons to email alerts
7. Build pipeline analytics endpoint

### Phase 4: Polish & Analytics (Week 7-8)
1. Add `company_past_performance` table and scoring
2. Build skip insights / profile suggestion engine
3. Add pipeline value tracking (total $$ in Go/Consider)
4. Add deadline-aware sorting and urgency indicators
5. Build user preference for auto-classification thresholds
6. Performance optimization: batch scoring, caching, query optimization
7. Add filter/sort options to pipeline view

---

## Tier Feature Gating

| Feature | Basic ($79) | Professional ($179) | Agency ($349) |
|---------|-------------|---------------------|---------------|
| Match Score | ✓ (simplified: NAICS + set-aside only) | ✓ (full 5-factor scoring) | ✓ (full + custom weights) |
| Estimated Value | Range only (e.g., "$100K-$500K") | Full breakdown + confidence | Full + historical trend chart |
| Go/Consider/Skip | ✓ (manual only) | ✓ (auto-classification) | ✓ (auto + analytics + suggestions) |
| Pipeline Analytics | Basic counts | Full stats | Full + export + weekly report |
| Profile Keywords | Up to 10 | Up to 50 | Unlimited |
| Past Performance | — | Up to 10 contracts | Unlimited |

---

## Bug Fix: Blog Article Pages Returning "Service Unavailable"

### Problem

The blog section's index/listing page loads correctly, but when a user clicks on an individual article, the page returns a **"Service Unavailable"** error. This suggests the issue is specific to the article detail route, not the blog system as a whole.

### Likely Causes (investigate in this order)

1. **Route definition mismatch** — The blog article route (e.g., `/blog/<slug>` or `/newsletter/<id>`) may not be correctly registered, or the route parameter (slug/id) isn't matching. Check `app.py` or the blog blueprint for the article detail route and verify it's registered with the correct URL pattern.

2. **Template rendering error** — The article detail template may reference a variable or filter that throws an exception (e.g., `article.content | markdown` with a missing markdown filter, or accessing an attribute that doesn't exist on the article object). Check Flask logs on Railway for a `500 Internal Server Error` or `Jinja2` template error that's being caught and returned as "Service Unavailable."

3. **Database query failure** — The query fetching a single article by slug/id may be failing silently. Possible causes: the slug column doesn't exist or has a different name than what the route handler expects, or there's a missing `WHERE` clause, or the query returns `None` and the template tries to render it without a null check.

4. **Middleware or error handler masking the real error** — A custom error handler or middleware (e.g., rate limiter, auth check) might be catching the real exception and returning a generic "Service Unavailable" page. Check if there's a `@app.errorhandler(503)` or a try/except block wrapping the route.

5. **Railway-specific timeout** — If the article detail view makes an external API call (e.g., fetching content from a CMS, rendering markdown via an external service), it could be timing out. Railway has a default request timeout; long-running requests get a 503.

### Debugging Steps

```python
# 1. Check Railway logs for the actual error
# In Railway dashboard → Deployments → Logs
# Look for the traceback when hitting a blog article URL

# 2. Add explicit error logging to the blog article route
@blog_bp.route('/blog/<slug>')
def article_detail(slug):
    try:
        article = get_article_by_slug(slug)  # or however articles are fetched
        if not article:
            abort(404)
        return render_template('blog/article.html', article=article)
    except Exception as e:
        import traceback
        app.logger.error(f"Blog article error for slug '{slug}': {e}")
        app.logger.error(traceback.format_exc())
        raise  # Re-raise so Flask shows the real error in logs

# 3. Test locally with debug mode
# FLASK_DEBUG=1 flask run
# Then hit http://localhost:5000/blog/<any-slug> and check the traceback

# 4. Verify the route is registered
# Add temporarily to check:
# print(app.url_map)
# Look for the blog article route in the output
```

### Common Fixes

```python
# Fix A: Route not registered (if using a Blueprint)
# Make sure the blueprint is registered in app.py:
from routes.blog import blog_bp
app.register_blueprint(blog_bp)

# Fix B: Missing slug/id in database
# Ensure articles have slugs generated on creation:
from slugify import slugify
article.slug = slugify(article.title)

# Fix C: Template variable missing
# In the template, add a safe fallback:
# {{ article.content | default('Content not available') }}

# Fix D: Null article not handled
@blog_bp.route('/blog/<slug>')
def article_detail(slug):
    article = Article.query.filter_by(slug=slug, published=True).first()
    if article is None:
        abort(404)  # Instead of crashing with AttributeError
    return render_template('blog/article.html', article=article)
```

### Priority

This is a **P1 bug** — the blog/newsletter is a key content marketing channel for TenderSentinel. Fix this before starting work on the new features above, since it affects the public-facing site and SEO.

---

## Technical Notes

- **Railway Scheduler:** Use APScheduler or Railway's built-in cron for nightly jobs (statistics recomputation, historical data fetching)
- **USASpending API:** Free, no auth needed, but rate-limited — implement exponential backoff and cache aggressively
- **FPDS Bulk Data:** Available as CSV extracts at fpds.gov — consider a one-time bulk load for historical data, then incremental updates via USASpending API
- **Performance:** Match scoring is CPU-light but high-volume. For 1000 active opportunities × 100 users = 100K score computations. Batch with bulk INSERTs, not individual queries
- **PostgreSQL Percentiles:** `PERCENTILE_CONT` is available natively — no extensions needed
- **Migration Safety:** All schema changes use `ALTER TABLE ... ADD COLUMN` with defaults or NULLs — no downtime required on Railway
