"""Lo que hace falta para operar el servicio: saber si está sano, dejar rastro
de lo que pasa y poder sacar los datos."""

import logging
from datetime import datetime, timezone

import pandas as pd

from app.services import inbox, metrics
from tests.conftest import add_visit


class TestChequeosDeSalud:
    def test_health_no_toca_la_base(self, cliente):
        """Si la base parpadea, el hosting no debe reiniciar un proceso sano."""
        respuesta = cliente.get("/health")

        assert respuesta.status_code == 200
        assert respuesta.text == "ok"

    def test_ready_confirma_que_la_base_responde(self, cliente):
        respuesta = cliente.get("/health/ready")

        assert respuesta.status_code == 200
        assert respuesta.text == "listo"

    def test_ready_avisa_si_la_base_no_responde(self, cliente, monkeypatch):
        """Un proceso vivo que no puede consultar no sirve, y sin esto ese
        fallo pasa inadvertido."""
        import app.main as main

        def base_caida():
            raise RuntimeError("conexión rechazada")

        monkeypatch.setattr(main, "SessionLocal", base_caida)
        respuesta = cliente.get("/health/ready")

        assert respuesta.status_code == 503
        assert "inaccesible" in respuesta.text


class TestLogs:
    def test_el_formato_incluye_hora_nivel_y_origen(self):
        from app.logging_config import FORMATO

        for pieza in ("%(asctime)s", "%(levelname)", "%(name)s", "%(message)s"):
            assert pieza in FORMATO

    def test_no_ahoga_los_loggers_ya_creados(self):
        """uvicorn y sqlalchemy crean los suyos antes de que esto corra."""
        import inspect

        from app import logging_config

        fuente = inspect.getsource(logging_config.configure_logging)
        assert '"disable_existing_loggers": False' in fuente

    def test_sqlalchemy_no_escupe_cada_consulta(self):
        from app.logging_config import configure_logging

        configure_logging("INFO")

        assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING


class TestExportacion:
    def test_saca_visitas_y_quejas(self, negocio, tmp_path):
        from app.database import SessionLocal
        from app.models import Business
        from scripts.export_data import exportar

        add_visit(negocio.id, negocio.mesa_id, converts=True)
        with SessionLocal() as db:
            business = db.get(Business, negocio.id)
            archivos = exportar(business, tmp_path)

        assert len(archivos) == 2
        nombres = " ".join(a.name for a in archivos)
        assert "visitas" in nombres and "quejas" in nombres
        assert all(a.exists() for a in archivos)

    def test_el_csv_se_abre_bien_en_excel(self, negocio, tmp_path):
        """utf-8-sig: sin el BOM, Excel en Windows destroza los acentos."""
        from app.database import SessionLocal
        from app.models import Business, Feedback
        from scripts.export_data import exportar

        with SessionLocal() as db:
            db.add(
                Feedback(
                    business_id=negocio.id,
                    placement_id=negocio.mesa_id,
                    message="La atención fue pésima en el mesón",
                )
            )
            db.commit()
            business = db.get(Business, negocio.id)
            archivos = exportar(business, tmp_path)

        quejas = next(a for a in archivos if "quejas" in a.name)
        contenido = quejas.read_bytes()

        assert contenido.startswith(b"\xef\xbb\xbf"), "falta el BOM que Excel necesita"
        assert "pésima" in contenido.decode("utf-8-sig")


class TestFechasCoherentes:
    def test_las_dos_fechas_de_una_queja_van_en_la_misma_hora(self, negocio):
        """Mezclar husos en la misma tabla confunde a quien la exporte."""
        from app.database import SessionLocal
        from app.models import Feedback

        cuando = datetime(2026, 8, 15, 23, 30, tzinfo=timezone.utc)
        with SessionLocal() as db:
            f = Feedback(
                business_id=negocio.id,
                placement_id=negocio.mesa_id,
                message="x",
                created_at=cuando,
                resolved_at=cuando,
            )
            db.add(f)
            db.commit()

        fila = metrics.load_feedback(negocio.id).iloc[0]

        assert fila["created_at"] == fila["resolved_at"]
        # 23:30 UTC son las 19:30 en Chile: ambas deben estar convertidas.
        assert fila["created_at"].hour == 19

    def test_una_queja_pendiente_no_rompe_la_conversion(self, negocio):
        from app.database import SessionLocal
        from app.models import Feedback

        with SessionLocal() as db:
            db.add(Feedback(business_id=negocio.id, placement_id=negocio.mesa_id, message="x"))
            db.commit()

        fila = metrics.load_feedback(negocio.id).iloc[0]

        assert pd.isna(fila["resolved_at"])


class TestLaDemoQuedaUsable:
    def test_el_seed_deja_credenciales_para_entrar_al_panel(self):
        """El README publica demo@cafe.cl / demo1234. Si el seed no las crea,
        existen solo en la base de quien las tecleó una vez y cualquiera que clone
        el repositorio se queda afuera."""
        from fastapi.testclient import TestClient

        from app.main import app
        from scripts.seed_demo_business import DEMO_EMAIL, DEMO_PASSWORD, seed

        seed()

        with TestClient(app, follow_redirects=False) as c:
            login = c.post("/panel/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})

        assert login.status_code == 302
        assert login.headers["location"] == "/dashboard/"


class TestRotacionDelEnlaceDelInforme:
    def test_rotar_invalida_el_enlace_anterior(self, negocio):
        """El enlace del informe no pide clave, a propósito. El precio es que un
        correo reenviado lo deja vivo para siempre; esto es la forma de cortarlo."""
        from fastapi.testclient import TestClient

        from app.database import SessionLocal
        from app.main import app
        from app.models import Business
        from scripts.new_client import rotar_token

        anterior = negocio.token
        rotar_token(anterior)

        with SessionLocal() as db:
            nuevo = db.get(Business, negocio.id).dashboard_token

        assert nuevo != anterior
        with TestClient(app) as c:
            assert c.get(f"/informe/{anterior}").status_code == 404
            assert c.get(f"/informe/{nuevo}").status_code == 200
