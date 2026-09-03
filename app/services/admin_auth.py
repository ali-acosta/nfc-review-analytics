"""Autenticación del panel de administración del operador.

Este panel es distinto de todos los demás accesos del sistema: ve y modifica a
*todos* los clientes a la vez. Un cliente que entra a su panel solo puede
hacerse daño a sí mismo; quien entre aquí puede cambiarle el enlace de reseñas a
la cartera completa, o leer las quejas privadas de negocios que no son suyos.

De ahí tres decisiones:

1. **La credencial vive en la configuración del servidor, no en la base.** Si
   algún día se filtra la base de datos, el acceso de administración no viaja con
   ella. Además evita una tabla y una migración para un único usuario.
2. **Se guarda como hash scrypt**, igual que las contraseñas de los clientes,
   para que la clave no quede en texto plano en el panel del hosting.
3. **Sin configuración, el panel no existe.** No es que quede abierto ni que use
   una clave por defecto: las rutas responden 404. Un panel de administración
   accesible por olvidar una variable de entorno es peor que no tenerlo.
"""

import hmac

from app.config import settings
from app.services.auth import hash_password, verify_password

SESSION_KEY = "admin"

# Hash señuelo para que un intento con el panel deshabilitado cueste lo mismo que
# uno con el panel activo, y no se pueda averiguar por tiempo si existe.
_SENUELO = hash_password("panel-de-administracion-deshabilitado")


def esta_habilitado() -> bool:
    """El panel solo existe si hay una credencial configurada."""
    return bool(settings.admin_password_hash)


def verificar(password: str) -> bool:
    """¿Es esta la contraseña del operador?

    Verifica siempre contra un hash, real o señuelo, para no delatar por tiempo
    de respuesta si el panel está configurado.
    """
    almacenado = settings.admin_password_hash or _SENUELO
    correcta = verify_password(password, almacenado)
    return bool(esta_habilitado() and correcta)


def hash_para_configurar(password: str) -> str:
    """El valor que hay que pegar en ADMIN_PASSWORD_HASH."""
    return hash_password(password)


def sesion_valida(sesion: dict) -> bool:
    """¿Esta sesión es la de un operador con el panel habilitado?

    Se compara el marcador con `compare_digest` por costumbre defensiva, y se
    exige que el panel siga habilitado: si se le quita la credencial al servidor,
    las sesiones ya abiertas tienen que dejar de servir en el acto, no seguir
    vivas hasta que caduque la cookie.
    """
    if not esta_habilitado():
        return False
    marcador = sesion.get(SESSION_KEY) or ""
    return hmac.compare_digest(str(marcador), "ok")
