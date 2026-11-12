"""Punto de conexión (opcional) con un modelo de IA.

La app funciona completa SIN IA: la búsqueda es local. Cuando se quiera usar
DeepSeek basta con definir la variable de entorno DEEPSEEK_API_KEY (por
ejemplo en `configuracion_ia.bat`, ver README de la app) y reiniciar.

DeepSeek usa el mismo formato de la API de OpenAI (chat/completions), así
que cambiar de proveedor después es cambiar URL, modelo y clave.

Flujo previsto: la persona hace una pregunta -> se buscan localmente las
sentencias más pertinentes (app/busqueda.py) -> se envían al modelo solo
fragmentos de ellas como contexto -> el modelo responde citando radicados.
Nunca se envía la base completa.
"""

from __future__ import annotations

import json
import os
import urllib.request

PROVEEDORES = {
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "modelo": "deepseek-chat",
        "variable_clave": "DEEPSEEK_API_KEY",
    },
}

INSTRUCCIONES = (
    "Eres un asistente de investigación jurídica colombiana. Responde solo con base en los "
    "fragmentos de sentencias que se te entregan. Cita cada afirmación con el radicado entre "
    "corchetes, por ejemplo [T-760/08]. Si los fragmentos no bastan para responder, dilo."
)


def proveedor_activo() -> str | None:
    nombre = os.environ.get("BUSCADOR_IA", "deepseek")
    datos = PROVEEDORES.get(nombre)
    if datos and os.environ.get(datos["variable_clave"]):
        return nombre
    return None


def estado() -> dict:
    activo = proveedor_activo()
    return {"activa": bool(activo), "proveedor": activo, "modelo": PROVEEDORES[activo]["modelo"] if activo else None}


def preguntar(pregunta: str, contexto: list[dict], max_tokens: int = 1200) -> str:
    """Envía la pregunta con los fragmentos de contexto y devuelve la respuesta."""
    nombre = proveedor_activo()
    if not nombre:
        raise RuntimeError("La IA no está configurada (falta DEEPSEEK_API_KEY).")
    datos = PROVEEDORES[nombre]
    bloques = "\n\n".join(f"[{c['radicado']}] ({c['corte']}, {c.get('ano')})\n{c['fragmento']}" for c in contexto)
    cuerpo = {
        "model": os.environ.get("BUSCADOR_IA_MODELO", datos["modelo"]),
        "messages": [
            {"role": "system", "content": INSTRUCCIONES},
            {"role": "user", "content": f"Fragmentos:\n\n{bloques}\n\nPregunta: {pregunta}"},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    solicitud = urllib.request.Request(
        datos["url"],
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ[datos['variable_clave']]}"},
    )
    with urllib.request.urlopen(solicitud, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]
