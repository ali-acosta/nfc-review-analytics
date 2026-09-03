"""Protección del panel.

El panel es una app Dash montada por WSGI, así que no puede leer la sesión de
Starlette. La solución es que este middleware valide la sesión y le pase a Dash
la identidad ya resuelta en una cabecera interna.

Es middleware ASGI puro (y no BaseHTTPMiddleware) porque necesita modificar el
scope antes de que la petición llegue al mount, no solo la respuesta.
"""

from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.services.auth import SESSION_KEY

BUSINESS_HEADER = b"x-business-id"
PROTECTED_PREFIX = "/dashboard"

# Cabeceras para todas las respuestas.
#
# Referrer-Policy no es decorativa aquí: al mandar al cliente a Google, el
# navegador enviaría como referente la URL completa de la landing, que incluye
# el token de la placa. Con esta política solo viaja el origen.
BASE_SECURITY_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"strict-origin-when-cross-origin",
}

# Solo tiene sentido sobre https: enviarla en desarrollo obligaría al navegador a
# recordar que localhost debe usar TLS, y romper el desarrollo por meses.
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")

# Las landings NO deben indexarse. Si un cliente comparte el enlace de su placa y
# Google lo indexa, empiezan a llegar visitantes de escritorio desde el buscador:
# navegadores reales, que no se filtran como bots y le inflan las visitas a esa
# placa, hundiendo su conversión. La URL de una placa es para quien está sentado
# en esa mesa, no para el mundo.
NOINDEX = (b"x-robots-tag", b"noindex, nofollow")
PUBLIC_LANDING_PREFIX = "/r/"

# CSP estricta solo para las páginas públicas, que es donde entra gente
# desconocida. El panel queda fuera: Dash genera sus propios scripts en línea y
# una CSP estricta lo rompería; a cambio, ahí ya hace falta iniciar sesión.
PUBLIC_CSP = (
    b"default-src 'self'; "
    b"script-src 'self'; "
    b"style-src 'self'; "
    b"img-src 'self' data:; "
    b"form-action 'self'; "
    b"base-uri 'none'; "
    b"frame-ancestors 'none'"
)


class DashboardAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(PROTECTED_PREFIX):
            return await self.app(scope, receive, send)

        business_id = scope.get("session", {}).get(SESSION_KEY)

        if not business_id:
            response = RedirectResponse("/panel/login", status_code=302)
            return await response(scope, receive, send)

        # Se descarta cualquier cabecera con este nombre que venga del cliente
        # ANTES de poner la nuestra: si no, bastaría con enviarla a mano para
        # ver el panel de otro comercio.
        headers = [(k, v) for k, v in scope["headers"] if k.lower() != BUSINESS_HEADER]
        headers.append((BUSINESS_HEADER, str(business_id).encode()))

        await self.app({**scope, "headers": headers}, receive, send)


class SecurityHeadersMiddleware:
    """Añade cabeceras de endurecimiento a cada respuesta."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        es_publica = not scope["path"].startswith(PROTECTED_PREFIX)

        async def send_con_cabeceras(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                presentes = {k.lower() for k, _ in headers}
                extra = dict(BASE_SECURITY_HEADERS)
                if es_publica:
                    extra[b"content-security-policy"] = PUBLIC_CSP
                if settings.base_url.startswith("https://"):
                    extra[HSTS[0]] = HSTS[1]
                if scope["path"].startswith(PUBLIC_LANDING_PREFIX):
                    extra[NOINDEX[0]] = NOINDEX[1]
                # No se pisa lo que la respuesta ya haya definido a propósito.
                headers.extend((k, v) for k, v in extra.items() if k not in presentes)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_con_cabeceras)
