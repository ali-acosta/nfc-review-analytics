"""Autenticación del panel del comercio.

Sin dependencias nuevas: `hashlib.scrypt` viene en la biblioteca estándar y es
una función de derivación de claves real —lenta y con sal—, no un hash rápido
como SHA-256, que sería inseguro para contraseñas.

El `dashboard_token` no desaparece: sigue sirviendo para los enlaces de informe
que se le envían por correo al propio dueño (un patrón habitual, como el enlace
de una factura). Lo que ahora exige contraseña es el panel interactivo.
"""

import hashlib
import hmac
import secrets
import string

SESSION_KEY = "business_id"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
_ALPHABET = string.ascii_lowercase + string.digits


def hash_password(password: str) -> str:
    """Devuelve 'scrypt$<sal_hex>$<hash_hex>'."""
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Nunca lanza: un hash corrupto o vacío es simplemente un login fallido."""
    if not stored or not password:
        return False
    try:
        algoritmo, salt_hex, hash_hex = stored.split("$")
        if algoritmo != "scrypt":
            return False
        derived = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    except (ValueError, TypeError):
        return False
    # Comparación en tiempo constante: una comparación normal filtra información
    # por el tiempo que tarda en encontrar la primera diferencia.
    return hmac.compare_digest(derived.hex(), hash_hex)


def generate_password(length: int = 12) -> str:
    """Contraseña inicial legible por teléfono: sin mayúsculas ni símbolos, que
    se confunden al dictarla, y con suficiente entropía igualmente."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
