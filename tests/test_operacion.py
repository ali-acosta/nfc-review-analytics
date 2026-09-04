"""Lo que hace falta para operar el servicio: saber si está sano, dejar rastro
de lo que pasa y poder sacar los datos."""

import logging
from datetime import datetime, timezone

import pandas as pd

from app.services import inbox, metrics
from tests.conftest import add_visit, url_informe


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
            # El token viejo ya no existe, así que ni siquiera con una firma
            # recién emitida para él abre nada.
            assert c.get(url_informe(anterior)).status_code == 404
            assert c.get(url_informe(nuevo)).status_code == 200


class TestEdicionDeClientes:
    """Corregir el enlace de reseñas era lo único frecuente que obligaba a
    escribir Python contra la base. Un cliente se da de alta antes de tener su
    link definitivo de Google, o el dueño rehace su ficha y el link cambia."""

    def _business(self, negocio_id):
        from app.database import SessionLocal
        from app.models import Business

        with SessionLocal() as db:
            return db.get(Business, negocio_id)

    def test_cambia_el_link_de_google(self, negocio):
        from scripts.new_client import editar

        editar(negocio.token, "", "https://g.page/r/CNuevo123/review", "", "")

        assert self._business(negocio.id).google_review_url == "https://g.page/r/CNuevo123/review"

    def test_cambia_varios_campos_a_la_vez(self, negocio):
        from scripts.new_client import editar

        editar(negocio.token, "Nombre Nuevo", "", "dueno@nuevo.cl", "123456")

        b = self._business(negocio.id)
        assert b.name == "Nombre Nuevo"
        assert b.alert_email == "dueno@nuevo.cl"
        assert b.telegram_chat_id == "123456"

    def test_no_toca_lo_que_no_se_pidio_cambiar(self, negocio):
        """Editar el correo no puede alterar el link de Google ni las placas: la
        URL de una placa está grabada en un chip pegado a una mesa."""
        from app.database import SessionLocal
        from app.models import Placement
        from sqlalchemy import select
        from scripts.new_client import editar

        antes_url = self._business(negocio.id).google_review_url
        with SessionLocal() as db:
            antes_tokens = sorted(
                p.token for p in db.scalars(select(Placement).where(Placement.business_id == negocio.id))
            )

        editar(negocio.token, "", "", "otro@correo.cl", "")

        with SessionLocal() as db:
            despues_tokens = sorted(
                p.token for p in db.scalars(select(Placement).where(Placement.business_id == negocio.id))
            )
        assert self._business(negocio.id).google_review_url == antes_url
        assert despues_tokens == antes_tokens

    def test_sin_campos_no_hace_nada_y_explica(self, negocio):
        import pytest

        from scripts.new_client import editar

        with pytest.raises(SystemExit) as salida:
            editar(negocio.token, "", "", "", "")

        assert "al menos un campo" in str(salida.value)

    def test_token_inexistente_no_revienta(self):
        import pytest

        from scripts.new_client import editar

        with pytest.raises(SystemExit) as salida:
            editar("no-existe", "Algo", "", "", "")

        assert "No existe un cliente" in str(salida.value)

    def test_asigna_el_correo_del_panel_si_no_tenia(self, negocio):
        """Un cliente creado sin correo no podía entrar al panel. Al asignarle uno
        de alertas, se aprovecha de habilitarle el acceso."""
        from scripts.new_client import editar

        editar(negocio.token, "", "", "primero@correo.cl", "")

        assert self._business(negocio.id).login_email == "primero@correo.cl"


class TestHojaDePlacas:
    """La hoja se le manda a quien fabrica las placas. Tiene que funcionar sola,
    sin servidor, y avisar cuando las URLs todavía son provisionales: imprimir
    con una dirección temporal es el único error irreversible del proyecto."""

    def _hoja(self, negocio_id):
        from app.database import SessionLocal
        from app.models import Business, Placement
        from sqlalchemy import select
        from scripts.qr_sheet import construir

        with SessionLocal() as db:
            business = db.get(Business, negocio_id)
            placements = db.scalars(
                select(Placement).where(Placement.business_id == negocio_id).order_by(Placement.id)
            ).all()
            return construir(business, placements)

    def test_lleva_una_tarjeta_por_placa_con_su_qr(self, negocio):
        html = self._hoja(negocio.id)

        assert html.count("data:image/png;base64,") == 2, "una imagen por placa"
        assert "Mesa 1" in html and "Mesón" in html

    def test_los_qr_van_embebidos_y_no_enlazados(self, negocio):
        """Si el QR se sirviera desde el servidor, la hoja dejaría de funcionar al
        mandarla por correo o al apagar la app, justo cuando el proveedor la abre."""
        html = self._hoja(negocio.id)

        assert "<img" in html
        assert "/qr.png" not in html, "el QR no puede depender del servidor"

    def test_no_usa_javascript(self, negocio):
        """Tiene que imprimir igual desde cualquier navegador y desde WeasyPrint."""
        assert "<script" not in self._hoja(negocio.id).lower()

    def test_avisa_de_no_imprimir_con_una_url_provisional(self, negocio):
        """El aviso es lo que separa una prueba de una caja de placas inservibles."""
        html = self._hoja(negocio.id)

        assert "NO IMPRIMIR" in html

    def test_sin_aviso_cuando_la_url_es_definitiva(self, negocio, monkeypatch):
        from scripts import qr_sheet

        monkeypatch.setattr(qr_sheet.settings, "base_url", "https://misresenas.cl")
        html = self._hoja(negocio.id)

        assert "NO IMPRIMIR" not in html

    def test_muestra_la_url_en_texto_para_grabar_el_chip(self, negocio):
        """Quien graba el chip NFC necesita leer la URL, no escanear el QR."""
        html = self._hoja(negocio.id)

        assert f"/r/{negocio.mesa}" in html


