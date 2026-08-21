import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from src.agente import grafo_app
from fastapi.responses import HTMLResponse
from src.recordatorios import scheduler
from src.twilio_client import procesar_webhook, enviar_mensaje
from contextlib import asynccontextmanager
from src.sesion import leer_datos_turno
from twilio.request_validator import RequestValidator

TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
# Si la app corre detras de un proxy/tunel (ngrok, Render, etc.) y la URL que
# ve FastAPI no coincide con la que Twilio realmente firmo (ej. http vs
# https), se puede fijar la URL publica real acá para que la validación
# de firma funcione igual.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL")


def _validar_firma_twilio(request: Request, form_dict: dict) -> bool:
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    firma = request.headers.get("X-Twilio-Signature", "")
    url = (PUBLIC_BASE_URL.rstrip("/") + request.url.path) if PUBLIC_BASE_URL else str(request.url)
    return validator.validate(url, form_dict, firma)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/webhook")
async def webhook(request:Request):
    try:
        datos = await request.form()

        if not _validar_firma_twilio(request, dict(datos)):
            raise HTTPException(status_code=403, detail="Firma de Twilio invalida")

        mensaje, telefono = procesar_webhook(datos)

        datos_turno = leer_datos_turno(telefono)
        paso_flujo = datos_turno.get("paso", "")

        resultado = grafo_app.invoke({
            "mensaje": mensaje,
            "telefono": telefono,
            "dni": "",
            "nombre": "",
            "categoria": "",
            "informacion": "",
            "respuesta": "",
            "historial": [],
            "requiere_secretario": False,
            "respuesta_final": "",
            "paso_flujo": paso_flujo
        })
        
        enviar_mensaje(telefono, resultado["respuesta_final"])
        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))