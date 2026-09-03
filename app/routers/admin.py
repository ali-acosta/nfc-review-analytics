"""Panel de administración del operador.

Hace desde el navegador lo que hasta ahora solo se podía hacer con
`scripts/new_client.py`: dar de alta un negocio, corregir sus datos, sumarle
placas, regenerarle la contraseña y rotarle el enlace del informe.

Existe porque el operador es una persona, no un servidor: si cada alta o cada
corrección exige abrir una terminal, el trabajo no escala y cada operación es una
oportunidad de equivocarse escribiendo Python contra la base en producción. La
CLI se mantiene, porque sigue siendo la vía cómoda para automatizar y para
arreglar cosas cuando el panel no esté disponible.

Es Jinja2 servido por FastAPI y no Dash, igual que el login de los clientes: son
formularios, no gráficos, y así el panel no depende del montaje WSGI ni relaja la
política de seguridad. Todo el CSS vive en un archivo aparte para que la CSP
estricta siga aplicando aquí.

Seguridad: cada ruta pasa por `_exigir_sesion`. Esto no es el panel de un
cliente, que solo puede dañarse a sí mismo; quien entre aquí ve las quejas
privadas y los enlaces de toda la cartera.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Business, Feedback, Placement, Tap, new_token
from app.services import admin_auth, metrics
from app.services.auth import generate_password, hash_password
from app.services.ratelimit import client_ip, login_limiter

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Mismos avisos que da la CLI al crear un cliente: un enlace de reseñas mal
# copiado se descubre tarde, cuando el cliente reclama que nadie le deja reseñas.
PLACEHOLDER_MARKERS = ("REEMPLAZAR", "PLACE_ID", "ejemplo", "example")
KNOWN_PATTERNS = ("g.page/r/", "search.google.com/local/writereview", "maps.app.goo.gl", "goo.gl/maps")


def _panel_habilitado() -> None:
    """Sin credencial configurada, el panel no existe: 404, no 401.

    Un 401 confirmaría que la ruta está ahí y solo falta la clave. Un 404 no
    dice nada.
    """
    if not admin_auth.esta_habilitado():
        raise HTTPException(status_code=404)


def _exigir_sesion(request: Request) -> None:
    _panel_habilitado()
    if not admin_auth.sesion_valida(request.session):
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})


def _avisos_de_url(url: str) -> list[str]:
    """Revisa el enlace de Google sin bloquear: el operador puede tener razones
    para pegar algo que no reconocemos."""
    if any(m in url for m in PLACEHOLDER_MARKERS):
        return ["Ese link parece un texto de relleno, no un enlace real de Google."]
    if not url.startswith(("http://", "https://")):
        return ["El link debería empezar con https://"]
    if not any(p in url for p in KNOWN_PATTERNS):
        return ["El link no se parece a un enlace de reseñas de Google (algo tipo https://g.page/r/…/review)."]
    return []


def _labels(texto: str) -> list[str]:
    return [t.strip() for t in texto.split(",") if t.strip()]


def _resumen(db: Session, business: Business) -> dict:
    """Lo mínimo para saber, de un vistazo, si un cliente está sano.

    Las cifras se piden a `metrics` y no se calculan aquí: si el panel del
    operador dijera algo distinto de lo que ve el dueño en el suyo, no se sabría
    a cuál creerle.
    """
    placas = db.scalar(
        select(func.count()).select_from(Placement).where(Placement.business_id == business.id)
    )
    pendientes = db.scalar(
        select(func.count())
        .select_from(Feedback)
        .where(Feedback.business_id == business.id, Feedback.resolved_at.is_(None))
    )
    embudo = metrics.funnel(metrics.load_taps(business.id))
    return {
        "business": business,
        "placas": placas or 0,
        "quejas_pendientes": pendientes or 0,
        "visitas": embudo["visits"],
        "conversion": embudo["conversion"],
        "tiene_acceso": bool(business.password_hash),
        "tiene_alertas": bool(business.alert_email or business.telegram_chat_id),
    }


def _base() -> str:
    return settings.base_url.rstrip("/")


# --------------------------------------------------------------------------- #
# Entrada
# --------------------------------------------------------------------------- #


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    _panel_habilitado()
    if admin_auth.sesion_valida(request.session):
        return RedirectResponse("/admin/", status_code=302)
    return templates.TemplateResponse(request, "admin_login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form("")):
    # El campo se declara opcional a propósito. Con Form(...) una petición sin
    # contraseña fallaba la validación y devolvía 422 ANTES de llegar a la
    # comprobación de abajo, lo que delataba que la ruta existe aunque el panel
    # estuviera deshabilitado. Con el panel apagado, cualquier cosa que llegue
    # aquí tiene que responder 404 y no contar nada.
    _panel_habilitado()
    ip = client_ip(request)

    # Se reutiliza el limitador del login de clientes: mismo criterio, y aquí con
    # más razón, porque una sola clave abre la cartera completa.
    if not login_limiter.allow(ip):
        return templates.TemplateResponse(
            request,
            "admin_login.html",
            {"error": "Demasiados intentos. Espera unos minutos."},
            status_code=429,
        )

    if not admin_auth.verificar(password):
        return templates.TemplateResponse(
            request, "admin_login.html", {"error": "Contraseña incorrecta."}, status_code=401
        )

    login_limiter.reset(ip)
    request.session[admin_auth.SESSION_KEY] = "ok"
    return RedirectResponse("/admin/", status_code=302)


@router.post("/logout")
def logout(request: Request):
    request.session.pop(admin_auth.SESSION_KEY, None)
    return RedirectResponse("/admin/login", status_code=302)


# --------------------------------------------------------------------------- #
# Listado y alta
# --------------------------------------------------------------------------- #


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(_exigir_sesion)])
def listado(request: Request, db: Session = Depends(get_db)):
    negocios = db.scalars(select(Business).order_by(Business.name)).all()
    return templates.TemplateResponse(
        request,
        "admin_list.html",
        {"clientes": [_resumen(db, b) for b in negocios], "base": _base()},
    )


@router.get("/nuevo", response_class=HTMLResponse, dependencies=[Depends(_exigir_sesion)])
def nuevo_form(request: Request):
    return templates.TemplateResponse(
        request, "admin_new.html", {"error": None, "avisos": [], "datos": {}}
    )


@router.post("/nuevo", response_class=HTMLResponse, dependencies=[Depends(_exigir_sesion)])
def crear(
    request: Request,
    nombre: str = Form(...),
    google_url: str = Form(...),
    placas: str = Form(...),
    email: str = Form(""),
    telegram: str = Form(""),
    db: Session = Depends(get_db),
):
    datos = {"nombre": nombre, "google_url": google_url, "placas": placas, "email": email, "telegram": telegram}
    labels = _labels(placas)

    if not labels:
        return templates.TemplateResponse(
            request,
            "admin_new.html",
            {"error": "Necesitas al menos una placa.", "avisos": [], "datos": datos},
            status_code=400,
        )

    # La contraseña se genera solo si hay correo: sin correo no hay a quién
    # entregársela ni forma de que el dueño entre.
    password = generate_password() if email.strip() else ""

    business = Business(
        name=nombre.strip(),
        google_review_url=google_url.strip(),
        alert_email=email.strip(),
        login_email=email.strip(),
        telegram_chat_id=telegram.strip(),
        password_hash=hash_password(password) if password else "",
    )
    db.add(business)
    db.flush()
    db.add_all([Placement(business_id=business.id, label=label) for label in labels])
    db.commit()
    db.refresh(business)

    # La clave se muestra UNA vez, en la pantalla siguiente. No se guarda en la
    # sesión ni se pasa por la URL, donde quedaría en el historial del navegador.
    return templates.TemplateResponse(
        request,
        "admin_creado.html",
        {
            "business": business,
            "placements": db.scalars(
                select(Placement).where(Placement.business_id == business.id).order_by(Placement.id)
            ).all(),
            "password": password,
            "avisos": _avisos_de_url(google_url.strip()),
            "base": _base(),
        },
    )


# --------------------------------------------------------------------------- #
# Ficha de un cliente
# --------------------------------------------------------------------------- #


def _cliente_o_404(db: Session, token: str) -> Business:
    business = db.scalar(select(Business).where(Business.dashboard_token == token))
    if business is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return business


def _ficha(request: Request, db: Session, business: Business, **extra):
    placements = db.scalars(
        select(Placement).where(Placement.business_id == business.id).order_by(Placement.id)
    ).all()
    contexto = {
        "business": business,
        "placements": placements,
        "resumen": _resumen(db, business),
        "avisos": _avisos_de_url(business.google_review_url),
        "base": _base(),
        "ok": None,
        "password_nueva": None,
    }
    contexto.update(extra)
    return templates.TemplateResponse(request, "admin_detail.html", contexto)


@router.get("/{token}", response_class=HTMLResponse, dependencies=[Depends(_exigir_sesion)])
def ficha(token: str, request: Request, db: Session = Depends(get_db)):
    return _ficha(request, db, _cliente_o_404(db, token))


@router.post("/{token}/editar", response_class=HTMLResponse, dependencies=[Depends(_exigir_sesion)])
def editar(
    token: str,
    request: Request,
    nombre: str = Form(...),
    google_url: str = Form(...),
    email: str = Form(""),
    telegram: str = Form(""),
    db: Session = Depends(get_db),
):
    business = _cliente_o_404(db, token)

    business.name = nombre.strip()
    business.google_review_url = google_url.strip()
    business.alert_email = email.strip()
    business.telegram_chat_id = telegram.strip()
    # El correo del panel solo se asigna si no había: cambiarlo dejaría al dueño
    # sin poder entrar con la credencial que ya se le entregó.
    if not business.login_email and email.strip():
        business.login_email = email.strip()
    db.commit()
    db.refresh(business)

    return _ficha(request, db, business, ok="Datos actualizados.")


@router.post("/{token}/placas", response_class=HTMLResponse, dependencies=[Depends(_exigir_sesion)])
def agregar_placas(
    token: str,
    request: Request,
    placas: str = Form(...),
    db: Session = Depends(get_db),
):
    business = _cliente_o_404(db, token)
    labels = _labels(placas)

    if not labels:
        return _ficha(request, db, business, ok=None)

    db.add_all([Placement(business_id=business.id, label=label) for label in labels])
    db.commit()

    return _ficha(
        request,
        db,
        business,
        ok=f"{len(labels)} placa(s) agregada(s). Sus códigos ya están listos para grabar.",
    )


@router.post("/{token}/password", response_class=HTMLResponse, dependencies=[Depends(_exigir_sesion)])
def resetear_password(token: str, request: Request, db: Session = Depends(get_db)):
    business = _cliente_o_404(db, token)

    if not business.login_email:
        return _ficha(
            request, db, business, ok="Primero asígnale un correo: sin él no puede entrar al panel."
        )

    password = generate_password()
    business.password_hash = hash_password(password)
    db.commit()
    db.refresh(business)

    return _ficha(request, db, business, password_nueva=password)


@router.post("/{token}/rotar", response_class=HTMLResponse, dependencies=[Depends(_exigir_sesion)])
def rotar(token: str, request: Request, db: Session = Depends(get_db)):
    """Invalida el enlace del informe y emite uno nuevo.

    El enlace del informe no pide contraseña a propósito, porque va por correo al
    dueño. El precio es que un correo reenviado lo deja vivo para siempre, con los
    teléfonos y las quejas de los clientes finales adentro. Esto lo corta.
    """
    business = _cliente_o_404(db, token)
    business.dashboard_token = new_token()
    db.commit()
    db.refresh(business)

    # Redirige al token NUEVO: la URL vieja ya no apunta a nada.
    return RedirectResponse(f"/admin/{business.dashboard_token}?rotado=1", status_code=302)
