"""Configuración común de los tests.

El entorno se fija ANTES de importar nada de `app`, porque `app.config` crea el
objeto `settings` y `app.database` crea el engine en tiempo de import: si no se
adelanta, los tests escribirían en la base real del proyecto.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

_TMP_DIR = Path(tempfile.mkdtemp(prefix="nfc-tests-"))
# TEST_DATABASE_URL permite correr la misma suite contra Postgres (lo hace CI).
# Se lee de una variable propia y NO de DATABASE_URL: si alguien tuviera esa
# exportada en su terminal, la suite escribiría en su base real.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ["BASE_URL"] = "http://testserver"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Business,
    Feedback,
    LoyaltyCard,
    LoyaltyProgram,
    Placement,
    Reward,
    Stamp,
    Tap,
)

PHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
BOT_UA = "WhatsApp/2.23.20.79 A"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean():
    """Cada test parte de una base vacía. Se borra en orden hijo → padre.

    `LoyaltyProgram` va antes que `Placement` porque apunta a la placa que se le
    crea al activar el programa.
    """
    with SessionLocal() as db:
        for model in (Stamp, Reward, LoyaltyCard, LoyaltyProgram, Tap, Feedback, Placement, Business):
            db.execute(delete(model))
        db.commit()
    yield


@pytest.fixture
def negocio():
    """Un negocio con dos placas. Devuelve valores planos, no objetos ORM, que
    quedarían desconectados al cerrarse la sesión."""
    with SessionLocal() as db:
        business = Business(name="Café de Prueba", google_review_url="https://g.page/r/CTest123/review")
        db.add(business)
        db.flush()
        mesa = Placement(business_id=business.id, label="Mesa 1")
        meson = Placement(business_id=business.id, label="Mesón")
        db.add_all([mesa, meson])
        db.commit()
        return SimpleNamespace(
            id=business.id,
            nombre=business.name,
            google_url=business.google_review_url,
            token=business.dashboard_token,
            mesa=mesa.token,
            mesa_id=mesa.id,
            meson=meson.token,
            meson_id=meson.id,
        )


@pytest.fixture
def programa(negocio):
    """Un negocio con programa de sellos activo, tal como lo deja el panel del dueño.

    Tres sellos y no cinco para que un test pueda completar una tarjeta sin
    inventar seis días distintos.
    """
    with SessionLocal() as db:
        placa = Placement(business_id=negocio.id, label="Caja (fidelización)")
        db.add(placa)
        db.flush()
        prog = LoyaltyProgram(
            business_id=negocio.id,
            placement_id=placa.id,
            stamps_required=3,
            reward="El 4° café gratis",
        )
        db.add(prog)
        db.commit()
        return SimpleNamespace(
            id=prog.id,
            token=prog.token,
            secret=prog.secret,
            requeridos=prog.stamps_required,
            premio=prog.reward,
            placa=placa.token,
            negocio=negocio,
        )


@pytest.fixture
def cliente():
    """Un visitante. TestClient guarda cookies, así que cada instancia se
    comporta como un teléfono distinto."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def visitante():
    def _make():
        client = TestClient(app)
        client.headers["user-agent"] = PHONE_UA
        return client

    return _make


def add_tap(business_id, placement_id, outcome, *, session_id=None, when=None, is_bot=False):
    """Escribe un evento directamente, para armar escenarios con fechas pasadas."""
    with SessionLocal() as db:
        tap = Tap(
            business_id=business_id,
            placement_id=placement_id,
            session_id=session_id or uuid.uuid4().hex,
            outcome=outcome,
            is_bot=is_bot,
            user_agent=BOT_UA if is_bot else PHONE_UA,
            created_at=when or datetime.now(timezone.utc),
        )
        db.add(tap)
        db.commit()


def add_visit(business_id, placement_id, *, converts=False, when=None, is_bot=False):
    """Un visitante completo: llega y, opcionalmente, va a Google."""
    session_id = uuid.uuid4().hex
    add_tap(business_id, placement_id, "landed", session_id=session_id, when=when, is_bot=is_bot)
    if converts:
        later = (when + timedelta(seconds=20)) if when else None
        add_tap(business_id, placement_id, "went_to_google", session_id=session_id, when=later, is_bot=is_bot)
    return session_id


def url_informe(token: str, mes: str | None = None) -> str:
    """La URL firmada del informe, que es la única que abre.

    Los tests usaban la ruta a secas; desde que el enlace lleva firma con
    vencimiento (90 días, un solo mes), esa ruta responde 403. Este ayudante
    evita repetir el armado en cada test y deja el mes explícito a la vista.
    """
    from app.services import enlaces, report as report_service

    year, month = report_service.resolve_period(mes)
    return enlaces.ruta_informe(token, year, month)
