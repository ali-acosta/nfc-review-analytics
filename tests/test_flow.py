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

    def test_la_pagina_de_gracias_ofrece_google_por_la_ruta_que_cuenta(self, negocio, visitante):
        """El botón de la página de gracias tiene que pasar por /go. Enlazando
        directo a Google, esta conversión no se registra y el informe del cliente
        muestra menos reseñas de las que su placa realmente generó."""
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")

        html = telefono.post(f"/r/{negocio.mesa}/feedback", data={"message": "algo"}).text

        assert f'href="/r/{negocio.mesa}/go"' in html
        assert negocio.google_url not in html, "no debe enlazar directo a Google"

    def test_quien_se_queja_y_luego_va_a_google_si_cuenta(self, negocio, visitante):
        """El caso que más vale medir: tuvo un problema, lo dijo en privado y aun
        así fue a dejar su reseña."""
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")
        telefono.post(f"/r/{negocio.mesa}/feedback", data={"message": "la espera fue larga"})

        telefono.get(f"/r/{negocio.mesa}/go", follow_redirects=False)

        resultado = metrics.funnel(metrics.load_taps(negocio.id))
        assert resultado["clicks"] == 1
        assert resultado["visits"] == 1
        assert resultado["conversion"] == 100.0

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


class TestLimitesDeLaBaseDeDatos:
    """SQLite ignora el largo declarado de una columna; Postgres lo aplica.

    Sin recortar al escribir, un texto largo pasa en desarrollo y revienta con un
    error 500 en producción, justo cuando un cliente acaba de escribir su queja
    parado en el mostrador. Esta clase corre en los dos motores (ver
    TEST_DATABASE_URL en conftest) y en Postgres falla si se quita el recorte.
    """

    def test_un_mensaje_larguisimo_no_rompe(self, negocio, visitante):
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")

        respuesta = telefono.post(f"/r/{negocio.mesa}/feedback", data={"message": "a" * 3000})

        assert respuesta.status_code == 200
        with SessionLocal() as db:
            guardado = db.scalars(select(Feedback)).one()
        assert len(guardado.message) == 2000

    def test_un_contacto_larguisimo_no_rompe(self, negocio, visitante):
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")

        respuesta = telefono.post(
            f"/r/{negocio.mesa}/feedback",
            data={"contact": "b" * 400, "message": "algo"},
        )

        assert respuesta.status_code == 200
        with SessionLocal() as db:
            assert len(db.scalars(select(Feedback)).one().contact) == 255

    def test_un_user_agent_larguisimo_no_rompe_la_landing(self, negocio, visitante):
        """Algunos navegadores embebidos en apps mandan user-agents enormes. Si
        no se recortara, ese teléfono no podría ni abrir la página."""
        telefono = visitante()
        telefono.headers["user-agent"] = "Mozilla/5.0 " + "X" * 700

        respuesta = telefono.get(f"/r/{negocio.mesa}")

        assert respuesta.status_code == 200
        with SessionLocal() as db:
            assert len(db.scalars(select(Tap)).first().user_agent) == 512

    def test_una_calificacion_fuera_de_rango_se_descarta(self, negocio, visitante):
        """El formulario solo ofrece 1 a 5, pero un POST a mano puede mandar
        cualquier cosa y ese número termina en el informe del cliente."""
        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")

        telefono.post(f"/r/{negocio.mesa}/feedback", data={"rating": "9", "message": "hola"})

        with SessionLocal() as db:
            assert db.scalars(select(Feedback)).one().rating is None


class TestFiltroDeBots:
    def test_un_telefono_cubot_no_es_un_bot(self, negocio, visitante):
        """Cubot es una marca de Android barato que se vende en Chile y su
        user-agent contiene "bot". Descartar a un cliente real es peor que dejar
        pasar un bot: es una reseña que el negocio pagó por conseguir y que nunca
        va a aparecer en su informe."""
        telefono = visitante()
        telefono.headers["user-agent"] = (
            "Mozilla/5.0 (Linux; Android 12; CUBOT NOTE 20) AppleWebKit/537.36 Chrome/104.0 Mobile Safari/537.36"
        )

        telefono.get(f"/r/{negocio.mesa}")

        assert metrics.funnel(metrics.load_taps(negocio.id))["visits"] == 1

    def test_los_bots_de_verdad_siguen_filtrados(self, negocio, visitante):
        bot = visitante()
        bot.headers["user-agent"] = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

        bot.get(f"/r/{negocio.mesa}")

        assert metrics.funnel(metrics.load_taps(negocio.id))["visits"] == 0
