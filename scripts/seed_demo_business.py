"""Crea un negocio de demo con varios soportes físicos para probar el flujo.

Uso (desde la raíz del proyecto, con el entorno virtual activado):
    python -m scripts.seed_demo_business
"""

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Business, Placement
from app.services.qrcode_gen import generate_qr_for_token, target_url

DEMO_NAME = "Café Demo"
DEMO_PLACEMENTS = ["Mesa 5", "Mesón de pago", "Boleta"]


def seed() -> None:
    init_db()

    with SessionLocal() as db:
        business = db.scalar(select(Business).where(Business.name == DEMO_NAME))
        if business is None:
            business = Business(
                name=DEMO_NAME,
                google_review_url="https://search.google.com/local/writereview?placeid=REEMPLAZAR_CON_PLACE_ID_REAL",
                telegram_chat_id=settings.telegram_chat_id,
            )
            db.add(business)
            db.flush()
            for label in DEMO_PLACEMENTS:
                db.add(Placement(business_id=business.id, label=label))
            db.commit()
            print(f"Negocio de demo creado: {business.name}")
        else:
            print(f"Negocio de demo ya existía: {business.name}")

        placements = db.scalars(select(Placement).where(Placement.business_id == business.id)).all()

        print("\nSoportes físicos (cada uno con su propio código, el que va grabado en el chip):")
        for placement in placements:
            generate_qr_for_token(placement.token)
            print(f"  · {placement.label:<15} {target_url(placement.token)}   (QR: qrcodes/{placement.token}.png)")

        print(f"\nPanel del negocio: {settings.base_url.rstrip('/')}/dashboard/?t={business.dashboard_token}")
        print(
            "\nOJO: BASE_URL debe apuntar al dominio definitivo ANTES de grabar chips o "
            "imprimir placas — la URL no se puede cambiar después."
        )


if __name__ == "__main__":
    seed()
