"""Entrada y salida del panel del comercio."""

import secrets
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Business
from app.services import enlaces
from app.services.auth import SESSION_KEY, hash_password, verify_password
from app.services.email import send_email
from app.services.ratelimit import client_ip, login_limiter, recovery_limiter

router = APIRouter(prefix="/panel")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Hash señuelo, calculado una vez al importar. Sirve para que un correo que no
# existe cueste lo mismo que uno que sí: sin esto, el `or` corta antes de llegar
# a scrypt y la respuesta vuelve decenas de milisegundos más rápido, lo que
# permite averiguar qué comercios son clientes con solo cronometrar. El mensaje
# único de error no sirve de nada si el reloj lo delata.
_HASH_SENUELO = hash_password(secrets.token_urlsafe(16))


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.session.get(SESSION_KEY):
        return RedirectResponse("/dashboard/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None, "email": ""})


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = client_ip(request)

    # Aquí sí se bloquea de verdad: a diferencia de la landing, no hay clientes
    # legítimos compartiendo IP a los que proteger, y lo que se está probando a
    # ciegas es la contraseña del panel de un comercio.
    if not login_limiter.allow(ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.",
                "email": email,
            },
            status_code=429,
        )

    email = email.strip().lower()
    business = db.scalar(select(Business).where(func.lower(Business.login_email) == email))

    # Se verifica siempre, contra el hash real o contra el señuelo, para que el
    # tiempo de respuesta no distinga un correo que existe de uno que no. Un
    # negocio sin contraseña asignada tampoco puede entrar, pero paga el mismo
    # costo de cómputo que el resto.
    hash_a_probar = business.password_hash if (business and business.password_hash) else _HASH_SENUELO
    clave_correcta = verify_password(password, hash_a_probar)

    # Un solo mensaje para "no existe" y "contraseña incorrecta": distinguirlos
    # permitiría averiguar qué comercios son clientes.
    if business is None or not business.password_hash or not clave_correcta:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Correo o contraseña incorrectos.", "email": email},
            status_code=401,
        )

    # Entró bien: la IP deja de arrastrar los intentos fallidos previos, para no
    # castigar a quien simplemente se equivocó un par de veces.
    login_limiter.reset(ip)
    request.session[SESSION_KEY] = business.id
    return RedirectResponse("/dashboard/", status_code=302)


@router.post("/logout")
def logout(request: Request):
    """Cerrar sesión es POST, no GET.

    Con GET, cualquier página ajena podía sacar al dueño de su panel con un
    `<img src="…/panel/logout">`. No es un robo de cuenta, pero es un servicio
    que se cae solo mientras el dueño no entiende por qué.
    """
    request.session.clear()
    return RedirectResponse("/panel/login", status_code=302)


@router.get("/logout", response_class=HTMLResponse)
def logout_confirmar(request: Request):
    """Quien llegue por GET —un enlace viejo, un marcador— recibe el botón.

    Alternativa era un 405, que a quien tecleó la dirección le parece un error
    del sistema.
    """
    if not request.session.get(SESSION_KEY):
        return RedirectResponse("/panel/login", status_code=302)
    return templates.TemplateResponse(request, "logout.html", {})


MIN_LARGO = 8


def _sesion_o_login(request: Request, db: Session) -> Business | None:
    """El middleware solo cubre /dashboard; estas rutas se protegen aquí."""
    business_id = request.session.get(SESSION_KEY)
    return db.get(Business, business_id) if business_id else None


@router.get("/password", response_class=HTMLResponse)
def password_form(request: Request, db: Session = Depends(get_db)):
    if _sesion_o_login(request, db) is None:
        return RedirectResponse("/panel/login", status_code=302)
    return templates.TemplateResponse(request, "password.html", {"error": None, "ok": False})


@router.post("/password", response_class=HTMLResponse)
def cambiar_password(
    request: Request,
    actual: str = Form(...),
    nueva: str = Form(...),
    repetir: str = Form(...),
    db: Session = Depends(get_db),
):
    business = _sesion_o_login(request, db)
    if business is None:
        return RedirectResponse("/panel/login", status_code=302)

    def error(mensaje: str):
        return templates.TemplateResponse(
            request, "password.html", {"error": mensaje, "ok": False}, status_code=400
        )

    # Se pide la actual aunque ya haya sesión: si alguien deja el panel abierto
    # en el mostrador, no debería poder quedarse con la cuenta.
    if not verify_password(actual, business.password_hash):
        return error("La contraseña actual no es correcta.")
    if nueva != repetir:
        return error("Las dos contraseñas nuevas no coinciden.")
    if len(nueva) < MIN_LARGO:
        return error(f"La contraseña nueva debe tener al menos {MIN_LARGO} caracteres.")
    if nueva == actual:
        return error("La contraseña nueva tiene que ser distinta de la actual.")

    business.password_hash = hash_password(nueva)
    db.commit()

    return templates.TemplateResponse(request, "password.html", {"error": None, "ok": True})


