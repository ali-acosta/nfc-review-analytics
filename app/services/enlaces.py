"""Enlaces firmados con vencimiento.

Dos enlaces del producto se mandan por correo y se abren sin login, porque
exigir una contraseña en cada correo mensual pondría fricción justo en la pieza
que sostiene la retención. Que no pidan login no significa que tengan que durar
para siempre:

* **El informe mensual** lleva teléfonos, correos y quejas de los clientes
  finales del comercio —datos personales de terceros—. Un correo reenviado, una
  casilla filtrada o un dueño que se va del negocio dejaban ese enlace vivo para
  siempre y con acceso a *todos* los meses. Ahora la firma cubre el token y el
  mes concreto, así que un enlace filtrado expone un mes y caduca a los 90 días.
* **La recuperación de contraseña** tiene que durar poco por definición: una
  hora, y con un solo uso lógico (cambiar la clave invalida el enlace, porque la
  firma incluye el hash actual).

`itsdangerous` no es una dependencia nueva: ya viene con Starlette, que la usa
para firmar las cookies de sesión.

La clave de firma es `SESSION_SECRET`. Rotarla invalida los enlaces vivos, que
es el comportamiento correcto ante una filtración. En desarrollo suele estar
vacía y ahí se usa una constante conocida: si se generara una clave por proceso,
cada `--reload` de uvicorn rompería el enlace que se acaba de abrir y probar a
mano sería imposible. En producción no puede estar vacía —`check_deploy` lo
marca como bloqueante— así que la constante nunca llega a usarse allá.
"""

from itsdangerous import URLSafeTimedSerializer

from app.config import settings

# 90 días: cubre de sobra el mes que se está informando y el tiempo en que un
# dueño podría volver a abrir el correo, sin dejar el enlace vivo un año.
VIGENCIA_INFORME = 90 * 24 * 60 * 60

# Una hora. Es un enlace que llega a una casilla de correo y da acceso a cambiar
# la contraseña del panel: cuanto menos viva, mejor.
VIGENCIA_CLAVE = 60 * 60

_CLAVE_DE_DESARROLLO = "clave-solo-para-desarrollo-sin-session-secret"


def _serializador(sal: str) -> URLSafeTimedSerializer:
    # La sal separa los dominios: una firma de informe no sirve como enlace de
    # recuperación de contraseña ni al revés, aunque compartan la clave.
    return URLSafeTimedSerializer(settings.session_secret or _CLAVE_DE_DESARROLLO, salt=sal)


# --------------------------------------------------------------------------- #
# Informe mensual
# --------------------------------------------------------------------------- #


def etiqueta_mes(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def firmar_informe(token: str, year: int, month: int) -> str:
    return _serializador("informe").dumps(f"{token}:{etiqueta_mes(year, month)}")


def informe_valido(firma: str | None, token: str, year: int, month: int) -> bool:
    """Nunca lanza: cualquier problema con la firma es simplemente 'no vale'."""
    if not firma:
        return False
    try:
        contenido = _serializador("informe").loads(firma, max_age=VIGENCIA_INFORME)
    except Exception:  # firma inválida, vencida o basura: da igual cuál
        return False
    return contenido == f"{token}:{etiqueta_mes(year, month)}"


def ruta_informe(token: str, year: int, month: int) -> str:
    """Ruta relativa, firmada y con el mes explícito.

    El mes va siempre en la URL aunque el informe sepa calcular uno por defecto:
    la firma cubre un mes concreto, y un enlace sin `mes` cambiaría de período al
    pasar de mes y dejaría de coincidir con su propia firma.
    """
    mes = etiqueta_mes(year, month)
    return f"/informe/{token}?mes={mes}&firma={firmar_informe(token, year, month)}"


def url_informe(token: str, year: int, month: int, base_url: str | None = None) -> str:
    """Enlace absoluto, que es el que se pega en un correo."""
    base = (base_url if base_url is not None else settings.base_url).rstrip("/")
    return f"{base}{ruta_informe(token, year, month)}"


# --------------------------------------------------------------------------- #
# Recuperación de contraseña
# --------------------------------------------------------------------------- #


def firmar_clave(business_id: int, password_hash: str) -> str:
    """El hash actual entra en la firma para que el enlace muera al usarse.

    Sin esto, el mismo enlace serviría varias veces durante una hora: quien lo
    interceptara podría volver a cambiar la contraseña después de que el dueño ya
    la cambió. Incluir el hash lo convierte en un enlace de un solo uso sin
    necesidad de una tabla ni de una migración.
    """
    return _serializador("clave").dumps({"id": business_id, "h": password_hash})


def datos_de_clave(firma: str | None) -> tuple[int, str] | None:
    """`(id_del_negocio, hash_firmado)` si el enlace es legítimo y no venció.

    Devuelve el hash firmado en vez de compararlo aquí porque para compararlo hay
    que ir a buscar el negocio a la base, y eso no es trabajo de este módulo.
    Nunca lanza: una firma rota es simplemente un enlace que no sirve.
    """
    if not firma:
        return None
    try:
        datos = _serializador("clave").loads(firma, max_age=VIGENCIA_CLAVE)
        return int(datos["id"]), str(datos["h"])
    except Exception:
        return None
