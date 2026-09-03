"""Envío mensual del informe a todos los clientes.

Pensado para correr agendado a principios de cada mes. Por defecto manda el
informe del último mes completo.

    python -m scripts.send_reports --dry-run     # muestra qué se enviaría
    python -m scripts.send_reports               # envía de verdad
    python -m scripts.send_reports --mes 2026-08 --token 4VB6_OoK

Salida con código 1 si algún envío falló, para que el agendador lo note.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Business
from app.services import report as report_service
from app.services.notify import notify_with_report

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


async def enviar(business: Business, year: int, month: int, adjuntar_pdf: bool) -> bool:
    resumen = report_service.build_summary_text(business, year, month, settings.base_url)
    asunto = f"Informe de reseñas — {business.name}"

    pdf = None
    if adjuntar_pdf:
        # El PDF es un extra: si el motor no está disponible, el resumen con el
        # enlace ya cumple. No se considera un fallo del envío.
        try:
            pdf = report_service.render_pdf(business, year, month)
        except report_service.PDFEngineUnavailable:
            print("      (sin PDF adjunto: WeasyPrint no disponible en este equipo)")

    return await notify_with_report(business, asunto, resumen, pdf)


def main() -> None:
    parser = argparse.ArgumentParser(description="Envía el informe mensual a los clientes.")
    parser.add_argument("--mes", help="Período AAAA-MM. Por defecto, el último mes completo.")
    parser.add_argument("--token", help="Enviar solo a este cliente (su dashboard_token).")
    parser.add_argument("--dry-run", action="store_true", help="Muestra el mensaje sin enviarlo.")
    parser.add_argument("--sin-pdf", action="store_true", help="No adjuntar el PDF.")
    args = parser.parse_args()

    year, month = report_service.resolve_period(args.mes)

    with SessionLocal() as db:
        query = select(Business)
        if args.token:
            query = query.where(Business.dashboard_token == args.token)
        clientes = db.scalars(query).all()

        if not clientes:
            sys.exit("No hay clientes a los que enviar.")

        print(f"Informe de {year}-{month:02d} · {len(clientes)} cliente(s)\n")
        # Omitido y fallido no son lo mismo: un cliente sin canal configurado es
        # una tarea pendiente del operador, no un error del envío. Mezclarlos deja
        # el workflow mensual en rojo todos los meses y enseña a ignorarlo, que es
        # peor que no tener alerta.
        fallidos, omitidos = [], []

        for business in clientes:
            print(f"  {business.name}")

            if args.dry_run:
                resumen = report_service.build_summary_text(business, year, month, settings.base_url)
                print("      " + resumen.replace("\n", "\n      ") + "\n")
                continue

            if not business.telegram_chat_id and not business.alert_email:
                print("      sin canal de aviso configurado (ni Telegram ni correo), se omite\n")
                omitidos.append(business.name)
                continue

            if asyncio.run(enviar(business, year, month, not args.sin_pdf)):
                print("      enviado\n")
            else:
                print("      FALLÓ el envío\n")
                fallidos.append(business.name)

    if omitidos:
        print(f"Sin canal de aviso configurado ({len(omitidos)}): {', '.join(omitidos)}")
        print("  Asígnales correo o Telegram para que reciban su informe.\n")

    # Solo un fallo real corta con error: es lo que tiene que ver el agendador.
    if fallidos:
        sys.exit(f"No se pudo enviar a: {', '.join(fallidos)}")


if __name__ == "__main__":
    main()
