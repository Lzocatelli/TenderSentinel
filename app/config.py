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
    },
    "basic": {
        "score_factors": 2,
        "estimated_value": "range",
        "auto_classify": False,
        "pipeline_dashboard": True,
        "past_performance_limit": 0,
        "profile_keywords_limit": 10,
    },
    "basico": None,  # alias → resolved at runtime
    "professional": {
        "score_factors": 5,           # full 5-factor scoring
        "estimated_value": "full",    # range + median + confidence
        "auto_classify": True,
        "pipeline_dashboard": True,
        "past_performance_limit": 10,
        "profile_keywords_limit": 50,
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


# ── Dashboard / Export ───────────────────────────────────────────────────────

DASHBOARD_LIMIT = 50
CSV_EXPORT_LIMIT = 500
COUNTER_CACHE_TTL_MINUTES = 5

# ── Stripe ───────────────────────────────────────────────────────────────────

TRIAL_PERIOD_DAYS = 7

# ── Set-aside types ──────────────────────────────────────────────────────────

VALID_SET_ASIDES = {"SBA", "8A", "HZC", "WOSB", "EDWOSB", "SDVOSB", "VSB"}

# ── Email banner (shared by alertas and relatorio) ───────────────────────────

EMAIL_BANNER = """
<div style="background:linear-gradient(135deg,#0f1f3d 0%,#1a3a6b 100%);padding:28px 32px;text-align:center;border-radius:12px 12px 0 0">
    <div style="font-size:28px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;font-family:Georgia,serif">
        Tender<span style="color:#d4af37">Sentinel</span>
    </div>
    <div style="font-size:11px;letter-spacing:2.5px;text-transform:uppercase;color:rgba(255,255,255,0.45);margin-top:5px">
        Smart Federal Contract Monitor
    </div>
</div>
"""
