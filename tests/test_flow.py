"""El recorrido real de un visitante, a través de las rutas."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Feedback, Tap
from app.services import metrics
from tests.conftest import BOT_UA


def _taps(outcome=None):
    with SessionLocal() as db:
        query = select(Tap)
        if outcome:
            query = query.where(Tap.outcome == outcome)
        return db.scalars(query).all()


class TestPoliticaDeGoogle:
    """La restricción no negociable del producto: el camino a Google está
    siempre disponible, sin filtro previo por calificación."""

    def test_la_landing_siempre_ofrece_google_en_un_click(self, negocio, visitante):
        html = visitante().get(f"/r/{negocio.mesa}").text

        assert f'href="/r/{negocio.mesa}/go"' in html

    def test_la_landing_no_pide_estrellas_antes_de_google(self, negocio, visitante):
        """Si alguien reintroduce el selector de estrellas como paso previo,
        este test cae. Ver CLAUDE.md, restricción 1."""
        html = visitante().get(f"/r/{negocio.mesa}").text.lower()

        assert 'data-rating' not in html
        assert 'class="star"' not in html

    def test_el_canal_privado_es_adicional_no_reemplazo(self, negocio, visitante):
        html = visitante().get(f"/r/{negocio.mesa}").text

        assert "private-toggle" in html
        assert f'href="/r/{negocio.mesa}/go"' in html


class TestRegistroDeVisitas:
    def test_llegar_registra_una_visita(self, negocio, visitante):
        respuesta = visitante().get(f"/r/{negocio.mesa}")

        assert respuesta.status_code == 200
        assert len(_taps("landed")) == 1

    def test_recargar_no_suma_visitas(self, negocio, visitante):
        telefono = visitante()
        for _ in range(4):
            telefono.get(f"/r/{negocio.mesa}")

        assert len(_taps("landed")) == 1
        assert metrics.funnel(metrics.load_taps(negocio.id))["visits"] == 1

    def test_dos_telefonos_distintos_son_dos_visitas(self, negocio, visitante):
        visitante().get(f"/r/{negocio.mesa}")
        visitante().get(f"/r/{negocio.mesa}")

        assert metrics.funnel(metrics.load_taps(negocio.id))["visits"] == 2

    def test_los_bots_quedan_marcados(self, negocio, visitante):
        bot = visitante()
        bot.headers["user-agent"] = BOT_UA
        bot.get(f"/r/{negocio.mesa}")

        assert all(tap.is_bot for tap in _taps())
        assert metrics.funnel(metrics.load_taps(negocio.id))["visits"] == 0

    def test_codigo_inexistente_da_404(self, cliente):
        assert cliente.get("/r/no-existe").status_code == 404


class TestIrAGoogle:
    def test_redirige_al_link_del_negocio(self, negocio, visitante):
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")

        respuesta = telefono.get(f"/r/{negocio.mesa}/go", follow_redirects=False)

        assert respuesta.status_code == 302
        assert respuesta.headers["location"] == negocio.google_url

    def test_registra_la_conversion(self, negocio, visitante):
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")
        telefono.get(f"/r/{negocio.mesa}/go", follow_redirects=False)

        resultado = metrics.funnel(metrics.load_taps(negocio.id))
        assert resultado == {"visits": 1, "clicks": 1, "conversion": 100.0}

    def test_tocar_dos_veces_cuenta_una_sola_conversion(self, negocio, visitante):
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")
        for _ in range(3):
            telefono.get(f"/r/{negocio.mesa}/go", follow_redirects=False)

        assert len(_taps("went_to_google")) == 1

    def test_click_sin_visita_previa_no_supera_el_100(self, negocio, visitante):
        """Entrar directo al enlace /go (link compartido, cookies borradas)
        dejaría el denominador corto si no se rellenara la visita."""
        visitante().get(f"/r/{negocio.mesa}/go", follow_redirects=False)

        resultado = metrics.funnel(metrics.load_taps(negocio.id))
        assert resultado["visits"] == 1
        assert resultado["conversion"] == 100.0


class TestCanalPrivado:
    def test_guarda_el_comentario_y_avisa(self, negocio, visitante):
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")

        respuesta = telefono.post(
            f"/r/{negocio.mesa}/feedback",
            data={"rating": "2", "contact": "ana@correo.cl", "message": "La espera fue larga"},
        )

        assert respuesta.status_code == 200
        with SessionLocal() as db:
            guardado = db.scalars(select(Feedback)).one()
        assert guardado.rating == 2
        assert guardado.message == "La espera fue larga"
        assert len(_taps("left_private_feedback")) == 1

    def test_la_calificacion_es_opcional(self, negocio, visitante):
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")

        respuesta = telefono.post(f"/r/{negocio.mesa}/feedback", data={"message": "Sin estrellas"})

        assert respuesta.status_code == 200
        with SessionLocal() as db:
            assert db.scalars(select(Feedback)).one().rating is None

    def test_dejar_comentario_no_cuenta_como_conversion(self, negocio, visitante):
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")
        telefono.post(f"/r/{negocio.mesa}/feedback", data={"message": "Algo pasó"})

        assert metrics.funnel(metrics.load_taps(negocio.id))["clicks"] == 0

class TestLasAlertasNuncaRompenElFlujo:
    """La ruta que genera ingresos no puede depender de la que da comodidad.
    Un fallo avisando por Telegram no puede impedir que el cliente deje su
    comentario ni mostrarle una pantalla de error."""

    def _alerta_con_transporte_roto(self, monkeypatch, error):
        import asyncio

        from app.services import telegram

        monkeypatch.setattr(telegram.settings, "telegram_bot_token", "token-de-prueba")

        class TransporteRoto:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def post(self, *_args, **_kwargs):
                raise error

        monkeypatch.setattr(telegram.httpx, "AsyncClient", lambda **_kwargs: TransporteRoto())
        asyncio.run(telegram.send_alert("123456", "mensaje de prueba"))

    def test_no_propaga_errores_de_red(self, monkeypatch):
        import httpx

        self._alerta_con_transporte_roto(monkeypatch, httpx.ConnectError("sin red"))

    def test_no_propaga_errores_inesperados(self, monkeypatch):
        """El bug que este test encontró: solo se capturaba httpx.HTTPError, así
        que cualquier otra excepción llegaba hasta el cliente como un error 500."""
        self._alerta_con_transporte_roto(monkeypatch, RuntimeError("algo inesperado"))

    def test_sin_configurar_no_hace_nada(self, monkeypatch):
        import asyncio

        from app.services import telegram

        monkeypatch.setattr(telegram.settings, "telegram_bot_token", "")
        asyncio.run(telegram.send_alert("", "mensaje"))

    def test_la_alerta_no_bloquea_la_respuesta(self, negocio, visitante):
        """Se envía en segundo plano: el cliente está parado en el local."""
        from app.routers import redirect

        import inspect

        firma = inspect.signature(redirect.submit_feedback)
        assert "background" in firma.parameters, "la alerta debe enviarse como BackgroundTask"

        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")
        respuesta = telefono.post(f"/r/{negocio.mesa}/feedback", data={"message": "hola"})

        assert respuesta.status_code == 200
        with SessionLocal() as db:
            assert db.scalars(select(Feedback)).all()
