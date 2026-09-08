"""Reglas del programa de sellos. Única fuente de verdad, como `metrics.py`.

Un sello se canjea por algo que cuesta plata, así que este módulo tiene una
responsabilidad distinta de la del resto del producto: en el embudo de reseñas,
un evento de más solo ensucia una métrica; aquí, un sello de más es un café
regalado y un premio cobrado dos veces es plata del comercio.

De ahí las tres reglas que se codifican acá y en ningún otro lado:

1. **El sello lo da la caja, no la mesa.** El token de una placa está pegado en
   una mesa y cualquiera lo lee; si tocar la placa diera un sello, el quinto
   café se regalaría tocándola cinco veces, o desde la casa con una foto del QR.
   Por eso hace falta un código que **rota cada minuto** y que se deriva de un
   secreto que nunca sale del servidor: para sumar un sello hay que estar
   mirando la pantalla de la caja, que es justo la condición física que el
   timbre de papel imponía sola.

2. **Un sello por tarjeta por día**, en hora local del negocio. Nadie se toma
   cinco cafés en una hora. Es la defensa que queda en pie si alguien alcanza a
   compartir un código por WhatsApp dentro de su ventana de dos minutos.

3. **Los sellos no se editan.** El consumo se anota en el premio y nunca en el
   sello, para que el registro de lo que ocurrió quede auditable.
"""

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LoyaltyCard, LoyaltyProgram, Reward, Stamp

# Un minuto por ventana. Se aceptan la actual y la anterior, así que un código
# vive entre 60 y 120 segundos: alcanza de sobra para que el cliente saque el
# teléfono, enfoque y cargue la página, y es demasiado poco para que la foto del
# código sirva de algo más tarde.
VENTANA_SEGUNDOS = 60

# Sin I, L, O, 0 ni 1: el código se muestra en una pantalla y puede terminar
# dictándose o tecleándose, y esos cinco son los que se confunden.
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LARGO_CODIGO = 6


def _ventana(momento: float | None = None) -> int:
    return int((momento if momento is not None else time.time()) // VENTANA_SEGUNDOS)


def _codigo_de_ventana(secret: str, ventana: int) -> str:
    """Código derivado del secreto del programa y del número de ventana.

    HMAC y no un hash a secas: sin clave, cualquiera que conociera el algoritmo
    y la hora podría calcular el código de cualquier local. Con HMAC hace falta
    el secreto, que solo está en la base.
    """
    digest = hmac.new(secret.encode("utf-8"), str(ventana).encode("ascii"), hashlib.sha256).digest()
    # Se consume el digest byte a byte en vez de usar su representación hex: así
    # el código sale del alfabeto legible y no de un hexadecimal con ceros y unos.
    return "".join(_ALFABETO[b % len(_ALFABETO)] for b in digest[:LARGO_CODIGO])


def codigo_actual(secret: str) -> str:
    """El código que la caja tiene que estar mostrando ahora mismo."""
    return _codigo_de_ventana(secret, _ventana())


def segundos_restantes() -> int:
    """Cuánto le queda a la ventana actual, para el contador de la pantalla."""
    return VENTANA_SEGUNDOS - int(time.time()) % VENTANA_SEGUNDOS


def codigo_valido(secret: str, codigo: str) -> bool:
    """Acepta la ventana actual y la inmediatamente anterior.

    La anterior no es una concesión: entre que el cliente enfoca el QR y el
    servidor procesa la petición pasan segundos, y sin tolerancia el sello
    fallaría justo en el cambio de minuto —delante del cajero, que es el peor
    momento posible para que el producto parezca roto—.
    """
    if not codigo or not secret:
        return False
    codigo = codigo.strip().upper()
    ahora = _ventana()
    # compare_digest en vez de ==: comparar cadenas corta en la primera
    # diferencia y filtra por tiempo cuánto prefijo se acertó.
    return any(hmac.compare_digest(_codigo_de_ventana(secret, v), codigo) for v in (ahora, ahora - 1))


# --------------------------------------------------------------------------- #
# Estado de una tarjeta
# --------------------------------------------------------------------------- #


def _limites_del_dia_local(momento: datetime) -> tuple[datetime, datetime]:
    """Inicio y fin, en UTC, del día local del negocio que contiene `momento`.

    El corte es en hora local y no en UTC por lo mismo que en el resto del
    producto: en Chile, medianoche UTC cae a media tarde, así que un límite
    diario en UTC partiría la jornada de un local por la mitad y dejaría pasar
    dos sellos en una misma tarde.
    """
    zona = ZoneInfo(settings.timezone)
    local = momento.astimezone(zona)
    inicio_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_local = inicio_local + timedelta(days=1)
    return inicio_local.astimezone(timezone.utc), fin_local.astimezone(timezone.utc)


def sello_hoy(db: Session, card: LoyaltyCard, momento: datetime | None = None) -> bool:
    """True si esta tarjeta ya recibió su sello del día."""
    inicio, fin = _limites_del_dia_local(momento or datetime.now(timezone.utc))
    return bool(
        db.scalar(
            select(func.count(Stamp.id)).where(
                Stamp.card_id == card.id, Stamp.created_at >= inicio, Stamp.created_at < fin
            )
        )
    )


def sellos_totales(db: Session, card: LoyaltyCard) -> int:
    return db.scalar(select(func.count(Stamp.id)).where(Stamp.card_id == card.id)) or 0


def sellos_consumidos(db: Session, card: LoyaltyCard) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(Reward.stamps_consumed), 0)).where(Reward.card_id == card.id)
    ) or 0


