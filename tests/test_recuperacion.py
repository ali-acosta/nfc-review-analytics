"""Recuperación de contraseña por el propio dueño.

Antes, un dueño que olvidaba su clave dependía de que el operador la regenerara
y se la dictara por teléfono: una llamada por semana con diez clientes, y una
contraseña que termina escrita en un WhatsApp.

Lo que estos tests cuidan es lo que hace peligroso un formulario así: que no
sirva para averiguar quiénes son clientes, que el enlace no dure ni se pueda
reusar, y que no se convierta en un cañón de correos contra la casilla de
alguien.
"""

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Business
from app.services import enlaces
from app.services.auth import hash_password, verify_password

CORREO = "duena@local.cl"
CLAVE_VIEJA = "clave-vieja-1234"
CLAVE_NUEVA = "clave-nueva-5678"


def _con_credenciales(negocio, email=CORREO, clave=CLAVE_VIEJA):
    with SessionLocal() as db:
        business = db.get(Business, negocio.id)
        business.login_email = email
        business.password_hash = hash_password(clave)
        db.commit()
        return business.password_hash


def _enlace_para(negocio):
    with SessionLocal() as db:
        business = db.get(Business, negocio.id)
        return "/panel/nueva-clave?firma=" + enlaces.firmar_clave(business.id, business.password_hash)


def _clave_guardada(negocio):
    with SessionLocal() as db:
        return db.get(Business, negocio.id).password_hash


def _smtp_configurado(monkeypatch):
    """La ruta se niega a fingir un envío si no hay por dónde mandarlo."""
    from app.services import correos

    monkeypatch.setattr(correos.settings, "smtp_host", "smtp.ejemplo.cl")
    monkeypatch.setattr(correos.settings, "smtp_from", "avisos@ejemplo.cl")


class TestNoDelataQuienEsCliente:
    def test_la_respuesta_es_la_misma_exista_o_no_la_cuenta(self, negocio, cliente, monkeypatch):
        """Si dijera 'ese correo no está registrado', el formulario serviría
        para recorrer la cartera de clientes, que es justo lo que el mensaje
        único del login evita."""
        _con_credenciales(negocio)
        _smtp_configurado(monkeypatch)

        real = cliente.post("/panel/recuperar", data={"email": CORREO})
        falso = cliente.post("/panel/recuperar", data={"email": "nadie@ninguna.cl"})

        assert real.status_code == falso.status_code == 200
        assert real.text == falso.text


class TestElEnvio:
    def test_manda_el_enlace_al_correo_de_la_cuenta(self, negocio, cliente, monkeypatch):
        _con_credenciales(negocio)
        _smtp_configurado(monkeypatch)
        enviados = []

        async def fake_send(to, subject, body, attachment=None):
            enviados.append((to, subject, body))
            return True

        monkeypatch.setattr("app.services.correos.send_email", fake_send)

        cliente.post("/panel/recuperar", data={"email": CORREO})

        assert len(enviados) == 1
        destino, _, cuerpo = enviados[0]
        assert destino == CORREO
        assert "/panel/nueva-clave?firma=" in cuerpo

    def test_no_manda_nada_a_un_correo_que_no_es_cliente(self, negocio, cliente, monkeypatch):
        _con_credenciales(negocio)
        _smtp_configurado(monkeypatch)
        enviados = []

        async def fake_send(to, subject, body, attachment=None):
            enviados.append(to)
            return True

        monkeypatch.setattr("app.services.correos.send_email", fake_send)

        cliente.post("/panel/recuperar", data={"email": "nadie@ninguna.cl"})

        assert enviados == []

    def test_sin_smtp_lo_dice_en_vez_de_fingir(self, negocio, cliente, monkeypatch):
        """Mostrar 'te mandamos un correo' sin tener por dónde mandarlo deja al
        dueño esperando algo que no va a llegar nunca."""
        _con_credenciales(negocio)
        from app.services import correos

        monkeypatch.setattr(correos.settings, "smtp_host", "")

        respuesta = cliente.post("/panel/recuperar", data={"email": CORREO})

        assert respuesta.status_code == 503
        assert "no está disponible" in respuesta.text

    def test_tiene_techo_por_ip(self, negocio, cliente, monkeypatch):
        """Cada acierto dispara un correo: sin límite, el formulario es un cañón
        gratis contra la casilla de un cliente y contra la cuota del proveedor."""
        _con_credenciales(negocio)
        _smtp_configurado(monkeypatch)
        from app.services.ratelimit import recovery_limiter

        recovery_limiter.reset("testclient")
        monkeypatch.setattr(recovery_limiter, "max_hits", 2)

        codigos = [
            cliente.post("/panel/recuperar", data={"email": CORREO}).status_code for _ in range(4)
        ]

        assert codigos[:2] == [200, 200]
        assert codigos[2:] == [429, 429]


