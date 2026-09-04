"""Revisa si el sistema está listo para producción, antes de que lo esté un cliente.

Desplegar es donde se acumulan los errores chicos: una variable sin cargar, la
base todavía en SQLite, un cliente con el enlace de Google de relleno. Ninguno se
nota al arrancar, todos se notan cuando un cliente está parado frente a una placa.
Esto los busca de una vez.

    python -m scripts.check_deploy              # revisa el entorno actual
    python -m scripts.check_deploy --clientes   # revisa además cada cliente

Sale con código 1 si hay algún BLOQUEANTE, para poder encadenarlo en un
despliegue automático.

Los tres niveles no son decoración:
  BLOQUEA  el servicio no funciona, o funciona mal de una forma que le cuesta
           dinero o reputación al cliente. No salir a producción así.
  REVISAR  funciona, pero hay algo que conviene mirar antes de cobrarle a alguien.
  BIEN     verificado.
"""

import argparse
import sys

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Business, Placement

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

LINE = "-" * 74

BLOQUEA, REVISAR, BIEN = "BLOQUEA", "REVISAR", "BIEN"

PLACEHOLDERS = ("REEMPLAZAR", "PLACE_ID", "ejemplo", "example", "google.com/maps")
HOSTS_PROVISIONALES = ("localhost", "127.0.0.1", "onrender.com", "testserver", "ngrok")


class Reporte:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def add(self, nivel: str, titulo: str, detalle: str = "") -> None:
        self.items.append((nivel, titulo, detalle))

    def bloqueantes(self) -> int:
        return sum(1 for nivel, _, _ in self.items if nivel == BLOQUEA)

    def imprimir(self, seccion: str) -> None:
        print(f"\n{seccion}")
        print(LINE)
        for nivel, titulo, detalle in self.items:
            marca = {BLOQUEA: "[X]", REVISAR: "[!]", BIEN: "[ok]"}[nivel]
            print(f"  {marca:<4} {titulo}")
            if detalle:
                for linea in detalle.split("\n"):
                    print(f"       {linea}")
        self.items.clear()


# --------------------------------------------------------------------------- #
# Configuración del servidor
# --------------------------------------------------------------------------- #


def revisar_base_url(r: Reporte) -> None:
    base = settings.base_url.rstrip("/")

    if not base.startswith("https://"):
        r.add(
            BLOQUEA,
            f"BASE_URL no usa https: {base}",
            "Es la URL que queda GRABADA en cada chip y PEGADA a cada mesa.\n"
            "Sin https las cookies viajan en claro, y sobre todo: si esta no es\n"
            "la dirección definitiva, cada placa impresa nace muerta.",
        )
        return

    host = base.split("//", 1)[1].split("/")[0]
    if any(m in host for m in HOSTS_PROVISIONALES):
        r.add(
            BLOQUEA,
            f"BASE_URL apunta a un host provisional: {host}",
            "Si se imprime una placa con esta dirección y algún día se cambia de\n"
            "hosting, todas las placas instaladas dejan de funcionar.",
        )
    elif ":" in host:
        r.add(REVISAR, f"BASE_URL lleva un puerto explícito: {host}", "Nadie imprime un puerto en una placa.")
    else:
        r.add(BIEN, f"BASE_URL apunta a un dominio propio con https: {host}")


def revisar_secretos(r: Reporte) -> None:
    if not settings.session_secret:
        r.add(
            BLOQUEA,
            "SESSION_SECRET vacío",
            "Se genera una al arrancar, así que CADA reinicio cierra la sesión de\n"
            "todos tus clientes. Genera una con:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(32))"',
        )
    elif len(settings.session_secret) < 32:
        r.add(REVISAR, "SESSION_SECRET corta", "Conviene que tenga al menos 32 caracteres.")
    else:
        r.add(BIEN, "SESSION_SECRET configurada")

    if not settings.admin_password_hash:
        r.add(
            REVISAR,
            "Panel de administración deshabilitado",
            "Responde 404 y no podrás gestionar clientes desde el navegador.\n"
            "Habilítalo con: python -m scripts.admin_password",
        )
    elif not settings.admin_password_hash.startswith("scrypt$"):
        r.add(
            BLOQUEA,
            "ADMIN_PASSWORD_HASH no parece un hash",
            "Ahí va el HASH, no la contraseña. Genéralo con:\n"
            "  python -m scripts.admin_password",
        )
    else:
        r.add(BIEN, "Panel de administración habilitado, con la clave guardada como hash")


