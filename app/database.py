import psycopg2
import os

def conectar():
    # Pega a URL, se não existir retorna "", e tira os espaços vazios
    database_url = os.environ.get("DATABASE_URL", "").strip()
    
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        
        print("Sucesso: Conectando via DATABASE_URL...")
        return psycopg2.connect(database_url)
    
    # Se chegou aqui, é porque a URL está literalmente vazia.
    # O raise vai parar o app e mostrar esse erro claro no log do Railway.
    raise ValueError("ERRO CRÍTICO: DATABASE_URL não foi encontrada ou está vazia no Railway. Verifique se deletou o .env do GitHub!")