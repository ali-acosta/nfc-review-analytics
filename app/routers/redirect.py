import hashlib
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Feedback, Placement, Tap
from app.services.notify import notify
from app.services.qrcode_gen import qr_png_bytes
from app.services.ratelimit import client_ip, feedback_limiter, public_limiter
from app.services.tracking import SESSION_COOKIE, SESSION_MAX_AGE, is_bot, new_session_id

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Los largos se leen del modelo y no se escriben a mano: si algún día cambia la
# columna, el recorte la sigue sola.
#
# Recortar no es cosmético. SQLite ignora el largo declarado y Postgres lo aplica:
# sin esto, un cliente que escriba un texto largo —o un teléfono con un user-agent
# gigante— provoca un error 500 en producción, parado en el mostrador, después de
# haberse tomado el trabajo de escribir. Es la misma trampa que ya mordió con las
# fechas: desarrollo permisivo, producción estricta.
MAX_CONTACTO = Feedback.__table__.c.contact.type.length
MAX_MENSAJE = Feedback.__table__.c.message.type.length
MAX_USER_AGENT = Tap.__table__.c.user_agent.type.length


def _get_placement_or_404(db: Session, token: str) -> Placement:
    placement = db.scalar(select(Placement).where(Placement.token == token))
    if placement is None:
        raise HTTPException(status_code=404, detail="Código no encontrado")
    return placement


def _already_logged(db: Session, session_id: str, placement_id: int, outcome: str) -> bool:
    """True if this session already produced this event on this placement.

    Without this a page refresh counts as a new visit and a double-click counts
    as two conversions.
    """
    return db.scalar(
        select(
            exists().where(
                Tap.session_id == session_id,
                Tap.placement_id == placement_id,
                Tap.outcome == outcome,
            )
        )
    )


def _log(db: Session, placement: Placement, session_id: str, user_agent: str, outcome: str) -> None:
    if _already_logged(db, session_id, placement.id, outcome):
        return
    db.add(
        Tap(
            business_id=placement.business_id,
            placement_id=placement.id,
            session_id=session_id,
            user_agent=user_agent[:MAX_USER_AGENT],
            is_bot=is_bot(user_agent),
            outcome=outcome,
        )
    )
    db.commit()


def _session_id(request: Request) -> tuple[str, bool]:
    """Returns (session_id, is_new)."""
    existing = request.cookies.get(SESSION_COOKIE)
    return (existing, False) if existing else (new_session_id(), True)


def _debe_contarse(request: Request) -> bool:
    """Si la IP se pasó del límite, la visita no se registra.

    Deliberadamente NO se responde 429: quien esté del otro lado puede ser un
    cliente real saliendo por el WiFi del local, detrás de la misma IP que
    decenas de personas. Se degrada la métrica, nunca la experiencia de quien
    vino a dejar una reseña.
    """
    return public_limiter.allow(client_ip(request))


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        # En producción (BASE_URL https) la cookie no debe viajar en claro. En
        # desarrollo sobre http tiene que quedar en False o el navegador la
        # descarta y cada visita parecería un visitante nuevo.
        secure=settings.base_url.startswith("https://"),
    )


@router.get("/r/{token}", response_class=HTMLResponse)
def landing(token: str, request: Request, db: Session = Depends(get_db)):
    placement = _get_placement_or_404(db, token)
    session_id, _ = _session_id(request)
    user_agent = request.headers.get("user-agent", "")

    if _debe_contarse(request):
        _log(db, placement, session_id, user_agent, "landed")

    response = templates.TemplateResponse(
        request,
        "landing.html",
        {
            "business": placement.business,
            "placement": placement,
            # Se pasa como bandera y no el contenido: el logo lo sirve su
            # propia ruta, cacheable, en vez de engordar cada carga de la
            # página con la imagen incrustada.
            "tiene_logo": placement.business.logo_data is not None,
        },
    )
    _set_session_cookie(response, session_id)
    return response


