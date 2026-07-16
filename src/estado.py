from typing import TypedDict,List

class EstadoSesion(TypedDict):
    mensaje:str
    telefono:str
    categoria:str
    informacion:str
    respuesta:str
    historial: List[dict]
    requiere_secretario: bool
    respuesta_final:str