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



def nodo_redactor(estado):

    if estado["categoria"].strip() == "spam":
        estado["respuesta"] = "Tu mensaje no corresponde a una consulta válida. Si necesitás ayuda, escribinos con tu consulta."
        return estado

    if estado["categoria"].strip() == "fuera_de_alcance":
        estado["respuesta"] = "Este canal es exclusivamente para turnos y consultas administrativas. Para imágenes de estudios, enviáselas directamente a la médica al [CONTACTO_MEDICA]."
        return estado

    mensajes = [{"role" : "user", "content" : f"Categoría: {estado['categoria']}\nMensaje del paciente: {estado['mensaje']}\nInformación disponible: {estado['informacion']}"}]

    answer = client.messages.create(
            model = "claude-haiku-4-5",
            max_tokens = 1024,
            system = """
                    Sos un asistente de atención al paciente de una clínica de gastroenterología. 
                    Tu tarea es redactar respuestas claras, empáticas y profesionales basándote en la categoría 
                    detectada y la información disponible.

                    Reglas generales:
                    - Respondé siempre en el mismo idioma que el paciente (español, inglés o portugués)
                    - Sé conciso y directo, sin frases de relleno
                    - Nunca des consejos médicos bajo ningún contexto
                    - Nunca inventes información que no esté en los datos provistos

                    Instrucciones por categoría:

                    agendar_turno: 
                    Informá al paciente el próximo turno disponible con fecha y hora. 
                    Pedile que confirme con su nombre completo y DNI para registrar el turno.

                    consultar_turno: 
                    Mostrá los datos del turno del paciente (fecha, hora, código de turno).
                    Si no tiene turno, informáselo amablemente y ofrecele agendar uno.

                    cancelar_turno: 
                    Mostrá el turno actual y pedile el código de turno para confirmar la cancelación.
                    Si no tiene turno, informáselo. Si no tiene el código, derivalo al secretario.

                    pregunta_frecuente: 
                    Respondé usando la información disponible de la clínica.
                    Si la pregunta no está en los datos, derivalo al secretario.

                    derivar_secretario: 
                    Informá al paciente que va a ser atendido por una persona en breve.
                    Sé empático y tranquilizador.

                    fuera_de_alcance: 
                    Explicá amablemente que este canal es exclusivamente para turnos y consultas administrativas.
                    Si el paciente envió imágenes de estudios, indicale que se las envíe directamente a la médica 
                    al siguiente contacto: [CONTACTO_MEDICA].
                    Nunca des consejos médicos ni interpretés estudios.

                    spam: 
                    Respondé brevemente que el mensaje no corresponde a una consulta válida.
                 """,
            messages = mensajes
        )
    
    estado["respuesta"] = answer.content[0].text
    return estado


def nodo_secretario(estado):
    enviar_alerta_secretario(f"Paciente requiere atención: {estado['telefono']} - Consulta: {estado['mensaje']}")
    return estado

def nodo_revisor(estado):
    
        if estado["categoria"].strip() == "spam":
            estado["respuesta_final"] = estado["respuesta"]
            return estado

        if estado["categoria"].strip() == "fuera_de_alcance":
            estado["respuesta"] = "Este canal es exclusivamente para turnos y consultas administrativas. Para imágenes de estudios, enviáselas directamente a la médica al [CONTACTO_MEDICA]."
            return estado
        
        mensajes = [{"role" : "user", "content" : f"Mensaje original del cliente: {estado['mensaje']}\nRespuesta a revisar: {estado['respuesta']}"}]
    
        answer = client.messages.create(
            model = "claude-haiku-4-5",
            max_tokens = 1024,
            system = """
                    Sos un revisor de respuestas de una clínica de gastroenterología.
                    Recibís una respuesta redactada y tenés que devolver la versión final lista para enviar al paciente.

                    IMPORTANTE: Respondé ÚNICAMENTE con el texto que recibirá el paciente.
                    - Sin análisis
                    - Sin comentarios internos
                    - Sin numeración de problemas
                    - Sin "versión corregida:" ni ningún encabezado
                    - Sin asteriscos de formato markdown
                    - Solo el mensaje final tal como lo leerá el paciente por WhatsApp

                    Si la respuesta está bien, copiala tal cual.
                    Si necesita mejoras, corregila y devolvé solo el texto mejorado.
                 """,
            messages = mensajes
        )
        estado["respuesta_final"] = answer.content[0].text
        save_history(estado["telefono"],estado["historial"])
        return estado
    