@router.get("/r/{token}/go")
def go_to_google(token: str, request: Request, db: Session = Depends(get_db)):
    placement = _get_placement_or_404(db, token)
    session_id, _ = _session_id(request)
    user_agent = request.headers.get("user-agent", "")

    # Una sesión que ya tiene su visita registrada es un navegador real siguiendo
    # el flujo, así que su conversión se cuenta aunque la IP esté en el límite.
    #
    # Sin esta excepción, la degradación no es neutra: en un almuerzo lleno, donde
    # todos comparten la IP del local, la visita se cuenta y el click siguiente se
    # pierde, así que el límite solo puede BAJAR la conversión del cliente, y
    # justo en su mejor momento. Un script que borra cookies nunca tiene una
    # visita previa asociada a su sesión nueva, así que sigue topando con el tope.
    ya_visito = _already_logged(db, session_id, placement.id, "landed")

    # A click with no preceding visit (direct link, cleared cookies) would push
    # conversion above 100%, so make sure the visit exists first.
    if ya_visito or _debe_contarse(request):
        _log(db, placement, session_id, user_agent, "landed")
        _log(db, placement, session_id, user_agent, "went_to_google")

    response = RedirectResponse(placement.business.google_review_url, status_code=302)
    _set_session_cookie(response, session_id)
    return response


@router.post("/r/{token}/feedback", response_class=HTMLResponse)
async def submit_feedback(
    token: str,
    request: Request,
    background: BackgroundTasks,
    rating: int | None = Form(None),
    contact: str = Form(""),
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    placement = _get_placement_or_404(db, token)
    session_id, _ = _session_id(request)
    user_agent = request.headers.get("user-agent", "")
    business = placement.business

    # Se recorta a lo que la columna admite y se descarta una calificación fuera
    # de rango: el formulario ya lo limita, pero un POST a mano no pasa por él.
    contact = contact.strip()[:MAX_CONTACTO]
    message = message.strip()[:MAX_MENSAJE]
    if rating is not None and not 1 <= rating <= 5:
        rating = None

    # Cada comentario despierta el teléfono del dueño. Pasado el límite se
    # responde igual con la página de gracias —quien abusa no obtiene señal de
    # que fue frenado— pero no se guarda ni se avisa.
    if feedback_limiter.allow(client_ip(request)):
        db.add(
            Feedback(
                business_id=business.id,
                placement_id=placement.id,
                rating=rating,
                contact=contact,
                message=message,
            )
        )
        db.commit()
        _log(db, placement, session_id, user_agent, "left_private_feedback")

        stars = f"{rating}★" if rating else "sin calificación"
        # En segundo plano: el cliente está parado en el local, no puede esperar
        # a que respondan Telegram o el correo para ver su confirmación.
        background.add_task(
            notify,
            business,
            f"Nuevo comentario privado — {business.name}",
            f"Soporte: {placement.label} ({stars})\n"
            f"Contacto: {contact or 'no proporcionado'}\n"
            f"Mensaje: {message or '(sin mensaje)'}",
        )

    # El placement viaja a la plantilla para que su botón de Google pase por /go
    # y la conversión quede contada: quien tuvo un problema, lo dijo y AUN ASÍ
    # fue a dejar su reseña es justamente el caso que más vale la pena medir.
    response = templates.TemplateResponse(
        request,
        "feedback_thanks.html",
        {
            "business": business,
            "placement": placement,
            "tiene_logo": business.logo_data is not None,
        },
    )
    _set_session_cookie(response, session_id)
    return response


@router.get("/r/{token}/qr.png")
def qr_code(token: str, db: Session = Depends(get_db)):
    _get_placement_or_404(db, token)
    return Response(content=qr_png_bytes(token), media_type="image/png")


@router.get("/r/{token}/logo.png")
def logo(token: str, request: Request, db: Session = Depends(get_db)):
    """Sirve el logo del negocio de esta placa.

    Se pide por el token de la placa y no por el del negocio: el token de placa
    ya es público (está pegado en la mesa), mientras que el del negocio abre su
    informe. Un `<img>` filtra su URL en cualquier lado, así que no puede llevar
    el token bueno.

    Lleva ETag porque un logo cambia casi nunca y esto se pide en cada visita: sin
    él, cada cliente que toca la placa vuelve a descargarlo. Con ETag el navegador
    pregunta y recibe un 304 vacío, y si el dueño lo cambia el hash cambia y se
    actualiza solo.
    """
    placement = _get_placement_or_404(db, token)
    datos = placement.business.logo_data
    if not datos:
        raise HTTPException(status_code=404, detail="Este negocio no tiene logo")

    etag = '"' + hashlib.sha256(datos).hexdigest()[:32] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)

    return Response(
        content=datos,
        media_type="image/png",
        headers={"ETag": etag, "Cache-Control": "public, max-age=3600"},
    )
