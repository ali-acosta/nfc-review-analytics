"""Logo y mensaje propios en la landing.

Es lo que hace que el cliente del local vea la página de SU negocio y no la de
una plataforma cualquiera. Para el dueño que paga, esa diferencia es buena parte
de lo que está comprando.

El logo se guarda en la base y no como archivo porque el hosting no tiene disco
persistente: un archivo se perdería en el siguiente despliegue y el logo
desaparecería solo, sin que nadie tocara nada.
"""

import io

import pytest
from PIL import Image

from app.database import SessionLocal
from app.models import Business
from app.services import logo as logo_service

# Las fixtures admin/operador viven en test_admin.py; pytest no las comparte
# entre archivos, así que se importan explícitamente.
from tests.test_admin import admin, operador  # noqa: F401


def imagen(ancho=600, alto=400, formato="PNG", color=(200, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (ancho, alto), color).save(buffer, format=formato)
    return buffer.getvalue()


def con_logo(business_id: int, datos: bytes | None = None) -> None:
    with SessionLocal() as db:
        b = db.get(Business, business_id)
        b.logo_data = datos if datos is not None else logo_service.procesar(imagen())
        db.commit()


class TestProcesadoDeImagenes:
    def test_acepta_los_formatos_normales(self):
        for formato in ("PNG", "JPEG", "WEBP", "BMP"):
            procesado = logo_service.procesar(imagen(formato=formato))
            assert Image.open(io.BytesIO(procesado)).format == "PNG", formato

    def test_siempre_devuelve_png(self):
        """Se reescribe la imagen en vez de guardar los bytes que llegaron. Así
        nunca se le sirve a un visitante un archivo que subió otra persona: un
        políglota, que es imagen válida y a la vez otra cosa, no sobrevive."""
        procesado = logo_service.procesar(imagen(formato="JPEG"))

        assert procesado[:4] == bytes([0x89, 0x50, 0x4E, 0x47]), "la firma de un PNG"

    def test_reduce_las_imagenes_grandes(self):
        """Un logo se ve a unos 120 px. Guardar 4000 px engorda la fila y hace
        que cada cliente del local descargue de más por nada."""
        procesado = logo_service.procesar(imagen(4000, 3000))
        resultado = Image.open(io.BytesIO(procesado))

        assert max(resultado.size) <= logo_service.MAX_LADO

    def test_conserva_la_proporcion(self):
        procesado = logo_service.procesar(imagen(800, 200))
        ancho, alto = Image.open(io.BytesIO(procesado)).size

        assert abs((ancho / alto) - 4.0) < 0.1

    def test_no_agranda_una_imagen_pequena(self):
        procesado = logo_service.procesar(imagen(100, 50))

        assert Image.open(io.BytesIO(procesado)).size == (100, 50)

    def test_rechaza_lo_que_no_es_imagen(self):
        with pytest.raises(logo_service.LogoInvalido):
            logo_service.procesar(b"esto es texto, no una imagen")

    def test_rechaza_un_svg(self):
        """Un SVG es XML y puede traer scripts dentro, que el navegador ejecuta
        si alguien abre el archivo directamente."""
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

        with pytest.raises(logo_service.LogoInvalido):
            logo_service.procesar(svg)

    def test_rechaza_un_archivo_enorme(self):
        with pytest.raises(logo_service.LogoInvalido) as error:
            logo_service.procesar(b"x" * (4 * 1024 * 1024))

        assert "3 MB" in str(error.value)

    def test_rechaza_un_archivo_vacio(self):
        with pytest.raises(logo_service.LogoInvalido):
            logo_service.procesar(b"")

    def test_el_mensaje_de_error_sirve_para_mostrarlo(self):
        """Lo lee el operador en el panel, así que tiene que decir qué hacer."""
        with pytest.raises(logo_service.LogoInvalido) as error:
            logo_service.procesar(b"no soy una imagen")

        assert "PNG" in str(error.value)


class TestLaLandingSePersonaliza:
    def test_sin_logo_no_aparece_la_imagen(self, negocio, visitante):
        html = visitante().get(f"/r/{negocio.mesa}").text

        assert "logo.png" not in html

    def test_con_logo_la_landing_lo_muestra(self, negocio, visitante):
        con_logo(negocio.id)

        html = visitante().get(f"/r/{negocio.mesa}").text

        assert f'src="/r/{negocio.mesa}/logo.png"' in html

    def test_el_logo_se_sirve(self, negocio, visitante):
        con_logo(negocio.id)

        respuesta = visitante().get(f"/r/{negocio.mesa}/logo.png")

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"] == "image/png"

    def test_sin_logo_la_ruta_da_404(self, negocio, visitante):
        assert visitante().get(f"/r/{negocio.mesa}/logo.png").status_code == 404

    def test_el_logo_se_pide_por_el_token_de_la_placa(self, negocio, visitante):
        """Y no por el del negocio, que abre su informe. La URL de un `<img>` se
        filtra en cualquier parte; el token de placa ya es público porque está
        pegado en la mesa."""
        con_logo(negocio.id)

        html = visitante().get(f"/r/{negocio.mesa}").text

        assert negocio.token not in html

    def test_no_se_vuelve_a_descargar_en_cada_visita(self, negocio, visitante):
        """Un logo cambia casi nunca y esto se pide en cada toque de placa."""
        con_logo(negocio.id)
        telefono = visitante()

        primera = telefono.get(f"/r/{negocio.mesa}/logo.png")
        etag = primera.headers["etag"]
        segunda = telefono.get(f"/r/{negocio.mesa}/logo.png", headers={"If-None-Match": etag})

        assert segunda.status_code == 304
        assert segunda.content == b""

    def test_cambiar_el_logo_invalida_la_cache(self, negocio, visitante):
        con_logo(negocio.id, logo_service.procesar(imagen(color=(10, 10, 200))))
        etag_viejo = visitante().get(f"/r/{negocio.mesa}/logo.png").headers["etag"]

        con_logo(negocio.id, logo_service.procesar(imagen(color=(10, 200, 10))))
        etag_nuevo = visitante().get(f"/r/{negocio.mesa}/logo.png").headers["etag"]

        assert etag_nuevo != etag_viejo

    def test_el_mensaje_propio_reemplaza_al_de_ejemplo(self, negocio, visitante):
        with SessionLocal() as db:
            db.get(Business, negocio.id).welcome_message = "Cuéntanos cómo estuvo tu café"
            db.commit()

        html = visitante().get(f"/r/{negocio.mesa}").text

        assert "Cuéntanos cómo estuvo tu café" in html
        assert "Gracias por visitarnos" not in html

    def test_sin_mensaje_propio_se_usa_el_de_ejemplo(self, negocio, visitante):
        html = visitante().get(f"/r/{negocio.mesa}").text

        assert "Gracias por visitarnos" in html

    def test_el_mensaje_no_puede_inyectar_html(self, negocio, visitante):
        """Lo escribe el operador, no un desconocido, pero un descuido no puede
        romper la página pública de un cliente."""
        with SessionLocal() as db:
            db.get(Business, negocio.id).welcome_message = '<script>alert(1)</script>'
            db.commit()

        html = visitante().get(f"/r/{negocio.mesa}").text

        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_la_pagina_de_gracias_tambien_lleva_el_logo(self, negocio, visitante):
        con_logo(negocio.id)
        telefono = visitante()

        html = telefono.post(f"/r/{negocio.mesa}/feedback", data={"message": "algo"}).text

        assert "logo.png" in html


class TestPersonalizacionDesdeElPanel:
    def test_se_puede_subir_al_dar_de_alta(self, operador):
        from sqlalchemy import select

        respuesta = operador.post(
            "/admin/nuevo",
            data={
                "nombre": "Con Logo",
                "google_url": "https://g.page/r/CL/review",
                "placas": "Barra",
                "email": "",
                "telegram": "",
                "mensaje": "Bienvenido a nuestra barra",
            },
            files={"logo": ("logo.png", imagen(), "image/png")},
        )

        assert respuesta.status_code == 200
        with SessionLocal() as db:
            creado = db.scalar(select(Business).where(Business.name == "Con Logo"))
        assert creado.logo_data is not None
        assert creado.welcome_message == "Bienvenido a nuestra barra"

    def test_un_logo_invalido_no_impide_crear_el_cliente(self, operador):
        """Un archivo mal subido no puede tirar abajo el alta: se avisa y sigue."""
        from sqlalchemy import select

        html = operador.post(
            "/admin/nuevo",
            data={"nombre": "Logo Malo", "google_url": "https://g.page/r/CM/review",
                  "placas": "Barra", "email": "", "telegram": "", "mensaje": ""},
            files={"logo": ("virus.png", b"no soy una imagen", "image/png")},
        ).text

        with SessionLocal() as db:
            creado = db.scalar(select(Business).where(Business.name == "Logo Malo"))

        assert creado is not None, "el cliente debe crearse igual"
        assert creado.logo_data is None
        assert "No se guardó el logo" in html

    def test_editar_sin_subir_nada_conserva_el_logo(self, operador, negocio):
        """Cambiar el correo no puede borrar el logo sin que nadie lo pida."""
        con_logo(negocio.id)

        operador.post(
            f"/admin/{negocio.token}/editar",
            data={"nombre": negocio.nombre, "google_url": negocio.google_url,
                  "email": "otro@correo.cl", "telegram": "", "mensaje": ""},
        )

        with SessionLocal() as db:
            assert db.get(Business, negocio.id).logo_data is not None

    def test_subir_uno_nuevo_reemplaza_al_anterior(self, operador, negocio):
        con_logo(negocio.id, logo_service.procesar(imagen(color=(1, 1, 1))))
        with SessionLocal() as db:
            antes = db.get(Business, negocio.id).logo_data

        operador.post(
            f"/admin/{negocio.token}/editar",
            data={"nombre": negocio.nombre, "google_url": negocio.google_url,
                  "email": "", "telegram": "", "mensaje": ""},
            files={"logo": ("nuevo.png", imagen(color=(250, 250, 250)), "image/png")},
        )

        with SessionLocal() as db:
            assert db.get(Business, negocio.id).logo_data != antes

    def test_se_puede_quitar_el_logo(self, operador, negocio):
        con_logo(negocio.id)

        operador.post(
            f"/admin/{negocio.token}/editar",
            data={"nombre": negocio.nombre, "google_url": negocio.google_url,
                  "email": "", "telegram": "", "mensaje": "", "quitar_logo": "1"},
        )

        with SessionLocal() as db:
            assert db.get(Business, negocio.id).logo_data is None

    def test_se_puede_cambiar_solo_el_mensaje(self, operador, negocio):
        operador.post(
            f"/admin/{negocio.token}/editar",
            data={"nombre": negocio.nombre, "google_url": negocio.google_url,
                  "email": "", "telegram": "", "mensaje": "Un mensaje nuevo"},
        )

        with SessionLocal() as db:
            assert db.get(Business, negocio.id).welcome_message == "Un mensaje nuevo"
