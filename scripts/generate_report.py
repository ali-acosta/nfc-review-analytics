"""Genera el informe mensual de un negocio a un archivo.

Sirve para probarlo y, más adelante, para el envío automático mensual.

Uso (desde la raíz del proyecto, con el entorno virtual activado):
    python -m scripts.generate_report --token 4VB6_OoK
    python -m scripts.generate_report --token 4VB6_OoK --mes 2026-08
    python -m scripts.generate_report --token 4VB6_OoK --pdf
"""

import argparse
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Business
from app.services import report as report_service

OUT_DIR = Path(__file__).resolve().parent.parent / "informes"


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera el informe mensual de un negocio.")
    parser.add_argument("--token", help="dashboard_token del negocio. Si se omite, usa el primero que exista.")
    parser.add_argument("--mes", help="Período en formato AAAA-MM. Por defecto, el mes actual.")
    parser.add_argument("--pdf", action="store_true", help="Genera PDF en vez de HTML (requiere WeasyPrint).")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.token:
            business = db.scalar(select(Business).where(Business.dashboard_token == args.token))
        else:
            business = db.scalars(select(Business)).first()

        if business is None:
            raise SystemExit("No se encontró el negocio. ¿Corriste 'python -m scripts.seed_demo_business'?")

        year, month = report_service.resolve_period(args.mes)
        OUT_DIR.mkdir(exist_ok=True)
        stem = f"informe-{business.id}-{year}-{month:02d}"

        if args.pdf:
            try:
                data = report_service.render_pdf(business, year, month)
            except report_service.PDFEngineUnavailable as exc:
                raise SystemExit(
                    "WeasyPrint no puede cargar sus librerías nativas en este equipo.\n"
                    f"  Detalle: {exc}\n\n"
                    "  Genera el HTML (sin --pdf) y usa Imprimir → Guardar como PDF,\n"
                    "  o instala el runtime de GTK3 para Windows."
                )
            out = OUT_DIR / f"{stem}.pdf"
            out.write_bytes(data)
        else:
            out = OUT_DIR / f"{stem}.html"
            out.write_text(report_service.render_html(business, year, month), encoding="utf-8")

        print(f"Informe de {business.name} · {year}-{month:02d}")
        print(f"Guardado en: {out}")


if __name__ == "__main__":
    main()
