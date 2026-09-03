import io
from pathlib import Path

import qrcode

from app.config import settings

QR_DIR = Path(__file__).resolve().parent.parent.parent / "qrcodes"


def target_url(token: str) -> str:
    """The URL burned into the NFC chip and printed in the QR.

    Comes from BASE_URL, which must point at the project's own domain before
    anything is printed: the URL cannot be changed once a plaque is installed.
    """
    return f"{settings.base_url.rstrip('/')}/r/{token}"


def generate_qr_for_token(token: str) -> Path:
    """Escribe el PNG a disco. Lo usan los scripts del operador, que necesitan el
    archivo para mandarlo a imprimir."""
    QR_DIR.mkdir(exist_ok=True)
    out_path = QR_DIR / f"{token}.png"

    img = qrcode.make(target_url(token))
    img.save(out_path)
    return out_path


def qr_png_bytes(token: str) -> bytes:
    """El mismo QR, en memoria, para servirlo por HTTP.

    La ruta web no tiene por qué tocar el disco: en el hosting es efímero, y
    escribir un archivo por cada petición es trabajo inútil que además deja basura
    que nadie limpia.
    """
    buffer = io.BytesIO()
    qrcode.make(target_url(token)).save(buffer, format="PNG")
    return buffer.getvalue()
