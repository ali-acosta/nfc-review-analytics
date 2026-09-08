"""Single source of truth for every number the client is shown.

The dashboard and the monthly PDF report both read from here on purpose: if a
report said 33% and the panel said 41% for the same month, the product would
lose the only thing it sells — a number the business owner can trust.

Rules encoded here, and nowhere else:
  · a visitor is a session, never a row (a reload is not a second visit);
  · bots never count;
  · conversion divides unique converting sessions by unique visiting sessions;
  · time is bucketed in the business's local timezone, never in UTC.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Feedback, LoyaltyCard, Placement, Reward, Stamp, Tap

TAP_COLUMNS = ["created_at", "session_id", "outcome", "label"]
FEEDBACK_COLUMNS = ["id", "created_at", "rating", "contact", "message", "label", "resolved_at"]
STAMP_COLUMNS = ["id", "created_at", "tarjeta"]
REWARD_COLUMNS = ["id", "issued_at", "redeemed_at", "sellos", "premio", "tarjeta"]


def _to_local(series: pd.Series) -> pd.Series:
    """Pasa los instantes guardados (UTC) a hora local del negocio, sin zona.

    Todo lo que viene después —filtrar por mes, agrupar por día— trabaja en
    hora local, que es la única con la que el dueño puede contrastar lo que
    vio en su local. En UTC, la cena de un restaurante chileno cae al día
    siguiente y el último día del mes se va al informe del mes siguiente.

    SQLite devuelve datetimes sin zona y Postgres con ella; `utc=True` los
    normaliza a ambos antes de convertir.
    """
    utc = pd.to_datetime(series, utc=True, errors="coerce")
    return utc.dt.tz_convert(ZoneInfo(settings.timezone)).dt.tz_localize(None)


def _a_utc(local_sin_zona: datetime) -> datetime:
    """Un instante en hora local del negocio, expresado en UTC.

    Los límites de período se piensan y se escriben en hora local (el 1 de agosto
    a las 00:00 *en Chile*), pero en la base están guardados en UTC. Esta es la
    traducción que permite filtrar en SQL sin cambiar de criterio: el corte sigue
    siendo el mismo que usa el resto del sistema.
    """
    return local_sin_zona.replace(tzinfo=ZoneInfo(settings.timezone)).astimezone(timezone.utc)


def load_taps(
    business_id: int, start: datetime | None = None, end: datetime | None = None
) -> pd.DataFrame:
    """Eventos del negocio, opcionalmente acotados a un período en hora local.

    Filtrar en SQL y no en pandas no es una optimización prematura: el panel
    recarga en cada refresco y por cada pestaña abierta, así que sin el filtro un
    local con un año de historia mueve cientos de miles de filas cada vez, en una
    instancia gratuita. `in_period` se mantiene por si alguien pasa un DataFrame
    ya cargado.
    """
    query = (
        select(Tap.created_at, Tap.session_id, Tap.outcome, Placement.label)
        .join(Placement, Tap.placement_id == Placement.id)
        .where(Tap.business_id == business_id, Tap.is_bot.is_(False))
    )
    if start is not None:
        query = query.where(Tap.created_at >= _a_utc(start))
    if end is not None:
        query = query.where(Tap.created_at < _a_utc(end))

    with SessionLocal() as db:
        rows = db.execute(query).all()
    df = pd.DataFrame(rows, columns=TAP_COLUMNS)
    if not df.empty:
        df["created_at"] = _to_local(df["created_at"])
    return df


def load_feedback(
    business_id: int, start: datetime | None = None, end: datetime | None = None
) -> pd.DataFrame:
    query = (
        select(
            Feedback.id,
            Feedback.created_at,
            Feedback.rating,
            Feedback.contact,
            Feedback.message,
            Placement.label,
            Feedback.resolved_at,
        )
        .join(Placement, Feedback.placement_id == Placement.id)
        .where(Feedback.business_id == business_id)
        .order_by(Feedback.created_at.desc())
    )
    if start is not None:
        query = query.where(Feedback.created_at >= _a_utc(start))
    if end is not None:
        query = query.where(Feedback.created_at < _a_utc(end))

    with SessionLocal() as db:
        rows = db.execute(query).all()
    df = pd.DataFrame(rows, columns=FEEDBACK_COLUMNS)
    if not df.empty:
        # Ambas fechas en hora local: mezclar husos dentro de la misma tabla
        # confunde a cualquiera que la exporte y compare las dos columnas.
        df["created_at"] = _to_local(df["created_at"])
        df["resolved_at"] = _to_local(df["resolved_at"])
    return df


def load_sellos(business_id: int) -> pd.DataFrame:
    """Los sellos del programa de fidelización, para respaldo y exportación.

    Vive aquí y no en `fidelizacion.py` por la misma razón que las dos funciones
    de arriba: es "leer los datos de un cliente en hora local", y la conversión
    a hora local tiene que salir de un solo lugar. `fidelizacion.py` se queda con
    las reglas —quién puede sellar y cuándo—, que es otra responsabilidad.

    Sin período: un sello no caduca, y el respaldo tiene que llevárselos todos.
    """
    query = (
        select(Stamp.id, Stamp.created_at, LoyaltyCard.token)
        .join(LoyaltyCard, Stamp.card_id == LoyaltyCard.id)
        .where(Stamp.business_id == business_id)
        .order_by(Stamp.created_at)
    )
    with SessionLocal() as db:
        rows = db.execute(query).all()
    df = pd.DataFrame(rows, columns=STAMP_COLUMNS)
    if not df.empty:
        df["created_at"] = _to_local(df["created_at"])
    return df


def load_premios(business_id: int) -> pd.DataFrame:
    """Los premios ganados y su canje.

    Es lo que el comercio le debe a sus clientes: perder esta tabla significa
    que alguien que ya juntó sus sellos llega al mostrador y el sistema le dice
    que no tiene nada. Por eso entra al respaldo semanal junto con las visitas.
    """
    query = (
        select(
            Reward.id,
            Reward.issued_at,
            Reward.redeemed_at,
            Reward.stamps_consumed,
            Reward.reward_text,
            LoyaltyCard.token,
        )
        .join(LoyaltyCard, Reward.card_id == LoyaltyCard.id)
        .where(Reward.business_id == business_id)
        .order_by(Reward.issued_at)
    )
    with SessionLocal() as db:
        rows = db.execute(query).all()
    df = pd.DataFrame(rows, columns=REWARD_COLUMNS)
    if not df.empty:
        df["issued_at"] = _to_local(df["issued_at"])
        df["redeemed_at"] = _to_local(df["redeemed_at"])
    return df


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """[start, end) for a calendar month."""
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def in_period(df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    if df.empty:
        return df
    return df[(df["created_at"] >= start) & (df["created_at"] < end)]


def unique_sessions(taps: pd.DataFrame, outcome: str) -> int:
    if taps.empty:
        return 0
    return int(taps.loc[taps["outcome"] == outcome, "session_id"].nunique())


def funnel(taps: pd.DataFrame) -> dict:
    visits = unique_sessions(taps, "landed")
    clicks = unique_sessions(taps, "went_to_google")
    return {
        "visits": visits,
        "clicks": clicks,
        # Denominator is unique visitors, not raw event rows: a visitor who
        # converts must not also inflate the number they are divided by.
        "conversion": (clicks / visits * 100) if visits else 0.0,
    }


def by_placement(taps: pd.DataFrame) -> pd.DataFrame:
    """Per physical support: visits, clicks and conversion, best first."""
    if taps.empty:
        return pd.DataFrame(columns=["label", "visitas", "clicks", "conversion"])

    visits = taps[taps["outcome"] == "landed"].groupby("label")["session_id"].nunique()
    clicks = taps[taps["outcome"] == "went_to_google"].groupby("label")["session_id"].nunique()
    out = pd.DataFrame({"visitas": visits, "clicks": clicks}).fillna(0).astype(int)
    out["conversion"] = (out["clicks"] / out["visitas"] * 100).where(out["visitas"] > 0, 0.0)
    return out.reset_index().sort_values("conversion", ascending=False)


def by_day(taps: pd.DataFrame) -> pd.DataFrame:
    if taps.empty:
        return pd.DataFrame(columns=["fecha", "visitas"])
    landed = taps[taps["outcome"] == "landed"].copy()
    if landed.empty:
        return pd.DataFrame(columns=["fecha", "visitas"])
    landed["fecha"] = landed["created_at"].dt.date
    return landed.groupby("fecha")["session_id"].nunique().reset_index(name="visitas")
