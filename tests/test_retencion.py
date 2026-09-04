"""Retención de los datos personales que deja un cliente final del comercio.

`Feedback.contact` es el teléfono o el correo de una persona que no es cliente
nuestra, que lo dejó para que le respondieran por un problema puntual y que no
tiene forma de pedir que se lo borren. La Ley 21.719 exige finalidad y plazo.

Lo que estos tests cuidan es que el borrado sea del contacto y **solo** del
contacto —la queja es el registro operativo del comercio y las métricas no
pueden moverse— y que no borre nada mientras no se le pida explícitamente.
"""

from datetime import timedelta

import pytest

from app.database import SessionLocal
from app.models import Feedback, utcnow
from scripts.anonimizar_contactos import anonimizar


def _queja(negocio, *, dias, contacto="+56 9 1234 5678", atendida=False):
    with SessionLocal() as db:
        queja = Feedback(
            business_id=negocio.id,
            placement_id=negocio.mesa_id,
            contact=contacto,
            message="El pedido llegó frío",
            created_at=utcnow() - timedelta(days=dias),
            resolved_at=utcnow() - timedelta(days=dias - 1) if atendida else None,
        )
        db.add(queja)
        db.commit()
        return queja.id


def _leer(queja_id):
    with SessionLocal() as db:
        queja = db.get(Feedback, queja_id)
        return queja.contact, queja.message


class TestQueBorraYQueNo:
    def test_borra_el_contacto_viejo(self, negocio):
        vieja = _queja(negocio, dias=400)

        anonimizar(meses=6, aplicar=True, solo_atendidas=False)

        contacto, _ = _leer(vieja)
        assert contacto == ""

    def test_conserva_el_comentario(self, negocio):
        """Sin el contacto, la queja ya no identifica a nadie, y es el registro
        con el que el comercio trabaja: 'el baño estaba sucio el 3 de agosto'."""
        vieja = _queja(negocio, dias=400)

        anonimizar(meses=6, aplicar=True, solo_atendidas=False)

        _, mensaje = _leer(vieja)
        assert mensaje == "El pedido llegó frío"

    def test_no_toca_las_recientes(self, negocio):
        reciente = _queja(negocio, dias=10)

        anonimizar(meses=6, aplicar=True, solo_atendidas=False)

        contacto, _ = _leer(reciente)
        assert contacto == "+56 9 1234 5678"

    def test_no_borra_quejas(self, negocio):
        _queja(negocio, dias=400)

        anonimizar(meses=6, aplicar=True, solo_atendidas=False)

        with SessionLocal() as db:
            assert db.query(Feedback).count() == 1


class TestNoBorraSinQueSeLoPidan:
    def test_por_defecto_solo_simula(self, negocio):
        """Es un borrado irreversible sobre datos de terceros: correrlo con el
        plazo equivocado no tiene vuelta atrás."""
        vieja = _queja(negocio, dias=400)

        anonimizar(meses=6, aplicar=False, solo_atendidas=False)

        contacto, _ = _leer(vieja)
        assert contacto == "+56 9 1234 5678"

    def test_la_simulacion_no_reporta_borrados(self, negocio):
        _queja(negocio, dias=400)

        assert anonimizar(meses=6, aplicar=False, solo_atendidas=False) == 0


class TestElPlazoSeCuentaDesdeQueLlegoLaQueja:
    """La revisión técnica proponía contar desde que se marcó atendida. Con ese
    criterio, una queja que nadie marca nunca conserva el teléfono para siempre,
    y son justo las abandonadas las que más tiempo acumulan: la política de
    retención se desactivaría sola con solo no tocar un botón."""

    def test_una_queja_vieja_sin_atender_tambien_se_limpia(self, negocio):
        abandonada = _queja(negocio, dias=400, atendida=False)

        anonimizar(meses=6, aplicar=True, solo_atendidas=False)

        contacto, _ = _leer(abandonada)
        assert contacto == ""

    def test_solo_atendidas_recupera_el_criterio_original(self, negocio):
        abandonada = _queja(negocio, dias=400, atendida=False)
        atendida = _queja(negocio, dias=400, atendida=True)

        anonimizar(meses=6, aplicar=True, solo_atendidas=True)

        assert _leer(abandonada)[0] == "+56 9 1234 5678"
        assert _leer(atendida)[0] == ""


class TestElPlazoEsConfigurable:
    @pytest.mark.parametrize(
        "meses, dias, se_borra",
        [
            (6, 400, True),
            (6, 100, False),
            (12, 400, True),
            (12, 200, False),
        ],
    )
    def test_respeta_los_meses_pedidos(self, negocio, meses, dias, se_borra):
        queja = _queja(negocio, dias=dias)

        anonimizar(meses=meses, aplicar=True, solo_atendidas=False)

        assert (_leer(queja)[0] == "") is se_borra


class TestLaLandingLoDice:
    """Un plazo que el cliente final no conoce no cumple con avisarle nada."""

    def test_la_landing_avisa_cuanto_se_guarda_el_contacto(self, negocio, visitante):
        html = visitante().get(f"/r/{negocio.mesa}").text

        assert "6 meses" in html

    def test_la_landing_dice_quien_trata_los_datos(self, negocio, visitante):
        """El responsable del tratamiento es el comercio, no la plataforma: es
        él quien recibe la queja y quien responde. La landing lo nombra."""
        html = visitante().get(f"/r/{negocio.mesa}").text

        aviso = html.split('class="legal"')[1]
        assert negocio.nombre in aviso
