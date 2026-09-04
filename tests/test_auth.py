"""El panel deja de ser una URL secreta y pasa a exigir contraseña. Estos tests
cuidan que nadie entre sin credenciales ni vea los datos de otro comercio."""

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.middleware import BUSINESS_HEADER
from app.models import Business
from app.services.auth import generate_password, hash_password, verify_password
from tests.conftest import url_informe

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
            c.post("/panel/logout")
            panel = c.get("/dashboard/")

        assert panel.status_code == 302

    def test_el_panel_cierra_sesion_con_un_formulario(self):
        """Se mira el layout de Dash y no el HTML servido: el panel se arma en
        el navegador desde un JSON, así que un `assert` sobre la respuesta HTTP
        no vería nunca este botón —ni notaría que volvió a ser un enlace—."""
        from dash import html

        from app.dashboard.dash_app import create_dash_app

        def recorrer(nodo):
            yield nodo
            hijos = getattr(nodo, "children", None)
            for hijo in hijos if isinstance(hijos, list) else [hijos] if hijos else []:
                yield from recorrer(hijo)

        nodos = list(recorrer(create_dash_app().layout))
        formularios = [n for n in nodos if isinstance(n, html.Form) and n.action == "/panel/logout"]
        enlaces_logout = [
            n for n in nodos if isinstance(n, html.A) and getattr(n, "href", "") == "/panel/logout"
        ]

        assert len(formularios) == 1, "el panel no ofrece cerrar sesión por POST"
        assert formularios[0].method == "post"
        assert not enlaces_logout, "volvió el logout por GET, que cualquiera puede disparar"

    def test_un_get_no_cierra_la_sesion(self, negocio):
        """Con logout por GET, un `<img src=".../panel/logout">` en cualquier
        página ajena dejaba al dueño fuera de su panel sin que él tocara nada.
        El GET ahora solo muestra el botón."""
        email, clave = _con_credenciales(negocio)

        with TestClient(app, follow_redirects=False) as c:
            c.post("/panel/login", data={"email": email, "password": clave})
            visto = c.get("/panel/logout")
            panel = c.get("/dashboard/")

        assert visto.status_code == 200
        assert panel.status_code == 200, "la sesión no debía cerrarse con un GET"


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
        mensual haría fricción justo en la pieza que sostiene la retención.

        Lo que sí cambió es que el enlace caduca: firma de 90 días y un solo
        mes. Fricción cero para el dueño, y un correo reenviado deja de ser una
        llave permanente a los contactos de sus clientes."""
        respuesta = cliente.get(url_informe(negocio.token))

        assert respuesta.status_code == 200

    def test_el_dueno_lo_abre_desde_su_panel_sin_firma(self, negocio):
        """Dentro del panel el enlace va sin firmar: sería absurdo que a un
        dueño con la sesión abierta se le caducara su propio informe."""
        email, clave = _con_credenciales(negocio)

        with TestClient(app) as c:
            c.post("/panel/login", data={"email": email, "password": clave})
            respuesta = c.get(f"/informe/{negocio.token}")

        assert respuesta.status_code == 200

    def test_sin_firma_y_sin_sesion_no_abre(self, negocio, cliente):
        respuesta = cliente.get(f"/informe/{negocio.token}")

        assert respuesta.status_code == 403

    def test_la_firma_de_un_mes_no_abre_otro(self, negocio, cliente):
        """Un enlace filtrado expone el mes que informaba, no la historia."""
        firma = url_informe(negocio.token, "2026-08").split("firma=")[1]

        respuesta = cliente.get(f"/informe/{negocio.token}?mes=2026-07&firma={firma}")

        assert respuesta.status_code == 403

    def test_la_firma_de_un_negocio_no_abre_la_de_otro(self, negocio, cliente):
        with SessionLocal() as db:
            otro = Business(name="Ajeno", google_review_url="https://g.page/r/CZ/review")
            db.add(otro)
            db.commit()
            token_ajeno = otro.dashboard_token

        firma = url_informe(negocio.token, "2026-08").split("firma=")[1]

        respuesta = cliente.get(f"/informe/{token_ajeno}?mes=2026-08&firma={firma}")

        assert respuesta.status_code == 403

    def test_una_firma_vencida_no_abre(self, negocio, cliente, monkeypatch):
        from app.services import enlaces

        monkeypatch.setattr(enlaces, "VIGENCIA_INFORME", -1)
        respuesta = cliente.get(url_informe(negocio.token, "2026-08"))

        assert respuesta.status_code == 403

    def test_el_enlace_vencido_no_delata_si_el_token_existe(self, negocio, cliente):
        """Misma respuesta para un token real y uno inventado: si el real diera
        403 y el falso 404, la página serviría para descubrir clientes."""
        real = cliente.get(f"/informe/{negocio.token}")
        falso = cliente.get("/informe/no-existe-esto")

        assert real.status_code == falso.status_code == 403
