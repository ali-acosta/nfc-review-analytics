"""El panel deja de ser una URL secreta y pasa a exigir contraseña. Estos tests
cuidan que nadie entre sin credenciales ni vea los datos de otro comercio."""

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.middleware import BUSINESS_HEADER
from app.models import Business
from app.services.auth import generate_password, hash_password, verify_password

CLAVE = "clave-de-prueba-123"


def _con_credenciales(negocio, email="dueno@local.cl", clave=CLAVE):
    with SessionLocal() as db:
        business = db.get(Business, negocio.id)
        business.login_email = email
        business.password_hash = hash_password(clave)
        db.commit()
    return email, clave


class TestHashDeContrasenas:
    def test_verifica_la_correcta(self):
        assert verify_password("secreta", hash_password("secreta")) is True

    def test_rechaza_la_incorrecta(self):
        assert verify_password("otra", hash_password("secreta")) is False

    def test_dos_hashes_de_la_misma_clave_son_distintos(self):
        """Cada hash lleva su propia sal: si fueran iguales, una filtración
        revelaría qué clientes usan la misma contraseña."""
        assert hash_password("secreta") != hash_password("secreta")

    def test_no_revienta_con_datos_corruptos(self):
        for guardado in ("", "basura", "scrypt$solo-una-parte", "md5$aa$bb"):
            assert verify_password("secreta", guardado) is False

    def test_no_acepta_clave_vacia(self):
        assert verify_password("", hash_password("secreta")) is False

    def test_la_clave_generada_es_usable(self):
        clave = generate_password()

        assert len(clave) >= 12
        assert clave.isalnum()
        assert verify_password(clave, hash_password(clave)) is True


class TestAccesoAlPanel:
    def test_sin_sesion_redirige_al_login(self, negocio):
        with TestClient(app, follow_redirects=False) as c:
            respuesta = c.get("/dashboard/")

        assert respuesta.status_code == 302
        assert respuesta.headers["location"] == "/panel/login"

    def test_con_credenciales_correctas_entra(self, negocio):
        email, clave = _con_credenciales(negocio)

        with TestClient(app, follow_redirects=False) as c:
            login = c.post("/panel/login", data={"email": email, "password": clave})
            panel = c.get("/dashboard/")

        assert login.status_code == 302
        assert login.headers["location"] == "/dashboard/"
        assert panel.status_code == 200

    def test_clave_incorrecta_no_entra(self, negocio):
        email, _ = _con_credenciales(negocio)

        with TestClient(app, follow_redirects=False) as c:
            login = c.post("/panel/login", data={"email": email, "password": "equivocada"})
            panel = c.get("/dashboard/")

        assert login.status_code == 401
        assert panel.status_code == 302

    def test_el_correo_no_distingue_mayusculas(self, negocio):
        _con_credenciales(negocio, email="Dueno@Local.CL")

        with TestClient(app, follow_redirects=False) as c:
            login = c.post("/panel/login", data={"email": "dueno@local.cl", "password": CLAVE})

        assert login.status_code == 302

    def test_el_error_no_revela_si_el_correo_existe(self, negocio):
        """Mensajes distintos permitirían averiguar qué comercios son clientes."""
        _con_credenciales(negocio)

        with TestClient(app) as c:
            inexistente = c.post("/panel/login", data={"email": "nadie@x.cl", "password": "x"})
            existente = c.post("/panel/login", data={"email": "dueno@local.cl", "password": "mala"})

        assert inexistente.status_code == existente.status_code == 401
        assert "incorrectos" in inexistente.text and "incorrectos" in existente.text

    def test_un_negocio_sin_clave_no_puede_entrar(self, negocio):
        """Los clientes creados antes del login quedaron con hash vacío: eso no
        puede convertirse en 'entra cualquiera'. Se prueba con clave vacía y con
        una cualquiera; lo que importa no es el código exacto de rechazo sino
        que ninguna de las dos abra el panel."""
        with SessionLocal() as db:
            business = db.get(Business, negocio.id)
            business.login_email = "sinclave@local.cl"
            business.password_hash = ""
            db.commit()

        for intento in ("", "cualquiera", " "):
            with TestClient(app, follow_redirects=False) as c:
                login = c.post("/panel/login", data={"email": "sinclave@local.cl", "password": intento})
                panel = c.get("/dashboard/")

            assert login.status_code != 302, f"la clave {intento!r} no debía ser aceptada"
            assert panel.status_code == 302, f"la clave {intento!r} dio acceso al panel"

    def test_cerrar_sesion_saca_del_panel(self, negocio):
        email, clave = _con_credenciales(negocio)

        with TestClient(app, follow_redirects=False) as c:
            c.post("/panel/login", data={"email": email, "password": clave})
            c.get("/panel/logout")
            panel = c.get("/dashboard/")

        assert panel.status_code == 302


class TestAislamientoEntreClientes:
    def test_no_se_puede_falsificar_la_identidad_por_cabecera(self, negocio):
        """La cabecera interna la inyecta el middleware. Si se aceptara la que
        manda el cliente, cualquiera vería el panel de cualquier comercio."""
        with SessionLocal() as db:
            otro = Business(name="Ajeno", google_review_url="https://g.page/r/CZ/review")
            db.add(otro)
            db.commit()
            otro_id = otro.id

        with TestClient(app, follow_redirects=False) as c:
            respuesta = c.get("/dashboard/", headers={BUSINESS_HEADER.decode(): str(otro_id)})

        assert respuesta.status_code == 302, "una cabecera falsificada no puede dar acceso"

    def test_la_sesion_manda_sobre_la_cabecera(self, negocio):
        email, clave = _con_credenciales(negocio)
        with SessionLocal() as db:
            otro = Business(
                name="Ajeno",
                google_review_url="https://g.page/r/CZ/review",
                login_email="otro@x.cl",
                password_hash=hash_password("otra"),
            )
            db.add(otro)
            db.commit()
            otro_id = otro.id

        with TestClient(app) as c:
            c.post("/panel/login", data={"email": email, "password": clave})
            respuesta = c.get("/dashboard/", headers={BUSINESS_HEADER.decode(): str(otro_id)})

        assert respuesta.status_code == 200
        assert "Ajeno" not in respuesta.text


class TestElInformeSigueSiendoEnlaceDirecto:
    def test_no_exige_login(self, negocio, cliente):
        """Decisión consciente: el enlace del informe se le manda por correo al
        propio dueño, como el enlace de una factura. Exigir login en cada correo
        mensual haría fricción justo en la pieza que sostiene la retención."""
        respuesta = cliente.get(f"/informe/{negocio.token}")

        assert respuesta.status_code == 200
