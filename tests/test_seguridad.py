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
