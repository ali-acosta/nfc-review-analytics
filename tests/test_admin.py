"""Panel de administración del operador.

Es el acceso más peligroso del sistema: un cliente que entra a su panel solo
puede dañarse a sí mismo, mientras que quien entre aquí ve las quejas privadas de
toda la cartera y puede cambiarle el enlace de reseñas a cualquiera. Por eso la
mitad de estos tests son sobre quién NO puede entrar.
"""

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Business, Placement
from app.services import admin_auth
from app.services.auth import hash_password
from sqlalchemy import select

CLAVE = "clave-de-operador-12345"


@pytest.fixture
def admin(monkeypatch):
    """Habilita el panel con una clave conocida."""
    monkeypatch.setattr(
        admin_auth.settings, "admin_password_hash", admin_auth.hash_para_configurar(CLAVE)
    )
    yield


@pytest.fixture
def operador(admin):
    """Un cliente HTTP con la sesión de operador ya iniciada."""
    with TestClient(app) as c:
        respuesta = c.post("/admin/login", data={"password": CLAVE}, follow_redirects=False)
        assert respuesta.status_code == 302
        yield c


class TestSinConfigurarNoExiste:
    """Un panel de administración accesible por olvidar una variable de entorno
    es peor que no tenerlo. Sin credencial, las rutas responden 404: ni siquiera
    confirman que existan."""

    def test_el_login_no_existe(self, monkeypatch):
        monkeypatch.setattr(admin_auth.settings, "admin_password_hash", "")

        with TestClient(app) as c:
            assert c.get("/admin/login").status_code == 404

    def test_el_listado_no_existe(self, monkeypatch):
        monkeypatch.setattr(admin_auth.settings, "admin_password_hash", "")

        with TestClient(app) as c:
            assert c.get("/admin/").status_code == 404

    def test_ninguna_clave_abre_un_panel_deshabilitado(self, monkeypatch):
        monkeypatch.setattr(admin_auth.settings, "admin_password_hash", "")

        with TestClient(app) as c:
            for intento in ("", "admin", "cualquiera"):
                assert c.post("/admin/login", data={"password": intento}).status_code == 404


class TestQuienPuedeEntrar:
    def test_sin_sesion_redirige_al_login(self, admin, negocio):
        with TestClient(app, follow_redirects=False) as c:
            for ruta in ("/admin/", "/admin/nuevo", f"/admin/{negocio.token}"):
                respuesta = c.get(ruta)
                assert respuesta.status_code == 302, ruta
                assert respuesta.headers["location"] == "/admin/login"

    def test_la_clave_incorrecta_no_entra(self, admin):
        with TestClient(app, follow_redirects=False) as c:
            login = c.post("/admin/login", data={"password": "equivocada"})
            listado = c.get("/admin/")

        assert login.status_code == 401
        assert listado.status_code == 302

    def test_la_clave_correcta_entra(self, operador):
        assert operador.get("/admin/").status_code == 200

    def test_cerrar_sesion_saca_del_panel(self, operador):
        operador.post("/admin/logout", follow_redirects=False)

        respuesta = operador.get("/admin/", follow_redirects=False)

        assert respuesta.status_code == 302

    def test_la_sesion_de_un_cliente_no_sirve_para_el_panel(self, admin, negocio):
        """Lo más importante de este archivo: un dueño que entra a SU panel no
        puede llegar al del operador, donde vería a toda la cartera."""
        with SessionLocal() as db:
            business = db.get(Business, negocio.id)
            business.login_email = "dueno@local.cl"
            business.password_hash = hash_password("suclave")
            db.commit()

        with TestClient(app, follow_redirects=False) as c:
            entrada = c.post("/panel/login", data={"email": "dueno@local.cl", "password": "suclave"})
            assert entrada.status_code == 302  # entró a su propio panel

            respuesta = c.get("/admin/")

        assert respuesta.status_code == 302, "la sesión de un cliente no puede abrir el panel del operador"

    def test_quitar_la_credencial_corta_las_sesiones_abiertas(self, operador, monkeypatch):
        """Si se le quita la clave al servidor, las sesiones ya abiertas tienen
        que dejar de servir en el acto, no seguir vivas hasta que caduque la
        cookie."""
        assert operador.get("/admin/").status_code == 200

        monkeypatch.setattr(admin_auth.settings, "admin_password_hash", "")

        assert operador.get("/admin/").status_code == 404

    def test_hay_limite_de_intentos(self, admin):
        from app.services.ratelimit import login_limiter

        login_limiter._hits.clear()
        login_limiter.max_hits = 3
        try:
            with TestClient(app) as c:
                codigos = [
                    c.post("/admin/login", data={"password": "mala"}).status_code for _ in range(5)
                ]
        finally:
            login_limiter.max_hits = 8
            login_limiter._hits.clear()

        assert codigos[:3] == [401, 401, 401]
        assert codigos[3:] == [429, 429]


