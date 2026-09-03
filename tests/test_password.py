"""El dueño cambia su propia contraseña sin depender de que el operador corra
un comando."""

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Business
from app.services.auth import hash_password, verify_password

ACTUAL = "clave-inicial"


def _entrar(negocio, clave=ACTUAL):
    with SessionLocal() as db:
        business = db.get(Business, negocio.id)
        business.login_email = "dueno@local.cl"
        business.password_hash = hash_password(clave)
        db.commit()
    cliente = TestClient(app, follow_redirects=False)
    cliente.post("/panel/login", data={"email": "dueno@local.cl", "password": clave})
    return cliente


def _hash_actual(negocio) -> str:
    with SessionLocal() as db:
        return db.get(Business, negocio.id).password_hash


class TestAcceso:
    def test_sin_sesion_manda_al_login(self, negocio):
        with TestClient(app, follow_redirects=False) as c:
            respuesta = c.get("/panel/password")

        assert respuesta.status_code == 302
        assert respuesta.headers["location"] == "/panel/login"

    def test_sin_sesion_tampoco_puede_cambiarla(self, negocio):
        with TestClient(app, follow_redirects=False) as c:
            respuesta = c.post(
                "/panel/password",
                data={"actual": ACTUAL, "nueva": "otra-clave-larga", "repetir": "otra-clave-larga"},
            )

        assert respuesta.status_code == 302

    def test_con_sesion_muestra_el_formulario(self, negocio):
        respuesta = _entrar(negocio).get("/panel/password")

        assert respuesta.status_code == 200
        assert "Cambiar contraseña" in respuesta.text


class TestCambio:
    def test_cambia_la_contrasena(self, negocio):
        cliente = _entrar(negocio)

        respuesta = cliente.post(
            "/panel/password",
            data={"actual": ACTUAL, "nueva": "nueva-clave-99", "repetir": "nueva-clave-99"},
        )

        assert respuesta.status_code == 200
        assert verify_password("nueva-clave-99", _hash_actual(negocio))
        assert not verify_password(ACTUAL, _hash_actual(negocio))

    def test_la_nueva_sirve_para_entrar(self, negocio):
        cliente = _entrar(negocio)
        cliente.post(
            "/panel/password",
            data={"actual": ACTUAL, "nueva": "nueva-clave-99", "repetir": "nueva-clave-99"},
        )

        with TestClient(app, follow_redirects=False) as c:
            vieja = c.post("/panel/login", data={"email": "dueno@local.cl", "password": ACTUAL})
            nueva = c.post("/panel/login", data={"email": "dueno@local.cl", "password": "nueva-clave-99"})

        assert vieja.status_code == 401
        assert nueva.status_code == 302

    def test_exige_la_contrasena_actual(self, negocio):
        """Si alguien deja el panel abierto en el mostrador, no debería poder
        quedarse con la cuenta."""
        cliente = _entrar(negocio)
        antes = _hash_actual(negocio)

        respuesta = cliente.post(
            "/panel/password",
            data={"actual": "no-es-esta", "nueva": "nueva-clave-99", "repetir": "nueva-clave-99"},
        )

        assert respuesta.status_code == 400
        assert _hash_actual(negocio) == antes

    def test_rechaza_si_no_coinciden(self, negocio):
        cliente = _entrar(negocio)
        antes = _hash_actual(negocio)

        respuesta = cliente.post(
            "/panel/password",
            data={"actual": ACTUAL, "nueva": "nueva-clave-99", "repetir": "otra-distinta-99"},
        )

        assert respuesta.status_code == 400
        assert "no coinciden" in respuesta.text
        assert _hash_actual(negocio) == antes

    def test_rechaza_una_demasiado_corta(self, negocio):
        cliente = _entrar(negocio)

        respuesta = cliente.post(
            "/panel/password", data={"actual": ACTUAL, "nueva": "corta", "repetir": "corta"}
        )

        assert respuesta.status_code == 400
        assert _hash_actual(negocio) != hash_password("corta")

    def test_rechaza_repetir_la_misma(self, negocio):
        cliente = _entrar(negocio)

        respuesta = cliente.post(
            "/panel/password", data={"actual": ACTUAL, "nueva": ACTUAL, "repetir": ACTUAL}
        )

        assert respuesta.status_code == 400
        assert "distinta" in respuesta.text
