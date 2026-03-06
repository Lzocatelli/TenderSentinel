from app.scheduler import buscar_e_alertar
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler(timezone="America/Sao_Paulo")

scheduler.add_job(buscar_e_alertar, 'cron', hour=7, minute=0)
scheduler.add_job(buscar_e_alertar, 'cron', hour=14, minute=0)

if __name__ == "__main__":
    print("LicitaBot iniciado! Rodando às 07:00 e 14:00 todos os dias.")
    print("Pressione Ctrl+C para parar.")
    buscar_e_alertar()  # roda imediatamente ao iniciar
    scheduler.start()