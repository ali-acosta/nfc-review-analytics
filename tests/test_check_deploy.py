"""Revisión previa al despliegue.

Este script existe porque desplegar es donde se juntan los errores chicos y el
usuario lo va a hacer solo, sin nadie que le revise el hombro. Cada cosa que
marca como BLOQUEA es algo que ya salió mal en algún proyecto: la base todavía en
SQLite sobre un disco que se borra, la URL de las placas apuntando a un host
temporal, un cliente con el enlace de Google de relleno.

Lo que se prueba aquí no es que el script corra, sino que **no deje pasar** un
entorno que rompería en producción. Un chequeo que nunca dice que no es peor que
no tener chequeo, porque da confianza sin fundamento.
"""

from scripts import check_deploy


def reporte_de(funcion, **ajustes):
    """Corre una revisión con la configuración cambiada y devuelve sus niveles."""
    import pytest

    r = check_deploy.Reporte()
    with pytest.MonkeyPatch().context() as mp:
        for clave, valor in ajustes.items():
            mp.setattr(check_deploy.settings, clave, valor)
        funcion(r)
    return r


def niveles(r):
    return [nivel for nivel, _, _ in r.items]


def texto(r):
    return " ".join(f"{t} {d}" for _, t, d in r.items)


class TestLaUrlDeLasPlacas:
    """Es lo único verdaderamente irreversible: queda grabada en un chip y pegada
    a una mesa."""

    def test_bloquea_sin_https(self):
        r = reporte_de(check_deploy.revisar_base_url, base_url="http://misresenas.cl")

        assert check_deploy.BLOQUEA in niveles(r)

    def test_bloquea_un_host_temporal_de_hosting(self):
        """Imprimir con esta URL y luego cambiar de hosting mata todas las placas."""
        r = reporte_de(check_deploy.revisar_base_url, base_url="https://algo.onrender.com")

        assert check_deploy.BLOQUEA in niveles(r)

    def test_bloquea_localhost(self):
        r = reporte_de(check_deploy.revisar_base_url, base_url="http://localhost:8000")

        assert check_deploy.BLOQUEA in niveles(r)

    def test_avisa_de_un_puerto_explicito(self):
        r = reporte_de(check_deploy.revisar_base_url, base_url="https://misresenas.cl:8000")

        assert check_deploy.REVISAR in niveles(r)

    def test_acepta_un_dominio_propio(self):
        r = reporte_de(check_deploy.revisar_base_url, base_url="https://misresenas.cl")

        assert niveles(r) == [check_deploy.BIEN]


class TestSecretos:
    def test_bloquea_sin_clave_de_sesion(self):
        """Sin ella, cada reinicio cierra la sesión de todos los clientes."""
        r = reporte_de(
            check_deploy.revisar_secretos, session_secret="", admin_password_hash="scrypt$aa$bb"
        )

        assert check_deploy.BLOQUEA in niveles(r)

    def test_bloquea_si_pusieron_la_contrasena_en_vez_del_hash(self):
        """Un error fácil de cometer y que dejaría la clave en texto plano en el
        panel del hosting."""
        r = reporte_de(
            check_deploy.revisar_secretos,
            session_secret="x" * 40,
            admin_password_hash="mi-contraseña-secreta",
        )

        assert check_deploy.BLOQUEA in niveles(r)

    def test_acepta_una_configuracion_correcta(self):
        r = reporte_de(
            check_deploy.revisar_secretos,
            session_secret="x" * 40,
            admin_password_hash="scrypt$aa$bb",
        )

        assert check_deploy.BLOQUEA not in niveles(r)


class TestCanalesDeAviso:
    def test_bloquea_sin_correo(self):
        """La alerta de queja es la razón principal por la que un cliente paga.
        Sin SMTP, un cliente enojado escribe y el dueño no se entera nunca."""
        r = reporte_de(
            check_deploy.revisar_alertas,
            smtp_host="", smtp_from="", telegram_bot_token="", sentry_dsn="",
        )

        assert check_deploy.BLOQUEA in niveles(r)

    def test_con_correo_configurado_no_bloquea(self):
        r = reporte_de(
            check_deploy.revisar_alertas,
            smtp_host="smtp-relay.brevo.com", smtp_from="avisos@misresenas.cl",
            telegram_bot_token="", sentry_dsn="https://x@y.ingest.sentry.io/1",
        )

        assert check_deploy.BLOQUEA not in niveles(r)

    def test_avisa_si_falta_el_monitoreo_sin_bloquear(self):
        r = reporte_de(
            check_deploy.revisar_alertas,
            smtp_host="smtp.x.cl", smtp_from="a@b.cl", telegram_bot_token="", sentry_dsn="",
        )

        assert check_deploy.REVISAR in niveles(r)
        assert check_deploy.BLOQUEA not in niveles(r)


class TestEstadoDeLosClientes:
    def test_bloquea_un_cliente_con_enlace_de_relleno(self, negocio):
        """Es el fallo más caro y más silencioso: el cliente instala sus placas,
        sus visitantes las tocan, y ninguno llega a dejar una reseña."""
        from app.database import SessionLocal
        from app.models import Business

        with SessionLocal() as db:
            b = db.get(Business, negocio.id)
            b.google_review_url = "https://search.google.com/local/writereview?placeid=REEMPLAZAR"
            b.alert_email = "dueno@local.cl"
            db.commit()

        r = check_deploy.Reporte()
        check_deploy.revisar_clientes(r)

        assert check_deploy.BLOQUEA in niveles(r)
        assert "provisional" in texto(r)

    def test_bloquea_un_cliente_sin_canal_de_aviso(self, negocio):
        from app.database import SessionLocal
        from app.models import Business

        with SessionLocal() as db:
            b = db.get(Business, negocio.id)
            b.google_review_url = "https://g.page/r/CBueno/review"
            b.alert_email = ""
            b.telegram_chat_id = ""
            db.commit()

        r = check_deploy.Reporte()
        check_deploy.revisar_clientes(r)

        assert check_deploy.BLOQUEA in niveles(r)
        assert "sin canal de aviso" in texto(r)

    def test_un_cliente_bien_configurado_pasa(self, negocio):
        from app.database import SessionLocal
        from app.models import Business
        from app.services.auth import hash_password

        with SessionLocal() as db:
            b = db.get(Business, negocio.id)
            b.google_review_url = "https://g.page/r/CBueno/review"
            b.alert_email = "dueno@local.cl"
            b.login_email = "dueno@local.cl"
            b.password_hash = hash_password("algo")
            db.commit()

        r = check_deploy.Reporte()
        check_deploy.revisar_clientes(r)

        assert niveles(r) == [check_deploy.BIEN]


class TestElChequeoSirveParaAutomatizar:
    def test_cuenta_los_bloqueantes(self):
        r = check_deploy.Reporte()
        r.add(check_deploy.BLOQUEA, "uno")
        r.add(check_deploy.REVISAR, "dos")
        r.add(check_deploy.BIEN, "tres")

        assert r.bloqueantes() == 1
