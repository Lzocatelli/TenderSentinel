import re
from typing import List


def _tokenize(texto: str) -> List[str]:
    if not texto:
        return []
    # Mantém letras/números e separa por espaços; bom o suficiente para PT-BR.
    texto = re.sub(r"[^0-9a-zA-ZÀ-ÿ]+", " ", texto.lower()).strip()
    return [t for t in texto.split() if t]


def _heuristic_score(objeto: str, palavras_chave: List[str]) -> int:
    """
    Fallback simples baseado em correspondência de palavras‑chave.
    Retorna um score inteiro de 1 a 5.
    """
    if not objeto:
        return 1

    texto = objeto.lower()
    palavras = [p.strip().lower() for p in (palavras_chave or []) if p.strip()]
    if not palavras:
        return 3

    tokens = _tokenize(texto)
    if not tokens:
        return 2

    token_set = set(tokens)
    hits = 0
    hits_frase = 0

    for p in palavras:
        # Se a keyword for frase, exige presença como substring.
        if " " in p:
            if p in texto:
                hits_frase += 1
            continue
        if p in token_set:
            hits += 1

    # Leve ajuste por densidade (evita textos enormes com 1 hit parecerem tão bons)
    densidade = (hits + 2 * hits_frase) / max(12, len(tokens))
    bruto = hits + 2 * hits_frase + (1 if densidade >= 0.06 else 0)

    if bruto <= 0:
        return 2
    if bruto == 1:
        return 3
    if bruto == 2:
        return 4
    return 5


def calcular_score(objeto: str, palavras_chave: List[str]) -> int:
    """
    Calcula um score de oportunidade (1–5) para uma licitação.

    Estratégia:
    - Por enquanto (fase de validação), calcula localmente via heurística.
    - Quando quiser reativar IA, podemos colocar atrás de um feature flag.
    """
    return _heuristic_score(objeto, palavras_chave)

