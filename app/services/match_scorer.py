"""
Match scoring engine for TenderSentinel.
Scores SAM.gov opportunities against a user's company profile on a 0-10 scale.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger("tendersentinel.match_scorer")


@dataclass
class MatchBreakdown:
    naics_score: float = 0.0       # max 3.0
    setaside_score: float = 0.0    # max 2.5
    keyword_score: float = 0.0     # max 2.0
    size_fit_score: float = 0.0    # max 1.5
    past_perf_score: float = 0.0   # max 1.0

    @property
    def overall(self) -> float:
        return round(
            self.naics_score
            + self.setaside_score
            + self.keyword_score
            + self.size_fit_score
            + self.past_perf_score,
            1,
        )

    def to_dict(self) -> dict:
        return {
            "overall_score": self.overall,
            "naics_score": self.naics_score,
            "setaside_score": self.setaside_score,
            "keyword_score": self.keyword_score,
            "size_fit_score": self.size_fit_score,
            "past_perf_score": self.past_perf_score,
        }


# SAM.gov set-aside codes → certification types
_SETASIDE_TO_CERT = {
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

# Revenue range midpoints for size-fit scoring
_REVENUE_MIDPOINTS = {
    "<1M": 500_000,
    "1M-5M": 3_000_000,
    "5M-25M": 15_000_000,
    "25M+": 50_000_000,
}


class MatchScorer:
    """Scores an opportunity against a company profile. Total max = 10.0."""

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
        opp_naics = opp.get("naics_code", "")
        if not opp_naics:
            return self.NAICS_MAX * 0.5

        user_naics = profile.get("naics_codes", [])
        primary_codes = [n["code"] for n in user_naics if n.get("is_primary")]
        secondary_codes = [n["code"] for n in user_naics if not n.get("is_primary")]

        if opp_naics in primary_codes:
            return self.NAICS_MAX

        if opp_naics in secondary_codes:
            return round(self.NAICS_MAX * 0.83, 1)  # 2.5

        all_codes = primary_codes + secondary_codes
        opp_prefix_4 = opp_naics[:4]
        if any(code[:4] == opp_prefix_4 for code in all_codes):
            return self.NAICS_MAX * 0.5  # 1.5

        opp_prefix_2 = opp_naics[:2]
        if any(code[:2] == opp_prefix_2 for code in all_codes):
            return round(self.NAICS_MAX * 0.17, 1)  # 0.5

        return 0.0

    def _score_setaside(self, opp: dict, profile: dict) -> float:
        opp_setaside = opp.get("set_aside", "") or ""
        user_certs = [c["type"] for c in profile.get("certifications", [])]

        if not opp_setaside or opp_setaside.upper() in ("NONE", ""):
            return round(self.SETASIDE_MAX * 0.6, 1)

        required_cert = _SETASIDE_TO_CERT.get(opp_setaside.upper())
        if required_cert and required_cert in user_certs:
            return self.SETASIDE_MAX
        elif required_cert and required_cert not in user_certs:
            return round(self.SETASIDE_MAX * 0.2, 1)

        return round(self.SETASIDE_MAX * 0.4, 1)

    def _score_keywords(self, opp: dict, profile: dict) -> float:
        opp_text = (opp.get("objeto", "") or "").lower()
        if not opp_text.strip():
            return 0.0

        user_keywords = profile.get("keywords", [])
        if not user_keywords:
            return self.KEYWORD_MAX * 0.5

        total_weight = sum(kw.get("weight", 1.0) for kw in user_keywords)
        matched_weight = sum(
            kw.get("weight", 1.0)
            for kw in user_keywords
            if kw["keyword"].lower() in opp_text
        )

        ratio = matched_weight / total_weight if total_weight > 0 else 0
        return round(ratio * self.KEYWORD_MAX, 2)

    def _score_size_fit(self, opp: dict, profile: dict) -> float:
        estimated_value = opp.get("estimated_value_mid")
        revenue_range = profile.get("annual_revenue_range")
        annual_revenue = _REVENUE_MIDPOINTS.get(revenue_range)

        if not estimated_value or not annual_revenue:
            return round(self.SIZE_FIT_MAX * 0.5, 1)

        ratio = estimated_value / annual_revenue if annual_revenue > 0 else 0

        if 0.05 <= ratio <= 0.50:
            return self.SIZE_FIT_MAX
        elif 0.01 <= ratio < 0.05 or 0.50 < ratio <= 1.0:
            return round(self.SIZE_FIT_MAX * 0.6, 1)
        elif ratio > 1.0:
            return round(self.SIZE_FIT_MAX * 0.2, 1)
        else:
            return round(self.SIZE_FIT_MAX * 0.3, 1)

    def _score_past_performance(self, opp: dict, profile: dict) -> float:
        past_perf = profile.get("past_performance", [])
        if not past_perf:
            return round(self.PAST_PERF_MAX * 0.3, 1)

        opp_naics = opp.get("naics_code", "")
        opp_agency = (opp.get("orgao", "") or "").lower()

        naics_match = any(pp.get("naics_code") == opp_naics for pp in past_perf)
        agency_match = any(opp_agency in (pp.get("agency", "") or "").lower() for pp in past_perf)

        if naics_match and agency_match:
            return self.PAST_PERF_MAX
        elif naics_match or agency_match:
            return round(self.PAST_PERF_MAX * 0.6, 1)
        else:
            return round(self.PAST_PERF_MAX * 0.2, 1)
