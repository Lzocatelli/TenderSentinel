from app.scraper import buscar_licitacoes, salvar_licitacoes, filtrar_por_palavra_chave

if __name__ == "__main__":
    print("Buscando licitações...")
    dados = buscar_licitacoes()
    
    print(f"Resposta da API: {dados}")