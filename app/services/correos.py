"""Los dos correos que le llegan al dueño sobre su propia cuenta.

Van juntos porque son la misma idea contada dos veces: un enlace firmado que
lleva a elegir contraseña. La diferencia está en quién lo pidió —el alta la pide
el operador, la recuperación la pide el dueño— y por eso duran distinto.

Existen para que **la contraseña nunca viaje en texto plano ni haya que dictarla
por teléfono**. Antes, dar de alta a un cliente terminaba con el operador
leyéndole una clave en voz alta, que el dueño anotaba en un papel o se mandaba a
sí mismo por WhatsApp. Ahora la elige él y nadie más la ve.

Estos correos NO pasan por `notify.py`. Ese módulo reparte avisos del negocio a
los canales que tenga configurados; esto es correspondencia de la cuenta y va al
`login_email`, que puede ser otro. Mandar por Telegram un enlace para cambiar la
contraseña sería, además, meterla en un canal que el dueño no eligió para eso.
"""

import logging

from app.config import settings
from app.models import Business
from app.services import enlaces
from app.services.email import send_email

logger = logging.getLogger(__name__)


def hay_correo_saliente() -> bool:
    """Si no hay SMTP, quien llama tiene que enterarse y dar la alternativa.

    Es la diferencia entre un alta que se completa sola y una que deja al dueño
    sin poder entrar mientras todos creen que ya se le avisó.
    """
    return bool(settings.smtp_host and settings.smtp_from)


async def enviar_bienvenida(business: Business) -> bool:
    """El correo del alta: qué es esto y cómo entrar. Su enlace vale una semana."""
    if not business.login_email:
        return False

    enlace = enlaces.url_nueva_clave(
        enlaces.firmar_bienvenida(business.id, business.password_hash)
    )
    panel = f"{settings.base_url.rstrip('/')}/panel/login"

    cuerpo = "\n".join(
        [
            "Hola,",
            "",
            f"Ya está listo el panel de reseñas de {business.name}. Desde ahí vas a ver",
            "cuánta gente toca las placas, cuántos terminan dejando su reseña en Google",
            "y los comentarios privados que te dejen tus clientes.",
            "",
            "Lo primero es elegir tu contraseña:",
            enlace,
            "",
            "Ese enlace vale una semana y sirve una sola vez. Después entras siempre por:",
            panel,
            f"con este mismo correo ({business.login_email}).",
            "",
            "Cada mes te vamos a mandar un informe con el resumen. Y cada vez que alguien",
            "te deje un comentario privado te avisamos en el momento: esa es la parte que",
            "te deja llamar al cliente antes de que escriba una estrella en público.",
            "",
        ]
    )

    entregado = await send_email(
        business.login_email,
        f"Tu panel de reseñas de {business.name} ya está listo",
        cuerpo,
    )
    if not entregado:
        logger.warning(
            "No se pudo enviar la bienvenida a '%s' (%s): hay que darle acceso a mano",
            business.name,
            business.login_email,
        )
    return entregado


async def enviar_recuperacion(business: Business) -> bool:
    """El correo de "¿olvidaste tu contraseña?". Su enlace vale una hora."""
    if not business.login_email:
        return False

    enlace = enlaces.url_nueva_clave(
        enlaces.firmar_clave(business.id, business.password_hash)
    )

    cuerpo = "\n".join(
        [
            "Hola,",
            "",
            f"Pediste crear una contraseña nueva para el panel de {business.name}.",
            "",
            "Entra aquí y elígela:",
            enlace,
            "",
            "El enlace vale una hora y sirve una sola vez.",
            "",
            "Si no fuiste tú, ignora este correo: tu contraseña actual sigue funcionando",
            "y nadie puede entrar con este enlace sin abrir tu casilla.",
            "",
        ]
    )

    return await send_email(
        business.login_email,
        "Crea una contraseña nueva para tu panel",
        cuerpo,
    )
