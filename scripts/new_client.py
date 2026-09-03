"""Alta de un cliente nuevo: crea el negocio, sus placas y sus códigos QR.

Reemplaza el tener que escribir Python a mano para dar de alta a alguien.

    python -m scripts.new_client                       # modo interactivo
    python -m scripts.new_client --nombre "Café Central" \\
        --google-url "https://g.page/r/CXXXX/review" --placas "Mesa 1,Mesa 2,Mesón"

    python -m scripts.new_client --listar               # ver clientes y sus tokens
    python -m scripts.new_client --agregar TOKEN --placas "Mesa 7,Mesa 8"
    python -m scripts.new_client --rotar-token TOKEN     # invalida el enlace del informe
"""

import argparse
import sys

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Business, Placement, new_token
from app.services.auth import generate_password, hash_password
from app.services.qrcode_gen import generate_qr_for_token, target_url

PLACEHOLDER_MARKERS = ("REEMPLAZAR", "PLACE_ID", "ejemplo", "example")
KNOWN_PATTERNS = ("g.page/r/", "search.google.com/local/writereview", "maps.app.goo.gl", "goo.gl/maps")

LINE = "-" * 72

# La consola de Windows usa cp1252 por defecto y revienta ante cualquier
# carácter fuera de ese rango (un nombre de negocio con una comilla tipográfica,
# por ejemplo). Nada de lo que imprime este script justifica un crash.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # consolas que no lo permiten
        pass


def _warn_base_url() -> None:
    """La URL de los QR queda grabada en el chip. Generarlos apuntando a
    localhost produce placas inservibles."""
    base = settings.base_url.rstrip("/")
    if "localhost" in base or "127.0.0.1" in base:
        print(f"\n  [!] BASE_URL es {base}")
        print("     Los QR que se generen ahora solo funcionan en TU equipo.")
        print("     Sirven para probar, NO para imprimir ni entregar a un cliente.")
        print("     Antes de fabricar placas, pon el dominio definitivo en .env (BASE_URL).")


def _check_google_url(url: str) -> None:
    if any(marker in url for marker in PLACEHOLDER_MARKERS):
        print("\n  [!] Ese link parece un placeholder, no un link real de Google.")
    elif not url.startswith(("http://", "https://")):
        print("\n  [!] El link debería empezar con https://")
    elif not any(pattern in url for pattern in KNOWN_PATTERNS):
        print("\n  [!] El link no se parece a un enlace de reseña de Google.")
        print("     Lo esperado es algo tipo https://g.page/r/…/review")


def _show(business: Business, placements: list[Placement], password: str = "") -> None:
    print(f"\n{LINE}\n  {business.name}\n{LINE}")
    print("\n  PLACAS  (cada código va grabado en su propio chip)\n")
    for p in placements:
        generate_qr_for_token(p.token)
        print(f"    {p.label}")
        print(f"      {target_url(p.token)}")
        print(f"      QR: qrcodes/{p.token}.png\n")

    base = settings.base_url.rstrip("/")

    if password:
        print("  CREDENCIALES DEL PANEL  (entrégaselas al dueño)\n")
        print(f"    Entrar en: {base}/panel/login")
        print(f"    Correo:    {business.login_email}")
        print(f"    Clave:     {password}")
        # La contraseña se guarda con hash: si se pierde, no se recupera, se
        # genera otra con --reset-password.
        print("\n    Anótala ahora: no se puede volver a mostrar.\n")
    else:
        print("  [!] Sin correo no se crearon credenciales del panel.")
        print("      Asígnalas después con --reset-password.\n")

    print(f"  Informe mensual (enlace directo, va por correo): {base}/informe/{business.dashboard_token}\n")
    _warn_base_url()
    print()


def _ask(prompt: str, required: bool = True) -> str:
    while True:
        value = input(prompt).strip()
        if value or not required:
            return value
        print("  (obligatorio)")


