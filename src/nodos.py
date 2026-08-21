import anthropic
from dotenv import load_dotenv
import os
import re
from src.postgres import obtener_proximo_turno_disponible, agendar_turno, obtener_turno_paciente, cancelar_turno, obtener_preguntas_frecuentes, TurnoNoDisponibleError
from src.sesion import save_history, read_history, guardar_datos_turno, leer_datos_turno
from src.twilio_client import enviar_alerta_secretario

load_dotenv()

client = anthropic.Anthropic()

CATEGORIAS_CON_FLUJO = [
    "agendar_turno", "agendar_turno_esperando_datos", "agendar_turno_confirmando",
    "consultar_turno", "consultar_turno_esperando_dni",
    "cancelar_turno", "cancelar_turno_esperando_codigo",
    "spam", "fuera_de_alcance"
]

# Categorías que ya traen su respuesta final armada y no necesitan pasar
# por el revisor de Claude en nodo_revisor.
CATEGORIAS_SIN_REVISION = CATEGORIAS_CON_FLUJO + ["saludo"]

DIAS_ES = {0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves", 4: "viernes", 5: "sábado", 6: "domingo"}
MESES_ES = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
            7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}

# Palabras/frases que indican que el paciente quiere abandonar el flujo activo
PALABRAS_ESCAPE_FLUJO = [
    "cancelar", "cancelalo", "cancelá", "olvidalo", "olvidá", "olvidate",
    "dejalo", "dejalo así", "salir", "otra cosa", "no quiero seguir",
    "no importa", "mejor no"
]

