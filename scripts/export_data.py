"""Exporta los datos de un cliente a CSV.

Sirve para tres cosas que en algún momento hacen falta: respaldar antes de un
cambio grande, entregarle sus datos a un cliente que los pide (o que se va), y
revisar números a mano cuando algo no cuadra.

    python -m scripts.export_data --listar
    python -m scripts.export_data --token 4VB6_OoK
    python -m scripts.export_data --todos --destino respaldos/
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Business
from app.services import metrics

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

DESTINO_POR_DEFECTO = Path("exportaciones")


def _nombre_archivo(business: Business, que: str) -> str:
    seguro = "".join(c if c.isalnum() or c in "-_" else "-" for c in business.name.lower())
    return f"{seguro}-{que}-{date.today():%Y%m%d}.csv"


def exportar(business: Business, destino: Path) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    escritos = []

    tablas = [
        ("visitas", metrics.load_taps(business.id)),
        ("quejas", metrics.load_feedback(business.id)),
    ]

    # Los sellos solo si el negocio tiene programa, para no llenar el respaldo de
    # archivos vacíos. Van al respaldo por una razón distinta de las visitas: no
    # es historial, es una deuda. Si se pierden, un cliente que ya juntó los suyos
    # llega al mostrador y el sistema le dice que no tiene nada, delante del
    # cajero y sin forma de demostrarlo.
    sellos = metrics.load_sellos(business.id)
    premios = metrics.load_premios(business.id)
    if not sellos.empty or not premios.empty:
        tablas += [("sellos", sellos), ("premios", premios)]

    for que, datos in tablas:
        ruta = destino / _nombre_archivo(business, que)
        # utf-8-sig para que Excel en Windows no destroce los acentos.
        datos.to_csv(ruta, index=False, encoding="utf-8-sig")
        escritos.append(ruta)
        print(f"    {len(datos):>5} filas → {ruta}")

    return escritos


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta los datos de un cliente a CSV.")
    parser.add_argument("--token", help="dashboard_token del cliente.")
    parser.add_argument("--todos", action="store_true", help="Exporta todos los clientes.")
    parser.add_argument("--listar", action="store_true", help="Lista los clientes disponibles.")
    parser.add_argument("--destino", default=str(DESTINO_POR_DEFECTO), help="Carpeta de salida.")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.listar:
            for b in db.scalars(select(Business).order_by(Business.id)):
                print(f"  {b.dashboard_token}  {b.name}")
            return

        if args.todos:
            negocios = list(db.scalars(select(Business).order_by(Business.id)))
        elif args.token:
            negocios = [db.scalar(select(Business).where(Business.dashboard_token == args.token))]
            if negocios[0] is None:
                sys.exit(f"No existe un cliente con el token '{args.token}'.")
        else:
            sys.exit("Indica --token, --todos o --listar.")

        destino = Path(args.destino)
        for business in negocios:
            print(f"\n  {business.name}")
            exportar(business, destino)

        from app.config import settings

        print(f"\n  Listo. Las fechas van en hora local ({settings.timezone}).\n")


if __name__ == "__main__":
    main()
