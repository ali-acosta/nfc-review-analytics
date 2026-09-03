import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.dashboard.dash_app import create_dash_app
from app.database import SessionLocal, init_db
from app.logging_config import configure_logging
from app.middleware import DashboardAuthMiddleware, SecurityHeadersMiddleware
from app.routers import admin, auth, redirect, reports

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _configurar_sentry(log: logging.Logger) -> None:
    """Enciende el monitoreo de errores si hay DSN. Nunca tumba el arranque.

    Que falte la librería o que el DSN esté mal escrito no puede impedir que la
    app levante: el monitoreo es una comodidad del operador, no una parte del
    flujo que le da una reseña a un cliente.
    """
    if not settings.sentry_dsn:
        log.info("SENTRY_DSN vacío: monitoreo de errores desactivado.")
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0,
            # Los comentarios privados de los clientes finales no viajan a un
            # tercero: son datos personales de gente que no es cliente nuestro.
            send_default_pii=False,
        )
        log.info("Monitoreo de errores activo.")
    except Exception as exc:
        log.warning("No se pudo activar el monitoreo de errores: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    log = logging.getLogger(__name__)

    _configurar_sentry(log)
    init_db()

    if not settings.session_secret:
        log.warning(
            "SESSION_SECRET vacío: se generó una clave temporal. En producción hay que fijarla "
            "o cada reinicio cerrará la sesión de todos los clientes."
        )
    if settings.base_url.startswith("http://") and "localhost" not in settings.base_url:
        log.warning("BASE_URL no usa https: las cookies de sesión viajarán sin cifrar.")
    if not settings.admin_password_hash:
        log.info(
            "ADMIN_PASSWORD_HASH vacío: el panel de administración responde 404. "
            "Genera la clave con 'python -m scripts.admin_password'."
        )

    log.info("Arrancando · zona horaria %s · base %s", settings.timezone, _motor_de_base())
    yield
    log.info("Apagando")


def _motor_de_base() -> str:
    return settings.database_url.split(":", 1)[0]


app = FastAPI(title="NFC Review & Analytics", lifespan=lifespan)

# El orden importa: add_middleware apila hacia afuera, así que SessionMiddleware
# —agregado después— envuelve al de autenticación y corre primero, dejando
# scope["session"] disponible para él.
app.add_middleware(DashboardAuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or secrets.token_urlsafe(32),
    session_cookie="nfc_panel",
    https_only=settings.base_url.startswith("https://"),
    same_site="lax",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(redirect.router)
app.include_router(reports.router)
app.include_router(auth.router)
app.include_router(admin.router)

dash_app = create_dash_app()
app.mount("/dashboard", WSGIMiddleware(dash_app.server))


@app.get("/health", response_class=PlainTextResponse)
def health():
    """Chequeo de salud para el hosting. No toca la base a propósito: si la
    base parpadea, no queremos que el hosting reinicie un proceso que está
    perfectamente vivo."""
    return "ok"


@app.get("/health/ready", response_class=PlainTextResponse)
def ready():
    """Chequeo profundo, para revisar a mano si el servicio está realmente
    operativo. Aquí sí se toca la base: un proceso vivo que no puede consultar
    no sirve de nada, y sin esto ese fallo pasa inadvertido."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:
        logging.getLogger(__name__).error("Chequeo de disponibilidad falló: %s", exc)
        return PlainTextResponse("base de datos inaccesible", status_code=503)
    return "listo"


@app.get("/", response_class=PlainTextResponse)
def root():
    return (
        "NFC Review & Analytics.\n"
        "Corre 'python -m scripts.seed_demo_business' para obtener los links "
        "de los soportes de demo y del panel."
    )