def listar() -> None:
    with SessionLocal() as db:
        businesses = db.scalars(select(Business).order_by(Business.id)).all()
        if not businesses:
            print("No hay clientes todavía.")
            return
        base = settings.base_url.rstrip("/")
        print(f"\n{LINE}\n  CLIENTES\n{LINE}\n")
        for b in businesses:
            count = len(db.scalars(select(Placement).where(Placement.business_id == b.id)).all())
            acceso = b.login_email if b.password_hash else "SIN CREDENCIALES (usa --reset-password)"
            print(f"  {b.name}  ({count} placa{'s' if count != 1 else ''})")
            print(f"    Entra como: {acceso}")
            print(f"    Informe:    {base}/informe/{b.dashboard_token}\n")


def agregar(token: str, labels: list[str]) -> None:
    with SessionLocal() as db:
        business = db.scalar(select(Business).where(Business.dashboard_token == token))
        if business is None:
            sys.exit(f"No existe un cliente con el token '{token}'. Usa --listar para verlos.")

        nuevas = [Placement(business_id=business.id, label=label) for label in labels]
        db.add_all(nuevas)
        db.commit()
        for p in nuevas:
            db.refresh(p)

        print(f"\n  Agregadas {len(nuevas)} placa(s) a {business.name}.")
        print("\n  PLACAS NUEVAS\n")
        for p in nuevas:
            generate_qr_for_token(p.token)
            print(f"    {p.label}")
            print(f"      {target_url(p.token)}")
            print(f"      QR: qrcodes/{p.token}.png\n")
        _warn_base_url()
        print()


def crear(nombre: str, google_url: str, labels: list[str], telegram: str, email: str = "") -> None:
    _check_google_url(google_url)
    if not telegram and not email:
        print("\n  [!] Sin Telegram ni correo, el dueño no recibirá las alertas de queja,")
        print("      que son la principal razón por la que un cliente sigue pagando.")

    # El correo de alertas sirve también como usuario del panel: pedir dos
    # correos distintos confundiría sin aportar nada a esta escala.
    password = generate_password() if email else ""

    with SessionLocal() as db:
        business = Business(
            name=nombre,
            google_review_url=google_url,
            telegram_chat_id=telegram,
            alert_email=email,
            login_email=email,
            password_hash=hash_password(password) if password else "",
        )
        db.add(business)
        db.flush()
        placements = [Placement(business_id=business.id, label=label) for label in labels]
        db.add_all(placements)
        db.commit()

        db.refresh(business)
        for p in placements:
            db.refresh(p)

        _show(business, placements, password)


def reset_password(token: str) -> None:
    with SessionLocal() as db:
        business = db.scalar(select(Business).where(Business.dashboard_token == token))
        if business is None:
            sys.exit(f"No existe un cliente con el token '{token}'. Usa --listar para verlos.")
        if not business.login_email:
            sys.exit(
                f"'{business.name}' no tiene correo, así que no puede entrar al panel.\n"
                "Asígnale uno primero en la base de datos."
            )

        password = generate_password()
        business.password_hash = hash_password(password)
        db.commit()

        base = settings.base_url.rstrip("/")
        print(f"\n  Contraseña nueva para {business.name}\n")
        print(f"    Entrar en: {base}/panel/login")
        print(f"    Correo:    {business.login_email}")
        print(f"    Clave:     {password}")
        print("\n    Anótala ahora: no se puede volver a mostrar.\n")


