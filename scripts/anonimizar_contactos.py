"""Borra los contactos viejos del buzón de quejas.

`Feedback.contact` guarda el teléfono o el correo de un cliente final del
comercio: una persona que no es cliente nuestra, que dejó su contacto para que
le respondieran por un problema concreto, y que no tiene forma de pedir que lo
borren. La Ley 21.719 exige una finalidad y un plazo; guardar ese dato para
siempre no tiene ninguna de las dos.

Se borra **solo el contacto**, nunca el comentario ni la queja. El comentario es
el registro operativo del comercio ("el baño estaba sucio el 3 de agosto") y sin
el contacto ya no identifica a nadie. Las métricas no se tocan.

**El plazo se cuenta desde que llegó la queja, no desde que se marcó atendida.**
La revisión técnica proponía contarlo desde la atención, pero eso deja una
política de retención que el dueño desactiva sin querer con solo no tocar el
botón: una queja que nadie marcó nunca conserva el teléfono para siempre, y son
justo las abandonadas las que más tiempo acumulan. Seis meses después nadie va a
llamar a ese cliente, esté marcada o no. `--solo-atendidas` recupera el criterio
original para quien lo prefiera.

**No borra nada salvo que se le pida con `--aplicar`.** Por defecto simula y
muestra lo que haría: es un borrado irreversible sobre datos de terceros, y el
error de correrlo con el plazo equivocado no tiene vuelta atrás.

    python -m scripts.anonimizar_contactos                  # simula, 6 meses
    python -m scripts.anonimizar_contactos --meses 12       # simula, 12 meses
    python -m scripts.anonimizar_contactos --aplicar        # borra de verdad
    python -m scripts.anonimizar_contactos --aplicar --solo-atendidas
"""

import argparse
import sys
from datetime import timedelta

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Business, Feedback, utcnow

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

MESES_POR_DEFECTO = 6
DIAS_POR_MES = 30  # aproximación deliberada: el plazo es una política, no una fecha exacta


def _consulta(corte, solo_atendidas: bool):
    condiciones = [Feedback.contact != "", Feedback.created_at < corte]
    if solo_atendidas:
        condiciones.append(Feedback.resolved_at.is_not(None))
    return select(Feedback).where(*condiciones)


def anonimizar(meses: int, aplicar: bool, solo_atendidas: bool) -> int:
    corte = utcnow() - timedelta(days=meses * DIAS_POR_MES)
    criterio = "atendidas" if solo_atendidas else "recibidas"

    print(f"\nQuejas {criterio} antes de {corte:%d-%m-%Y} con contacto guardado.\n")

    with SessionLocal() as db:
        objetivo = db.scalars(_consulta(corte, solo_atendidas).order_by(Feedback.created_at)).all()

        if not objetivo:
            print("  No hay ningún contacto que borrar. Nada que hacer.\n")
            return 0

        nombres = {
            b.id: b.name for b in db.scalars(select(Business)).all()
        }
        por_negocio: dict[int, int] = {}
        for queja in objetivo:
            por_negocio[queja.business_id] = por_negocio.get(queja.business_id, 0) + 1

        for business_id, cuantas in sorted(por_negocio.items(), key=lambda par: -par[1]):
            print(f"  {nombres.get(business_id, f'negocio {business_id}'):30} {cuantas:4} contactos")

        mas_vieja = objetivo[0].created_at
        print(f"\n  Total: {len(objetivo)} contactos. El más antiguo es del {mas_vieja:%d-%m-%Y}.")

        if not aplicar:
            print("\n  SIMULACIÓN: no se borró nada. Agrega --aplicar para hacerlo de verdad.\n")
            return 0

        for queja in objetivo:
            queja.contact = ""
        db.commit()

    print(f"\n  Listo: se borraron {len(objetivo)} contactos. Los comentarios quedaron intactos.\n")
    return len(objetivo)


def _pendientes_con_contacto() -> int:
    """Cuántas quejas sin atender guardan un contacto, para avisarlo al final."""
    with SessionLocal() as db:
        return db.scalar(
            select(func.count())
            .select_from(Feedback)
            .where(Feedback.contact != "", Feedback.resolved_at.is_(None))
        ) or 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--meses", type=int, default=MESES_POR_DEFECTO,
        help=f"antigüedad a partir de la cual se borra el contacto (por defecto {MESES_POR_DEFECTO})",
    )
    parser.add_argument(
        "--aplicar", action="store_true",
        help="borra de verdad; sin esta bandera solo simula",
    )
    parser.add_argument(
        "--solo-atendidas", action="store_true",
        help="limita el borrado a las quejas ya marcadas como atendidas",
    )
    args = parser.parse_args()

    if args.meses < 1:
        parser.error("--meses tiene que ser al menos 1")

    anonimizar(args.meses, args.aplicar, args.solo_atendidas)

    if args.solo_atendidas:
        pendientes = _pendientes_con_contacto()
        if pendientes:
            print(
                f"  Aviso: hay {pendientes} quejas sin atender que conservan el contacto y este\n"
                "  modo no las toca. Si nadie las va a marcar, ese dato se guarda indefinidamente.\n"
            )


if __name__ == "__main__":
    main()
