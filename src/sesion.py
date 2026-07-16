import redis
from dotenv import load_dotenv
import os
import json

load_dotenv()

redis_url = os.environ.get("REDIS_URL")
if redis_url:
    redisClient = redis.Redis.from_url(redis_url, decode_responses = True)
else:
    redisClient = redis.Redis(
        host = os.environ.get("REDIS_HOST"),
        port = os.environ.get("REDIS_PORT"),
        decode_responses=True
    )

def create_session_id(telefono):
    return telefono

def save_history(session_id,historial):
    historial_str = json.dumps(historial)
    redisClient.set("sesion:" + session_id, historial_str, ex = 1800)

def read_history(session_id):
    sesion = ("sesion:" + session_id)
    sesionRedis = redisClient.get(sesion)
    if sesionRedis:
        return json.loads(sesionRedis)
    else:
        return []
    
def save_medical_appointment(telefono, session_id):
    redisClient.set("estado:" + telefono, session_id)

def read_medical_appointment(telefono):
    turno = redisClient.get("estado:" + telefono)
    if turno:
        return turno
    else:
        return None