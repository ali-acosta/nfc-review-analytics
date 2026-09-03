"""El token de una placa está pegado en una mesa: es público por diseño.
Sin límite, un script puede inflar las visitas de un cliente y hundirle la
conversión, que es justo el número por el que paga."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import metrics
from app.services.auth import hash_password
from app.services.ratelimit import RateLimiter, client_ip, feedback_limiter, login_limiter, public_limiter
from app.database import SessionLocal
from app.models import Business


@pytest.fixture(autouse=True)
def _limites_limpios():
    """Los limitadores son globales del proceso: sin esto, un test arrastraría
    los intentos del anterior."""
    for limiter in (public_limiter, login_limiter, feedback_limiter):
        limiter._hits.clear()
    yield
    for limiter in (public_limiter, login_limiter, feedback_limiter):
        limiter._hits.clear()


class TestElLimitador:
    def test_deja_pasar_hasta_el_maximo(self):
        limiter = RateLimiter(max_hits=3, window_seconds=60)

        assert [limiter.allow("ip") for _ in range(4)] == [True, True, True, False]

    def test_cada_clave_lleva_su_propia_cuenta(self):
        limiter = RateLimiter(max_hits=1, window_seconds=60)

        assert limiter.allow("ip-a") is True
        assert limiter.allow("ip-b") is True
        assert limiter.allow("ip-a") is False

    def test_la_ventana_libera_al_expirar(self, monkeypatch):
        import app.services.ratelimit as modulo

        reloj = {"t": 1000.0}
        monkeypatch.setattr(modulo.time, "monotonic", lambda: reloj["t"])
        limiter = RateLimiter(max_hits=1, window_seconds=60)

        assert limiter.allow("ip") is True
        assert limiter.allow("ip") is False

        reloj["t"] += 61
        assert limiter.allow("ip") is True

    def test_reset_borra_la_cuenta(self):
        limiter = RateLimiter(max_hits=1, window_seconds=60)
        limiter.allow("ip")

        limiter.reset("ip")

        assert limiter.allow("ip") is True


class TestIpDelCliente:
    def test_usa_x_forwarded_for_detras_del_proxy(self):
        """El hosting termina TLS por delante: sin mirar esta cabecera, todos
        los visitantes compartirían la IP del proxy y una sola clave."""

        class Req:
            headers = {"x-forwarded-for": "200.1.2.3, 10.0.0.1"}
            client = type("C", (), {"host": "10.0.0.1"})()

        assert client_ip(Req()) == "200.1.2.3"

    def test_sin_proxy_usa_la_conexion(self):
        class Req:
            headers = {}
            client = type("C", (), {"host": "190.5.5.5"})()

        assert client_ip(Req()) == "190.5.5.5"


class TestVisitasPublicas:
    def test_pasado_el_limite_deja_de_contar(self, negocio, visitante):
        """Se degrada la métrica, no la experiencia."""
        public_limiter.max_hits = 3
        try:
            respuestas = []
            for _ in range(6):
                respuestas.append(visitante().get(f"/r/{negocio.mesa}").status_code)
        finally:
            public_limiter.max_hits = 60

        assert respuestas == [200] * 6, "la página debe servirse siempre"
        assert metrics.funnel(metrics.load_taps(negocio.id))["visits"] == 3

    def test_el_cliente_llega_a_google_aunque_este_limitado(self, negocio, visitante):
        public_limiter.max_hits = 1
        try:
            visitante().get(f"/r/{negocio.mesa}")
            respuesta = visitante().get(f"/r/{negocio.mesa}/go", follow_redirects=False)
        finally:
            public_limiter.max_hits = 60

        assert respuesta.status_code == 302
        assert respuesta.headers["location"] == negocio.google_url


class TestComentariosPrivados:
    def test_pasado_el_limite_no_dispara_mas_alertas(self, negocio, visitante):
        """Cada comentario despierta el teléfono del dueño."""
        feedback_limiter.max_hits = 2
        try:
            for i in range(5):
                visitante().post(f"/r/{negocio.mesa}/feedback", data={"message": f"queja {i}"})
        finally:
            feedback_limiter.max_hits = 10

        assert len(metrics.load_feedback(negocio.id)) == 2

    def test_responde_normal_para_no_avisar_al_que_abusa(self, negocio, visitante):
        feedback_limiter.max_hits = 1
        try:
            visitante().post(f"/r/{negocio.mesa}/feedback", data={"message": "una"})
            segunda = visitante().post(f"/r/{negocio.mesa}/feedback", data={"message": "dos"})
        finally:
            feedback_limiter.max_hits = 10

        assert segunda.status_code == 200


class TestLogin:
    def _cliente_con_credenciales(self, negocio):
        with SessionLocal() as db:
            business = db.get(Business, negocio.id)
            business.login_email = "dueno@local.cl"
            business.password_hash = hash_password("correcta")
            db.commit()

    def test_bloquea_la_fuerza_bruta(self, negocio):
        self._cliente_con_credenciales(negocio)
        login_limiter.max_hits = 3
        try:
            with TestClient(app) as c:
                codigos = [
                    c.post("/panel/login", data={"email": "dueno@local.cl", "password": "mala"}).status_code
                    for _ in range(5)
                ]
        finally:
            login_limiter.max_hits = 8

        assert codigos[:3] == [401, 401, 401]
        assert codigos[3:] == [429, 429], "tras varios fallos debe cortar"

    def test_bloqueado_no_entra_ni_con_la_correcta(self, negocio):
        """Si no, bastaría con seguir probando hasta acertar."""
        self._cliente_con_credenciales(negocio)
        login_limiter.max_hits = 2
        try:
            with TestClient(app, follow_redirects=False) as c:
                for _ in range(2):
                    c.post("/panel/login", data={"email": "dueno@local.cl", "password": "mala"})
                respuesta = c.post("/panel/login", data={"email": "dueno@local.cl", "password": "correcta"})
        finally:
            login_limiter.max_hits = 8

        assert respuesta.status_code == 429

    def test_entrar_bien_limpia_los_intentos_previos(self, negocio):
        """Equivocarse dos veces no puede dejar castigado a un cliente legítimo."""
        self._cliente_con_credenciales(negocio)
        login_limiter.max_hits = 4
        try:
            with TestClient(app, follow_redirects=False) as c:
                c.post("/panel/login", data={"email": "dueno@local.cl", "password": "mala"})
                c.post("/panel/login", data={"email": "dueno@local.cl", "password": "mala"})
                ok = c.post("/panel/login", data={"email": "dueno@local.cl", "password": "correcta"})
                # Tras el reset vuelve a tener el cupo completo.
                siguientes = [
                    c.post("/panel/login", data={"email": "dueno@local.cl", "password": "mala"}).status_code
                    for _ in range(4)
                ]
        finally:
            login_limiter.max_hits = 8

        assert ok.status_code == 302
        assert siguientes[:3] == [401, 401, 401]
