"""Lo que tiene que seguir siendo cierto para que el despliegue no falle."""

import re
from pathlib import Path

from sqlalchemy import create_engine

RAIZ = Path(__file__).resolve().parent.parent


class TestSalud:
    def test_health_responde_sin_tocar_la_base(self, cliente):
        respuesta = cliente.get("/health")

        assert respuesta.status_code == 200
        assert respuesta.text == "ok"

    def test_render_apunta_al_health_correcto(self):
        blueprint = (RAIZ / "render.yaml").read_text(encoding="utf-8")

        assert "healthCheckPath: /health" in blueprint

    def test_render_escucha_donde_corresponde(self):
        """Sin 0.0.0.0 y sin $PORT el contenedor queda inalcanzable."""
        blueprint = (RAIZ / "render.yaml").read_text(encoding="utf-8")

        assert "--host 0.0.0.0" in blueprint
        assert "--port $PORT" in blueprint


class TestBaseDeDatos:
    def test_el_driver_de_postgres_esta_disponible(self):
        """Cambiar DATABASE_URL a Postgres no debe fallar por falta de driver."""
        engine = create_engine("postgresql+psycopg://u:p@localhost:5432/db")

        assert engine.dialect.driver == "psycopg"

    def test_psycopg_esta_declarado(self):
        requisitos = (RAIZ / "requirements.txt").read_text(encoding="utf-8")

        assert "psycopg" in requisitos

    def test_connect_args_de_sqlite_no_se_aplican_a_postgres(self):
        """check_same_thread solo existe en SQLite: pasárselo a Postgres
        reventaría la conexión en producción."""
        codigo = (RAIZ / "app" / "database.py").read_text(encoding="utf-8")

        assert 'startswith("sqlite")' in codigo


class TestCookieDeSesion:
    def test_no_es_secure_en_desarrollo(self, negocio, visitante):
        """Con BASE_URL http, una cookie Secure se descartaría y cada visita
        parecería un visitante nuevo, inflando las métricas."""
        respuesta = visitante().get(f"/r/{negocio.mesa}")

        cookie = respuesta.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "Secure" not in cookie

    def test_se_vuelve_secure_con_https(self, negocio, visitante, monkeypatch):
        from app.routers import redirect

        monkeypatch.setattr(redirect.settings, "base_url", "https://reseñas.cl")
        respuesta = visitante().get(f"/r/{negocio.mesa}")

        assert "Secure" in respuesta.headers["set-cookie"]


class TestConfiguracionDeEjemplo:
    def test_env_example_documenta_todas_las_variables(self):
        """Una variable que exista en Settings pero no en .env.example es una
        que nadie va a configurar en el servidor."""
        from app.config import Settings

        ejemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
        declaradas = {n.upper() for n in Settings.model_fields}
        documentadas = set(re.findall(r"^([A-Z_]+)=", ejemplo, re.MULTILINE))

        assert declaradas <= documentadas, f"faltan en .env.example: {declaradas - documentadas}"


class TestLosCanalesDeAvisoLleganAProduccion:
    """Una variable que la app lee pero que el despliegue nunca pasa es un canal
    de aviso que no existe en producción, aunque el código esté perfecto.

    Pasó exactamente eso con el correo: `send_email` estaba escrito y probado,
    pero ni el workflow mensual ni render.yaml pasaban las variables SMTP, así
    que en producción se saltaba el envío en silencio."""

    def _campos_smtp(self):
        from app.config import Settings

        return {n.upper() for n in Settings.model_fields if n.startswith("smtp_")}

    def test_el_envio_mensual_recibe_las_credenciales_de_correo(self):
        workflow = (RAIZ / ".github" / "workflows" / "informe-mensual.yml").read_text(encoding="utf-8")

        # SMTP_PORT tiene default razonable (587) y no necesita ir como secret.
        faltan = {c for c in self._campos_smtp() - {"SMTP_PORT"} if c not in workflow}

        assert not faltan, f"el workflow mensual no pasa: {faltan}"

    def test_el_servidor_web_recibe_las_credenciales_de_correo(self):
        """La alerta de queja sale del servidor web, no del workflow: es la que
        llega en el momento y la que sostiene la suscripción."""
        blueprint = (RAIZ / "render.yaml").read_text(encoding="utf-8")

        faltan = {c for c in self._campos_smtp() - {"SMTP_PORT"} if c not in blueprint}

        assert not faltan, f"render.yaml no declara: {faltan}"

    def test_una_variable_vacia_no_tumba_el_arranque(self):
        """Un secret que no existe llega como cadena vacía. Sin env_ignore_empty,
        SMTP_PORT='' revienta al convertir a entero y se cae el proceso entero."""
        import os
        from app.config import Settings

        previo = os.environ.get("SMTP_PORT")
        os.environ["SMTP_PORT"] = ""
        try:
            assert Settings().smtp_port == 587
        finally:
            if previo is None:
                os.environ.pop("SMTP_PORT", None)
            else:
                os.environ["SMTP_PORT"] = previo


