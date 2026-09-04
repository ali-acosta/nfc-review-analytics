"""Entorno de Alembic.

Toma la URL de la base desde la configuración de la aplicación en vez del .ini,
para que migraciones y app no puedan apuntar a bases distintas.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base
from app import models  # noqa: F401  (registra las tablas en Base.metadata)

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Renderiza los tipos propios como el tipo real de la base.

    `UtcDateTime` es un TypeDecorator: en la base no es más que un timestamp, y
    toda su lógica es del lado de Python. Sin esto, el autogenerado escribe
    `app.models.UtcDateTime()` en la migración sin importar el módulo, y el
    upgrade revienta con NameError. Además conviene conceptualmente: una
    migración describe el esquema, no los tipos de la aplicación.
    """
    if type_ == "type" and obj.__class__.__name__ == "UtcDateTime":
        return "sa.DateTime(timezone=True)"
    return False  # el resto lo renderiza Alembic como siempre


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        render_item=render_item,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite no soporta ALTER TABLE completo: sin esto, cualquier cambio de
        # columna futuro fallaría en desarrollo.
        render_as_batch=settings.database_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=render_item,
            render_as_batch=settings.database_url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
