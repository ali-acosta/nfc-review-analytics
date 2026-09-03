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
    QR_DIR.mkdir(exist_ok=True)
    out_path = QR_DIR / f"{token}.png"

    img = qrcode.make(target_url(token))
    img.save(out_path)
    return out_path
