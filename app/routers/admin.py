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

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Business, Feedback, Placement, Tap, new_token
from app.services import admin_auth, logo as logo_service, metrics
from app.services.auth import generate_password, hash_password
from app.services.notify import notify
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


async def _leer_logo(archivo: UploadFile | None) -> tuple[bytes | None, str]:
    """Procesa el logo subido. Devuelve (datos, aviso).

    Nunca lanza: un logo mal subido no puede impedir que se dé de alta a un
    cliente ni que se guarden sus otros datos. Se avisa y se sigue.
    """
    if archivo is None or not archivo.filename:
        return None, ""
    try:
        return logo_service.procesar(await archivo.read()), ""
    except logo_service.LogoInvalido as exc:
        return None, f"No se guardó el logo: {exc}"


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

    # Cuándo se usó por última vez una placa de este cliente. Es el dato que
    # delata una placa despegada, un chip reescrito o un local que dejó de
    # ponerla a la vista: el cliente sigue pagando y no está pasando nada. Sin
    # esto, el operador se entera cuando el cliente se va.
    ultimo = db.scalar(
        select(func.max(Tap.created_at)).where(Tap.business_id == business.id, Tap.is_bot.is_(False))
    )
    dias_sin_actividad = None
    if ultimo is not None:
        if ultimo.tzinfo is None:
            ultimo = ultimo.replace(tzinfo=timezone.utc)
        dias_sin_actividad = (datetime.now(timezone.utc) - ultimo).days

    return {
        "business": business,
        "placas": placas or 0,
        "quejas_pendientes": pendientes or 0,
        "visitas": embudo["visits"],
        "conversion": embudo["conversion"],
        "tiene_acceso": bool(business.password_hash),
        "tiene_alertas": bool(business.alert_email or business.telegram_chat_id),
        "dias_sin_actividad": dias_sin_actividad,
        "sin_estrenar": ultimo is None,
    }


def _nombre_archivo(nombre: str) -> str:
    """Nombre de archivo seguro para la cabecera Content-Disposition.

    Las cabeceras HTTP son ASCII: un nombre con tilde o ñ llega al navegador
    convertido en basura y el archivo se descarga ilegible. Se translitera lo
    que se pueda y se descarta el resto.
    """
    import unicodedata

    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode("ascii")
    limpio = "".join(c if c.isalnum() or c in "-_" else "-" for c in plano.lower()).strip("-")
    return f"placas-{limpio or 'cliente'}.html"


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
async def crear(
    request: Request,
    nombre: str = Form(...),
    google_url: str = Form(...),
    placas: str = Form(...),
    email: str = Form(""),
    telegram: str = Form(""),
    mensaje: str = Form(""),
    logo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    datos = {"nombre": nombre, "google_url": google_url, "placas": placas,
             "email": email, "telegram": telegram, "mensaje": mensaje}
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
    logo_data, aviso_logo = await _leer_logo(logo)

    business = Business(
        name=nombre.strip(),
        google_review_url=google_url.strip(),
        alert_email=email.strip(),
        login_email=email.strip(),
        telegram_chat_id=telegram.strip(),
        password_hash=hash_password(password) if password else "",
        logo_data=logo_data,
        welcome_message=mensaje.strip()[:300],
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
            "avisos": _avisos_de_url(google_url.strip()) + ([aviso_logo] if aviso_logo else []),
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
        "logo": logo_service.descripcion(business.logo_data),
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
async def editar(
    token: str,
    request: Request,
    nombre: str = Form(...),
    google_url: str = Form(...),
    email: str = Form(""),
    telegram: str = Form(""),
    mensaje: str = Form(""),
    logo: UploadFile | None = File(None),
    quitar_logo: str = Form(""),
    db: Session = Depends(get_db),
):
    business = _cliente_o_404(db, token)

    business.name = nombre.strip()
    business.google_review_url = google_url.strip()
    business.alert_email = email.strip()
    business.telegram_chat_id = telegram.strip()
    business.welcome_message = mensaje.strip()[:300]

    # Un logo nuevo reemplaza al anterior; no subir nada deja el que había. Sin
    # esto, editar el correo borraría el logo sin que nadie lo pidiera.
    logo_data, aviso_logo = await _leer_logo(logo)
    if logo_data is not None:
        business.logo_data = logo_data
    elif quitar_logo:
        business.logo_data = None
    # El correo del panel solo se asigna si no había: cambiarlo dejaría al dueño
    # sin poder entrar con la credencial que ya se le entregó.
    if not business.login_email and email.strip():
        business.login_email = email.strip()
    db.commit()
    db.refresh(business)

    return _ficha(request, db, business, ok=aviso_logo or "Datos actualizados.")


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


@router.get("/{token}/placas.html", dependencies=[Depends(_exigir_sesion)])
def hoja_de_placas(token: str, descargar: int = 0, db: Session = Depends(get_db)):
    """La hoja que se le manda a quien fabrica las placas.

    Se genera aquí y no solo por CLI porque es el paso siguiente natural después
    de dar de alta un cliente: se crean sus placas y de inmediato hay que mandar
    a fabricarlas. Los QR van embebidos, así que el archivo descargado funciona
    solo, sin depender de que el servidor esté encendido cuando el proveedor lo
    abra.
    """
    from scripts.qr_sheet import construir

    business = _cliente_o_404(db, token)
    placements = db.scalars(
        select(Placement).where(Placement.business_id == business.id).order_by(Placement.id)
    ).all()
    if not placements:
        raise HTTPException(status_code=404, detail="Este cliente no tiene placas")

    html = construir(business, placements)

    if not descargar:
        return HTMLResponse(html)

    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_nombre_archivo(business.name)}"'},
    )


