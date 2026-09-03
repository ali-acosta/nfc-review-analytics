"""El mensaje mensual es el recordatorio recurrente de que el servicio existe.
Si sus números no coinciden con el informe, se pierde la confianza que sostiene
la suscripción."""

import asyncio
import re
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import Business
from app.services import metrics
from app.services import report as report_service
from tests.conftest import add_visit

AGOSTO = datetime(2026, 8, 14, 13, tzinfo=timezone.utc)
JULIO = datetime(2026, 7, 14, 13, tzinfo=timezone.utc)


def _business(negocio):
    with SessionLocal() as db:
        return db.get(Business, negocio.id)


def _resumen(negocio, year=2026, month=8, base="https://reseñas.cl"):
    return report_service.build_summary_text(_business(negocio), year, month, base)


class TestResumenMensual:
    def test_lleva_los_mismos_numeros_que_el_informe(self, negocio):
        for i in range(10):
            add_visit(negocio.id, negocio.mesa_id, converts=i < 4, when=AGOSTO)

        inicio, fin = metrics.month_bounds(2026, 8)
        esperado = metrics.funnel(metrics.in_period(metrics.load_taps(negocio.id), inicio, fin))
        texto = _resumen(negocio)

        assert f"Visitas únicas: {esperado['visits']}" in texto
        assert f"Fueron a Google: {esperado['clicks']}" in texto
        assert f"Conversión: {esperado['conversion']:.0f}%" in texto

    def test_incluye_el_enlace_al_informe_del_periodo(self, negocio):
        add_visit(negocio.id, negocio.mesa_id, when=AGOSTO)

        texto = _resumen(negocio, base="https://reseñas.cl/")

        assert f"https://reseñas.cl/informe/{negocio.token}?mes=2026-08" in texto

    def test_muestra_la_variacion_contra_el_mes_anterior(self, negocio):
        for _ in range(10):
            add_visit(negocio.id, negocio.mesa_id, when=AGOSTO)
        for _ in range(5):
            add_visit(negocio.id, negocio.mesa_id, when=JULIO)

        texto = _resumen(negocio)

        assert "+100% vs julio 2026" in texto

    def test_sin_mes_anterior_omite_la_comparacion(self, negocio):
        add_visit(negocio.id, negocio.mesa_id, when=AGOSTO)

        texto = _resumen(negocio)

        assert "vs julio" not in texto
        assert "Visitas únicas: 1" in texto

    def test_destaca_el_mejor_soporte(self, negocio):
        for i in range(4):
            add_visit(negocio.id, negocio.mesa_id, converts=i < 3, when=AGOSTO)
        for i in range(4):
            add_visit(negocio.id, negocio.meson_id, converts=i < 1, when=AGOSTO)

        texto = _resumen(negocio)

        assert "Mejor soporte: Mesa 1 (75%)" in texto

    def test_un_mes_vacio_no_rompe(self, negocio):
        texto = _resumen(negocio, month=3)

        assert "Conversión: 0%" in texto
        assert "Marzo 2026" in texto


class TestEnvioPorTelegram:
    def test_sin_configurar_informa_que_no_envio(self, monkeypatch):
        from app.services import telegram

        monkeypatch.setattr(telegram.settings, "telegram_bot_token", "")
        monkeypatch.setattr(telegram.settings, "telegram_chat_id", "")

        assert asyncio.run(telegram.send_message("", "hola")) is False
        assert asyncio.run(telegram.send_document("", "x.pdf", b"datos")) is False

    def test_un_fallo_de_red_se_reporta_sin_reventar(self, monkeypatch):
        """A diferencia de las alertas, aquí el resultado importa: el agendador
        tiene que enterarse de que no se envió."""
        import httpx

        from app.services import telegram

        monkeypatch.setattr(telegram.settings, "telegram_bot_token", "token-prueba")

        class TransporteRoto:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def post(self, *_a, **_k):
                raise httpx.ConnectError("sin red")

        monkeypatch.setattr(telegram.httpx, "AsyncClient", lambda **_k: TransporteRoto())

        assert asyncio.run(telegram.send_message("123", "hola")) is False

    def test_envio_exitoso_devuelve_true(self, monkeypatch):
        from app.services import telegram

        monkeypatch.setattr(telegram.settings, "telegram_bot_token", "token-prueba")
        enviados = []

        class TransporteOk:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def post(self, url, **kwargs):
                enviados.append((url, kwargs))

                class R:
                    def raise_for_status(self):
                        return None

                return R()

        monkeypatch.setattr(telegram.httpx, "AsyncClient", lambda **_k: TransporteOk())

        assert asyncio.run(telegram.send_message("123", "hola")) is True
        assert enviados[0][1]["json"]["text"] == "hola"


class TestAgendador:
    def test_el_workflow_corre_a_mes_cerrado(self):
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent
        workflow = (raiz / ".github" / "workflows" / "informe-mensual.yml").read_text(encoding="utf-8")

        cron = re.search(r'cron:\s*"([^"]+)"', workflow).group(1)
        minuto, hora, dia, mes, _ = cron.split()

        assert dia == "1" and mes == "*", "debe correr el día 1 de cada mes"
        assert minuto.isdigit() and hora.isdigit()
