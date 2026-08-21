import psycopg2
import psycopg2.errors
from psycopg2 import pool
import os
import random
import string
from dotenv import load_dotenv
from datetime import datetime, timedelta, time
from contextlib import contextmanager

load_dotenv()

database_url = os.environ.get("DATABASE_URL")
if database_url:
    pgPool = pool.ThreadedConnectionPool(1, 20, database_url)
else:
    pgPool = pool.ThreadedConnectionPool(
        1, 20,
        host=os.environ.get("POSTGRES_HOST"),
        port=os.environ.get("POSTGRES_PORT"),
        dbname=os.environ.get("POSTGRES_DB"),
        user=os.environ.get("POSTGRES_USER"),
        password=os.environ.get("POSTGRES_PASSWORD"),
    )


@contextmanager
def obtener_conexion():
    """Pide una conexión al pool y la devuelve al terminar (haya fallado o no
    la operación). Reemplaza la conexión/cursor globales que antes se
    compartían entre todos los requests concurrentes."""
    conn = pgPool.getconn()
    try:
        yield conn
    finally:
        pgPool.putconn(conn)


class TurnoNoDisponibleError(Exception):
    """Se lanza cuando dos pacientes intentan agendar el mismo dia+hora
    (otro paciente confirmó ese horario mientras este todavía lo tenía
    seleccionado)."""
    pass


def agendar_turno(telefono, nombre, dni, fecha, hora):
    codigo = "TUR-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO pacientes(telefono, nombre, dni) VALUES (%s,%s,%s)
                       ON CONFLICT (dni) DO UPDATE SET nombre = EXCLUDED.nombre, telefono = EXCLUDED.telefono""",
                    (telefono, nombre, dni)
                )
                cur.execute(
                    "INSERT INTO turnos(codigo_turno, dni_paciente, fecha, hora, estado) VALUES (%s,%s,%s,%s,%s)",
                    (codigo, dni, fecha, hora, "agendado")
                )
            conn.commit()
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            raise TurnoNoDisponibleError(f"El turno {fecha} {hora} ya fue reservado por otro paciente.")
    return codigo

def obtener_turno_paciente(dni_paciente):
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM turnos WHERE estado = 'agendado' AND dni_paciente = %s ORDER BY fecha, hora",
                (dni_paciente,)
            )
            resultados = cur.fetchall()
        conn.commit()
        return resultados

def cancelar_turno(codigo_turno):
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE turnos SET estado = 'cancelado' WHERE codigo_turno = %s AND estado = 'agendado'",
                (codigo_turno,)
            )
            filas_afectadas = cur.rowcount
        conn.commit()
        return filas_afectadas > 0

def obtener_preguntas_frecuentes():
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM preguntas_frecuentes")
            resultados = cur.fetchall()
        conn.commit()
        return resultados

def obtener_turnos_proximos_24hs():
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT *, pacientes.telefono FROM turnos JOIN pacientes ON turnos.dni_paciente = pacientes.dni WHERE estado = 'agendado' AND recordatorio_enviado = false AND (fecha + hora) BETWEEN NOW() AND NOW() + INTERVAL '24 hours'")
            resultados = cur.fetchall()
        conn.commit()
        return resultados

def marcar_recordatorio_enviado(idTurno):
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE turnos SET recordatorio_enviado = true WHERE idTurno = %s", (idTurno,))
        conn.commit()


DIAS_LABORALES = [0, 1, 2, 4]  # 0=lunes, 1=martes, 2=miércoles, 4=viernes
HORA_INICIO = time(10, 0)
HORA_FIN = time(17, 0)
INTERVALO_MINUTOS = 30

def obtener_proximo_turno_disponible():
    fecha_busqueda = datetime.now().date() + timedelta(days=1)

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            for _ in range(365):
                if fecha_busqueda.weekday() in DIAS_LABORALES:

                    cur.execute(
                        "SELECT hora FROM turnos WHERE fecha = %s AND estado = 'agendado'",
                        (fecha_busqueda,)
                    )
                    horas_ocupadas = [row[0] for row in cur.fetchall()]

                    slot_actual = datetime.combine(fecha_busqueda, HORA_INICIO)
                    fin_dia = datetime.combine(fecha_busqueda, HORA_FIN)

                    while slot_actual < fin_dia:
                        if slot_actual.time() not in horas_ocupadas:
                            conn.commit()
                            return {"fecha": fecha_busqueda, "hora": slot_actual.time()}
                        slot_actual += timedelta(minutes=INTERVALO_MINUTOS)

                fecha_busqueda += timedelta(days=1)
            conn.commit()
    return None
