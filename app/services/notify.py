"""Punto único de envío de avisos a un negocio.

Un negocio puede tener Telegram, correo, ambos o ninguno. Quien avisa no debería
saber por cuál canal sale: si mañana se agrega WhatsApp, se agrega aquí y nada
más cambia.
"""

import asyncio
import logging

from app.models import Business
from app.services.email import send_email
from app.services.telegram import send_document, send_message

logger = logging.getLogger(__name__)


async def notify(business: Business, subject: str, body: str) -> bool:
    """Avisa por todos los canales configurados. Devuelve si llegó por alguno.

    Nunca lanza: quien llama puede estar en medio del flujo de un cliente que
    está dejando su reseña, y ese flujo no puede depender de esto.
    """
    canales = []
    if business.telegram_chat_id:
        canales.append(send_message(business.telegram_chat_id, f"{subject}\n\n{body}"))
    if business.alert_email:
        canales.append(send_email(business.alert_email, subject, body))

    if not canales:
        logger.info("El negocio '%s' no tiene canales de aviso configurados", business.name)
        return False

    resultados = await asyncio.gather(*canales, return_exceptions=True)

    entregado = False
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            logger.warning("Fallo enviando aviso a '%s': %s", business.name, resultado)
        elif resultado:
            entregado = True
    return entregado


async def notify_with_report(business: Business, subject: str, body: str, pdf: bytes | None) -> bool:
    """Como notify, pero adjuntando el informe donde el canal lo permita."""
    canales = []
    if business.telegram_chat_id:
        canales.append(send_message(business.telegram_chat_id, f"{subject}\n\n{body}"))
    if business.alert_email:
        adjunto = ("informe.pdf", pdf) if pdf else None
        canales.append(send_email(business.alert_email, subject, body, adjunto))

    if not canales:
        return False

    resultados = await asyncio.gather(*canales, return_exceptions=True)
    entregado = any(r is True for r in resultados)

    if entregado and pdf and business.telegram_chat_id:
        await send_document(business.telegram_chat_id, "informe.pdf", pdf)

    return entregado
