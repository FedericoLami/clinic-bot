# Contexto del proyecto — clinic-bot

Documento de arquitectura y decisiones de diseño para retomar el desarrollo en cualquier sesión.

---

## Perfil del desarrollador

- **Nombre:** Federico Lami
- **Nivel:** Python intermedio, experiencia con LangGraph, FastAPI, Docker, Redis, PostgreSQL, Claude API, Twilio
- **Metodología:** Aprendizaje guiado — explicar el "por qué" antes del "cómo", guiar con pistas en lugar de dar código completo. Excepción: si Federico pide explícitamente "dámelo hecho", entregar directo y retomar el método después.

---

## Concepto del proyecto

Chatbot de WhatsApp para clínicas médicas que automatiza la atención al paciente: agendamiento de turnos, consultas, cancelaciones, recordatorios automáticos y derivación al secretario. El bot **es** el sistema de gestión — no se integra con un sistema externo, sino que maneja su propia base de datos.

Pensado para producción real con una clínica. Hay que trabajarlo con estándares de privacidad de datos médicos (Ley 25.326 Argentina).

**Integración WhatsApp:** Twilio como intermediario (para desarrollo y producción).

---

## Funcionalidades definidas

1. Agendar turno
2. Consultar turno existente
3. Cancelar turno (con validación de anticipación mínima)
4. Recordatorio automático 24hs antes del turno (tarea programada, sin IA)
5. Recordatorio cuando el paciente pregunta
6. Derivación al secretario (mensaje al número del secretario vía WhatsApp + aviso al paciente)
7. Preguntas frecuentes (obra social, dirección, horarios, documentación necesaria)
8. Lista de espera cuando no hay turnos disponibles
9. Confirmación de turno al agendarlo

---

## Decisiones de diseño tomadas

- **Identificador del paciente:** número de teléfono de WhatsApp (único por paciente, lo provee Twilio automáticamente)
- **Agenda:** general de la clínica (no por médico individual)
- **Recordatorios:** automáticos 24hs antes + respuesta cuando el paciente pregunta
- **Derivación:** el bot manda mensaje al número del secretario Y avisa al paciente que fue derivado
- **Cancelaciones:** validación de anticipación mínima configurable (ej: no se puede cancelar con menos de 2hs)
- **Privacidad:** los datos de pacientes son sensibles — anonimizar en logs, cumplir Ley 25.326

---

## Arquitectura del sistema

```
paciente escribe por WhatsApp
        ↓
Twilio recibe y hace POST a /webhook
        ↓
[Clasificador] — detecta la intención
        ↓
[Buscador] — consulta Postgres o Redis según la categoría
        ↓
[Redactor] — redacta la respuesta con historial y contexto
        ↓
[Secretario] — (solo si requiere_secretario=True) notifica al secretario
        ↓
[Revisor] — verifica la respuesta
        ↓
Twilio envía la respuesta al paciente por WhatsApp
```

**Tarea paralela (sin IA):**
```
recordatorios.py corre cada hora
        ↓
obtiene turnos del día siguiente de Postgres
        ↓
envía recordatorio por WhatsApp a pacientes no notificados
```

---

## Estructura de archivos

