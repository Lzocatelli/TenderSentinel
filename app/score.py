import re
import math
from typing import List, Optional


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text.lower()).strip()
    return [t for t in text.split() if t]


def _keyword_score(title: str, keywords: List[str]) -> float:
    """
    Keyword match score (0–6).
    Phrase matches (multi-word) count double.
    """
    if not title or not keywords:
        return 0.0

    text = title.lower()
    tokens = _tokenize(text)
    token_set = set(tokens)
    keywords = [k.strip().lower() for k in keywords if k.strip()]

    hits = 0
    phrase_hits = 0

    for kw in keywords:
        if " " in kw:
            if kw in text:
                phrase_hits += 1
        elif kw in token_set:
            hits += 1

    density = (hits + 2 * phrase_hits) / max(12, len(tokens))
    raw = hits + 2 * phrase_hits + (1 if density >= 0.06 else 0)

    if raw <= 0:
        return 0.0

    return min(2.0 + raw * 1.5, 6.0)


def _naics_score(opportunity_naics: Optional[str], user_naics: List[str]) -> float:
    """
    NAICS match score (0–3).
    Exact 6-digit match = 3.0
    4-digit industry group match = 1.5
    2-digit sector match = 0.5
    """
    if not opportunity_naics or not user_naics:
        return 0.0

    opp = str(opportunity_naics).strip()

    for user_code in user_naics:
        u = str(user_code).strip()

        if opp == u:
            return 3.0

        # 4-digit industry group
        if len(opp) >= 4 and len(u) >= 4 and opp[:4] == u[:4]:
            return 1.5

        # 2-digit sector
        if len(opp) >= 2 and len(u) >= 2 and opp[:2] == u[:2]:
            return 0.5

    return 0.0


def _set_aside_score(opportunity_set_aside: Optional[str], user_set_asides: List[str]) -> float:
    """
    +1.0 if the opportunity's set-aside matches one the user qualifies for.
    Common codes: SBA, 8A, HZC (HUBZone), WOSB, EDWOSB, SDVOSB, VSB
    """
    if not opportunity_set_aside or not user_set_asides:
        return 0.0

    opp_sa = opportunity_set_aside.strip().upper()
    user_sa = [s.strip().upper() for s in user_set_asides]

    return 1.0 if opp_sa in user_sa else 0.0


def _value_bonus(value: Optional[float]) -> float:
    """
    Logarithmic value bonus (0–1).
    $10k = +0.3, $100k = +0.6, $1M = +0.9, $10M+ = +1.0
    """
    if not value or value <= 0:
        return 0.0
    try:
        return min(math.log10(value / 10_000 + 1) * 0.5, 1.0)
    except Exception:
        return 0.0


def calculate_score(
    title: str,
    keywords: List[str],
    value: float = None,
    naics_code: str = None,
    user_naics: List[str] = None,
    set_aside: str = None,
    user_set_asides: List[str] = None,
) -> int:
    """
    Relevance score (0–10) for a SAM.gov opportunity.

    Breakdown:
    - Keyword match:   0–6 pts
    - NAICS match:     0–3 pts
    - Set-aside match: 0–1 pt
    - Value bonus:     0–1 pt (log scale, USD)
    """
    score = 0.0
    score += _keyword_score(title, keywords or [])
    score += _naics_score(naics_code, user_naics or [])
    score += _set_aside_score(set_aside, user_set_asides or [])
    score += _value_bonus(value)

    return max(0, min(10, round(score)))


# Legacy alias for backwards compat
calcular_score = calculate_score
