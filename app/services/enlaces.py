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
* **El correo de bienvenida** lleva a la misma pantalla que la recuperación, pero
  su enlace dura una semana: el dueño lo recibe cuando el operador lo da de alta,
  no cuando él lo pidió, y bien puede abrirlo al día siguiente. Con una hora, el
  alta llegaría muerta a la casilla más veces de las que llegaría útil.

`itsdangerous` no es una dependencia nueva: ya viene con Starlette, que la usa
para firmar las cookies de sesión.

La clave de firma es `SESSION_SECRET`. Rotarla invalida los enlaces vivos, que
es el comportamiento correcto ante una filtración. En desarrollo suele estar
vacía y ahí se usa una constante conocida: si se generara una clave por proceso,
cada `--reload` de uvicorn rompería el enlace que se acaba de abrir y probar a
mano sería imposible. En producción no puede estar vacía —`check_deploy` lo
marca como bloqueante— así que la constante nunca llega a usarse allá.
"""

import hashlib

from itsdangerous import URLSafeTimedSerializer

from app.config import settings

# 90 días: cubre de sobra el mes que se está informando y el tiempo en que un
# dueño podría volver a abrir el correo, sin dejar el enlace vivo un año.
VIGENCIA_INFORME = 90 * 24 * 60 * 60

# Una hora. Es un enlace que llega a una casilla de correo y da acceso a cambiar
# la contraseña del panel: cuanto menos viva, mejor.
VIGENCIA_CLAVE = 60 * 60

# Una semana para el enlace del alta. Lo que marca la vigencia no es qué hace el
# enlace —los dos llevan a elegir contraseña— sino cuándo lo va a abrir quien lo
# recibe.
VIGENCIA_BIENVENIDA = 7 * 24 * 60 * 60

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


def huella(password_hash: str) -> str:
    """Huella corta e irreversible del hash de la contraseña.

    Es lo que viaja en el enlace, y **nunca el hash entero**. `itsdangerous`
    firma pero no cifra: el contenido de un token se lee con solo decodificarlo,
    sin conocer la clave del servidor. Con el hash dentro, un correo reenviado o
    una casilla filtrada entregaban el scrypt del dueño para atacarlo con calma
    y sin límite de intentos.

    Una huella cumple lo único que hace falta —cambiar cuando la contraseña
    cambia, para que el enlace muera al usarse— sin llevar nada aprovechable.
    Dieciséis caracteres alcanzan de sobra: no se busca nada en una tabla, solo
    se compara contra el hash de un negocio ya identificado.
    """
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def firmar_clave(business_id: int, password_hash: str) -> str:
    """Enlace de recuperación (una hora).

    La huella de la contraseña actual entra en la firma para que el enlace muera
    al usarse: sin esto, el mismo enlace serviría varias veces durante una hora y
    quien lo interceptara podría volver a cambiar la contraseña después de que el
    dueño ya la cambió. Lo convierte en un enlace de un solo uso sin necesidad de
    una tabla ni de una migración.
    """
    return _serializador("clave").dumps({"id": business_id, "h": huella(password_hash)})


def firmar_bienvenida(business_id: int, password_hash: str) -> str:
    """Enlace del alta (una semana). Muere al usarse, igual que el anterior."""
    return _serializador("bienvenida").dumps({"id": business_id, "h": huella(password_hash)})


def datos_de_clave(firma: str | None) -> tuple[int, str] | None:
    """`(id_del_negocio, huella_firmada)` si el enlace es legítimo y no venció.

    Acepta los dos tipos de enlace porque los dos llevan a la misma pantalla:
    elegir una contraseña. Lo que los separa es cuánto viven, y de eso se encarga
    la sal con la que se verifica cada uno.

    Devuelve la huella en vez de compararla aquí porque para compararla hay que
    ir a buscar el negocio a la base, y eso no es trabajo de este módulo.
    Nunca lanza: una firma rota es simplemente un enlace que no sirve.
    """
    if not firma:
        return None
    # Una sal por propósito, y con ella su plazo. El plazo va aquí y no dentro
    # del contenido firmado a propósito: así lo decide el servidor al verificar
    # y no el propio enlace, que si no podría pedir durar más de lo que le toca.
    for sal, vigencia in (("clave", VIGENCIA_CLAVE), ("bienvenida", VIGENCIA_BIENVENIDA)):
        try:
            datos = _serializador(sal).loads(firma, max_age=vigencia)
        except Exception:
            continue
        return int(datos["id"]), str(datos["h"])
    return None


def url_nueva_clave(firma: str, base_url: str | None = None) -> str:
    """El enlace para elegir contraseña, armado en un solo lugar.

    Lo usan el correo de bienvenida y el de recuperación. Armarlo a mano en cada
    llamador es cómo el enlace del informe terminó existiendo en seis versiones
    distintas antes de que empezara a llevar firma.
    """
    base = (base_url if base_url is not None else settings.base_url).rstrip("/")
    return f"{base}/panel/nueva-clave?firma={firma}"