@router.post("/{token}/probar-alerta", response_class=HTMLResponse, dependencies=[Depends(_exigir_sesion)])
async def probar_alerta(token: str, request: Request, db: Session = Depends(get_db)):
    """Manda un aviso de prueba por los canales configurados del cliente.

    Sin esto, que el correo esté mal escrito se descubre el día que un cliente
    real deja una queja y el dueño no se entera: justo la alerta que sostiene la
    suscripción, perdida en silencio. Vale más comprobarlo el día del alta.
    """
    business = _cliente_o_404(db, token)

    if not business.alert_email and not business.telegram_chat_id:
        return _ficha(
            request, db, business,
            ok="Este cliente no tiene ningún canal configurado, así que no hay a dónde avisar.",
        )

    entregado = await notify(
        business,
        f"Prueba de alertas — {business.name}",
        "Este es un mensaje de prueba enviado desde el panel de administración.\n\n"
        "Si lo estás leyendo, las alertas de queja van a llegar bien a este canal.\n"
        "No hay que hacer nada.",
    )

    if entregado:
        destino = business.alert_email or f"Telegram {business.telegram_chat_id}"
        return _ficha(request, db, business, ok=f"Aviso de prueba enviado a {destino}.")

    return _ficha(
        request, db, business,
        ok="No se pudo entregar por ningún canal. Revisa el correo del cliente y la "
           "configuración SMTP del servidor.",
    )


@router.post("/{token}/eliminar", dependencies=[Depends(_exigir_sesion)])
def eliminar(
    token: str,
    request: Request,
    confirmacion: str = Form(""),
    db: Session = Depends(get_db),
):
    """Borra un cliente y todo su historial.

    Pide escribir el nombre exacto porque no hay vuelta atrás: se van con él las
    visitas y las quejas, que son irreemplazables. Un cliente que se va merece
    que le exporten sus datos antes (scripts/export_data.py), no que se borren de
    un clic mal dado.
    """
    business = _cliente_o_404(db, token)

    if confirmacion.strip() != business.name:
        return _ficha(
            request, db, business,
            ok="Para eliminar, escribe el nombre del negocio EXACTAMENTE como aparece arriba.",
        )

    # Orden hijo → padre: las claves foráneas no admiten otro.
    db.execute(delete(Tap).where(Tap.business_id == business.id))
    db.execute(delete(Feedback).where(Feedback.business_id == business.id))
    db.execute(delete(Placement).where(Placement.business_id == business.id))
    db.delete(business)
    db.commit()

    return RedirectResponse("/admin/", status_code=302)
