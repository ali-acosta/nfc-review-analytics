import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_DOC_URL = "https://api.telegram.org/bot{token}/sendDocument"


async def send_alert(chat_id: str, text: str) -> None:
    """Best-effort Telegram notification. Never raises: if the bot token or
    chat id is missing, or the request fails, it just logs and moves on."""
    token = settings.telegram_bot_token
    chat_id = chat_id or settings.telegram_chat_id

    if not token or not chat_id:
        logger.info("Telegram no configurado; se omite la alerta: %s", text)
        return

    url = TELEGRAM_API_URL.format(token=token)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
            response.raise_for_status()
    except Exception as exc:
        # Catch-all deliberado, no pereza: esto es un canal secundario de aviso.
        # Nada de lo que pase aquí —red, DNS, TLS, un token mal formado, un bug
        # nuestro— puede impedir que un cliente deje su reseña o su comentario.
        logger.warning("No se pudo enviar la alerta de Telegram: %s", exc)


async def send_document(chat_id: str, filename: str, content: bytes, caption: str = "") -> bool:
    """Envía un archivo (el informe en PDF). Devuelve si se logró.

    A diferencia de send_alert, aquí el resultado sí importa: quien llama es el
    envío mensual, que necesita saber si debe reportar el fallo al operador.
    """
    token = settings.telegram_bot_token
    chat_id = chat_id or settings.telegram_chat_id

    if not token or not chat_id:
        logger.info("Telegram no configurado; no se envía %s", filename)
        return False

    url = TELEGRAM_DOC_URL.format(token=token)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                data={"chat_id": chat_id, "caption": caption[:1024]},
                files={"document": (filename, content, "application/pdf")},
            )
            response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("No se pudo enviar el documento a Telegram: %s", exc)
        return False


async def send_message(chat_id: str, text: str) -> bool:
    """Como send_alert pero informando el resultado, para el envío mensual."""
    token = settings.telegram_bot_token
    chat_id = chat_id or settings.telegram_chat_id

    if not token or not chat_id:
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                TELEGRAM_API_URL.format(token=token),
                json={"chat_id": chat_id, "text": text},
            )
            response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("No se pudo enviar el mensaje a Telegram: %s", exc)
        return False
