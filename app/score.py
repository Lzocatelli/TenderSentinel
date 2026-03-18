import re
import math
from typing import List


def _tokenize(texto: str) -> List[str]:
    if not texto:
        return []
    texto = re.sub(r"[^0-9a-zA-ZÀ-ÿ]+", " ", texto.lower()).strip()
    return [t for t in texto.split() if t]


def _heuristic_score(objeto: str, palavras_chave: List[str], valor: float = None) -> int:
    """
    Score baseado em correspondência de palavras-chave + bônus por valor.
    Retorna inteiro de 0 a 10.
    """
    if not objeto:
        return 0

    texto = objeto.lower()
    palavras = [p.strip().lower() for p in (palavras_chave or []) if p.strip()]

    if not palavras:
        return 0

    tokens = _tokenize(texto)
    if not tokens:
        return 0

    token_set = set(tokens)
    hits = 0
    hits_frase = 0

    for p in palavras:
        # Frases compostas: exige presença como substring
        if " " in p:
            if p in texto:
                hits_frase += 1
            continue
        if p in token_set:
            hits += 1

    # Densidade evita textos enormes com 1 hit parecerem tão bons
    densidade = (hits + 2 * hits_frase) / max(12, len(tokens))
    bruto = hits + 2 * hits_frase + (1 if densidade >= 0.06 else 0)

    if bruto <= 0:
        return 0

    # Converte bruto para escala 0-10
    # 1 hit = 4, 2 hits = 6, 3+ hits = 8, com bônus de valor chegando a 10
    score_base = min(2 + bruto * 2, 8)

    # Bônus por valor do contrato (escala logarítmica)
    bonus_valor = 0
    if valor and valor > 0:
        try:
            # R$10k = +0.5, R$100k = +1.0, R$1M = +1.5
            bonus_valor = min(math.log10(valor / 10_000 + 1) * 0.75, 2.0)
        except Exception:
            pass

    score_final = round(score_base + bonus_valor)
    return max(0, min(10, score_final))


def calcular_score(objeto: str, palavras_chave: List[str], valor: float = None) -> int:
    """
    Calcula score de oportunidade (0-10) para uma licitação.
    Estratégia atual: heurística estatística.
    Futuramente: Claude Haiku atrás de feature flag.
    """
    return _heuristic_score(objeto, palavras_chave, valor)