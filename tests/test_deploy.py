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
