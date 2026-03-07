from app.scraper import buscar_licitacoes, salvar_licitacoes
from app.alertas import disparar_alertas
from app.database import conectar


if __name__ == "__main__":
    print("=== INICIANDO TESTE COMPLETO (LOCAL) ===")

    print("\n1. Buscando licitações no portal...")
    licitacoes = buscar_licitacoes()
    total = salvar_licitacoes(licitacoes)
    print(f"{total} licitações novas salvas no banco.")

    print("\n2. Preparando banco de dados para o teste...")
    conn = conectar()
    cur = conn.cursor()

    palavras_teste = [
        "software",
        "desenvolvimento de software",
        "manutenção de software",
        "licença de software",
        "sistema de gestão",
        "aplicação web",
        "aplicativo",
        "serviços de TI",
    ]
    meu_email = "luizzocatelli2014@gmail.com"  # O e-mail que vai receber o alerta

    cur.execute(
        """
        INSERT INTO clientes (nome, email, palavras_chave, ativo) 
        VALUES ('Teste Local', %s, %s, TRUE)
        ON CONFLICT (email) DO UPDATE 
        SET palavras_chave = %s;
    """,
        (meu_email, palavras_teste, palavras_teste),
    )

    # Limpa os registros anteriores de alertas para o teste
    cur.execute("DELETE FROM alertas_enviados;")
    conn.commit()
    cur.close()
    conn.close()

    print("\n3. Disparando alertas para o cliente de teste...")
    disparar_alertas()

    print("\nTeste completo finalizado!")