def nodo_clasificador(estado):
    estado["historial"] = read_history(estado["telefono"])
    estado["historial"].append({"role": "user", "content": estado["mensaje"]})

    # Leer flujo activo de Redis
    datos_turno = leer_datos_turno(estado["telefono"])
    paso = datos_turno.get("paso", "")

    # Escape hatch: si hay un flujo activo pero el paciente pide explícitamente
    # abandonarlo, limpiamos el estado y clasificamos el mensaje normalmente
    # en vez de forzar la categoría del paso.
    mensaje_lower = estado["mensaje"].lower()
    if paso and any(palabra in mensaje_lower for palabra in PALABRAS_ESCAPE_FLUJO):
        guardar_datos_turno(estado["telefono"], {})
        paso = ""

    if paso in ["esperando_datos", "confirmando"]:
        estado["categoria"] = f"agendar_turno_{paso}"
        estado["paso_flujo"] = paso
        return estado

    if paso in ["consultar_turno_esperando_dni", "cancelar_turno_esperando_codigo"]:
        estado["categoria"] = paso
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
                - saludo: saludos, agradecimientos, despedidas o mensajes sociales sin consulta específica (hola, gracias, buenas, chau, ok, perfecto)
                - derivar_secretario: el paciente necesita hablar con una persona o el mensaje no encaja en ninguna categoría válida
                - fuera_de_alcance: el paciente menciona síntomas, dolores, urgencias médicas, envía imágenes o hace consultas médicas de cualquier tipo
                - spam: mensajes sin sentido, texto aleatorio o publicidad

                Reglas importantes:
                - Este canal es EXCLUSIVAMENTE para turnos y consultas administrativas de la clínica. NUNCA para consultas médicas.
                - Si el paciente menciona síntomas, dolores, urgencias o cualquier consulta médica: clasificar como fuera_de_alcance
                - Si el paciente envía imágenes o archivos: clasificar como fuera_de_alcance
                - Saludos, agradecimientos y despedidas: clasificar como saludo
                - En caso de duda entre categorías: preferir derivar_secretario
                - Aceptás mensajes en español, inglés y portugués

                Respondé únicamente con la palabra de la categoría. Sin explicaciones, sin JSON, sin puntuación.
             """,
        messages=mensajes
    )

    estado["categoria"] = answer.content[0].text.strip()
    return estado


def nodo_buscador(estado):
    categoria = estado["categoria"].strip()
    if categoria == "agendar_turno":
        estado["informacion"] = str(obtener_proximo_turno_disponible())
    elif categoria == "pregunta_frecuente":
        estado["informacion"] = str(obtener_preguntas_frecuentes())
    else:
        estado["informacion"] = ""
    return estado


def nodo_redactor(estado):
    categoria = estado["categoria"].strip()

    # ── SPAM ──────────────────────────────────────────────────────────────────
    if categoria == "spam":
        estado["respuesta"] = "Este número es para turnos y consultas de la clínica. Si necesitás ayuda, escribí tu consulta."
        return estado

    # ── FUERA DE ALCANCE ──────────────────────────────────────────────────────
    if categoria == "fuera_de_alcance":
        estado["respuesta"] = "Este canal es exclusivamente para turnos y consultas administrativas. Para imágenes de estudios, enviáselas directamente a la médica."
        return estado

    # ── SALUDO / AGRADECIMIENTO ───────────────────────────────────────────────
    if categoria == "saludo":
        mensajes = estado["historial"]
        answer = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=100,
            system="""Sos la recepcionista de una clínica de gastroenterología. 
                    Respondé saludos, agradecimientos y despedidas de forma cordial, breve y natural.
                    Sin emojis. Sin ofrecer ayuda adicional al final. Solo respondé el saludo.""",
            messages=mensajes
        )
        estado["respuesta"] = answer.content[0].text
        return estado

    # ── FLUJO: AGENDAR TURNO ──────────────────────────────────────────────────
    if categoria in ["agendar_turno", "agendar_turno_esperando_datos", "agendar_turno_confirmando"]:
        paso = estado.get("paso_flujo", "")
        datos_turno = leer_datos_turno(estado["telefono"])

        if not paso or paso == "":
            turno_info = obtener_proximo_turno_disponible()
            fecha = turno_info['fecha']
            hora = turno_info['hora']

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
            mensajes = [{"role": "user", "content": f"""Extraé el nombre completo y DNI del siguiente mensaje.
                        Respondé ÚNICAMENTE con un JSON válido, sin texto adicional, sin markdown, sin explicaciones.
                        Formato exacto: {{"nombre": "valor", "dni": "valor"}}
                        Si no encontrás algún dato, poné cadena vacía.
                        Mensaje: {estado['mensaje']}"""}]
            answer = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=200,
                messages=mensajes,
                system="Respondé solo con JSON válido. Sin texto adicional. Sin markdown. Sin explicaciones."
            )

            respuesta_raw = answer.content[0].text.strip().replace("```json", "").replace("```", "").strip()
            print(f"EXTRACCION RAW: {respuesta_raw}")

            import json as json_module
            try:
                datos = json_module.loads(respuesta_raw)

                if not datos.get("nombre") or not datos.get("dni"):
                    estado["respuesta"] = "Necesito su nombre completo y DNI. Por favor envíelos juntos en un mensaje."
                    return estado

                datos_turno.update(datos)
                guardar_datos_turno(estado["telefono"], {**datos_turno, "paso": "confirmando"})
                estado["paso_flujo"] = "confirmando"
                estado["respuesta"] = (
                    f"Registramos los siguientes datos:\n"
                    f"- Nombre: {datos['nombre']}\n"
                    f"- DNI: {datos['dni']}\n"
                    f"- Turno: {datos_turno.get('turno', '')}\n\n"
                    f"Respondá SI para confirmar o NO para cancelar."
                )
            except Exception as ex:
                print(f"ERROR PARSEO JSON: {ex} | Raw: {respuesta_raw}")
                estado["respuesta"] = "Necesito su nombre completo y DNI. Por favor envíelos juntos en un solo mensaje."

            return estado

        elif paso == "confirmando":
            mensaje_lower = estado["mensaje"].lower()
            confirma = re.search(r"\bs[ií]\b", mensaje_lower) is not None
            rechaza = re.search(r"\bno\b", mensaje_lower) is not None

            if confirma and not rechaza:
                try:
                    codigo = agendar_turno(
                        estado["telefono"],
                        datos_turno.get("nombre", ""),
                        datos_turno.get("dni", ""),
                        datos_turno.get("fecha", ""),
                        datos_turno.get("hora", "")
                    )
                    guardar_datos_turno(estado["telefono"], {})  # limpiar Redis
                    estado["paso_flujo"] = ""
                    estado["respuesta"] = f"Turno confirmado. Su código de turno es: {codigo}. Guárdelo para futuras consultas o cancelaciones."
                except TurnoNoDisponibleError as e:
                    print(f"TURNO YA TOMADO: {e}")
                    guardar_datos_turno(estado["telefono"], {})
                    estado["paso_flujo"] = ""
                    estado["respuesta"] = "Ese horario ya fue reservado por otro paciente mientras tanto. Por favor, escríbanos de nuevo para pedir el próximo turno disponible."
                except Exception as e:
                    print(f"ERROR AGENDAR: {e}")
                    guardar_datos_turno(estado["telefono"], {})
                    estado["respuesta"] = "Hubo un error al registrar el turno. Por favor comuníquese con la secretaría."
            elif rechaza and not confirma:
                guardar_datos_turno(estado["telefono"], {})
                estado["paso_flujo"] = ""
                estado["respuesta"] = "Cancelamos el proceso. Si desea agendar un turno nuevamente, escríbanos."
            else:
                # Respuesta ambigua (ni SI ni NO claros, o ambas): no asumimos, volvemos a preguntar
                estado["respuesta"] = "No entendí su respuesta. Por favor confirme el turno respondiendo SI o NO."
            return estado

    # ── FLUJO: CONSULTAR TURNO ────────────────────────────────────────────────
    if categoria in ["consultar_turno", "consultar_turno_esperando_dni"]:
        paso = estado.get("paso_flujo", "")

        if paso != "consultar_turno_esperando_dni":
            guardar_datos_turno(estado["telefono"], {"paso": "consultar_turno_esperando_dni"})
            estado["respuesta"] = "Para consultar su turno, por favor indíqueme su número de DNI."
            return estado
        else:
            dni = estado["mensaje"].strip()
            turno = obtener_turno_paciente(dni)
            guardar_datos_turno(estado["telefono"], {})
            if turno:
                t = turno[0]
                estado["respuesta"] = f"Su turno está registrado para el {t[3]} a las {t[4]}.\nCódigo de turno: {t[1]}."
            else:
                estado["respuesta"] = "No encontramos un turno registrado con ese DNI. Si cree que es un error, comuníquese con la secretaría."
            return estado

    # ── FLUJO: CANCELAR TURNO ─────────────────────────────────────────────────
    if categoria in ["cancelar_turno", "cancelar_turno_esperando_codigo"]:
        paso = estado.get("paso_flujo", "")

        if paso != "cancelar_turno_esperando_codigo":
            guardar_datos_turno(estado["telefono"], {"paso": "cancelar_turno_esperando_codigo"})
            estado["respuesta"] = "Para cancelar su turno necesito el código de turno (formato TUR-XXXX). Si no lo tiene, comuníquese con la secretaría."
            return estado
        else:
            codigo = estado["mensaje"].strip().upper()
            try:
                cancelado = cancelar_turno(codigo)
                guardar_datos_turno(estado["telefono"], {})
                if cancelado:
                    estado["respuesta"] = f"Su turno con código {codigo} fue cancelado correctamente."
                else:
                    estado["respuesta"] = f"No encontramos un turno activo con el código {codigo}. Verifique el código o comuníquese con la secretaría."
            except Exception as e:
                print(f"ERROR CANCELAR: {e}")
                guardar_datos_turno(estado["telefono"], {})
                estado["respuesta"] = "No pudimos cancelar el turno. Verifique el código o comuníquese con la secretaría."
            return estado

    # ── RESTO: PREGUNTAS FRECUENTES Y DERIVAR SECRETARIO ─────────────────────
    mensajes = estado["historial"] + [{
        "role": "user",
        "content": f"Categoría: {estado['categoria']}\nMensaje del paciente: {estado['mensaje']}\nInformación disponible: {estado['informacion']}"
    }]

    answer = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system="""Sos el asistente de una clínica de gastroenterología.
                Respondé de forma clara, empática y profesional.
                - Sin emojis
                - Sin frases de relleno
                - Nunca des consejos médicos
                - Nunca inventes información

                Para pregunta_frecuente: respondé usando la información disponible.
                Para derivar_secretario: informá cordialmente que será atendido por una persona en breve.""",
        messages=mensajes
    )

    estado["respuesta"] = answer.content[0].text
    return estado


def nodo_secretario(estado):
    enviar_alerta_secretario(f"Paciente requiere atención: {estado['telefono']} - Consulta: {estado['mensaje']}")
    return estado


def nodo_revisor(estado):
    categoria = estado["categoria"].strip()

    # Shortcircuit — estas categorías no necesitan revisión de Claude
    if categoria in CATEGORIAS_SIN_REVISION:
        estado["respuesta_final"] = estado["respuesta"]
        estado["historial"].append({"role": "assistant", "content": estado["respuesta_final"]})
        save_history(estado["telefono"], estado["historial"])
        return estado

    mensajes = [{"role": "user", "content": f"Mensaje del paciente: {estado['mensaje']}\nRespuesta a revisar: {estado['respuesta']}"}]

    answer = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system="""Sos un revisor de respuestas de una clínica de gastroenterología.
                Devolvé ÚNICAMENTE el texto final que recibirá el paciente.
                Sin análisis, sin encabezados, sin asteriscos, sin comentarios.
                Si la respuesta está bien, copiala tal cual. Si necesita mejoras, corregila.""",
        messages=mensajes
    )
    estado["respuesta_final"] = answer.content[0].text
    estado["historial"].append({"role": "assistant", "content": estado["respuesta_final"]})
    save_history(estado["telefono"], estado["historial"])
    return estado