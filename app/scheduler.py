from app.scraper import buscar_licitacoes, salvar_licitacoes
from app.alertas import disparar_alertas
from app.relatorio import gerar_relatorio_semanal

from apscheduler.schedulers.blocking import BlockingScheduler
from pytz import timezone


def buscar_e_alertar():
    print("Iniciando busca de licitações...")
    licitacoes = buscar_licitacoes()

    total = salvar_licitacoes(licitacoes)
    print(f"{total} licitações novas salvas.")

    print("Disparando alertas...")
    disparar_alertas()

    print("Ciclo concluído!")


def iniciar_scheduler():
    """
    Agenda:
    - Todos os dias às 9h00 (America/Sao_Paulo): buscar_e_alertar
    - Toda segunda-feira às 9h30 (America/Sao_Paulo): gerar_relatorio_semanal
    """
    tz = timezone("America/Sao_Paulo")
    scheduler = BlockingScheduler(timezone=tz)

    scheduler.add_job(
        buscar_e_alertar,
        "cron",
        hour=9,
        minute=0,
        id="buscar_e_alertar_diario",
        replace_existing=True,
    )

    scheduler.add_job(
        gerar_relatorio_semanal,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=30,
        id="relatorio_semanal_profissional_agencia",
        replace_existing=True,
    )

    print("Scheduler iniciado. Aguardando jobs...")
    scheduler.start()


if __name__ == "__main__":
    iniciar_scheduler()