def rotar_token(token: str) -> None:
    """Genera un enlace de informe nuevo e invalida el anterior.

    El enlace del informe no pide contraseña, a propósito: va por correo al dueño
    como el enlace de una factura. El precio de esa comodidad es que un correo
    reenviado, una casilla comprometida o un dueño que deja el negocio dejan ese
    enlace vivo para siempre, con los teléfonos y las quejas de los clientes
    finales adentro. Esto es la forma de cortarlo.

    Ojo: los enlaces viejos dejan de funcionar. Hay que mandarle el nuevo al dueño.
    """
    with SessionLocal() as db:
        business = db.scalar(select(Business).where(Business.dashboard_token == token))
        if business is None:
            sys.exit(f"No existe un cliente con el token '{token}'. Usa --listar para verlos.")

        anterior = business.dashboard_token
        business.dashboard_token = new_token()
        db.commit()
        db.refresh(business)

        base = settings.base_url.rstrip("/")
        print(f"\n  Enlace de informe nuevo para {business.name}\n")
        print(f"    Antes:  {base}/informe/{anterior}   (ya no funciona)")
        print(f"    Ahora:  {base}/informe/{business.dashboard_token}")
        print("\n    Mándaselo al dueño: el enlace anterior quedó invalidado.\n")


def interactivo() -> tuple[str, str, list[str], str, str]:
    print(f"\n{LINE}\n  ALTA DE CLIENTE NUEVO\n{LINE}\n")
    nombre = _ask("  Nombre del negocio: ")

    print("\n  Link de reseña de Google.")
    print("  Se obtiene en Google Business Profile → 'Solicitar reseñas',")
    print("  o armándolo con el Place ID real del local.")
    google_url = _ask("  Link: ")

    print("\n  Placas a instalar, separadas por coma.")
    print("  Ponles nombres que el dueño reconozca: 'Mesa 5', 'Mesón', 'Boleta'.")
    placas = _ask("  Placas: ")

    print("\n  Canales para avisarle al dueño cuando reciba una queja.")
    print("  El correo suele funcionar mejor: un dueño de pyme lo revisa a diario,")
    print("  y puede que ni tenga Telegram instalado.")
    email = _ask("  Correo (Enter para omitir): ", required=False)
    telegram = _ask("  Chat ID de Telegram (Enter para omitir): ", required=False)

    return nombre, google_url, [p.strip() for p in placas.split(",") if p.strip()], telegram, email


def main() -> None:
    parser = argparse.ArgumentParser(description="Da de alta un cliente con sus placas y QR.")
    parser.add_argument("--nombre", help="Nombre del negocio.")
    parser.add_argument("--google-url", help="Link de reseña de Google del negocio.")
    parser.add_argument("--placas", help="Nombres de las placas separados por coma.")
    parser.add_argument("--telegram", default="", help="Chat ID de Telegram para las alertas.")
    parser.add_argument("--email", default="", help="Correo del dueño para las alertas.")
    parser.add_argument("--listar", action="store_true", help="Lista los clientes existentes y sus enlaces.")
    parser.add_argument("--agregar", metavar="TOKEN", help="Agrega placas a un cliente existente.")
    parser.add_argument(
        "--reset-password", metavar="TOKEN", help="Genera una contraseña nueva para un cliente."
    )
    parser.add_argument(
        "--rotar-token",
        metavar="TOKEN",
        help="Genera un enlace de informe nuevo e invalida el anterior.",
    )
    args = parser.parse_args()

    init_db()

    if args.listar:
        return listar()

    if args.reset_password:
        return reset_password(args.reset_password)

    if args.rotar_token:
        return rotar_token(args.rotar_token)

    labels = [p.strip() for p in args.placas.split(",") if p.strip()] if args.placas else []

    if args.agregar:
        if not labels:
            sys.exit("Con --agregar necesitas --placas \"Mesa 7,Mesa 8\".")
        return agregar(args.agregar, labels)

    if args.nombre and args.google_url and labels:
        return crear(args.nombre, args.google_url, labels, args.telegram, args.email)

    if any([args.nombre, args.google_url, args.placas]):
        sys.exit("Para crear un cliente necesitas --nombre, --google-url y --placas (o ninguno, para el modo interactivo).")

    nombre, google_url, labels, telegram, email = interactivo()
    if not labels:
        sys.exit("Necesitas al menos una placa.")
    crear(nombre, google_url, labels, telegram, email)


if __name__ == "__main__":
    main()
