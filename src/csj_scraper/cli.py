"""CLI para descargar providencias de la Sala Laboral de la CSJ.

Ejemplos:
    python main.py --anio 2026
    python main.py --anio 2020-2026
    python main.py --anio 2024 --tipo SENTENCIA --limite 20
    python main.py --anio 2011-2026   # backfill completo de 15 años
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from . import config
from .pipeline import ejecutar


def _parsear_anios(valor: str) -> list[str]:
    if "-" in valor:
        inicio, fin = valor.split("-", 1)
        return [str(a) for a in range(int(inicio), int(fin) + 1)]
    return [valor]


def main() -> None:
    anio_actual = datetime.now().year
    parser = argparse.ArgumentParser(
        description="Descarga y clasifica providencias de la Sala de Casación Laboral "
        "y la Sala de Descongestión Laboral de la Corte Suprema de Justicia."
    )
    parser.add_argument(
        "--anio",
        default=f"{anio_actual - config.ANIOS_A_CUBRIR + 1}-{anio_actual}",
        help="Año único (2024) o rango (2011-2026). Por defecto: últimos 15 años.",
    )
    parser.add_argument(
        "--tipo",
        choices=config.TIPOS_PROVIDENCIA,
        action="append",
        help="Filtrar por tipo de providencia. Se puede repetir. Por defecto: SENTENCIA y AUTO.",
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

    anios = _parsear_anios(args.anio)
    ejecutar(anios=anios, tipos=args.tipo, limite=args.limite, forzar=args.forzar)


if __name__ == "__main__":
    main()
