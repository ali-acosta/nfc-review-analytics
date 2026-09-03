"""Los eventos se guardan en UTC pero se agrupan en hora local del negocio.

Sin esto, la cena de un restaurante chileno (que cae después de medianoche UTC)
aparecería al día siguiente, y lo del último día del mes se iría al informe del
mes siguiente. El dueño compara el gráfico con lo que vio en su local: si no
cuadra, deja de creerle a la herramienta.
"""

from datetime import datetime, timedelta, timezone

from app.services import metrics
from tests.conftest import add_visit

CHILE = timezone(timedelta(hours=-4))


def _en_chile(dia: int, hora: int, mes: int = 8, minuto: int = 0) -> datetime:
    return datetime(2026, mes, dia, hora, minuto, tzinfo=CHILE)


class TestDiaLocal:
    def test_la_cena_cuenta_en_el_dia_que_ocurrio(self, negocio):
        """21:30 del 31 de agosto en Chile son las 01:30 UTC del 1 de
        septiembre. Para el dueño fue el 31 de agosto."""
        add_visit(negocio.id, negocio.mesa_id, when=_en_chile(31, 21, minuto=30))

        dias = metrics.by_day(metrics.load_taps(negocio.id))["fecha"].tolist()

        assert dias == [datetime(2026, 8, 31).date()]

    def test_una_noche_de_servicio_no_se_parte_en_dos_dias(self, negocio):
        """Turno de cena de un restaurante: 19:00 a 23:00 hora local. En UTC
        cruza la medianoche, pero es una sola noche."""
        for hora in (19, 20, 21, 22, 23):
            add_visit(negocio.id, negocio.mesa_id, when=_en_chile(15, hora))

        tabla = metrics.by_day(metrics.load_taps(negocio.id))

        assert len(tabla) == 1, f"la noche quedó repartida en {len(tabla)} días"
        assert tabla.iloc[0]["visitas"] == 5

    def test_la_madrugada_local_no_se_va_al_dia_anterior(self, negocio):
        add_visit(negocio.id, negocio.mesa_id, when=_en_chile(15, 1))

        dias = metrics.by_day(metrics.load_taps(negocio.id))["fecha"].tolist()

        assert dias == [datetime(2026, 8, 15).date()]


class TestMesLocal:
    def test_el_ultimo_dia_del_mes_no_se_fuga_al_siguiente(self, negocio):
        add_visit(negocio.id, negocio.mesa_id, when=_en_chile(31, 22))

        taps = metrics.load_taps(negocio.id)
        agosto = metrics.funnel(metrics.in_period(taps, *metrics.month_bounds(2026, 8)))
        septiembre = metrics.funnel(metrics.in_period(taps, *metrics.month_bounds(2026, 9)))

        assert agosto["visits"] == 1, "la visita debe estar en el informe de agosto"
        assert septiembre["visits"] == 0

    def test_el_primer_dia_del_mes_no_se_adelanta(self, negocio):
        """01:00 del 1 de septiembre en Chile son las 05:00 UTC del mismo día:
        el caso inverso, que también tiene que caer donde corresponde."""
        add_visit(negocio.id, negocio.mesa_id, when=_en_chile(1, 1, mes=9))

        taps = metrics.load_taps(negocio.id)

        assert metrics.funnel(metrics.in_period(taps, *metrics.month_bounds(2026, 8)))["visits"] == 0
        assert metrics.funnel(metrics.in_period(taps, *metrics.month_bounds(2026, 9)))["visits"] == 1

    def test_el_informe_del_mes_cuadra_con_el_dia_local(self, negocio):
        """Una visita el 31 a las 22:00 y otra el 1 a las 01:00: una en cada
        mes, aunque en UTC ambas caigan en septiembre."""
        add_visit(negocio.id, negocio.mesa_id, when=_en_chile(31, 22))
        add_visit(negocio.id, negocio.mesa_id, when=_en_chile(1, 1, mes=9))

        taps = metrics.load_taps(negocio.id)

        assert metrics.funnel(metrics.in_period(taps, *metrics.month_bounds(2026, 8)))["visits"] == 1
        assert metrics.funnel(metrics.in_period(taps, *metrics.month_bounds(2026, 9)))["visits"] == 1


class TestConfiguracion:
    def test_la_zona_es_configurable(self, negocio, monkeypatch):
        """Hoy es global porque todos los clientes son chilenos. Cambiarla debe
        mover los datos de día, no romper nada."""
        add_visit(negocio.id, negocio.mesa_id, when=_en_chile(31, 22))

        monkeypatch.setattr(metrics.settings, "timezone", "UTC")
        dias_utc = metrics.by_day(metrics.load_taps(negocio.id))["fecha"].tolist()

        monkeypatch.setattr(metrics.settings, "timezone", "America/Santiago")
        dias_chile = metrics.by_day(metrics.load_taps(negocio.id))["fecha"].tolist()

        assert dias_utc == [datetime(2026, 9, 1).date()]
        assert dias_chile == [datetime(2026, 8, 31).date()]