class TestRespaldos:
    """El historial de toques de un cliente no se puede reconstruir: son personas
    que pasaron por su local y ya no están. Además es con lo que se le factura."""

    def _workflow(self) -> str:
        return (RAIZ / ".github" / "workflows" / "respaldo.yml").read_text(encoding="utf-8")

    def test_hay_un_respaldo_agendado(self):
        import re

        cron = re.search(r'cron:\s*"([^"]+)"', self._workflow()).group(1)
        minuto, hora, dia_mes, mes, dia_semana = cron.split()

        assert dia_mes == "*" and mes == "*", "debe correr por día de la semana, no del mes"
        assert dia_semana.isdigit(), "debe fijar un día de la semana"

    def test_el_respaldo_recibe_la_base_de_produccion(self):
        """Sin DATABASE_URL exportaría una base vacía y el respaldo sería un
        archivo sin nada, que es peor que no tenerlo: da falsa tranquilidad."""
        assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in self._workflow()

    def test_el_respaldo_se_guarda_en_algun_lado(self):
        workflow = self._workflow()

        assert "upload-artifact" in workflow
        assert "retention-days" in workflow

    def test_exporta_todos_los_clientes_y_no_uno(self):
        assert "--todos" in self._workflow()


class TestLaFirmaDeLosEnlacesLlegaAProduccion:
    """El correo mensual y el servidor web tienen que firmar con la MISMA clave.

    Es el mismo error que ya se cometió con SMTP, con otra cara: el código
    perfecto y la variable que nunca llega. Si el workflow mensual firma con una
    clave distinta a la del servidor, cada cliente recibe el día 1 un correo con
    un enlace que su propio informe rechaza, y el fallo aparece en producción,
    una vez al mes, en la pieza que sostiene la suscripción."""

    def test_el_envio_mensual_recibe_la_clave_de_firma(self):
        workflow = (RAIZ / ".github" / "workflows" / "informe-mensual.yml").read_text(encoding="utf-8")

        assert "SESSION_SECRET: ${{ secrets.SESSION_SECRET }}" in workflow

    def test_el_servidor_web_recibe_la_clave_de_firma(self):
        blueprint = (RAIZ / "render.yaml").read_text(encoding="utf-8")

        assert "SESSION_SECRET" in blueprint


class TestLaRetencionDeContactosEstaAgendada:
    """Un borrado de datos personales que hay que acordarse de correr a mano no
    es una política de retención: es una intención."""

    def _workflow(self) -> str:
        return (RAIZ / ".github" / "workflows" / "informe-mensual.yml").read_text(encoding="utf-8")

    def test_corre_sola_todos_los_meses(self):
        assert "scripts.anonimizar_contactos" in self._workflow()

    def test_corre_de_verdad_y_no_en_simulacion(self):
        """El script simula por defecto a propósito. Agendado sin --aplicar
        quedaría un job en verde que no borra nada."""
        workflow = self._workflow()
        linea = [l for l in workflow.splitlines() if "scripts.anonimizar_contactos" in l][0]

        assert "--aplicar" in linea

    def test_recibe_la_base_de_produccion(self):
        assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in self._workflow()


class TestLaSesionDelPanelNoDuraDemasiado:
    def test_caduca_en_una_semana(self):
        """El panel se deja abierto en el computador del mostrador del local.
        Catorce días (el valor por defecto de Starlette) es demasiado."""
        from app.main import SESION_MAX_AGE

        assert SESION_MAX_AGE == 7 * 24 * 60 * 60

    def test_la_cookie_sale_con_ese_vencimiento(self, negocio):
        """Sin seguir la redirección: la cookie viaja en el 302 del login."""
        from fastapi.testclient import TestClient

        from app.database import SessionLocal
        from app.main import app
        from app.models import Business
        from app.services.auth import hash_password

        with SessionLocal() as db:
            business = db.get(Business, negocio.id)
            business.login_email = "duena@local.cl"
            business.password_hash = hash_password("clave-de-prueba-123")
            db.commit()

        with TestClient(app, follow_redirects=False) as c:
            respuesta = c.post(
                "/panel/login", data={"email": "duena@local.cl", "password": "clave-de-prueba-123"}
            )

        assert "Max-Age=604800" in respuesta.headers["set-cookie"]
