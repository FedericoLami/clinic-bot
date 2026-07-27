from twilio.rest import Client
import os
from dotenv import load_dotenv

load_dotenv()

client = Client(
    os.environ.get("TWILIO_ACCOUNT_SID"),
    os.environ.get("TWILIO_AUTH_TOKEN")
)

TWILIO_WHATSAPP_NUMBER =  os.environ.get("TWILIO_WHATSAPP_NUMBER")
TWILIO_SECRETARY_NUMBER = os.environ.get("TWILIO_SECRETARY_NUMBER")



def enviar_mensaje(telefono,mensaje):
    client.messages.create(
    from_ = TWILIO_WHATSAPP_NUMBER,
    to=f"whatsapp:{telefono}",
    body=mensaje
    )

def enviar_alerta_secretario(mensaje):
    client.messages.create(
        from_ = TWILIO_WHATSAPP_NUMBER,
        to = TWILIO_SECRETARY_NUMBER,
        body = mensaje
    )

def procesar_webhook(datos):
    mensaje = datos.get("Body", "")
    telefono = datos.get("From","").replace("whatsapp:","")
    return mensaje, telefono