class TestAltaDeClientes:
    def test_crea_el_negocio_con_sus_placas(self, operador):
        respuesta = operador.post(
            "/admin/nuevo",
            data={
                "nombre": "Panadería Nueva",
                "google_url": "https://g.page/r/CNueva/review",
                "placas": "Mostrador, Vitrina",
                "email": "dueno@panaderia.cl",
                "telegram": "",
            },
        )

        assert respuesta.status_code == 200
        with SessionLocal() as db:
            creado = db.scalar(select(Business).where(Business.name == "Panadería Nueva"))
            placas = db.scalars(select(Placement).where(Placement.business_id == creado.id)).all()

        assert [p.label for p in placas] == ["Mostrador", "Vitrina"]
        assert creado.login_email == "dueno@panaderia.cl"
        assert creado.password_hash, "debe quedar con credenciales para entrar al panel"

    def test_muestra_la_contrasena_una_sola_vez(self, operador):
        """Se guarda cifrada, así que esta pantalla es la única oportunidad de
        copiarla. Tiene que estar en el HTML."""
        html = operador.post(
            "/admin/nuevo",
            data={
                "nombre": "Con Clave",
                "google_url": "https://g.page/r/CX/review",
                "placas": "Barra",
                "email": "x@y.cl",
                "telegram": "",
            },
        ).text

        assert 'class="clave"' in html

    def test_sin_correo_avisa_que_no_hay_credenciales(self, operador):
        html = operador.post(
            "/admin/nuevo",
            data={
                "nombre": "Sin Correo",
                "google_url": "https://g.page/r/CY/review",
                "placas": "Barra",
                "email": "",
                "telegram": "",
            },
        ).text

        assert "Sin correo no se crearon credenciales" in html

    def test_sin_placas_no_crea_nada(self, operador):
        respuesta = operador.post(
            "/admin/nuevo",
            data={"nombre": "Sin Placas", "google_url": "https://g.page/r/CZ/review",
                  "placas": "  ,  ", "email": "", "telegram": ""},
        )

        assert respuesta.status_code == 400
        with SessionLocal() as db:
            assert db.scalar(select(Business).where(Business.name == "Sin Placas")) is None

    def test_avisa_si_el_link_no_parece_de_google(self, operador):
        """Un enlace mal copiado se descubre tarde, cuando el cliente reclama que
        nadie le deja reseñas."""
        html = operador.post(
            "/admin/nuevo",
            data={"nombre": "Link Raro", "google_url": "https://ejemplo.cl/algo",
                  "placas": "Barra", "email": "", "telegram": ""},
        ).text

        assert "relleno" in html or "no se parece" in html


