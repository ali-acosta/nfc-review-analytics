"""La alerta de queja es la principal razón por la que un cliente sigue pagando.
Si sale por un canal que el dueño no revisa, es como no mandarla."""

import asyncio

from app.database import SessionLocal
from app.models import Business
from app.services import email as email_service
from app.services import notify as notify_service


def _negocio(**kwargs) -> Business:
    return Business(name="Café", google_review_url="https://g.page/r/CX/review", **kwargs)


class TestElegirCanal:
    def test_sin_canales_no_pretende_haber_avisado(self):
        assert asyncio.run(notify_service.notify(_negocio(), "asunto", "cuerpo")) is False

    def test_usa_solo_el_canal_configurado(self, monkeypatch):
        llamadas = []

        async def falso_telegram(chat, texto):
            llamadas.append(("telegram", chat))
            return True

        async def falso_correo(destino, asunto, cuerpo, adjunto=None):
            llamadas.append(("correo", destino))
            return True

        monkeypatch.setattr(notify_service, "send_message", falso_telegram)
        monkeypatch.setattr(notify_service, "send_email", falso_correo)

        asyncio.run(notify_service.notify(_negocio(alert_email="due@o.cl"), "a", "b"))

        assert llamadas == [("correo", "due@o.cl")]

    def test_con_ambos_avisa_por_los_dos(self, monkeypatch):
        llamadas = []

        async def falso_telegram(chat, texto):
            llamadas.append("telegram")
            return True

        async def falso_correo(destino, asunto, cuerpo, adjunto=None):
            llamadas.append("correo")
            return True

        monkeypatch.setattr(notify_service, "send_message", falso_telegram)
        monkeypatch.setattr(notify_service, "send_email", falso_correo)

        negocio = _negocio(telegram_chat_id="123", alert_email="due@o.cl")
        assert asyncio.run(notify_service.notify(negocio, "a", "b")) is True
        assert sorted(llamadas) == ["correo", "telegram"]

    def test_si_un_canal_falla_el_otro_igual_entrega(self, monkeypatch):
        async def telegram_roto(chat, texto):
            raise RuntimeError("Telegram caído")

        async def correo_ok(destino, asunto, cuerpo, adjunto=None):
            return True

        monkeypatch.setattr(notify_service, "send_message", telegram_roto)
        monkeypatch.setattr(notify_service, "send_email", correo_ok)

        negocio = _negocio(telegram_chat_id="123", alert_email="due@o.cl")

        assert asyncio.run(notify_service.notify(negocio, "a", "b")) is True

    def test_si_todos_fallan_lo_reporta(self, monkeypatch):
        async def roto(*_a, **_k):
            raise RuntimeError("caído")

        monkeypatch.setattr(notify_service, "send_message", roto)
        monkeypatch.setattr(notify_service, "send_email", roto)

        negocio = _negocio(telegram_chat_id="123", alert_email="due@o.cl")

        assert asyncio.run(notify_service.notify(negocio, "a", "b")) is False


class TestCorreo:
    def test_sin_smtp_no_intenta_enviar(self, monkeypatch):
        monkeypatch.setattr(email_service.settings, "smtp_host", "")

        assert asyncio.run(email_service.send_email("a@b.cl", "asunto", "cuerpo")) is False

    def test_sin_destinatario_no_intenta_enviar(self, monkeypatch):
        monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.brevo.com")
        monkeypatch.setattr(email_service.settings, "smtp_from", "avisos@reseñas.cl")

        assert asyncio.run(email_service.send_email("", "asunto", "cuerpo")) is False

    def test_un_smtp_caido_no_propaga(self, monkeypatch):
        monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.inexistente.cl")
        monkeypatch.setattr(email_service.settings, "smtp_from", "avisos@reseñas.cl")

        def explota(*_a, **_k):
            raise OSError("no se pudo conectar")

        monkeypatch.setattr(email_service.smtplib, "SMTP", explota)

        assert asyncio.run(email_service.send_email("a@b.cl", "asunto", "cuerpo")) is False

    def test_arma_el_mensaje_con_remitente_asunto_y_destino(self, monkeypatch):
        monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.brevo.com")
        monkeypatch.setattr(email_service.settings, "smtp_from", "avisos@resenas.cl")
        monkeypatch.setattr(email_service.settings, "smtp_user", "")
        enviados = []

        class FakeSMTP:
            def __init__(self, *_a, **_k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def starttls(self):
                pass

            def send_message(self, msg):
                enviados.append(msg)

        monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)

        ok = asyncio.run(email_service.send_email("dueno@local.cl", "Nueva queja", "La espera fue larga"))

        assert ok is True
        mensaje = enviados[0]
        assert mensaje["To"] == "dueno@local.cl"
        assert mensaje["From"] == "avisos@resenas.cl"
        assert mensaje["Subject"] == "Nueva queja"
        assert "La espera fue larga" in mensaje.get_content()


class TestIntegracionConElFlujo:
    def test_la_queja_avisa_por_el_canal_del_negocio(self, negocio, visitante, monkeypatch):
        avisos = []

        async def espia(business, asunto, cuerpo):
            avisos.append((business.name, asunto, cuerpo))
            return True

        monkeypatch.setattr("app.routers.redirect.notify", espia)

        with SessionLocal() as db:
            db.get(Business, negocio.id).alert_email = "dueno@local.cl"
            db.commit()

        telefono = visitante()
        telefono.get(f"/r/{negocio.mesa}")
        telefono.post(f"/r/{negocio.mesa}/feedback", data={"rating": "2", "message": "Muy lento"})

        assert len(avisos) == 1
        _, asunto, cuerpo = avisos[0]
        assert negocio.nombre in asunto
        assert "Muy lento" in cuerpo
        assert "Mesa 1" in cuerpo
