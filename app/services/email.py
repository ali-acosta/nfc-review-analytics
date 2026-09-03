"""Alertas por correo.

Existe porque el canal importa tanto como el mensaje: un dueño de pyme en Chile
revisa su correo todos los días, y Telegram probablemente no lo tenga instalado.
Como la alerta de queja es la principal razón por la que un cliente sigue
pagando, mandarla a un canal que nadie mira equivale a no mandarla.

Usa smtplib de la biblioteca estándar: sin dependencias nuevas y compatible con
cualquier proveedor SMTP (Brevo, Gmail, Zoho).
"""

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def _send_sync(to: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    if attachment:
        filename, content = attachment
        message.add_attachment(content, maintype="application", subtype="pdf", filename=filename)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)


async def send_email(
    to: str,
    subject: str,
    body: str,
    attachment: tuple[str, bytes] | None = None,
) -> bool:
    """Devuelve si se logró enviar. Nunca lanza.

    smtplib es bloqueante, así que va a un hilo: si no, la conexión SMTP dejaría
    el event loop congelado mientras otro cliente intenta tocar una placa.
    """
    if not _is_configured() or not to:
        logger.info("SMTP no configurado o sin destinatario; no se envía '%s'", subject)
        return False

    try:
        await asyncio.to_thread(_send_sync, to, subject, body, attachment)
        return True
    except Exception as exc:
        logger.warning("No se pudo enviar el correo a %s: %s", to, exc)
        return False
