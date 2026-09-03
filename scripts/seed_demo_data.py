"""Genera actividad histórica realista para demostraciones.

Un informe con 4 visitas no vende nada. Esto llena la base con un par de meses
de tráfico verosímil para que el panel y el informe mensual se vean como se
verían en un local real: con tendencia, con comparación contra el mes anterior,
con una placa que rinde mejor que las otras y con quejas de verdad.

Escribe directamente en la base con fechas hacia atrás, sin pasar por las rutas
(que siempre marcan la hora actual).

Uso:
    python -m scripts.seed_demo_data --limpiar
    python -m scripts.seed_demo_data --dias 90
"""

import argparse
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.database import SessionLocal, init_db
from app.models import Business, Feedback, Placement, Tap

# Cada soporte convierte distinto: es lo que hace que el informe tenga algo
# accionable que decir ("la placa de la mesa rinde el doble que la boleta").
CONVERSION_BY_LABEL = {
    "Mesa 5": 0.46,
    "Mesón de pago": 0.31,
    "Boleta": 0.17,
}
DEFAULT_CONVERSION = 0.30

# Reparto del tráfico entre soportes.
TRAFFIC_WEIGHT = {"Mesa 5": 0.5, "Mesón de pago": 0.34, "Boleta": 0.16}

BOT_AGENTS = [
    "WhatsApp/2.23.20.79 A",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "facebookexternalhit/1.1",
    "Mozilla/5.0 (compatible; UptimeRobot/2.0)",
]
PHONE_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; moto g84) AppleWebKit/537.36 Chrome/122.0 Mobile Safari/537.36",
]

COMPLAINTS = [
    ("La espera fue larga, casi 30 minutos por dos cafés.", "+56 9 8123 4567", 2),
    ("El café estaba frío y cuando lo dije nadie se hizo cargo.", "", 1),
    ("Muy rico todo, pero el baño estaba sucio.", "camila.r@correo.cl", 3),
    ("Cobraron un ítem que no pedimos. Lo arreglaron, pero demoró.", "+56 9 7654 3210", 2),
    ("El local estaba muy ruidoso, imposible conversar.", "", 3),
    ("Pedí sin lactosa y me trajeron con leche normal.", "jperez@correo.cl", 2),
    ("Atención lenta en la caja a la hora de almuerzo.", "", 3),
]


def _visits_for(day: datetime, boost: float) -> int:
    """Tráfico diario: los fines de semana suben, y el mes actual va algo mejor
    que el anterior para que la comparación muestre tendencia."""
    base = 22 if day.weekday() >= 4 else 13
    return max(0, int(random.gauss(base * boost, base * 0.28)))


def seed(days: int, wipe: bool) -> None:
    init_db()
    random.seed(20260902)

    with SessionLocal() as db:
        business = db.scalars(select(Business)).first()
        if business is None:
            raise SystemExit("No hay negocio. Corre antes: python -m scripts.seed_demo_business")

        placements = db.scalars(select(Placement).where(Placement.business_id == business.id)).all()
        if not placements:
            raise SystemExit("El negocio no tiene soportes. Corre: python -m scripts.seed_demo_business")

        if wipe:
            db.execute(delete(Tap).where(Tap.business_id == business.id))
            db.execute(delete(Feedback).where(Feedback.business_id == business.id))
            db.commit()
            print("Actividad anterior borrada.")

        weights = [TRAFFIC_WEIGHT.get(p.label, 0.2) for p in placements]
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        taps, feedbacks = [], []

        for offset in range(days, -1, -1):
            day = today - timedelta(days=offset)
            # El mes en curso rinde ~15% mejor que el anterior.
            boost = 1.15 if day.month == today.month else 1.0

            for _ in range(_visits_for(day, boost)):
                placement = random.choices(placements, weights=weights, k=1)[0]
                session = uuid.uuid4().hex
                agent = random.choice(PHONE_AGENTS)
                # Horario de local: mayor densidad al mediodía y en la tarde.
                moment = day + timedelta(hours=random.choice([9, 11, 13, 13, 14, 17, 19, 20]),
                                         minutes=random.randint(0, 59))

                taps.append(Tap(business_id=business.id, placement_id=placement.id, session_id=session,
                                created_at=moment, user_agent=agent, is_bot=False, outcome="landed"))

                rate = CONVERSION_BY_LABEL.get(placement.label, DEFAULT_CONVERSION)
                if random.random() < rate:
                    taps.append(Tap(business_id=business.id, placement_id=placement.id, session_id=session,
                                    created_at=moment + timedelta(seconds=random.randint(4, 40)),
                                    user_agent=agent, is_bot=False, outcome="went_to_google"))
                elif random.random() < 0.05:
                    text, contact, rating = random.choice(COMPLAINTS)
                    when = moment + timedelta(seconds=random.randint(20, 180))
                    feedbacks.append(Feedback(business_id=business.id, placement_id=placement.id,
                                              created_at=when, rating=rating, contact=contact, message=text))
                    taps.append(Tap(business_id=business.id, placement_id=placement.id, session_id=session,
                                    created_at=when, user_agent=agent, is_bot=False,
                                    outcome="left_private_feedback"))

            # Tráfico automatizado, para que se vea que el filtro trabaja.
            for _ in range(random.randint(0, 3)):
                placement = random.choice(placements)
                taps.append(Tap(business_id=business.id, placement_id=placement.id,
                                session_id=uuid.uuid4().hex,
                                created_at=day + timedelta(hours=random.randint(0, 23)),
                                user_agent=random.choice(BOT_AGENTS), is_bot=True, outcome="landed"))

        db.add_all(taps)
        db.add_all(feedbacks)
        db.commit()

        real = sum(1 for t in taps if not t.is_bot and t.outcome == "landed")
        clicks = sum(1 for t in taps if t.outcome == "went_to_google")
        bots = sum(1 for t in taps if t.is_bot)
        print(f"Generados {days} días de actividad para {business.name}:")
        print(f"  {real} visitas reales · {clicks} clicks a Google · {len(feedbacks)} quejas privadas")
        print(f"  {bots} visitas de bots (se excluyen de toda métrica)")
        print("\nPanel:   /panel/login  (demo@cafe.cl / demo1234)")
        print(f"Informe: /informe/{business.dashboard_token}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera actividad de demo realista.")
    parser.add_argument("--dias", type=int, default=75, help="Días hacia atrás a generar (default 75).")
    parser.add_argument("--limpiar", action="store_true", help="Borra la actividad existente antes de generar.")
    args = parser.parse_args()
    seed(args.dias, args.limpiar)