class TestAptaParaImprimir:
    """El criterio se asume provisional salvo prueba en contrario. Una URL
    desconocida tiene que hacer saltar el aviso, no pasar de largo: la placa queda
    pegada a una mesa y su URL no se puede cambiar nunca."""

    def test_solo_https_en_dominio_propio_sin_puerto(self):
        import pytest

        from scripts.qr_sheet import es_apta_para_imprimir

        aptas = ["https://misresenas.cl", "https://www.misresenas.cl/"]
        no_aptas = [
            "http://misresenas.cl",          # sin cifrar
            "http://localhost:8000",         # desarrollo
            "http://127.0.0.1:8000",         # desarrollo
            "http://192.168.100.7:8000",     # red local
            "http://testserver",             # entorno de pruebas
            "https://algo.onrender.com",     # hosting temporal
            "https://misresenas.cl:8000",    # nadie imprime un puerto
        ]

        for url in aptas:
            assert es_apta_para_imprimir(url.rstrip("/")) is True, url
        for url in no_aptas:
            assert es_apta_para_imprimir(url) is False, url


class TestLoQueQuedaImpresoEnLaPlaca:
    """La línea punteada es el corte: todo lo de adentro termina pegado a la mesa
    de un local, a la vista de sus clientes.

    La etiqueta ("Caja", "Mesa 5") y la URL son datos de fabricación: sirven a
    quien graba el chip y a quien instala. Impresos en la placa son ruido para el
    cliente y dejan a la vista una dirección que nadie va a teclear. Van afuera
    del recorte a propósito, y este test existe para que no se vuelvan a colar.
    """

    def _texto_de_la_placa(self, negocio_id) -> str:
        """El texto que de verdad se imprimiría, sin atributos ni etiquetas."""
        import re

        from app.database import SessionLocal
        from app.models import Business, Placement
        from sqlalchemy import select
        from scripts.qr_sheet import construir

        with SessionLocal() as db:
            business = db.get(Business, negocio_id)
            placements = db.scalars(
                select(Placement).where(Placement.business_id == negocio_id).order_by(Placement.id)
            ).all()
            html = construir(business, placements)

        bloque = re.search(r'<div class="placa">(.*?)</div>', html, re.S).group(1)
        # alt y src no se imprimen.
        sin_atributos = re.sub(r'(alt|src)="[^"]*"', "", bloque)
        return " ".join(re.sub(r"<[^>]+>", " ", sin_atributos).split())

    def test_la_url_no_se_imprime_en_la_placa(self, negocio):
        texto = self._texto_de_la_placa(negocio.id)

        assert "http" not in texto
        assert negocio.mesa not in texto

    def test_la_etiqueta_interna_no_se_imprime_en_la_placa(self, negocio):
        """"Mesa 1" le dice algo al que instala, nada al cliente que se sienta."""
        texto = self._texto_de_la_placa(negocio.id)

        assert "Mesa 1" not in texto

    def test_la_placa_si_lleva_la_llamada_a_la_accion(self, negocio):
        texto = self._texto_de_la_placa(negocio.id)

        assert "¿Cómo estuvo tu visita?" in texto

    def test_la_ficha_de_fabricacion_conserva_lo_que_hace_falta(self, negocio):
        """Fuera del recorte, pero presente: sin la URL nadie puede grabar el chip
        y sin la etiqueta nadie sabe dónde va cada placa."""
        from app.database import SessionLocal
        from app.models import Business, Placement
        from sqlalchemy import select
        from scripts.qr_sheet import construir

        with SessionLocal() as db:
            business = db.get(Business, negocio.id)
            placements = db.scalars(
                select(Placement).where(Placement.business_id == negocio.id).order_by(Placement.id)
            ).all()
            html = construir(business, placements)

        assert f"/r/{negocio.mesa}" in html
        assert "Mesa 1" in html
        assert "grabar en el chip" in html