```
clinic-bot/
│
├── src/
│   ├── estado.py           # TypedDict del estado compartido del grafo
│   ├── nodos.py            # Los 5 agentes del pipeline
│   ├── agente.py           # Grafo LangGraph con edges condicionales
│   ├── postgres.py         # Conexión y queries a PostgreSQL
│   ├── sesion.py           # Historial y estado de conversación en Redis
│   ├── recordatorios.py    # Tarea programada de recordatorios automáticos
│   ├── twilio_client.py    # Cliente Twilio para enviar/recibir WhatsApp
│   └── main_api.py         # API REST con FastAPI (webhook + panel admin)
│
├── database/
│   ├── schema.sql          # Definición de las 4 tablas
│   └── seed.sql            # Datos de prueba (médicos, preguntas frecuentes)
│
├── .env
├── .gitignore
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## Detalle de cada archivo

### `src/estado.py`
TypedDict con el estado compartido del grafo.
**Campos:**
- `mensaje: str` — lo que escribe el paciente
- `telefono: str` — número de WhatsApp del paciente (identificador único)
- `categoria: str` — intención detectada por el clasificador
- `informacion: str` — datos recuperados de Postgres
- `respuesta: str` — generada por el redactor
- `historial: List[dict]` — conversación completa en formato {role, content}
- `requiere_secretario: bool` — si True, activa el nodo secretario
- `respuesta_final: str` — aprobada por el revisor
**Paquetes:** `typing`

---

### `src/nodos.py`
Los 5 agentes del pipeline.

**`nodo_clasificador`**
Detecta la intención del mensaje. Categorías:
- `agendar_turno`
- `consultar_turno`
- `cancelar_turno`
- `pregunta_frecuente`
- `lista_espera`
- `derivar_secretario`
- `spam`

**`nodo_buscador`**
Según la categoría, consulta:
- `agendar_turno` → `obtener_turnos_disponibles()`
- `consultar_turno` → `obtener_turno_paciente(telefono)`
- `cancelar_turno` → `obtener_turno_paciente(telefono)` + validación de anticipación
- `pregunta_frecuente` → `obtener_preguntas_frecuentes()`
- `lista_espera` → `agregar_lista_espera(telefono)`
- `derivar_secretario` → devuelve string vacío, activa `requiere_secretario = True`
- `spam` → string vacío

**`nodo_redactor`**
Redacta la respuesta usando el historial completo + información del buscador. Usa Claude con system prompt específico para una clínica médica: empático, claro, conciso. Incluye disclaimer de que el bot no da consejos médicos.

**`nodo_secretario`**
Solo corre si `requiere_secretario = True`. Envía alerta al número del secretario vía Twilio y redacta aviso al paciente.

**`nodo_revisor`**
Verifica que la respuesta sea correcta, empática y no contenga información médica inventada. Agrega la respuesta al historial.

**Paquetes:** `anthropic`, `dotenv`, `src.postgres`, `src.sesion`, `src.twilio_client`

---

### `src/agente.py`
Grafo LangGraph con edges condicionales.

**Flujo:**
```
clasificador → buscador → redactor → [condicional] → revisor
                                            ↓
                                      secretario (si requiere_secretario=True)
```

Edge condicional después del redactor: si `estado["requiere_secretario"]` es True, va a `nodo_secretario` antes del revisor.

**Paquetes:** `langgraph`, `src.nodos`, `src.estado`

---

### `src/postgres.py`
Conexión y queries a PostgreSQL.

**Funciones:**
- `obtener_turnos_disponibles(fecha)` — turnos libres para agendar
- `agendar_turno(telefono, nombre, fecha, hora)` — inserta nuevo turno
- `obtener_turno_paciente(telefono)` — turno actual del paciente
- `cancelar_turno(telefono)` — marca como cancelado con validación
- `agregar_lista_espera(telefono, nombre)` — agrega a lista de espera
- `obtener_preguntas_frecuentes()` — todas las FAQ
- `obtener_turnos_proximos_24hs()` — para el recordatorio automático
- `marcar_recordatorio_enviado(idTurno)` — evita enviar recordatorio dos veces

**Paquetes:** `psycopg2`, `dotenv`, `os`

---

### `src/sesion.py`
Gestión de sesiones en Redis. TTL de 30 minutos (más largo que en pizzería — una consulta médica puede llevar más tiempo).

**Funciones:**
- `leer_historial(telefono)` — historial de conversación por teléfono
- `guardar_historial(telefono, historial)` — con TTL 30 min
- `guardar_estado_conversacion(telefono, estado)` — estado del flujo (ej: "esperando_confirmacion_turno")
- `leer_estado_conversacion(telefono)` — lee estado del flujo

**Paquetes:** `redis`, `dotenv`, `os`, `json`

---

### `src/recordatorios.py`
Tarea programada que corre independientemente del bot. No usa IA. Cada hora consulta Postgres y manda recordatorios por WhatsApp a los pacientes con turno al día siguiente que no fueron notificados.

**Paquetes:** `apscheduler`, `src.postgres`, `src.twilio_client`

---

### `src/twilio_client.py`
Cliente Twilio para enviar y recibir mensajes de WhatsApp.

**Funciones:**
- `enviar_mensaje(telefono, mensaje)` — envía WhatsApp al paciente
- `enviar_alerta_secretario(mensaje)` — envía al número del secretario
- `procesar_webhook(datos)` — extrae el mensaje y el teléfono del request de Twilio

**Paquetes:** `twilio`, `dotenv`, `os`

---

### `src/main_api.py`
API REST con FastAPI.

**Endpoints:**
- `POST /webhook` — recibe mensajes entrantes de Twilio, invoca el grafo, responde
- `GET /admin/turnos` — lista turnos del día para el panel de administración
- `GET /admin/lista-espera` — pacientes en lista de espera
- `GET /` — sirve el frontend del panel de administración

**Paquetes:** `fastapi`, `uvicorn`, `pydantic`, `src.agente`, `src.twilio_client`, `src.postgres`

---

## Esquema de base de datos (PostgreSQL)

```
pacientes
├── telefono (PK, varchar) — número de WhatsApp
├── nombre (varchar)
├── dni (varchar)
├── obra_social (varchar)
└── fecha_registro (timestamp)

