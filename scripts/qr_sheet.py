"""Hoja de placas lista para imprimir y recortar.

Es la pieza que se le manda a quien fabrica: un A4 con una tarjeta por soporte,
con su QR, su etiqueta y la URL en texto para poder grabarla en el chip NFC.

Los QR van embebidos como data: URI, así que el archivo se puede enviar por
correo y funciona solo, sin depender de que el servidor esté encendido.

    python -m scripts.qr_sheet --token 4VB6_OoK
    python -m scripts.qr_sheet --token 4VB6_OoK --salida placas.html
"""

import argparse
import base64
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Business, Placement
from app.services.qrcode_gen import qr_png_bytes, target_url

# La consola de Windows usa cp1252 y revienta con cualquier carácter fuera de ese
# rango; un nombre de negocio con tilde no puede tumbar el script.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"
OUT_DIR = Path(__file__).resolve().parent.parent / "informes"


HOSTS_PROVISIONALES = ("localhost", "127.0.0.1", "onrender.com", "testserver", "ngrok")


def es_apta_para_imprimir(base_url: str) -> bool:
    """¿Esta URL se puede grabar en un chip y pegar a una mesa para siempre?

    El criterio es al revés de lo intuitivo: se asume provisional salvo prueba en
    contrario. Imprimir con una dirección temporal es el único error irreversible
    del proyecto —la placa queda pegada y su URL no se puede cambiar—, así que una
    URL desconocida tiene que hacer saltar el aviso, no pasar de largo.

    Apta significa las tres cosas: https (un dominio propio en producción lo
    tiene), sin puerto explícito (nadie imprime ":8000" en una placa) y sin
    parecerse a un host de desarrollo o de hosting temporal.
    """
    if not base_url.startswith("https://"):
        return False

    host = base_url.split("//", 1)[1].split("/")[0]
    if ":" in host:
        return False

    return not any(marca in host for marca in HOSTS_PROVISIONALES)


def construir(business: Business, placements: list[Placement]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )

    base = settings.base_url.rstrip("/")
    provisional = not es_apta_para_imprimir(base)

    tarjetas = [
        {
            "label": p.label,
            "url": target_url(p.token),
            "qr_base64": base64.b64encode(qr_png_bytes(p.token)).decode("ascii"),
        }
        for p in placements
    ]

    # El logo va embebido igual que los QR: la hoja se le manda por correo a quien
    # fabrica las placas y tiene que verse completa sin acceso al servidor.
    logo = base64.b64encode(business.logo_data).decode("ascii") if business.logo_data else ""

    return env.get_template("qr_sheet.html").render(
        business=business,
        placements=tarjetas,
        base_url=base,
        aviso_base_url=provisional,
        logo=logo,
        generado_el=datetime.now(ZoneInfo(settings.timezone)).strftime("%d-%m-%Y"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera la hoja de placas para imprimir.")
    parser.add_argument("--token", help="dashboard_token del cliente. Si se omite, usa el primero.")
    parser.add_argument("--salida", help="Ruta del archivo HTML. Por defecto, informes/placas-<negocio>.html")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.token:
            business = db.scalar(select(Business).where(Business.dashboard_token == args.token))
            if business is None:
                sys.exit(f"No existe un cliente con el token '{args.token}'.")
        else:
            business = db.scalars(select(Business)).first()
            if business is None:
                sys.exit("No hay clientes. Crea uno con 'python -m scripts.new_client'.")

        placements = db.scalars(
            select(Placement).where(Placement.business_id == business.id).order_by(Placement.id)
        ).all()
        if not placements:
            sys.exit(f"'{business.name}' no tiene placas. Agrégalas con --agregar.")

        html = construir(business, placements)

    if args.salida:
        destino = Path(args.salida)
    else:
        seguro = "".join(c if c.isalnum() or c in "-_" else "-" for c in business.name.lower())
        OUT_DIR.mkdir(exist_ok=True)
        destino = OUT_DIR / f"placas-{seguro}.html"

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html, encoding="utf-8")

    print(f"\n  {business.name} · {len(placements)} placa(s)")
    print(f"  Guardado en: {destino}")
    print("\n  Ábrelo en el navegador e imprime, o guarda como PDF para mandárselo")
    print("  a quien fabrique las placas.\n")

    base = settings.base_url.rstrip("/")
    if "localhost" in base or "127.0.0.1" in base:
        print(f"  [!] BASE_URL es {base}: la hoja lleva un aviso de NO IMPRIMIR.")
        print("      Pon el dominio definitivo en .env antes de fabricar nada.\n")


if __name__ == "__main__":
    main()
