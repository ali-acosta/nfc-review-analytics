"""Crea un negocio de demo con varios soportes físicos para probar el flujo.

Uso (desde la raíz del proyecto, con el entorno virtual activado):
    python -m scripts.seed_demo_business
"""

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Business, Placement
from app.services.auth import hash_password
from app.services import enlaces
from app.services import report as report_service
from app.services.qrcode_gen import generate_qr_for_token, target_url

DEMO_NAME = "Café Demo"
DEMO_PLACEMENTS = ["Mesa 5", "Mesón de pago", "Boleta"]

# Credenciales fijas y publicadas en el README: es una demo, no un cliente. Si no
# se crean aquí, existen solo en la base local de quien las tecleó una vez, y
# cualquiera que clone el repositorio y siga las instrucciones no puede entrar.
DEMO_EMAIL = "demo@cafe.cl"
DEMO_PASSWORD = "demo1234"


def seed() -> None:
    init_db()

    with SessionLocal() as db:
        business = db.scalar(select(Business).where(Business.name == DEMO_NAME))
        if business is None:
            business = Business(
                name=DEMO_NAME,
                google_review_url="https://search.google.com/local/writereview?placeid=REEMPLAZAR_CON_PLACE_ID_REAL",
                telegram_chat_id=settings.telegram_chat_id,
                login_email=DEMO_EMAIL,
                alert_email=DEMO_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
            )
            db.add(business)
            db.flush()
            for label in DEMO_PLACEMENTS:
                db.add(Placement(business_id=business.id, label=label))
            db.commit()
            print(f"Negocio de demo creado: {business.name}")
        else:
            print(f"Negocio de demo ya existía: {business.name}")
            # Una demo creada antes de que existiera el login quedaría sin
            # credenciales y sin forma de entrar al panel.
            if not business.password_hash:
                business.login_email = DEMO_EMAIL
                business.alert_email = business.alert_email or DEMO_EMAIL
                business.password_hash = hash_password(DEMO_PASSWORD)
                db.commit()
                print("  (se le asignaron las credenciales de demo que le faltaban)")

        placements = db.scalars(select(Placement).where(Placement.business_id == business.id)).all()

        print("\nSoportes físicos (cada uno con su propio código, el que va grabado en el chip):")
        for placement in placements:
            generate_qr_for_token(placement.token)
            print(f"  · {placement.label:<15} {target_url(placement.token)}   (QR: qrcodes/{placement.token}.png)")

        base = settings.base_url.rstrip("/")
        print(f"\nPanel del negocio: {base}/panel/login")
        print(f"  Correo: {DEMO_EMAIL}")
        print(f"  Clave:  {DEMO_PASSWORD}")
        year, month = report_service.resolve_period(None)
        # Firmado y por mes: el enlace a secas ya no abre nada.
        print("\nInforme mensual (enlace directo, vale 90 días):")
        print(f"  {enlaces.url_informe(business.dashboard_token, year, month)}")
        print(
            "\nOJO: BASE_URL debe apuntar al dominio definitivo ANTES de grabar chips o "
            "imprimir placas — la URL no se puede cambiar después."
        )


if __name__ == "__main__":
    seed()