def sellos_disponibles(db: Session, card: LoyaltyCard) -> int:
    """Sellos que todavía no se convirtieron en premio.

    Se calcula restando y no con un contador guardado en la tarjeta: un contador
    se desincroniza en cuanto algo falle a medias, y aquí el número respalda un
    premio. Restar dos agregados siempre da la verdad que hay en las tablas.
    """
    return sellos_totales(db, card) - sellos_consumidos(db, card)


def premios_pendientes(db: Session, card: LoyaltyCard) -> list[Reward]:
    return list(
        db.scalars(
            select(Reward)
            .where(Reward.card_id == card.id, Reward.redeemed_at.is_(None))
            .order_by(Reward.issued_at)
        )
    )


# --------------------------------------------------------------------------- #
# Sellar y canjear
# --------------------------------------------------------------------------- #


def crear_tarjeta(db: Session, program: LoyaltyProgram) -> LoyaltyCard:
    card = LoyaltyCard(business_id=program.business_id)
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


def agregar_sello(db: Session, program: LoyaltyProgram, card: LoyaltyCard) -> bool:
    """Suma un sello y emite el premio si con eso se completa. False si ya tenía
    el sello del día.

    El premio se emite acá y no cuando el cliente abre su tarjeta porque ganarlo
    es un hecho, no una vista: si dependiera de abrir la página, dos pestañas lo
    emitirían dos veces.
    """
    if sello_hoy(db, card):
        return False

    db.add(Stamp(card_id=card.id, business_id=card.business_id))
    db.commit()

    # `while` y no `if`: si el dueño baja el premio de 10 a 3 sellos, una tarjeta
    # con 9 disponibles gana tres premios de una vez, que es lo que le
    # prometieron. Con `if` quedarían sellos colgados sin explicación.
    requeridos = max(1, program.stamps_required)
    while sellos_disponibles(db, card) >= requeridos:
        db.add(
            Reward(
                card_id=card.id,
                business_id=card.business_id,
                stamps_consumed=requeridos,
                reward_text=program.reward,
            )
        )
        db.commit()
    return True


def canjear(db: Session, reward: Reward) -> bool:
    """Marca el premio como cobrado. False si ya lo estaba.

    La condición `redeemed_at IS NULL` va dentro del UPDATE y no en un `if`
    previo: entre leer y escribir cabe otra petición, y dos toques al botón
    cobrarían el mismo premio dos veces. Así el segundo no actualiza ninguna
    fila y se entera.
    """
    resultado = db.execute(
        update(Reward)
        .where(Reward.id == reward.id, Reward.redeemed_at.is_(None))
        .values(redeemed_at=datetime.now(timezone.utc))
    )
    db.commit()
    return resultado.rowcount == 1


# --------------------------------------------------------------------------- #
# Consultas para el panel del dueño
# --------------------------------------------------------------------------- #


def resumen(db: Session, business_id: int) -> dict:
    """Los cuatro números que el dueño quiere ver de su programa."""
    tarjetas = db.scalar(
        select(func.count(LoyaltyCard.id)).where(LoyaltyCard.business_id == business_id)
    ) or 0
    sellos = db.scalar(
        select(func.count(Stamp.id)).where(Stamp.business_id == business_id)
    ) or 0
    ganados = db.scalar(
        select(func.count(Reward.id)).where(Reward.business_id == business_id)
    ) or 0
    canjeados = db.scalar(
        select(func.count(Reward.id)).where(
            Reward.business_id == business_id, Reward.redeemed_at.is_not(None)
        )
    ) or 0
    return {
        "tarjetas": tarjetas,
        "sellos": sellos,
        "premios_ganados": ganados,
        "premios_canjeados": canjeados,
    }
