"""
Shared configuration and constants for TenderSentinel.
"""

import os
import logging

from dotenv import load_dotenv

load_dotenv(override=False)

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("tendersentinel")

# ── URLs ─────────────────────────────────────────────────────────────────────

BASE_URL = os.getenv("BASE_URL", "https://tendersentinel.com")

# ── Plan limits ──────────────────────────────────────────────────────────────

PLAN_LIMITS = {
    "basic": 5,
    "basico": 5,
    "professional": 20,
    "profissional": 20,
    "agency": None,  # unlimited
    "agencia": None,
}

FREE_KEYWORD_LIMIT = 1

# ── Feature gating per plan ──────────────────────────────────────────────────

PLAN_FEATURES = {
    None: {  # free / trial
        "score_factors": 2,           # NAICS + set-aside only
        "estimated_value": "range",   # low-high only, no median/confidence
        "auto_classify": False,
        "pipeline_dashboard": False,
        "past_performance_limit": 0,
        "profile_keywords_limit": 5,
        "ai_summary": False,
    },
    "basic": {
        "score_factors": 2,
        "estimated_value": "range",
        "auto_classify": False,
        "pipeline_dashboard": True,
        "past_performance_limit": 0,
        "profile_keywords_limit": 10,
        "ai_summary": False,
    },
    "basico": None,  # alias → resolved at runtime
    "professional": {
        "score_factors": 5,           # full 5-factor scoring
        "estimated_value": "full",    # range + median + confidence
        "auto_classify": True,
        "pipeline_dashboard": True,
        "past_performance_limit": 10,
        "profile_keywords_limit": 50,
        "ai_summary": True,
    },
    "profissional": None,  # alias → resolved at runtime
    "agency": {
        "score_factors": 5,
        "estimated_value": "full",
        "auto_classify": True,
        "pipeline_dashboard": True,
        "past_performance_limit": None,  # unlimited
        "profile_keywords_limit": None,  # unlimited
        "custom_weights": True,
        "pipeline_export": True,
        "skip_insights": True,
        "ai_summary": True,
    },
    "agencia": None,  # alias → resolved at runtime
}

# Alias resolution
PLAN_FEATURES["basico"] = PLAN_FEATURES["basic"]
PLAN_FEATURES["profissional"] = PLAN_FEATURES["professional"]
PLAN_FEATURES["agencia"] = PLAN_FEATURES["agency"]


def get_plan_features(plan: str | None) -> dict:
    """Get feature flags for a given plan name."""
    return PLAN_FEATURES.get(plan) or PLAN_FEATURES[None]


# English display name for a plan, regardless of which slug is stored —
# some accounts still carry the pre-anglicization pt-BR value (e.g.
# "gratuito") in clientes.plano, so this can't just title-case the raw value.
PLAN_DISPLAY_NAMES = {
    None: "Free",
    "gratuito": "Free",
    "basic": "Basic",
    "basico": "Basic",
    "professional": "Professional",
    "profissional": "Professional",
    "agency": "Agency",
    "agencia": "Agency",
}


def plan_display_name(plan: str | None) -> str:
    """Human-readable, English plan name for display in templates."""
    return PLAN_DISPLAY_NAMES.get(plan, "Free")


# ── Dashboard / Export ───────────────────────────────────────────────────────

DASHBOARD_LIMIT = 50
CSV_EXPORT_LIMIT = 500
COUNTER_CACHE_TTL_MINUTES = 5

# ── AI Summaries (optional — disabled if ANTHROPIC_API_KEY is unset) ────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
AI_SUMMARY_MODEL = os.getenv("AI_SUMMARY_MODEL", "claude-haiku-4-5-20251001")
ai_summary_enabled = bool(ANTHROPIC_API_KEY)

# ── Stripe ───────────────────────────────────────────────────────────────────

TRIAL_PERIOD_DAYS = 7

# ── Set-aside types ──────────────────────────────────────────────────────────

VALID_SET_ASIDES = {"SBA", "8A", "HZC", "WOSB", "EDWOSB", "SDVOSB", "VSB"}

# ── SAM.gov notice types ─────────────────────────────────────────────────────
#
# SAM.gov's Contract Opportunities feed mixes several notice types in one
# stream: open solicitations, but also presolicitation forecasts, sources-sought
# market research, award notices (the contract is already decided), sole-source
# justifications, and a few rarer ones. None of those last few are something a
# user can bid on today, so counting them as "opportunities" alongside open
# solicitations inflates every count derived from `licitacoes`.
#
# This is a BLOCKLIST, not an allowlist: an unrecognized or newly-introduced
# notice_type value defaults to INCLUDED. SAM.gov can rename or add types, and
# `notice_type` is NULL for rows ingested before this field existed — in both
# cases the safe failure mode is "still show it" rather than silently hiding a
# real open solicitation because we didn't recognize its label.
#
# Reflects the taxonomy SAM.gov's public API documented at the time this was
# written (the "type" field on each item in `opportunitiesData`) — verify
# against a live API response if these ever look stale.
NON_COMPETITIVE_NOTICE_TYPES = {
    "Presolicitation",
    "Sources Sought",
    "Special Notice",
    "Award Notice",
    "Justification",
    "Sale of Surplus Property",
    "Intent to Bundle Requirements (DoD-Funded)",
    "Fair Opportunity / Limited Sources Justification",
}

# Display labels, e.g. for a badge on the dashboard. Falls back to the raw
# notice_type (or "Opportunity" if unset) for anything not listed here.
NOTICE_TYPE_LABELS = {
    "Solicitation": "Open for bids",
    "Combined Synopsis/Solicitation": "Open for bids",
    "Presolicitation": "Forecast",
    "Sources Sought": "Sources sought",
    "Special Notice": "Special notice",
    "Award Notice": "Awarded",
    "Justification": "Sole source",
    "Sale of Surplus Property": "Surplus sale",
    "Intent to Bundle Requirements (DoD-Funded)": "Bundling intent",
    "Fair Opportunity / Limited Sources Justification": "Limited sources",
}


def open_for_bids_filter():
    """
    SQL fragment (and its one param) that excludes known non-competitive
    notice types from a `licitacoes` query. `notice_type` only exists on that
    table, so this is safe to drop into any query touching it regardless of
    alias or joins.

    Usage:
        frag, non_competitive = open_for_bids_filter()
        cur.execute(f"SELECT ... WHERE ... AND {frag}", [*other_params, non_competitive])
    """
    return (
        "(notice_type IS NULL OR NOT (notice_type = ANY(%s)))",
        list(NON_COMPETITIVE_NOTICE_TYPES),
    )

# ── Email banner (shared by alertas and relatorio) ───────────────────────────

EMAIL_BANNER = """
<div style="background:linear-gradient(135deg,#131b2e 0%,#1c2b47 100%);padding:28px 32px;text-align:center;border-radius:12px 12px 0 0">
    <div style="font-size:28px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;font-family:Inter,system-ui,-apple-system,'Segoe UI',sans-serif">
        Tender<span style="color:#fc7218">Sentinel</span>
    </div>
    <div style="font-size:11px;letter-spacing:2.5px;text-transform:uppercase;color:rgba(255,255,255,0.45);margin-top:5px;font-family:Inter,system-ui,-apple-system,'Segoe UI',sans-serif">
        Smart Federal Contract Monitor
    </div>
</div>
"""
