"""Lo que ve el cliente final del comercio: sumar un sello y ver su tarjeta.

Rutas públicas, sin login y sin ningún dato personal. La tarjeta *es* su token,
igual que la de cartón que reemplaza: quien la tiene, la tiene.

El sello siempre entra por `/sello/{programa}/{codigo}`, o sea por el código que
rota en la pantalla de la caja. **No hay ninguna ruta que sume un sello desde la
placa de la mesa**, y eso es deliberado: esa placa está pegada a la vista de
todos y un sello vale un café.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import LoyaltyCard, LoyaltyProgram
from app.services import fidelizacion
from app.services.ratelimit import client_ip, tarjeta_limiter

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Un año: la tarjeta de un café se llena en semanas o meses, y una cookie que
# caduca antes le borra los sellos a un cliente que no hizo nada malo.
COOKIE_MAX_AGE = 365 * 24 * 60 * 60


def _nombre_cookie(program_token: str) -> str:
    """Una cookie por programa.

    La tarjeta está alcanzada por comercio, así que un cliente que va a dos
    locales tiene dos tarjetas y necesita recordar las dos. Una sola cookie
    compartida haría que entrar al segundo local le borrara la del primero.
    """
    return f"tarjeta_{program_token}"


def _set_cookie_tarjeta(response: Response, program_token: str, card_token: str) -> None:
    response.set_cookie(
        _nombre_cookie(program_token),
        card_token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.base_url.startswith("https://"),
    )


def _programa_activo(db: Session, token: str) -> LoyaltyProgram:
    programa = db.scalar(select(LoyaltyProgram).where(LoyaltyProgram.token == token))
    if programa is None or not programa.active:
        raise HTTPException(status_code=404, detail="Programa no encontrado")
    return programa


def _tarjeta_o_404(db: Session, token: str) -> LoyaltyCard:
    card = db.scalar(select(LoyaltyCard).where(LoyaltyCard.token == token))
    if card is None:
        raise HTTPException(status_code=404, detail="Tarjeta no encontrada")
    return card


def _programa_de(db: Session, card: LoyaltyCard) -> LoyaltyProgram | None:
    return db.scalar(select(LoyaltyProgram).where(LoyaltyProgram.business_id == card.business_id))


def _contexto_tarjeta(db: Session, card: LoyaltyCard, programa: LoyaltyProgram, codigo: str) -> dict:
    """Todo lo que la plantilla necesita para dibujar la tarjeta."""
    disponibles = fidelizacion.sellos_disponibles(db, card)
    requeridos = max(1, programa.stamps_required)
    pendientes = fidelizacion.premios_pendientes(db, card)
    return {
        "business": programa.business,
        "programa": programa,
        "card": card,
        "disponibles": disponibles,
        "requeridos": requeridos,
        "faltan": max(0, requeridos - disponibles),
        "premios": pendientes,
        # El botón de canje solo aparece si el código de la caja es válido en
        # este momento: cobrar un premio tiene que pasar delante del cajero, no
        # desde el sillón de la casa abriendo un marcador.
        "puede_canjear": bool(pendientes) and fidelizacion.codigo_valido(programa.secret, codigo),
        "codigo": codigo,
        "placement": programa.placement,
        "tiene_logo": programa.business.logo_data is not None,
    }


@router.get("/sello/{program_token}/{codigo}", response_class=HTMLResponse)
def sellar(
    program_token: str,
    codigo: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Lo que abre el QR de la caja. Suma el sello del día y muestra la tarjeta."""
    programa = _programa_activo(db, program_token)

    if not fidelizacion.codigo_valido(programa.secret, codigo):
        # El código de la pantalla ya rotó. No es un error del cliente y no se
        # le trata como tal: se le pide volver a escanear.
        return templates.TemplateResponse(
            request,
            "sello_invalido.html",
            {"business": programa.business, "tiene_logo": programa.business.logo_data is not None},
            status_code=410,
        )

    token_guardado = request.cookies.get(_nombre_cookie(program_token))
    card = db.scalar(select(LoyaltyCard).where(LoyaltyCard.token == token_guardado)) if token_guardado else None
    # Una cookie que apunta a la tarjeta de OTRO comercio no sirve aquí: sería
    # sumarle sellos de este local a la tarjeta del de al lado.
    if card is not None and card.business_id != programa.business_id:
        card = None

    if card is None:
        # Solo la creación de tarjetas se limita por IP. Sellar no puede
        # limitarse así: en un local todos los clientes salen por el mismo WiFi,
        # y un tope por IP dejaría sin su sello a la mitad de la fila.
        if not tarjeta_limiter.allow(client_ip(request)):
            return templates.TemplateResponse(
                request,
                "sello_invalido.html",
                {
                    "business": programa.business,
                    "tiene_logo": programa.business.logo_data is not None,
                    "mensaje": "Hubo demasiadas tarjetas nuevas desde esta conexión. "
                    "Espera un momento y vuelve a escanear.",
                },
                status_code=429,
            )
        card = fidelizacion.crear_tarjeta(db, programa)

    sumado = fidelizacion.agregar_sello(db, programa, card)

    # Se redirige a la tarjeta en vez de renderizarla aquí para que la URL que
    # queda en el navegador sea la de la tarjeta: es la que el cliente puede
    # guardar en su pantalla de inicio, y la que tiene sentido si recarga.
    destino = f"/tarjeta/{card.token}?s={'ok' if sumado else 'repetido'}&c={codigo}"
    response = RedirectResponse(destino, status_code=303)
    _set_cookie_tarjeta(response, program_token, card.token)
    return response


