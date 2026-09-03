import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Crea el esquema en SQLite, la vía rápida para tests y desarrollo.

    En cualquier otro motor NO se toca nada: si `create_all` corriera contra un
    Postgres vacío, dejaría las tablas creadas pero sin la marca de versión de
    Alembic, y el siguiente `alembic upgrade head` fallaría porque las tablas ya
    existen. El despliegue migra antes de arrancar (ver render.yaml); esto solo
    avisa si alguien levanta la app a mano sin haber migrado.
    """
    from app import models  # noqa: F401  (registers models on Base.metadata)

    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
        return

    logging.getLogger(__name__).info(
        "Base no-SQLite: el esquema lo gestiona Alembic. Si es una base nueva, "
        "corre 'alembic upgrade head' antes de arrancar."
    )
