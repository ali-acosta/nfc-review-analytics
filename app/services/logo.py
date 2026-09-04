"""Procesamiento del logo del cliente para la landing.

**Dónde se guarda y por qué**: en la base de datos, no en el sistema de archivos.
El hosting no tiene disco persistente, así que un logo escrito como archivo
desaparecería en el siguiente despliegue y el cliente vería su logo esfumarse sin
que nadie tocara nada. Un almacenamiento externo tipo S3 resolvería lo mismo,
pero suma un servicio y un costo donde una columna alcanza: son unos pocos kB por
cliente, no una galería.

**Qué se guarda**: el resultado de reprocesar la imagen, nunca los bytes que
llegaron. Se abre con Pillow, se reduce y se vuelve a codificar como PNG. Eso
tiene tres efectos que importan:

1. Garantiza que sea de verdad una imagen. Un archivo que se llame `logo.png`
   pero contenga otra cosa no sobrevive a la reapertura.
2. Nunca se le sirve a un visitante un byte que subió alguien más. Los archivos
   políglotas, que son imagen válida y a la vez otra cosa, mueren al reescribirse.
3. Descarta metadatos EXIF, que en una foto pueden llevar coordenadas del local.

**Qué NO se acepta**: SVG. Es XML, puede traer scripts dentro y el navegador los
ejecuta si alguien abre el archivo directamente. Un logo no necesita ser vectorial
para verse bien a 200 píxeles.
"""

import io

from PIL import Image, UnidentifiedImageError

# Un logo en la landing se ve a unos 120 px de alto en un teléfono. 400 da margen
# para pantallas de alta densidad sin engordar la fila ni la página.
MAX_LADO = 400

# Tope de lo que se acepta recibir. Antes de decodificar nada: una imagen
# diminuta puede descomprimirse en gigabytes ("bomba de descompresión"), así que
# también se limita el resultado.
MAX_BYTES_ENTRADA = 3 * 1024 * 1024  # 3 MB
MAX_PIXELES = 40_000_000  # ~40 megapíxeles antes de redimensionar

FORMATOS_ACEPTADOS = {"PNG", "JPEG", "WEBP", "GIF", "BMP"}
MIME = "image/png"


class LogoInvalido(ValueError):
    """El archivo no sirve como logo. El mensaje es para mostrárselo al operador."""


def procesar(datos: bytes) -> bytes:
    """Devuelve el PNG listo para guardar, o lanza LogoInvalido con el motivo."""
    if not datos:
        raise LogoInvalido("El archivo llegó vacío.")

    if len(datos) > MAX_BYTES_ENTRADA:
        mb = len(datos) / 1024 / 1024
        raise LogoInvalido(
            f"La imagen pesa {mb:.1f} MB y el máximo son 3 MB. "
            "Un logo no necesita tanto: redúcelo antes de subirlo."
        )

    try:
        imagen = Image.open(io.BytesIO(datos))
        formato = (imagen.format or "").upper()
        imagen.verify()  # detecta archivos corruptos sin decodificarlos enteros
    except (UnidentifiedImageError, OSError, ValueError):
        raise LogoInvalido(
            "Eso no parece una imagen. Se aceptan PNG, JPG, WEBP, GIF y BMP; "
            "los SVG no, porque pueden traer código dentro."
        ) from None

    if formato not in FORMATOS_ACEPTADOS:
        raise LogoInvalido(
            f"Formato {formato or 'desconocido'} no aceptado. "
            "Usa PNG, JPG, WEBP, GIF o BMP."
        )

    # verify() deja el archivo inutilizable: hay que reabrirlo para trabajarlo.
    imagen = Image.open(io.BytesIO(datos))

    ancho, alto = imagen.size
    if ancho * alto > MAX_PIXELES:
        raise LogoInvalido(
            f"La imagen mide {ancho}x{alto} píxeles, demasiado grande para procesarla."
        )

    # RGBA conserva la transparencia, que es lo normal en un logo sobre fondo claro.
    imagen = imagen.convert("RGBA")
    imagen.thumbnail((MAX_LADO, MAX_LADO), Image.LANCZOS)

    salida = io.BytesIO()
    imagen.save(salida, format="PNG", optimize=True)
    return salida.getvalue()


def descripcion(datos: bytes | None) -> str:
    """Texto corto para mostrarle al operador qué hay guardado."""
    if not datos:
        return "sin logo"
    try:
        imagen = Image.open(io.BytesIO(datos))
        return f"{imagen.width}x{imagen.height} px · {len(datos) / 1024:.0f} kB"
    except Exception:
        return f"{len(datos) / 1024:.0f} kB"
