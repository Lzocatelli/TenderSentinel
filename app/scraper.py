import requests
import os
from datetime import date, timedelta
from app.database import conectar

MODALIDADES = [4, 5, 6, 7]  # Concorrência, Pregão, Dispensa, Inexigibilidade

def buscar_licitacoes(data_inicio=None, data_fim=None, pagina=1):
    if not data_inicio:
        data_inicio = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    if not data_fim:
        data_fim = date.today().strftime("%Y%m%d")

    url = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
    todas = []

    for modalidade in MODALIDADES:
        params = {
            "dataInicial": data_inicio,
            "dataFinal": data_fim,
            "pagina": pagina,
            "tamanhoPagina": 50,
            "codigoModalidadeContratacao": modalidade
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                dados = response.json()
                todas.extend(dados.get("data", []))
            else:
                print(f"Erro modalidade {modalidade}: {response.status_code}")
        except Exception as e:
            print(f"Erro na requisição: {e}")

    return todas

def salvar_licitacoes(licitacoes):
    if not licitacoes:
        print("Nenhuma licitação encontrada.")
        return 0

    conn = conectar()
    cur = conn.cursor()
    salvas = 0

    for item in licitacoes:
        try:
            cur.execute("""
                INSERT INTO licitacoes (pncp_id, orgao, objeto, valor, data_publicacao, link)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (pncp_id) DO NOTHING
            """, (
                item.get("numeroControlePNCP"),
                item.get("orgaoEntidade", {}).get("razaoSocial"),
                item.get("objetoCompra"),
                item.get("valorTotalEstimado"),
                item.get("dataPublicacaoPncp", "")[:10] if item.get("dataPublicacaoPncp") else None,
                item.get("linkSistemaOrigem")
            ))
            if cur.rowcount > 0:
                salvas += 1
        except Exception as e:
            print(f"Erro ao salvar: {e}")
            continue

    conn.commit()
    cur.close()
    conn.close()
    return salvas

def filtrar_por_palavra_chave(palavras_chave):
    conn = conectar()
    cur = conn.cursor()
    resultados = []

    for palavra in palavras_chave:
        cur.execute("""
            SELECT pncp_id, orgao, objeto, valor, data_publicacao, link
            FROM licitacoes
            WHERE LOWER(objeto) LIKE %s
        """, (f"%{palavra.lower()}%",))
        resultados.extend(cur.fetchall())

    cur.close()
    conn.close()
    return resultados