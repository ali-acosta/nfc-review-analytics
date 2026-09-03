"""Gestión de la bandeja de quejas privadas.

El valor de interceptar una queja está en resolverla, no en leerla. Sin un
estado, la bandeja solo crece y a los pocos meses el dueño no sabe cuáles ya
atendió, así que deja de abrirla.
"""

from sqlalchemy import update

from app.database import SessionLocal
from app.models import Feedback, utcnow


def mark_resolved(business_id: int, feedback_ids: list[int]) -> int:
    """Marca quejas como atendidas. Devuelve cuántas cambiaron.

    El filtro por business_id no es decorativo: sin él, un id ajeno enviado
    desde el panel de un cliente resolvería la queja de otro comercio.
    """
    if not feedback_ids:
        return 0

    with SessionLocal() as db:
        resultado = db.execute(
            update(Feedback)
            .where(
                Feedback.id.in_(feedback_ids),
                Feedback.business_id == business_id,
                Feedback.resolved_at.is_(None),
            )
            .values(resolved_at=utcnow())
        )
        db.commit()
        return resultado.rowcount


def reopen(business_id: int, feedback_ids: list[int]) -> int:
    """Vuelve a dejarlas pendientes, por si se marcó una por error."""
    if not feedback_ids:
        return 0

    with SessionLocal() as db:
        resultado = db.execute(
            update(Feedback)
            .where(Feedback.id.in_(feedback_ids), Feedback.business_id == business_id)
            .values(resolved_at=None)
        )
        db.commit()
        return resultado.rowcount
