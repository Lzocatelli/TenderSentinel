from app.scraper import buscar_licitacoes, salvar_licitacoes
from app.alertas import disparar_alertas, enviar_email
import os
import traceback
from dotenv import load_dotenv

load_dotenv(override=False)


if __name__ == "__main__":
    print("=== TenderSentinel — execução única (produção) ===")

    try:
        print("\n1. Buscando licitações no portal...")
        licitacoes = buscar_licitacoes()
        total = salvar_licitacoes(licitacoes)
        print(f"{total} licitações novas salvas no banco.")

        print("\n2. Disparando alertas para os clientes ativos...")
        disparar_alertas()

        print("\nExecução concluída com sucesso.")

    except Exception as e:
        msg = f"Erro no job TenderSentinel:\n\n{traceback.format_exc()}"
        print(msg)

        admin_email = os.getenv("ADMIN_EMAIL")
        if admin_email:
            try:
                enviar_email(
                    admin_email,
                    "TenderSentinel — Falha no job diário",
                    f"<pre>{msg}</pre>",
                )
            except Exception:
                pass

        raise