def revisar_base_de_datos(r: Reporte) -> None:
    url = settings.database_url

    if url.startswith("sqlite"):
        r.add(
            BLOQUEA,
            "La base sigue siendo SQLite",
            "En un hosting sin disco persistente, el archivo se borra en cada\n"
            "despliegue: se pierde el historial completo de tus clientes.\n"
            "Crea un Postgres en Neon y apunta DATABASE_URL ahí.",
        )
        return

    r.add(BIEN, f"Base de datos: {url.split(':', 1)[0]}")

    try:
        from alembic.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from alembic.config import Config
        from app.database import engine

        with engine.connect() as conexion:
            actual = MigrationContext.configure(conexion).get_current_revision()
        esperada = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()

        if actual is None:
            r.add(
                BLOQUEA,
                "La base no tiene migraciones aplicadas",
                "Corre 'alembic upgrade head' antes de arrancar.",
            )
        elif actual != esperada:
            r.add(
                BLOQUEA,
                f"La base está en la migración {actual} y el código espera {esperada}",
                "Corre 'alembic upgrade head'.",
            )
        else:
            r.add(BIEN, "Migraciones al día")
    except Exception as exc:
        r.add(REVISAR, "No se pudo verificar el estado de las migraciones", str(exc))


def revisar_alertas(r: Reporte) -> None:
    if settings.smtp_host and settings.smtp_from:
        r.add(BIEN, f"Correo configurado: {settings.smtp_host}")
    else:
        r.add(
            BLOQUEA,
            "SMTP sin configurar",
            "Es el canal por el que llegan las alertas de queja, que es la razón\n"
            "principal por la que un cliente sigue pagando. Sin esto, un cliente\n"
            "enojado escribe y el dueño no se entera nunca.\n"
            "También es por donde el dueño recupera su contraseña: sin SMTP vuelve\n"
            "a depender de que se la regeneres y se la dictes por teléfono.",
        )

    if settings.telegram_bot_token:
        r.add(BIEN, "Telegram configurado")

    if not settings.sentry_dsn:
        r.add(
            REVISAR,
            "Sin monitoreo de errores",
            "Un error en producción solo se descubre si un cliente lo cuenta, y\n"
            "un cliente parado en un mostrador no cuenta nada: se va.",
        )
    else:
        r.add(BIEN, "Monitoreo de errores activo")


# --------------------------------------------------------------------------- #
# Estado de los clientes
# --------------------------------------------------------------------------- #


def revisar_clientes(r: Reporte) -> None:
    with SessionLocal() as db:
        negocios = db.scalars(select(Business).order_by(Business.name)).all()

        if not negocios:
            r.add(REVISAR, "No hay clientes cargados todavía")
            return

        for b in negocios:
            placas = db.scalars(select(Placement).where(Placement.business_id == b.id)).all()
            problemas = []

            if any(m in b.google_review_url for m in PLACEHOLDERS):
                problemas.append(
                    (BLOQUEA, "su enlace de Google es provisional: sus clientes no llegan a dejar reseña")
                )
            elif not b.google_review_url.startswith("https://"):
                problemas.append((REVISAR, "su enlace de Google no empieza con https"))

            if not placas:
                problemas.append((BLOQUEA, "no tiene ninguna placa"))
            if not b.alert_email and not b.telegram_chat_id:
                problemas.append((BLOQUEA, "sin canal de aviso: no se enterará de ninguna queja"))
            if not b.password_hash:
                problemas.append((REVISAR, "sin credenciales: no puede entrar a ver sus números"))

            if problemas:
                nivel = BLOQUEA if any(n == BLOQUEA for n, _ in problemas) else REVISAR
                r.add(nivel, f"{b.name}", "\n".join(f"· {t}" for _, t in problemas))
            else:
                r.add(BIEN, f"{b.name} ({len(placas)} placas)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Revisa si todo está listo para producción.")
    parser.add_argument("--clientes", action="store_true", help="Revisa además el estado de cada cliente.")
    args = parser.parse_args()

    print(f"\n{LINE}\n  REVISIÓN PREVIA AL DESPLIEGUE\n{LINE}")

    reporte = Reporte()

    revisar_base_url(reporte)
    revisar_secretos(reporte)
    bloqueantes = reporte.bloqueantes()
    reporte.imprimir("URL Y SECRETOS")

    revisar_base_de_datos(reporte)
    bloqueantes += reporte.bloqueantes()
    reporte.imprimir("BASE DE DATOS")

    revisar_alertas(reporte)
    bloqueantes += reporte.bloqueantes()
    reporte.imprimir("AVISOS Y MONITOREO")

    if args.clientes:
        revisar_clientes(reporte)
        bloqueantes += reporte.bloqueantes()
        reporte.imprimir("CLIENTES")

    print(f"\n{LINE}")
    if bloqueantes:
        print(f"  {bloqueantes} problema(s) BLOQUEANTE(S). No salgas a producción así.\n")
        sys.exit(1)
    print("  Sin bloqueantes. Revisa igual los [!] antes de cobrarle a alguien.\n")


if __name__ == "__main__":
    main()
