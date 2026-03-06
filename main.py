from app.scraper import buscar_licitacoes, salvar_licitacoes
from app.alertas import disparar_alertas


if __name__ == "__main__":
    print("=== LicitaBot — execução única (produção) ===")

    print("\n1. Buscando licitações no portal...")
    licitacoes = buscar_licitacoes()
    total = salvar_licitacoes(licitacoes)
    print(f"{total} licitações novas salvas no banco.")

    print("\n2. Disparando alertas para os clientes ativos...")
    disparar_alertas()

    print("\nExecução concluída com sucesso.")