import requests
import os
import time
from datetime import date, timedelta
from dotenv import load_dotenv
from app.database import conectar

load_dotenv()

SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"


def buscar_licitacoes(data_inicio=None, data_fim=None):
    if not data_inicio:
        data_inicio = (date.today() - timedelta(days=1)).strftime("%m/%d/%Y")
    if not data_fim:
        data_fim = date.today().strftime("%m/%d/%Y")

    api_key = os.getenv("SAM_API_KEY")
    todas = []
    offset = 0
    limit = 1000

    params = {
        "api_key": api_key,
        "postedFrom": data_inicio,
        "postedTo": data_fim,
        "limit": limit,
        "offset": offset,
    }

    for tentativa in range(3):
        try:
            response = requests.get(SAM_API_URL, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                todas = data.get("opportunitiesData", [])
                return todas
            else:
                print(f"SAM.gov error: {response.status_code}")
                return todas

        except requests.exceptions.Timeout:
            print(f"SAM.gov timeout (attempt {tentativa + 1}/3)...")
            if tentativa < 2:
                time.sleep(3)
            else:
                print("SAM.gov did not respond after 3 attempts.")

    return todas


def salvar_licitacoes(licitacoes):
    if not licitacoes:
        print("No opportunities found.")
        return 0

    conn = conectar()
    cur = conn.cursor()
    salvas = 0

    for item in licitacoes:
        try:
            # Parse state from place of performance
            pop = item.get("placeOfPerformance") or {}
            state = (pop.get("state") or {}).get("code")

            # Parse deadline date
            deadline_raw = item.get("responseDeadLine")
            deadline = deadline_raw[:10] if deadline_raw else None

            # Parse posted date
            posted_raw = item.get("postedDate")
            posted = posted_raw[:10] if posted_raw else None

            cur.execute("""
                INSERT INTO licitacoes
                    (sam_id, orgao, objeto, data_publicacao, link, uf, naics_code, set_aside, deadline)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sam_id) DO NOTHING
            """, (
                item.get("noticeId"),
                item.get("fullParentPathName"),
                item.get("title"),
                posted,
                item.get("uiLink"),
                state,
                item.get("naicsCode"),
                item.get("typeOfSetAside") or None,
                deadline,
            ))
            if cur.rowcount > 0:
                salvas += 1
        except Exception as e:
            print(f"Error saving opportunity: {e}")
            conn.rollback()
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
            SELECT sam_id, orgao, objeto, deadline, data_publicacao, link, naics_code, set_aside
            FROM licitacoes
            WHERE LOWER(objeto) LIKE %s
        """, (f"%{palavra.lower()}%",))
        resultados.extend(cur.fetchall())

    cur.close()
    conn.close()
    return resultados
