"""Entrada y salida del panel del comercio."""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Business
from app.services.auth import SESSION_KEY, hash_password, verify_password
from app.services.ratelimit import client_ip, login_limiter

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


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/panel/login", status_code=302)


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
