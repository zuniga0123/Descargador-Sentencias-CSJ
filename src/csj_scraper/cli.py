"""CLI para descargar providencias de la Sala Laboral de la CSJ y de la
Corte Constitucional.

Ejemplos:
    python main.py --anio 2026
    python main.py --anio 2020-2026
    python main.py --anio 2024 --tipo SENTENCIA --limite 20
    python main.py --corte constitucional --anio 2019 --tipo T --max-minutos 25
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from . import config
from .pipeline import ejecutar, reclasificar, reconstruir_indice


def _parsear_anios(valor: str) -> list[str]:
    """'2024' -> ['2024']; '2020-2022' -> ascendente; '2022-2020' -> descendente."""
    if "-" in valor:
        inicio, fin = (int(x) for x in valor.split("-", 1))
        paso = 1 if fin >= inicio else -1
        return [str(a) for a in range(inicio, fin + paso, paso)]
    return [valor]


def main() -> None:
    anio_actual = datetime.now().year
    parser = argparse.ArgumentParser(
        description="Descarga y clasifica providencias de la Sala de Casación Laboral y la Sala de "
        "Descongestión Laboral de la Corte Suprema de Justicia, o de la Corte Constitucional."
    )
    parser.add_argument(
        "--corte",
        choices=["suprema", "constitucional"],
        default="suprema",
        help="Corte a descargar. Por defecto: suprema (Sala Laboral). Las sentencias de la Corte "
        "Constitucional se guardan en el repositorio Descargador-Sentencias-CC, clonado junto a este.",
    )
    parser.add_argument(
        "--anio",
        default=None,
        help="Año único (2024) o rango (2011-2026). Por defecto: últimos 15 años (suprema) o "
        "desde 1992 (constitucional).",
    )
    parser.add_argument(
        "--tipo",
        action="append",
        help="Filtrar por tipo de providencia; se puede repetir. Suprema: SENTENCIA, AUTO. "
        "Constitucional: T, C, SU, A (auto). Por defecto, sin autos: SENTENCIA en la "
        "Suprema; T, C y SU en la Constitucional.",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Detener tras descargar este número de documentos nuevos (útil para pruebas).",
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Re-descargar aunque ya exista en el índice.",
    )
    parser.add_argument(
        "--con-original",
        action="store_true",
        help="Además del Markdown, descargar también el PDF/Word original de cada providencia "
        "(duplica tiempo y espacio en disco). Por defecto solo se guarda Markdown + metadata.",
    )
    parser.add_argument(
        "--max-minutos",
        type=float,
        default=None,
        help="Detenerse ordenadamente tras N minutos, guardando el avance (para entornos "
        "que cortan los procesos largos). Volver a correr el mismo comando continúa.",
    )
    parser.add_argument(
        "--reenumerar",
        action="store_true",
        help="Ignorar la enumeración guardada y volver a consultar la lista de providencias "
        "(útil para años recientes en los que la Corte sigue publicando).",
    )
    parser.add_argument(
        "--reclasificar",
        action="store_true",
        help="No descarga nada: vuelve a aplicar las reglas de clasificación a todo lo "
        "descargado (tras cambiar src/csj_scraper/taxonomy.py) y mueve los archivos.",
    )
    parser.add_argument(
        "--reconstruir-indice",
        action="store_true",
        help="No descarga nada: regenera jurisprudencia/indice.sqlite a partir de los "
        ".md y _metadata.json existentes (p.ej. después de clonar el repositorio).",
    )
    parser.add_argument(
        "--verboso",
        action="store_true",
        help="Mostrar más detalle en los logs.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verboso else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.corte == "constitucional":
        _main_constitucional(args, parser)
        return

    tipos_validos = config.TIPOS_PROVIDENCIA
    if args.tipo and not set(args.tipo) <= set(tipos_validos):
        parser.error(f"--tipo para la Corte Suprema debe ser uno de: {', '.join(tipos_validos)}")
    if args.reconstruir_indice:
        reconstruir_indice()
        return
    if args.reclasificar:
        reclasificar()
        return

    anios = _parsear_anios(args.anio or f"{anio_actual - config.ANIOS_A_CUBRIR + 1}-{anio_actual}")
    ejecutar(
        anios=anios,
        tipos=args.tipo,
        limite=args.limite,
        forzar=args.forzar,
        descargar_original=args.con_original,
        max_minutos=args.max_minutos,
        reenumerar=args.reenumerar,
    )


def _main_constitucional(args, parser) -> None:
    from cc_scraper import config as cc_config
    from cc_scraper import pipeline as cc_pipeline

    if not cc_config.DESTINO.is_dir():
        parser.error(
            f"No encuentro el repositorio de datos de la Corte Constitucional en {cc_config.DESTINO}. "
            "Clónalo ahí (rama datos) o indica otra ruta con la variable de entorno CC_DATOS_DIR."
        )
    if args.tipo and not set(args.tipo) <= set(cc_config.TIPOS):
        parser.error(f"--tipo para la Corte Constitucional debe ser uno de: {', '.join(cc_config.TIPOS)}")
    if args.reclasificar:
        parser.error("--reclasificar solo aplica a la Corte Suprema (la Constitucional usa los temas oficiales).")
    if args.reconstruir_indice:
        cc_pipeline.reconstruir_indice()
        return
    anios = _parsear_anios(args.anio or f"{cc_config.ANIO_INICIAL}-{datetime.now().year}")
    cc_pipeline.ejecutar(
        anios=[int(a) for a in anios],
        tipos=args.tipo,
        limite=args.limite,
        max_minutos=args.max_minutos,
        reenumerar=args.reenumerar,
    )


if __name__ == "__main__":
    main()
