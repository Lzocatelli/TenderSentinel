PLANO_LIMITES = {
    "basico": 5,
    "profissional": 20,
    "agencia": None,  # unlimited
}


def limite_palavras(plano):
    """Returns the max keywords allowed. None = unlimited."""
    if not plano:
        return 1
    return PLANO_LIMITES.get(plano, 1)


def formatar_moeda(valor):
    """Formats a numeric value as USD (e.g. $1,234.56)."""
    if valor is None:
        return "N/A"
    try:
        return f"${float(valor):,.2f}"
    except Exception:
        return "N/A"
