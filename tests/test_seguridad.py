"""La landing es pública: la abre gente desconocida desde su teléfono."""

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Business
from app.services.auth import hash_password


class TestCabeceras:
    def test_la_landing_las_lleva_todas(self, negocio, visitante):
        cabeceras = visitante().get(f"/r/{negocio.mesa}").headers

        assert cabeceras["x-content-type-options"] == "nosniff"
        assert cabeceras["x-frame-options"] == "DENY"
        assert "content-security-policy" in cabeceras

    def test_el_referer_no_filtra_el_token_a_google(self, negocio, visitante):
        """Sin esta política, al mandar al cliente a Google el navegador
        enviaría como referente la URL completa, con el token de la placa."""
        cabeceras = visitante().get(f"/r/{negocio.mesa}").headers

        assert cabeceras["referrer-policy"] == "strict-origin-when-cross-origin"

    def test_la_redireccion_a_google_tambien_va_protegida(self, negocio, visitante):
        respuesta = visitante().get(f"/r/{negocio.mesa}/go", follow_redirects=False)

        assert respuesta.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    def test_la_csp_publica_prohibe_scripts_en_linea(self, negocio, visitante):
        csp = visitante().get(f"/r/{negocio.mesa}").headers["content-security-policy"]

        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp
        assert "frame-ancestors 'none'" in csp

    def test_el_panel_queda_fuera_de_la_csp_estricta(self, negocio):
        """Dash genera sus propios scripts en línea; una CSP estricta lo
        rompería. A cambio, ahí ya hace falta iniciar sesión."""
        with SessionLocal() as db:
            business = db.get(Business, negocio.id)
            business.login_email = "dueno@local.cl"
            business.password_hash = hash_password("clave")
            db.commit()

        with TestClient(app) as c:
            c.post("/panel/login", data={"email": "dueno@local.cl", "password": "clave"})
            respuesta = c.get("/dashboard/")

        assert respuesta.status_code == 200
        assert "content-security-policy" not in respuesta.headers
        assert respuesta.headers["x-content-type-options"] == "nosniff"


class TestLandingSinScriptEnLinea:
    def test_el_javascript_esta_en_un_archivo_aparte(self, negocio, visitante):
        """Si vuelve a haber un <script> embebido, la CSP lo bloquearía en
        silencio y el canal privado dejaría de abrirse."""
        html = visitante().get(f"/r/{negocio.mesa}").text

        assert '<script src="/static/landing.js">' in html
        assert "addEventListener" not in html, "el JS no puede estar embebido en el HTML"

    def test_el_archivo_se_sirve(self, cliente):
        respuesta = cliente.get("/static/landing.js")

        assert respuesta.status_code == 200
        assert "private-toggle" in respuesta.text


class TestNoIndexado:
    """La URL de una placa es para quien está sentado en esa mesa.

    Si un cliente comparte el enlace y Google lo indexa, empiezan a llegar
    visitantes de escritorio desde el buscador: navegadores reales, que no se
    filtran como bots, inflando las visitas de esa placa y hundiendo la
    conversión que el negocio paga por medir."""

    def test_la_landing_pide_no_ser_indexada(self, negocio, visitante):
        respuesta = visitante().get(f"/r/{negocio.mesa}")

        assert respuesta.headers["x-robots-tag"] == "noindex, nofollow"
        assert 'name="robots"' in respuesta.text

    def test_la_pagina_de_gracias_tampoco(self, negocio, visitante):
        telefono = visitante()
        respuesta = telefono.post(f"/r/{negocio.mesa}/feedback", data={"message": "algo"})

        assert 'name="robots"' in respuesta.text


class TestHSTS:
    def test_no_se_envia_en_desarrollo(self, negocio, visitante):
        """Sobre http, mandarla obligaría al navegador a recordar que localhost
        usa TLS y rompería el desarrollo por meses."""
        respuesta = visitante().get(f"/r/{negocio.mesa}")

        assert "strict-transport-security" not in respuesta.headers

    def test_se_envia_sobre_https(self, negocio, visitante, monkeypatch):
        from app import middleware

        monkeypatch.setattr(middleware.settings, "base_url", "https://resenas.cl")
        respuesta = visitante().get(f"/r/{negocio.mesa}")

        assert "max-age=31536000" in respuesta.headers["strict-transport-security"]


class TestElLoginNoDelataQuienEsCliente:
    def test_cuesta_lo_mismo_exista_o_no_el_correo(self, negocio, monkeypatch):
        """El mensaje de error ya es único, pero sin verificar siempre contra un
        hash el `or` corta antes de llegar a scrypt y la respuesta vuelve mucho
        más rápido para un correo que no existe. Cronometrando se averigua qué
        comercios son clientes.

        Se cuentan llamadas y no milisegundos: medir tiempo en un test es
        frágil, contar es exacto."""
        from app.routers import auth
        from app.services.auth import hash_password

        with SessionLocal() as db:
            business = db.get(Business, negocio.id)
            business.login_email = "dueno@local.cl"
            business.password_hash = hash_password("correcta")
            db.commit()

        llamadas = []
        original = auth.verify_password
        monkeypatch.setattr(auth, "verify_password", lambda *a: llamadas.append(1) or original(*a))

        with TestClient(app) as c:
            c.post("/panel/login", data={"email": "nadie@x.cl", "password": "x"})
            inexistente = len(llamadas)
            llamadas.clear()
            c.post("/panel/login", data={"email": "dueno@local.cl", "password": "mala"})
            existente = len(llamadas)

        assert inexistente == existente == 1, "ambos casos deben pagar el mismo costo de cómputo"