class TestFichaDelCliente:
    def test_editar_cambia_los_datos(self, operador, negocio):
        operador.post(
            f"/admin/{negocio.token}/editar",
            data={"nombre": "Nombre Corregido", "google_url": "https://g.page/r/CBueno/review",
                  "email": "correo@nuevo.cl", "telegram": "555"},
        )

        with SessionLocal() as db:
            b = db.get(Business, negocio.id)

        assert b.name == "Nombre Corregido"
        assert b.google_review_url == "https://g.page/r/CBueno/review"
        assert b.alert_email == "correo@nuevo.cl"
        assert b.telegram_chat_id == "555"

    def test_editar_no_toca_las_placas(self, operador, negocio):
        """Los códigos están grabados en chips pegados a mesas."""
        with SessionLocal() as db:
            antes = sorted(p.token for p in db.scalars(
                select(Placement).where(Placement.business_id == negocio.id)))

        operador.post(
            f"/admin/{negocio.token}/editar",
            data={"nombre": "Otro", "google_url": "https://g.page/r/CC/review",
                  "email": "", "telegram": ""},
        )

        with SessionLocal() as db:
            despues = sorted(p.token for p in db.scalars(
                select(Placement).where(Placement.business_id == negocio.id)))

        assert despues == antes

    def test_agregar_placas(self, operador, negocio):
        operador.post(f"/admin/{negocio.token}/placas", data={"placas": "Terraza, Delivery"})

        with SessionLocal() as db:
            labels = [p.label for p in db.scalars(
                select(Placement).where(Placement.business_id == negocio.id))]

        assert "Terraza" in labels and "Delivery" in labels

    def test_generar_contrasena_nueva(self, operador, negocio):
        with SessionLocal() as db:
            b = db.get(Business, negocio.id)
            b.login_email = "dueno@local.cl"
            b.password_hash = hash_password("vieja")
            db.commit()
            hash_viejo = b.password_hash

        html = operador.post(f"/admin/{negocio.token}/password").text

        with SessionLocal() as db:
            hash_nuevo = db.get(Business, negocio.id).password_hash

        assert 'class="clave"' in html
        assert hash_nuevo != hash_viejo

    def test_no_genera_contrasena_sin_correo(self, operador, negocio):
        """Sin correo no hay a quién entregársela ni con qué usuario entrar."""
        html = operador.post(f"/admin/{negocio.token}/password").text

        assert "Primero asígnale un correo" in html

    def test_rotar_invalida_el_enlace_anterior(self, operador, negocio):
        anterior = negocio.token

        respuesta = operador.post(f"/admin/{anterior}/rotar", follow_redirects=False)

        with SessionLocal() as db:
            nuevo = db.get(Business, negocio.id).dashboard_token

        assert respuesta.status_code == 302
        assert nuevo != anterior
        assert nuevo in respuesta.headers["location"]
        assert operador.get(f"/informe/{anterior}").status_code == 404

    def test_cliente_inexistente_da_404(self, operador):
        assert operador.get("/admin/no-existe-este-token").status_code == 404


class TestElListado:
    def test_muestra_los_clientes_con_sus_cifras(self, operador, negocio):
        from datetime import datetime, timezone

        from tests.conftest import add_visit

        for i in range(10):
            add_visit(negocio.id, negocio.mesa_id, converts=i < 4,
                      when=datetime(2026, 8, 5, 12, tzinfo=timezone.utc))

        html = operador.get("/admin/").text

        assert negocio.nombre in html
        assert "10" in html and "40%" in html

    def test_señala_a_quien_le_falta_algo(self, operador, negocio):
        """El listado tiene que gritar cuáles clientes están mal configurados:
        uno sin canal de alertas no se entera de las quejas, que es la razón por
        la que paga."""
        html = operador.get("/admin/").text

        assert "sin alertas" in html or "sin acceso al panel" in html


class TestNoSeIndexa:
    def test_el_panel_pide_no_ser_indexado(self, operador):
        respuesta = operador.get("/admin/")

        assert respuesta.headers["x-robots-tag"] == "noindex, nofollow"

    def test_el_login_tampoco(self, admin):
        with TestClient(app) as c:
            assert c.get("/admin/login").headers["x-robots-tag"] == "noindex, nofollow"


class TestLaClaveNoViajaEnClaro:
    def test_se_guarda_como_hash(self):
        """La clave del operador no puede quedar en texto plano en el panel del
        hosting: lo que se configura es su hash."""
        h = admin_auth.hash_para_configurar("mi-clave-secreta")

        assert h.startswith("scrypt$")
        assert "mi-clave-secreta" not in h

    def test_verifica_la_correcta_y_rechaza_la_mala(self, monkeypatch):
        monkeypatch.setattr(
            admin_auth.settings, "admin_password_hash", admin_auth.hash_para_configurar("correcta")
        )

        assert admin_auth.verificar("correcta") is True
        assert admin_auth.verificar("incorrecta") is False
        assert admin_auth.verificar("") is False
