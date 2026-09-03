"""Límite de peticiones por IP, en memoria.

El token de una placa es público por diseño: está pegado en una mesa y
cualquiera puede leer la URL. Sin un límite, basta un script que borre cookies
entre peticiones para inflar las visitas de un cliente y hundirle la conversión
—justo el número por el que paga—.

En memoria y no en Redis porque hoy corre un solo proceso. Si algún día hay
varias instancias, cada una llevará su propia cuenta y el límite efectivo será
el configurado por instancia: aceptable, pero hay que saberlo.
"""

import ipaddress
import logging
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

# Umbral a partir del cual se barren las IPs que ya no tienen peticiones vivas,
# para que el diccionario no crezca sin techo.
_SWEEP_THRESHOLD = 10_000


class RateLimiter:
    def __init__(self, max_hits: int, window_seconds: int, name: str = "") -> None:
        self.max_hits = max_hits
        self.window = window_seconds
        self.name = name
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """True si la petición cabe dentro del límite. Registra el intento."""
        now = time.monotonic()
        hits = self._hits[key]

        while hits and now - hits[0] > self.window:
            hits.popleft()

        if len(self._hits) > _SWEEP_THRESHOLD:
            self._sweep(now)

        if len(hits) >= self.max_hits:
            logger.warning("Límite '%s' superado por %s", self.name, key)
            return False

        hits.append(now)
        return True

    def reset(self, key: str) -> None:
        """Tras un login correcto no tiene sentido seguir penalizando la IP."""
        self._hits.pop(key, None)

    def _sweep(self, now: float) -> None:
        vacias = [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]
        for k in vacias:
            del self._hits[k]


def _es_publica(ip: str) -> bool:
    """True si es una IP de internet, no una privada ni un salto interno."""
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def client_ip(request) -> str:
    """IP del cliente, respetando el proxy del hosting.

    Render y compañía terminan TLS por delante, así que request.client.host es
    siempre la IP del proxy: sin mirar X-Forwarded-For, todos los visitantes
    compartirían una única clave y el límite se aplicaría a todo el tráfico
    junto.

    Se lee de DERECHA a IZQUIERDA y no al revés. Render no borra la cabecera que
    llega del cliente, solo le agrega la IP real al final: si se tomara la
    primera, cualquiera podría mandar una X-Forwarded-For inventada y distinta en
    cada petición para no compartir nunca clave con la anterior, dejando sin
    efecto tanto el límite de visitas como el de fuerza bruta del login. Lo que
    agregó el proxy propio está al final; lo anterior lo pudo escribir el cliente
    y no se le cree. Las privadas se saltan para tolerar saltos internos del
    hosting.

    Si algún día el hosting agregara un salto interno con IP pública, todos los
    visitantes caerían en una sola clave: degrada la métrica, pero no se puede
    falsificar. Ese es el fallo seguro.
    """
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada:
        for ip in reversed([parte.strip() for parte in reenviada.split(",")]):
            if _es_publica(ip):
                return ip
    return request.client.host if request.client else "desconocida"


# Generoso a propósito: en un local los clientes salen por el WiFi del negocio,
# así que decenas de personas comparten una misma IP pública. 60 por minuto
# cubre de sobra a un local lleno y sigue frenando a un script.
public_limiter = RateLimiter(max_hits=60, window_seconds=60, name="público")

# Estricto: aquí no hay IPs compartidas legítimas que proteger, y lo que está
# en juego es la contraseña del panel de un cliente.
login_limiter = RateLimiter(max_hits=8, window_seconds=900, name="login")

# Cada comentario privado despierta el teléfono del dueño. Sin techo, alguien
# podría convertir esa alerta en una molestia constante. 10 cada 10 minutos deja
# pasar hasta un mal día real en el local y corta el abuso.
feedback_limiter = RateLimiter(max_hits=10, window_seconds=600, name="comentarios")
