import psycopg2
import os
import random
import string
from dotenv import load_dotenv

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

