"""Session identity and bot filtering for the tap funnel.

The product sells the conversion number, so the number has to be defensible:
a page refresh must not count as a second visit, and a WhatsApp link preview
must not count as a customer.
"""

import uuid

SESSION_COOKIE = "nfc_sid"
SESSION_MAX_AGE = 60 * 60 * 24  # 24h — long enough to link a visit to its click

# Substrings of user agents that are never a real customer standing at a counter.
_BOT_MARKERS = (
    "bot",
    "crawler",
    "spider",
    "curl",
    "wget",
    "python-requests",
    "httpx",
    "headlesschrome",
    "facebookexternalhit",
    "whatsapp",
    "telegrambot",
    "slackbot",
    "twitterbot",
    "discordbot",
    "linkedinbot",
    "embedly",
    "preview",
    "lighthouse",
    "pingdom",
    "uptimerobot",
)


# Teléfonos reales cuyo user-agent contiene por casualidad uno de los marcadores
# de arriba. Se revisan ANTES: descartar a un cliente de verdad es peor que dejar
# pasar un bot, porque el cliente descartado es una reseña que el negocio pagó por
# conseguir y que nunca aparecerá en su informe.
#
# Cubot es una marca de Android barato que se vende en Chile y contiene "bot".
_NO_SON_BOTS = ("cubot",)


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    if not ua:
        return True  # a real phone browser always sends one
    if any(marca in ua for marca in _NO_SON_BOTS):
        return False
    return any(marker in ua for marker in _BOT_MARKERS)


def new_session_id() -> str:
    return uuid.uuid4().hex
