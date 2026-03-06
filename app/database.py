import psycopg2
import os
from dotenv import load_dotenv


load_dotenv(override=False)

def conectar():
    database_url = os.getenv("DATABASE_URL")
    
    
    if database_url:
        
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        
        print("Conectando via DATABASE_URL...")
        return psycopg2.connect(database_url)
    
    
    print("Conectando via variáveis individuais...")
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )