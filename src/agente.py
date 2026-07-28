from langgraph.graph import StateGraph, END
from src.nodos import nodo_redactor, nodo_buscador, nodo_clasificador, nodo_revisor, nodo_secretario
from src.estado import EstadoSesion

def decidir_siguiente(estado):
    if estado["requiere_secretario"]:
        return "secretario"
    return "revisor"

grafo = StateGraph(EstadoSesion)

grafo.add_node("clasificador", nodo_clasificador)
grafo.add_node("buscador", nodo_buscador)
grafo.add_node("redactor", nodo_redactor)
grafo.add_node("secretario", nodo_secretario)
grafo.add_node("revisor", nodo_revisor)

grafo.set_entry_point("clasificador")
grafo.add_edge("clasificador", "buscador")
grafo.add_edge("buscador", "redactor")
grafo.add_conditional_edges("redactor", decidir_siguiente, {
    "secretario": "secretario",
    "revisor": "revisor"
})
grafo.add_edge("secretario", "revisor")
grafo.add_edge("revisor", END)

grafo_app = grafo.compile()