from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Feedback, Placement, Tap
from app.services.notify import notify
from app.services.qrcode_gen import generate_qr_for_token
from app.services.ratelimit import client_ip, feedback_limiter, public_limiter
from app.services.tracking import SESSION_COOKIE, SESSION_MAX_AGE, is_bot, new_session_id

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


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
            user_agent=user_agent,
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
        {"business": placement.business, "placement": placement},
    )
    _set_session_cookie(response, session_id)
    return response


@router.get("/r/{token}/go")
def go_to_google(token: str, request: Request, db: Session = Depends(get_db)):
    placement = _get_placement_or_404(db, token)
    session_id, _ = _session_id(request)
    user_agent = request.headers.get("user-agent", "")

    # A click with no preceding visit (direct link, cleared cookies) would push
    # conversion above 100%, so make sure the visit exists first.
    if _debe_contarse(request):
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

    response = templates.TemplateResponse(request, "feedback_thanks.html", {"business": business})
    _set_session_cookie(response, session_id)
    return response


@router.get("/r/{token}/qr.png")
def qr_code(token: str, db: Session = Depends(get_db)):
    _get_placement_or_404(db, token)
    path = generate_qr_for_token(token)
    return FileResponse(path, media_type="image/png")
