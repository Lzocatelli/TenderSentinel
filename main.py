from app.scraper import buscar_licitacoes, salvar_licitacoes
from app.alertas import disparar_alertas
from app.database import conectar

if __name__ == "__main__":
    print("=== INICIANDO TESTE COMPLETO ===")
    
    
    print("\n1. Buscando licitações no portal...")
    licitacoes = buscar_licitacoes()
    total = salvar_licitacoes(licitacoes)
    print(f"{total} licitações novas salvas no banco.")

    
    print("\n2. Preparando banco de dados para o teste...")
    conn = conectar()
    cur = conn.cursor()
    
    palavra_teste = "aquisição" 
    meu_email = "luizzocatelli2014@gmail.com" # O e-mail que vai receber o alerta
    
    
    cur.execute("""
        INSERT INTO clientes (nome, email, palavras_chave, ativo) 
        VALUES ('Teste Local', %s, ARRAY[%s], TRUE)
        ON CONFLICT (email) DO UPDATE 
        SET palavras_chave = ARRAY[%s];
    """, (meu_email, palavra_teste, palavra_teste))
    
    
    cur.execute("DELETE FROM alertas_enviados;")
    conn.commit()
    cur.close()
    conn.close()

   
    print(f"\n3. Procurando '{palavra_teste}' e disparando alertas...")
    disparar_alertas()
    
    print("\n Teste finalizado!")