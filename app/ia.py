"""Conexión (opcional) con DeepSeek.

La app funciona completa sin IA. Para activarla se pega la clave de DeepSeek
en la pantalla Configuración del buscador (se guarda solo en este computador,
en datos/configuracion_ia.json) o se define la variable DEEPSEEK_API_KEY.

DeepSeek usa el formato de la API de OpenAI (chat/completions), así que
cambiar de proveedor después es cambiar URL, modelo y clave.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from . import config

CONFIG_IA = config.DATOS_DIR / "configuracion_ia.json"
URL_POR_DEFECTO = "https://api.deepseek.com/chat/completions"
MODELOS = {
    "deepseek-chat": "DeepSeek Chat (rápido, recomendado)",
    "deepseek-reasoner": "DeepSeek Reasoner (razona más, más lento)",
}
_bloqueo = threading.Lock()


class ErrorIA(Exception):
    """Error con un mensaje que se le puede mostrar a la persona."""


def _leer_config() -> dict:
    try:
        return json.loads(CONFIG_IA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _clave() -> str | None:
    return os.environ.get("DEEPSEEK_API_KEY") or _leer_config().get("clave") or None


def _modelo() -> str:
    return os.environ.get("BUSCADOR_IA_MODELO") or _leer_config().get("modelo") or "deepseek-chat"


def _url() -> str:
    # BUSCADOR_IA_URL permite probar con un servidor local compatible.
    return os.environ.get("BUSCADOR_IA_URL") or URL_POR_DEFECTO


def estado() -> dict:
    clave = _clave()
    return {
        "activa": bool(clave),
        "proveedor": "deepseek" if clave else None,
        "modelo": _modelo(),
        "modelos": MODELOS,
        "clave_final": clave[-4:] if clave else None,
        "desde_variable": bool(os.environ.get("DEEPSEEK_API_KEY")),
    }


def guardar_config(clave: str | None = None, modelo: str | None = None, borrar_clave: bool = False) -> dict:
    with _bloqueo:
        datos = _leer_config()
        if borrar_clave:
            datos.pop("clave", None)
        elif clave:
            clave = clave.strip()
            if not re.fullmatch(r"[A-Za-z0-9_\-\.]{10,200}", clave):
                raise ErrorIA("La clave no tiene el formato esperado (debe empezar por sk-).")
            datos["clave"] = clave
        if modelo:
            if modelo not in MODELOS:
                raise ErrorIA("Modelo no reconocido.")
            datos["modelo"] = modelo
        config.DATOS_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_IA.write_text(json.dumps(datos, indent=2), encoding="utf-8")
    return estado()


def _mensaje_http(codigo: int, cuerpo: str) -> str:
    if codigo == 401:
        return "DeepSeek rechazó la clave. Revísala en Configuración."
    if codigo == 402:
        return "La cuenta de DeepSeek no tiene saldo. Recárgala en platform.deepseek.com."
    if codigo == 422 or codigo == 400:
        return f"DeepSeek no aceptó la solicitud ({codigo}): {cuerpo[:200]}"
    if codigo == 429:
        return "DeepSeek está limitando las solicitudes. Intenta de nuevo en un minuto."
    return f"DeepSeek no respondió bien (error {codigo}). Intenta de nuevo más tarde."


def chat(mensajes: list[dict], *, json_salida: bool = True, max_tokens: int = 2000,
         temperatura: float = 0.1, timeout: int = 240) -> tuple[str, dict]:
    """Llama al modelo y devuelve (texto, uso de tokens). Reintenta errores pasajeros."""
    clave = _clave()
    if not clave:
        raise ErrorIA("La IA no está configurada. Agrega la clave de DeepSeek en Configuración.")
    modelo = _modelo()
    cuerpo: dict = {"model": modelo, "messages": mensajes, "max_tokens": max_tokens, "stream": False}
    if modelo == "deepseek-reasoner":
        # En el modelo que razona, el límite incluye su razonamiento interno.
        cuerpo["max_tokens"] = max(max_tokens * 4, 8000)
    else:
        cuerpo["temperature"] = temperatura
        if json_salida:
            cuerpo["response_format"] = {"type": "json_object"}
    datos = json.dumps(cuerpo).encode("utf-8")
    ultimo_error = "sin respuesta"
    for intento in range(4):
        solicitud = urllib.request.Request(
            _url(), data=datos,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {clave}"},
        )
        try:
            with urllib.request.urlopen(solicitud, timeout=timeout) as resp:
                respuesta = json.loads(resp.read())
            texto = respuesta["choices"][0]["message"].get("content") or ""
            uso = respuesta.get("usage") or {}
            if not texto.strip():
                ultimo_error = "respuesta vacía"
                time.sleep(2 * (intento + 1))
                continue
            return texto, {"entrada": uso.get("prompt_tokens", 0), "salida": uso.get("completion_tokens", 0)}
        except urllib.error.HTTPError as exc:
            cuerpo_error = exc.read().decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503, 504) and intento < 3:
                ultimo_error = _mensaje_http(exc.code, cuerpo_error)
                time.sleep(5 * (intento + 1))
                continue
            raise ErrorIA(_mensaje_http(exc.code, cuerpo_error)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            ultimo_error = f"sin conexión con DeepSeek ({exc})"
            time.sleep(5 * (intento + 1))
        except (KeyError, IndexError, ValueError) as exc:
            ultimo_error = f"respuesta inesperada ({exc})"
            time.sleep(2)
    raise ErrorIA(f"No se pudo completar la consulta a DeepSeek: {ultimo_error}.")


def leer_json(texto: str) -> dict:
    """Extrae el objeto JSON de la respuesta (tolera texto o ``` alrededor)."""
    texto = texto.strip()
    try:
        return json.loads(texto)
    except ValueError:
        pass
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio >= 0 and fin > inicio:
        try:
            return json.loads(texto[inicio : fin + 1])
        except ValueError:
            pass
    raise ErrorIA("DeepSeek devolvió una respuesta que no se pudo interpretar. Intenta de nuevo.")


def chat_json(mensajes: list[dict], **kw) -> tuple[dict, dict]:
    texto, uso = chat(mensajes, json_salida=True, **kw)
    return leer_json(texto), uso


def probar() -> dict:
    datos, uso = chat_json(
        [{"role": "user", "content": 'Responde solo este JSON: {"ok": true}'}], max_tokens=20, timeout=60
    )
    return {"ok": bool(datos.get("ok")), "modelo": _modelo(), "uso": uso}
