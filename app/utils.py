# Fonte única de verdade para limites de plano e helpers reutilizáveis

PLANO_LIMITES = {
    "basico": 5,
    "profissional": 20,
    "agencia": None,  # ilimitado
}


def limite_palavras(plano):
    """Retorna o máximo de palavras-chave permitido. None = ilimitado."""
    if not plano:
        return 1
    return PLANO_LIMITES.get(plano, 1)


def formatar_moeda(valor):
    """Formata um valor numérico como moeda brasileira (R$ 1.234,56)."""
    if valor is None:
        return "Não informado"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "Não informado"