# --------------------------------------------------------------------------- #
# Recuperación de contraseña
#
# Antes, un dueño que olvidaba su clave dependía de que el operador corriera
# `--reset-password` y se la dictara por teléfono. Con diez clientes eso es una
# llamada por semana, y una contraseña dictada en voz alta que además queda
# escrita en algún WhatsApp.
#
# El enlace se firma con `itsdangerous`, vale una hora y muere al usarse: la
# firma incluye el hash actual de la contraseña, así que en cuanto cambia, el
# enlace deja de validar. Sin tabla nueva y sin migración.
# --------------------------------------------------------------------------- #

# Misma respuesta exista o no la cuenta. Si dijera "ese correo no está
# registrado", el formulario serviría para averiguar qué comercios son clientes,
# que es justo lo que el mensaje único del login evita.
AVISO_ENVIADO = (
    "Si ese correo corresponde a una cuenta, te acabamos de enviar un enlace para "
    "crear una contraseña nueva. Revisa también la carpeta de spam."
)


def _hay_correo_saliente() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


@router.get("/recuperar", response_class=HTMLResponse)
def recuperar_form(request: Request):
    return templates.TemplateResponse(
        request,
        "recuperar.html",
        {"error": None, "aviso": None, "hay_correo": _hay_correo_saliente()},
    )


@router.post("/recuperar", response_class=HTMLResponse)
def recuperar(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    def pagina(error: str | None = None, aviso: str | None = None, status: int = 200):
        return templates.TemplateResponse(
            request,
            "recuperar.html",
            {"error": error, "aviso": aviso, "hay_correo": _hay_correo_saliente()},
            status_code=status,
        )

    if not _hay_correo_saliente():
        # Decirlo es más honesto que mostrar "te mandamos un correo" y dejar al
        # dueño esperando algo que nunca va a llegar. No revela nada de nadie.
        return pagina(
            error="La recuperación por correo no está disponible en este momento. "
            "Escríbele a quien te entregó el acceso y te generará una clave nueva.",
            status=503,
        )

    if not recovery_limiter.allow(client_ip(request)):
        return pagina(
            error="Demasiados intentos. Espera unos minutos e inténtalo de nuevo.",
            status=429,
        )

    email = email.strip().lower()
    business = db.scalar(select(Business).where(func.lower(Business.login_email) == email))

    # El envío va en segundo plano: además de no hacer esperar al dueño, hace que
    # la respuesta tarde lo mismo exista o no la cuenta. Un envío que se demora
    # solo cuando el correo es real delataría lo mismo que el texto no dice.
    if business is not None and business.login_email:
        enlace = f"{settings.base_url.rstrip('/')}/panel/nueva-clave?firma=" + enlaces.firmar_clave(
            business.id, business.password_hash
        )
        background.add_task(
            send_email,
            business.login_email,
            "Crea una contraseña nueva para tu panel",
            f"Hola,\n\nPediste crear una contraseña nueva para el panel de {business.name}.\n\n"
            f"Entra aquí y elígela:\n{enlace}\n\n"
            "El enlace vale una hora y sirve una sola vez.\n\n"
            "Si no fuiste tú, ignora este correo: tu contraseña actual sigue funcionando "
            "y nadie puede entrar con este enlace sin abrir tu casilla.\n",
        )

    return pagina(aviso=AVISO_ENVIADO)


def _negocio_de_la_firma(db: Session, firma: str | None) -> Business | None:
    """El negocio del enlace, solo si la firma vale y la clave no cambió."""
    datos = enlaces.datos_de_clave(firma)
    if datos is None:
        return None
    business_id, hash_firmado = datos
    business = db.get(Business, business_id)
    if business is None or business.password_hash != hash_firmado:
        return None
    return business


@router.get("/nueva-clave", response_class=HTMLResponse)
def nueva_clave_form(request: Request, firma: str = "", db: Session = Depends(get_db)):
    if _negocio_de_la_firma(db, firma) is None:
        return templates.TemplateResponse(request, "enlace_vencido.html", {}, status_code=403)
    return templates.TemplateResponse(
        request, "nueva_clave.html", {"error": None, "firma": firma}
    )


@router.post("/nueva-clave", response_class=HTMLResponse)
def nueva_clave(
    request: Request,
    firma: str = Form(""),
    nueva: str = Form(...),
    repetir: str = Form(...),
    db: Session = Depends(get_db),
):
    business = _negocio_de_la_firma(db, firma)
    if business is None:
        return templates.TemplateResponse(request, "enlace_vencido.html", {}, status_code=403)

    def error(mensaje: str):
        return templates.TemplateResponse(
            request, "nueva_clave.html", {"error": mensaje, "firma": firma}, status_code=400
        )

    if nueva != repetir:
        return error("Las dos contraseñas no coinciden.")
    if len(nueva) < MIN_LARGO:
        return error(f"La contraseña debe tener al menos {MIN_LARGO} caracteres.")

    business.password_hash = hash_password(nueva)
    db.commit()

    # Se entra en el acto: quien acaba de demostrar que controla la casilla del
    # dueño y eligió la clave no gana nada teniendo que escribirla otra vez.
    request.session[SESSION_KEY] = business.id
    login_limiter.reset(client_ip(request))
    return RedirectResponse("/dashboard/", status_code=302)
