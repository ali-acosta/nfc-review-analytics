"""El informe mensual es lo que llega al cliente. Sus números tienen que ser
los mismos del panel, sobre el mismo período."""

import re
from datetime import date, datetime, timezone

from app.database import SessionLocal
from app.models import Business
from app.services import metrics
from app.services import report as report_service
from tests.conftest import add_visit, url_informe

KPI_RE = re.compile(r'kpi-label">([^<]+)</div>\s*<div class="kpi-value[^"]*">([^<]+)</div>')


def _kpis(html):
    return {k.strip(): v.strip() for k, v in KPI_RE.findall(html)}


def _business(negocio):
    with SessionLocal() as db:
        return db.get(Business, negocio.id)


class TestNumerosDelInforme:
    def test_coincide_con_lo_que_calcula_el_panel(self, negocio):
        """El invariante central: si el informe dijera 38% y el panel 45%, el
        producto pierde lo único que vende. Ambos leen de metrics."""
        agosto = datetime(2026, 8, 12, 13, tzinfo=timezone.utc)
        for i in range(10):
            add_visit(negocio.id, negocio.mesa_id, converts=i < 4, when=agosto)

        inicio, fin = metrics.month_bounds(2026, 8)
        esperado = metrics.funnel(metrics.in_period(metrics.load_taps(negocio.id), inicio, fin))
        html = report_service.render_html(_business(negocio), 2026, 8)

        kpis = _kpis(html)
        assert kpis["Visitas únicas"] == str(esperado["visits"])
        assert kpis["Fueron a Google"] == str(esperado["clicks"])
        assert kpis["Conversión"] == f"{esperado['conversion']:.0f}%"

    def test_solo_cuenta_el_periodo_pedido(self, negocio):
        agosto = datetime(2026, 8, 12, 13, tzinfo=timezone.utc)
        julio = datetime(2026, 7, 12, 13, tzinfo=timezone.utc)
        for _ in range(5):
            add_visit(negocio.id, negocio.mesa_id, converts=True, when=agosto)
        for _ in range(30):
            add_visit(negocio.id, negocio.mesa_id, converts=False, when=julio)

        kpis = _kpis(report_service.render_html(_business(negocio), 2026, 8))

        assert kpis["Visitas únicas"] == "5"

    def test_compara_contra_el_mes_anterior(self, negocio):
        for _ in range(10):
            add_visit(negocio.id, negocio.mesa_id, when=datetime(2026, 8, 5, 12, tzinfo=timezone.utc))
        for _ in range(5):
            add_visit(negocio.id, negocio.mesa_id, when=datetime(2026, 7, 5, 12, tzinfo=timezone.utc))

        html = report_service.render_html(_business(negocio), 2026, 8)

        # 10 vs 5 = +100% respecto de julio.
        assert "100% vs julio 2026" in html

    def test_sin_mes_anterior_no_inventa_comparacion(self, negocio):
        add_visit(negocio.id, negocio.mesa_id, when=datetime(2026, 8, 5, 12, tzinfo=timezone.utc))

        html = report_service.render_html(_business(negocio), 2026, 8)

        assert "sin mes anterior" in html
        assert "vs julio" not in html

    def test_un_mes_vacio_no_rompe(self, negocio):
        html = report_service.render_html(_business(negocio), 2026, 3)

        assert _kpis(html)["Conversión"] == "0%"
        assert "Todavía no hay visitas" in html or "Sin visitas" in html


class TestPeriodoPorDefecto:
    def test_es_el_ultimo_mes_completo(self):
        """Un informe mensual se envía a mes cerrado. Usar el mes en curso
        mostraría un período a medias durante casi todo el mes."""
        hoy = date.today()

        assert report_service.resolve_period(None) == metrics.previous_month(hoy.year, hoy.month)

    def test_acepta_un_mes_explicito(self):
        assert report_service.resolve_period("2026-08") == (2026, 8)

    def test_rechaza_formato_invalido(self):
        import pytest

        with pytest.raises(ValueError):
            report_service.resolve_period("agosto")


class TestRutas:
    def test_entrega_el_informe(self, negocio, cliente):
        add_visit(negocio.id, negocio.mesa_id, converts=True,
                  when=datetime(2026, 8, 5, 12, tzinfo=timezone.utc))

        respuesta = cliente.get(url_informe(negocio.token, "2026-08"))

        assert respuesta.status_code == 200
        assert negocio.nombre in respuesta.text

    def test_token_desconocido_da_404(self, cliente):
        """Con firma válida pero token inexistente: 404. Sin firma no se llega
        hasta aquí —es 403 antes de mirar la base— para que la respuesta no
        delate qué tokens son de clientes."""
        assert cliente.get(url_informe("token-inventado")).status_code == 404

    def test_mes_mal_escrito_da_400(self, negocio, cliente):
        assert cliente.get(f"/informe/{negocio.token}?mes=agosto").status_code == 400

    def test_un_negocio_no_ve_el_informe_de_otro(self, negocio, cliente):
        with SessionLocal() as db:
            otro = Business(name="Negocio Ajeno", google_review_url="https://g.page/r/CZ/review")
            db.add(otro)
            db.commit()
            token_ajeno = otro.dashboard_token

        respuesta = cliente.get(url_informe(token_ajeno))

        assert respuesta.status_code == 200
        assert negocio.nombre not in respuesta.text

    def test_el_pdf_nunca_devuelve_error_de_servidor(self, negocio, cliente):
        """Con WeasyPrint disponible responde 200; sin sus librerías nativas,
        501 con instrucciones. Nunca un 500."""
        firmada = url_informe(negocio.token).replace("?", "/pdf?")
        respuesta = cliente.get(firmada)

        assert respuesta.status_code in (200, 501)
