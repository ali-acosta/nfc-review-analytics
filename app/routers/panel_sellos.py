"""Lo que ve el comercio de su programa de sellos: configurarlo y la pantalla de la caja.

Jinja2 sobre FastAPI y no Dash, por la misma razón que el panel del operador:
esto son formularios y una pantalla fija, no gráficos. Además la pantalla de la
caja tiene que poder quedarse abierta todo el día en el computador del mostrador
sin depender de que Dash reconstruya su layout.

Va fuera de `/dashboard` porque ese path es un mount WSGI y se traga todo lo que
cuelgue debajo.
"""

import base64
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Business, LoyaltyProgram, Placement
from app.services import fidelizacion
from app.services.auth import SESSION_KEY
from app.services.qrcode_gen import qr_png_bytes_for_url

router = APIRouter(prefix="/panel")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Etiqueta de la placa que se crea al activar el programa. Las reseñas que
# salgan del flujo de sellos se atribuyen ahí, en vez de ensuciar la de una mesa.
ETIQUETA_PLACA_CAJA = "Caja (fidelización)"

MAX_SELLOS = 20


def _sesion(request: Request, db: Session) -> Business | None:
    business_id = request.session.get(SESSION_KEY)
    return db.get(Business, business_id) if business_id else None


def _programa_de(db: Session, business_id: int) -> LoyaltyProgram | None:
    return db.scalar(select(LoyaltyProgram).where(LoyaltyProgram.business_id == business_id))


def _url_sello(programa: LoyaltyProgram) -> str:
    base = settings.base_url.rstrip("/")
    return f"{base}/sello/{programa.token}/{fidelizacion.codigo_actual(programa.secret)}"


@router.get("/fidelizacion", response_class=HTMLResponse)
def configuracion(request: Request, db: Session = Depends(get_db)):
    business = _sesion(request, db)
    if business is None:
        return RedirectResponse("/panel/login", status_code=302)

    programa = _programa_de(db, business.id)
    return templates.TemplateResponse(
        request,
        "fidelizacion.html",
        {
            "business": business,
            "programa": programa,
            "resumen": fidelizacion.resumen(db, business.id) if programa else None,
            "max_sellos": MAX_SELLOS,
            "error": None,
            "ok": False,
        },
    )


@router.post("/fidelizacion", response_class=HTMLResponse)
def guardar_configuracion(
    request: Request,
    sellos: int = Form(5),
    premio: str = Form(""),
    activo: str = Form(""),
    db: Session = Depends(get_db),
):
    business = _sesion(request, db)
    if business is None:
        return RedirectResponse("/panel/login", status_code=302)

    programa = _programa_de(db, business.id)
    premio = premio.strip()[:200]

    def pagina(error: str | None = None, ok: bool = False, status: int = 200):
        return templates.TemplateResponse(
            request,
            "fidelizacion.html",
            {
                "business": business,
                "programa": _programa_de(db, business.id),
                "resumen": fidelizacion.resumen(db, business.id) if programa else None,
                "max_sellos": MAX_SELLOS,
                "error": error,
                "ok": ok,
            },
            status_code=status,
        )

    if not 1 <= sellos <= MAX_SELLOS:
        return pagina(error=f"La cantidad de sellos tiene que estar entre 1 y {MAX_SELLOS}.", status=400)
    if not premio:
        return pagina(error="Escribe cuál es el premio: es lo que va a leer tu cliente.", status=400)

    if programa is None:
        # Se crea una placa propia para el flujo de sellos. Sin esto, las reseñas
        # que vengan de la caja se le sumarían a una mesa cualquiera y la
        # comparación por soporte —que es algo que el dueño mira— mentiría.
        placa = Placement(business_id=business.id, label=ETIQUETA_PLACA_CAJA)
        db.add(placa)
        db.flush()
        programa = LoyaltyProgram(business_id=business.id, placement_id=placa.id)
        db.add(programa)

    programa.stamps_required = sellos
    programa.reward = premio
    programa.active = activo == "si"
    db.commit()

    return pagina(ok=True)


@router.get("/caja", response_class=HTMLResponse)
def caja(request: Request, db: Session = Depends(get_db)):
    """La pantalla que se deja abierta en la caja.

    El QR que muestra cambia cada minuto. Es lo único que permite sumar un sello,
    así que esta pantalla es el equivalente exacto del timbre que hoy está detrás
    del mostrador: quien lo tiene, puede sellar.
    """
    business = _sesion(request, db)
    if business is None:
        return RedirectResponse("/panel/login", status_code=302)

    programa = _programa_de(db, business.id)
    return templates.TemplateResponse(
        request,
        "caja.html",
        {"business": business, "programa": programa},
    )


@router.get("/caja/codigo")
def codigo(request: Request, db: Session = Depends(get_db)):
    """El código y su QR, en JSON, para que la pantalla se refresque sola.

    El QR viaja como data: URI en vez de como una ruta a una imagen porque
    cambia cada minuto: una URL propia sería un recurso nuevo cada vez, sin nada
    que cachear y con una petición extra por refresco.
    """
    business = _sesion(request, db)
    if business is None:
        return {"error": "sin sesion"}

    programa = _programa_de(db, business.id)
    if programa is None or not programa.active:
        return {"error": "sin programa"}

    url = _url_sello(programa)
    png = base64.b64encode(qr_png_bytes_for_url(url)).decode("ascii")
    return {
        "codigo": fidelizacion.codigo_actual(programa.secret),
        "qr": f"data:image/png;base64,{png}",
        "segundos": fidelizacion.segundos_restantes(),
    }
