import anthropic
from dotenv import load_dotenv
import os
from src.postgres import obtener_proximo_turno_disponible,obtener_turnos_disponibles, agendar_turno, obtener_turno_paciente, cancelar_turno, obtener_preguntas_frecuentes
from src.sesion import save_history, read_history
from src.twilio_client import enviar_alerta_secretario

load_dotenv()

client = anthropic.Anthropic()

def nodo_clasificador(estado):
    estado["historial"] = read_history(estado["telefono"])
    estado["historial"].append({"role": "user", "content": estado["mensaje"]})
    mensajes = estado["historial"]
    answer = client.messages.create(
            model = "claude-haiku-4-5",
            max_tokens = 1024,
            system = """
                    Sos un clasificador de mensajes de pacientes de una clínica de gastroenterología.
                    Tu única tarea es determinar la intención del mensaje y responder con una sola categoría.

                    Categorías disponibles:
                    - agendar_turno: el paciente quiere sacar, pedir o reservar un turno médico
                    - consultar_turno: el paciente pregunta si tiene turno, cuándo es o quiere ver los datos de su turno
                    - cancelar_turno: el paciente quiere cancelar o anular su turno
                    - pregunta_frecuente: preguntas sobre obras sociales, horarios, dirección, documentación, preparación para estudios o aranceles
                    - derivar_secretario: el paciente necesita hablar con una persona o el mensaje no encaja en ninguna categoría válida
                    - fuera_de_alcance: el paciente menciona síntomas, dolores, urgencias médicas, envía imágenes o hace consultas médicas de cualquier tipo
                    - spam: mensajes sin sentido, texto aleatorio o publicidad

                    Reglas importantes:
                    - Este canal es EXCLUSIVAMENTE para turnos y consultas administrativas de la clínica. NUNCA para consultas médicas.
                    - Si el paciente menciona síntomas, dolores, urgencias o cualquier consulta médica: clasificar como fuera_de_alcance
                    - Si el paciente envía imágenes o archivos: clasificar como fuera_de_alcance
                    - Si el mensaje es un "sí" o "no" suelto sin contexto claro: clasificar como derivar_secretario
                    - En caso de duda entre categorías: preferir derivar_secretario
                    - Aceptás mensajes en español, inglés y portugués

                    Respondé únicamente con la palabra de la categoría. Sin explicaciones, sin JSON, sin puntuación.
                 """,
            messages = mensajes
        )
    
    estado["categoria"] = answer.content[0].text
    return estado


def nodo_buscador(estado):
    categoria = estado["categoria"]
    if categoria == "agendar_turno":
        estado["informacion"] = str(obtener_proximo_turno_disponible())
    elif categoria == "consultar_turno":
        estado["informacion"] = str(obtener_turno_paciente(estado["dni"]))
    elif categoria == "cancelar_turno":
        estado["informacion"] = str(obtener_turno_paciente(estado["dni"]))
    elif categoria == "pregunta_frecuente":
        estado["informacion"] = str(obtener_preguntas_frecuentes())
    elif categoria in ["fuera_de_alcance", "spam", "derivar_secretario"]:
        estado["informacion"] = ""
    return estado