"""El valor de interceptar una queja está en resolverla, no en leerla."""

import pandas as pd

from app.database import SessionLocal
from app.models import Business, Feedback
from app.services import inbox, metrics


def _queja(negocio, mensaje="algo pasó") -> int:
    with SessionLocal() as db:
        f = Feedback(
            business_id=negocio.id,
            placement_id=negocio.mesa_id,
            message=mensaje,
        )
        db.add(f)
        db.commit()
        return f.id


class TestMarcarAtendidas:
    def test_marca_las_indicadas(self, negocio):
        uno, dos = _queja(negocio, "una"), _queja(negocio, "dos")

        assert inbox.mark_resolved(negocio.id, [uno]) == 1

        con_estado = metrics.load_feedback(negocio.id).set_index("id")
        # pandas devuelve NaT, no None, para una fecha nula.
        assert not pd.isna(con_estado.loc[uno, "resolved_at"])
        assert pd.isna(con_estado.loc[dos, "resolved_at"])

    def test_marcar_dos_veces_no_cuenta_de_nuevo(self, negocio):
        uno = _queja(negocio)
        inbox.mark_resolved(negocio.id, [uno])

        assert inbox.mark_resolved(negocio.id, [uno]) == 0

    def test_sin_ids_no_hace_nada(self, negocio):
        _queja(negocio)

        assert inbox.mark_resolved(negocio.id, []) == 0

    def test_se_puede_reabrir(self, negocio):
        uno = _queja(negocio)
        inbox.mark_resolved(negocio.id, [uno])

        assert inbox.reopen(negocio.id, [uno]) == 1
        assert pd.isna(metrics.load_feedback(negocio.id).set_index("id").loc[uno, "resolved_at"])


class TestAislamientoEntreClientes:
    def test_no_se_puede_resolver_la_queja_de_otro_comercio(self, negocio):
        """Sin filtrar por negocio, un id ajeno enviado desde el panel de un
        cliente cerraría la queja de otro."""
        with SessionLocal() as db:
            otro = Business(name="Ajeno", google_review_url="https://g.page/r/CZ/review")
            db.add(otro)
            db.flush()
            ajena = Feedback(business_id=otro.id, placement_id=negocio.mesa_id, message="ajena")
            db.add(ajena)
            db.commit()
            ajena_id, otro_id = ajena.id, otro.id

        assert inbox.mark_resolved(negocio.id, [ajena_id]) == 0

        with SessionLocal() as db:
            assert db.get(Feedback, ajena_id).resolved_at is None

        # El dueño legítimo sí puede.
        assert inbox.mark_resolved(otro_id, [ajena_id]) == 1

    def test_reabrir_tampoco_cruza_comercios(self, negocio):
        with SessionLocal() as db:
            otro = Business(name="Ajeno", google_review_url="https://g.page/r/CZ/review")
            db.add(otro)
            db.flush()
            ajena = Feedback(business_id=otro.id, placement_id=negocio.mesa_id, message="ajena")
            db.add(ajena)
            db.commit()
            ajena_id, otro_id = ajena.id, otro.id
        inbox.mark_resolved(otro_id, [ajena_id])

        assert inbox.reopen(negocio.id, [ajena_id]) == 0


class TestVistaDeLaBandeja:
    def test_las_pendientes_van_primero(self, negocio):
        """Son las que hay que atender: tienen que estar arriba."""
        from app.dashboard.dash_app import _inbox_rows

        vieja = _queja(negocio, "vieja")
        _queja(negocio, "nueva")
        inbox.mark_resolved(negocio.id, [vieja])

        estados = [fila["estado"] for fila in _inbox_rows(negocio.id)]

        assert estados == ["Pendiente", "Atendida"]

    def test_muestra_el_estado_y_el_contenido(self, negocio):
        from app.dashboard.dash_app import _inbox_rows

        _queja(negocio, "la espera fue larga")

        fila = _inbox_rows(negocio.id)[0]

        assert fila["estado"] == "Pendiente"
        assert fila["mensaje"] == "la espera fue larga"
        assert fila["soporte"] == "Mesa 1"
        assert fila["estrellas"] == "—", "sin calificación no debe mostrarse vacío"

    def test_sin_quejas_devuelve_lista_vacia(self, negocio):
        from app.dashboard.dash_app import _inbox_rows

        assert _inbox_rows(negocio.id) == []