@router.get("/mi-tarjeta/{program_token}", response_class=HTMLResponse)
def mi_tarjeta(program_token: str, request: Request, db: Session = Depends(get_db)):
    """"Ver mi tarjeta" desde la landing, sin que el cliente tenga que guardar su URL.

    Existe porque la plantilla de la landing no puede leer la cookie: esta ruta
    la lee y lleva a la tarjeta que corresponda. Quien todavía no tiene ninguna
    recibe una explicación, no un 404 —no hizo nada mal, solo no ha pasado por
    la caja—.
    """
    programa = _programa_activo(db, program_token)
    token_guardado = request.cookies.get(_nombre_cookie(program_token))
    card = db.scalar(select(LoyaltyCard).where(LoyaltyCard.token == token_guardado)) if token_guardado else None

    if card is None or card.business_id != programa.business_id:
        return templates.TemplateResponse(
            request,
            "sello_invalido.html",
            {
                "business": programa.business,
                "tiene_logo": programa.business.logo_data is not None,
                "mensaje": f"Todavía no tienes tarjeta de sellos en {programa.business.name}. "
                "Pídela en la caja: escaneas el código de la pantalla y queda creada al instante.",
            },
        )

    return RedirectResponse(f"/tarjeta/{card.token}", status_code=302)


@router.get("/tarjeta/{card_token}", response_class=HTMLResponse)
def ver_tarjeta(
    card_token: str,
    request: Request,
    s: str = "",
    c: str = "",
    db: Session = Depends(get_db),
):
    card = _tarjeta_o_404(db, card_token)
    programa = _programa_de(db, card)
    if programa is None:
        raise HTTPException(status_code=404, detail="Este comercio no tiene programa de sellos")

    contexto = _contexto_tarjeta(db, card, programa, c)
    contexto["aviso"] = s
    response = templates.TemplateResponse(request, "tarjeta.html", contexto)
    # Se refresca la cookie en cada visita: quien abrió su tarjeta desde un
    # marcador en otro navegador queda con la cookie puesta también ahí.
    _set_cookie_tarjeta(response, programa.token, card.token)
    return response


@router.post("/tarjeta/{card_token}/canjear", response_class=HTMLResponse)
def canjear(
    card_token: str,
    request: Request,
    codigo: str = Form(""),
    db: Session = Depends(get_db),
):
    """Cobra un premio. Exige el código de la caja, igual que sellar.

    Es la misma primitiva de confianza a propósito: el premio cuesta plata, así
    que cobrarlo tiene que ocurrir delante de quien atiende. Sin esto, cualquiera
    con el enlace de su tarjeta cobraría su café desde la casa y llegaría al
    local con la tarjeta ya limpia.
    """
    card = _tarjeta_o_404(db, card_token)
    programa = _programa_de(db, card)
    if programa is None:
        raise HTTPException(status_code=404, detail="Este comercio no tiene programa de sellos")

    if not fidelizacion.codigo_valido(programa.secret, codigo):
        contexto = _contexto_tarjeta(db, card, programa, "")
        contexto["aviso"] = "codigo_vencido"
        return templates.TemplateResponse(request, "tarjeta.html", contexto, status_code=410)

    pendientes = fidelizacion.premios_pendientes(db, card)
    # Se cobra el más antiguo: si alguien juntó dos, el primero que ganó es el
    # primero que sale.
    cobrado = fidelizacion.canjear(db, pendientes[0]) if pendientes else False

    contexto = _contexto_tarjeta(db, card, programa, codigo)
    contexto["aviso"] = "canjeado" if cobrado else "sin_premio"
    return templates.TemplateResponse(request, "tarjeta.html", contexto)
