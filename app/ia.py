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
_SIN_JSON_RAZONADOR = threading.Event()


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
    if json_salida and not (modelo == "deepseek-reasoner" and _SIN_JSON_RAZONADOR.is_set()):
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
            if exc.code == 400 and "response_format" in cuerpo and "response_format" in cuerpo_error.lower():
                # El modelo no admite el modo JSON: se repite sin él y se recuerda.
                _SIN_JSON_RAZONADOR.set()
                cuerpo.pop("response_format")
                datos = json.dumps(cuerpo).encode("utf-8")
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


# Marcas internas del modelo que a veces se cuelan en la respuesta, p. ej. <|endoftext|>,
# <｜end▁of▁sentence｜> o <|im_end|>; rompen el JSON y nunca son contenido real.
_RE_MARCAS = re.compile(r"<[|｜][^<>\n]{1,60}?[|｜]>")
_RE_PENSAMIENTO = re.compile(r"<think>.*?</think>", re.S)


def limpiar_respuesta(texto: str) -> str:
    texto = _RE_MARCAS.sub("", texto or "")
    texto = _RE_PENSAMIENTO.sub("", texto)
    texto = texto.strip()
    texto = re.sub(r"^```(?:json|JSON)?\s*", "", texto)
    texto = re.sub(r"\s*```\s*$", "", texto)
    return texto.strip()


def _normalizar_fuera_de_cadenas(t: str) -> str:
    """Recorre el texto distinguiendo lo que está dentro de comillas: dentro, convierte los
    saltos de línea y tabuladores literales en escapes y corrige escapes inválidos; fuera,
    quita comentarios // y /* */ y comas sobrantes antes de } o ]."""
    salida, i, n = [], 0, len(t)
    en_cadena = False
    while i < n:
        c = t[i]
        if en_cadena:
            if c == "\\":
                sig = t[i + 1] if i + 1 < n else ""
                if sig in '"\\/bfnrt':
                    salida.append(c + sig); i += 2; continue
                if sig == "u" and re.match(r"[0-9a-fA-F]{4}", t[i + 2 : i + 6]):
                    salida.append(t[i : i + 6]); i += 6; continue
                salida.append("\\\\"); i += 1; continue   # escape inválido: se conserva la barra
            if c == '"':
                en_cadena = False
            elif c == "\n":
                salida.append("\\n"); i += 1; continue
            elif c == "\r":
                i += 1; continue
            elif c == "\t":
                salida.append("\\t"); i += 1; continue
            elif ord(c) < 32:
                i += 1; continue
            salida.append(c); i += 1; continue
        if c == '"':
            en_cadena = True
        elif c == "/" and t[i + 1 : i + 2] == "/":
            fin = t.find("\n", i)
            i = n if fin < 0 else fin
            continue
        elif c == "/" and t[i + 1 : i + 2] == "*":
            fin = t.find("*/", i + 2)
            i = n if fin < 0 else fin + 2
            continue
        salida.append(c); i += 1
    return re.sub(r",\s*([}\]])", r"\1", "".join(salida))


def _como_objeto(datos) -> dict | None:
    if isinstance(datos, dict):
        return datos
    if isinstance(datos, list):  # algunos modelos devuelven la lista sin la clave que la envuelve
        return {"_lista": datos}
    return None


def _cargar(t: str) -> dict | None:
    """Intenta leer un JSON con tolerancia creciente; None si no se puede."""
    for candidato in (t, _normalizar_fuera_de_cadenas(t)):
        try:
            r = _como_objeto(json.loads(candidato, strict=False))
            if r is not None:
                return r
        except ValueError:
            pass
    # Último recurso: sintaxis de Python (comillas simples, True/False/None).
    if "'" in t:
        import ast
        try:
            convertido = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", re.sub(r"\bnull\b", "None", t)))
            return _como_objeto(ast.literal_eval(convertido))
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            pass
    return None


def _inicios(t: str) -> list[int]:
    """Posiciones donde puede empezar el JSON (primer { o [ y los siguientes, por si hay texto antes)."""
    return [m.start() for m in re.finditer(r"[{\[]", t)][:40]


def reparar_json(texto: str) -> dict | None:
    """Rescata lo aprovechable de un JSON cortado: cierra cadenas y llaves abiertas,
    descartando el último elemento incompleto."""
    limpio = limpiar_respuesta(texto)
    inicios = _inicios(limpio)
    if not inicios:
        return None
    t = _normalizar_fuera_de_cadenas(limpio[inicios[0]:])
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
        datos = _cargar(candidato + cierre)
        if datos is not None:
            datos["_reparado"] = True
            return datos
    return None


def leer_json(texto: str) -> dict:
    """Extrae el objeto JSON de la respuesta. Tolera marcas internas del modelo, bloques ```,
    texto antes o después, saltos de línea dentro de las cadenas, escapes inválidos,
    comentarios, comas sobrantes y una lista en lugar de un objeto."""
    limpio = limpiar_respuesta(texto)
    directo = _cargar(limpio)
    if directo is not None:
        return directo
    decodificador = json.JSONDecoder(strict=False)
    for inicio in _inicios(limpio):
        # Si antes empezó algo con forma de JSON ({" o [{) que no se pudo leer, la respuesta está
        # cortada: no se acepta un fragmento interno (se perderían la clave y el resto); se repara.
        if re.search(r'[{\[]\s*[\[{"]', limpio[:inicio]):
            break
        fragmento = limpio[inicio:]
        for candidato in (fragmento, _normalizar_fuera_de_cadenas(fragmento)):
            try:
                datos, _ = decodificador.raw_decode(candidato)
            except ValueError:
                continue
            r = _como_objeto(datos)
            if r is not None:
                return r
    raise ErrorIA("La respuesta de la IA no se pudo interpretar. Intenta de nuevo.")


def lista_de(datos: dict, clave: str) -> list:
    """La lista esperada bajo `clave` (o la lista que el modelo devolvió sin envolver)."""
    valor = datos.get(clave)
    if isinstance(valor, list):
        return valor
    return datos.get("_lista") if isinstance(datos.get("_lista"), list) else []


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
            try:
                json.loads(limpiar_respuesta(texto), strict=False)
                motivo = ""
            except ValueError as exc:
                motivo = str(exc)
            _registrar_falla(texto, f"{fin} · {motivo}" if motivo else fin, intento)
            if limite >= TOPE_SALIDA and fin == "length":
                break  # no cabe ni con el máximo: se repara lo que haya
            limite = min(limite * 2 if fin == "length" else int(limite * 1.5), TOPE_SALIDA)
    reparado = reparar_json(texto)
    if reparado is not None:
        return reparado, uso_total
    raise ErrorIA("DeepSeek devolvió respuestas que no se pudieron interpretar (se intentó 3 veces). "
                  "Intenta de nuevo; si se repite, envía el archivo datos/registro_ia.log.")


def probar() -> dict:
    """Comprueba que la clave funciona: basta con que DeepSeek responda."""
    texto, uso = chat(
        [{"role": "user", "content": 'Devuelve un objeto JSON con la clave "estado" y el valor "listo".'}],
        json_salida=True, max_tokens=60, timeout=60,
    )
    try:
        leer_json(texto)
        formato = True
    except ErrorIA:
        formato = False
        _registrar_falla(texto, "prueba de conexión", 1)
    return {"ok": True, "formato_json": formato, "modelo": _modelo(), "uso": uso}
