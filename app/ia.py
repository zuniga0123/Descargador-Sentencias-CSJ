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
    """Error de la IA. `accionable` indica que la persona puede resolverlo (clave, saldo,
    configuración) y conviene mostrarle el mensaje tal cual; los demás se muestran con un
    texto neutro y el detalle queda en datos/registro_ia.log."""

    def __init__(self, mensaje: str, accionable: bool = False) -> None:
        super().__init__(mensaje)
        self.accionable = accionable


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


TOPE_SALIDA = 8000          # máximo de tokens de respuesta que admite deepseek-chat
TOPE_SALIDA_RAZONADOR = 32000
REGISTRO = config.DATOS_DIR / "registro_ia.log"


def _chat(mensajes: list[dict], *, json_salida: bool, max_tokens: int, temperatura: float,
          timeout: int) -> tuple[str, dict, str]:
    """Una llamada (con reintentos de red). Devuelve (texto, uso, motivo de fin)."""
    clave = _clave()
    if not clave:
        raise ErrorIA("La IA no está configurada. Agrega la clave de DeepSeek en Configuración.", accionable=True)
    modelo = _modelo()
    cuerpo: dict = {"model": modelo, "messages": mensajes, "max_tokens": min(max_tokens, TOPE_SALIDA), "stream": False}
    if modelo == "deepseek-reasoner":
        # En el modelo que razona, el límite incluye su razonamiento interno.
        cuerpo["max_tokens"] = min(max(max_tokens * 4, 8000), TOPE_SALIDA_RAZONADOR)
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
            opcion = respuesta["choices"][0]
            texto = opcion["message"].get("content") or ""
            fin = opcion.get("finish_reason") or ""
            uso = respuesta.get("usage") or {}
            if not texto.strip():
                ultimo_error = "respuesta vacía"
                time.sleep(2 * (intento + 1))
                continue
            return texto, {"entrada": uso.get("prompt_tokens", 0), "salida": uso.get("completion_tokens", 0)}, fin
        except urllib.error.HTTPError as exc:
            cuerpo_error = exc.read().decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503, 504) and intento < 3:
                ultimo_error = _mensaje_http(exc.code, cuerpo_error)
                time.sleep(5 * (intento + 1))
                continue
            raise ErrorIA(_mensaje_http(exc.code, cuerpo_error), accionable=exc.code in (401, 402)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            ultimo_error = f"sin conexión con DeepSeek ({exc})"
            time.sleep(5 * (intento + 1))
        except (KeyError, IndexError, ValueError) as exc:
            ultimo_error = f"respuesta inesperada ({exc})"
            time.sleep(2)
    raise ErrorIA(f"No se pudo completar la consulta a DeepSeek: {ultimo_error}.")


def chat(mensajes: list[dict], *, json_salida: bool = True, max_tokens: int = 2000,
         temperatura: float = 0.1, timeout: int = 240) -> tuple[str, dict]:
    """Llama al modelo y devuelve (texto, uso de tokens). Reintenta errores pasajeros."""
    texto, uso, _ = _chat(mensajes, json_salida=json_salida, max_tokens=max_tokens,
                          temperatura=temperatura, timeout=timeout)
    return texto, uso


def registrar(detalle: str) -> None:
    """Anota un error en datos/registro_ia.log (solo en este computador)."""
    try:
        config.DATOS_DIR.mkdir(parents=True, exist_ok=True)
        with open(REGISTRO, "a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} · modelo {_modelo()} · error\n{detalle}\n")
    except OSError:
        pass


def _registrar_falla(texto: str, fin: str, intento: int) -> None:
    """Guarda en datos/registro_ia.log las respuestas que no se pudieron leer (solo en este computador)."""
    try:
        config.DATOS_DIR.mkdir(parents=True, exist_ok=True)
        if REGISTRO.exists() and REGISTRO.stat().st_size > 2_000_000:
            REGISTRO.unlink()
        with open(REGISTRO, "a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} · modelo {_modelo()} · fin={fin or '?'} · "
                    f"intento {intento} · {len(texto)} caracteres\n{texto[:1500]}\n[…]\n{texto[-800:]}\n")
    except OSError:
        pass


def _sin_envoltura(texto: str) -> str:
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*", "", texto)
    texto = re.sub(r"\s*```\s*$", "", texto)
    inicio = texto.find("{")
    return texto[inicio:] if inicio > 0 else texto


def _sin_comas_finales(texto: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", texto)


def reparar_json(texto: str) -> dict | None:
    """Rescata lo aprovechable de un JSON cortado: cierra cadenas y llaves abiertas,
    descartando el último elemento incompleto."""
    t = _sin_comas_finales(_sin_envoltura(texto))
    if not t.startswith("{"):
        return None
    # Puntos donde se puede cortar sin romper la estructura: tras cerrar un valor.
    cortes = []
    pila, en_cadena, escape = [], False, False
    for i, c in enumerate(t):
        if en_cadena:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                en_cadena = False
            continue
        if c == '"':
            en_cadena = True
        elif c in "{[":
            pila.append(c)
        elif c in "}]":
            if pila:
                pila.pop()
            cortes.append((i + 1, list(pila)))
        elif c == ",":
            cortes.append((i, list(pila)))
    for pos, abiertos in reversed(cortes[-200:]):
        candidato = t[:pos].rstrip().rstrip(",")
        cierre = "".join("}" if a == "{" else "]" for a in reversed(abiertos))
        try:
            datos = json.loads(_sin_comas_finales(candidato + cierre))
        except ValueError:
            continue
        if isinstance(datos, dict):
            datos["_reparado"] = True
            return datos
    return None


def leer_json(texto: str) -> dict:
    """Extrae el objeto JSON de la respuesta (tolera ``` alrededor, texto previo y comas sobrantes)."""
    texto = texto.strip()
    for candidato in (texto, _sin_envoltura(texto), _sin_comas_finales(_sin_envoltura(texto))):
        try:
            datos = json.loads(candidato)
            if isinstance(datos, dict):
                return datos
        except ValueError:
            pass
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio >= 0 and fin > inicio:
        try:
            return json.loads(_sin_comas_finales(texto[inicio : fin + 1]))
        except ValueError:
            pass
    raise ErrorIA("DeepSeek devolvió una respuesta que no se pudo interpretar. Intenta de nuevo.")


def chat_json(mensajes: list[dict], *, max_tokens: int = 2000, temperatura: float = 0.1,
              timeout: int = 240) -> tuple[dict, dict]:
    """Llama al modelo pidiendo JSON. Si la respuesta llega cortada por longitud la pide de
    nuevo con más espacio; si no se puede leer, reintenta; al final intenta repararla."""
    uso_total = {"entrada": 0, "salida": 0}
    limite = max_tokens
    texto = ""
    for intento in range(1, 4):
        texto, uso, fin = _chat(mensajes, json_salida=True, max_tokens=limite, temperatura=temperatura, timeout=timeout)
        uso_total["entrada"] += uso["entrada"]
        uso_total["salida"] += uso["salida"]
        try:
            return leer_json(texto), uso_total
        except ErrorIA:
            _registrar_falla(texto, fin, intento)
            if limite >= TOPE_SALIDA and fin == "length":
                break  # no cabe ni con el máximo: se repara lo que haya
            limite = min(limite * 2 if fin == "length" else int(limite * 1.5), TOPE_SALIDA)
    reparado = reparar_json(texto)
    if reparado is not None:
        return reparado, uso_total
    raise ErrorIA("DeepSeek devolvió respuestas que no se pudieron interpretar (se intentó 3 veces). "
                  "Intenta de nuevo; si se repite, envía el archivo datos/registro_ia.log.")


def probar() -> dict:
    datos, uso = chat_json(
        [{"role": "user", "content": 'Responde solo este JSON: {"ok": true}'}], max_tokens=20, timeout=60
    )
    return {"ok": bool(datos.get("ok")), "modelo": _modelo(), "uso": uso}
