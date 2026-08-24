# clinic-bot — Chatbot de WhatsApp para Clínicas Médicas

Sistema de atención al paciente vía WhatsApp para una clínica de gastroenterología. Automatiza el agendamiento de turnos, consultas, cancelaciones, recordatorios automáticos y derivación al secretario — sin intervención humana para las consultas del día a día.

El bot **es** el sistema de gestión: no se integra con ningún sistema externo, sino que maneja su propia base de datos de pacientes y turnos.

---

## Funcionalidades

- **Agendar turno** — calcula el próximo slot disponible dinámicamente (lunes/martes/miércoles/viernes, 10:00-17:00, cada 30 minutos), lo ofrece al paciente y registra el turno con nombre, DNI y código único (`TUR-XXXX`)
- **Consultar turno** — el paciente consulta su turno por DNI
- **Cancelar turno** — cancelación por código de turno con validación de que el turno exista y esté activo
- **Recordatorios automáticos** — tarea programada que corre cada hora y manda WhatsApp 24hs antes del turno
- **Preguntas frecuentes** — obras sociales, horarios, documentación, preparación para estudios, aranceles
- **Derivación al secretario** — el bot avisa por WhatsApp al secretario cuando no puede resolver la consulta
- **Manejo de fuera de alcance** — respuesta clara cuando el paciente intenta usar el canal para consultas médicas

---

## Demo

![Demo del sistema](demo.gif)

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Orquestación de agentes | LangGraph |
| Modelo de lenguaje | Claude Haiku (Anthropic API) |
| Integración WhatsApp | Twilio |
| Memoria de sesiones | Redis (TTL 30 min) |
| Base de datos | PostgreSQL |
| Tareas programadas | APScheduler |
| Backend / API REST | FastAPI + Uvicorn |
| Contenedorización | Docker |

---

## Arquitectura

```
paciente escribe por WhatsApp
        ↓
Twilio recibe → POST /webhook
        ↓
[Clasificador] — detecta la intención
        ↓    (lee estado de flujo de Redis antes de llamar a Claude)
[Buscador] — consulta Postgres o Redis según la categoría
        ↓
[Redactor] — redacta la respuesta con historial completo
        ↓
[Secretario] — (solo si requiere_secretario=True) notifica al secretario
        ↓
[Revisor] — verifica calidad antes de enviar
        ↓
Twilio envía la respuesta al paciente
```

**Flujos multi-paso con estado en Redis:**

```
agendar_turno:
  → esperando_datos (bot ofrece turno, espera nombre y DNI)
  → confirmando (bot muestra resumen, espera SI/NO)
  → completado (turno registrado en Postgres, Redis limpio)

consultar_turno:
  → consultar_turno_esperando_dni

cancelar_turno:
  → cancelar_turno_esperando_codigo
```

**Tarea paralela (sin IA):**

```
APScheduler corre cada hora
        ↓
obtiene turnos del día siguiente de Postgres
        ↓
envía recordatorio por WhatsApp
        ↓
marca recordatorio_enviado = true
```

---

## Estructura del proyecto

```
clinic-bot/
│
├── src/
│   ├── estado.py           # TypedDict del estado compartido del grafo
│   ├── nodos.py            # Los 5 agentes del pipeline LangGraph
│   ├── agente.py           # Grafo LangGraph con edge condicional para secretario
│   ├── postgres.py         # Conexión y queries a PostgreSQL
│   ├── sesion.py           # Historial y estado de flujo en Redis
│   ├── recordatorios.py    # Tarea programada de recordatorios automáticos
│   ├── twilio_client.py    # Cliente Twilio (enviar/recibir WhatsApp)
│   └── main_api.py         # API REST con FastAPI
│
├── database/
│   ├── schema.sql
│   ├── seed.sql
│   └── migrations/
│       └── 001_unique_turno_slot.sql
│
├── Dockerfile
├── .env
├── requirements.txt
└── README.md
```

---

## Esquema de base de datos

```
pacientes
├── dni (PK)
├── telefono
├── nombre
├── obra_social (nullable)
└── fecha_registro

turnos
├── idTurno (SERIAL PK)
├── codigo_turno (UNIQUE)
├── dni_paciente (FK → pacientes)
├── fecha
├── hora
├── estado — 'agendado' | 'cancelado' | 'completado'
└── recordatorio_enviado

preguntas_frecuentes
├── idPregunta (SERIAL PK)
├── categoria
├── pregunta
└── respuesta
```

Constraint de unicidad: `turnos(fecha, hora) WHERE estado = 'agendado'` — previene doble reserva ante requests concurrentes.

---

## Instalación y uso

### Requisitos previos

- Python 3.11
- Docker Desktop
- Cuenta de Twilio con WhatsApp Sandbox activo
- ngrok (para desarrollo local)
- API Key de Anthropic

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/FedericoLami/clinic-bot.git
cd clinic-bot

# 2. Crear y activar entorno virtual
py -3.11 -m venv venv
venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar .env
ANTHROPIC_API_KEY=tu-api-key
REDIS_HOST=localhost
REDIS_PORT=6379
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=clinica
POSTGRES_USER=postgres
POSTGRES_PASSWORD=tu-password
TWILIO_ACCOUNT_SID=tu-account-sid
TWILIO_AUTH_TOKEN=tu-auth-token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
TWILIO_SECRETARY_NUMBER=whatsapp:+549XXXXXXXXX

