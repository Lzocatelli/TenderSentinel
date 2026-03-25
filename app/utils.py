from app.config import PLAN_LIMITS, FREE_KEYWORD_LIMIT


def keyword_limit(plan):
    """Returns the max keywords allowed. None = unlimited."""
    if not plan:
        return FREE_KEYWORD_LIMIT
    return PLAN_LIMITS.get(plan, FREE_KEYWORD_LIMIT)


def format_currency(value):
    """Formats a numeric value as USD (e.g. $1,234.56)."""
    if value is None:
        return "N/A"
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "N/A"


# Legacy aliases for backwards compat during migration
limite_palavras = keyword_limit
formatar_moeda = format_currency
