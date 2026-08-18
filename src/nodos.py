import anthropic
from dotenv import load_dotenv
import os
from src.postgres import obtener_proximo_turno_disponible,obtener_turnos_disponibles, agendar_turno, obtener_turno_paciente, cancelar_turno, obtener_preguntas_frecuentes
from src.sesion import save_history, read_history
from src.twilio_client import enviar_alerta_secretario
from src.sesion import save_history, read_history, guardar_datos_turno, leer_datos_turno

load_dotenv()

client = anthropic.Anthropic()

def nodo_clasificador(estado):
    estado["historial"] = read_history(estado["telefono"])
    estado["historial"].append({"role": "user", "content": estado["mensaje"]})
    
    # Leer flujo activo de Redis
    datos_turno = leer_datos_turno(estado["telefono"])
    paso = datos_turno.get("paso", "")
    
    if paso in ["esperando_datos", "confirmando"]:
        estado["categoria"] = f"agendar_turno_{paso}"
        estado["paso_flujo"] = paso
        return estado
    
    # Clasificar normalmente con Claude
    mensajes = estado["historial"]
    answer = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system="""
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
        messages=mensajes
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
    elif categoria in ["agendar_turno_esperando_datos", "agendar_turno_confirmando"]:
        estado["informacion"] = ""
    return estado



def nodo_redactor(estado):

    if estado["categoria"].strip() == "spam":
        estado["respuesta"] = "Este número es para turnos y consultas de la clínica. Si necesitás ayuda, escribí tu consulta."
        return estado

    if estado["categoria"].strip() == "fuera_de_alcance":
        estado["respuesta"] = "Este canal es exclusivamente para turnos y consultas administrativas. Para imágenes de estudios, enviáselas directamente a la médica."
        return estado

    if estado["categoria"].strip() in ["agendar_turno", "agendar_turno_esperando_datos", "agendar_turno_confirmando"]:
        paso = estado.get("paso_flujo", "")
        datos_turno = leer_datos_turno(estado["telefono"])

        if not paso or paso == "":
            turno_info = obtener_proximo_turno_disponible()
            fecha = turno_info['fecha']
            hora = turno_info['hora']

            DIAS_ES = {0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves", 4: "viernes", 5: "sábado", 6: "domingo"}
            MESES_ES = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio", 7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}

            turno_display = f"{DIAS_ES[fecha.weekday()]} {fecha.day} de {MESES_ES[fecha.month]} de {fecha.year} a las {hora.strftime('%H:%M')} hs"

            estado["respuesta"] = f"El próximo turno disponible es el {turno_display}.\n\nPara registrarlo necesito su nombre completo y DNI."
            estado["paso_flujo"] = "esperando_datos"
            guardar_datos_turno(estado["telefono"], {
                "paso": "esperando_datos",
                "turno": turno_display,
                "fecha": str(fecha),
                "hora": str(hora)
            })
            return estado

        elif paso == "esperando_datos":
            mensajes = [{
                "role": "user",
                "content": f"""Extraé el nombre completo y DNI del siguiente mensaje.
                Respondé ÚNICAMENTE con un JSON válido, sin texto adicional, sin markdown, sin explicaciones.
                Formato exacto: {{"nombre": "valor", "dni": "valor"}}
                Si no encontrás algún dato, poné cadena vacía.
                Mensaje: {estado['mensaje']}"""
            }]
            answer = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=200,
                messages=mensajes,
                system="Respondé solo con JSON válido. Sin texto adicional. Sin markdown. Sin explicaciones."
            )

            respuesta_raw = answer.content[0].text.strip()
            respuesta_raw = respuesta_raw.replace("```json", "").replace("```", "").strip()
            print(f"EXTRACCION RAW: {respuesta_raw}")

            import json as json_module
            try:
                datos = json_module.loads(respuesta_raw)

                if not datos.get("nombre") or not datos.get("dni"):
                    estado["respuesta"] = "Necesito tu nombre completo y DNI. Por favor enviálos juntos."
                    return estado

                datos_turno.update(datos)
                guardar_datos_turno(estado["telefono"], {**datos_turno, "paso": "confirmando"})
                estado["paso_flujo"] = "confirmando"
                estado["respuesta"] = f"Registramos los siguientes datos:\n- Nombre: {datos['nombre']}\n- DNI: {datos['dni']}\n- Turno: {datos_turno.get('turno', '')}\n\nRespondé SI para confirmar o NO para cancelar."
            except Exception as ex:
                print(f"ERROR PARSEO JSON: {ex} | Raw: {respuesta_raw}")
                estado["respuesta"] = "Necesito tu nombre completo y DNI. Por favor enviálos juntos en un solo mensaje."

            return estado

        elif paso == "confirmando":
            if "si" in estado["mensaje"].lower() or "sí" in estado["mensaje"].lower():
                try:
                    codigo = agendar_turno(
                        estado["telefono"],
                        datos_turno.get("nombre", ""),
                        datos_turno.get("dni", ""),
                        datos_turno.get("fecha", ""),
                        datos_turno.get("hora", "")
                    )
                    guardar_datos_turno(estado["telefono"], {**datos_turno, "paso": "completado"})
                    estado["paso_flujo"] = "completado"
                    estado["respuesta"] = f"Turno confirmado. Su código de turno es: {codigo}. Guárdelo para futuras consultas o cancelaciones."
                except Exception as e:
                    print(f"ERROR AGENDAR: {e}")
                    estado["respuesta"] = "Hubo un error al registrar el turno. Por favor comuníquese con la secretaría."
            else:
                estado["respuesta"] = "Cancelamos el proceso. Si desea agendar un turno nuevamente, escríbanos."
                guardar_datos_turno(estado["telefono"], {})
                estado["paso_flujo"] = ""
            return estado

    mensajes = estado["historial"] + [{"role": "user", "content": f"Categoría: {estado['categoria']}\nMensaje del paciente: {estado['mensaje']}\nInformación disponible: {estado['informacion']}"}]

    answer = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system="""
                Sos un asistente de atención al paciente de una clínica de gastroenterología.
                Tu tarea es redactar respuestas claras, empáticas y profesionales.

                Reglas generales:
                - Respondé siempre en el mismo idioma que el paciente (español, inglés o portugués)
                - Sé conciso y directo, sin frases de relleno
                - Sin emojis
                - Sin "te tengo buenas noticias" ni frases similares
                - Nunca des consejos médicos
                - Nunca inventes información que no esté en los datos provistos
                - Sin preguntas de seguimiento al final

                Instrucciones por categoría:
                consultar_turno: mostrá los datos del turno. Si no tiene, ofrecé agendar uno.
                cancelar_turno: mostrá el turno actual y pedí el código de turno para cancelar. Si no tiene código, derivalo al secretario.
                pregunta_frecuente: respondé usando la información disponible.
                derivar_secretario: informá que será atendido por una persona en breve.
             """,
        messages=mensajes
    )

    estado["respuesta"] = answer.content[0].text
    return estado


def nodo_secretario(estado):
    enviar_alerta_secretario(f"Paciente requiere atención: {estado['telefono']} - Consulta: {estado['mensaje']}")
    return estado

def nodo_revisor(estado):
    
    # Shortcircuit para categorías que no necesitan revisión de Claude
    if estado["categoria"].strip() in [
        "spam",
        "fuera_de_alcance", 
        "agendar_turno",
        "agendar_turno_esperando_datos",
        "agendar_turno_confirmando"
    ]:
        estado["respuesta_final"] = estado["respuesta"]
        save_history(estado["telefono"], estado["historial"])
        return estado
    
    mensajes = [{"role": "user", "content": f"Mensaje original del cliente: {estado['mensaje']}\nRespuesta a revisar: {estado['respuesta']}"}]

    answer = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system="""
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
        messages=mensajes
    )
    estado["respuesta_final"] = answer.content[0].text
    save_history(estado["telefono"], estado["historial"])
    return estado
    