import psycopg2
import os
import random
import string
from dotenv import load_dotenv
from datetime import datetime, timedelta, time

load_dotenv()

database_url = os.environ.get("DATABASE_URL")
if database_url:
    pgConnection = psycopg2.connect(database_url)
else:
    pgConnection = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST"),
        port=os.environ.get("POSTGRES_PORT"),
        dbname=os.environ.get("POSTGRES_DB"),
        user=os.environ.get("POSTGRES_USER"),
        password=os.environ.get("POSTGRES_PASSWORD"),
    )

pgCursor = pgConnection.cursor()

def obtener_turnos_disponibles(fecha):
    pgCursor.execute("SELECT * FROM turnos WHERE estado = 'disponible' AND fecha = %s ORDER BY hora", (fecha,))
    resultados = pgCursor.fetchall()
    return resultados

def agendar_turno(telefono,nombre,dni,fecha,hora):
    codigo = "TUR-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    pgCursor.execute("INSERT INTO pacientes(telefono,nombre,dni) VALUES (%s,%s,%s) ON CONFLICT (dni) DO NOTHING", (telefono,nombre,dni))
    pgCursor.execute("INSERT INTO turnos(codigo_turno,telefono_paciente,fecha,hora,estado) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (codigo_turno) DO NOTHING", (codigo,telefono,fecha,hora,"agendado"))
    pgConnection.commit()
    return codigo

def obtener_turno_paciente(dni_paciente):
    pgCursor.execute("SELECT * FROM turnos WHERE estado = 'agendado' AND dni_paciente = %s",(dni_paciente,))
    resultados = pgCursor.fetchall()
    return resultados

def cancelar_turno(codigo_turno):
    pgCursor.execute("UPDATE turnos SET estado = 'cancelado' WHERE codigo_turno = %s ",(codigo_turno,))
    pgConnection.commit()

def obtener_preguntas_frecuentes():
    pgCursor.execute("SELECT * FROM preguntas_frecuentes")
    resultados = pgCursor.fetchall()
    return resultados

def obtener_turnos_proximos_24hs():
    pgCursor.execute("SELECT * FROM turnos WHERE estado = 'agendado' AND recordatorio_enviado = false AND (fecha + hora) BETWEEN NOW() AND NOW() + INTERVAL '24 hours'")
    resultados = pgCursor.fetchall()
    return resultados

def marcar_recordatorio_enviado(idTurno):
    pgCursor.execute("UPDATE turnos SET recordatorio_enviado = true WHERE idTurno = %s",(idTurno,))
    pgConnection.commit()


DIAS_LABORALES = [0, 1, 2, 4]  # 0=lunes, 1=martes, 2=miércoles, 4=viernes
HORA_INICIO = time(10, 0)
HORA_FIN = time(17, 0)
INTERVALO_MINUTOS = 30

def obtener_proximo_turno_disponible():
    fecha_busqueda = datetime.now().date() + timedelta(days=1)
    
    for _ in range(365):
        if fecha_busqueda.weekday() in DIAS_LABORALES:
            
            pgCursor.execute(
                "SELECT hora FROM turnos WHERE fecha = %s AND estado = 'agendado'",
                (fecha_busqueda,)
            )
            horas_ocupadas = [row[0] for row in pgCursor.fetchall()]
            
            slot_actual = datetime.combine(fecha_busqueda, HORA_INICIO)
            fin_dia = datetime.combine(fecha_busqueda, HORA_FIN)
            
            while slot_actual < fin_dia:
                if slot_actual.time() not in horas_ocupadas:
                    return {"fecha": fecha_busqueda, "hora": slot_actual.time()}
                slot_actual += timedelta(minutes=INTERVALO_MINUTOS)
        
        fecha_busqueda += timedelta(days=1)
    return None