turnos
├── idTurno (SERIAL PK)
├── telefono_paciente (FK → pacientes)
├── fecha (date)
├── hora (time)
├── especialidad (varchar)
├── estado (varchar) — 'agendado', 'cancelado', 'completado', 'en_espera'
└── recordatorio_enviado (boolean)

preguntas_frecuentes
├── idPregunta (SERIAL PK)
├── categoria (varchar)
├── pregunta (varchar)
└── respuesta (text)

medicos
├── idMedico (SERIAL PK)
├── nombre (varchar)
├── especialidad (varchar)
└── horarios (text) — descripción de disponibilidad
```

---

## Stack tecnológico

| Componente | Tecnología |
|-----------|-----------|
| Orquestación de agentes | LangGraph (edges condicionales) |
| Modelo de lenguaje | Claude Haiku (Anthropic API) |
| Integración WhatsApp | Twilio |
| Memoria de sesiones | Redis (TTL 30 min) |
| Base de datos | PostgreSQL |
| Tareas programadas | APScheduler |
| Backend / API REST | FastAPI + Uvicorn |
| Contenedorización | Docker |
| Despliegue | Railway |

---

## Lo nuevo que se aprende en este proyecto

1. **Twilio WhatsApp API** — recibir y enviar mensajes reales de WhatsApp
2. **Edges condicionales en LangGraph** — flujo dinámico según el estado
3. **APScheduler** — tareas programadas en Python
4. **Webhooks** — cómo Twilio notifica a tu servidor cuando llega un mensaje
5. **ngrok** — para exponer el servidor local durante desarrollo (Twilio necesita una URL pública para el webhook)

---

## Estado del proyecto al crear este documento

**No arrancado.** Solo arquitectura y decisiones de diseño definidas.

**Próximos pasos al retomar:**
1. Crear cuenta en Twilio y configurar número de WhatsApp sandbox
2. Crear repositorio GitHub y estructura de carpetas
3. Instalar dependencias: `twilio`, `apscheduler`, `langgraph`, `anthropic`, `fastapi`, `psycopg2`, `redis`, `python-dotenv`
4. Crear los contenedores Docker de Redis y PostgreSQL
5. Escribir `database/schema.sql` y `database/seed.sql`
6. Arrancar con `src/estado.py`

---

## Consideraciones de privacidad

- Los datos de pacientes (nombre, DNI, obra social) son sensibles — cumplir Ley 25.326 (Argentina)
- No loggear datos personales en texto plano
- El bot no da consejos médicos — incluir disclaimer en el system prompt del redactor
- Los números de teléfono en Redis tienen TTL — no se guardan conversaciones para siempre