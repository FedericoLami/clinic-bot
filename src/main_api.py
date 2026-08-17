from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from src.agente import grafo_app
from fastapi.responses import HTMLResponse
from src.recordatorios import scheduler
from src.twilio_client import procesar_webhook, enviar_mensaje
from contextlib import asynccontextmanager

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
        mensaje, telefono = procesar_webhook(datos)

        resultado = grafo_app.invoke({
            "mensaje": mensaje,
            "telefono": telefono,
            "dni": "",
            "categoria": "",
            "informacion": "",
            "respuesta": "",
            "historial": [],
            "requiere_secretario": False,
            "respuesta_final": ""
        })
        
        enviar_mensaje(telefono, resultado["respuesta_final"])
        return {"status": "ok"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))