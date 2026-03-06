from app.scraper import buscar_licitacoes, salvar_licitacoes
from app.alertas import disparar_alertas

def buscar_e_alertar():
    print("Iniciando busca de licitações...")
    licitacoes = buscar_licitacoes()
    
    # Salva no banco e retorna a quantidade
    total = salvar_licitacoes(licitacoes)
    print(f"{total} licitações novas salvas.")

    print("Disparando alertas...")
    disparar_alertas()
    
    print("Ciclo concluído!")