class TestElEnlace:
    def test_permite_elegir_una_clave_nueva(self, negocio, cliente):
        _con_credenciales(negocio)
        enlace = _enlace_para(negocio)

        cliente.get(enlace)
        cliente.post(
            "/panel/nueva-clave",
            data={"firma": enlace.split("firma=")[1], "nueva": CLAVE_NUEVA, "repetir": CLAVE_NUEVA},
        )

        assert verify_password(CLAVE_NUEVA, _clave_guardada(negocio))

    def test_deja_al_dueno_dentro_del_panel(self, negocio):
        """Ya demostró que controla la casilla y acaba de elegir la clave:
        obligarlo a escribirla otra vez no protege nada."""
        _con_credenciales(negocio)
        firma = _enlace_para(negocio).split("firma=")[1]

        with TestClient(app) as c:
            respuesta = c.post(
                "/panel/nueva-clave",
                data={"firma": firma, "nueva": CLAVE_NUEVA, "repetir": CLAVE_NUEVA},
            )

        assert respuesta.status_code == 200
        assert respuesta.url.path == "/dashboard/"

    def test_sirve_una_sola_vez(self, negocio, cliente):
        """La firma incluye el hash actual, así que al cambiar la clave el
        enlace muere: quien lo interceptara no puede volver a usarlo después."""
        _con_credenciales(negocio)
        firma = _enlace_para(negocio).split("firma=")[1]
        datos = {"firma": firma, "nueva": CLAVE_NUEVA, "repetir": CLAVE_NUEVA}

        cliente.post("/panel/nueva-clave", data=datos)
        segunda = cliente.post("/panel/nueva-clave", data={**datos, "nueva": "otra-clave-999", "repetir": "otra-clave-999"})

        assert segunda.status_code == 403
        assert verify_password(CLAVE_NUEVA, _clave_guardada(negocio))

    def test_caduca(self, negocio, cliente, monkeypatch):
        _con_credenciales(negocio)
        monkeypatch.setattr(enlaces, "VIGENCIA_CLAVE", -1)
        firma = _enlace_para(negocio).split("firma=")[1]

        respuesta = cliente.get(f"/panel/nueva-clave?firma={firma}")

        assert respuesta.status_code == 403

    def test_una_firma_inventada_no_abre(self, negocio, cliente):
        respuesta = cliente.get("/panel/nueva-clave?firma=esto-no-es-una-firma")

        assert respuesta.status_code == 403

    def test_una_firma_de_informe_no_sirve_para_cambiar_la_clave(self, negocio, cliente):
        """Las dos firmas usan la misma clave del servidor; lo que las separa es
        la sal. Sin ella, un enlace de informe filtrado sería una llave del
        panel."""
        _con_credenciales(negocio)
        firma = enlaces.firmar_informe(negocio.token, 2026, 8)

        respuesta = cliente.get(f"/panel/nueva-clave?firma={firma}")

        assert respuesta.status_code == 403

    def test_no_acepta_una_clave_corta(self, negocio, cliente):
        _con_credenciales(negocio)
        firma = _enlace_para(negocio).split("firma=")[1]

        respuesta = cliente.post(
            "/panel/nueva-clave", data={"firma": firma, "nueva": "corta", "repetir": "corta"}
        )

        assert respuesta.status_code == 400
        assert verify_password(CLAVE_VIEJA, _clave_guardada(negocio))

    def test_no_acepta_dos_claves_distintas(self, negocio, cliente):
        _con_credenciales(negocio)
        firma = _enlace_para(negocio).split("firma=")[1]

        respuesta = cliente.post(
            "/panel/nueva-clave",
            data={"firma": firma, "nueva": CLAVE_NUEVA, "repetir": "otra-cosa-1234"},
        )

        assert respuesta.status_code == 400
        assert verify_password(CLAVE_VIEJA, _clave_guardada(negocio))


class TestLoQueViajaDentroDelEnlace:
    """`itsdangerous` firma, pero no cifra.

    El contenido de un token se lee con solo decodificarlo, sin conocer la clave
    del servidor. La primera versión metía ahí el hash scrypt completo del dueño:
    un correo reenviado o una casilla filtrada lo entregaban para atacarlo con
    calma, sin límite de intentos y sin que nadie se enterara. Ahora viaja una
    huella irreversible, que cumple lo mismo (morir cuando la clave cambia) sin
    llevar nada aprovechable.
    """

    def _contenido(self, firma: str) -> dict:
        from itsdangerous import URLSafeTimedSerializer

        # A propósito con una clave equivocada: se trata de leer lo que puede
        # leer cualquiera que solo tenga el enlace.
        return URLSafeTimedSerializer("una-clave-que-no-es-la-del-servidor").loads_unsafe(firma)[1]

    def test_no_lleva_el_hash_de_la_contraseña(self, negocio):
        guardado = _con_credenciales(negocio)
        firma = _enlace_para(negocio).split("firma=")[1]

        contenido = str(self._contenido(firma))

        assert guardado not in contenido
        assert "scrypt" not in contenido

    def test_el_correo_de_bienvenida_tampoco(self, negocio):
        guardado = _con_credenciales(negocio)
        firma = enlaces.firmar_bienvenida(negocio.id, guardado)

        contenido = str(self._contenido(firma))

        assert guardado not in contenido
        assert "scrypt" not in contenido

    def test_la_huella_cambia_con_la_contraseña(self):
        """Es lo que hace que el enlace muera al usarse."""
        assert enlaces.huella(hash_password("una")) != enlaces.huella(hash_password("otra"))


class TestSeLlegaDesdeElLogin:
    def test_el_login_ofrece_recuperar(self, cliente):
        """Un dueño que olvidó la clave está mirando el login, no la
        documentación."""
        assert "/panel/recuperar" in cliente.get("/panel/login").text