# 5. Levantar contenedores
docker run -d --name redis-clinica -p 6379:6379 redis
docker run -d --name postgres-clinica -e POSTGRES_PASSWORD=tu-password -e POSTGRES_DB=clinica -p 5432:5432 postgres

# 6. Crear tablas y cargar datos
docker cp database/schema.sql postgres-clinica:/schema.sql
docker exec -it postgres-clinica psql -U postgres -d clinica -f /schema.sql

docker cp database/seed.sql postgres-clinica:/seed.sql
docker exec -it postgres-clinica psql -U postgres -d clinica -f /seed.sql

docker cp database/migrations/001_unique_turno_slot.sql postgres-clinica:/001_unique_turno_slot.sql
docker exec -it postgres-clinica psql -U postgres -d clinica -f /001_unique_turno_slot.sql

# 7. Iniciar servidor
uvicorn src.main_api:app --reload

# 8. Exponer con ngrok
ngrok http 8000

# 9. Configurar webhook en Twilio
# Messaging → Try it out → Send a WhatsApp message → Sandbox Settings
# When a message comes in: https://TU-URL.ngrok-free.app/webhook (POST)
```

---

## Disponibilidad de turnos

La agenda se calcula dinámicamente — no hay slots pre-cargados en la base de datos.

```python
DIAS_LABORALES = [0, 1, 2, 4]  # lunes, martes, miércoles, viernes
HORA_INICIO = time(10, 0)
HORA_FIN = time(17, 0)
INTERVALO_MINUTOS = 30
```

---

## Privacidad

- El DNI es el identificador primario del paciente — permite que una persona saque turnos para distintos familiares desde el mismo celular
- El historial de conversación expira automáticamente a los 30 minutos de inactividad
- Cumplimiento Ley 25.326 (Argentina)

---

## Decisiones de diseño

**DNI como identificador primario del paciente, no el teléfono**
El teléfono de WhatsApp identifica la conversación, pero no al paciente. Una misma persona puede sacar turnos para distintos familiares desde el mismo celular — si el identificador fuera el teléfono, sería imposible distinguir entre "turno de Juan" y "turno de la madre de Juan" en la misma conversación. El DNI resuelve esto de raíz.

**Cálculo dinámico de slots disponibles en lugar de tabla pre-cargada**
Una tabla de slots requeriría cargar miles de filas por anticipado y mantenerlas sincronizadas. El sistema calcula los slots libres en tiempo de ejecución: dado el horario de la doctora (días y horas fijas en constantes de código), un slot está disponible si no aparece en `turnos` con estado `'agendado'`. Cambiar la disponibilidad implica modificar dos constantes, no una tabla.

**Estado de flujo conversacional en Redis, no en variables de memoria**
FastAPI atiende múltiples requests concurrentes — cada mensaje de WhatsApp llega como un request independiente sin estado compartido en memoria. Redis permite que el clasificador sepa en qué paso del flujo está el paciente (esperando_datos, confirmando, etc.) entre mensajes, sin importar qué instancia del servidor atiende cada request.

**El clasificador lee Redis antes de llamar a Claude**
Si hay un flujo activo (por ejemplo, el bot ya preguntó el DNI y está esperando la respuesta), llamar a Claude para clasificar el siguiente mensaje es un gasto innecesario de tokens y latencia — y produce clasificaciones incorrectas porque "31234567" (un DNI) se clasifica como spam. El clasificador lee el paso activo de Redis primero y lo asigna directamente como categoría sin invocar el LLM.

---

## Desafíos técnicos resueltos

**Race condition en reserva de turnos**
Dos pacientes podían quedar con el mismo horario si sus requests llegaban casi al mismo tiempo: el primero calculaba el slot libre, el segundo también lo veía libre antes de que el primero insertara en la base. La solución fue un índice parcial único en PostgreSQL: `CREATE UNIQUE INDEX ON turnos(fecha, hora) WHERE estado = 'agendado'`. Cualquier intento de doble reserva falla a nivel de base de datos antes de llegar al código.

**Falsa confirmación al cancelar turnos**
`UPDATE ... WHERE codigo_turno = X` no lanza excepción si el código no existe — simplemente afecta 0 filas. El sistema respondía "turno cancelado correctamente" aunque el código fuera inválido. La solución fue validar `pgCursor.rowcount` después del UPDATE y responder distinto si es 0.

**Historial de conversación sin respuestas del bot**
El historial persistido en Redis solo contenía mensajes del paciente (`role: user`), nunca las respuestas del bot (`role: assistant`). Esto hacía que el contexto de conversaciones previas fuera inútil para el LLM — veía una lista de mensajes del usuario sin saber qué había respondido antes. El fix fue agregar la respuesta final al historial en `nodo_revisor` antes de persistir en Redis.

**Scheduler iniciado dos veces al arrancar**
APScheduler se iniciaba una vez al importar `recordatorios.py` y una segunda vez en el `lifespan` de FastAPI, lanzando `SchedulerAlreadyRunningError`. La solución fue remover el `.start()` del módulo de recordatorios y dejarlo exclusivamente en el `lifespan`.

---

## Autor

**Federico Lami**
[LinkedIn](https://www.linkedin.com/in/federicolami/) · [GitHub](https://github.com/FedericoLami)