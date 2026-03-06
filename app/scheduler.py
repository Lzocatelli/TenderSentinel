import time
from apscheduler.schedulers.blocking import BlockingScheduler
from app.scraper import buscar_licitacoes, salvar_licitacoes
from app.alertas import disparar_alertas

scheduler = BlockingScheduler(timezone="America/Sao_Paulo")

def buscar_e_alertar():
    print("Iniciando busca de licitações...")
    licitacoes = buscar_licitacoes()
    total = salvar_licitacoes(licitacoes)
    print(f"{total} licitações novas salvas.")

    print("Disparando alertas...")
    disparar_alertas()
    print("Ciclo concluído!")

# Roda todo dia às 07:00 e às 14:00
scheduler.add_job(buscar_e_alertar, 'cron', hour=7, minute=0)
scheduler.add_job(buscar_e_alertar, 'cron', hour=14, minute=0)

if __name__ == "__main__":
    print("Scheduler iniciado! Rodando às 07:00 e 14:00 todos os dias.")
    print("Pressione Ctrl+C para parar.")
    buscar_e_alertar()  # roda uma vez imediatamente ao iniciar
    scheduler.start()