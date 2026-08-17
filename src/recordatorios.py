from apscheduler.schedulers.background import BackgroundScheduler
from src.postgres import obtener_turnos_proximos_24hs, marcar_recordatorio_enviado
from src.twilio_client import enviar_mensaje

def enviar_recordatorios():
    turnos = obtener_turnos_proximos_24hs()
    for turno in turnos:
        mensaje = f"Tenes un turno el dia: {turno[3]}, a la hora:, {turno[4]}"
        enviar_mensaje(turno[7],mensaje)
        marcar_recordatorio_enviado(turno[0])

scheduler = BackgroundScheduler()
scheduler.add_job(enviar_recordatorios, 'interval', hours = 1)
scheduler.start()