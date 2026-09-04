"""Correo de bienvenida al dar de alta un cliente.

Existe para que **la contraseña nunca se dicte**. Antes, un alta terminaba con el
operador leyéndole una clave por teléfono al dueño, que la anotaba en un papel o
se la mandaba a sí mismo por WhatsApp. Ahora le llega un enlace y la elige él.

Lo que estos tests cuidan: que la clave generada no se le muestre a nadie cuando
el correo salió, que sí se muestre cuando no salió (o el alta quedaría sin salida
y el dueño sin poder entrar), y que el enlace del alta dure lo que tiene que
durar: el dueño no lo pidió, así que puede abrirlo al día siguiente.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Business
from app.services import admin_auth, correos, enlaces
from app.services.auth import hash_password, verify_password

CLAVE_OPERADOR = "clave-de-operador-12345"
CORREO = "duena@local.cl"


@pytest.fixture
def operador(monkeypatch):
    monkeypatch.setattr(
        admin_auth.settings, "admin_password_hash", admin_auth.hash_para_configurar(CLAVE_OPERADOR)
    )
    with TestClient(app) as c:
        c.post("/admin/login", data={"password": CLAVE_OPERADOR}, follow_redirects=False)
        yield c


@pytest.fixture
def buzon(monkeypatch):
    """Reemplaza el envío real y guarda lo que se habría mandado."""
    enviados = []

    async def fake_send(to, subject, body, attachment=None):
        enviados.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(correos.settings, "smtp_host", "smtp.ejemplo.cl")
    monkeypatch.setattr(correos.settings, "smtp_from", "avisos@ejemplo.cl")
    monkeypatch.setattr("app.services.correos.send_email", fake_send)
    return enviados


@pytest.fixture
def sin_smtp(monkeypatch):
    monkeypatch.setattr(correos.settings, "smtp_host", "")


def _alta(operador, email=CORREO, nombre="Panadería Nueva"):
    return operador.post(
        "/admin/nuevo",
        data={
            "nombre": nombre,
            "google_url": "https://g.page/r/CTest123/review",
            "placas": "Mesón",
            "email": email,
        },
    )


def _recien_creado():
    with SessionLocal() as db:
        return db.scalar(select(Business).where(Business.login_email == CORREO))


def _link_del_correo(cuerpo: str) -> str:
    linea = [l for l in cuerpo.splitlines() if "/panel/nueva-clave" in l][0]
    return linea.strip().replace("http://testserver", "")


class TestElAltaAvisaAlDueno:
    def test_le_manda_el_correo(self, operador, buzon):
        _alta(operador)

        assert len(buzon) == 1
        assert buzon[0]["to"] == CORREO
        assert "/panel/nueva-clave?firma=" in buzon[0]["body"]

    def test_el_correo_no_lleva_la_contraseña(self, operador, buzon):
        """El punto entero de esta función: la clave no viaja en texto plano.

        Se comprueba contra la clave que quedó guardada, no contra una constante:
        si alguien mandara la generada, este test la vería aparecer."""
        _alta(operador)
        business = _recien_creado()

        cuerpo = buzon[0]["body"]
        # No hay forma de recuperar la clave en claro desde el hash, así que se
        # verifica al revés: ninguna palabra del correo puede ser la contraseña.
        for palabra in cuerpo.split():
            assert not verify_password(palabra.strip(".,:"), business.password_hash)

    def test_el_enlace_del_correo_deja_entrar(self, operador, buzon):
        _alta(operador)
        ruta = _link_del_correo(buzon[0]["body"])

        with TestClient(app) as dueno:
            assert dueno.get(ruta).status_code == 200
            respuesta = dueno.post(
                "/panel/nueva-clave",
                data={
                    "firma": ruta.split("firma=")[1],
                    "nueva": "la-que-yo-elijo",
                    "repetir": "la-que-yo-elijo",
                },
            )

        assert respuesta.url.path == "/dashboard/"

    def test_no_manda_nada_si_el_cliente_no_tiene_correo(self, operador, buzon):
        _alta(operador, email="")

        assert buzon == []


class TestLaClaveGeneradaNoSeMuestraSiSalioElCorreo:
    def test_la_pantalla_del_alta_no_la_muestra(self, operador, buzon):
        html = _alta(operador).text

        assert "Ya le avisamos al dueño" in html
        assert "Credenciales del dueño" not in html

    def test_sin_smtp_sigue_mostrandola(self, operador, sin_smtp):
        """Sin esto, un alta sin correo saliente dejaría al dueño sin forma de
        entrar y al operador sin nada que entregarle."""
        html = _alta(operador).text

        assert "Credenciales del dueño" in html
        assert "Ya le avisamos" not in html

    def test_la_cuenta_nunca_queda_sin_contraseña(self, operador, buzon):
        """Aunque la clave generada no se muestre, tiene que existir: una cuenta
        con el hash vacío es una cuenta en la que no hace falta contraseña."""
        _alta(operador)

        assert _recien_creado().password_hash.startswith("scrypt$")


class TestElEnlaceDelAltaDuraMasQueElDeRecuperacion:
    """No es el mismo plazo porque no es la misma situación: la recuperación la
    pidió el dueño hace un minuto; el alta le llega sin avisar y puede abrirla al
    día siguiente. Con una hora, el alta llegaría muerta más veces que útil."""

    def test_una_semana_contra_una_hora(self):
        assert enlaces.VIGENCIA_BIENVENIDA == 7 * 24 * 60 * 60
        assert enlaces.VIGENCIA_BIENVENIDA > enlaces.VIGENCIA_CLAVE

    def test_el_enlace_del_alta_sobrevive_a_la_hora_de_la_recuperacion(
        self, negocio, cliente, monkeypatch
    ):
        with SessionLocal() as db:
            business = db.get(Business, negocio.id)
            business.login_email = CORREO
            business.password_hash = hash_password("una-clave-cualquiera")
            db.commit()
            firma = enlaces.firmar_bienvenida(business.id, business.password_hash)

        # Se vence el plazo de la recuperación; el del alta no.
        monkeypatch.setattr(enlaces, "VIGENCIA_CLAVE", -1)

        assert cliente.get(f"/panel/nueva-clave?firma={firma}").status_code == 200

    def test_vencido_tambien_caduca(self, negocio, cliente, monkeypatch):
        with SessionLocal() as db:
            business = db.get(Business, negocio.id)
            business.password_hash = hash_password("una-clave-cualquiera")
            db.commit()
            firma = enlaces.firmar_bienvenida(business.id, business.password_hash)

        monkeypatch.setattr(enlaces, "VIGENCIA_BIENVENIDA", -1)

        assert cliente.get(f"/panel/nueva-clave?firma={firma}").status_code == 403


class TestLaCLIHaceLoMismo:
    def test_da_de_alta_y_avisa(self, buzon, capsys):
        from scripts.new_client import crear

        crear("Café CLI", "https://g.page/r/CTest123/review", ["Mesa 1"], "", CORREO)

        salida = capsys.readouterr().out
        assert len(buzon) == 1
        assert "Le mandamos el correo de bienvenida" in salida
        assert "Clave:" not in salida, "no debería dictarse ninguna contraseña"

    def test_sin_smtp_imprime_la_clave(self, sin_smtp, capsys):
        from scripts.new_client import crear

        crear("Café CLI", "https://g.page/r/CTest123/review", ["Mesa 1"], "", CORREO)

        assert "Clave:" in capsys.readouterr().out
